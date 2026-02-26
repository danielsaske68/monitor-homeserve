import os
import time
import logging
import threading
import requests

from flask import Flask
from bs4 import BeautifulSoup

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"

CHECK_INTERVAL = 120

logging.basicConfig(level=logging.INFO)

# =========================
# FLASK
# =========================

app = Flask(__name__)

@app.route('/')
def home():
    return "Monitor HomeServe activo"


@app.route('/login')
def login():
    return "Login Telegram activo"


@app.route('/servicios')
def servicios():
    return "Servicios disponibles"


# =========================
# SCRAPER
# =========================

servicios_guardados = []


def obtener_servicios():

    try:

        r = requests.get(URL, timeout=20)

        soup = BeautifulSoup(r.text, "html.parser")

        servicios = []

        for a in soup.find_all("a"):

            texto = a.get_text(strip=True)

            if texto and len(texto) > 5:

                servicios.append(texto)

        servicios = list(set(servicios))

        logging.info(f"Servicios detectados: {len(servicios)}")

        return servicios

    except Exception as e:

        logging.error(e)

        return []


# =========================
# TELEGRAM MENU
# =========================

def menu():

    keyboard = [

        [InlineKeyboardButton("🔄 Actualizar", callback_data="actualizar")],

        [InlineKeyboardButton("📋 Ver servicios actuales", callback_data="ver")],

        [InlineKeyboardButton("🌐 Servicios Web", url=SERVICIOS_URL)],

        [InlineKeyboardButton("🔑 Login Telegram", url=LOGIN_URL)]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# /START
# =========================

def start(update, context):

    update.message.reply_text(

        "Monitor HomeServe activo",

        reply_markup=menu()

    )


# =========================
# BOTONES
# =========================

def botones(update, context):

    query = update.callback_query

    query.answer()

    global servicios_guardados


    # ACTUALIZAR

    if query.data == "actualizar":

        nuevos = obtener_servicios()

        if not servicios_guardados:

            servicios_guardados = nuevos

            texto = "Base guardada"

        else:

            cambios = []

            for s in nuevos:

                if s not in servicios_guardados:

                    cambios.append(s)

            servicios_guardados = nuevos

            if cambios:

                texto = "Nuevos servicios:\n\n"

                for c in cambios:

                    texto += "- " + c + "\n"

            else:

                texto = "No hay cambios"

        query.edit_message_text(

            texto,

            reply_markup=menu()

        )


    # VER SERVICIOS

    if query.data == "ver":

        actuales = obtener_servicios()

        if not actuales:

            texto = "No hay servicios"

        else:

            texto = "Servicios actuales:\n\n"

            for s in actuales:

                texto += "- " + s + "\n"

        query.edit_message_text(

            texto,

            reply_markup=menu()

        )


# =========================
# MONITOR AUTOMATICO
# =========================

def monitor():

    global servicios_guardados

    while True:

        try:

            nuevos = obtener_servicios()

            if not servicios_guardados:

                servicios_guardados = nuevos

            else:

                cambios = []

                for s in nuevos:

                    if s not in servicios_guardados:

                        cambios.append(s)

                if cambios and TOKEN and CHAT_ID:

                    texto = "Nuevo servicio detectado:\n\n"

                    for c in cambios:

                        texto += "- " + c + "\n"

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        data={

                            "chat_id": CHAT_ID,

                            "text": texto

                        }

                    )

                servicios_guardados = nuevos

        except Exception as e:

            logging.error(e)

        time.sleep(CHECK_INTERVAL)


# =========================
# TELEGRAM INIT
# =========================

def iniciar_bot():

    if not TOKEN:

        print("ERROR BOT_TOKEN no encontrado")
        return

    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    dp.add_handler(CallbackQueryHandler(botones))

    updater.start_polling()

    print("Telegram iniciado")


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    threading.Thread(target=iniciar_bot).start()

    threading.Thread(target=monitor).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
