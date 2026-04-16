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

BASE_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN")  # 🔥 FIX IMPORTANTE

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

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    return [r[0] for r in c.fetchall()]

init_db()

# ---------------- TELEGRAM SAFE ----------------
def tg_send(chat, text, markup=None):
    try:
        payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
        if markup:
            payload["reply_markup"] = markup
        return requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"tg_send error: {e}")

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
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"tg_edit error: {e}")

def tg_answer(callback_id):
    try:
        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5
        )
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
                {"text": "🌐 Web", "callback_data": "WEB"}
            ],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}]
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
            {"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{sid}_348"},
            {"text": "🟢 En espera", "callback_data": f"ESTADO_{sid}_318"}
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
            logger.error(f"login error: {e}")
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
            logger.error(f"obtener error: {e}")
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            obs = "Pendiente cliente" if estado == "348" else "En espera"

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
            logger.error(f"loop error: {e}")
            homeserve.login()
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)

        if not data:
            return jsonify(ok=True)

        logger.info(f"📩 UPDATE: {data}")

        # ---------------- MESSAGE ----------------
        if "message" in data:
            chat = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")

            guardar_usuario(chat)

            logger.info(f"💬 MSG {chat}: {text}")

            if text == "/start":
                tg_send(chat, "🤖 Bot activo", botones())

        # ---------------- CALLBACK (CLAVE) ----------------
        if "callback_query" in data:
            cq = data["callback_query"]

            chat = cq["message"]["chat"]["id"]
            msg_id = cq["message"]["message_id"]
            action = cq["data"]
            cid = cq["id"]

            logger.info(f"🔥 CALLBACK {chat}: {action}")

            tg_answer(cid)
            guardar_usuario(chat)

            if action == "LOGIN":
                ok = homeserve.login()
                tg_edit(chat, msg_id, "LOGIN OK" if ok else "ERROR", botones())

            elif action == "REFRESH":
                servicios = homeserve.obtener()
                tg_edit(chat, msg_id, f"{len(servicios)} servicios", botones())

            elif action == "WEB":
                actuales = homeserve.obtener()
                if actuales:
                    sid, txt = list(actuales.items())[0]
                    tg_edit(chat, msg_id, txt, botones_servicio(sid))
                else:
                    tg_edit(chat, msg_id, "Sin servicios", botones())

            elif action.startswith("ACEPTAR_"):
                sid = action.split("_")[1]
                ok, msg = homeserve.cambiar_estado(sid, "318")
                tg_edit(chat, msg_id, msg, botones())

            elif action.startswith("RECHAZAR_"):
                sid = action.split("_")[1]
                ok, msg = homeserve.cambiar_estado(sid, "348")
                tg_edit(chat, msg_id, msg, botones())

        return jsonify(ok=True)

    except Exception as e:
        logger.error(f"WEBHOOK CRASH: {e}")
        return jsonify(ok=True)

# ---------------- WEBHOOK SET ----------------
def set_webhook():
    if not BASE_DOMAIN:
        logger.warning("NO DOMAIN")
        return

    url = f"https://{BASE_DOMAIN}/telegram_webhook"
    try:
        r = requests.get(f"{TELEGRAM_API}/setWebhook?url={url}")
        logger.info(f"WEBHOOK: {r.text}")
    except Exception as e:
        logger.error(f"webhook error: {e}")

# ---------------- START ----------------
set_webhook()
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 BOT INICIADO")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
