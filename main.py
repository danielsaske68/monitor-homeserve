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

# ---------------- CONFIG ----------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # Chat ID de prueba
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}

# ---------------- TELEGRAM ----------------

def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "📋 Ver servicios guardados", "callback_data": "GUARDADOS"}],
            [{"text": "🌐 Ver servicios WEB", "callback_data": "WEB"}],
            [{"text": "🌐 Ir asignación", "url": ASIGNACION_URL}]
        ]
    }

def enviar(chat, texto):
    try:
        requests.post(
            TELEGRAM_API + "/sendMessage",
            json={
                "chat_id": chat,
                "text": texto,
                "parse_mode": "HTML",
                "reply_markup": botones()
            },
            timeout=10
        )
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

# ---------------- HOMESERVE ----------------

class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {
            "CODIGO": USUARIO,
            "PASSW": PASSWORD,
            "BTN": "Aceptar"
        }
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

# ---------------- LOOP AUTOMÁTICO ----------------

def bot_loop():
    global SERVICIOS_ACTUALES
    if not homeserve.login():
        logger.error("No se pudo iniciar sesión al arrancar el bot")
    while True:
        try:
            actuales = homeserve.obtener()
            # Detectar nuevos
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    enviar(CHAT_ID, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Error loop: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return f"HomeServe Monitor OK - Servicios guardados: {len(SERVICIOS_ACTUALES)}"

# ---------------- TELEGRAM WEBHOOK ----------------

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    # Botones
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Ando ready mi rey" if ok else "❌ Pailas mi rey tamos en fallo")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            enviar(chat, "🔄😏 Actualizado Mi sensei")

        elif accion == "GUARDADOS":
            if SERVICIOS_ACTUALES:
                txt = "📋 <b>Servicio almacenado</b>\n\n"
                for s in SERVICIOS_ACTUALES.values():
                    txt += s + "\n\n"
            else:
                txt = "🫤Andamos pailas"
            enviar(chat, txt)

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if actuales:
                txt = "🌐 <b>😎Mi lideeeel encontre algo</b>\n\n"
                for s in actuales.values():
                    txt += s + "\n\n"
            else:
                txt = "🫤Andamos repailas "
            enviar(chat, txt)

    # Comando /start
    elif "message" in data and "text" in data["message"]:
        chat = data["message"]["chat"]["id"]
        texto = data["message"]["text"]
        if texto == "/start":
            enviar(chat, "👋 ¡Bot activo! Usa los botones para interactuar.")

    return jsonify(ok=True)

# ---------------- THREAD ----------------

threading.Thread(target=bot_loop, daemon=True).start()

# ---------------- RUN ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
