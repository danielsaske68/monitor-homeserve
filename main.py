import os
import time
import threading
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

# ------------------------------
# Configuración
# ------------------------------
load_dotenv()

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO_SEGUNDOS = int(os.getenv("INTERVALO_SEGUNDOS", 120))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ------------------------------
# Logging
# ------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ------------------------------
# Variables compartidas para web
# ------------------------------
SERVICIOS_ACTUALES = set()
ULTIMO_SERVICIO = None

# ------------------------------
# Telegram Client
# ------------------------------
class TelegramClient:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def enviar_mensaje(self, mensaje, buttons=None):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if buttons:
            data["reply_markup"] = {"inline_keyboard": buttons}
        try:
            r = requests.post(url, json=data, timeout=10)
            r.raise_for_status()
            logger.info("Mensaje enviado a Telegram")
            return True
        except Exception as e:
            logger.error(f"Error enviando Telegram: {e}")
            return False

# ------------------------------
# HomeServe Scraper
# ------------------------------
class HomeServeScraper:
    def __init__(self, usuario, password):
        self.usuario = usuario
        self.password = password
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": self.usuario, "PASSW": self.password, "BTN": "Aceptar"}
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            self.session.get(LOGIN_URL, headers=headers)
            r = self.session.post(LOGIN_URL, data=payload, headers=headers, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallido")
                return False
            logger.info("Login exitoso")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener_servicios(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            servicios = set()
            for fila in soup.find_all("tr"):
                t = fila.get_text(strip=True)
                if t and len(t) > 30:
                    servicios.add(t)
            return servicios
        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return set()

# ------------------------------
# HomeServe Bot
# ------------------------------
class HomeServeBot:
    def __init__(self, scraper, telegram, intervalo):
        self.scraper = scraper
        self.telegram = telegram
        self.intervalo = intervalo
        self.servicios_previos = None

    def iniciar(self):
        global SERVICIOS_ACTUALES, ULTIMO_SERVICIO
        if not self.scraper.login():
            logger.error("No se pudo conectar a HomeServe")
            return

        try:
            while True:
                actuales = self.scraper.obtener_servicios()
                
                # Enviar todos los servicios actuales al inicio
                if self.servicios_previos is None:
                    self.servicios_previos = actuales
                    if actuales:
                        todos = "\n\n".join(actuales)
                        buttons = [
                            [
                                {"text": "🔑 Login", "url": LOGIN_URL},
                                {"text": "📋 Asignación", "url": ASIGNACION_URL}
                            ],
                            [
                                {"text": "🔄 Actualizar servicios", "callback_data": "REFRESH"}
                            ]
                        ]
                        self.telegram.enviar_mensaje(f"📋 <b>Servicios actuales:</b>\n\n{todos}", buttons=buttons)

                # Detectar nuevos servicios
                nuevos = actuales - self.servicios_previos if self.servicios_previos else set()
                if nuevos:
                    for s in nuevos:
                        self.telegram.enviar_mensaje(f"🆕 <b>Nuevo servicio asignado:</b>\n\n{s}")
                        ULTIMO_SERVICIO = s

                SERVICIOS_ACTUALES = actuales
                self.servicios_previos = actuales
                time.sleep(self.intervalo)

        except Exception as e:
            logger.error(f"Error en loop principal: {e}")
            time.sleep(30)

# ------------------------------
# Flask server
# ------------------------------
app = Flask(__name__)

HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
    <title>HomeServe Bot</title>
</head>
<body>
    <h1>HomeServe Bot</h1>
    <p>Servicios actuales: {{ cantidad }}</p>
    <p>Último servicio detectado: {{ ultimo or 'Ninguno aún' }}</p>
    <form method="get">
        <button type="submit">Actualizar</button>
    </form>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(
        HTML_TEMPLATE,
        cantidad=len(SERVICIOS_ACTUALES),
        ultimo=ULTIMO_SERVICIO
    )

# Endpoint para Telegram buttons
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    if "callback_query" in data:
        cb = data["callback_query"]
        if cb["data"] == "REFRESH":
            servicios = "\n\n".join(SERVICIOS_ACTUALES) or "Ninguno"
            chat_id = cb["message"]["chat"]["id"]
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": f"🔄 <b>Servicios actuales:</b>\n\n{servicios}",
                "parse_mode": "HTML"
            })
    return jsonify({"ok": True})

# ------------------------------
# Iniciar bot en segundo plano
# ------------------------------
def iniciar_bot_thread():
    scraper = HomeServeScraper(USUARIO, PASSWORD)
    telegram = TelegramClient(BOT_TOKEN, CHAT_ID)
    bot = HomeServeBot(scraper, telegram, INTERVALO_SEGUNDOS)
    bot.iniciar()

threading.Thread(target=iniciar_bot_thread, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
