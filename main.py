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

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_NUEVOS = {}
SERVICIOS_CURSO = {}
SERVICIOS_ESTADO = {}

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
        json={"chat_id": chat, "text": texto, "parse_mode": "HTML", "reply_markup": botones_generales()}
    )

def enviar_servicio(chat, servicio_id, texto):
    botones = {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}
            ],
            [{"text": "🔄 Refresh", "callback_data": "REFRESH"}]
        ]
    }
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={"chat_id": chat, "text": texto, "parse_mode": "HTML", "reply_markup": botones}
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
        json={"chat_id": chat, "text": texto, "parse_mode": "HTML", "reply_markup": botones}
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

    # Obtener servicios nuevos
    def obtener_servicios_nuevos(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
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
            logger.info(f"Servicios nuevos: {len(servicios)}")
            return servicios
        except Exception as e:
            logger.error(f"Error obtener servicios nuevos: {e}")
            return {}

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

    # Cambiar estado de un servicio
    def cambiar_estado_servicio(self, servicio_id, estado):
        try:
            logger.info(f"🔧 Cambiando estado servicio {servicio_id}")
            url_servicio = f"{SERVICIOS_CURSO_URL}&ID={servicio_id}"
            r = self.session.get(url_servicio, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            # Buscar input tipo IMAGE con name repaso
            input_estado = soup.find("input", {"name": "repaso", "type": "IMAGE"})
            if not input_estado:
                logger.error(f"No se encontró el formulario de cambio de estado para {servicio_id}")
                return False
            post_url = r.url
            payload = {
                input_estado["name"]: input_estado.get("value", ""),
                "fecha": datetime.now().strftime("%d/%m/%Y"),
                "estado": estado
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": url_servicio
            }
            r_post = self.session.post(post_url, data=payload, headers=headers, timeout=15)
            if r_post.status_code == 200:
                logger.info(f"✅ Estado cambiado servicio {servicio_id} a {estado}")
                return True
            else:
                logger.error(f"Error POST estado servicio {servicio_id} - Status {r_post.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error al cambiar estado del servicio {servicio_id}: {e}")
            return False

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_NUEVOS, SERVICIOS_CURSO

    homeserve.login()

    while True:
        try:
            nuevos = homeserve.obtener_servicios_nuevos()
            en_curso = homeserve.obtener_servicios_en_curso()

            # Enviar solo servicios realmente nuevos
            for idserv, servicio in nuevos.items():
                if idserv not in SERVICIOS_NUEVOS:
                    enviar_servicio(CHAT_ID, idserv, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")

            SERVICIOS_NUEVOS = nuevos
            SERVICIOS_CURSO = en_curso

            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios nuevos: {len(SERVICIOS_NUEVOS)} - En curso: {len(SERVICIOS_CURSO)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    global SERVICIOS_ESTADO, SERVICIOS_CURSO

    data = request.json
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        # BOTONES GENERALES
        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            nuevos = homeserve.obtener_servicios_nuevos()
            en_curso = homeserve.obtener_servicios_en_curso()
            SERVICIOS_NUEVOS.update(nuevos)
            SERVICIOS_CURSO.update(en_curso)
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            txt = "🌐 <b>Web</b>\n\n"
            for s in SERVICIOS_NUEVOS.values():
                txt += s + "\n\n"
            enviar(chat, txt if SERVICIOS_NUEVOS else "Nada encontrado")

        elif accion == "CAMBIAR_ESTADO":
            if SERVICIOS_CURSO:
                for idserv, servicio in SERVICIOS_CURSO.items():
                    enviar_estado_servicio(chat, idserv, f"🔧 <b>Cambiar estado</b>\n\n{servicio}")
            else:
                enviar(chat, "No hay servicios en curso para cambiar estado.")

        # SERVICIOS NUEVOS
        elif accion.startswith("ACEPTAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "ACEPTADO"
            enviar(chat, f"✅ Servicio {servicio_id} aceptado")

        elif accion.startswith("RECHAZAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "RECHAZADO"
            enviar(chat, f"❌ Servicio {servicio_id} rechazado")

        # CAMBIO DE ESTADO EN CURSO
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
