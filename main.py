import os
import time
import threading
import logging
import psycopg2
import requests
from flask import Flask

# --------------------------
# CONFIGURACIÓN
# --------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")  # tu URL de PostgreSQL
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # token bot
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # chat_id

CHECK_INTERVAL = 120  # segundos entre chequeos

# --------------------------
# LOGGING
# --------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --------------------------
# FLASK
# --------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot activo ✅"

# --------------------------
# FUNCIONES DE DB
# --------------------------
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def setup_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios_vistos (
            id SERIAL PRIMARY KEY,
            servicio_id TEXT UNIQUE,
            nombre TEXT,
            estado TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Tabla servicios_vistos lista ✅")

def servicio_nuevo(servicio_id, nombre, estado):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO servicios_vistos (servicio_id, nombre, estado) VALUES (%s, %s, %s)", 
                    (servicio_id, nombre, estado))
        conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

# --------------------------
# TELEGRAM
# --------------------------
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
    try:
        r = requests.post(url, data=data)
        if r.status_code == 200:
            logger.info(f"Alerta enviada a Telegram ✅: {mensaje}")
        else:
            logger.error(f"Error Telegram: {r.text}")
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")

# --------------------------
# MONITOR PRINCIPAL
# --------------------------
def monitor_loop():
    logger.info("Monitor iniciado ⚡")
    setup_db()
    while True:
        # Aquí tu lógica para revisar servicios
        # EJEMPLO DE PRUEBA
        servicio_id = "TEST123"
        nombre = "Prueba"
        estado = "Pendiente"

        if servicio_nuevo(servicio_id, nombre, estado):
            enviar_telegram(f"{servicio_id} | {nombre} | {estado}")

        time.sleep(CHECK_INTERVAL)

# --------------------------
# EJECUTAR HILO
# --------------------------
threading.Thread(target=monitor_loop, daemon=True).start()

# --------------------------
# INICIAR FLASK
# --------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
