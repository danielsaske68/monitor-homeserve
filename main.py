import os
import asyncio
from flask import Flask, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")

async def run_bot():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        page = await browser.new_page()

        # Ir al login
        await page.goto(LOGIN_URL)
        await page.wait_for_load_state("networkidle")

        # Rellenar formulario usando NAME
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)

        # Enviar formulario
        await page.click('input[type="submit"], button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Ir a pestaña servicios
        await page.goto(SERVICIOS_URL)
        await page.wait_for_load_state("networkidle")

        # Verificar que cargó algo
        title = await page.title()

        await browser.close()

        return f"Login correcto. Página cargada: {title}"

@app.route("/")
def home():
    return "Bot activo"

@app.route("/run")
def run():
    result = asyncio.run(run_bot())
    return jsonify({"status": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
