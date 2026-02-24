import os
import time
import threading
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO = 120

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

SERVICIOS = []
ULTIMO = "Ninguno"

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


# -------------------
# TELEGRAM
# -------------------

def enviar_telegram(texto):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": texto
    }

    try:
        requests.post(url, data=data, timeout=10)
        print("Mensaje telegram enviado")
    except Exception as e:
        print("Error telegram:", e)


# -------------------
# SCRAPER
# -------------------

def login(session):

    payload = {
        "CODIGO": USUARIO,
        "PASSW": PASSWORD,
        "BTN": "Aceptar"
    }

    session.get(LOGIN_URL)

    r = session.post(LOGIN_URL, data=payload)

    if "error" in r.text.lower():
        print("Login fallo")
        return False

    print("Login OK")

    return True


def obtener_servicios(session):

    r = session.get(SERVICIOS_URL)

    soup = BeautifulSoup(r.text, "html.parser")

    lista = []

    for tr in soup.find_all("tr"):

        texto = tr.get_text(strip=True)

        if len(texto) > 40:
            lista.append(texto)

    return lista


# -------------------
# BOT LOOP
# -------------------

def bot():

    global SERVICIOS
    global ULTIMO

    session = requests.Session()

    if not login(session):
        return

    enviar_telegram("BOT HOMESERVE INICIADO")

    while True:

        try:

            nuevos = obtener_servicios(session)

            print("Servicios detectados:", len(nuevos))

            if SERVICIOS == []:

                SERVICIOS = nuevos

                if nuevos:
                    ULTIMO = nuevos[0]

                enviar_telegram(f"Servicios actuales: {len(nuevos)}")

            else:

                for s in nuevos:

                    if s not in SERVICIOS:

                        enviar_telegram("Nuevo servicio:\n\n" + s)

                        ULTIMO = s

                SERVICIOS = nuevos

        except Exception as e:

            print("Error loop:", e)

        time.sleep(INTERVALO)


# -------------------
# WEB
# -------------------

@app.route("/")
def home():

    return f"""
    <h1>BOT HOMESERVE</h1>

    Servicios actuales: {len(SERVICIOS)}

    <br><br>

    Ultimo servicio:

    <br><br>

    {ULTIMO}
    """


# -------------------
# START THREAD
# -------------------

threading.Thread(target=bot, daemon=True).start()
