import os
import json
import re
import asyncio
from flask import Flask, jsonify
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

app = Flask(__name__)

# --- URLs y credenciales ---
LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")

DATA_FILE = "services.json"

# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = Bot(token=TELEGRAM_TOKEN)

# --- Funciones de almacenamiento ---
def load_old_services():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_services(services):
    with open(DATA_FILE, "w") as f:
        json.dump(services, f)

# --- Bot scraping y detección ---
async def run_bot():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        # Login
        await page.goto(LOGIN_URL)
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)
        await page.click('input[type="submit"], button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Ir a servicios
        await page.goto(SERVICIOS_URL)
        await page.wait_for_load_state("networkidle")

        # Extraer servicios desde <td>
        tds = await page.query_selector_all("td")
        services_found = []
        for td in tds:
            text = (await td.inner_text()).strip()
            if re.match(r"^\d{7,9}$", text):
                services_found.append(text)
        services_found = list(set(services_found))

        # Detectar nuevos servicios
        old_services = load_old_services()
        new_services = [s for s in services_found if s not in old_services]

        # Guardar lista actual
        save_services(services_found)

        # Enviar alertas Telegram
        for s in new_services:
            bot.send_message(chat_id=CHAT_ID, text=f"🆕 Nuevo servicio detectado: {s}")

        # Debug
        print("Servicios detectados:", services_found)
        print("Nuevos servicios:", new_services)

        await browser.close()
        return {
            "total_detectados": len(services_found),
            "servicios_actuales": services_found,
            "nuevos_servicios": new_services
        }

# --- Flask ---
@app.route("/")
def home():
    return "Bot activo"

@app.route("/run")
def run():
    try:
        result = asyncio.run(run_bot())
        return jsonify(result)
    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500

# --- Comandos Telegram ---
async def ver_servicios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        services = load_old_services()
        if not services:
            text = "No hay servicios detectados todavía."
        else:
            keyboard = [[InlineKeyboardButton("Refrescar", callback_data="refresh")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = "Servicios actuales:\n" + "\n".join(services)
            await update.message.reply_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    services = load_old_services()
    text = "Servicios actuales:\n" + "\n".join(services)
    await query.edit_message_text(text=text)

# --- Lanzar Telegram ---
def start_telegram_bot():
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler("servicios", ver_servicios))
    app_bot.add_handler(CallbackQueryHandler(button_callback))
    app_bot.run_polling(poll_interval=1)

# --- Ejecutar Flask y Telegram ---
if __name__ == "__main__":
    import threading
    threading.Thread(target=start_telegram_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
