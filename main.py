import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import logging
from flask import Flask, jsonify
import psycopg2

# ---------------- VARIABLES ----------------
USUARIO = os.getenv('USUARIO')
CONTRASEÑA = os.getenv('CONTRASEÑA')
TOKEN_TELEGRAM = os.getenv('TOKEN_TELEGRAM')
CHAT_ID = os.getenv('CHAT_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

ARCHIVO_SERVICIOS = "servicios_alertados.json"

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("monitor_homeserve.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------- FLASK ----------------
app = Flask(__name__)

# ---------------- FUNCIONES ----------------

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    """Crea tabla si no existe"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            numero VARCHAR PRIMARY KEY,
            tipo VARCHAR,
            estado VARCHAR,
            fecha_detectado TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def enviar_alerta_telegram(numero, tipo, estado):
    """Envía alerta por Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
        mensaje = f"""NUEVO SERVICIO DISPONIBLE

Numero: {numero}
Tipo: {tipo}
Estado: {estado}
Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"""
        payload = {'chat_id': CHAT_ID, 'text': mensaje}
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"[TELEGRAM] Alerta enviada para {numero}")
        else:
            logger.error(f"[TELEGRAM] Error HTTP {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Excepcion: {e}")

def login(session):
    """Login HomeServe"""
    try:
        response = session.get(URL_LOGIN, timeout=10)
        payload = {'CODIGO': USUARIO, 'PASSW': CONTRASEÑA, 'ACEPT': 'Aceptar'}
        response = session.post(URL_LOGIN, data=payload, timeout=10)
        return 'prof_asignacion' in response.text.lower()
    except Exception as e:
        logger.error(f"[LOGIN] Error: {e}")
        return False

def obtener_servicios(session):
    """Obtiene servicios desde la web"""
    servicios = {}
    try:
        response = session.get(URL_SERVICIOS, timeout=10)
        if response.status_code != 200:
            return servicios
        soup = BeautifulSoup(response.text, 'html.parser')
        filas = soup.find_all('tr')
        for fila in filas:
            celdas = fila.find_all('td')
            if len(celdas) >= 3:
                numero = celdas[0].get_text(strip=True)
                tipo = celdas[1].get_text(strip=True)
                estado = celdas[2].get_text(strip=True)
                if numero.replace('.', '').replace(',', '').isdigit() and len(numero) >= 6:
                    servicios[numero] = {'tipo': tipo, 'estado': estado}
    except Exception as e:
        logger.error(f"[SERVICIOS] Error: {e}")
    return servicios

def guardar_servicio_db(numero, tipo, estado):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO servicios (numero, tipo, estado, fecha_detectado)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (numero) DO NOTHING
        """, (numero, tipo, estado, datetime.now()))
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Error insertando {numero}: {e}")
    finally:
        cur.close()
        conn.close()

@app.route('/check', methods=['GET'])
def check_servicios():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
    })
    if not login(session):
        return jsonify({"error": "Login fallido"}), 500

    servicios = obtener_servicios(session)
    nuevos = 0
    for numero, datos in servicios.items():
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM servicios WHERE numero=%s", (numero,))
        if cur.fetchone() is None:
            enviar_alerta_telegram(numero, datos['tipo'], datos['estado'])
            guardar_servicio_db(numero, datos['tipo'], datos['estado'])
            nuevos += 1
        cur.close()
        conn.close()
    return jsonify({"nuevos_servicios": nuevos})

# ---------------- MAIN ----------------
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
