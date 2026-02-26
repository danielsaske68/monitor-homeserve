import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")  # https://tuservicio.onrender.com
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}
CHAT_IDS = set()

app = Flask(__name__)

# ---------------------------------------------------
# CLASE HOMESERVE
# ---------------------------------------------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        self.session.get(LOGIN_URL)
        r = self.session.post(LOGIN_URL, data=payload)
        if "error" in r.text.lower():
            logger.error("Login fallo")
            return False
        logger.info("Login OK")
        return True

    def obtener(self):
        r = self.session.get(ASIGNACION_URL, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        texto = soup.get_text("\n")
        bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
        servicios = {}
        for b in bloques:
            m = re.search(r"\b\d{7,8}\b", b)
            if m:
                idserv = m.group(0)
                limpio = " ".join(b.split())
                servicios[idserv] = limpio
        logger.info(f"Servicios detectados: {len(servicios)}")
        return servicios

homeserve = HomeServe()

# ---------------------------------------------------
# TELEGRAM FUNCIONES
# ---------------------------------------------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Actualizar", "callback_data": "REFRESH"}],
            [{"text": "📋 Ver servicios guardados", "callback_data": "GUARDADOS"}],
            [{"text": "🌐 Ver servicios WEB", "callback_data": "WEB"}],
            [{"text": "🌐 Ir asignación", "url": ASIGNACION_URL}]
        ]
    }

def enviar(chat, texto):
    try:
        r = requests.post(
            TELEGRAM_API + "/sendMessage",
            json={"chat_id": chat, "text": texto, "parse_mode": "HTML", "reply_markup": botones()},
            timeout=10
        )
        logger.info(f"Enviado a {chat}: {texto[:50]}...")
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")

def set_webhook():
    webhook_url = f"{BASE_URL}/telegram_webhook"
    r = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url})
    if r.ok:
        logger.info(f"Webhook registrado: {webhook_url}")
    else:
        logger.error(f"Error registrando webhook: {r.text}")

# ---------------------------------------------------
# LOOP HOME SERVE
# ---------------------------------------------------
def bot_loop():
    global SERVICIOS_ACTUALES
    if not homeserve.login():
        logger.error("Login inicial fallido")
    while True:
        try:
            actuales = homeserve.obtener()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    for chat in CHAT_IDS:
                        enviar(chat, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Error en loop: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------------------------------------------
# FLASK RUTAS
# ---------------------------------------------------
@app.route("/")
def home():
    return f"Monitor OK - Servicios guardados: {len(SERVICIOS_ACTUALES)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    logger.info(f"Webhook recibido: {data}")

    # /start
    if "message" in data and "text" in data["message"]:
        chat = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        CHAT_IDS.add(chat)
        if text == "/start":
            enviar(chat, "¡Bot activo! Usa los botones para interactuar.")

    # botones
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]
        CHAT_IDS.add(chat)
        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Login error")
        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            enviar(chat, "🔄 Actualizado")
        elif accion == "GUARDADOS":
            txt = "📋 <b>Servicios guardados</b>\n\n"
            for s in SERVICIOS_ACTUALES.values():
                txt += s + "\n\n"
            enviar(chat, txt if SERVICIOS_ACTUALES else "No hay servicios guardados")
        elif accion == "WEB":
            actuales = homeserve.obtener()
            txt = "🌐 <b>Servicios en la WEB</b>\n\n"
            for s in actuales.values():
                txt += s + "\n\n"
            enviar(chat, txt if actuales else "No hay servicios en web")

    return jsonify(ok=True)

# ---------------------------------------------------
# THREAD HOME SERVE
# ---------------------------------------------------
threading.Thread(target=bot_loop, daemon=True).start()

# ---------------------------------------------------
# RUN
# ---------------------------------------------------
if __name__ == "__main__":
    set_webhook()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
