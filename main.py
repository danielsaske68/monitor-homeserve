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

# ---------------- VARIABLES ----------------
SERVICIOS_ACTUALES = {}
PANEL = {}
app = Flask(__name__)

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
def enviar(chat, texto, botones=None, editar=False):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones

    try:
        if editar and chat in PANEL:
            data["message_id"] = PANEL[chat]
            requests.post(f"{TELEGRAM_API}/editMessageText", json=data, timeout=10)
        else:
            r = requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10)
            if r.ok:
                PANEL[chat] = r.json()["result"]["message_id"]
    except Exception as e:
        logger.error(f"Telegram error: {e}")

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR"}]
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
            {"text": "🔴 348", "callback_data": f"ESTADO_{sid}_348"},
            {"text": "🟢 318", "callback_data": f"ESTADO_{sid}_318"}
        ]]
    }

def lista_servicios(servicios):
    return {"inline_keyboard": [[{"text": sid, "callback_data": f"SEL_{sid}"}] for sid in servicios]}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
        self.session.get(LOGIN_URL)
        r = self.session.post(LOGIN_URL, data=payload)
        return "error" not in r.text.lower()

    def obtener(self):
        r = self.session.get(ASIGNACION_URL)
        texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
        bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
        servicios = {}
        for b in bloques:
            m = re.search(r"\b\d{7,8}\b", b)
            if m:
                servicios[m.group(0)] = " ".join(b.split())
        return servicios

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, s in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🆕 Nuevo servicio: {sid}")
                    for u in obtener_usuarios():
                        enviar(u, f"🆕 <b>Nuevo servicio</b>\n\n{s}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- WEBHOOK (FIX REAL) ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True, silent=True)

    if not data:
        return jsonify(ok=True)

    # ---------------- MESSAGE ----------------
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Hola, en qué puedo ayudar", botones_generales())

    # ---------------- CALLBACK BUTTONS ----------------
    if "callback_query" in data:
        cq = data["callback_query"]
        accion = cq["data"]
        chat = cq["message"]["chat"]["id"]

        # ⭐⭐⭐ ESTO ES LO QUE TE FALTABA (CRÍTICO)
        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": cq["id"]},
            timeout=5
        )

        guardar_usuario(chat)

        last_msg_id = cq["message"]["message_id"]

        logger.info(f"🔘 Botón recibido: {accion}")

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login", last_msg_id=last_msg_id)

        elif accion == "REFRESH":
            actuales = homeserve.obtener()
            enviar(chat, f"🔄 Servicios: {len(actuales)}", last_msg_id=last_msg_id)

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if not actuales:
                enviar(chat, "No hay servicios", last_msg_id=last_msg_id)
            else:
                for sid, servicio in actuales.items():
                    enviar(chat, f"📋 {servicio}", botones_servicio_nuevo(sid))

        elif accion == "CAMBIAR_ESTADO":
            curso = homeserve.obtener_curso()
            enviar(chat, "🛠 Selecciona servicio:", botones_lista_servicios(curso), last_msg_id=last_msg_id)

        elif accion.startswith("SEL_"):
            sid = accion.split("_")[1]
            enviar(chat, f"🔧 Servicio {sid}", botones_estado(sid), last_msg_id=last_msg_id)

        elif accion.startswith("ESTADO_"):
            _, sid, estado = accion.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            enviar(chat, msg, last_msg_id=last_msg_id)

        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.aceptar_servicio(sid)
            enviar(chat, msg, last_msg_id=last_msg_id)

        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.rechazar_servicio(sid)
            enviar(chat, msg, last_msg_id=last_msg_id)

    return jsonify(ok=True)

        # ---------------- /START ----------------
        elif "message" in data:
            msg = data["message"]
            chat = msg["chat"]["id"]

            guardar_usuario(chat)

            if msg.get("text") == "/start":
                enviar(chat, "🤖 Bot activo", botones())

        return jsonify(ok=True)

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
