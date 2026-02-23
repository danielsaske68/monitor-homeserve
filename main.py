import json
import requests
import logging
from flask import Flask, request

# Configuración básica
TOKEN_TELEGRAM = "TU_TOKEN_TELEGRAM"
CHAT_ID = "TU_CHAT_ID"
URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MonitorHomeServe")

app = Flask(__name__)

class MonitorHomeServe:
    def __init__(self):
        self.servicios_alertados = {}

    def cargar_servicios(self):
        try:
            with open("servicios_alertados.json", "r") as f:
                self.servicios_alertados = json.load(f)
        except FileNotFoundError:
            self.servicios_alertados = {}
        except Exception as e:
            logger.error(f"Error cargando servicios: {e}")

    def enviar_menu_telegram(self):
        """Envía el menú principal con botones al usuario"""
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
            mensaje = "👋 ¡Bot HomeServe activo!\nSelecciona una opción:"

            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "Último servicio", "callback_data": "ultimo_servicio"},
                        {"text": "Total servicios", "callback_data": "total_servicios"}
                    ],
                    [
                        {"text": "Login HomeServe", "url": URL_LOGIN},
                        {"text": "Asignación de servicios", "url": URL_SERVICIOS}
                    ]
                ]
            }

            payload = {
                'chat_id': CHAT_ID,
                'text': mensaje,
                'reply_markup': keyboard
            }

            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("[TELEGRAM] Menú enviado correctamente")
                return True
            else:
                logger.error(f"[TELEGRAM] Error enviando menú: {response.status_code} {response.text}")
                return False

        except Exception as e:
            logger.error(f"[TELEGRAM] Excepción al enviar menú: {e}")
            return False

    def manejar_callbacks(self, update):
        """Maneja los botones pulsados por el usuario"""
        if 'callback_query' in update:
            data = update['callback_query']['data']
            chat_id = update['callback_query']['message']['chat']['id']

            if data == "ultimo_servicio":
                if self.servicios_alertados:
                    ultimo_numero = list(self.servicios_alertados.keys())[-1]
                    datos = self.servicios_alertados[ultimo_numero]
                    texto = f"Último servicio:\nNumero: {ultimo_numero}\nTipo: {datos.get('tipo','')} \nEstado: {datos.get('estado','')}"
                else:
                    texto = "No hay servicios registrados aún."
                requests.post(f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage", json={
                    'chat_id': chat_id,
                    'text': texto
                })

            elif data == "total_servicios":
                total = len(self.servicios_alertados)
                texto = f"Actualmente hay {total} servicios en la nube."
                requests.post(f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage", json={
                    'chat_id': chat_id,
                    'text': texto
                })

monitor = MonitorHomeServe()
monitor.cargar_servicios()
monitor.enviar_menu_telegram()

# Endpoint para recibir updates de Telegram (webhook)
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json()
    monitor.manejar_callbacks(update)
    return "OK"

# Ruta mínima para Render
@app.route("/")
def home():
    return "Bot HomeServe activo ✅"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
