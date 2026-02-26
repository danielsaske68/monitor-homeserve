import os
import time
import logging
import threading

import requests
from bs4 import BeautifulSoup
from flask import Flask
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

# =========================
# CONFIG
# =========================

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# =========================
# LOGS
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# FLASK (Render necesita esto)
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot funcionando OK"


# =========================
# SESSION LOGIN
# =========================

session = requests.Session()


def login():

    try:

        payload = {
            "email": os.getenv("USER_EMAIL"),
            "password": os.getenv("USER_PASSWORD")
        }

        session.post(LOGIN_URL, data=payload)

        logger.info("Login OK")

    except Exception as e:
        logger.error("Error login: %s", e)


# =========================
# SCRAPING
# =========================

def obtener_servicios():

    try:

        r = session.get(SERVICIOS_URL)

        soup = BeautifulSoup(r.text, "html.parser")

        servicios = []

        for s in soup.find_all("tr"):

            texto = s.get_text(" ", strip=True)

            if len(texto) > 20:
                servicios.append(texto)

        logger.info(f"Servicios detectados: {len(servicios)}")

        return servicios

    except Exception as e:

        logger.error("Error obteniendo servicios: %s", e)

        return []


# =========================
# BOTONES TELEGRAM
# =========================

def menu():

    keyboard = [

        [InlineKeyboardButton("🔄 Actualizar", callback_data="actualizar")],

        [InlineKeyboardButton("📋 Ver servicios actuales", callback_data="ver")]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# COMANDO START
# =========================

def start(update, context):

    update.message.reply_text(
        "Bot Homeserve activo",
        reply_markup=menu()
    )


# =========================
# BOTONES
# =========================

def botones(update, context):

    query = update.callback_query

    query.answer()

    if query.data == "actualizar":

        servicios = obtener_servicios()

        if servicios:

            texto = "\n\n".join(servicios)

        else:

            texto = "No hay servicios"

        query.edit_message_text(texto, reply_markup=menu())


    if query.data == "ver":

        servicios = obtener_servicios()

        if servicios:

            texto = "\n\n".join(servicios)

        else:

            texto = "No hay servicios"

        query.edit_message_text(texto, reply_markup=menu())


# =========================
# MONITOR AUTOMATICO
# =========================

servicios_anteriores = []


def monitor():

    global servicios_anteriores

    login()

    while True:

        servicios = obtener_servicios()

        if servicios != servicios_anteriores:

            servicios_anteriores = servicios

            if servicios:

                texto = "Nuevos servicios:\n\n" + "\n\n".join(servicios)

                bot.send_message(chat_id=CHAT_ID, text=texto)

        time.sleep(60)


# =========================
# TELEGRAM BOT
# =========================

def iniciar_bot():

    global updater
    global bot

    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    dp.add_handler(CallbackQueryHandler(botones))

    bot = updater.bot

    updater.start_polling()

    logger.info("Bot Telegram iniciado")


# =========================
# ARRANQUE
# =========================

iniciar_bot()

threading.Thread(target=monitor).start()
