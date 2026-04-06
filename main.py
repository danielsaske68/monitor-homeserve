import os
import time
import threading
import logging
import re
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

load_dotenv()

# ---------------- CONFIG ----------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 60))

if not all([USUARIO, PASSWORD, BOT_TOKEN, CHAT_ID]):
    raise ValueError("Faltan variables de entorno")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"
CAMBIO_ESTADO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=cambiar_estado_servicio"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}
SERVICIOS_ESTADO = {}
SERVICIOS_CURSO = {}

# ---------------- BOTONES GENERALES ----------------
def botones_generales():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}]
        ]
    }

def enviar(chat, texto):
    import requests
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones_generales()
        }
    )

def enviar_estado_servicio(chat, servicio_id, texto):
    import requests
    botones = {
        "inline_keyboard": [
            [
                {"text": "🟡 En progreso", "callback_data": f"ESTADO_{servicio_id}_307"},
                {"text": "✅ Finalizado", "callback_data": f"ESTADO_{servicio_id}_308"}
            ]
        ]
    }
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones
        }
    )

# ---------------- HOMESERVE CON PLAYWRIGHT ----------------
class HomeServe:
    def __init__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def login(self):
        try:
            self.page.goto(LOGIN_URL)
            self.page.fill('input[name="CODIGO"]', USUARIO)
            self.page.fill('input[name="PASSW"]', PASSWORD)
            self.page.click('input[name="BTN"]')
            self.page.wait_for_load_state("networkidle", timeout=10000)
            
            content = self.page.content()
            if "error" in content.lower():
                logger.error("Login fallo")
                return False
            
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener_servicios_en_curso(self):
        try:
            self.page.goto(SERVICIOS_CURSO_URL)
            self.page.wait_for_load_state("networkidle", timeout=10000)
            html = self.page.content()
            
            soup = BeautifulSoup(html, "html.parser")
            texto = soup.get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    idserv = m.group(0)
                    limpio = " ".join(b.split())
                    servicios[idserv] = limpio
            logger.info(f"Servicios en curso: {len(servicios)}")
            return servicios
        except Exception as e:
            logger.error(f"Error obtener servicios en curso: {e}")
            return {}

    def cambiar_estado_servicio(self, servicio_id, nuevo_estado):
        try:
            self.page.goto(f"{CAMBIO_ESTADO_URL}?SERVICIO={servicio_id}")
            self.page.wait_for_load_state("networkidle", timeout=10000)

            fecha_siguiente = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")

            self.page.fill('input[name="FECSIG"]', fecha_siguiente)
            self.page.select_option('select[name="ESTADO"]', nuevo_estado)
            self.page.check('input[name="INFORMO"]')
            self.page.fill('textarea[name="Observaciones"]', "A la espera de contactar con cliente")
            self.page.click('input[name="BTNCAMBIAESTADO"]')
            self.page.wait_for_load_state("networkidle", timeout=10000)

            logger.info(f"✔ Estado enviado correctamente para servicio {servicio_id}")
            return True
        except Exception as e:
            logger.error(f"Error cambiando estado del servicio {servicio_id}: {e}")
            return False

    def close(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()


homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    homeserve.login()
    while True:
        try:
            SERVICIOS_CURSO.update(homeserve.obtener_servicios_en_curso())
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios: {len(SERVICIOS_CURSO)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")
        elif accion == "REFRESH":
            SERVICIOS_CURSO.update(homeserve.obtener_servicios_en_curso())
            enviar(chat, "🔄 Actualizado")
        elif accion == "WEB":
            txt = ""
            for s in SERVICIOS_CURSO.values():
                txt += s + "\n\n"
            enviar(chat, txt if txt else "Nada encontrado")
        elif accion == "CAMBIAR_ESTADO":
            for idserv, servicio in SERVICIOS_CURSO.items():
                enviar_estado_servicio(chat, idserv, f"🔧 <b>Cambiar estado</b>\n\n{servicio}")
        elif accion.startswith("ESTADO_"):
            parts = accion.split("_")
            servicio_id, nuevo_estado = parts[1], parts[2]
            ok = homeserve.cambiar_estado_servicio(servicio_id, nuevo_estado)
            if ok:
                SERVICIOS_ESTADO[servicio_id] = nuevo_estado
                enviar(chat, f"🛠 Servicio {servicio_id} cambiado a: {nuevo_estado}")
            else:
                enviar(chat, f"❌ Error cambiando estado del servicio {servicio_id}")
    elif "message" in data:
        chat = data["message"]["chat"]["id"]
        if data["message"].get("text") == "/start":
            enviar(chat, "👋 Bot activo con control total")
    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
