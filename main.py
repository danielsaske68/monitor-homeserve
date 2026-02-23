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

        # Ir a login
        await page.goto(LOGIN_URL)

        # ⚠️ CAMBIAR SELECTORES SEGÚN HTML REAL
        await page.fill('#usuario', USERNAME)
        await page.fill('#password', PASSWORD)

        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Ir a servicios
        await page.goto(SERVICIOS_URL)
        await page.wait_for_load_state("networkidle")

        content = await page.content()

        await browser.close()
        return "Login y acceso correcto"

@app.route("/")
def home():
    return "Bot activo"

@app.route("/run")
def run():
    result = asyncio.run(run_bot())
    return jsonify({"status": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
