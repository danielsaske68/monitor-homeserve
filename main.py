import requests
from bs4 import BeautifulSoup
import re
import logging
from flask import Flask, request, jsonify

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# URL y credenciales HomeServe
LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
USUARIO = "16205"
PASSW = "Aventura60,"

# Token del bot
TELEGRAM_BOT_TOKEN = "7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU"

def login_homeserve():
    session = requests.Session()
    logging.info("Intentando loguearse en HomeServe...")

    # HomeServe necesita POST con campos exactos
    payload = {
        'usuario': USUARIO,
        'passw': PASSW
    }

    resp = session.post(LOGIN_URL, data=payload)
    if "Logout" in resp.text or resp.status_code == 200:
        logging.info("Login exitoso ✅")
        return session
    logging.error("Error de login ❌")
    return None

def obtener_servicios(session):
    resp = session.get(ASIGNACION_URL)
    html = resp.text

    # Buscar todos los números de 8 dígitos
    servicios = re.findall(r'\b\d{8}\b', html)
    logging.info(f"Servicios encontrados: {len(servicios)}")
    return servicios

@app.route("/test_servicios")
def test_servicios():
    session = login_homeserve()
    if not session:
        return jsonify({"error": "No se pudo loguear"}), 500

    servicios = obtener_servicios(session)
    return jsonify({"servicios": servicios, "cantidad": len(servicios)})

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json()
    logging.info(f"Llegó actualización de Telegram: {update}")

    # Ejemplo simple: responder /servicios
    try:
        chat_id = update['message']['chat']['id']
        text = update['message']['text']

        if text == "/servicios":
            session = login_homeserve()
            if not session:
                mensaje = "No se pudo loguear en HomeServe ❌"
            else:
                servicios = obtener_servicios(session)
                if servicios:
                    mensaje = "Servicios activos:\n" + "\n".join(servicios)
                else:
                    mensaje = "No se encontraron servicios activos."
            
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": chat_id, "text": mensaje}
            )

    except Exception as e:
        logging.error(f"Error en webhook: {e}")

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
