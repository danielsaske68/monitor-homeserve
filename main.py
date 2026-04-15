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
logger = logging.getLogger("bot")

# ---------------- APP ----------------
app = Flask(__name__)

SERVICIOS_ACTUALES = {}
WEB_CACHE = {}
WEB_INDEX = {}
USER_STATE = {}

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

def eliminar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))
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

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    return requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

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

def botones_usuarios():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar usuario", "callback_data": "ADD_USER"}],
            [{"text": "📋 Listar usuarios", "callback_data": "LIST_USERS"}],
            [{"text": "🗑 Eliminar usuario", "callback_data": "DEL_USER"}],
            [{"text": "⬅ Volver", "callback_data": "BACK_MENU"}]
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
                {"text": "⬅ Anterior", "callback_data": "WEB_PREV"},
                {"text": "➡ Siguiente", "callback_data": "WEB_NEXT"}
            ],
            [{"text": "🏠 Menú", "callback_data": "BACK_MENU"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{sid}_348"},
                {"text": "🟢 En espera", "callback_data": f"ESTADO_{sid}_318"}
            ],
            [{"text": "⬅ Volver", "callback_data": "CAMBIAR"}]
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

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"
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
            return True, f"Estado {estado} aplicado"
        except Exception as e:
            return False, f"Error: {e}"

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
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        guardar_usuario(chat)

        if chat in USER_STATE:
            if USER_STATE[chat] == "ADD_USER":
                guardar_usuario(text)
                tg_send(chat, f"✅ Usuario añadido: {text}")
                USER_STATE.pop(chat)

            elif USER_STATE[chat] == "DEL_USER":
                eliminar_usuario(text)
                tg_send(chat, f"🗑 Usuario eliminado: {text}")
                USER_STATE.pop(chat)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

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
            servicios = homeserve.obtener()
            WEB_CACHE[chat] = list(servicios.items())
            WEB_INDEX[chat] = 0

            if not WEB_CACHE[chat]:
                tg_edit(chat, msg_id, "Sin servicios", botones())
            else:
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

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

        elif action == "USUARIOS":
            tg_edit(chat, msg_id, "👥 Panel de usuarios", botones_usuarios())

        elif action == "ADD_USER":
            USER_STATE[chat] = "ADD_USER"
            tg_send(chat, "✍️ Envía el ID del usuario")

        elif action == "DEL_USER":
            USER_STATE[chat] = "DEL_USER"
            tg_send(chat, "🗑 Envía el ID a eliminar")

        elif action == "LIST_USERS":
            tg_edit(chat, msg_id, "\n".join(obtener_usuarios()) or "Sin usuarios", botones_usuarios())

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            ok, msg = homeserve.cambiar_estado(sid, "318")
            tg_edit(chat, msg_id, f"✅ {msg}", botones())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            ok, msg = homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, f"❌ {msg}", botones())

        elif action == "CAMBIAR":
            curso = homeserve.obtener_curso()
            tg_edit(chat, msg_id, "🛠 Selecciona servicio:", lista_servicios(curso))

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
