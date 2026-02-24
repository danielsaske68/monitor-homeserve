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

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}

###########################################################
# TELEGRAM
###########################################################

class Telegram:
    def enviar(self, texto):
        botones = {
            "inline_keyboard": [
                [
                    {"text": "🔐 Login", "callback_data": "LOGIN"},
                    {"text": "🔄 Refrescar (solo memoria)", "callback_data": "REFRESH"}
                ],
                [
                    {"text": "🆕 Servicios nuevos", "callback_data": "SERVICIOS_NUEVOS"},
                    {"text": "📋 Todos los servicios", "callback_data": "TODOS_SERVICIOS"}
                ],
                [
                    {"text": "🌐 Ir asignación", "url": ASIGNACION_URL}
                ]
            ]
        }

        requests.post(
            TELEGRAM_API + "/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": texto,
                "parse_mode": "HTML",
                "reply_markup": botones
            },
            timeout=10
        )

telegram = Telegram()

###########################################################
# HOMESERVE
###########################################################

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

###########################################################
# LOOP DE NOTIFICACIÓN NUEVOS SERVICIOS
###########################################################

def bot_loop():
    global SERVICIOS_ACTUALES
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    telegram.enviar(f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(e)
            homeserve.login()
            time.sleep(20)

###########################################################
# FLASK
###########################################################

app = Flask(__name__)

@app.route("/")
def home():
    return f"HomeServe Monitor OK\nServicios actuales: {len(SERVICIOS_ACTUALES)}"

###########################################################
# TELEGRAM BUTTONS
###########################################################

def format_servicios(servicios_dict, titulo):
    """Formatea los servicios con separación visual"""
    if not servicios_dict:
        return "No hay servicios"
    texto = f"{titulo}\n\n"
    for s in servicios_dict.values():
        texto += f"📌 {s}\n" + "──────────────\n"
    return texto

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            txt = "✅ Login OK" if ok else "❌ Login error"

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            txt = "🔄 Memoria actualizada"

        elif accion == "SERVICIOS_NUEVOS":
            nuevos = {k:v for k,v in homeserve.obtener().items() if k not in SERVICIOS_ACTUALES}
            txt = format_servicios(nuevos, "🆕 Servicios nuevos")
            SERVICIOS_ACTUALES.update(nuevos)

        elif accion == "TODOS_SERVICIOS":
            todos = homeserve.obtener()
            txt = format_servicios(todos, "📋 Todos los servicios activos")

        requests.post(
            TELEGRAM_API + "/sendMessage",
            json={
                "chat_id": chat,
                "text": txt,
                "parse_mode": "HTML"
            }
        )

    return jsonify(ok=True)

###########################################################
# THREAD
###########################################################

threading.Thread(target=bot_loop, daemon=True).start()

###########################################################
# RUN
###########################################################

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
