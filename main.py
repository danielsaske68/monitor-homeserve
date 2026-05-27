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

# NUEVO STATE (SERVICIOS TXT)
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

# ---------------- FILE SERVICES ----------------
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
    logger.info(f"SEND -> {chat}: {text}")
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

def tg_edit(chat, msg_id, text, markup=None):
    logger.info(f"EDIT -> {chat}: {text}")
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
            [{"text": "📦 Numero de servicios", "callback_data": "NUM_SERV"}]
        ]
    }

def botones_num_serv():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar servicio", "callback_data": "ADD_SERV"}],
            [{"text": "🗑 Eliminar archivo", "callback_data": "DEL_SERV"}],
            [{"text": "📥 Descargar", "callback_data": "DOWN_SERV"}],
            [{"text": "👁 Ver", "callback_data": "VIEW_SERV"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
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
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
            ],
            [{"text": "⬅️ Volver", "callback_data": "WEB"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 348 Cliente", "callback_data": f"ESTADO_{sid}_348"},
                {"text": "🟢 318 Confirmación", "callback_data": f"ESTADO_{sid}_318"}
            ],
            [{"text": "⬅️ Volver", "callback_data": "CAMBIAR"}]
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
            logger.info("LOGIN OK" if "error" not in r.text.lower() else "LOGIN FAIL")
            return "error" not in r.text.lower()
        except Exception as e:
            logger.error(e)
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

            logger.info(f"SERVICIOS: {len(servicios)}")
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
    data = request.json
    logger.info(f"UPDATE: {data}")

    if not data:
        return jsonify(ok=True)

    # -------- MENSAJES --------
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        guardar_usuario(chat)

        logger.info(f"MESSAGE -> {chat}: {text}")

        # LOGIN STATE USERS
        if chat in USER_STATE:
            if USER_STATE[chat] == "ADD_USER":
                guardar_usuario(text)
                tg_send(chat, "✅ Usuario añadido")
                USER_STATE.pop(chat)

            elif USER_STATE[chat] == "DEL_USER":
                eliminar_usuario(text)
                tg_send(chat, "🗑 Usuario eliminado")
                USER_STATE.pop(chat)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

    # -------- CALLBACKS --------
    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        logger.info(f"CALLBACK -> {action}")

        tg_answer(cq["id"])
        guardar_usuario(chat)

        # 🔐 LOGIN
        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "✅ Login OK" if ok else "❌ Login FAIL", botones())

        # 🔄 REFRESH
        elif action == "REFRESH":
            servicios = homeserve.obtener()
            tg_edit(chat, msg_id, f"📦 {len(servicios)} servicios", botones())

        # 🌐 WEB
        elif action == "WEB":
            servicios = homeserve.obtener()
            WEB_CACHE[chat] = list(servicios.items())
            WEB_INDEX[chat] = 0

            if servicios:
                sid, txt = WEB_CACHE[chat][0]
                tg_edit(chat, msg_id, txt, botones_servicio(sid))
            else:
                tg_edit(chat, msg_id, "Sin servicios", botones())

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

        elif action == "USUARIOS":
            tg_edit(chat, msg_id, "Usuarios", botones_usuarios())

        elif action == "ADD_USER":
            USER_STATE[chat] = "ADD_USER"
            tg_send(chat, "Envía ID")

        elif action == "DEL_USER":
            USER_STATE[chat] = "DEL_USER"
            tg_send(chat, "Envía ID")

        elif action == "LIST_USERS":
            tg_edit(chat, msg_id, "\n".join(obtener_usuarios()) or "Vacío", botones_usuarios())

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            url = f"https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion&servicio={sid}"

            try:
                r = homeserve.session.get(url, timeout=15)
                html = r.text.lower()

                errores = ["error", "illegal", "denegado", "caducada", "no autorizado"]
                fallo = any(e in html for e in errores)

                if fallo:
                    tg_edit(chat, msg_id, "❌ Error al aceptar", botones())
                else:
                    tg_edit(chat, msg_id, f"✅ Servicio {sid} aceptado", botones())

            except Exception as e:
                tg_edit(chat, msg_id, f"❌ {e}", botones())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, "❌ Rechazado", botones())

        elif action == "CAMBIAR":
            curso = homeserve.obtener_curso()
            tg_edit(chat, msg_id, "Selecciona", lista_servicios(curso))

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"{sid}", botones_estado(sid))

        elif action.startswith("ESTADO_"):
            _, sid, estado = action.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            tg_edit(chat, msg_id, msg, botones_estado(sid))

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
