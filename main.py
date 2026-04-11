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
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            chat_id TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

def actualizar_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("ALTER TABLE usuarios ADD COLUMN panel_msg_id TEXT")
        conn.commit()
        conn.close()
        logger.info("✅ Columna panel_msg_id añadida")
    except sqlite3.OperationalError:
        logger.info("ℹ️ Columna panel_msg_id ya existe")

def guardar_usuario(chat_id, panel_msg_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    if panel_msg_id:
        c.execute("UPDATE usuarios SET panel_msg_id=? WHERE chat_id=?", (panel_msg_id, chat_id))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT chat_id, panel_msg_id FROM usuarios")
        data = c.fetchall()
        conn.close()
        return {row[0]: row[1] for row in data}
    except:
        # fallback por si aún no existe la columna
        c.execute("SELECT chat_id FROM usuarios")
        data = c.fetchall()
        conn.close()
        return {row[0]: None for row in data}

init_db()
actualizar_db()

# ---------------- TELEGRAM ----------------
def enviar_panel(chat, texto, botones=None):
    usuarios = obtener_usuarios()
    panel_id = usuarios.get(str(chat))

    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones

    try:
        if panel_id:
            data["message_id"] = int(panel_id)
            requests.post(f"{TELEGRAM_API}/editMessageText", json=data)
        else:
            r = requests.post(f"{TELEGRAM_API}/sendMessage", json=data)
            if r.ok:
                msg_id = r.json()["result"]["message_id"]
                guardar_usuario(chat, msg_id)
    except Exception as e:
        logger.error(f"Error panel: {e}")

def enviar_servicio(chat, texto, botones=None):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=data)
    except Exception as e:
        logger.error(f"Error servicio: {e}")

def menu():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [[
            {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
            {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
        ]]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [[
            {"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{sid}_348"},
            {"text": "🟢 En espera por confirmar", "callback_data": f"ESTADO_{sid}_318"}
        ]]
    }

def lista_servicios(servicios):
    return {"inline_keyboard": [[{"text": sid, "callback_data": f"SEL_{sid}"}] for sid in servicios]}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL)
            r = self.session.post(LOGIN_URL, data=payload)
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL)
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

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL)
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            return {re.search(r"\d{7,8}", b).group(): " ".join(b.split()) for b in bloques if re.search(r"\d{7,8}", b)}
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado,
                "FECSIG": datetime.now().strftime("%d/%m/%Y"),
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }
            r = self.session.post(BASE_URL, data=payload)
            return r.status_code == 200, f"✅ Estado {estado} aplicado"
        except Exception as e:
            return False, f"❌ Error: {e}"

    def aceptar_servicio(self, sid):
        try:
            r = self.session.post(BASE_URL, data={"w3exec":"prof_asignacion","servicio":sid,"ACEPTAR":"Aceptar"})
            return r.status_code == 200, f"✅ Servicio {sid} aceptado"
        except Exception as e:
            return False, f"❌ Error: {e}"

    def rechazar_servicio(self, sid):
        try:
            r = self.session.post(BASE_URL, data={"w3exec":"prof_asignacion","servicio":sid,"RECHAZAR":"Rechazar"})
            return r.status_code == 200, f"❌ Servicio {sid} rechazado"
        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    homeserve.login()
    while True:
        actuales = homeserve.obtener()
        for sid, servicio in actuales.items():
            if sid not in SERVICIOS_ACTUALES:
                for user in obtener_usuarios():
                    enviar_servicio(user, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}", botones_servicio(sid))
        SERVICIOS_ACTUALES = actuales
        time.sleep(INTERVALO)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text","").startswith("/start"):
            enviar_panel(chat, "👋 Hola, en qué puedo ayudar", menu())

    if "callback_query" in data:
        chat = data["callback_query"]["message"]["chat"]["id"]
        accion = data["callback_query"]["data"]
        guardar_usuario(chat)

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar_panel(chat, "✅ Login OK" if ok else "❌ Error login", menu())

        elif accion == "REFRESH":
            enviar_panel(chat, "🔄 Actualizado", menu())

        elif accion == "WEB":
            servicios = homeserve.obtener()
            if not servicios:
                enviar_panel(chat, "No hay servicios", menu())
            else:
                for sid, s in servicios.items():
                    enviar_servicio(chat, f"📋 {s}", botones_servicio(sid))

        elif accion == "CAMBIAR_ESTADO":
            curso = homeserve.obtener_curso()
            if curso:
                enviar_panel(chat, "🛠 Selecciona servicio:", lista_servicios(curso))
            else:
                enviar_panel(chat, "⚠️ No hay servicios en curso", menu())

        elif accion.startswith("SEL_"):
            sid = accion.split("_")[1]
            enviar_panel(chat, f"🔧 Servicio {sid}", botones_estado(sid))

        elif accion.startswith("ESTADO_"):
            _, sid, estado = accion.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            enviar_panel(chat, msg, menu())

        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.aceptar_servicio(sid)
            enviar_servicio(chat, msg)

        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.rechazar_servicio(sid)
            enviar_servicio(chat, msg)

    return jsonify(ok=True)

# ---------------- INICIO ----------------
usuarios = obtener_usuarios()
for user in usuarios:
    enviar_servicio(user, "🤖 Bot activo")

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado correctamente")
    app.run(host="0.0.0.0", port=10000)
