import os
import threading
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask, jsonify

# -------------------------
# Configuración
# -------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")  # tu URL de Render PostgreSQL
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MONITOR_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# -------------------------
# Flask App
# -------------------------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "alive"}), 200

# -------------------------
# Base de datos
# -------------------------
def get_connection():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_connection()
    cur = conn.cursor()
    # Ejemplo: crear tabla si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# -------------------------
# Telegram
# -------------------------
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Error enviando Telegram:", e)

# -------------------------
# Monitor
# -------------------------
def check_website():
    try:
        r = requests.get(MONITOR_URL)
        soup = BeautifulSoup(r.text, "html.parser")
        # Aquí deberías parsear tu contenido y decidir si hay algo nuevo
        servicios = soup.find_all("tr")  # ejemplo simple
        return len(servicios) > 0
    except Exception as e:
        print("Error al revisar sitio:", e)
        return False

def monitor_loop():
    setup_db()
    send_telegram("✅ Bot HomeServe iniciado correctamente")
    print("🚀 Monitor iniciado")

    while True:
        has_data = check_website()
        if has_data:
            send_telegram("📢 Hay datos en la tabla!")
        time.sleep(60)  # espera 1 minuto entre checks

# -------------------------
# Iniciar monitor (Gunicorn compatible)
# -------------------------
def start_background_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

start_background_monitor()
