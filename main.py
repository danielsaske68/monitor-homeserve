import os
import time
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask
from threading import Thread

# =========================
# Configuración (AHORA DESDE ENV)
# =========================
LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USUARIO = os.environ.get("USUARIO")
PASSWORD = os.environ.get("PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

REVISAR_CADA = 60

# =========================
# Inicialización
# =========================
app = Flask(__name__)
session = requests.Session()
ultimos_servicios = set()
historial_servicios = []

# =========================
# Funciones Web
# =========================
def login():
    payload = {"username": USUARIO, "password": PASSWORD}
    r = session.post(LOGIN_URL, data=payload)
    return r.status_code == 200

def obtener_servicios():
    r = session.get(SERVICIOS_URL)
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    elementos = soup.find_all("div", class_="servicio")
    return [e.text.strip() for e in elementos]

def revisar_nuevos_servicios(bot):
    global ultimos_servicios, historial_servicios
    servicios_actuales = set(obtener_servicios())
    nuevos = servicios_actuales - ultimos_servicios

    if nuevos:
        mensaje = "🚨 Nuevos servicios:\n\n" + "\n\n".join(nuevos)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje)
        historial_servicios.extend(nuevos)
        print(mensaje)

    ultimos_servicios = servicios_actuales

# =========================
# Comandos Telegram
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Últimos servicios", callback_data="ultimos")],
        [InlineKeyboardButton("Historial", callback_data="historial")],
        [InlineKeyboardButton("Asignación", url=SERVICIOS_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🤖 Monitor activo", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ultimos":
        mensaje = "📝 Últimos servicios:\n\n" + "\n\n".join(ultimos_servicios) if ultimos_servicios else "No hay servicios aún."
        await query.edit_message_text(text=mensaje)

    elif query.data == "historial":
        mensaje = "📜 Historial (últimos 50):\n\n" + "\n\n".join(historial_servicios[-50:]) if historial_servicios else "No hay historial aún."
        await query.edit_message_text(text=mensaje)

# =========================
# Flask endpoint (OBLIGATORIO PARA RENDER)
# =========================
@app.route("/")
def home():
    return "🤖 Monitor activo", 200

# =========================
# Monitor Loop
# =========================
def iniciar_monitor(bot):
    if not login():
        print("❌ No se pudo iniciar sesión.")
        return

    global ultimos_servicios
    ultimos_servicios = set(obtener_servicios())
    print("✅ Estado inicial cargado")

    while True:
        revisar_nuevos_servicios(bot)
        time.sleep(REVISAR_CADA)

# =========================
# Bot Telegram
# =========================
def iniciar_bot():
    app_telegram = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CallbackQueryHandler(button))

    bot_instance = app_telegram.bot

    Thread(target=iniciar_monitor, args=(bot_instance,), daemon=True).start()

    print("🤖 Bot iniciado")
    app_telegram.run_polling()

# =========================
# Ejecución principal (VERSIÓN RENDER)
# =========================
if __name__ == "__main__":
    Thread(target=iniciar_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
