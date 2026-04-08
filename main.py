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
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

# ---------------- VARIABLES ----------------
SERVICIOS_ACTUALES = {}
app = Flask(__name__)

# ---------------- USUARIOS ----------------
def guardar_usuario(chat_id):
    try:
        with open("usuarios.txt", "a+") as f:
            f.seek(0)
            usuarios = f.read().splitlines()
            if str(chat_id) not in usuarios:
                f.write(str(chat_id) + "\n")
                logger.info(f"👤 Usuario guardado: {chat_id}")
    except Exception as e:
        logger.error(f"Error guardando usuario: {e}")

def obtener_usuarios():
    try:
        with open("usuarios.txt", "r") as f:
            return f.read().splitlines()
    except:
        return []

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
            [{"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{servicio_id}_348"},
             {"text": "🟢 En espera profesional", "callback_data": f"ESTADO_{servicio_id}_318"}]
        ]
    }

def botones_servicio_nuevo(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
             {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}]
        ]
    }

def botones_lista_servicios(servicios):
    teclado = []
    for sid in servicios:
        teclado.append([{"text": f"{sid}", "callback_data": f"SEL_{sid}"}])
    return {"inline_keyboard": teclado}

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
                logger.error("❌ Login fallo")
                return False
            logger.info("✅ Login OK")
            return True
        except Exception as e:
            logger.error(f"Login error: {e}")
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
                    sid = m.group(0)
                    servicios[sid] = " ".join(b.split())

            logger.info(f"🔎 Revisando servicios... encontrados: {len(servicios)}")

            if len(servicios) == 0:
                logger.info("⚠️ No hay servicios disponibles")

            return servicios

        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return {}

    def obtener_curso(self):
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
            logger.error(f"Error servicios curso: {e}")
            return {}

    def cambiar_estado(self, servicio_id, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            obs = "Pendiente de localizar a asegurado" if estado == "348" else "En espera de Profesional por confirmación del Siniestro"

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "ESTADO": estado,
                "FECSIG": fecha.strftime("%d/%m/%Y"),
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            r = self.session.post(BASE_URL, data=payload, timeout=10)

            if r.status_code == 200:
                return True, f"✅ Estado {estado} aplicado correctamente"
            else:
                return False, f"⚠️ Error HTTP {r.status_code}"

        except Exception as e:
            return False, f"❌ Error: {e}"

    def aceptar_servicio(self, servicio_id):
        try:
            payload = {
                "w3exec": "prof_asignacion",
                "servicio": servicio_id,
                "ACEPTAR": "Aceptar"
            }

            r = self.session.post(BASE_URL, data=payload, timeout=10)

            if r.status_code == 200:
                return True, f"✅ Servicio {servicio_id} aceptado"
            return False, f"⚠️ Error aceptando"

        except Exception as e:
            return False, f"❌ Error: {e}"

    def rechazar_servicio(self, servicio_id):
        try:
            payload = {
                "w3exec": "prof_asignacion",
                "servicio": servicio_id,
                "RECHAZAR": "Rechazar"
            }

            r = self.session.post(BASE_URL, data=payload, timeout=10)

            if r.status_code == 200:
                return True, f"❌ Servicio {servicio_id} rechazado"
            return False, f"⚠️ Error rechazando"

        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Iniciando loop de servicios...")

    if not homeserve.login():
        logger.error("❌ No se pudo hacer login inicial")

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, servicio in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 Nuevo servicio detectado: {sid}")

                    for user in obtener_usuarios():
                        enviar(user, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}", botones_servicio_nuevo(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"Error loop: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Bot activo", botones_generales())

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]
        guardar_usuario(chat)

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            homeserve.obtener()
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if not actuales:
                enviar(chat, "No hay servicios")
            else:
                for sid, servicio in actuales.items():
                    enviar(chat, f"📋 {servicio}", botones_servicio_nuevo(sid))

        elif accion == "CAMBIAR_ESTADO":
            curso = homeserve.obtener_curso()
            if curso:
                enviar(chat, "🛠 Selecciona servicio:", botones_lista_servicios(curso))
            else:
                enviar(chat, "⚠️ No hay servicios en curso")

        elif accion.startswith("SEL_"):
            sid = accion.split("_")[1]
            enviar(chat, f"🔧 Servicio {sid}", botones_estado(sid))

        elif accion.startswith("ESTADO_"):
            _, sid, estado = accion.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            enviar(chat, f"{sid}\n{msg}")

        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.aceptar_servicio(sid)
            enviar(chat, msg)

        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.rechazar_servicio(sid)
            enviar(chat, msg)

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado correctamente")
    app.run(host="0.0.0.0", port=10000)
