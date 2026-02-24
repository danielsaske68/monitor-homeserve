import os
import time
import requests
import threading
import logging
import re

from flask import Flask
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from bs4 import BeautifulSoup

# CONFIG

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

USUARIO=os.getenv("USUARIO")
PASSWORD=os.getenv("PASSWORD")

INTERVALO=int(os.getenv("INTERVALO_SEGUNDOS",30))

LOGIN_URL="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"


# LOGS

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger()


# TELEGRAM

bot=Bot(token=TELEGRAM_TOKEN)


# FLASK (para Render)

app=Flask(__name__)

@app.route("/")
def home():
    return "Bot funcionando"


# BOT SCRAPER

class BotServicios:

    def __init__(self):

        self.session=requests.Session()

        self.servicios=set()

        self.logueado=False


    def login(self):

        try:

            data={
                "usuario":USUARIO,
                "password":PASSWORD
            }

            r=self.session.post(LOGIN_URL,data=data,timeout=20)

            if r.status_code==200:

                self.logueado=True

                logger.info("Login correcto")

                return True

            else:

                logger.error("Login fallo")

                return False

        except Exception as e:

            logger.error(e)

            return False


    def obtener_servicios(self):

        try:

            r=self.session.get(ASIGNACION_URL,timeout=20)

            soup=BeautifulSoup(r.text,"html.parser")

            texto=soup.get_text("\n")

            bloques=re.split(r"\n(?=\d{7,8}\s)",texto)

            servicios={}

            for b in bloques:

                idmatch=re.search(r"\b\d{7,8}\b",b)

                if not idmatch:
                    continue

                idserv=idmatch.group(0)

                limpio=b.strip()

                servicios[idserv]=limpio


            logger.info(f"Servicios detectados {len(servicios)}")

            return servicios

        except Exception as e:

            logger.error(e)

            return {}


botserv=BotServicios()


# MENÚ TELEGRAM

def menu():

    botones=[

        [InlineKeyboardButton("🔑 Login",callback_data="login")],

        [InlineKeyboardButton("📋 Ver servicios actuales",callback_data="ver")],

        [InlineKeyboardButton("🔄 Actualizar",callback_data="update")],

        [InlineKeyboardButton("🌐 Ir a asignación",url=ASIGNACION_URL)]

    ]

    return InlineKeyboardMarkup(botones)



# MENSAJES

def enviar_menu():

    bot.send_message(

        CHAT_ID,

        "🤖 Bot de servicios activo",

        reply_markup=menu()

    )



def enviar_servicios(servicios):

    if not servicios:

        bot.send_message(CHAT_ID,"No hay servicios disponibles")
        return

    texto="📋 Servicios actuales:\n\n"

    for s in servicios.values():

        texto+=f"{s}\n\n"

    bot.send_message(CHAT_ID,texto)



def enviar_nuevo(servicio):

    bot.send_message(

        CHAT_ID,

        f"🆕 Nuevo servicio\n\n{servicio}"

    )



# DETECTOR AUTOMATICO

def detector():

    while True:

        try:

            if not botserv.logueado:
                botserv.login()

            servicios=botserv.obtener_servicios()

            actuales=set(servicios.keys())

            nuevos=actuales-botserv.servicios

            for n in nuevos:

                enviar_nuevo(servicios[n])

            botserv.servicios=actuales

        except Exception as e:

            logger.error(e)

        time.sleep(INTERVALO)



# TELEGRAM BOTONES

def telegram_loop():

    offset=None

    while True:

        updates=bot.get_updates(offset=offset,timeout=20)

        for u in updates:

            offset=u.update_id+1

            if not u.callback_query:
                continue

            data=u.callback_query.data

            bot.answer_callback_query(u.callback_query.id)

            if data=="login":

                ok=botserv.login()

                if ok:
                    bot.send_message(CHAT_ID,"Login correcto")
                else:
                    bot.send_message(CHAT_ID,"Login fallo")


            elif data=="ver":

                servicios=botserv.obtener_servicios()

                enviar_servicios(servicios)


            elif data=="update":

                botserv.login()

                servicios=botserv.obtener_servicios()

                enviar_servicios(servicios)



        time.sleep(2)



# START

if __name__=="__main__":

    enviar_menu()

    threading.Thread(target=detector).start()

    threading.Thread(target=telegram_loop).start()

    app.run(host="0.0.0.0",port=10000)
