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

# ---------------- TXT STATE ----------------
TXT_PATH = "/data/servicios.txt"
TXT_STATE = {}

os.makedirs("/data", exist_ok=True)

def init_txt():
    if not os.path.exists(TXT_PATH):
        with open(TXT_PATH, "w") as f:
            f.write("")

def leer_txt():
    with open(TXT_PATH, "r") as f:
        return [x.strip() for x in f.readlines() if x.strip()]

def agregar_txt(valor):
    with open(TXT_PATH, "a") as f:
        f.write(str(valor) + "\n")

def limpiar_txt():
    with open(TXT_PATH, "w") as f:
        f.write("")

def init_db():
    conn = sqlite3.connect("/data/usuarios.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS usuarios (chat_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect("/data/usuarios.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect("/data/usuarios.db")
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    return [r[0] for r in c.fetchall()]

def eliminar_usuario(chat_id):
    conn = sqlite3.connect("/data/usuarios.db")
    c = conn.cursor()
    c.execute("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))
    conn.commit()
    conn.close()

init_db()
init_txt()

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
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                  json={"callback_query_id": callback_id}, timeout=10)

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"},
             {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}],
            [{"text": "📦 Número de servicios", "callback_data": "MENU_TXT"}]
        ]
    }

def botones_txt():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar servicio", "callback_data": "ADD_TXT"}],
            [{"text": "🗑 Eliminar todo", "callback_data": "DEL_TXT"}],
            [{"text": "📄 Ver servicios", "callback_data": "VIEW_TXT"}],
            [{"text": "⬇️ Descargar TXT", "callback_data": "DOWN_TXT"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
        ]
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
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", text)

            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())
            return servicios
        except:
            return {}

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", None)

            SERVICIOS_ACTUALES = actuales

        except Exception as e:
            logger.error(e)
            homeserve.login()

        time.sleep(INTERVALO)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        guardar_usuario(chat)

        # ➕ input TXT
        if chat in TXT_STATE:
            if TXT_STATE[chat] == "ADD":
                agregar_txt(text)
                tg_send(chat, "✅ agregado. Escribe otro o /done para terminar")
            if text == "/done":
                TXT_STATE.pop(chat, None)
                tg_send(chat, "✔️ terminado")

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])

        if action == "MENU_TXT":
            tg_edit(chat, msg_id, "📦 Menú servicios TXT", botones_txt())

        elif action == "ADD_TXT":
            TXT_STATE[chat] = "ADD"
            tg_send(chat, "✏️ envía números uno por uno")

        elif action == "DEL_TXT":
            limpiar_txt()
            tg_edit(chat, msg_id, "🗑 eliminado", botones_txt())

        elif action == "VIEW_TXT":
            data = "\n".join(leer_txt()) or "vacío"
            tg_edit(chat, msg_id, f"📄\n{data}", botones_txt())

        elif action == "DOWN_TXT":
            requests.post(
                f"{TELEGRAM_API}/sendDocument",
                data={"chat_id": chat},
                files={"document": open(TXT_PATH, "rb")}
            )

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
