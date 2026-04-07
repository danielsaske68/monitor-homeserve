import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# ---------------- VARIABLES GLOBALES ----------------
SERVICIOS_ACTUALES = {}
SERVICIOS_ESTADO = {}

# ---------------- FLASK ----------------
app = Flask(__name__)

# ---------------- TELEGRAM ----------------
def enviar(chat, texto, botones=None):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones
    try:
        requests.post(TELEGRAM_API + "/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")

def botones_generales():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}]
        ]
    }

def botones_estado(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "348 - Pendiente de cliente", "callback_data": f"ESTADO_{servicio_id}_348"},
             {"text": "318 - En espera profesional", "callback_data": f"ESTADO_{servicio_id}_318"}]
        ]
    }

def botones_servicio_nuevo(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
             {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}]
        ]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallo")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def obtener_servicios_nuevos(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=10)
            r.encoding = "latin-1"
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    idserv = m.group(0)
                    limpio = " ".join(b.split())
                    servicios[idserv] = limpio
            return servicios
        except Exception as e:
            logger.error(f"Error obteniendo servicios nuevos: {e}")
            return {}

homeserve = HomeServe()

# ---------------- LOOP ALERTAS ----------------
def bot_loop():
    homeserve.login()
    while True:
        try:
            actuales = homeserve.obtener_servicios_nuevos()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    enviar(CHAT_ID, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}", botones_servicio_nuevo(idserv))
            global SERVICIOS_ACTUALES
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Error en loop: {e}")
            time.sleep(20)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    chat = None

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Bot activo correctamente", botones_generales())
            return jsonify(ok=True)

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Login fallo")

    return jsonify(ok=True)

# ---------------- INICIO ----------------
# Lanzar loop de alertas en un hilo antes de Gunicorn
threading.Thread(target=bot_loop, daemon=True).start()
logger.info("Bot loop arrancado correctamente")

# Flask app seguirá siendo usada por Gunicorn
