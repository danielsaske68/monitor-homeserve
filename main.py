import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv

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
SERVICIOS_EN_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

SERVICIOS_ACTUALES = {}
SERVICIOS_ESTADO = {}

# ---------------- BOTONES GENERALES ----------------
def botones_generales():
    return {
        "inline_keyboard": [
            [
                {"text": "🔐 Login", "callback_data": "LOGIN"},
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ],
            [
                {"text": "📋 Guardados", "callback_data": "GUARDADOS"}
            ],
            [
                {"text": "🌐 Web", "callback_data": "WEB"}
            ],
            [
                {"text": "🌐 Ir asignación", "url": ASIGNACION_URL}
            ]
        ]
    }

# ---------------- TELEGRAM ----------------
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

def enviar_servicio(chat, servicio_id, texto):
    estado = SERVICIOS_ESTADO.get(servicio_id, "PENDIENTE")
    botones = {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"},
                {"text": "🔄 Pendiente", "callback_data": f"PENDIENTE_{servicio_id}"}
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ]
        ]
    }

    texto_completo = f"{texto}\n\n<b>Estado actual:</b> {estado}"
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto_completo,
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
            payload = {
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            }
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

    def obtener_asignacion(self):
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

            logger.info(f"Servicios asignación: {len(servicios)}")
            return servicios

        except Exception as e:
            logger.error(f"Error obtener_asignacion: {e}")
            return {}

    def obtener_en_curso(self):
        """
        Obtiene servicios en curso y actualiza SERVICIOS_ESTADO
        """
        try:
            r = self.session.get(SERVICIOS_EN_CURSO_URL, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            texto = soup.get_text("\n")

            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            nuevos_servicios = 0

            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicio_id = m.group(0)
                    limpio = " ".join(b.split())
                    if servicio_id not in SERVICIOS_ESTADO:
                        SERVICIOS_ESTADO[servicio_id] = "PENDIENTE"
                        nuevos_servicios += 1
                        logger.info(f"Servicio {servicio_id} agregado como PENDIENTE")

            logger.info(f"Total nuevos servicios en curso: {nuevos_servicios}")
            return nuevos_servicios

        except Exception as e:
            logger.error(f"Error obtener_en_curso: {e}")
            return 0

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    homeserve.login()
    homeserve.obtener_en_curso()

    while True:
        try:
            actuales = homeserve.obtener_asignacion()

            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES and idserv not in SERVICIOS_ESTADO:
                    SERVICIOS_ESTADO[idserv] = "PENDIENTE"
                    enviar_servicio(
                        CHAT_ID,
                        idserv,
                        f"🆕 <b>Nuevo servicio</b>\n\n{servicio}"
                    )

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(20)

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"OK - Servicios: {len(SERVICIOS_ACTUALES)}"

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    global SERVICIOS_ESTADO

    data = request.json

    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        # ---------------- BOTONES ANTIGUOS ----------------
        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Andamos Ready mi rey" if ok else "❌ Error login")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener_asignacion())
            homeserve.obtener_en_curso()
            enviar(chat, "🔄 Actualizado")

        elif accion == "GUARDADOS":
            if SERVICIOS_ACTUALES:
                txt = "📋 <b>Servicios</b>\n\n"
                for s in SERVICIOS_ACTUALES.values():
                    txt += s + "\n\n"
            else:
                txt = "tamos pailas"
            enviar(chat, txt)

        elif accion == "WEB":
            actuales = homeserve.obtener_asignacion()
            if actuales:
                txt = "🌐 <b>Web</b>\n\n"
                for s in actuales.values():
                    txt += s + "\n\n"
            else:
                txt = "No hay nada mi rey"
            enviar(chat, txt)

        # ---------------- NUEVOS BOTONES DE ESTADO ----------------
        elif accion.startswith(("ACEPTAR_", "RECHAZAR_", "PENDIENTE_")):
            servicio_id = accion.split("_")[1]
            if accion.startswith("ACEPTAR_"):
                SERVICIOS_ESTADO[servicio_id] = "ACEPTADO"
            elif accion.startswith("RECHAZAR_"):
                SERVICIOS_ESTADO[servicio_id] = "RECHAZADO"
            elif accion.startswith("PENDIENTE_"):
                SERVICIOS_ESTADO[servicio_id] = "PENDIENTE"

            enviar(chat, f"🔄 Estado de servicio {servicio_id} actualizado a <b>{SERVICIOS_ESTADO[servicio_id]}</b>")

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
