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

def tg_answer(cid):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                  json={"callback_query_id": cid},
                  timeout=10)

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [
                {"text": "🔐 Login", "callback_data": "LOGIN"},
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ],
            [{"text": "🌐 Web", "callback_data": "WEB"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [[
            {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
            {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
        ]]
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
            logger.error(f"LOGIN ERROR: {e}")
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
        except Exception as e:
            logger.error(f"OBTENER ERROR: {e}")
            return {}

    def aceptar(self, sid):
        try:
            self.session.post(BASE_URL, data={
                "w3exec": "prof_asignacion",
                "servicio": sid,
                "ACEPTAR": "Aceptar"
            }, timeout=10)
            return True, f"✅ Servicio {sid} aceptado"
        except Exception as e:
            return False, str(e)

    def rechazar(self, sid):
        try:
            self.session.post(BASE_URL, data={
                "w3exec": "prof_asignacion",
                "servicio": sid,
                "RECHAZAR": "Rechazar"
            }, timeout=10)
            return True, f"❌ Servicio {sid} rechazado"
        except Exception as e:
            return False, str(e)

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 LOOP INICIADO")
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()
            logger.info(f"📊 servicios: {len(actuales)}")

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 nuevo servicio {sid}")
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"LOOP ERROR: {e}")
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        logger.info(f"📩 UPDATE: {data}")

        # -------- MESSAGE --------
        if "message" in data:
            chat = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            guardar_usuario(chat)

            logger.info(f"💬 MSG {chat}: {text}")

            if text == "/start":
                tg_send(chat, "🤖 Bot activo", botones())

        # -------- CALLBACK --------
        elif "callback_query" in data:
            cq = data["callback_query"]
            chat = cq["message"]["chat"]["id"]
            msg_id = cq["message"]["message_id"]
            action = cq["data"]

            logger.info(f"🔥 CALLBACK {chat}: {action}")

            tg_answer(cq["id"])
            guardar_usuario(chat)

            if action == "LOGIN":
                ok = homeserve.login()
                tg_edit(chat, msg_id, "OK" if ok else "ERROR", botones())

            elif action == "REFRESH":
                tg_edit(chat, msg_id, f"{len(homeserve.obtener())} servicios", botones())

            elif action == "WEB":
                servicios = homeserve.obtener()
                if not servicios:
                    tg_edit(chat, msg_id, "Sin servicios", botones())
                else:
                    sid, txt = list(servicios.items())[0]
                    tg_edit(chat, msg_id, txt, botones_servicio(sid))

            elif action.startswith("ACEPTAR_"):
                sid = action.split("_")[1]
                ok, msg = homeserve.aceptar(sid)
                tg_edit(chat, msg_id, msg, botones())

            elif action.startswith("RECHAZAR_"):
                sid = action.split("_")[1]
                ok, msg = homeserve.rechazar(sid)
                tg_edit(chat, msg_id, msg, botones())

        return jsonify(ok=True), 200

    except Exception as e:
        logger.error(f"WEBHOOK CRASH: {e}")
        return jsonify(ok=True), 200


# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 BOT INICIADO")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
