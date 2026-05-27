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
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"

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

init_db()

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
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(cid):
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": cid},
        timeout=10
    )

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "📦 Servicios", "callback_data": "CURSO"}],
            [{"text": "📋 Trabajo en curso", "callback_data": "TRABAJO_CURSO"}]
        ]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:

    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(
                LOGIN_URL,
                data={"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"},
                timeout=10
            )
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self, url):
        try:
            r = self.session.get(url, timeout=15)
            r.encoding = "latin-1"

            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", text)

            data = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    data[m.group(0)] = " ".join(b.split())

            return data

        except:
            return {}

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    homeserve.login()

    while True:
        try:
            SERVICIOS_ACTUALES = homeserve.obtener(ASIGNACION_URL)
            time.sleep(INTERVALO)
        except:
            homeserve.login()
            time.sleep(10)

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
        guardar_usuario(chat)

        # ---------------- CURSO ----------------
        if action == "CURSO":

            curso = homeserve.obtener(SERVICIOS_CURSO_URL)

            if not curso:
                tg_edit(chat, msg_id, "❌ No hay servicios en curso", botones())
            else:
                texto = "📋 <b>Servicios en curso</b>\n\n"

                for sid, data in curso.items():
                    texto += f"🔹 <b>{sid}</b>\n{data}\n\n"

                if len(texto) > 3500:
                    texto = texto[:3500] + "\n\n⚠️ Truncado..."

                tg_edit(chat, msg_id, texto, botones())

        # ---------------- TRABAJO CURSO ----------------
        elif action == "TRABAJO_CURSO":

            curso = homeserve.obtener(SERVICIOS_CURSO_URL)

            if not curso:
                tg_edit(chat, msg_id, "❌ No hay servicios en curso", botones())
            else:
                texto = "📋 <b>Trabajo en curso</b>\n\n"

                for sid, data in curso.items():
                    texto += f"🔹 <b>{sid}</b>\n{data}\n\n"

                if len(texto) > 3500:
                    texto = texto[:3500] + "\n\n⚠️ Truncado..."

                tg_edit(chat, msg_id, texto, botones())

        # ---------------- LOGIN ----------------
        elif action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "Login OK" if ok else "Error", botones())

        # ---------------- ACEPTAR ----------------
        elif action.startswith("ACEPTAR_"):

            sid = action.split("_")[1]

            try:
                url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
                r = homeserve.session.get(url, timeout=15)

                html = r.text.lower()

                errores = ["error","illegal","denegado","caducada","no autorizado","acceso inválido"]
                fallo = any(e in html for e in errores)

                if fallo:
                    tg_edit(chat, msg_id, f"❌ Error al aceptar {sid}", botones())
                else:
                    tg_edit(chat, msg_id, f"✅ Servicio {sid} aceptado", botones())

            except Exception as e:
                tg_edit(chat, msg_id, f"❌ {e}", botones())

        # ---------------- RECHAZAR ----------------
        elif action.startswith("RECHAZAR_"):

            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"❌ Rechazado {sid}", botones())

    return jsonify(ok=True)

# ---------------- START ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
