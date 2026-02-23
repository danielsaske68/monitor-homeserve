import requests
from bs4 import BeautifulSoup
from flask import Flask, request
import logging

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Datos de HomeServe
HOMESERVE_LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
HOMESERVE_ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
CODIGO = "16205"   # reemplaza con tu usuario
PASSW = "Aventura60,"     # reemplaza con tu contraseña

# Datos de Telegram
BOT_TOKEN = "7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU"  # reemplaza con tu token
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# Función para login y mantener sesión
def login_homeserve():
    logging.info("Intentando loguearse en HomeServe...")
    session = requests.Session()
    payload = {
        "usuario": CODIGO,
        "clave": PASSW
    }
    response = session.post(HOMESERVE_LOGIN_URL, data=payload)
    if "Perfil" in response.text or response.status_code == 200:
        logging.info("Login exitoso ✅")
        return session
    else:
        logging.error("Error de login ❌")
        return None

# Función para obtener servicios
def obtener_servicios(session):
    response = session.get(HOMESERVE_ASIGNACION_URL)
    soup = BeautifulSoup(response.text, "html.parser")
    servicios = []

    for a in soup.find_all("a", href=True):
        if "prof_asignacion&servicio=" in a['href']:
            servicio_id = a.text.strip()
            servicios.append(servicio_id)

    logging.info(f"Servicios encontrados: {len(servicios)}")
    return servicios

# Función para enviar mensajes a Telegram
def enviar_telegram(chat_id, texto):
    requests.post(TELEGRAM_API, json={
        "chat_id": chat_id,
        "text": texto
    })

# Endpoint webhook de Telegram
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json()
    logging.info(f"Llegó actualización de Telegram: {update}")

    chat_id = None
    comando = None

    # Manejar callback_query o mensaje normal
    if "callback_query" in update:
        comando = update['callback_query']['data']
        chat_id = update['callback_query']['message']['chat']['id']
    elif "message" in update:
        comando = update['message'].get('text')
        chat_id = update['message']['chat']['id']
    else:
        logging.error("Webhook recibido sin 'message' ni 'callback_query'")
        return "OK", 200

    session = login_homeserve()
    if not session:
        enviar_telegram(chat_id, "❌ Error al loguearse en HomeServe")
        return "OK", 200

    servicios = obtener_servicios(session)

    # Comandos del bot
    if comando == "ultimo":
        if servicios:
            enviar_telegram(chat_id, f"📌 Último servicio: {servicios[0]}")
        else:
            enviar_telegram(chat_id, "No se encontraron servicios.")
    elif comando == "total":
        enviar_telegram(chat_id, f"📊 Número de servicios: {len(servicios)}")
    else:
        enviar_telegram(chat_id, "Comando no reconocido.")

    return "OK", 200

# Endpoint de prueba
@app.route("/test_servicios", methods=["GET"])
def test_servicios():
    session = login_homeserve()
    if not session:
        return "Error al loguearse en HomeServe ❌", 500

    servicios = obtener_servicios(session)
    return {"servicios": servicios}, 200

# Inicio de la app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
