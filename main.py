import os
import time
import threading
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# VARIABLES RENDER
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

# ----------------
# TELEGRAM
# ----------------

def enviar_telegram(texto, botones=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "HTML"
    }

    if botones:
        payload["reply_markup"] = {"inline_keyboard": botones}

    try:
        requests.post(url, json=payload, timeout=10)
        print("Mensaje telegram enviado")
    except Exception as e:
        print("Error telegram:", e)

# ----------------
# LOGIN
# ----------------

def login(session):
    payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
    session.get(LOGIN_URL)
    r = session.post(LOGIN_URL, data=payload)
    if "error" in r.text.lower():
        print("Login fallo")
        return False
    print("Login OK")
    return True

# ----------------
# SERVICIOS
# ----------------

def obtener_servicios(session):
    r = session.get(SERVICIOS_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    texto = soup.get_text().lower()
    if "no hay servicios" in texto:
        return []
    lista = []
    for tr in soup.find_all("tr"):
        fila = tr.get_text(strip=True)
        if len(fila) > 40 and "servicios para ud" not in fila.lower():
            lista.append(fila)
    return lista

# ----------------
# BOT LOOP
# ----------------

def bot():
    global SERVICIOS, ULTIMO
    session = requests.Session()
    if not login(session):
        return
    enviar_telegram("BOT HOMESERVE INICIADO ✅", botones=[[{"text":"Ver Servicios","callback_data":"ver_servicios"}]])
    while True:
        try:
            nuevos = obtener_servicios(session)
            print("Servicios detectados:", len(nuevos))
            if SERVICIOS == []:
                SERVICIOS = nuevos
                if nuevos:
                    ULTIMO = nuevos[0]
                enviar_telegram(f"Servicios actuales: {len(nuevos)}", botones=[[{"text":"Ver Servicios","callback_data":"ver_servicios"}]])
            else:
                for s in nuevos:
                    if s not in SERVICIOS:
                        enviar_telegram("Nuevo servicio:\n\n" + s, botones=[[{"text":"Ver Servicios","callback_data":"ver_servicios"}]])
                        ULTIMO = s
                SERVICIOS = nuevos
        except Exception as e:
            print("Error:", e)
        time.sleep(INTERVALO)

# ----------------
# WEB
# ----------------

@app.route("/")
def home():
    return f"""
    <h1>BOT HOMESERVE</h1>
    Servicios actuales: {len(SERVICIOS)}<br><br>
    Ultimo servicio:<br><br>{ULTIMO}
    """

# ----------------
# TELEGRAM WEBHOOK
# ----------------

@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    global SERVICIOS
    data = request.get_json()
    if "callback_query" in data:
        callback = data["callback_query"]
        if callback["data"] == "ver_servicios":
            chat_id = callback["message"]["chat"]["id"]
            if SERVICIOS:
                texto = "\n\n".join(SERVICIOS)
            else:
                texto = "No hay servicios activos"
            enviar_telegram(texto)
    return jsonify({"ok": True})

# ----------------
# START BOT
# ----------------

threading.Thread(target=bot, daemon=True).start()
