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

# 🔥 OPTIMIZACIÓN: sesión reutilizable para Telegram
tg_session = requests.Session()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bot")

# ---------------- OPTIMIZACIONES REGEX ----------------
DIGIT_RE = re.compile(r"\b\d{7,8}\b")
SPLIT_RE = re.compile(r"\n(?=\d{7,8}\s)")

# ---------------- APP ----------------
app = Flask(__name__)

SERVICIOS_ACTUALES = {}
PANEL = {}

@app.route("/test", methods=["GET"])
def test():
    return "OK BOT ACTIVO"

# ---------------- DB ----------------
DB_PATH = "/data/usuarios.db"
os.makedirs("/data", exist_ok=True)

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
    data = [r[0] for r in c.fetchall()]
    conn.close()
    return data

init_db()

# ---------------- TELEGRAM (OPTIMIZADO) ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    return tg_session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

def tg_edit(chat, msg_id, text, markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup
    tg_session.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(callback_id):
    tg_session.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
        timeout=10
    )

# ---------------- BOTONES (SIN CAMBIOS) ----------------
def botones():
    return {
        "inline_keyboard": [
            [
                {"text": "🔐 Login", "callback_data": "LOGIN"},
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [[
            {"text": "⚙️ Cambiar estado", "callback_data": f"SEL_{sid}"}
        ]]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [[
            {"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{sid}_348"},
            {"text": "🟢 En espera confirmación", "callback_data": f"ESTADO_{sid}_318"}
        ]]
    }

def lista_servicios(servicios):
    return {
        "inline_keyboard": [[
            {"text": sid, "callback_data": f"SEL_{sid}"}
        ] for sid in servicios]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data={
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            }, timeout=10)
            return "error" not in r.text.lower()
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")

            bloques = SPLIT_RE.split(text)
            servicios = {}

            for b in bloques:
                m = DIGIT_RE.search(b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())

            return servicios
        except Exception as e:
            logger.error(f"Error obtener: {e}")
            return {}

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")

            bloques = SPLIT_RE.split(text)
            servicios = {}

            for b in bloques:
                m = DIGIT_RE.search(b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())

            return servicios
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            obs = (
                "Pendiente de localizar a asegurado"
                if estado == "348"
                else "En espera de Profesional por confirmación del Siniestro"
            )

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado,
                "FECSIG": fecha.strftime("%d/%m/%Y"),
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            self.session.post(BASE_URL, data=payload, timeout=10)
            return True, f"✅ Estado {estado} aplicado"
        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP (OPTIMIZADO) ----------------
def loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Monitor iniciado")
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            # 🔥 OPTIMIZACIÓN: usuarios SOLO UNA VEZ
            usuarios = obtener_usuarios()

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 Nuevo servicio {sid}")
                    for u in usuarios:
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            msg = tg_send(chat, "🤖 Bot activo", botones())
            PANEL[chat] = msg.json()["result"]["message_id"]

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])
        guardar_usuario(chat)

        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "✅ Login OK" if ok else "❌ Error", botones())

        elif action == "REFRESH":
            tg_edit(chat, msg_id, f"🔄 {len(homeserve.obtener())} servicios", botones())

        elif action == "WEB":
            actuales = homeserve.obtener()
            text = "\n\n".join(actuales.values()) if actuales else "Sin servicios"
            tg_edit(chat, msg_id, text, botones())

        elif action == "CAMBIAR":
            curso = homeserve.obtener_curso()
            tg_edit(chat, msg_id,
                   "❌ No hay servicios en curso" if not curso else "🛠 Selecciona servicio:",
                   lista_servicios(curso) if curso else botones())

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"📌 Servicio {sid}", botones_estado(sid))

        elif action.startswith("ESTADO_"):
            _, sid, estado = action.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            tg_edit(chat, msg_id, msg, botones_estado(sid))

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado")
    app.run(host="0.0.0.0", port=10000)
