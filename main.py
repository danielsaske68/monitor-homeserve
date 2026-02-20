import os
import time
import threading
import logging
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask

# ==============================
# CONFIG
# ==============================

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("CODIGO")
PASSWORD = os.getenv("PASSW")
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 60

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==============================
# WEB SERVER (para Render)
# ==============================

@app.route("/")
def home():
    return "Bot activo"

# ==============================
# TELEGRAM
# ==============================

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje
        }
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")

# ==============================
# DATABASE
# ==============================

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios_vistos (
            id TEXT PRIMARY KEY
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def servicio_existe(servicio_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM servicios_vistos WHERE id = %s;", (servicio_id,))
    existe = cur.fetchone()
    cur.close()
    conn.close()
    return existe is not None

def guardar_servicio(servicio_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO servicios_vistos (id) VALUES (%s);", (servicio_id,))
    conn.commit()
    cur.close()
    conn.close()

# ==============================
# MONITOR
# ==============================

class Monitor:

    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            data = {
                "CODIGO": USERNAME,
                "PASSW": PASSWORD
            }

            response = self.session.post(LOGIN_URL, data=data, timeout=15)

            if response.status_code == 200:
                logger.info("Login exitoso")
                return True
            return False

        except Exception as e:
            logger.error(f"Error login: {e}")
            return False

    def obtener_servicios(self):
        try:
            response = self.session.get(SERVICIOS_URL, timeout=15)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            servicios = []

            filas = soup.select("table tr")

            for fila in filas:
                columnas = fila.find_all("td")
                if len(columnas) > 0:
                    servicio_id = columnas[0].text.strip()
                    if servicio_id:
                        servicios.append(servicio_id)

            return servicios

        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return None

    def run(self):

        enviar_telegram("✅ Bot iniciado en Render")

        while True:

            while not self.login():
                logger.error("Login fallido. Reintentando en 30s")
                time.sleep(30)

            servicios = self.obtener_servicios()

            if servicios is None:
                time.sleep(30)
                continue

            for servicio in servicios:
                if not servicio_existe(servicio):
                    guardar_servicio(servicio)
                    enviar_telegram(f"🚨 Nuevo servicio:\n{servicio}")

            time.sleep(CHECK_INTERVAL)

# ==============================
# START
# ==============================

def iniciar_monitor():
    init_db()
    monitor = Monitor()
    monitor.run()

if __name__ == "__main__":
    threading.Thread(target=iniciar_monitor).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
