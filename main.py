import os
import time
import requests
from bs4 import BeautifulSoup
import logging


# ---------- CONFIG ----------

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 60))


LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"

ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"


# ---------- LOGGING ----------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

logger = logging.getLogger()


# ---------- TELEGRAM ----------

def enviar_telegram(mensaje):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": mensaje
    }

    try:

        requests.post(url, data=data, timeout=10)

        logger.info("Mensaje enviado a Telegram")

    except Exception as e:

        logger.error("Error Telegram: " + str(e))


# ---------- LOGIN ----------

def login(session):

    payload = {
        "CODIGO": USUARIO,
        "PASSW": PASSWORD
    }

    try:

        session.get(LOGIN_URL)

        r = session.post(LOGIN_URL, data=payload, timeout=15)

        if r.status_code == 200:

            logger.info("Login correcto")

            return True

    except Exception as e:

        logger.error("Error login " + str(e))

    return False


# ---------- SCRAPER ----------

def obtener_servicios(session):

    servicios = set()

    try:

        r = session.get(ASIGNACION_URL, timeout=15)

        soup = BeautifulSoup(r.text, "lxml")

        filas = soup.find_all("tr")

        for fila in filas:

            texto = fila.get_text(" ", strip=True)

            if len(texto) > 40:

                servicios.add(texto)

        logger.info(f"Servicios encontrados: {len(servicios)}")

    except Exception as e:

        logger.error("Error scraping " + str(e))

    return servicios


# ---------- BOT ----------

def iniciar_bot():

    session = requests.Session()

    if not login(session):

        logger.error("No se pudo loguear")

        return


    servicios_previos = obtener_servicios(session)

    logger.info("Estado inicial guardado")


    while True:

        try:

            servicios_actuales = obtener_servicios(session)

            nuevos = servicios_actuales - servicios_previos

            if nuevos:

                for servicio in nuevos:

                    mensaje = "🚨 NUEVO SERVICIO 🚨\n\n" + servicio

                    enviar_telegram(mensaje)

                    logger.info("Nuevo servicio detectado")


                servicios_previos = servicios_actuales


            time.sleep(INTERVALO)


        except Exception as e:

            logger.error("Error loop " + str(e))

            time.sleep(30)


# ---------- START ----------

if __name__ == "__main__":

    logger.info("Bot HomeServe iniciado")

    iniciar_bot()
