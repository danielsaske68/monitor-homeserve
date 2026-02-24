import os
import time
import threading
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

# ---------------- CONFIG ----------------

load_dotenv()

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO_SEGUNDOS = int(os.getenv("INTERVALO_SEGUNDOS",120))
WEB_URL = os.getenv("WEB_URL")  # https://monitor-homeserve.onrender.com

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# ---------------- LOG ----------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# ---------------- VARIABLES ----------------

SERVICIOS_ACTUALES=set()
SERVICIOS_NUEVOS=set()
ULTIMO_SERVICIO=None

# ---------------- TELEGRAM ----------------

class TelegramClient:

    def enviar(self,mensaje,botones=None):

        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        data={
        "chat_id":CHAT_ID,
        "text":mensaje,
        "parse_mode":"HTML"
        }

        if botones:
            data["reply_markup"]={"inline_keyboard":botones}

        requests.post(url,json=data)


# ---------------- SCRAPER ----------------

class HomeServeScraper:

    def __init__(self):
        self.session=requests.Session()

    def login(self):

        payload={
        "CODIGO":USUARIO,
        "PASSW":PASSWORD,
        "BTN":"Aceptar"
        }

        headers={"User-Agent":"Mozilla/5.0"}

        self.session.get(LOGIN_URL,headers=headers)

        r=self.session.post(LOGIN_URL,data=payload,headers=headers)

        if "error" in r.text.lower():
            logger.error("Login fallido")
            return False

        logger.info("Login correcto")
        return True


    def obtener(self):

        r=self.session.get(ASIGNACION_URL)

        soup=BeautifulSoup(r.text,"html.parser")

        servicios=set()

        for fila in soup.find_all("tr"):

            texto=fila.get_text(" ",strip=True)

            if len(texto)>25:
                servicios.add(texto)

        logger.info(f"Servicios detectados {len(servicios)}")

        return servicios


# ---------------- BOT ----------------

class Bot:

    def __init__(self):

        self.scraper=HomeServeScraper()
        self.tg=TelegramClient()

        self.previos=None


    def botones(self):

        return [

        [
        {"text":"🔑 Login","url":LOGIN_URL},
        {"text":"📋 Asignación","url":ASIGNACION_URL}
        ],

        [
        {"text":"🆕 Ver nuevos","callback_data":"NEW"},
        {"text":"📊 Ver actuales","callback_data":"ALL"}
        ],

        [
        {"text":"🌐 Abrir web","url":WEB_URL}
        ]

        ]


    def iniciar(self):

        global SERVICIOS_ACTUALES
        global SERVICIOS_NUEVOS
        global ULTIMO_SERVICIO

        self.scraper.login()

        while True:

            actuales=self.scraper.obtener()

            if self.previos is None:

                self.previos=actuales

                SERVICIOS_ACTUALES=actuales

                self.tg.enviar(

                f"✅ Bot iniciado\nServicios actuales: {len(actuales)}",

                self.botones()

                )


            nuevos=actuales-self.previos

            if nuevos:

                SERVICIOS_NUEVOS=nuevos

                for s in nuevos:

                    self.tg.enviar(

                    f"🆕 NUEVO SERVICIO\n\n{s}"

                    )

                    ULTIMO_SERVICIO=s


            SERVICIOS_ACTUALES=actuales

            self.previos=actuales

            time.sleep(INTERVALO_SEGUNDOS)


bot=Bot()

threading.Thread(target=bot.iniciar,daemon=True).start()

# ---------------- WEB ----------------

app=Flask(__name__)

HTML="""

<h1>Monitor HomeServe</h1>

<h2>Servicios actuales: {{cantidad}}</h2>

<h3>Último:</h3>

{{ultimo}}

<hr>

<h3>Lista:</h3>

{% for s in servicios %}

<p>{{s}}</p>

{% endfor %}

"""


@app.route("/")

def home():

    return render_template_string(

    HTML,

    cantidad=len(SERVICIOS_ACTUALES),

    ultimo=ULTIMO_SERVICIO,

    servicios=SERVICIOS_ACTUALES

    )


# ---------------- TELEGRAM BOTONES ----------------

@app.route("/telegram_webhook",methods=["POST"])

def telegram():

    global SERVICIOS_ACTUALES
    global SERVICIOS_NUEVOS

    data=request.json

    if "callback_query" in data:

        chat=data["callback_query"]["message"]["chat"]["id"]

        accion=data["callback_query"]["data"]

        if accion=="ALL":

            texto="\n\n".join(SERVICIOS_ACTUALES)

            requests.post(

            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",

            json={

            "chat_id":chat,
            "text":f"📊 SERVICIOS ACTUALES\n\n{texto}",
            "parse_mode":"HTML"

            })

        if accion=="NEW":

            if SERVICIOS_NUEVOS:

                texto="\n\n".join(SERVICIOS_NUEVOS)

            else:

                texto="No hay servicios nuevos"

            requests.post(

            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",

            json={

            "chat_id":chat,
            "text":f"🆕 SERVICIOS NUEVOS\n\n{texto}",
            "parse_mode":"HTML"

            })


    return jsonify(ok=True)


# ---------------- START ----------------

if __name__=="__main__":

    port=int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0",port=port)
