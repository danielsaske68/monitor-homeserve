import requests
from bs4 import BeautifulSoup
import re
import logging

# -----------------------------
# Tus credenciales (asegúrate de definirlas en variables de entorno)
# -----------------------------
HS_USER = "TU_CODIGO"     
HS_PASS = "TU_PASSW"    

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

def obtener_servicios():
    try:
        session = requests.Session()

        # Headers tipo navegador real
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": LOGIN_URL,
        }

        # -----------------------------
        # 1️⃣ LOGIN
        # -----------------------------
        login_payload = {
            "usuario": HS_USER,
            "contraseña": HS_PASS
        }

        login_response = session.post(LOGIN_URL, data=login_payload, headers=headers)

        if login_response.status_code != 200:
            logging.error("Error en login HomeServe")
            return []

        # -----------------------------
        # 2️⃣ IR A ASIGNACIÓN
        # -----------------------------
        response = session.get(ASIGNACION_URL, headers=headers)

        if response.status_code != 200:
            logging.error("Error entrando a asignación")
            return []

        html = response.text
        logging.info("Página de asignación cargada correctamente")

        # -----------------------------
        # 3️⃣ EXTRAER TODOS LOS SERVICIOS (8 dígitos)
        # -----------------------------
        servicios = list(set(re.findall(r"\b\d{8}\b", html)))
        servicios.sort()

        logging.info(f"Servicios encontrados: {servicios}")
        return servicios

    except Exception as e:
        logging.error(f"Error obteniendo servicios: {e}")
        return []
