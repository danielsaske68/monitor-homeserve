import os
import time
import threading
import logging
import requests
import re
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

# ---------------- CONFIG ----------------

load_dotenv()

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS",60))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

TELEGRAM_API=f"https://api.telegram.org/bot{BOT_TOKEN}"

# ---------------- LOG ----------------

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger(__name__)

# ---------------- VARIABLES ----------------

SERVICIOS_ACTUALES={}
SERVICIOS_ANTERIORES={}

ULTIMO=None

# ---------------- TELEGRAM ----------------

class Telegram:

    def enviar(self,texto):

        botones=[
            [
                {"text":"🔐 Login","callback_data":"LOGIN"},
                {"text":"🔄 Actualizar","callback_data":"REFRESH"}
            ],
            [
                {"text":"📋 Ver servicios","callback_data":"SERVICIOS"}
            ],
            [
                {
                 "text":"🌐 Asignación",
                 "url":ASIGNACION_URL
                }
            ]
        ]

        requests.post(
            TELEGRAM_API+"/sendMessage",
            json={
                "chat_id":CHAT_ID,
                "text":texto,
                "parse_mode":"HTML",
                "reply_markup":{
                    "inline_keyboard":botones
                }
            },
            timeout=10
        )

telegram=Telegram()

# ---------------- SCRAPER ----------------

class HomeServe:

    def __init__(self):

        self.session=requests.Session()

    def login(self):

        payload={
            "CODIGO":USUARIO,
            "PASSW":PASSWORD,
            "BTN":"Aceptar"
        }

        self.session.get(LOGIN_URL)

        r=self.session.post(LOGIN_URL,data=payload)

        if "error" in r.text.lower():

            logger.info("Login fallo")
            return False

        logger.info("Login OK")

        return True

    def obtener(self):

        r=self.session.get(ASIGNACION_URL)

        soup=BeautifulSoup(r.text,"html.parser")

        texto=soup.get_text("\n")

        servicios={}

        lineas=texto.split("\n")

        servicio_actual=[]
        id_actual=None

        for linea in lineas:

            linea=linea.strip()

            if not linea:
                continue

            # Detecta ID servicio (ej 15431174)
            m=re.search(r"\b1\d{7}\b",linea)

            if m:

                if id_actual:

                    servicios[id_actual]=" ".join(servicio_actual)

                id_actual=m.group()

                servicio_actual=[linea]

            else:

                if id_actual:

                    servicio_actual.append(linea)

        if id_actual:

            servicios[id_actual]=" ".join(servicio_actual)

        logger.info(f"Servicios detectados: {len(servicios)}")

        return servicios


homeserve=HomeServe()

# ---------------- BOT ----------------

def loop():

    global SERVICIOS_ACTUALES
    global SERVICIOS_ANTERIORES
    global ULTIMO

    homeserve.login()

    while True:

        try:

            SERVICIOS_ACTUALES=homeserve.obtener()

            if not SERVICIOS_ANTERIORES:

                SERVICIOS_ANTERIORES=SERVICIOS_ACTUALES.copy()

                if SERVICIOS_ACTUALES:

                    texto="📋 <b>Servicios actuales</b>\n\n"

                    for s in SERVICIOS_ACTUALES.values():

                        texto+=s+"\n\n"

                    telegram.enviar(texto)

            nuevos=set(SERVICIOS_ACTUALES)-set(SERVICIOS_ANTERIORES)

            if nuevos:

                for id in nuevos:

                    texto="🆕 <b>Nuevo servicio</b>\n\n"

                    texto+=SERVICIOS_ACTUALES[id]

                    telegram.enviar(texto)

                    ULTIMO=SERVICIOS_ACTUALES[id]

            SERVICIOS_ANTERIORES=SERVICIOS_ACTUALES.copy()

            time.sleep(INTERVALO)

        except Exception as e:

            logger.error(e)

            time.sleep(20)


threading.Thread(target=loop,daemon=True).start()

# ---------------- FLASK ----------------

app=Flask(__name__)

HTML="""
<h1>HomeServe BOT</h1>

Servicios detectados: {{n}}

<br><br>

Último servicio:

<br><br>

{{u}}

<br><br>

<form>

<button>Actualizar</button>

</form>
"""

@app.route("/")
def home():

    return render_template_string(
        HTML,
        n=len(SERVICIOS_ACTUALES),
        u=ULTIMO
    )

# ---------------- TELEGRAM CALLBACK ----------------

@app.route("/telegram_webhook",methods=["POST"])
def telegram():

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

                txt="📋 Servicios actuales\n\n"

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

# ---------------- RUN ----------------

if __name__=="__main__":

    port=int(os.getenv("PORT",10000))

    app.run(host="0.0.0.0",port=port)
