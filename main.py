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
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
CAMBIO_ESTADO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=cambiar_estado_servicio"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_CURSO = {}     # Todos los servicios actuales
SERVICIOS_ACTUALES = {}  # Solo los nuevos detectados
SERVICIOS_ESTADO = {}    # Para guardar cambios de estado

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

def enviar_botones_servicio(chat, servicio_id, servicio_texto, nuevo=True):
    if nuevo:
        botones = {
            "inline_keyboard": [
                [
                    {"text": "✅ Aceptar", "callback_data": f"NUEVO_{servicio_id}_ACEPTAR"},
                    {"text": "❌ Rechazar", "callback_data": f"NUEVO_{servicio_id}_RECHAZAR"}
                ]
            ]
        }
    else:
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
            "text": servicio_texto,
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
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallo")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

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
            fecha_siguiente = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
            payload = {
                "SERVICIO": servicio_id,
                "ESTADO": nuevo_estado,
                "FECSIG": fecha_siguiente,
                "INFORMO": "on",
                "Observaciones": "ala espera de contactar con cliente",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }
            r = self.session.post(CAMBIO_ESTADO_URL, data=payload, timeout=10)
            if r.status_code == 200:
                logger.info(f"✔ POST simulado enviado correctamente para servicio {servicio_id}")
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
            servicios_actualizados = homeserve.obtener_servicios_en_curso()
            nuevos_servicios = {k: v for k, v in servicios_actualizados.items() if k not in SERVICIOS_CURSO}

            # Actualizar globales
            SERVICIOS_CURSO.update(servicios_actualizados)
            SERVICIOS_ACTUALES.update(nuevos_servicios)

            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios: {len(SERVICIOS_CURSO)}"

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
            servicios_actualizados = homeserve.obtener_servicios_en_curso()
            nuevos_servicios = {k: v for k, v in servicios_actualizados.items() if k not in SERVICIOS_CURSO}
            SERVICIOS_CURSO.update(servicios_actualizados)
            SERVICIOS_ACTUALES.update(nuevos_servicios)
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            txt = "\n\n".join(SERVICIOS_CURSO.values())
            enviar(chat, txt if txt else "Nada encontrado")

        elif accion == "CAMBIAR_ESTADO":
            for idserv, servicio in SERVICIOS_CURSO.items():
                if idserv in SERVICIOS_ACTUALES:
                    enviar_botones_servicio(chat, idserv, f"🆕 Nuevo servicio:\n\n{servicio}", nuevo=True)
                else:
                    enviar_botones_servicio(chat, idserv, f"🔧 Servicio en curso:\n\n{servicio}", nuevo=False)

        elif accion.startswith("ESTADO_"):
            parts = accion.split("_")
            servicio_id, nuevo_estado = parts[1], parts[2]
            ok = homeserve.cambiar_estado_servicio(servicio_id, nuevo_estado)
            if ok:
                SERVICIOS_ESTADO[servicio_id] = nuevo_estado
                enviar(chat, f"🛠 Servicio {servicio_id} cambiado a: {nuevo_estado}")
            else:
                enviar(chat, f"❌ Error cambiando estado del servicio {servicio_id}")

        elif accion.startswith("NUEVO_"):
            parts = accion.split("_")
            servicio_id, decision = parts[1], parts[2]
            if decision == "ACEPTAR":
                enviar(chat, f"✅ Servicio {servicio_id} aceptado")
            else:
                enviar(chat, f"❌ Servicio {servicio_id} rechazado")
            # Quitar de nuevos
            SERVICIOS_ACTUALES.pop(servicio_id, None)

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
