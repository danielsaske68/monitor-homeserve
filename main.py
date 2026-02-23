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
detected_services = set()

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICES_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

async def get_services():
    global detected_services
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(LOGIN_URL)
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        await page.goto(SERVICES_URL)
        rows = await page.query_selector_all("td")  # cada servicio está en un <td>
        current_services = set()
        for td in rows:
            text = (await td.inner_text()).strip()
            if text.isdigit():
                current_services.add(text)
        # detectar nuevos servicios
        new_services = current_services - detected_services
        for s in new_services:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Nuevo servicio detectado: {s}")
        detected_services = current_services
        await browser.close()
        return {"nuevos_servicios": list(new_services), "servicios_actuales": list(current_services), "total_detectados": len(current_services)}

@app.route("/run")
def run():
    result = asyncio.run(get_services())
    return jsonify(result)

@app.route("/")
def home():
    return "Bot Homeserve corriendo ✅"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
