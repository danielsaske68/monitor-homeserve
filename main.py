import os
import threading
import time
import logging
import requests
import psycopg2
from psycopg2 import sql
from flask import Flask, jsonify

# ==========================================
# CONFIGURACIÓN
# ==========================================

DATABASE_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MONITOR_INTERVAL = 60  # segundos

# ==========================================
# LOGGING PROFESIONAL
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MonitorHomeserve")

# ==========================================
# FLASK APP
# ==========================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Monitor activo ⚡", 200

@app.route("/health")
def health():
    return jsonify({
        "status": "running",
        "monitor_interval": MONITOR_INTERVAL
    }), 200

# ==========================================
# DB CONNECTION
# ==========================================

def get_connection():
    return psycopg2.connect(DATABASE_URL)

# ==========================================
# DB SETUP + AUTO FIX COLUMN
# ==========================================

def setup_db():
    conn = get_connection()
    cur = conn.cursor()

    # Crear tabla si no existe
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

    # Verificar que exista columna servicio_id
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='servicios_vistos'
        AND column_name='servicio_id';
    """)

    if not cur.fetchone():
        logger.warning("Columna servicio_id no existe. Intentando agregarla...")
        cur.execute("ALTER TABLE servicios_vistos ADD COLUMN servicio_id TEXT;")
        conn.commit()
        logger.info("Columna servicio_id agregada correctamente ✅")

    cur.close()
    conn.close()

    logger.info("Base de datos lista ✅")

# ==========================================
# INSERT SEGURO
# ==========================================

def servicio_nuevo(servicio_id, nombre, estado):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO servicios_vistos (servicio_id, nombre, estado)
            VALUES (%s, %s, %s)
            ON CONFLICT (servicio_id) DO NOTHING;
        """, (servicio_id, nombre, estado))

        conn.commit()
        inserted = cur.rowcount > 0

        cur.close()
        conn.close()

        if inserted:
            logger.info(f"Nuevo servicio detectado: {servicio_id}")

        return inserted

    except Exception as e:
        logger.error(f"Error DB insert: {e}")
        return False

# ==========================================
# TELEGRAM CON REINTENTO
# ==========================================

def enviar_telegram(mensaje, retries=3):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram no configurado (faltan variables de entorno)")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for intento in range(retries):
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": mensaje
                },
                timeout=10
            )

            if response.status_code == 200:
                logger.info("Mensaje enviado a Telegram ✅")
                return
            else:
                logger.warning(f"Telegram respondió con {response.status_code}")

        except Exception as e:
            logger.error(f"Error enviando Telegram (intento {intento+1}): {e}")

        time.sleep(2)

    logger.error("No se pudo enviar mensaje a Telegram después de varios intentos ❌")

# ==========================================
# MONITOR LOOP
# ==========================================

def monitor_loop():
    logger.info("Monitor iniciado ⚡")

    while True:
        try:
            logger.info("Ejecutando ciclo de monitoreo...")

            # ⚠️ REEMPLAZA ESTA PARTE CON TU SCRAPER REAL
            servicios = [
                {"id": "TEST001", "nombre": "Servicio prueba", "estado": "Pendiente"}
            ]

            for s in servicios:
                if servicio_nuevo(s["id"], s["nombre"], s["estado"]):
                    enviar_telegram(
                        f"🚨 Nuevo servicio detectado\n\n"
                        f"ID: {s['id']}\n"
                        f"Nombre: {s['nombre']}\n"
                        f"Estado: {s['estado']}"
                    )

        except Exception as e:
            logger.error(f"Error en monitor_loop: {e}")

        time.sleep(MONITOR_INTERVAL)

# ==========================================
# INICIO
# ==========================================

def start_monitor():
    setup_db()
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()

start_monitor()
