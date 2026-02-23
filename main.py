import os
import json
import re
import asyncio
from flask import Flask, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")

DATA_FILE = "services.json"


def load_old_services():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_services(services):
    with open(DATA_FILE, "w") as f:
        json.dump(services, f)


async def run_bot():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

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

        content = await page.content()

        await browser.close()

        # Buscar números de 7-9 dígitos (IDs de servicio)
        services_found = list(set(re.findall(r"\b\d{7,9}\b", content)))

        old_services = load_old_services()

        new_services = [s for s in services_found if s not in old_services]

        # Guardar lista actual
        save_services(services_found)

        return {
            "total_detectados": len(services_found),
            "servicios_actuales": services_found,
            "nuevos_servicios": new_services
        }


@app.route("/")
def home():
    return "Bot activo"

@app.route("/run")
def run():
    result = asyncio.run(run_bot())
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
