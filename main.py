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

def obtener_panel(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT panel_msg_id FROM usuarios WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    data = [row[0] for row in c.fetchall()]
    conn.close()
    return data

init_db()

# ---------------- TELEGRAM ----------------
def enviar(chat, texto, botones=None):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones

    r = requests.post(TELEGRAM_API + "/sendMessage", json=data).json()
    return r.get("result", {}).get("message_id")

def editar(chat, msg_id, texto, botones=None):
    data = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": texto,
        "parse_mode": "HTML"
    }
    if botones:
        data["reply_markup"] = botones

    requests.post(TELEGRAM_API + "/editMessageText", json=data)

def responder_callback(callback_id):
    requests.post(TELEGRAM_API + "/answerCallbackQuery", json={
        "callback_query_id": callback_id
    })

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

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD}
            self.session.get(LOGIN_URL)
            r = self.session.post(LOGIN_URL, data=payload)
            ok = "error" not in r.text.lower()
            logger.info("Login OK" if ok else "Login FAIL")
            return ok
        except:
            return False

    def asegurar_login(self):
        if not self.login():
            logger.info("Reintentando login...")
            self.login()

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL)
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
            self.asegurar_login()
            return {}

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Iniciando loop...")
    homeserve.login()

    while True:
        actuales = homeserve.obtener()

        logger.info(f"📊 Servicios detectados: {len(actuales)}")

        for sid, servicio in actuales.items():
            if sid not in SERVICIOS_ACTUALES:
                logger.info(f"🆕 Nuevo servicio: {sid}")
                for user in obtener_usuarios():
                    enviar(user, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}", botones_servicio_nuevo(sid))

        SERVICIOS_ACTUALES = actuales
        time.sleep(INTERVALO)

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

        responder_callback(query["id"])  # 🔥 CLAVE

        guardar_usuario(chat)

        if accion == "LOGIN":
            ok = homeserve.login()
            editar(chat, msg_id, "✅ Login correcto" if ok else "❌ Error login", botones_generales())

        elif accion == "REFRESH":
            servicios = homeserve.obtener()
            editar(chat, msg_id, f"🔄 Servicios: {len(servicios)}", botones_generales())

        elif accion == "WEB":
            servicios = homeserve.obtener()
            texto = "\n\n".join(servicios.values()) if servicios else "Sin servicios"
            editar(chat, msg_id, f"🌐 {texto}", botones_generales())

    return jsonify(ok=True)

# ---------------- INICIO ----------------
usuarios = obtener_usuarios()
for user in usuarios:
    enviar(user, "🤖 Bot activo")

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
