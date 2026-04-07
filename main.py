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
import sys

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

# ---------------- LOGS ----------------
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("main")

# ---------------- VARIABLES ----------------
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

            logger.info(f"🔎 Revisando servicios... encontrados: {len(servicios)}")
            return servicios

        except Exception as e:
            logger.error(f"Error obteniendo servicios nuevos: {e}")
            return {}

    def obtener_servicios_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")

            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}

            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())

            return servicios

        except Exception as e:
            logger.error(f"Error obteniendo servicios en curso: {e}")
            return {}

    def cambiar_estado(self, servicio_id, codigo_estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            fecha_str = fecha.strftime("%d/%m/%Y")

            obs = "Pendiente de localizar a asegurado" if codigo_estado == "348" else "En espera de Profesional por confirmación del Siniestro"

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "Pag": "1",
                "ESTADO": codigo_estado,
                "FECSIG": fecha_str,
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            r = self.session.post(BASE_URL, data=payload, timeout=10)

            if "estado actual de la reparacion" in r.text.lower() or "Pendiente" in r.text:
                return True, f"✅ Estado {codigo_estado} aplicado correctamente"
            else:
                return False, "⚠️ Revisar HTML manualmente"

        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Iniciando loop de servicios...")
    
    if not homeserve.login():
        logger.error("❌ No se pudo iniciar sesión")

    while True:
        try:
            logger.info("⏱ Ejecutando revisión...")

            actuales = homeserve.obtener_servicios_nuevos()

            if not actuales:
                logger.info("⚠️ No hay servicios disponibles")

            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 Nuevo servicio detectado: {idserv}")
                    enviar(
                        CHAT_ID,
                        f"🆕 <b>Nuevo servicio</b>\n\n{servicio}",
                        botones_servicio_nuevo(idserv)
                    )

            SERVICIOS_ACTUALES = actuales

            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"💥 Error en loop: {e}")
            time.sleep(20)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

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

        elif accion == "WEB":
            actuales = homeserve.obtener_servicios_nuevos()
            txt = "\n\n".join(actuales.values()) if actuales else "No hay servicios"
            enviar(chat, txt)

        elif accion == "CAMBIAR_ESTADO":
            curso = homeserve.obtener_servicios_curso()
            for sid in curso:
                enviar(chat, f"🔧 Servicio {sid}", botones_estado(sid))

        elif accion.startswith("ESTADO_"):
            parts = accion.split("_")
            sid, estado = parts[1], parts[2]
            ok, msg = homeserve.cambiar_estado(sid, estado)
            enviar(chat, f"Servicio {sid}:\n{msg}")

        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            SERVICIOS_ESTADO[sid] = "ACEPTADO"
            enviar(chat, f"✅ Servicio {sid} aceptado")

        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            SERVICIOS_ESTADO[sid] = "RECHAZADO"
            enviar(chat, f"❌ Servicio {sid} rechazado")

    return jsonify(ok=True)

# ---------------- INICIO (CLAVE PARA RAILWAY) ----------------
threading.Thread(target=bot_loop).start()
logger.info("🚀 Bot y loop iniciados correctamente")

# ---------------- LOCAL ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
