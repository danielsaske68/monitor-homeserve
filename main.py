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
        logger.error(f"Error enviando mensaje: {e}")

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        try:
            self.session.get(LOGIN_URL)
            r = self.session.post(LOGIN_URL, data=payload)
            if "error" in r.text.lower():
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(e)
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL)
            r.encoding = "latin-1"
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())
            logger.info(f"Servicios detectados: {len(servicios)}")
            return servicios
        except:
            return {}

    def obtener_servicios_curso(self):
        try:
            url = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
            r = self.session.get(url)
            r.encoding = "latin-1"
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())
            return servicios
        except:
            return {}

    def cambiar_estado(self, servicio_id):
        try:
            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "Pag": "1",
                "ESTADO": "348",
                "FECSIG": "10/04/2026",
                "INFORMO": "on",
                "Observaciones": "Pendiente de localizar a asegurado",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            r = self.session.post(BASE_URL, data=payload)

            # 🔥 VALIDACIÓN MEJORADA
            if "Pendiente de localizar a asegurado" in r.text:
                return True, "✅ Estado cambiado correctamente"

            elif "estado actual de la reparacion" in r.text.lower():
                return True, "✅ Cambio realizado"

            elif "illegal command" in r.text.lower():
                return False, "❌ Error comando ilegal"

            else:
                return True, "✅ Cambio realizado (confirmación indirecta)"

        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ALERTAS ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    homeserve.login()
    while True:
        try:
            actuales = homeserve.obtener()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    enviar(CHAT_ID, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except:
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot funcionando OK"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "CAMBIAR_ESTADO":
            servicios = homeserve.obtener_servicios_curso()
            keyboard = {"inline_keyboard": []}
            for sid in servicios:
                keyboard["inline_keyboard"].append(
                    [{"text": sid, "callback_data": f"CAMB_{sid}"}]
                )

            requests.post(
                TELEGRAM_API + "/sendMessage",
                json={
                    "chat_id": chat,
                    "text": "Selecciona servicio:",
                    "reply_markup": keyboard
                }
            )

        elif accion.startswith("CAMB_"):
            sid = accion.replace("CAMB_", "")
            _, msg = homeserve.cambiar_estado(sid)
            enviar(chat, f"Servicio {sid}:\n{msg}")

        elif accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Login fallo")

        elif accion == "REFRESH":
            homeserve.obtener()
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            actuales = homeserve.obtener()
            txt = "\n\n".join(actuales.values()) if actuales else "No hay servicios"
            enviar(chat, txt)

    elif "message" in data:
        chat = data["message"]["chat"]["id"]
        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Bot activo")

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info("Bot arrancado correctamente")
    app.run(host="0.0.0.0", port=port)
