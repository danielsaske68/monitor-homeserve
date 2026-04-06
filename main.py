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
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# ---------------- VARIABLES GLOBALES ----------------
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
            [{"text": "🔄 Refresh", "callback_data": "REFRESH"}]
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

    # ---------------- CAMBIO DE ESTADO COMPLETO ----------------
    def cambiar_estado_servicio(self, servicio_id, nuevo_estado):
        try:
            BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"

            # Mapeo de estado fijo
            estado_valor = "348"  # Siempre "En espera de Cliente por indicaciones"
            fecha = datetime.now().strftime("%d/%m/%Y")

            # PASO 1: Abrir servicio
            url_servicio = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={servicio_id}&Pag=1"
            r1 = self.session.get(url_servicio, timeout=15)
            if "error" in r1.text.lower():
                logger.error("Error abriendo servicio")
                return False

            # PASO 2: Simular click en cambio de estado
            payload_click = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "Pag": "1",
                "repaso.x": "10",
                "repaso.y": "10"
            }
            r2 = self.session.post(BASE_URL, data=payload_click, timeout=15)
            if "Illegal command" in r2.text:
                logger.error("Error entrando a cambio estado")
                return False

            soup = BeautifulSoup(r2.text, "html.parser")
            pag_input = soup.find("input", {"name": "Pag"})
            pag = pag_input["value"] if pag_input else "1"
            logger.info(f"➡️ Pag detectado: {pag}")

            # PASO 3: Enviar formulario final
            payload_final = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "Pag": pag,
                "ESTADO": estado_valor,
                "FECSIG": fecha,
                "INFORMO": "on",
                "Observaciones": "En espera de cliente por localizar",
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            logger.info(f"📤 Enviando cambio estado {servicio_id} → {estado_valor}")
            r3 = self.session.post(BASE_URL, data=payload_final, timeout=15)

            # Guardar para debug
            with open(f"debug_estado_{servicio_id}.html", "w", encoding="latin-1") as f:
                f.write(r3.text)

            if "Illegal command" in r3.text:
                logger.error("❌ Illegal command al guardar")
                return False

            if "estado actual de la reparacion" in r3.text.lower():
                logger.info("✅ Cambio de estado realizado")
                return True

            logger.warning("⚠️ No se pudo confirmar claramente el cambio")
            return False

        except Exception as e:
            logger.error(f"Error al cambiar estado del servicio {servicio_id}: {e}")
            return False


homeserve = HomeServe()

# ---------------- LOOP DE SERVICIOS NUEVOS ----------------
def bot_loop():
    global SERVICIOS_ACTUALES
    homeserve.login()
    while True:
        try:
            actuales = homeserve.obtener_servicios_nuevos()
            for idserv, servicio in actuales.items():
                if idserv not in SERVICIOS_ACTUALES:
                    enviar_servicio(CHAT_ID, idserv, f"🆕 <b>Nuevo servicio</b>\n\n{servicio}")
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
    global SERVICIOS_ESTADO, SERVICIOS_CURSO, SERVICIOS_ACTUALES
    data = request.json
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login")

        elif accion == "REFRESH":
            SERVICIOS_ACTUALES.update(homeserve.obtener_servicios_nuevos())
            enviar(chat, "🔄 Actualizado")

        elif accion == "WEB":
            actuales = homeserve.obtener_servicios_nuevos()
            txt = "🌐 <b>Web</b>\n\n"
            for s in actuales.values():
                txt += s + "\n\n"
            enviar(chat, txt if actuales else "Nada encontrado")

        elif accion == "CAMBIAR_ESTADO":
            SERVICIOS_CURSO = homeserve.obtener_servicios_en_curso()
            if SERVICIOS_CURSO:
                for idserv, servicio in SERVICIOS_CURSO.items():
                    enviar_estado_servicio(chat, idserv, f"🔧 <b>Cambiar estado</b>\n\n{servicio}")
            else:
                enviar(chat, "No hay servicios en curso para cambiar estado.")

        elif accion.startswith("ACEPTAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "ACEPTADO"
            enviar(chat, f"✅ Servicio {servicio_id} aceptado")

        elif accion.startswith("RECHAZAR_"):
            servicio_id = accion.split("_")[1]
            SERVICIOS_ESTADO[servicio_id] = "RECHAZADO"
            enviar(chat, f"❌ Servicio {servicio_id} rechazado")

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
