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

BASE_WEBHOOK_URL = "https://monitor-homeserve-production.up.railway.app/telegram_webhook"

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

# ---------------- VARIABLES ----------------
SERVICIOS_ACTUALES = {}
app = Flask(__name__)

# ---------------- DATABASE ----------------
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
    usuarios = [row[0] for row in c.fetchall()]
    conn.close()
    return usuarios

init_db()

# ---------------- TELEGRAM ----------------
def enviar(chat, texto, botones=None):
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones

    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")

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

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()
        self.last_login = 0

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)

            if "error" in r.text.lower():
                logger.error("❌ Login falló")
                return False

            self.last_login = time.time()
            logger.info("✅ Login OK")
            return True

        except Exception as e:
            logger.error(f"❌ Error login: {e}")
            return False

    def asegurar_login(self):
        # Re-login cada 10 minutos
        if time.time() - self.last_login > 600:
            logger.info("🔄 Renovando sesión...")
            return self.login()
        return True

    def obtener(self):
        try:
            self.asegurar_login()

            r = self.session.get(ASIGNACION_URL, timeout=15)

            # 🔥 detectar sesión caída
            if "login" in r.text.lower():
                logger.warning("⚠️ Sesión expirada")
                self.login()
                return {}

            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)

            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())

            return servicios

        except Exception as e:
            logger.error(f"💥 Error obteniendo servicios: {e}")
            return {}

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Monitor iniciado")

    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            logger.info(f"📊 Servicios detectados: {len(actuales)}")

            nuevos = 0

            for sid, s in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    nuevos += 1
                    logger.info(f"🆕 Nuevo servicio: {sid}")

                    for u in obtener_usuarios():
                        enviar(u, f"🆕 <b>Nuevo servicio</b>\n\n{s}", botones_servicio(sid))

            if nuevos == 0:
                logger.info("😴 Sin nuevos")

            SERVICIOS_ACTUALES = actuales

            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"💥 Error loop: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        guardar_usuario(chat)

        if data["message"].get("text") == "/start":
            enviar(chat, "🤖 Bot activo", botones())

    if "callback_query" in data:
        chat = data["callback_query"]["message"]["chat"]["id"]
        accion = data["callback_query"]["data"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error", botones())

        elif accion == "REFRESH":
            servicios = homeserve.obtener()
            enviar(chat, f"🔄 {len(servicios)} servicios encontrados", botones())

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if not actuales:
                enviar(chat, "No hay servicios")
            else:
                for sid, s in actuales.items():
                    enviar(chat, f"📋 {s}", botones_servicio(sid))

    return jsonify(ok=True)

# ---------------- CONFIG WEBHOOK ----------------
def configurar_webhook():
    try:
        url = f"{TELEGRAM_API}/setWebhook?url={BASE_WEBHOOK_URL}"
        r = requests.get(url)
        logger.info(f"🌐 Webhook configurado: {r.text}")
    except Exception as e:
        logger.error(f"Error configurando webhook: {e}")

# ---------------- INICIO ----------------
configurar_webhook()

threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
