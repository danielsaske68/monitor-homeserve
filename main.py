import os
import time
import threading
import requests
import psycopg2
from flask import Flask
from bs4 import BeautifulSoup

app = Flask(__name__)

# ================= CONFIG =================
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# ================= TELEGRAM =================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": mensaje})
    except Exception as e:
        print("Error enviando Telegram:", e)

# ================= BASE DE DATOS =================
def get_db():
    return psycopg2.connect(DATABASE_URL)

def servicio_existe(descripcion):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM servicios WHERE descripcion=%s", (descripcion,))
    existe = cur.fetchone()
    cur.close()
    conn.close()
    return existe is not None

def guardar_servicio(descripcion):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO servicios (descripcion) VALUES (%s) ON CONFLICT DO NOTHING", (descripcion,))
    conn.commit()
    cur.close()
    conn.close()

# ================= LOGIC DE HOMESERVE =================
def login(session):
    payload = {
        "usuario": USERNAME,
        "password": PASSWORD
    }
    session.post(LOGIN_URL, data=payload)

def obtener_servicios(session):
    response = session.get(SERVICIOS_URL)
    soup = BeautifulSoup(response.text, "html.parser")
    filas = soup.find_all("tr")  # Ajusta según estructura real
    return [fila.text.strip() for fila in filas if fila.text.strip()]

# ================= WORKER BACKGROUND =================
def worker():
    while True:
        try:
            session = requests.Session()
            login(session)

            servicios = obtener_servicios(session)

            for servicio in servicios:
                if not servicio_existe(servicio):
                    guardar_servicio(servicio)
                    enviar_telegram(f"🚨 Nuevo servicio:\n{servicio}")

            print("Revisión completada")

        except Exception as e:
            print("Error en worker:", e)

        time.sleep(300)  # cada 5 minutos

# ================= FLASK ENDPOINTS =================
@app.route("/")
def home():
    return "Bot funcionando correctamente 🚀"

@app.route("/ver-servicios")
def ver_servicios():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM servicios ORDER BY fecha DESC LIMIT 50")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return str(rows)

# ================= MAIN =================
if __name__ == "__main__":
    # Inicia worker en segundo plano
    threading.Thread(target=worker, daemon=True).start()
    # Flask listo para Gunicorn
    app.run(host="0.0.0.0", port=10000)
