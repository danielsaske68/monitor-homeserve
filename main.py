import os
import time
import re
import threading
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

HOMESERVE_USER = os.environ.get("HOMESERVE_USER")
HOMESERVE_PASS = os.environ.get("HOMESERVE_PASS")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=login"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

CHECK_INTERVAL = 60  # segundos

# ==========================================
# FLASK APP (Gunicorn lo usa)
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
            requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": mensaje
                },
                timeout=10
            )
    except Exception as e:
        print("Error enviando a Telegram:", e)

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
    cur.execute(
        "INSERT INTO servicios (data) VALUES (%s) ON CONFLICT (data) DO NOTHING",
        (servicio,)
    )
    conn.commit()
    cur.close()
    conn.close()

# ==========================================
# LOGIN Y SCRAPING
# ==========================================

def login(session):
    payload = {
        "usuario": HOMESERVE_USER,
        "password": HOMESERVE_PASS
    }
    session.post(LOGIN_URL, data=payload, timeout=15)

def es_servicio_valido(texto):
    patron = r"\b\d{6,}\b"  # detecta códigos numéricos largos
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
# MONITOR
# ==========================================

def start_monitor():
    crear_tabla_si_no_existe()

    enviar_telegram("🚀 Bot iniciado correctamente")

    servicios_vistos = obtener_servicios_existentes()
    enviar_telegram(f"📊 Servicios almacenados en BD: {len(servicios_vistos)}")

    session = requests.Session()
    login(session)

    while True:
        try:
            servicios_actuales = obtener_servicios_web(session)
            nuevos = servicios_actuales - servicios_vistos

            if nuevos:
                for servicio in nuevos:
                    guardar_servicio(servicio)
                    enviar_telegram(f"🆕 Nuevo servicio:\n{servicio}")

                servicios_vistos.update(nuevos)

        except Exception as e:
            enviar_telegram(f"⚠ Error detectado: {str(e)}")
            session = requests.Session()
            login(session)

        time.sleep(CHECK_INTERVAL)

# ==========================================
# ARRANQUE AUTOMÁTICO DEL MONITOR
# ==========================================

monitor_thread = threading.Thread(target=start_monitor)
monitor_thread.daemon = True
monitor_thread.start()
