import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # tu chat ID de prueba
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# Botones de prueba
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"}],
            [{"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "📋 Guardados", "callback_data": "GUARDADOS"}]
        ]
    }

# Función para enviar mensaje
def enviar(chat, texto):
    requests.post(
        TELEGRAM_API + "/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "reply_markup": botones()
        },
        timeout=10
    )

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    # Revisamos si es un callback de botón
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]

        if accion == "LOGIN":
            enviar(chat, "✅ Login simulado OK")
        elif accion == "REFRESH":
            enviar(chat, "🔄 Refresh simulado")
        elif accion == "GUARDADOS":
            enviar(chat, "📋 Guardados simulados")

    # Revisamos si es un mensaje /start
    elif "message" in data and "text" in data["message"]:
        chat = data["message"]["chat"]["id"]
        texto = data["message"]["text"]

        if texto == "/start":
            enviar(chat, "👋 ¡Bot activo! Prueba los botones.")

    return jsonify(ok=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
