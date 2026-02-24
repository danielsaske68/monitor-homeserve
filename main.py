import os
import time
import threading
import logging
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask,request,jsonify
from dotenv import load_dotenv

load_dotenv()

USUARIO=os.getenv("USUARIO")
PASSWORD=os.getenv("PASSWORD")
BOT_TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
INTERVALO=int(os.getenv("INTERVALO_SEGUNDOS",60))

LOGIN_URL="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

TELEGRAM_API=f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("main")

SERVICIOS_ACTUALES={}
SERVICIOS_ANTERIORES={}

##########################################################
# TELEGRAM
##########################################################

class Telegram:

    def enviar(self,texto):

        botones={
            "inline_keyboard":[

                [
                    {"text":"🔐 Login",
                     "callback_data":"LOGIN"},

                    {"text":"🔄 Actualizar",
                     "callback_data":"REFRESH"}
                ],

                [
                    {"text":"📋 Ver servicios",
                     "callback_data":"SERVICIOS"}
                ],

                [
                    {"text":"🌐 Ir a asignación",
                     "url":ASIGNACION_URL}
                ]

            ]
        }

        requests.post(
            TELEGRAM_API+"/sendMessage",
            json={
                "chat_id":CHAT_ID,
                "text":texto,
                "parse_mode":"HTML",
                "reply_markup":botones
            }
        )

        logger.info("Mensaje Telegram enviado")


telegram=Telegram()

##########################################################
# HOMESERVE
##########################################################

class HomeServe:

    def __init__(self):

        self.session=requests.Session()

    def login(self):

        try:

            payload={
                "CODIGO":USUARIO,
                "PASSW":PASSWORD,
                "BTN":"Aceptar"
            }

            self.session.get(LOGIN_URL)

            r=self.session.post(
                LOGIN_URL,
                data=payload,
                timeout=15
            )

            if "error" in r.text.lower():

                logger.error("Login fallo")
                return False

            logger.info("Login OK")

            return True

        except Exception as e:

            logger.error(e)
            return False


    ##########################################################
    # DETECTOR REAL POR ID
    ##########################################################

    def obtener(self):

        try:

            r=self.session.get(ASIGNACION_URL,timeout=15)

            soup=BeautifulSoup(r.text,"html.parser")

            texto=soup.get_text(" ",strip=True)

            ids=re.findall(r"\b\d{6,9}\b",texto)

            servicios={}

            for idserv in ids:

                if idserv not in servicios:

                    pos=texto.find(idserv)

                    bloque=texto[pos:pos+400]

                    servicios[idserv]=bloque


            logger.info(f"Servicios detectados: {len(servicios)}")

            return servicios

        except Exception as e:

            logger.error(e)

            return {}


homeserve=HomeServe()

##########################################################
# BOT LOOP
##########################################################

def bot_loop():

    global SERVICIOS_ACTUALES
    global SERVICIOS_ANTERIORES

    homeserve.login()

    while True:

        try:

            nuevos={}

            actuales=homeserve.obtener()

            for k,v in actuales.items():

                if k not in SERVICIOS_ACTUALES:

                    nuevos[k]=v


            if nuevos:

                for s in nuevos.values():

                    telegram.enviar(
                        "🆕 <b>Nuevo servicio detectado</b>\n\n"+s
                    )


            SERVICIOS_ANTERIORES=SERVICIOS_ACTUALES.copy()

            SERVICIOS_ACTUALES=actuales


            time.sleep(INTERVALO)

        except Exception as e:

            logger.error(e)

            time.sleep(30)


##########################################################
# FLASK
##########################################################

app=Flask(__name__)

@app.route("/")
def home():

    return f"""
HomeServe Monitor OK

Servicios actuales: {len(SERVICIOS_ACTUALES)}
"""

##########################################################
# TELEGRAM BUTTONS
##########################################################

@app.route("/telegram_webhook",methods=["POST"])
def telegram_webhook():

    data=request.json

    if "callback_query" in data:

        accion=data["callback_query"]["data"]

        chat=data["callback_query"]["message"]["chat"]["id"]

        if accion=="LOGIN":

            ok=homeserve.login()

            txt="✅ Login correcto" if ok else "❌ Login fallo"


        elif accion=="REFRESH":

            SERVICIOS_ACTUALES.update(homeserve.obtener())

            txt="🔄 Actualizado"


        elif accion=="SERVICIOS":

            if SERVICIOS_ACTUALES:

                txt="📋 <b>Servicios actuales</b>\n\n"

                for s in SERVICIOS_ACTUALES.values():

                    txt+=s+"\n\n"

            else:

                txt="No hay servicios"


        requests.post(
            TELEGRAM_API+"/sendMessage",
            json={
                "chat_id":chat,
                "text":txt,
                "parse_mode":"HTML"
            }
        )

    return jsonify(ok=True)

##########################################################
# START THREAD
##########################################################

threading.Thread(
    target=bot_loop,
    daemon=True
).start()

##########################################################
# RUN
##########################################################

if __name__=="__main__":

    port=int(os.environ.get("PORT",10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
