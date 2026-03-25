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
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 60))

if not all([USUARIO, PASSWORD, BOT_TOKEN, CHAT_ID]):
    raise ValueError("Faltan variables de entorno")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS"
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
        logger.error(f"Error enviando mensaje: {e}")

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
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login falló")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener(self):
        try:
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
        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return {}

homeserve = HomeServe()

# ---------------- LOOP ----------------

def bot_loop():
    global SERVICIOS_ACTUALES

    if not homeserve.login():
        logger.error("No se pudo iniciar sesión al arrancar")

    while True:
        try:
            actuales = homeserve.obtener()

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
    return f"OK - Servicios: {len(SERVICIOS_ACTUALES)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            enviar(chat, "🔄 Actualizado")

        elif accion == "GUARDADOS":
            if SERVICIOS_ACTUALES:
                txt = "📋 <b>Servicios</b>\n\n"
                for s in SERVICIOS_ACTUALES.values():
                    txt += s + "\n\n"
            else:
                txt = "Sin datos"
            enviar(chat, txt)

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if actuales:
                txt = "🌐 <b>Web</b>\n\n"
                for s in actuales.values():
                    txt += s + "\n\n"
            else:
                txt = "Nada encontrado"
            enviar(chat, txt)

    elif "message" in data and "text" in data["message"]:
        chat = data["message"]["chat"]["id"]
        if data["message"]["text"] == "/start":
            enviar(chat, "👋 Bot activo")

    return jsonify(ok=True)

# ---------------- THREAD SAFE ----------------

if os.environ.get("RAILWAY_ENVIRONMENT"):
    threading.Thread(target=bot_loop, daemon=True).start()

# ---------------- RUN ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
