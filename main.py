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

SERVICIOS_ACTUALES = {}
WEB_CACHE = {}
WEB_INDEX = {}
USER_STATE = {}

# ---------------- SESSION GLOBAL ----------------
tg_session = requests.Session()

# ---------------- DB ----------------
DB_PATH = "/data/usuarios.db"
os.makedirs("/data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS usuarios (chat_id TEXT PRIMARY KEY)")
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?)", (str(chat_id),))
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    data = [r[0] for r in conn.execute("SELECT chat_id FROM usuarios")]
    conn.close()
    return data

init_db()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    try:
        payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
        if markup:
            payload["reply_markup"] = markup
        tg_session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=5)
    except:
        pass

def tg_edit(chat, msg_id, text, markup=None):
    try:
        payload = {
            "chat_id": chat,
            "message_id": msg_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if markup:
            payload["reply_markup"] = markup
        tg_session.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=5)
    except:
        pass

def tg_answer(cid):
    try:
        tg_session.post(f"{TELEGRAM_API}/answerCallbackQuery",
                        json={"callback_query_id": cid},
                        timeout=5)
    except:
        pass

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [
                {"text": "🔐 Login", "callback_data": "LOGIN"},
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ],
            [
                {"text": "🌐 Web", "callback_data": "WEB"},
                {"text": "👥 Usuarios", "callback_data": "USUARIOS"}
            ],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
            ],
            [
                {"text": "⬅", "callback_data": "WEB_PREV"},
                {"text": "➡", "callback_data": "WEB_NEXT"}
            ],
            [{"text": "🏠", "callback_data": "BACK_MENU"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 348", "callback_data": f"ESTADO_{sid}_348"},
                {"text": "🟢 318", "callback_data": f"ESTADO_{sid}_318"}
            ],
            [{"text": "⬅", "callback_data": "CAMBIAR"}]
        ]
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
            self.session.get(LOGIN_URL, timeout=5)
            r = self.session.post(LOGIN_URL, data={
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            }, timeout=5)
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=8)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")

            servicios = {}
            for b in re.split(r"\n(?=\d{7,8}\s)", text):
                m = re.search(r"\d{7,8}", b)
                if m:
                    servicios[m.group()] = " ".join(b.split())
            return servicios
        except:
            return {}

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=8)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")

            servicios = {}
            for b in re.split(r"\n(?=\d{7,8}\s)", text):
                m = re.search(r"\d{7,8}", b)
                if m:
                    servicios[m.group()] = " ".join(b.split())
            return servicios
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado,
                "FECSIG": fecha.strftime("%d/%m/%Y"),
                "INFORMO": "on",
                "Observaciones": "Auto",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            self.session.post(BASE_URL, data=payload, timeout=5)
            return True, f"Estado {estado} aplicado"
        except:
            return False, "Error"

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
                        tg_send(u, f"🆕 {txt}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales

        except:
            homeserve.login()

        time.sleep(INTERVALO)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])

        if action == "LOGIN":
            tg_edit(chat, msg_id, "Login OK" if homeserve.login() else "Error", botones())

        elif action == "REFRESH":
            tg_edit(chat, msg_id, f"{len(homeserve.obtener())} servicios", botones())

        elif action == "WEB":
            servicios = homeserve.obtener()
            WEB_CACHE[chat] = list(servicios.items())
            WEB_INDEX[chat] = 0

            if WEB_CACHE[chat]:
                sid, txt = WEB_CACHE[chat][0]
                tg_edit(chat, msg_id, txt, botones_servicio(sid))

        elif action == "WEB_NEXT":
            WEB_INDEX[chat] = (WEB_INDEX[chat] + 1) % len(WEB_CACHE[chat])
            sid, txt = WEB_CACHE[chat][WEB_INDEX[chat]]
            tg_edit(chat, msg_id, txt, botones_servicio(sid))

        elif action == "WEB_PREV":
            WEB_INDEX[chat] = (WEB_INDEX[chat] - 1) % len(WEB_CACHE[chat])
            sid, txt = WEB_CACHE[chat][WEB_INDEX[chat]]
            tg_edit(chat, msg_id, txt, botones_servicio(sid))

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            ok, msg = homeserve.cambiar_estado(sid, "318")
            tg_edit(chat, msg_id, msg, botones())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            ok, msg = homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, msg, botones())

        elif action == "CAMBIAR":
            tg_edit(chat, msg_id, "Servicios", lista_servicios(homeserve.obtener_curso()))

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, sid, botones_estado(sid))

        elif action.startswith("ESTADO_"):
            _, sid, estado = action.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            tg_edit(chat, msg_id, msg, botones_estado(sid))

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
