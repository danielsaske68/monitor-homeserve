import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# ---------------- CONFIG ----------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 60))

if not all([USUARIO, PASSWORD, BOT_TOKEN, CHAT_ID]):
    raise ValueError("Faltan variables de entorno")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
CAMBIO_ESTADO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# ---------------- VARIABLES GLOBALES ----------------
SERVICIOS_NUEVOS = {}
SERVICIOS_CURSO = {}
SERVICIOS_ESTADO = {}

# ---------------- BOTONES ----------------
def botones_generales():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}]
        ]
    }

def enviar(chat, texto):
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones_generales()
        }
    )

def enviar_servicio(chat, servicio_id, texto):
    botones = {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}
            ],
            [{"text": "🔄 Refresh", "callback_data": "REFRESH"}]
        ]
    }
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones
        }
    )

def enviar_estado_servicio(chat, servicio_id, texto):
    botones = {
        "inline_keyboard": [
            [
                {"text": "🟡 En progreso", "callback_data": f"ESTADO_{servicio_id}_307"},
                {"text": "✅ Finalizado", "callback_data": f"ESTADO_{servicio_id}_308"}
            ]
        ]
    }
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones
        }
    )

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallo")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener_servicios_nuevos(self):
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
            logger.info(f"Servicios nuevos: {len(servicios)}")
            return servicios
        except Exception as e:
            logger.error(f"Error obtener servicios nuevos: {e}")
            return {}

    def obtener_servicios_en_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=15)
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
            logger.info(f"Servicios en curso: {len(servicios)}")
            return servicios
        except Exception as e:
            logger.error(f"Error obtener servicios en curso: {e}")
            return {}

    def cambiar_estado_servicio(self, servicio_id, nuevo_estado):
        try:
            # Fecha siguiente día
            fecha_siguiente = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
            payload = {
                "SERVICIO": servicio_id,
                "ESTADO": nuevo_estado,  # 307 En progreso, 308 Finalizado
                "FECSIG": fecha_siguiente,
                "INFORMO": "on",
                "Observaciones": "ala espera de contactar con cliente",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }
            r = self.session.post(CAMBIO_ESTADO_URL, data=payload, timeout=10)
            if r.status_code == 200:
                logger.info(f"✔ Servicio {servicio_id} cambiado correctamente a {nuevo_estado}")
                return True
            else:
                logger.error(f"❌ Error POST servicio {servicio_id}, status: {r.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error al cambiar estado del servicio {servicio_id}: {e}")
            return False

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    homeserve.login()
    while True:
        try:
            # Solo actualizamos servicios en curso para el loop interno
            SERVICIOS_CURSO.update(homeserve.obtener_servicios_en_curso())
            # Actualizamos servicios nuevos y avisamos de nuevos
            nuevos = homeserve.obtener_servicios_nuevos()
            for idserv, servicio in nuevos.items():
                if idserv not in SERVICIOS_NUEVOS:
                    enviar_servicio(CHAT_ID, idserv, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
            SERVICIOS_NUEVOS.update(nuevos)
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios nuevos: {len(SERVICIOS_NUEVOS)}, en curso: {len(SERVICIOS_CURSO)}"

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
            SERVICIOS_NUEVOS.update(homeserve.obtener_servicios_nuevos())
            SERVICIOS_CURSO.update(homeserve.obtener_servicios_en_curso())
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            # Mostrar solo servicios nuevos
            txt = ""
            for s in SERVICIOS_NUEVOS.values():
                txt += s + "\n\n"
            enviar(chat, txt if SERVICIOS_NUEVOS else "Nada nuevo por asignar")

        elif accion == "CAMBIAR_ESTADO":
            SERVICIOS_CURSO.update(homeserve.obtener_servicios_en_curso())
            if SERVICIOS_CURSO:
                for idserv, servicio in SERVICIOS_CURSO.items():
                    enviar_estado_servicio(chat, idserv, f"🔧 <b>Cambiar estado</b>\n\n{servicio}")
            else:
                enviar(chat, "No hay servicios en curso para cambiar estado.")

        # Servicios nuevos
        elif accion.startswith("ACEPTAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "ACEPTADO"
            enviar(chat, f"✅ Servicio {servicio_id} aceptado")

        elif accion.startswith("RECHAZAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "RECHAZADO"
            enviar(chat, f"❌ Servicio {servicio_id} rechazado")

        # Cambio de estado en curso
        elif accion.startswith("ESTADO_"):
            parts = accion.split("_")
            servicio_id, nuevo_estado = parts[1], parts[2]  # 307 o 308
            ok = homeserve.cambiar_estado_servicio(servicio_id, nuevo_estado)
            if ok:
                SERVICIOS_ESTADO[servicio_id] = nuevo_estado
                estado_texto = "En progreso" if nuevo_estado == "307" else "Finalizado"
                enviar(chat, f"🛠 Servicio {servicio_id} cambiado a: {estado_texto}")
            else:
                enviar(chat, f"❌ Error cambiando estado del servicio {servicio_id}")

    elif "message" in data:
        chat = data["message"]["chat"]["id"]
        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Bot activo con control total")

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
