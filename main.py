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
                {"text": "🌐 Web", "callback_data": "WEB"},
                {"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}
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
    botones = {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
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

    def obtener(self):
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

            logger.info(f"Servicios: {len(servicios)}")
            return servicios

        except Exception as e:
            logger.error(f"Error obtener: {e}")
            return {}

    def cambiar_estado_servicio(self, idserv, estado):
        """
        Función dummy para cambiar el estado del servicio.
        Dependiendo de la web, aquí se puede hacer POST con idserv y estado.
        """
        try:
            # TODO: Implementar POST real según el endpoint de cambio de estado
            logger.info(f"Cambiando estado {idserv} -> {estado}")
            return True
        except Exception as e:
            logger.error(f"Error cambiar estado: {e}")
            return False

homeserve = HomeServe()

# ---------------- LOOP ----------------
def bot_loop():
    global SERVICIOS_ACTUALES

    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES and idserv not in SERVICIOS_ESTADO:
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
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener())
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            actuales = homeserve.obtener()
            if actuales:
                txt = "🌐 <b>Web</b>\n\n"
                for s in actuales.values():
                    txt += s + "\n\n"
            else:
                txt = "Nada encontrado"
            enviar(chat, txt)

        # ---------------- NUEVOS BOTONES ----------------
        elif accion.startswith("ACEPTAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "ACEPTADO"
            enviar(chat, f"✅ Servicio {servicio_id} aceptado")

        elif accion.startswith("RECHAZAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "RECHAZADO"
            enviar(chat, f"❌ Servicio {servicio_id} rechazado")

        # ---------------- CAMBIAR ESTADO ----------------
        elif accion == "CAMBIAR_ESTADO":
            servicios = homeserve.obtener()  # Servicios en curso
            if not servicios:
                enviar(chat, "No hay servicios en curso.")
                return jsonify(ok=True)

            for idserv, texto_servicio in servicios.items():
                botones = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Pendiente", "callback_data": f"ESTADO_{idserv}_PENDIENTE"},
                            {"text": "🔧 En Proceso", "callback_data": f"ESTADO_{idserv}_ENPROCESO"},
                            {"text": "✔️ Finalizado", "callback_data": f"ESTADO_{idserv}_FINALIZADO"}
                        ]
                    ]
                }
                requests.post(
                    TELEGRAM_API + "/sendMessage",
                    json={
                        "chat_id": chat,
                        "text": f"<b>Servicio {idserv}</b>\n\n{texto_servicio}",
                        "parse_mode": "HTML",
                        "reply_markup": botones
                    }
                )

        elif accion.startswith("ESTADO_"):
            _, idserv, nuevo_estado = accion.split("_")
            exito = homeserve.cambiar_estado_servicio(idserv, estado=nuevo_estado)
            if exito:
                SERVICIOS_ESTADO[idserv] = nuevo_estado
                enviar(chat, f"✅ Servicio {idserv} cambiado a {nuevo_estado}")
            else:
                enviar(chat, f"❌ No se pudo cambiar el estado del servicio {idserv}")

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
