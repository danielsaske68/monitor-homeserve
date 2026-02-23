import os
import json
import threading
import time
import requests
from flask import Flask, jsonify
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIG ---
USERNAME = os.environ.get("USERNAME")
PASSWORD = os.environ.get("PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# Almacenamiento temporal de servicios detectados
servicios_detectados = set()

# --- FUNCIONES ---
def obtener_servicios():
    # Aquí pones tu scraping o API real
    # Este ejemplo simula la respuesta
    response = {
        "nuevos_servicios": ["955855521","15425931","15313040"],
        "servicios_actuales": ["955855521","15425931","15313040"]
    }
    return response

def check_servicios():
    global servicios_detectados
    while True:
        data = obtener_servicios()
        actuales = set(data.get("servicios_actuales", []))
        nuevos = actuales - servicios_detectados
        if nuevos:
            for s in nuevos:
                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Nuevo servicio detectado: {s}")
        servicios_detectados = actuales
        time.sleep(60)  # Revisa cada 60s

# --- FLASK ROUTES ---
@app.route('/')
def home():
    return "Bot de servicios corriendo ✅"

@app.route('/servicios')
def listar_servicios():
    return jsonify(list(servicios_detectados))

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Ver servicios", callback_data="ver")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Bot iniciado ✅", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ver":
        await query.edit_message_text(text="Servicios actuales:\n" + "\n".join(servicios_detectados))

def run_telegram():
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button))
    app_bot.run_polling()

# --- MAIN ---
if __name__ == "__main__":
    # Correr chequeo en background
    t1 = threading.Thread(target=check_servicios, daemon=True)
    t1.start()

    # Correr bot de telegram en otro thread
    t2 = threading.Thread(target=run_telegram, daemon=True)
    t2.start()

    # Correr Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
