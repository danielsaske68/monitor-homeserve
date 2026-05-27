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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

app = Flask(__name__)

# ---------------- STATE ----------------
SERVICIOS_ACTUALES = {}
WEB_CACHE = {}
WEB_INDEX = {}
USER_STATE = {}
SERV_STATE = {}

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
    return [r[0] for r in c.fetchall()]

def eliminar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))
    conn.commit()
    conn.close()

init_db()

# ---------------- FILE SYSTEM ----------------
def file_path(chat):
    return f"/data/servicios_{chat}.txt"

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def read_services(chat):
    try:
        with open(file_path(chat), "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def clear_services(chat):
    open(file_path(chat), "w").close()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

def tg_edit(chat, msg_id, text, markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": markup
    }
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(callback_id):
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
        timeout=10
    )

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"},
             {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}],
            [{"text": "📦 Numero de servicios", "callback_data": "NUM_SERV"}],
            [{"text": "📋 Servicios totales", "callback_data": "SERV_TOTALES"}]
        ]
    }

def botones_num_serv():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar servicio", "callback_data": "ADD_SERV"}],
            [{"text": "🗑 Eliminar archivo", "callback_data": "DEL_SERV"}],
            [{"text": "📥 Descargar", "callback_data": "DOWN_SERV"}],
            [{"text": "👁 Ver", "callback_data": "VIEW_SERV"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_NUM_SERV"}]
        ]
    }

def botones_usuarios():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar", "callback_data": "ADD_USER"}],
            [{"text": "🗑 Eliminar", "callback_data": "DEL_USER"}],
            [{"text": "📋 Listar", "callback_data": "LIST_USERS"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
             {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}],
            [{"text": "⬅️ Volver", "callback_data": "WEB"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [{"text": "🔴 348 Cliente", "callback_data": f"ESTADO_{sid}_348"},
             {"text": "🟢 318 Confirmación", "callback_data": f"ESTADO_{sid}_318"}],
            [{"text": "⬅️ Volver", "callback_data": "CAMBIAR"}]
        ]
    }

def lista_servicios(servicios):
    return {
        "inline_keyboard": [[{"text": sid, "callback_data": f"SEL_{sid}"}] for sid in servicios]
    }

# ---------------- NUEVO: SERVICIOS TOTALES ----------------
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
        except:
            return False

    def obtener_servicios_totales(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"

            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")[1:]

            servicios = []

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue

                link = cols[0].find("a")
                sid = link.text.strip() if link else cols[0].get_text(strip=True)

                servicios.append({
                    "id": sid,
                    "direccion": cols[2].get_text(strip=True),
                    "fecha_caduca": cols[5].get_text(strip=True)
                })

            return servicios
        except:
            return []

homeserve = HomeServe()

def formatear_servicios_totales(servicios):
    texto = "📦 <b>Servicios totales</b>\n\n"
    for s in servicios:
        texto += (
            f"🆔 {s['id']}\n"
            f"📍 {s['direccion']}\n"
            f"📅 Caduca: {s['fecha_caduca']}\n"
            "──────────────\n"
        )
    return texto

# ---------------- CALLBACK NUEVO ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        guardar_usuario(chat)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])

        if action == "SERV_TOTALES":
            servicios = homeserve.obtener_servicios_totales()
            if servicios:
                tg_edit(chat, msg_id, formatear_servicios_totales(servicios), botones())
            else:
                tg_edit(chat, msg_id, "Sin servicios", botones())

    return jsonify(ok=True)

# ---------------- LOOP ----------------
def loop():
    while True:
        time.sleep(INTERVALO)

threading.Thread(target=loop, daemon=True).start()
