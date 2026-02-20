import os
import psycopg2
from datetime import datetime
import requests
import logging

# ===== LOGGING =====
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ===== VARIABLES =====
DATABASE_URL = os.getenv('postgresql://servicios_db_md79_user:8WzYZdOPdI4XdTclppihkPjgHtLbtzb4@dpg-d6cd3hntn9qs73d8g5hg-a/servicios_db_md79')
TOKEN_TELEGRAM = os.getenv('7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU')
CHAT_ID = os.getenv('1573811842')

# ===== FUNCIONES =====
def conectar_db():
    """Conecta a PostgreSQL usando DATABASE_URL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("Conexión a PostgreSQL exitosa ✅")
        return conn
    except Exception as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
        return None

def crear_tabla(conn):
    """Crea tabla de servicios si no existe"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS servicios_vistos (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(50) UNIQUE,
                    tipo VARCHAR(100),
                    estado VARCHAR(100),
                    fecha_detectado TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Tabla servicios_vistos lista ✅")
    except Exception as e:
        logger.error(f"Error creando tabla: {e}")

def insertar_servicio(conn, numero, tipo, estado):
    """Inserta un servicio nuevo si no existe"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO servicios_vistos (numero, tipo, estado, fecha_detectado)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (numero) DO NOTHING
            """, (numero, tipo, estado, datetime.now()))
            conn.commit()
            logger.info(f"Servicio insertado: {numero} | {tipo} | {estado}")
            return True
    except Exception as e:
        logger.error(f"Error insertando servicio: {e}")
        return False

def enviar_alerta_telegram(numero, tipo, estado):
    """Envía alerta de Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
        mensaje = f"NUEVO SERVICIO TEST\nNumero: {numero}\nTipo: {tipo}\nEstado: {estado}\nHora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        payload = {'chat_id': CHAT_ID, 'text': mensaje}
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            logger.info(f"Alerta enviada a Telegram ✅: {numero}")
            return True
        else:
            logger.error(f"Error Telegram {r.status_code}: {r.text}")
            return False
    except Exception as e:
        logger.error(f"Excepción Telegram: {e}")
        return False

# ===== MAIN =====
if __name__ == "__main__":
    logger.info("Iniciando prueba completa del bot ⚡")
    conn = conectar_db()
    if conn:
        crear_tabla(conn)

        # Servicio de prueba
        numero_test = "TEST123"
        tipo_test = "Prueba"
        estado_test = "Pendiente"

        # Insertar en DB
        if insertar_servicio(conn, numero_test, tipo_test, estado_test):
            # Enviar alerta a Telegram
            enviar_alerta_telegram(numero_test, tipo_test, estado_test)

        conn.close()
    logger.info("Script de prueba finalizado ✅")
