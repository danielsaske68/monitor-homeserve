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

        # --- Login ---
        await page.goto(LOGIN_URL)
        await page.fill('input[name="CODIGO"]', USERNAME)
        await page.fill('input[name="PASSW"]', PASSWORD)
        await page.click('input[type="submit"], button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # --- Ir a servicios ---
        await page.goto(SERVICIOS_URL)
        await page.wait_for_load_state("networkidle")

        # --- Extraer servicios desde <td> ---
        tds = await page.query_selector_all("td")
        services_found = []

        for td in tds:
            text = (await td.inner_text()).strip()
            # Solo números de 7 a 9 dígitos
            if re.match(r"^\d{7,9}$", text):
                services_found.append(text)

        services_found = list(set(services_found))  # eliminar duplicados

        # --- Detectar nuevos servicios ---
        old_services = load_old_services()
        new_services = [s for s in services_found if s not in old_services]

        # --- Guardar lista actual ---
        save_services(services_found)

        # Debug en consola
        print("Servicios detectados:", services_found)
        print("Nuevos servicios:", new_services)

        await browser.close()

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
    try:
        result = asyncio.run(run_bot())
        return jsonify(result)
    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
