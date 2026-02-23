# main.py
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# CONFIGURACIÓN DEL BOT
# =========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7827444792:AAF0rtSLFQl4pRUATbSqGl0U9imZQdfCRAU")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# =========================
# MOCK DE SERVICIOS
# =========================
def obtener_servicios_mock():
    """Devuelve los servicios actuales sin login (solo prueba)."""
    return [
        {"id": "15313040", "url": "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion&servicio=15313040"},
        {"id": "15425931", "url": "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion&servicio=15425931"}
    ]

# =========================
# FUNCIONES DE TELEGRAM
# =========================
def send_message(chat_id, text):
    """Envía mensaje a Telegram."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("Error enviando mensaje:", e)

# =========================
# WEBHOOK DE TELEGRAM
# =========================
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data:
        return jsonify({"ok": False, "error": "No JSON"}), 400

    chat_id = None
    text_to_send = ""

    # Manejar callback_query
    if "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["from"]["id"]
        data_callback = query["data"]
        if data_callback == "ultimo":
            servicios = obtener_servicios_mock()
            if servicios:
                ultimo = servicios[-1]
                text_to_send = f"Último servicio:\n{ultimo['id']}: {ultimo['url']}"
            else:
                text_to_send = "No hay servicios disponibles."
        elif data_callback == "total":
            servicios = obtener_servicios_mock()
            text_to_send = f"Número de servicios actuales: {len(servicios)}"
    # Manejar mensajes normales
    elif "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text_to_send = "Hola 👷‍♂️\nSelecciona una opción en el menú."

    if chat_id and text_to_send:
        send_message(chat_id, text_to_send)

    return jsonify({"ok": True})

# =========================
# RUTA PRINCIPAL (solo prueba)
# =========================
@app.route("/", methods=["GET"])
def index():
    return "Monitor HomeServe Bot activo ✅", 200

# =========================
# INICIO DE LA APP
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
