# ===== PARCHE PYTHON 3.14 (OBLIGATORIO PARA TELEGRAM) =====
import sys
import types

imghdr = types.ModuleType("imghdr")
imghdr.what = lambda *args, **kwargs: None
sys.modules["imghdr"] = imghdr
# ===========================================================


import requests
from bs4 import BeautifulSoup
import time
import threading
import os
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

from flask import Flask

# ===== CONFIG =====

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

INTERVALO = 60

# ===== LOGS =====

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# ===== VARIABLES =====

bot_activo = False
servicios_guardados = []

session = requests.Session()


# ===== LOGIN =====

def login():

    logging.info("Login...")

    data = {
        "email": os.environ.get("EMAIL"),
        "password": os.environ.get("PASSWORD")
    }

    session.post(URL_LOGIN, data=data)


# ===== SCRAPER =====

def obtener_servicios():

    r = session.get(URL_SERVICIOS)

    soup = BeautifulSoup(r.text, "html.parser")

    servicios = []

    for s in soup.find_all("tr"):

        texto = s.get_text(strip=True)

        if len(texto) > 20:
            servicios.append(texto)

    return servicios


# ===== TELEGRAM BOTONES =====

def menu():

    teclado = [
        [InlineKeyboardButton("▶️ Arrancar bot", callback_data="startbot")],
        [InlineKeyboardButton("🔐 Login", callback_data="login")],
        [InlineKeyboardButton("📋 Ver servicios", callback_data="servicios")],
        [InlineKeyboardButton("🔄 Actualizar", callback_data="actualizar")]
    ]

    return InlineKeyboardMarkup(teclado)


# ===== START TELEGRAM =====

def start(update, context):

    update.message.reply_text(
        "Bot Homeserve listo",
        reply_markup=menu()
    )


# ===== BOTONES =====

def botones(update, context):

    global bot_activo
    global servicios_guardados

    query = update.callback_query
    query.answer()

    if query.data == "startbot":

        bot_activo = True

        query.edit_message_text(
            "Bot arrancado",
            reply_markup=menu()
        )

    elif query.data == "login":

        login()

        query.edit_message_text(
            "Login hecho",
            reply_markup=menu()
        )


    elif query.data == "servicios":

        servicios = obtener_servicios()

        if not servicios:

            texto = "No hay servicios"

        else:

            texto = ""

            for s in servicios:
                texto += "• " + s + "\n\n"

        query.edit_message_text(
            texto,
            reply_markup=menu()
        )


    elif query.data == "actualizar":

        servicios = obtener_servicios()

        servicios_guardados = servicios

        texto = "Actualizado\n\n"

        for s in servicios:
            texto += "• " + s + "\n\n"

        query.edit_message_text(
            texto,
            reply_markup=menu()
        )


# ===== MONITOR =====

def monitor():

    global servicios_guardados
    global bot_activo

    while True:

        if bot_activo:

            try:

                servicios = obtener_servicios()

                nuevos = []

                for s in servicios:

                    if s not in servicios_guardados:
                        nuevos.append(s)

                if nuevos:

                    texto = "NUEVOS SERVICIOS\n\n"

                    for n in nuevos:
                        texto += "• " + n + "\n\n"

                    updater.bot.send_message(
                        chat_id=CHAT_ID,
                        text=texto
                    )

                    servicios_guardados = servicios

                    logging.info("Servicios nuevos detectados")

            except Exception as e:

                logging.info("Error monitor")
                logging.info(e)

        time.sleep(INTERVALO)


# ===== TELEGRAM =====

updater = Updater(TOKEN, use_context=True)

dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))

dp.add_handler(CallbackQueryHandler(botones))


# ===== FLASK PARA RENDER =====

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot activo"


def web():

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )


# ===== ARRANQUE =====

threading.Thread(target=web).start()

threading.Thread(target=monitor).start()

updater.start_polling()

print("BOT ARRANCADO")

updater.idle()
