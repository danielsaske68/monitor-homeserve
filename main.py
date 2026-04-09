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
DB_VOLUME_PATH = "/data/usuarios"
DB_PATH = os.path.join(DB_VOLUME_PATH, "usuarios.db")
os.makedirs(DB_VOLUME_PATH, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS usuarios (chat_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
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
             {"text": "🟢 En espera por confirmar", "callback_data": f"ESTADO_{servicio_id}_318"}]
        ]
    }

def botones_servicio(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
             {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}]
        ]
    }

def botones_lista_servicios(servicios):
    return {"inline_keyboard": [[{"text": sid, "callback_data": f"SEL_{sid}"}] for sid in servicios]}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\d{7,8}", b)
                if m:
                    servicios[m.group()] = " ".join(b.split())
            return servicios
        except:
            return {}

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
    homeserve.login()
    while True:
        actuales = homeserve.obtener()
        for sid, s in actuales.items():
            if sid not in SERVICIOS_ACTUALES:
                for user in obtener_usuarios():
                    enviar(user, f"🆕 <b>Nuevo servicio</b>\n\n{s}", botones_servicio(sid))
        SERVICIOS_ACTUALES = actuales
        time.sleep(INTERVALO)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        msg = data["message"].get("text", "")
        if msg.startswith("/start"):
            enviar(chat, "👋 Hola, En que puedo ayudar", botones_generales())

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]
        guardar_usuario(chat)

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login", botones_generales())

        elif accion == "REFRESH":
            enviar(chat, "🔄 Actualizado", botones_generales())

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if not actuales:
                enviar(chat, "No hay servicios", botones_generales())
            else:
                for sid, servicio in actuales.items():
                    enviar(chat, f"📋 {servicio}", botones_servicio(sid))

        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.aceptar_servicio(sid)
            enviar(chat, msg, botones_generales())

        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.rechazar_servicio(sid)
            enviar(chat, msg, botones_generales())

    return jsonify(ok=True)

# ---------------- INICIO ----------------
usuarios = obtener_usuarios()

for user in usuarios:
    enviar(user, "🤖 Bot activo", botones_generales())

SERVICIOS_ACTUALES = homeserve.obtener()
for sid, s in SERVICIOS_ACTUALES.items():
    for user in usuarios:
        enviar(user, f"🆕 {s}", botones_servicio(sid))

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado correctamente")
    app.run(host="0.0.0.0", port=10000)
