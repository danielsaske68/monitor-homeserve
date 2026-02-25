import requests
from bs4 import BeautifulSoup
import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

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


# ===== TELEGRAM =====

def menu():

    teclado = [

        [InlineKeyboardButton("🔑 Login", callback_data="login")],

        [InlineKeyboardButton("📋 Ir a asignación", callback_data="asignacion")],

        [InlineKeyboardButton("🔄 Refrescar", callback_data="refrescar")],

        [InlineKeyboardButton("📦 Servicios actuales", callback_data="actuales")]

    ]

    return InlineKeyboardMarkup(teclado)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(

        "Monitor Homeserve activo",

        reply_markup=menu()

    )


async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    # LOGIN

    if query.data == "login":

        session.get(LOGIN_URL)

        await query.edit_message_text(

            "Login abierto en sesión",

            reply_markup=menu()

        )


    # IR A ASIGNACION

    if query.data == "asignacion":

        session.get(SERVICIOS_URL)

        await query.edit_message_text(

            "Página asignación abierta",

            reply_markup=menu()

        )


    # REFRESCAR

    if query.data == "refrescar":

        servicios = obtener_servicios()

        texto = "\n\n-----------\n\n".join(servicios[:10])

        await query.edit_message_text(

            f"Refrescado\n\n{texto}",

            reply_markup=menu()

        )


    # TODOS

    if query.data == "actuales":

        servicios = obtener_servicios()

        texto = "\n\n-----------\n\n".join(servicios)

        await query.edit_message_text(

            f"Servicios actuales:\n\n{texto}",

            reply_markup=menu()

        )


# ===== MONITOR AUTOMATICO =====

async def monitor(app):

    global servicios_guardados

    while True:

        servicios = obtener_servicios()

        nuevos = [s for s in servicios if s not in servicios_guardados]

        if nuevos:

            for s in nuevos:

                texto = f"🚨 NUEVO SERVICIO\n\n{s}"

                await app.bot.send_message(CHAT_ID, texto)

        servicios_guardados = servicios

        await asyncio.sleep(CHECK_INTERVAL)


# ===== MAIN =====

async def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(botones))


    asyncio.create_task(monitor(app))

    await app.run_polling()


if __name__ == "__main__":

    asyncio.run(main())
