import threading
import time
import logging
import requests
import psycopg2
from flask import Flask

# ----------------------------
# CONFIGURACIÓN
# ----------------------------
DB_HOST = "dpg-d6cglop5pdvs73d4mm1g-a"           # Cambiar si es diferente
DB_NAME = "servicios_db_6q8c"   # Tu base de datos
DB_USER = "servicios_db_6q8c_user"
DB_PASS = "Gz4r2HbAI40vuLxvCCOpZn5XCXElAPHA"

TELEGRAM_TOKEN = "7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU"
TELEGRAM_CHAT_ID = "1573811842"

MONITOR_INTERVAL = 60  # Segundos entre cada revisión

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("Monitor")

# ----------------------------
# FLASK
# ----------------------------
app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def index():
    return "Monitor Activo ✅", 200

# ----------------------------
# CONEXIÓN A DB
# ----------------------------
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

# ----------------------------
# CREAR TABLA SI NO EXISTE
# ----------------------------
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

# ----------------------------
# FUNCIONES DEL BOT
# ----------------------------
def servicio_nuevo(servicio_id, nombre, estado):
    """Retorna True si el servicio es nuevo y lo guarda en la DB."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO servicios_vistos (servicio_id, nombre, estado)
            VALUES (%s, %s, %s)
            ON CONFLICT (servicio_id) DO NOTHING;
        """, (servicio_id, nombre, estado))
        conn.commit()
        inserted = cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error insertando servicio {servicio_id}: {e}")
        inserted = False
    finally:
        cur.close()
        conn.close()
    return inserted

def enviar_alerta_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje})
        logger.info(f"Alerta enviada a Telegram ✅: {mensaje}")
    except Exception as e:
        logger.error(f"No se pudo enviar Telegram: {e}")

# ----------------------------
# MONITOR
# ----------------------------
def monitor_loop():
    logger.info("Monitor iniciado ⚡")
    while True:
        try:
            # ----------------------------
            # SIMULAMOS SERVICIOS (CAMBIAR ESTO POR TU SCRAPER/LLAMADA REAL)
            # ----------------------------
            servicios = [
                {"id": "SERV123", "nombre": "Prueba Servicio 1", "estado": "Pendiente"},
                {"id": "SERV124", "nombre": "Prueba Servicio 2", "estado": "Pendiente"}
            ]

            for s in servicios:
                if servicio_nuevo(s["id"], s["nombre"], s["estado"]):
                    enviar_alerta_telegram(f"Nuevo servicio: {s['nombre']} ({s['estado']})")

        except Exception as e:
            logger.error(f"Error en monitor_loop: {e}")

        time.sleep(MONITOR_INTERVAL)

# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    setup_db()
    # Iniciamos monitor en hilo paralelo
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    # Ejecutamos Flask
    app.run(host="0.0.0.0", port=10000)
