import os
import time
import logging
import requests
import psycopg2
from bs4 import BeautifulSoup

# =========================
# CONFIGURACIÓN
# =========================

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("CODIGO")
PASSWORD = os.getenv("PASSW")

DATABASE_URL = os.getenv("DATABASE_URL")

CHECK_INTERVAL = 60  # segundos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# BASE DE DATOS
# =========================

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

# =========================
# BOT
# =========================

class Monitor:

    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            data = {
                "CODIGO": USERNAME,
                "PASSW": PASSWORD
            }

            response = self.session.post(LOGIN_URL, data=data)

            if response.status_code == 200:
                logger.info("Login exitoso")
                return True
            else:
                logger.error("Login fallido")
                return False

        except Exception as e:
            logger.error(f"Error en login: {e}")
            return False

    def obtener_servicios(self):
        try:
            response = self.session.get(SERVICIOS_URL)
            soup = BeautifulSoup(response.text, "html.parser")

            servicios = []

            # AJUSTAR SELECTOR SEGÚN TU HTML
            filas = soup.select("table tr")

            for fila in filas:
                columnas = fila.find_all("td")
                if len(columnas) > 0:
                    servicio_id = columnas[0].text.strip()
                    servicios.append(servicio_id)

            return servicios

        except Exception as e:
            logger.error(f"Error obteniendo servicios: {e}")
            return []

    def run(self):
        while True:

            while not self.login():
                logger.error("Login fallido. Reintentando en 30 segundos...")
                time.sleep(30)

            try:
                servicios = self.obtener_servicios()

                for servicio in servicios:
                    if not servicio_existe(servicio):
                        logger.info(f"Nuevo servicio detectado: {servicio}")
                        guardar_servicio(servicio)
                        # AQUÍ VA TU ENVÍO A TELEGRAM

            except Exception as e:
                logger.error(f"Error general: {e}")

            time.sleep(CHECK_INTERVAL)

# =========================
# START
# =========================

if __name__ == "__main__":
    init_db()
    monitor = Monitor()
    monitor.run()
