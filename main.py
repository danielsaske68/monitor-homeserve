import os
import time
import threading
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask
from dotenv import load_dotenv

# ------------------------------
# Configuracion desde .env o Environment
# ------------------------------
load_dotenv()

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO_SEGUNDOS = int(os.getenv("INTERVALO_SEGUNDOS", 120))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
TELEGRAM_API_URL = "https://api.telegram.org"

# ------------------------------
# Logging
# ------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ------------------------------
# Telegram
# ------------------------------
class TelegramClient:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def enviar_mensaje(self, mensaje):
        url = f"{TELEGRAM_API_URL}/bot{self.bot_token}/sendMessage"
        data = {"chat_id": self.chat_id, "text": mensaje, "parse_mode": "HTML"}
        try:
            r = requests.post(url, data=data, timeout=10)
            r.raise_for_status()
            logger.info("Mensaje enviado a Telegram")
            return True
        except Exception as e:
            logger.error(f"Error enviando Telegram: {e}")
            return False

# ------------------------------
# HomeServe Scraper
# ------------------------------
class HomeServeScraper:
    def __init__(self, usuario, password):
        self.usuario = usuario
        self.password = password
        self.session = requests.Session()

    def login(self):
        payload = {"CODIGO": self.usuario, "PASSW": self.password, "BTN": "Aceptar"}
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            self.session.get(LOGIN_URL, headers=headers)
            r = self.session.post(LOGIN_URL, data=payload, headers=headers, timeout=10)
            if "error" in r.text.lower():
                logger.error("Login fallido")
                return False
            logger.info("Login exitoso")
            return True
        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener_servicios(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            servicios = set()
            for fila in soup.find_all("tr"):
                t = fila.get_text(strip=True)
                if t and len(t) > 30:
                    servicios.add(t)
            return servicios
        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return set()

# ------------------------------
# Bot
# ------------------------------
class HomeServeBot:
    def __init__(self, scraper, telegram, intervalo):
        self.scraper = scraper
        self.telegram = telegram
        self.intervalo = intervalo
        self.servicios_previos = None

    def iniciar(self):
        if not self.scraper.login():
            logger.error("No se pudo conectar a HomeServe")
            return
        try:
            while True:
                self.revisar_servicios()
                time.sleep(self.intervalo)
        except Exception as e:
            logger.error(f"Error en loop principal: {e}")
            time.sleep(30)

    def revisar_servicios(self):
        actuales = self.scraper.obtener_servicios()
        if self.servicios_previos is None:
            self.servicios_previos = actuales
            return
        nuevos = actuales - self.servicios_previos
        for s in nuevos:
            self.telegram.enviar_mensaje(f"NUEVO SERVICIO ASIGNADO:\n\n{s}")
            logger.info("Nuevo servicio detectado")
        self.servicios_previos = actuales

# ------------------------------
# Flask server para Render
# ------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "HomeServe Bot funcionando"

def iniciar_bot_thread():
    scraper = HomeServeScraper(USUARIO, PASSWORD)
    telegram = TelegramClient(BOT_TOKEN, CHAT_ID)
    bot = HomeServeBot(scraper, telegram, INTERVALO_SEGUNDOS)
    bot.iniciar()

# Ejecutar bot en segundo plano
threading.Thread(target=iniciar_bot_thread, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
