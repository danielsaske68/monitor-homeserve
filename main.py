import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ---------------- CARGA DE VARIABLES ----------------
load_dotenv()

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

# ---------------- TELEGRAM ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Ver servicios WEB", "callback_data": "WEB"}],
            [{"text": "🔁 Cambiar estado servicios", "callback_data": "CAMBIAR_ESTADO"}]
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
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        try:
            self.session.get(LOGIN_URL, timeout=15)
            r = self.session.post(LOGIN_URL, data=payload, timeout=15)
            if "error" in r.text.lower():
                logger.error("Login fallo")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error en login: {e}")
            return False

    def obtener(self):
        """Servicios nuevos para alertas"""
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
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
            return servicios
        except Exception as e:
            logger.error(f"Error al obtener servicios: {e}")
            return {}

    def obtener_servicios_curso(self):
        """Servicios para cambiar estado"""
        try:
            url = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
            r = self.session.get(url, timeout=15)
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
            logger.info(f"Servicios en curso detectados: {len(servicios)}")
            return servicios
        except Exception as e:
            logger.error(f"Error al obtener servicios en curso: {e}")
            return {}

    def cambiar_estado(self, servicio_id):
        """Cambia el estado exactamente como el script manual"""
        try:
            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "Pag": "1",
                "ESTADO": "348",
                "FECSIG": "10/04/2026",
                "INFORMO": "on",
                "Observaciones": "En espera de cliente por localizar",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }
            r = self.session.post(BASE_URL, data=payload, timeout=15)
            if "estado actual de la reparacion" in r.text.lower():
                logger.info(f"Cambio de estado exitoso para {servicio_id}")
                return True, "✅ Cambio de estado posible éxito"
            elif "illegal command" in r.text.lower():
                logger.warning(f"Error ilegal comando para {servicio_id}")
                return False, "❌ Error: comando ilegal"
            else:
                logger.warning(f"HTML inesperado para {servicio_id}")
                return None, "⚠️ Revisar HTML manualmente"
        except Exception as e:
            logger.error(f"Error cambiando estado {servicio_id}: {e}")
            return False, f"❌ Error en request: {e}"

homeserve = HomeServe()

# ---------------- LOOP AUTOMÁTICO ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    logger.info("Iniciando loop automático de alertas...")
    if not homeserve.login():
        logger.error("No se pudo iniciar sesión al arrancar el bot")
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
    return f"HomeServe Monitor OK - Servicios guardados: {len(SERVICIOS_ACTUALES)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "CAMBIAR_ESTADO":
            servicios = homeserve.obtener_servicios_curso()
            if not servicios:
                enviar(chat, "No se encontraron servicios en curso.")
            else:
                keyboard = {"inline_keyboard": []}
                for sid, stext in servicios.items():
                    keyboard["inline_keyboard"].append([{"text": f"{sid}", "callback_data": f"CAMB_EST_{sid}"}])
                requests.post(
                    TELEGRAM_API + "/sendMessage",
                    json={"chat_id": chat, "text": "Selecciona un servicio para cambiar estado:", "reply_markup": keyboard}
                )

        elif accion.startswith("CAMB_EST_"):
            servicio_id = accion.replace("CAMB_EST_", "")
            exito, mensaje = homeserve.cambiar_estado(servicio_id)
            enviar(chat, f"Servicio {servicio_id}:\n{mensaje}")

        elif accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Ando ready mi rey" if ok else "❌ Pailas mi rey tamos en fallo")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            enviar(chat, "🔄 Actualizado Mi sensei")

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if actuales:
                txt = "🌐 <b>Mi lideeeel encontre algo</b>\n\n"
                for s in actuales.values():
                    txt += s + "\n\n"
            else:
                txt = "Andamos repailas "
            enviar(chat, txt)

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
    logger.info("Arrancando Flask...")
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Usando puerto: {port}")
    app.run(host="0.0.0.0", port=port)
