import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 🔹 Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

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
        self.driver = None
        self.logged_in = False

    # ---------------- LOGIN ----------------
    def login(self):
        try:
            if self.driver:
                self.driver.quit()
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            self.driver = webdriver.Chrome(options=options)
            self.driver.get(LOGIN_URL)
            self.driver.find_element(By.NAME, "CODIGO").send_keys(USUARIO)
            self.driver.find_element(By.NAME, "PASSW").send_keys(PASSWORD)
            self.driver.find_element(By.NAME, "BTN").click()
            time.sleep(2)
            self.logged_in = True
            logger.info("Login Selenium OK")
            return True
        except Exception as e:
            logger.error(f"Error login Selenium: {e}")
            self.logged_in = False
            return False

    # ---------------- SERVICIOS ----------------
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

    # ---------------- CAMBIO DE ESTADO ----------------
    def cambiar_estado_servicio(self, servicio_id):
        if not self.logged_in:
            if not self.login():
                return False
        try:
            # Abrir servicio
            url_servicio = f"https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio={servicio_id}&Pag=1"
            self.driver.get(url_servicio)
            time.sleep(2)

            # Click en repaso
            self.driver.find_element(By.NAME, "repaso").click()
            time.sleep(2)

            # Estado
            Select(self.driver.find_element(By.NAME, "estado")).select_by_value("348")

            # Fecha siguiente
            mañana = datetime.now() + timedelta(days=1)
            fecha_input = self.driver.find_element(By.NAME, "FECSIG")
            fecha_input.clear()
            fecha_input.send_keys(mañana.strftime("%d/%m/%Y"))

            # Checkbox INFORMO
            checkbox = self.driver.find_element(By.NAME, "INFORMO")
            if not checkbox.is_selected():
                checkbox.click()

            # Observaciones
            obs = self.driver.find_element(By.NAME, "Observaciones")
            obs.clear()
            obs.send_keys("ala espera de localizar asegurado")

            # Aceptar cambios
            self.driver.find_element(By.NAME, "BTNCAMBIAESTADO").click()
            time.sleep(2)

            logger.info(f"✅ Servicio {servicio_id} actualizado")
            return True
        except Exception as e:
            logger.error(f"❌ Error cambiando estado {servicio_id}: {e}")
            return False

homeserve = HomeServe()

# ---------------- LOOP SERVICIOS NUEVOS ----------------
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

        # BOTONES GENERALES
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
            ok = homeserve.cambiar_estado_servicio(servicio_id)
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
