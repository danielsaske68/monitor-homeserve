import os
import time
import threading
import logging
import re
import requests
import sqlite3
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

# ---------------- DATABASE ----------------
DB_PATH = "/data/usuarios.db"
os.makedirs("/data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            chat_id TEXT PRIMARY KEY,
            panel_msg_id TEXT
        )
    """)
    conn.commit()
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    conn.commit()
    conn.close()

def guardar_panel(chat_id, msg_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE usuarios SET panel_msg_id=? WHERE chat_id=?", (msg_id, chat_id))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    usuarios = [row[0] for row in c.fetchall()]
    conn.close()
    return usuarios

init_db()

# ---------------- TELEGRAM ----------------
def enviar(chat, texto, botones=None):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones

    try:
        r = requests.post(TELEGRAM_API + "/sendMessage", json=data, timeout=10).json()
        return r.get("result", {}).get("message_id")
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")

def editar(chat, msg_id, texto, botones=None):
    data = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": texto,
        "parse_mode": "HTML"
    }
    if botones:
        data["reply_markup"] = botones

    try:
        requests.post(TELEGRAM_API + "/editMessageText", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Error editando mensaje: {e}")

def responder_callback(callback_id):
    try:
        requests.post(TELEGRAM_API + "/answerCallbackQuery", json={
            "callback_query_id": callback_id
        }, timeout=10)
    except:
        pass

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
             {"text": "🟢 En espera confirmar", "callback_data": f"ESTADO_{servicio_id}_318"}]
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
            ok = "error" not in r.text.lower()
            logger.info("✅ Login OK" if ok else "❌ Login FAIL")
            return ok
        except:
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

            return servicios
        except:
            self.login()
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
        except:
            self.login()
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
            return (r.status_code == 200, f"✅ Estado {estado} aplicado correctamente")

        except Exception as e:
            return False, f"❌ Error: {e}"

    def aceptar_servicio(self, servicio_id):
        try:
            r = self.session.post(BASE_URL, data={
                "w3exec": "prof_asignacion",
                "servicio": servicio_id,
                "ACEPTAR": "Aceptar"
            }, timeout=10)

            return (r.status_code == 200, f"✅ Servicio {servicio_id} aceptado")

        except Exception as e:
            return False, f"❌ Error: {e}"

    def rechazar_servicio(self, servicio_id):
        try:
            r = self.session.post(BASE_URL, data={
                "w3exec": "prof_asignacion",
                "servicio": servicio_id,
                "RECHAZAR": "Rechazar"
            }, timeout=10)

            return (r.status_code == 200, f"❌ Servicio {servicio_id} rechazado")

        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Iniciando loop...")
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()
            logger.info(f"📊 Servicios detectados: {len(actuales)}")

            for sid, servicio in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 Nuevo servicio: {sid}")

                    for user in obtener_usuarios():
                        enviar(user,
                               f"🆕 <b>Nuevo servicio</b>\n\n{servicio}",
                               botones_servicio_nuevo(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"💥 Error loop: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    logger.info(f"📩 Update: {data}")

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            msg_id = enviar(chat, "👋 Hola, En que puedo ayudar", botones_generales())
            guardar_panel(chat, msg_id)

    if "callback_query" in data:
        query = data["callback_query"]
        accion = query["data"]
        chat = query["message"]["chat"]["id"]
        msg_id = query["message"]["message_id"]

        responder_callback(query["id"])

        if accion == "LOGIN":
            ok = homeserve.login()
            editar(chat, msg_id, "✅ Login OK" if ok else "❌ Error login", botones_generales())

        elif accion == "REFRESH":
            servicios = homeserve.obtener()
            editar(chat, msg_id, f"🔄 Servicios actuales: {len(servicios)}", botones_generales())

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

# ---------------- INICIO ----------------
usuarios = obtener_usuarios()
for user in usuarios:
    enviar(user, "🤖 Bot activo")

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado correctamente")
    app.run(host="0.0.0.0", port=8080)
