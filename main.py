import requests
import psycopg2
from bs4 import BeautifulSoup
import time
import os

# -------------------------
# Configuración de Telegram
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
        if resp.status_code != 200:
            print("Error enviando Telegram:", resp.text)
    except Exception as e:
        print("Excepción enviando Telegram:", e)

# -------------------------
# Configuración de Postgres
# -------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            codigo TEXT,
            descripcion TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# -------------------------
# Login y sesión
# -------------------------
LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("HOMESERVE_USER")
PASSWORD = os.getenv("HOMESERVE_PASS")

def get_session():
    session = requests.Session()
    # Ajusta los nombres de los campos según el formulario real
    payload = {
        "username": USERNAME,
        "password": PASSWORD
    }
    resp = session.post(LOGIN_URL, data=payload)
    if resp.status_code != 200 or "error" in resp.text.lower():
        send_telegram("⚠️ Error logueando en HomeServe.")
        raise Exception("Login failed")
    return session

# -------------------------
# Función de monitor
# -------------------------
def check_website(session):
    try:
        resp = session.get(SERVICIOS_URL)
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.find_all("tr")[1:]  # saltando cabecera

        if not rows:
            return False

        conn = get_connection()
        cur = conn.cursor()

        nuevos = 0
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            codigo = cols[0].text.strip()
            descripcion = cols[1].text.strip()

            # Evitar duplicados
            cur.execute("SELECT 1 FROM servicios WHERE codigo=%s", (codigo,))
            if cur.fetchone():
                continue

            cur.execute(
                "INSERT INTO servicios (codigo, descripcion) VALUES (%s, %s)",
                (codigo, descripcion)
            )
            conn.commit()

            # Enviar cada registro nuevo a Telegram
            send_telegram(f"📌 Nuevo servicio:\nCódigo: {codigo}\nDescripción: {descripcion}")
            nuevos += 1

        cur.close()
        conn.close()
        return nuevos > 0

    except Exception as e:
        print("Error revisando la web:", e)
        return False

# -------------------------
# Loop principal
# -------------------------
def start_monitor():
    setup_db()

    # Enviar mensaje inicial con conteo de servicios
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM servicios")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        send_telegram(f"✅ Bot HomeServe iniciado correctamente. Actualmente hay {count} servicios en la base de datos.")
    except Exception as e:
        print("Error leyendo la DB al iniciar:", e)
        send_telegram("⚠️ Bot arrancó, pero no se pudo leer la DB.")

    print("🚀 Monitor iniciado")

    # Iniciar sesión
    session = get_session()

    # Loop de monitor
    while True:
        has_data = check_website(session)
        if has_data:
            print("📢 Se detectaron nuevos servicios y fueron enviados a Telegram.")
        time.sleep(60)  # cada 60 segundos

# -------------------------
# Arranque del bot
# -------------------------
if __name__ == "__main__":
    start_monitor()
