import os
import time
import re
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime

# ==========================================
# CONFIGURACIÓN
# ==========================================

DATABASE_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

CHECK_INTERVAL = 60  # segundos
RESUMEN_HORA = 20    # 20 = 8PM

# ==========================================
# FLASK APP (Render necesita puerto abierto)
# ==========================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot HomeServe Profesional Activo ✅"

# ==========================================
# TELEGRAM
# ==========================================

def enviar_telegram(mensaje):
    try:
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": mensaje
            }, timeout=10)
    except:
        pass

# ==========================================
# BASE DE DATOS
# ==========================================

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def crear_tabla_si_no_existe():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            data TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def obtener_servicios_existentes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT data FROM servicios")
    filas = cur.fetchall()
    cur.close()
    conn.close()
    return {fila[0] for fila in filas}

def guardar_servicio(servicio):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO servicios (data) VALUES (%s) ON CONFLICT (data) DO NOTHING",
            (servicio,)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

def contar_servicios():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM servicios")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

# ==========================================
# LOGIN Y SCRAPING
# ==========================================

def login(session):
    payload = {
        "CODIGO": os.environ.get("HOMESERVE_USER"),
        "PASSW": os.environ.get("HOMESERVE_PASS")
    }
    session.post(LOGIN_URL, data=payload, timeout=15)

def es_servicio_valido(texto):
    # Ajusta esta expresión según el formato real
    # Detecta códigos tipo: 123456 o HS-123456
    patron = r"\b\d{5,}\b"
    return re.search(patron, texto)

def obtener_servicios_web(session):
    response = session.get(ASIGNACION_URL, timeout=20)

    if "login" in response.url.lower():
        raise Exception("Sesión expirada")

    soup = BeautifulSoup(response.text, "html.parser")

    servicios = set()

    for fila in soup.select("tr"):
        texto = fila.get_text(" ", strip=True)

        if texto and es_servicio_valido(texto):
            servicios.add(texto)

    return servicios

# ==========================================
# MONITOR PROFESIONAL
# ==========================================

def start_monitor():
    crear_tabla_si_no_existe()

    enviar_telegram("🚀 Bot Profesional iniciado correctamente")

    servicios_vistos = obtener_servicios_existentes()
    enviar_telegram(f"📊 Servicios almacenados en BD: {len(servicios_vistos)}")

    session = requests.Session()
    login(session)

    ultima_fecha_resumen = None

    while True:
        try:
            ahora = datetime.now()

            # Revisar servicios nuevos
            servicios_actuales = obtener_servicios_web(session)
            nuevos = servicios_actuales - servicios_vistos

            if nuevos:
                for servicio in nuevos:
                    guardar_servicio(servicio)
                    enviar_telegram(f"🆕 Nuevo servicio detectado:\n{servicio}")

                servicios_vistos.update(nuevos)

            # Resumen diario automático
            if ahora.hour == RESUMEN_HORA:
                fecha_hoy = ahora.date()
                if ultima_fecha_resumen != fecha_hoy:
                    total = contar_servicios()
                    enviar_telegram(
                        f"📈 Resumen diario:\n"
                        f"Total servicios almacenados: {total}\n"
                        f"Nuevos hoy: {len(nuevos)}"
                    )
                    ultima_fecha_resumen = fecha_hoy

        except Exception as e:
            enviar_telegram(f"⚠ Error detectado: {str(e)}")
            session = requests.Session()
            login(session)

        time.sleep(CHECK_INTERVAL)

# ==========================================
# ARRANQUE
# ==========================================

if __name__ == "__main__":
    start_monitor()
