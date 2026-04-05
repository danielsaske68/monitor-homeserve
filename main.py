import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime

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
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}
SERVICIOS_ESTADO = {}
SERVICIOS_CURSO = {}

# ---------------- BOTONES ----------------
def botones_generales():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}]
        ]
    }

def enviar(chat, texto):
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
    botones = {
        "inline_keyboard": [
            [
                {"text": "🟡 En progreso", "callback_data": f"ESTADO_{servicio_id}_ENPROGRESO"},
                {"text": "✅ Finalizado", "callback_data": f"ESTADO_{servicio_id}_FINALIZADO"}
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

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallo")
                return False
            logger.info("Login OK")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    # Obtener servicios en curso
    def obtener_servicios_en_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
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

    # Cambiar estado con fecha
    def cambiar_estado(self, servicio_id, nuevo_estado):
        try:
            logger.info(f"🔧 Cambiando estado servicio {servicio_id}")
            # 1️⃣ Obtener lista de servicios en curso
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # 2️⃣ Buscar el bloque que contiene el servicio_id
            form = None
            for input_tag in soup.find_all("input", {"name": "repaso"}):
                parent_form = input_tag.find_parent("form")
                if parent_form and servicio_id in parent_form.get_text():
                    form = parent_form
                    break

            if not form:
                logger.error(f"No se encontró el formulario de cambio de estado para {servicio_id}")
                return False

            # 3️⃣ Construir payload
            action = form.get("action")
            if not action.startswith("http"):
                action = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe" + action

            payload = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    payload[name] = value

            # 4️⃣ Actualizar estado y fecha
            payload["ESTADO"] = nuevo_estado
            fecha_hoy = datetime.today().strftime("%d/%m/%Y")
            payload["FECHA"] = fecha_hoy

            # 5️⃣ POST
            self.session.post(action, data=payload, timeout=15)
            logger.info(f"✅ Estado de {servicio_id} cambiado a {nuevo_estado} con fecha {fecha_hoy}")
            return True

        except Exception as e:
            logger.error(f"Error al cambiar estado del servicio {servicio_id}: {e}")
            return False

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_CURSO
    homeserve.login()
    while True:
        try:
            SERVICIOS_CURSO = homeserve.obtener_servicios_en_curso()
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios en curso: {len(SERVICIOS_CURSO)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    global SERVICIOS_ESTADO

    data = request.json
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            SERVICIOS_CURSO = homeserve.obtener_servicios_en_curso()
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            txt = "🌐 <b>Servicios en curso</b>\n\n"
            for s in SERVICIOS_CURSO.values():
                txt += s + "\n\n"
            enviar(chat, txt if SERVICIOS_CURSO else "Nada encontrado")

        elif accion == "CAMBIAR_ESTADO":
            if SERVICIOS_CURSO:
                for idserv, servicio in SERVICIOS_CURSO.items():
                    enviar_estado_servicio(chat, idserv, f"🔧 <b>Cambiar estado</b>\n\n{servicio}")
            else:
                enviar(chat, "No hay servicios en curso para cambiar estado.")

        elif accion.startswith("ESTADO_"):
            parts = accion.split("_")
            servicio_id, nuevo_estado = parts[1], parts[2]
            ok = homeserve.cambiar_estado(servicio_id, nuevo_estado)
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
