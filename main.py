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

# ---------------- APP ----------------
app = Flask(__name__)

SERVICIOS_ACTUALES = {}
PANEL = {}

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
    c.execute("INSERT OR IGNORE INTO usuarios VALUES (?)", (str(chat_id),))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    users = [r[0] for r in c.fetchall()]
    conn.close()
    return users

init_db()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, reply_markup=None):
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    if r.ok:
        PANEL[chat] = r.json()["result"]["message_id"]

def tg_edit(chat, msg_id, text, reply_markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(callback_id):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                  json={"callback_query_id": callback_id},
                  timeout=5)

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Estado", "callback_data": "CAMBIAR"}]
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
            {"text": "🔴 Cliente", "callback_data": f"ESTADO_{sid}_348"},
            {"text": "🟢 Espera", "callback_data": f"ESTADO_{sid}_318"}
        ]]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.s = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.s.get(LOGIN_URL, timeout=10)
            r = self.s.post(LOGIN_URL, data=payload, timeout=10)
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.s.get(ASIGNACION_URL, timeout=15)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            blocks = re.split(r"\n(?=\d{7,8}\s)", text)

            out = {}
            for b in blocks:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    out[m.group(0)] = " ".join(b.split())
            return out
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado
            }
            self.s.post(BASE_URL, data=payload, timeout=10)
            return True, f"Estado {estado} OK"
        except as e:
            return False, str(e)

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Monitor iniciado")

    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(e)
            homeserve.login()
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        data_cb = cq["data"]

        tg_answer(cq["id"])
        guardar_usuario(chat)

        msg_id = cq["message"]["message_id"]

        if data_cb == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "LOGIN OK" if ok else "FAIL", botones())

        elif data_cb == "REFRESH":
            tg_edit(chat, msg_id, f"{len(homeserve.obtener())} servicios", botones())

        elif data_cb == "WEB":
            for sid, txt in homeserve.obtener().items():
                tg_send(chat, txt, botones_servicio(sid))

        elif data_cb.startswith("ACEPTAR_"):
            sid = data_cb.split("_")[1]
            tg_send(chat, f"OK {sid}")

        elif data_cb.startswith("RECHAZAR_"):
            sid = data_cb.split("_")[1]
            tg_send(chat, f"NO {sid}")

        elif data_cb.startswith("ESTADO_"):
            _, sid, st = data_cb.split("_")
            ok, msg = homeserve.cambiar_estado(sid, st)
            tg_send(chat, msg)

    elif "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            tg_send(chat, "Bot activo", botones())

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Running")
    app.run(host="0.0.0.0", port=10000)
