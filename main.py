import os
import asyncio
from flask import Flask, jsonify
from playwright.async_api import async_playwright
from telegram import Bot

app = Flask(__name__)

USERNAME = os.environ.get("USERNAME")
PASSWORD = os.environ.get("PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)

servicios_vistos = set()

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

async def revisar_servicios():
    global servicios_vistos
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(LOGIN_URL)
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)
        await page.click('input[type="submit"]')
        await page.wait_for_load_state('networkidle')
        await page.goto(SERVICIOS_URL)
        rows = await page.query_selector_all("td")
        nuevos = []
        for row in rows:
            texto = await row.inner_text()
            if texto.isdigit() and texto not in servicios_vistos:
                servicios_vistos.add(texto)
                nuevos.append(texto)
        await browser.close()
        return nuevos

async def enviar_telegram(servicios):
    for s in servicios:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Nuevo servicio detectado: {s}")

@app.route("/run")
def run():
    nuevos = asyncio.run(revisar_servicios())
    if nuevos:
        asyncio.run(enviar_telegram(nuevos))
    return jsonify({"nuevos_servicios": nuevos, "total_detectados": len(nuevos)})

@app.route("/")
def index():
    return "Bot Homeserve activo 🚀"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
