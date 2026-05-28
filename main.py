import os
import time
import threading
import logging
import re
import requests
import sqlite3
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

app = Flask(__name__)

# ---------------- STATE ----------------
SERVICIOS_ACTUALES = {}
WEB_CACHE = {}
WEB_INDEX = {}
USER_STATE = {}
SERV_STATE = {}

# ---------------- DB ----------------
DB_PATH = "/data/usuarios.db"
os.makedirs("/data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS usuarios (chat_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    usuarios = [r[0] for r in c.fetchall()]
    conn.close()
    return usuarios

def eliminar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))
    conn.commit()
    conn.close()

init_db()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

def tg_edit(chat, msg_id, text, markup=None):
    payload = {"chat_id": chat, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(callback_id):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                  json={"callback_query_id": callback_id},
                  timeout=10)

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"},
             {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}],
            [{"text": "📦 Numero de servicios", "callback_data": "NUM_SERV"}],
            [{"text": "📋 Servicios en curso", "callback_data": "CURSO"}]
        ]
    }

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data={
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            }, timeout=10)
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", text)

            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())
            return servicios
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)

            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            fecha_str = fecha.strftime("%d/%m/%Y")

            obs = ("Pendiente de localizar a asegurado"
                   if estado == "348"
                   else "En espera de Profesional por confirmación del Siniestro")

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "Pag": "1",
                "ESTADO": estado,
                "FECSIG": fecha_str,
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            self.session.post(BASE_URL, data=payload, timeout=10)
            return True, f"✅ Estado {estado} aplicado ({fecha_str})"
        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones())

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(e)
            homeserve.login()
            time.sleep(10)

threading.Thread(target=loop, daemon=True).start()

# ---------------- WEBHOOK (ARREGLADO BIEN) ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():

    try:
        data = request.json

        if "message" in data:
            chat = data["message"]["chat"]["id"]
            guardar_usuario(chat)

        if "callback_query" in data:

            cq = data["callback_query"]
            chat = cq["message"]["chat"]["id"]
            msg_id = cq["message"]["message_id"]
            action = cq["data"]

            tg_answer(cq["id"])
            guardar_usuario(chat)

            # ---------------- ACEPTAR ----------------
            if action.startswith("ACEPTAR_"):

                sid = action.split("_")[1]

                try:
                    url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
                    r = homeserve.session.get(url, timeout=15)
                    html = r.text.lower()

                    errores = [
                        "error", "illegal", "denegado",
                        "caducada", "no autorizado",
                        "acceso inválido"
                    ]

                    fallo = any(e in html for e in errores)

                    ok_visual = ("<table" in html or "<form" in html or "servicio" in html)

                    if fallo:
                        tg_edit(chat, msg_id, f"❌ Error al aceptar servicio {sid}", botones())
                    elif ok_visual:
                        tg_edit(chat, msg_id, f"✅ Servicio {sid} aceptado correctamente", botones())
                    else:
                        tg_edit(chat, msg_id, f"⚠️ No se pudo confirmar aceptación de {sid}", botones())

                except Exception as e:
                    tg_edit(chat, msg_id, f"❌ {e}", botones())

            # ---------------- RECHAZAR ----------------
            elif action.startswith("RECHAZAR_"):

                sid = action.split("_")[1]
                homeserve.cambiar_estado(sid, "348")
                tg_edit(chat, msg_id, "❌ Rechazado", botones())

        # 🔥 ESTE ES EL FIX CRÍTICO
        return jsonify(ok=True)

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {e}")
        return jsonify(ok=False)
