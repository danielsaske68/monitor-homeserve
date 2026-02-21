import threading
import time
import logging
import psycopg2
from flask import Flask, jsonify

# ---------------------
# Configuración Logging
# ---------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------
# Configuración Flask
# ---------------------
app = Flask(__name__)

# ---------------------
# Conexión a PostgreSQL
# ---------------------
DB_CONFIG = {
    "host": "dpg-d6cglop5pdvs73d4mm1g-a",
    "database": "servicios_db_6q8c",
    "user": "servicios_db_6q8c_user",
    "password": "Gz4r2HbAI40vuLxvCCOpZn5XCXElAPHA",
    "port": 5432
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------
# Crear tabla si no existe
# ---------------------
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

# ---------------------
# Función para insertar servicio
# ---------------------
def servicio_nuevo(servicio_id, nombre, estado):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO servicios_vistos (servicio_id, nombre, estado) VALUES (%s, %s, %s) ON CONFLICT (servicio_id) DO NOTHING",
            (servicio_id, nombre, estado)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error al insertar servicio: {e}")
        return False

# ---------------------
# Monitor de servicios (simulado)
# ---------------------
def monitor_loop():
    while True:
        # Aquí iría tu lógica de scraping o monitor real
        servicios = [
            ("TEST123", "Prueba", "Pendiente"),
        ]
        for servicio_id, nombre, estado in servicios:
            if servicio_nuevo(servicio_id, nombre, estado):
                logger.info(f"Servicio insertado: {servicio_id} | {nombre} | {estado}")
        time.sleep(10)  # espera 10 segundos antes de la siguiente iteración

# ---------------------
# Rutas Flask
# ---------------------
@app.route("/")
def home():
    return jsonify({"status": "Monitor activo ⚡"})

# ---------------------
# Función principal
# ---------------------
if __name__ == "__main__":
    logger.info("Monitor iniciado ⚡")
    setup_db()
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    # Corre Flask en el puerto que Render asigna con la variable $PORT
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
