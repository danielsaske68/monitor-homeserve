import os
import time
import re
import threading
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from datetime import datetime, date

# ==========================================
# CONFIGURACIÓN
# ==========================================

DATABASE_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HOMESERVE_USER = os.environ.get("HOMESERVE_USER")
HOMESERVE_PASS = os.environ.get("HOMESERVE_PASS")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

CHECK_INTERVAL = 60

# ==========================================
# FLASK APP
# ==========================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot HomeServe Profesional Activo ✅"

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

def contar_servicios():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM servicios")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

def contar_servicios_hoy():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM servicios
        WHERE DATE(created_at) = CURRENT_DATE
    """)
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

def obtener_ultimos_servicios():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT data FROM servicios
        ORDER BY created_at DESC
        LIMIT 5
    """)
    filas = cur.fetchall()
    cur.close()
    conn.close()
    return [fila[0] for fila in filas]

def obtener_servicios_existentes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT data FROM servicios")
    filas = cur.fetchall()
    cur.close()
    conn.close()
    return {fila[0] for fila in filas}

# ==========================================
# SCRAPING
# ==========================================

def login(session):
    payload = {
        "usuario": HOMESERVE_USER,
        "password": HOMESERVE_PASS
    }
    session.post(LOGIN_URL, data=payload, timeout=15)

def es_servicio_valido(texto):
    patron = r"\b\d{6,}\b"
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
# TELEGRAM
# ==========================================

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje
        }, timeout=10)
    except Exception as e:
        print("Error Telegram:", e)

def responder(chat_id, mensaje, keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": mensaje}
    if keyboard:
        data["reply_markup"] = keyboard
    requests.post(url, json=data)

# Webhook unificado para recibir mensajes y botones
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()

    # Mensajes de texto
    if "message" in data:
        texto = data["message"].get("text", "")
        chat_id = data["message"]["chat"]["id"]

        if texto == "/start":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Ver últimos servicios", "callback_data": "ver_ultimos"}],
                    [{"text": "Servicios hoy", "callback_data": "ver_hoy"}],
                    [{"text": "Total servicios", "callback_data": "ver_total"}]
                ]
            }
            responder(chat_id, "🤖 Bot activo. Selecciona una opción:", keyboard)

    # Botones inline
    elif "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        data_cb = query["data"]

        if data_cb == "ver_ultimos":
            ultimos = obtener_ultimos_servicios()
            if ultimos:
                mensaje = "🆕 Últimos servicios:\n\n" + "\n\n".join(ultimos)
            else:
                mensaje = "No hay servicios aún."
            responder(chat_id, mensaje)

        elif data_cb == "ver_hoy":
            hoy = contar_servicios_hoy()
            responder(chat_id, f"📅 Servicios guardados hoy: {hoy}")

        elif data_cb == "ver_total":
            total = contar_servicios()
            responder(chat_id, f"📊 Total servicios almacenados: {total}")

    return jsonify({"status": "ok"})

# ==========================================
# MONITOR
# ==========================================

def start_monitor():
    crear_tabla_si_no_existe()
    enviar_telegram("🚀 Bot iniciado correctamente")

    servicios_vistos = obtener_servicios_existentes()

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
# ARRANQUE
# ==========================================

monitor_thread = threading.Thread(target=start_monitor)
monitor_thread.daemon = True
monitor_thread.start()
