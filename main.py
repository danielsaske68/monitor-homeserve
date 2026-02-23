import os
import asyncio
from flask import Flask, jsonify
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

# ====================
# Configuración
# ====================
USERNAME = os.environ.get("USERNAME")
PASSWORD = os.environ.get("PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)

# Estado global para servicios detectados
SERVICIOS_DETECTADOS = set()

bot = Bot(token=TELEGRAM_TOKEN)

# ====================
# Funciones Playwright
# ====================
async def obtener_servicios():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales")
        
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)
        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")
        
        # Ir a la pestaña de servicios
        await page.goto("https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion")
        await page.wait_for_load_state("networkidle")
        
        # Extraer números de servicios
        rows = await page.query_selector_all("td")
        servicios = set()
        for td in rows:
            text = await td.inner_text()
            if text.isdigit():
                servicios.add(text)
        
        await browser.close()
        return servicios

# ====================
# Funciones Telegram
# ====================
async def enviar_nuevos(servicios_nuevos):
    for s in servicios_nuevos:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Nuevo servicio detectado: {s}")

async def check_nuevos_servicios():
    global SERVICIOS_DETECTADOS
    servicios_actuales = await obtener_servicios()
    nuevos = servicios_actuales - SERVICIOS_DETECTADOS
    if nuevos:
        await enviar_nuevos(nuevos)
    SERVICIOS_DETECTADOS = servicios_actuales

# ====================
# Rutas Flask
# ====================
@app.route("/")
def index():
    return "Monitor Homeserve en marcha 🚀"

@app.route("/run")
def run():
    asyncio.run(check_nuevos_servicios())
    return jsonify({"servicios_actuales": list(SERVICIOS_DETECTADOS)})

# ====================
# Comandos Telegram
# ====================
async def start(update, context):
    keyboard = [
        [InlineKeyboardButton("Ver servicios", callback_data="ver_servicios")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Monitor Homeserve activo ✅", reply_markup=reply_markup)

async def button(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "ver_servicios":
        servicios = "\n".join(SERVICIOS_DETECTADOS) if SERVICIOS_DETECTADOS else "No hay servicios."
        await query.edit_message_text(text=f"Servicios actuales:\n{servicios}")

# ====================
# Inicialización Telegram
# ====================
def iniciar_bot_telegram():
    app_telegram = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CallbackQueryHandler(button))
    return app_telegram

# ====================
# Main
# ====================
if __name__ == "__main__":
    # Lanzar bot Telegram en segundo plano
    app_telegram = iniciar_bot_telegram()
    loop = asyncio.get_event_loop()
    loop.create_task(app_telegram.start())
    
    # Lanzar Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
