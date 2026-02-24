import requests
from bs4 import BeautifulSoup
import time

# -----------------------------
# CONFIGURACIÓN
# -----------------------------
TELEGRAM_TOKEN = "TU_BOT_TOKEN"
CHAT_ID = "TU_CHAT_ID"
URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
USERNAME = "TU_USUARIO"
PASSWORD = "TU_PASSWORD"
CHECK_INTERVAL = 30  # segundos
# -----------------------------

session = requests.Session()

def login():
    """
    Realiza login en la web y mantiene la sesión.
    """
    try:
        # Obtenemos la página de login para cookies hidden si las hay
        r = session.get(URL_LOGIN)
        r.raise_for_status()
        
        # Parseamos campos ocultos (csrf, token, etc.) si aplica
        soup = BeautifulSoup(r.text, "html.parser")
        data = {
            "username": USERNAME,
            "password": PASSWORD
        }
        # Si hay token hidden, agregarlo:
        token = soup.find("input", {"name": "csrf_token"})
        if token:
            data["csrf_token"] = token["value"]

        r2 = session.post(URL_LOGIN, data=data)
        r2.raise_for_status()
        if "logout" in r2.text.lower():
            print("Login OK")
            return True
        else:
            print("Login fallido")
            return False
    except Exception as e:
        print(f"Error en login: {e}")
        return False

def obtener_servicios_actuales():
    """
    Obtiene servicios desde la página de asignación después de login.
    Devuelve lista de nombres o IDs.
    """
    try:
        r = session.get(URL_SERVICIOS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Dependiendo de cómo esté la página, por ejemplo lista en <li class="servicio">
        servicios = [li.text.strip() for li in soup.find_all("li", class_="servicio")]
        return servicios
    except Exception as e:
        print(f"Error al obtener servicios: {e}")
        return []

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload)
        r.raise_for_status()
        print("Mensaje telegram enviado")
    except Exception as e:
        print(f"Error al enviar Telegram: {e}")

def formatear_mensaje(servicios):
    if not servicios:
        return "*No hay servicios activos*"
    mensaje = f"*Servicios detectados:* {len(servicios)}\n\n"
    for i, s in enumerate(servicios, 1):
        mensaje += f"{i}. {s}\n"
    return mensaje

def main():
    if not login():
        return

    servicios_previos = []

    while True:
        servicios_actuales = obtener_servicios_actuales()
        if servicios_actuales != servicios_previos:
            mensaje = formatear_mensaje(servicios_actuales)
            enviar_telegram(mensaje)
            servicios_previos = servicios_actuales
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
