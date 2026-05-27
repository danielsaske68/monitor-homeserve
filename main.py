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

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

app = Flask(__name__)

# ---------------- STATE ----------------
SERVICIOS_ACTUALES = {}
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

# ---------------- FILE ----------------
def file_path(chat):
    return f"/data/servicios_{chat}.txt"

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def read_services(chat):
    try:
        return open(file_path(chat), "r", encoding="utf-8").read()
    except:
        return ""

def clear_services(chat):
    open(file_path(chat), "w").close()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)

def tg_edit(chat, msg_id, text, markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload)

def tg_answer(callback_id):
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": callback_id}
    )

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"},
             {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Estado", "callback_data": "CAMBIAR"}],
            [{"text": "📦 Servicios TXT", "callback_data": "NUM_SERV"}],
            [{"text": "📋 Servicios totales", "callback_data": "SERV_TOTALES"}]
        ]
    }

def botones_num_serv():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar", "callback_data": "ADD_SERV"}],
            [{"text": "🗑 Borrar", "callback_data": "DEL_SERV"}],
            [{"text": "👁 Ver", "callback_data": "VIEW_SERV"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK"}]
        ]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            self.session.get(LOGIN_URL)
            r = self.session.post(LOGIN_URL, data={
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            })
            return "error" not in r.text.lower()
        except:
            return False

    def obtener_servicios_totales(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"

            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")[1:]

            data = []

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue

                link = cols[0].find("a")
                sid = link.text.strip() if link else cols[0].get_text(strip=True)

                data.append({
                    "id": sid,
                    "direccion": cols[2].get_text(strip=True),
                    "caduca": cols[5].get_text(strip=True)
                })

            return data

        except:
            return []

homeserve = HomeServe()

# ---------------- FORMAT ----------------
def format_servicios(data):
    txt = "📦 <b>Servicios totales</b>\n\n"
    for s in data:
        txt += (
            f"🆔 {s['id']}\n"
            f"📍 {s['direccion']}\n"
            f"📅 Caduca: {s['caduca']}\n"
            "──────────────\n"
        )
    return txt

# ---------------- LOOP ----------------
def loop():
    while True:
        time.sleep(INTERVALO)

threading.Thread(target=loop, daemon=True).start()

# ---------------- WEBHOOK ----------------
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
                tg_edit(chat, msg_id, format_servicios(servicios), botones())
            else:
                tg_edit(chat, msg_id, "Sin servicios", botones())

        elif action == "BACK":
            tg_edit(chat, msg_id, "Menú", botones())

        elif action == "NUM_SERV":
            tg_edit(chat, msg_id, "Servicios TXT", botones_num_serv())

        elif action == "VIEW_SERV":
            tg_edit(chat, msg_id, read_services(chat) or "Vacío", botones_num_serv())

        elif action == "DEL_SERV":
            clear_services(chat)
            tg_edit(chat, msg_id, "Borrado", botones_num_serv())

        elif action == "ADD_SERV":
            SERV_STATE[chat] = True
            tg_edit(chat, msg_id, "Escribe servicios")

    return jsonify(ok=True)

# ---------------- START ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
