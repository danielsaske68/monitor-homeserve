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
    c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
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

# ---------------- FILE ----------------
def file_path(chat):
    return f"/data/servicios_{chat}.txt"

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def read_services(chat):
    try:
        return open(file_path(chat), "r", encoding="utf-8").read()
    except:
        return ""

def clear_services(chat):
    open(file_path(chat), "w").close()

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
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cid})

# ---------------- BOTONES ----------------
def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 348", "callback_data": f"ESTADO_{sid}_348"},
                {"text": "🟢 318", "callback_data": f"ESTADO_{sid}_318"}
            ],
            [
                {"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"},
                {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}
            ],
            [{"text": "⬅️ Volver", "callback_data": "CAMBIAR"}]
        ]
    }

def lista_servicios(servicios):
    return {"inline_keyboard": [[{"text": s, "callback_data": f"SEL_{s}"}] for s in servicios]}

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
            bloques = re.split(r"\n(?=\d{7,8}\s)", text)
            out = {}
            for b in bloques:
                m = re.search(r"\d{7,8}", b)
                if m:
                    out[m.group()] = " ".join(b.split())
            return out
        except:
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)
            fecha_str = fecha.strftime("%d/%m/%Y")

            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": sid,
                "ESTADO": estado,
                "FECSIG": fecha_str,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            self.session.post(BASE_URL, data=payload)
            return True, f"✅ Estado {estado} aplicado"
        except Exception as e:
            return False, str(e)

homeserve = HomeServe()

# ---------------- LOOP ----------------
def loop():
    global SERVICIOS_ACTUALES
    homeserve.login()

    while True:
        try:
            actuales = homeserve.obtener()
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except:
            homeserve.login()
            time.sleep(5)

threading.Thread(target=loop, daemon=True).start()

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    # ---------------- MENSAJES ----------------
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()

        guardar_usuario(chat)

        # ---- flujo servicios manuales ----
        if chat in SERV_STATE:
            data_serv = SERV_STATE[chat]
            msg_edit = data_serv["msg_id"]

            if text.upper() == "TERMINAR":
                SERV_STATE.pop(chat, None)
                tg_edit(chat, msg_edit, "✅ Servicios guardados correctamente", botones_num_serv())
            else:
                add_service(chat, text)
                actual = read_services(chat)
                tg_edit(
                    chat,
                    msg_edit,
                    f"✅ Guardado ✔️\n\n{actual}\n\nEscribe otro o TERMINAR",
                    botones_num_serv()
                )
            return jsonify(ok=True)

        # ---- comandos básicos ----
        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

        # ---- usuarios estado ----
        if chat in USER_STATE:
            state = USER_STATE[chat]

            if state == "ADD_USER":
                guardar_usuario(text)
                tg_send(chat, "✅ Usuario añadido")
                USER_STATE.pop(chat, None)

            elif state == "DEL_USER":
                eliminar_usuario(text)
                tg_send(chat, "🗑 Usuario eliminado")
                USER_STATE.pop(chat, None)

    # ---------------- CALLBACKS ----------------
    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])
        guardar_usuario(chat)

        # ---- login ----
        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "Login OK" if ok else "Error", botones())

        elif action == "REFRESH":
            tg_edit(chat, msg_id, f"{len(homeserve.obtener())} servicios", botones())

        # ---- curso ----
        elif action == "CURSO":
            servicios = homeserve.obtener_servicios_curso()
            if not servicios:
                tg_edit(chat, msg_id, "❌ No hay servicios en curso", botones())
            else:
                texto = "📋 <b>Servicios en curso</b>\n\n"
                for s in servicios:
                    texto += (
                        f"🔹 <b>Servicio:</b> {s['servicio']}\n"
                        f"📍 <b>Dirección:</b> {s['direccion']}\n"
                        f"📅 <b>Caduca:</b> {s['fec_caduca']}\n\n"
                    )

                if len(texto) > 3500:
                    texto = texto[:3500] + "\n\n⚠️ Texto truncado..."

                tg_edit(chat, msg_id, texto, botones())

        elif action == "NUM_SERV":
            tg_edit(chat, msg_id, "📦 Numero de servicios", botones_num_serv())

        elif action == "ADD_SERV":
            SERV_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id,
                    "✍️ Escribe servicios.\n\nCuando acabes escribe:\nTERMINAR",
                    botones_num_serv())

        elif action == "DEL_SERV":
            clear_services(chat)
            tg_edit(chat, msg_id, "🗑 Archivo eliminado", botones_num_serv())

        elif action == "VIEW_SERV":
            contenido = read_services(chat)
            tg_edit(chat, msg_id, contenido if contenido else "Vacío", botones_num_serv())

        elif action == "DOWN_SERV":
            path = file_path(chat)
            with open(path, "rb") as f:
                requests.post(
                    f"{TELEGRAM_API}/sendDocument",
                    data={"chat_id": chat},
                    files={"document": f}
                )

        elif action == "BACK_NUM_SERV":
            tg_edit(chat, msg_id, "Menú", botones())

        # ---- web ----
        elif action == "WEB":
            servicios = homeserve.obtener()
            if servicios:
                sid, txt = list(servicios.items())[0]
                tg_edit(chat, msg_id, txt, botones_servicio(sid))
            else:
                tg_edit(chat, msg_id, "Sin servicios", botones())

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

        # ---- usuarios ----
        elif action == "USUARIOS":
            tg_edit(chat, msg_id, "Usuarios", botones_usuarios())

        elif action == "ADD_USER":
            USER_STATE[chat] = "ADD_USER"
            tg_send(chat, "Envía ID")

        elif action == "DEL_USER":
            USER_STATE[chat] = "DEL_USER"
            tg_send(chat, "Envía ID")

        elif action == "LIST_USERS":
            tg_edit(chat, msg_id,
                    "\n".join(obtener_usuarios()) or "Vacío",
                    botones_usuarios())

        # =========================
        # ✅ ACEPTAR SERVICIO
        # =========================
        elif action.startswith("ACEPTAR_"):
            sid = action.split("_", 1)[1]

            try:
                url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
                r = homeserve.session.get(url, timeout=15)
                html = r.text.lower()

                errores = [
                    "error", "illegal", "denegado",
                    "caducada", "no autorizado", "acceso inválido"
                ]

                fallo = any(e in html for e in errores)
                ok_visual = ("<table" in html or "<form" in html or "servicio" in html)

                if fallo:
                    tg_edit(chat, msg_id, f"❌ Error al aceptar servicio {sid}", botones())
                elif ok_visual:
                    tg_edit(chat, msg_id, f"✅ Servicio {sid} aceptado correctamente", botones())
                else:
                    tg_edit(chat, msg_id,
                            f"⚠️ No se pudo confirmar aceptación de {sid}",
                            botones())

            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error: {e}", botones())

        # =========================
        # ❌ RECHAZAR SERVICIO
        # =========================
        elif action.startswith("RECHAZAR_"):
            sid = action.split("_", 1)[1]

            ok, msg = homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, "❌ Rechazado\n" + msg, botones())

        # ---- cambio estado ----
        elif action == "CAMBIAR":
            curso = homeserve.obtener_curso()
            tg_edit(chat, msg_id, "Selecciona", lista_servicios(curso))

        elif action.startswith("SEL_"):
            sid = action.split("_", 1)[1]
            tg_edit(chat, msg_id, sid, botones_estado(sid))

        elif action.startswith("ESTADO_"):
            try:
                _, sid, estado = action.split("_")
                ok, msg = homeserve.cambiar_estado(sid, estado)
                tg_edit(chat, msg_id, msg, botones_estado(sid))
            except:
                tg_edit(chat, msg_id, "❌ Error estado inválido", botones())

    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
