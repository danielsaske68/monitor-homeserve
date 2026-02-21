import os
import time
import threading
import requests
import psycopg2
from flask import Flask
from bs4 import BeautifulSoup

# =========================
# CONFIGURACIÓN DESDE ENV
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

URL_OBJETIVO = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"  # <-- CAMBIA ESTO

INTERVALO = 120 # 5 minutos

app = Flask(__name__)

# =========================
# CONEXIÓN DB
# =========================

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            titulo TEXT UNIQUE
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Base de datos inicializada")

# =========================
# TELEGRAM
# =========================

def send_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje
        }
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Error enviando Telegram:", e)

# =========================
# VERIFICACIÓN INICIAL
# =========================

def check_database_status():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM servicios;")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()

        mensaje = f"✅ Bot iniciado correctamente\n📊 Registros en DB: {total}"
        send_telegram(mensaje)

        print("Chequeo enviado a Telegram")

    except Exception as e:
        print("Error verificando DB:", e)
        send_telegram(f"❌ Error conectando a la base de datos:\n{e}")

# =========================
# SCRAPER
# =========================

def obtener_servicios():
    try:
        response = requests.get(URL_OBJETIVO, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        # 👇 AJUSTA ESTE SELECTOR SEGÚN TU PÁGINA
        elementos = soup.find_all("h2")

        servicios = [el.get_text(strip=True) for el in elementos]
        return servicios

    except Exception as e:
        print("Error scrapeando:", e)
        return []

# =========================
# MONITOR
# =========================

def monitor():
    while True:
        print("Ejecutando ciclo de monitoreo...")
        servicios = obtener_servicios()

        if servicios:
            conn = get_connection()
            cur = conn.cursor()

            for servicio in servicios:
                try:
                    cur.execute(
                        "INSERT INTO servicios (titulo) VALUES (%s) ON CONFLICT DO NOTHING;",
                        (servicio,)
                    )
                    if cur.rowcount > 0:
                        print("Nuevo servicio:", servicio)
                        send_telegram(f"🚨 Nuevo servicio detectado:\n{servicio}")

                except Exception as e:
                    print("Error insertando:", e)

            conn.commit()
            cur.close()
            conn.close()

        time.sleep(INTERVALO)

# =========================
# FLASK ENDPOINTS
# =========================

@app.route("/")
def home():
    return "Bot funcionando correctamente"

@app.route("/health")
def health():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM servicios;")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return f"OK - Registros en DB: {total}"
    except:
        return "Error conectando a DB", 500

# =========================
# INICIO
# =========================

if __name__ == "__main__":
    init_db()
    check_database_status()

    hilo = threading.Thread(target=monitor)
    hilo.daemon = True
    hilo.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
