import os
import psycopg2
import requests
from bs4 import BeautifulSoup
from time import sleep

# -----------------------
# Configuración de Telegram
# -----------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    else:
        print("[WARN] Telegram no configurado correctamente.")

# -----------------------
# Conexión a la base de datos
# -----------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if not DATABASE_URL:
        raise Exception("No se ha configurado DATABASE_URL")
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_connection()
    cur = conn.cursor()
    # Crear tabla si no existe (ajusta columnas según tu DB)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id SERIAL PRIMARY KEY,
            detalle TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# -----------------------
# Obtener servicios existentes
# -----------------------
def obtener_servicios_existentes():
    conn = get_connection()
    cur = conn.cursor()
    # Asegúrate de usar la columna correcta
    cur.execute("SELECT detalle FROM servicios")
    servicios_vistos = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return servicios_vistos

# -----------------------
# Monitor principal
# -----------------------
def start_monitor():
    setup_db()
    servicios_vistos = obtener_servicios_existentes()
    # Mensaje inicial al arrancar el bot
    mensaje_inicial = f"Bot arrancado ✅\nServicios existentes en DB: {len(servicios_vistos)}"
    print(mensaje_inicial)
    send_telegram_message(mensaje_inicial)

    while True:
        try:
            # -----------------------
            # Login y obtención de servicios
            # -----------------------
            session = requests.Session()
            login_url = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
            asignacion_url = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

            # Ajusta tus credenciales aquí
            payload = {
                "CODIGO": os.environ.get("HOMESERVE_USER"),
                "PASSW": os.environ.get("HOMESERVE_PASS")
            }
            session.post(login_url, data=payload)

            response = session.get(asignacion_url)
            soup = BeautifulSoup(response.text, "html.parser")

            # Ejemplo: extraer servicios
            servicios_actuales = []
            for servicio in soup.select(".servicio"):
                detalle = servicio.get_text(strip=True)
                servicios_actuales.append(detalle)

            # -----------------------
            # Comparar con DB
            # -----------------------
            nuevos = [s for s in servicios_actuales if s not in servicios_vistos]

            if nuevos:
                mensaje = f"🔔 Nuevos servicios detectados:\n" + "\n".join(nuevos)
                send_telegram_message(mensaje)
                # Guardar nuevos en DB
                conn = get_connection()
                cur = conn.cursor()
                for s in nuevos:
                    cur.execute("INSERT INTO servicios (detalle) VALUES (%s)", (s,))
                conn.commit()
                cur.close()
                conn.close()
                servicios_vistos.extend(nuevos)

        except Exception as e:
            print(f"[ERROR] {e}")
            send_telegram_message(f"[ERROR] {e}")

        sleep(60)  # Revisa cada 1 minuto

# -----------------------
# Ejecutar el bot
# -----------------------
if __name__ == "__main__":
    start_monitor()
