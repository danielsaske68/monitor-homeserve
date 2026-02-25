# PARCHE PYTHON 3.14 (NO CAMBIA TU BOT)
import sys
import types

if "imghdr" not in sys.modules:
    imghdr = types.ModuleType("imghdr")
    imghdr.what = lambda *args, **kwargs: None
    sys.modules["imghdr"] = imghdr


# TU SCRIPT ORIGINAL (SIN CAMBIOS)

import requests
from bs4 import BeautifulSoup
import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

# CONFIG
TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

CHECK_INTERVAL = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

session = requests.Session()
servicios_guardados = []
bot_arrancado = False


# ===== SCRAPER =====

def obtener_servicios():

    try:

        r = session.get(SERVICIOS_URL)

        soup = BeautifulSoup(r.text, "html.parser")

        bloques = soup.find_all("tr")

        servicios = []

        for b in bloques:

            texto = b.get_text("\n", strip=True)

            if len(texto) > 30:
                servicios.append(texto)

        logger.info(f"Servicios detectados: {len(servicios)}")

        return servicios

    except Exception as e:

        logger.error(e)
        return []


# ===== MENU =====

def menu():

    teclado = [

        [InlineKeyboardButton("🔑 Login", callback_data="login")],

        [InlineKeyboardButton("📋 Ir a asignación", callback_data="asignacion")],

        [InlineKeyboardButton("🔄 Refrescar", callback_data="refrescar")],

        [InlineKeyboardButton("📦 Servicios actuales", callback_data="actuales")]

    ]

    return InlineKeyboardMarkup(teclado)


# ===== START =====

def start(update, context):

    global bot_arrancado

    bot_arrancado = True

    update.message.reply_text(
        "Monitor Homeserve ARRANCADO",
        reply_markup=menu()
    )


# ===== BOTONES =====

def botones(update, context):

    query = update.callback_query
    query.answer()

    if query.data == "login":

        session.get(LOGIN_URL)

        query.edit_message_text(
            "Login realizado",
            reply_markup=menu()
        )


    if query.data == "asignacion":

        session.get(SERVICIOS_URL)

        query.edit_message_text(
            "Asignación abierta",
            reply_markup=menu()
        )


    if query.data == "refrescar":

        servicios = obtener_servicios()

        texto = "\n\n-----------\n\n".join(servicios[:10])

        query.edit_message_text(
            f"Actualizado\n\n{texto}",
            reply_markup=menu()
        )


    if query.data == "actuales":

        servicios = obtener_servicios()

        texto = "\n\n-----------\n\n".join(servicios)

        query.edit_message_text(
            f"Servicios actuales\n\n{texto}",
            reply_markup=menu()
        )


# ===== MONITOR =====

async def monitor(bot):

    global servicios_guardados
    global bot_arrancado

    while True:

        if bot_arrancado:

            servicios = obtener_servicios()

            nuevos = [s for s in servicios if s not in servicios_guardados]

            if nuevos:

                for s in nuevos:

                    bot.send_message(
                        chat_id=CHAT_ID,
                        text=f"🚨 NUEVO SERVICIO\n\n{s}"
                    )

            servicios_guardados = servicios

        await asyncio.sleep(CHECK_INTERVAL)


# ===== MAIN =====

def main():

    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    dp.add_handler(CallbackQueryHandler(botones))

    updater.start_polling()

    loop = asyncio.get_event_loop()
    loop.create_task(monitor(updater.bot))

    updater.idle()


if __name__ == "__main__":
    main()
