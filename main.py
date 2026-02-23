# main.py
import os
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Config Telegram
BOT_TOKEN = os.getenv("7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU")  # Pon tu token aquí en Render Environment
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Config HomeServe
HOMESERVE_USER = os.getenv("HOMESERVE_USER")
HOMESERVE_PASS = os.getenv("HOMESERVE_PASS")
HOMESERVE_LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
HOMESERVE_ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

session = requests.Session()


def login_homeserve():
    """Login a HomeServe y mantener la sesión."""
    logging.info("Intentando loguearse en HomeServe...")
    data = {
        'usuario': HOMESERVE_USER,
        'pass': HOMESERVE_PASS
    }
    r = session.post(HOMESERVE_LOGIN_URL, data=data)
    if "Bienvenido" in r.text or r.status_code == 200:
        logging.info("Login exitoso ✅")
        return True
    logging.error("Login fallido ❌")
    return False


def obtener_servicios():
    """Extraer los servicios actuales de HomeServe."""
    r = session.get(HOMESERVE_ASIGNACION_URL)
    soup = BeautifulSoup(r.text, 'html.parser')
    servicios = []

    # Buscar todos los enlaces dentro de <tr> que contienen los números de servicio
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=True)
        if a and a.text.strip().isdigit():
            servicios.append({
                "id": a.text.strip(),
                "url": a['href']
            })
    logging.info(f"Servicios encontrados: {len(servicios)}")
    return servicios


def send_message(chat_id, text):
    """Enviar mensaje a Telegram."""
    url = f"{TELEGRAM_API}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=data)


@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json()
    logging.info(f"Llegó actualización de Telegram: {update}")

    chat_id = None
    callback_data = None

    # Manejar mensaje normal
    if 'message' in update:
        chat_id = update['message']['chat']['id']
        text = update['message']['text']
    # Manejar botón (callback_query)
    elif 'callback_query' in update:
        chat_id = update['callback_query']['message']['chat']['id']
        callback_data = update['callback_query']['data']

    if chat_id is None:
        return jsonify({"ok": True})

    # Comandos
    if callback_data == "ultimo":
        servicios = obtener_servicios()
        if servicios:
            s = servicios[-1]
            send_message(chat_id, f"Último servicio: {s['id']}\nURL: {s['url']}")
        else:
            send_message(chat_id, "No se encontraron servicios 😢")
    elif callback_data == "total":
        servicios = obtener_servicios()
        send_message(chat_id, f"Número de servicios: {len(servicios)}")
    else:
        # Mensaje normal
        send_message(chat_id, "Hola 👷‍♂️\nUsa los botones para consultar tus servicios.")

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def index():
    return "Monitor HomeServe funcionando ✅"


if __name__ == "__main__":
    if login_homeserve():
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
