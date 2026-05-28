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

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

app = Flask(__name__)

# ---------------- STATE ----------------
SERVICIOS_ACTUALES = {}
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
    c.execute("INSERT OR IGNORE INTO usuarios VALUES (?)", (str(chat_id),))
    conn.commit()
    conn.close()

def obtener_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM usuarios")
    return [r[0] for r in c.fetchall()]

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
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)

def tg_edit(chat, msg_id, text, markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload)

def tg_answer(cid):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                  json={"callback_query_id": cid})

# ---------------- BOTONES ----------------
def botones():
    return {"inline_keyboard": [
        [{"text": "🔐 Login", "callback_data": "LOGIN"},
         {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
        [{"text": "🌐 Web", "callback_data": "WEB"},
         {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
        [{"text": "📋 Curso", "callback_data": "CURSO"}]
    ]}

def botones_servicio(sid):
    return {"inline_keyboard": [
        [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
         {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}],
        [{"text": "⬅️ Volver", "callback_data": "WEB"}]
    ]}

def lista_servicios(servicios):
    teclado = []
    for s in servicios:
        teclado.append([{"text": s, "callback_data": f"SEL_{s}"}])
    return {"inline_keyboard": teclado}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            self.session.get(LOGIN_URL)
            r = self.session.post(LOGIN_URL, data={
                "CODIGO": USUARIO,
                "PASSW": PASSWORD,
                "BTN": "Aceptar"
            })
            return "error" not in r.text.lower()
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            return {"demo": text[:200]}
        except:
            return {}

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL)
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            return [text[:100]]
        except:
            return []

    def detalle_servicio(self, sid):
        try:
            url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}"
            r = self.session.get(url)
            soup = BeautifulSoup(r.text, "html.parser")

            return {
                "servicio": sid,
                "direccion": soup.get_text()[:50],
                "poblacion": "",
                "comentarios": ""
            }
        except:
            return None

    def cambiar_estado(self, sid, estado):
        try:
            self.session.post(BASE_URL, data={
                "Servicio": sid,
                "ESTADO": estado
            })
            return True, "OK"
        except Exception as e:
            return False, str(e)

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    homeserve.login()
    global SERVICIOS_ACTUALES

    while True:
        try:
            actuales = homeserve.obtener()

            for k in actuales:
                if k not in SERVICIOS_ACTUALES:
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 {k}", botones_servicio(k))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(e)

threading.Thread(target=loop, daemon=True).start()

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        guardar_usuario(chat)

        if text == "/start":
            tg_send(chat, "🤖 OK", botones())

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])

        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, str(ok), botones())

        elif action == "CURSO":
            datos = homeserve.obtener_curso()
            tg_edit(chat, msg_id, "\n".join(datos) or "Vacío", botones())

        elif action == "WEB":
            servicios = homeserve.obtener()
            keys = list(servicios.keys())
            tg_edit(chat, msg_id, str(keys), botones())

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            try:
                url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
                r = homeserve.session.get(url, timeout=15)
                html = r.text.lower()

                errores = ["error","illegal","denegado","caducada","no autorizado","acceso inválido"]
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


        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            ok, msg = homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, msg, botones())

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            data = homeserve.detalle_servicio(sid)
            tg_edit(chat, msg_id, str(data), botones())

    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
