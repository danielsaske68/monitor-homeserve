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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bot")

# ---------------- APP ----------------
app = Flask(__name__)

SERVICIOS_ACTUALES = {}
PANEL = {}

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
    data = [r[0] for r in c.fetchall()]
    conn.close()
    return data

def contar_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM usuarios")
    return c.fetchone()[0]

init_db()

# ---------------- TELEGRAM ----------------
def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup

    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)

    if r.ok:
        PANEL[chat] = r.json()["result"]["message_id"]

def tg_edit(chat, msg_id, text, markup=None):
    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup

    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)

def tg_answer(cid):
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": cid},
        timeout=10
    )

# ---------------- BOTONES ----------------
def menu_principal():
    return {
        "inline_keyboard": [
            [
                {"text": "🔐 Login", "callback_data": "LOGIN"},
                {"text": "🔄 Refresh", "callback_data": "REFRESH"}
            ],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR"}],
            [{"text": "👤 Usuarios", "callback_data": "USUARIOS"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
            ],
            [
                {"text": "🔴 Estado", "callback_data": f"ESTADOS_{sid}"},
                {"text": "⬅️ Volver", "callback_data": "BACK_MENU"}
            ]
        ]
    }

def botones_estados(sid):
    return {
        "inline_keyboard": [
            [{"text": "🔴 Pendiente cliente", "callback_data": f"SET_{sid}_348"}],
            [{"text": "🟢 En espera", "callback_data": f"SET_{sid}_318"}],
            [{"text": "⬅️ Volver", "callback_data": f"BACK_SERV_{sid}"}]
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

            obs = "Pendiente cliente" if estado == "348" else "En espera profesional"

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado,
                "FECSIG": fecha.strftime("%d/%m/%Y"),
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            self.session.post(BASE_URL, data=payload, timeout=10)
            return True, "Estado actualizado"
        except Exception as e:
            return False, str(e)

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES

    logger.info("🔥 Monitor iniciado")
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones_servicio(sid))

            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)

        except Exception as e:
            logger.error(e)
            homeserve.login()
            time.sleep(10)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    # ---------------- MESSAGE ----------------
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        guardar_usuario(chat)

        if text == "/start":
            tg_send(chat, f"🤖 Bot activo\n👤 Usuarios: {contar_usuarios()}", menu_principal())

        elif text == "/users":
            users = obtener_usuarios()
            tg_send(chat, "👤 Usuarios:\n" + "\n".join(users), menu_principal())

    # ---------------- CALLBACKS ----------------
    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]
        cid = cq["id"]

        tg_answer(cid)
        guardar_usuario(chat)

        # ---------- MENU ----------
        if action == "BACK_MENU":
            tg_edit(chat, msg_id, "🏠 Menú principal", menu_principal())

        elif action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "✅ Login OK" if ok else "❌ Error", menu_principal())

        elif action == "REFRESH":
            s = homeserve.obtener()
            tg_edit(chat, msg_id, f"🔄 {len(s)} servicios", menu_principal())

        elif action == "WEB":
            s = homeserve.obtener()
            txt = "\n\n".join(s.values()) if s else "Sin servicios"
            tg_edit(chat, msg_id, txt, menu_principal())

        elif action == "CAMBIAR":
            s = homeserve.obtener()
            if not s:
                tg_edit(chat, msg_id, "Sin servicios", menu_principal())
            else:
                # mostrar lista simple
                text = "Selecciona servicio:\n\n" + "\n".join(s.keys())
                tg_edit(chat, msg_id, text, menu_principal())

        elif action == "USUARIOS":
            users = obtener_usuarios()
            tg_edit(chat, msg_id, "👤 Usuarios:\n" + "\n".join(users), menu_principal())

        # ---------- SERVICIO ----------
        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"✅ Aceptado {sid}", menu_principal())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"❌ Rechazado {sid}", menu_principal())

        # ---------- ESTADOS ----------
        elif action.startswith("ESTADOS_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, "🛠 Cambiar estado", botones_estados(sid))

        elif action.startswith("SET_"):
            _, sid, estado = action.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            tg_edit(chat, msg_id, msg, menu_principal())

        elif action.startswith("BACK_SERV_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"Servicio {sid}", botones_servicio(sid))

    return jsonify(ok=True)

# ---------------- START ----------------
threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado")
    app.run(host="0.0.0.0", port=10000)
