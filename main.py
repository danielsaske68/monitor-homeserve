import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask
import logging


# ---------- CONFIG ----------

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 60))


LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"

ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"


# ---------- LOGS ----------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

logger = logging.getLogger()


# ---------- TELEGRAM ----------

def enviar_telegram(texto):

    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data={
        "chat_id":CHAT_ID,
        "text":texto
    }

    try:

        requests.post(url,data=data,timeout=10)

        logger.info("Telegram enviado")

    except Exception as e:

        logger.error("Telegram error "+str(e))


# ---------- LOGIN ----------

def login(session):

    payload={
        "CODIGO":USUARIO,
        "PASSW":PASSWORD
    }

    try:

        session.get(LOGIN_URL)

        r=session.post(LOGIN_URL,data=payload,timeout=15)

        if r.status_code==200:

            logger.info("Login correcto")

            return True

    except Exception as e:

        logger.error("Error login "+str(e))

    return False


# ---------- SCRAPER ----------

def obtener_servicios(session):

    servicios=set()

    try:

        r=session.get(ASIGNACION_URL,timeout=15)

        soup=BeautifulSoup(r.text,"lxml")

        filas=soup.find_all("tr")

        for fila in filas:

            texto=fila.get_text(" ",strip=True)

            if len(texto)>40:

                servicios.add(texto)

        logger.info("Servicios encontrados "+str(len(servicios)))

    except Exception as e:

        logger.error("Error scraping "+str(e))

    return servicios


# ---------- BOT ----------

def bot_loop():

    session=requests.Session()

    if not login(session):

        logger.error("No login")

        return


    servicios_previos=obtener_servicios(session)

    logger.info("Estado inicial guardado")


    while True:

        try:

            actuales=obtener_servicios(session)

            nuevos=actuales-servicios_previos


            if nuevos:

                for s in nuevos:

                    enviar_telegram("🚨 NUEVO SERVICIO 🚨\n\n"+s)

                    logger.info("Nuevo servicio")


                servicios_previos=actuales


            time.sleep(INTERVALO)


        except Exception as e:

            logger.error("Loop error "+str(e))

            time.sleep(30)


# ---------- WEB SERVER ----------

app=Flask(__name__)


@app.route("/")
def home():

    return "HomeServe Bot activo"


# ---------- START ----------

if __name__=="__main__":

    logger.info("Iniciando bot HomeServe")


    hilo=threading.Thread(target=bot_loop)

    hilo.daemon=True

    hilo.start()


    port=int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0",port=port)
