from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os
import re
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# VARIABLES DE ENTORNO
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
HS_USER = os.environ.get("HS_USER")
HS_PASS = os.environ.get("HS_PASS")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# =========================
# TELEGRAM
# =========================
def send_message(chat_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    requests.post(url, json=payload)


# =========================
# SCRAPING HOMESERVE
# =========================
def obtener_servicios():
    try:
        session = requests.Session()

        # LOGIN
        login_payload = {
            "usuario": HS_USER,
            "password": HS_PASS
        }

        session.post(LOGIN_URL, data=login_payload)

        # IR A ASIGNACIÓN
        response = session.get(ASIGNACION_URL)

        soup = BeautifulSoup(response.text, "html.parser")

        # Buscar números de 8 dígitos
        servicios = set()
        textos = soup.get_text()

        matches = re.findall(r"\b\d{8}\b", textos)

        for m in matches:
            servicios.add(m)

        servicios = sorted(list(servicios))

        return servicios

    except Exception as e:
        logging.error(f"Error obteniendo servicios: {e}")
        return []


# =========================
# WEBHOOK
# =========================
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text == "/start":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📌 Último servicio", "callback_data": "ultimo"}],
                    [{"text": "📊 Número de servicios", "callback_data": "total"}],
                    [{"text": "🔐 Login HomeServe", "url": LOGIN_URL}],
                    [{"text": "📂 Ir a Asignación", "url": ASIGNACION_URL}]
                ]
            }

            send_message(chat_id, "Bienvenido 👷‍♂️\nSelecciona una opción:", keyboard)

    elif "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        accion = data["callback_query"]["data"]

        servicios = obtener_servicios()

        if accion == "ultimo":
            if servicios:
                send_message(chat_id, f"📌 Último servicio:\n{servicios[-1]}")
            else:
                send_message(chat_id, "No se encontraron servicios.")

        elif accion == "total":
            send_message(chat_id, f"📊 Total servicios disponibles:\n{len(servicios)}")

    return {"ok": True}


@app.route("/")
def home():
    return "Bot HomeServe funcionando ✅"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
