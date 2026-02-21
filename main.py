import os
import time
import requests
from bs4 import BeautifulSoup
import psycopg2
from flask import Flask

# -------------------
# CONFIGURACIÓN
# -------------------
DATABASE_URL = os.environ.get("DATABASE_URL")  # Ej: postgres://user:pass@host/db
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# -------------------
# FLASK APP PARA RENDER
# -------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot HomeServe en marcha ✅"

# -------------------
# FUNCIONES DE DB
# -------------------
def get_connection():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            descripcion TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def guardar_servicio(descripcion):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO servicios (descripcion) VALUES (%s)", (descripcion,))
    conn.commit()
    cur.close()
    conn.close()

def obtener_servicios_existentes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT descripcion FROM servicios")
    filas = cur.fetchall()
    cur.close()
    conn.close()
    return {fila[0] for fila in filas}

# -------------------
# FUNCIONES DE TELEGRAM
# -------------------
def enviar_telegram(mensaje):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje})

# -------------------
# FUNCIONES DE MONITOREO
# -------------------
def login(session):
    payload = {
        "usuario": os.environ.get("HOMESERVE_USER"),
        "clave": os.environ.get("HOMESERVE_PASS")
    }
    session.post(LOGIN_URL, data=payload)

def obtener_servicios(session):
    resp = session.get(ASIGNACION_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    servicios = []

    # Aquí parsea los servicios según la estructura de la web
    for tag in soup.select(".servicio"):  # ajustar selector real
        descripcion = tag.get_text(strip=True)
        servicios.append(descripcion)
    return servicios

def start_monitor():
    enviar_telegram("🤖 Bot HomeServe iniciado y en marcha")
    setup_db()
    session = requests.Session()
    login(session)

    servicios_vistos = obtener_servicios_existentes()

    while True:
        try:
            servicios_actuales = set(obtener_servicios(session))
            nuevos = servicios_actuales - servicios_vistos

            for servicio in nuevos:
                guardar_servicio(servicio)
                enviar_telegram(f"📌 Nuevo servicio detectado:\n{servicio}")

            servicios_vistos.update(nuevos)

        except Exception as e:
            enviar_telegram(f"⚠ Error en monitor: {e}")

        time.sleep(60)  # espera 1 minuto entre chequeos

# -------------------
# ARRANQUE DIRECTO
# -------------------
if __name__ == "__main__":
    start_monitor()
