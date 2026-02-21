import os
import time
import threading
import logging
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask

##########################
# CONFIGURACIÓN (Entorno)
##########################

DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Tus credenciales HomeServe
HS_USUARIO = os.getenv("HS_USUARIO")
HS_PASSWORD = os.getenv("HS_PASSWORD")

URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

CHECK_INTERVAL = 120  # segundos entre chequeos

##########################
# LOGGING
##########################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("MonitorHomeServe")

##########################
# FLASK APP
##########################

app = Flask(__name__)

@app.route("/")
def home():
    return "Monitor HomeServe activo ✅"

@app.route("/health")
def health():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM servicios_vistos;")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return f"OK - Servicios guardados: {total}"
    except Exception as e:
        return f"ERROR DB: {e}", 500

##########################
# DATABASE
##########################

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios_vistos (
            id SERIAL PRIMARY KEY,
            numero TEXT UNIQUE,
            tipo TEXT,
            estado TEXT,
            fecha_detectado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Tabla servicios_vistos lista")

def servicio_es_nuevo(numero):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM servicios_vistos WHERE numero = %s;", (numero,))
        existe = cur.fetchone() is not None
        cur.close()
        conn.close()
        return not existe
    except Exception as e:
        logger.error("DB error checking existencia: %s", e)
        return False

def guardar_servicio(numero, tipo, estado):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO servicios_vistos (numero, tipo, estado)
            VALUES (%s, %s, %s)
            ON CONFLICT (numero) DO NOTHING;
        """, (numero, tipo, estado))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Guardado servicio {numero}")
    except Exception as e:
        logger.error("Error guardando servicio: %s", e)

##########################
# TELEGRAM
##########################

def enviar_telegram(texto, retries=3):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("⚠ Telegram sin configurar")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for intento in range(retries):
        try:
            r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": texto}, timeout=10)
            if r.status_code == 200:
                logger.info("📨 Mensaje enviado a Telegram")
                return
            else:
                logger.warning(f"⚠ Telegram HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"Error Telegram (intento {intento+1}): {e}")
        time.sleep(2)
    logger.error("❌ Falló enviar a Telegram después de varios intentos")

##########################
# SCRAPING / LOGIN
##########################

def hacer_login(session):
    payload = {
        "CODIGO": HS_USUARIO,
        "PASSW": HS_PASSWORD,
        "ACEPT": "Aceptar"
    }
    try:
        session.post(URL_LOGIN, data=payload, timeout=10)
        logger.info("🔐 Login enviado")
        return True
    except Exception as e:
        logger.error("Login fallido: %s", e)
        return False

def obtener_servicios(session):
    try:
        r = session.get(URL_SERVICIOS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        filas = soup.select("table tr")
        servicios = []

        for fila in filas:
            celdas = fila.find_all("td")
            if len(celdas) >= 3:
                numero = celdas[0].get_text(strip=True)
                tipo = celdas[1].get_text(strip=True)
                estado = celdas[2].get_text(strip=True)
                # filtro básico para evitar filas inválidas
                if numero and tipo and estado:
                    servicios.append({
                        "numero": numero,
                        "tipo": tipo,
                        "estado": estado
                    })
        logger.info(f"🔎 Servicios encontrados: {len(servicios)}")
        return servicios
    except Exception as e:
        logger.error("Error al obtener servicios: %s", e)
        return []

##########################
# MONITOR PRINCIPAL
##########################

def monitor_loop():
    logger.info("🚀 Monitor iniciado")
    setup_db()

    # Login inicial
    session = requests.Session()
    if not hacer_login(session):
        enviar_telegram("❌ Error login HomeServe (inicial)")
        return

    enviar_telegram("✅ Bot HomeServe iniciado correctamente")

    while True:
        servicios = obtener_servicios(session)
        if not servicios:
            logger.warning("Sin servicios o error, reintentando login...")
            hacer_login(session)
            time.sleep(CHECK_INTERVAL)
            continue

        for s in servicios:
            num = s["numero"]
            if servicio_es_nuevo(num):
                guardar_servicio(num, s["tipo"], s["estado"])
                enviar_telegram(
                    f"📌 Nuevo servicio HomeServe:\n"
                    f"🔢 Número: {num}\n"
                    f"📋 Tipo: {s['tipo']}\n"
                    f"📍 Estado: {s['estado']}"
                )

        time.sleep(CHECK_INTERVAL)

##########################
# EJECUCIÓN
##########################

if __name__ == "__main__":
    # Correr monitor en hilo
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    # Iniciar Flask en puerto definido por Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
