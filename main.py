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
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}
SERVICIOS_ESTADO = {}

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
    return {"inline_keyboard": [[{"text": "🔐 Login", "callback_data": "LOGIN"},
                                 {"text": "🔄 Refresh", "callback_data": "REFRESH"}]]}

def botones_servicio_nuevo(servicio_id):
    return {"inline_keyboard": [[{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
                                 {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}]]}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        try:
            logger.info("Intentando login...")
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
            logger.info("Obteniendo servicios desde Asignación...")
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
            logger.info(f"Servicios detectados: {len(servicios)}")
            if len(servicios) == 0:
                logger.info("No se encontraron servicios nuevos.")
            return servicios
        except Exception as e:
            logger.error(f"Error obteniendo servicios nuevos: {e}")
            return {}

homeserve = HomeServe()

# ---------------- LOOP ALERTAS ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    if not homeserve.login():
        logger.error("No se pudo iniciar sesión al arrancar el bot")
    while True:
        try:
            logger.info("=== Iniciando iteración del loop ===")
            actuales = homeserve.obtener_servicios_nuevos()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    logger.info(f"Nuevo servicio detectado: {idserv}")
                    enviar(CHAT_ID, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}", botones_servicio_nuevo(idserv))
            if len(actuales) == 0:
                logger.info("Actualmente no hay servicios en asignación.")
            SERVICIOS_ACTUALES = actuales
            logger.info("=== Iteración del loop finalizada ===\n")
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Error en loop: {e}")
            homeserve.login()
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
        elif accion == "REFRESH":
            homeserve.obtener_servicios_nuevos()
            enviar(chat, "🔄 Actualizado")

    return jsonify(ok=True)

# ---------------- INICIO ----------------
if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    logger.info("Bot arrancado correctamente")
    app.run(host="0.0.0.0", port=10000)
