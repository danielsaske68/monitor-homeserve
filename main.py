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
USER_STATE = {}
SERV_STATE = {}

# ---------------- DB (OPTIMIZADA) ----------------
DB_PATH = "/data/usuarios.db"
os.makedirs("/data", exist_ok=True)

def db(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    data = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data

db("CREATE TABLE IF NOT EXISTS usuarios (chat_id TEXT PRIMARY KEY)")

def guardar_usuario(chat_id):
    db("INSERT OR IGNORE INTO usuarios VALUES (?)", (str(chat_id),))

def obtener_usuarios():
    return [r[0] for r in db("SELECT chat_id FROM usuarios", fetch=True)]

def eliminar_usuario(chat_id):
    db("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))

# ---------------- FILE SYSTEM ----------------
def file_path(chat): return f"/data/servicios_{chat}.txt"

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

# ---------------- TELEGRAM (OPTIMIZADO) ----------------
def tg(method, data=None, files=None):
    return requests.post(
        f"{TELEGRAM_API}/{method}",
        json=data,
        files=files,
        timeout=10
    )

def tg_send(chat, text, markup=None):
    return tg("sendMessage", {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": markup
    })

def tg_edit(chat, msg_id, text, markup=None):
    return tg("editMessageText", {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": markup
    })

def tg_answer(cid):
    return tg("answerCallbackQuery", {"callback_query_id": cid})

def tg_doc(chat, path):
    return tg(
        "sendDocument",
        data={"chat_id": chat},
        files={"document": open(path, "rb")}
    )

# ---------------- BOTONES ----------------
def botones():
    return {"inline_keyboard": [
        [{"text":"🔐 Login","callback_data":"LOGIN"},{"text":"🔄 Refresh","callback_data":"REFRESH"}],
        [{"text":"🌐 Web","callback_data":"WEB"},{"text":"👥 Usuarios","callback_data":"USUARIOS"}],
        [{"text":"🛠 Cambiar estado","callback_data":"CAMBIAR"}],
        [{"text":"📦 Numero de servicios","callback_data":"NUM_SERV"}],
        [{"text":"📋 Servicios en curso","callback_data":"CURSO"}]
    ]}

def botones_num_serv():
    return {"inline_keyboard": [
        [{"text":"➕ Agregar","callback_data":"ADD_SERV"}],
        [{"text":"🗑 Eliminar","callback_data":"DEL_SERV"}],
        [{"text":"📥 Descargar","callback_data":"DOWN_SERV"}],
        [{"text":"👁 Ver","callback_data":"VIEW_SERV"}],
        [{"text":"⬅️ Volver","callback_data":"BACK_NUM_SERV"}]
    ]}

def botones_usuarios():
    return {"inline_keyboard": [
        [{"text":"➕ Agregar","callback_data":"ADD_USER"}],
        [{"text":"🗑 Eliminar","callback_data":"DEL_USER"}],
        [{"text":"📋 Listar","callback_data":"LIST_USERS"}],
        [{"text":"⬅️ Volver","callback_data":"BACK_MENU"}]
    ]}

def botones_servicio(sid):
    return {"inline_keyboard": [
        [{"text":"✅ Aceptar","callback_data":f"ACEPTAR_{sid}"},{"text":"❌ Rechazar","callback_data":f"RECHAZAR_{sid}"}],
        [{"text":"⬅️ Volver","callback_data":"WEB"}]
    ]}

def botones_estado(sid):
    return {"inline_keyboard": [
        [{"text":"🔴 348 Cliente","callback_data":f"ESTADO_{sid}_348"},{"text":"🟢 318 Confirmación","callback_data":f"ESTADO_{sid}_318"}],
        [{"text":"⬅️ Volver","callback_data":"CAMBIAR"}]
    ]}

def lista_servicios(servicios):
    return {
        "inline_keyboard": [[{"text":sid,"callback_data":f"SEL_{sid}"}] for sid in servicios]
        + [[{"text":"⬅️ Volver","callback_data":"BACK_MENU"}]]
    }

# ---------------- HOMESERVE (SIN CAMBIOS LOGICOS) ----------------
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

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"
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

    def obtener_servicios_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=15)
            r.encoding = "latin-1"
            soup = BeautifulSoup(r.text, "html.parser")

            servicios = []
            for fila in soup.find_all("tr")[1:]:
                cols = fila.find_all("td")
                if len(cols) >= 6:
                    raw = cols[0].get_text(" ", strip=True)
                    m = re.search(r"\d{7,8}", raw)
                    if not m:
                        continue

                    servicios.append({
                        "servicio": m.group(0),
                        "direccion": cols[2].get_text(" ", strip=True),
                        "fec_caduca": cols[5].get_text(" ", strip=True)
                    })

            return servicios
        except Exception as e:
            logger.error(e)
            return []

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)
            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            obs = "Pendiente de localizar a asegurado" if estado == "348" else "En espera de Profesional por confirmación del Siniestro"

            self.session.post(BASE_URL, data={
                "w3exec":"ver_servicioencurso",
                "Servicio":sid,
                "ESTADO":estado,
                "FECSIG":fecha.strftime("%d/%m/%Y"),
                "INFORMO":"on",
                "Observaciones":obs,
                "BTNCAMBIAESTADO":"Aceptar el Cambio"
            }, timeout=10)

            return True, f"✅ Estado {estado}"
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

threading.Thread(target=loop, daemon=True).start()

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        guardar_usuario(chat)

        if chat in SERV_STATE:
            msg = SERV_STATE[chat]["msg_id"]

            if text.upper() == "TERMINAR":
                SERV_STATE.pop(chat)
                tg_edit(chat, msg, "✅ Guardado", botones_num_serv())
            else:
                add_service(chat, text)
                tg_edit(chat, msg, read_services(chat), botones_num_serv())
            return jsonify(ok=True)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

        if chat in USER_STATE:
            if USER_STATE[chat] == "ADD_USER":
                guardar_usuario(text)
                tg_send(chat, "✅ Usuario añadido")
            elif USER_STATE[chat] == "DEL_USER":
                eliminar_usuario(text)
                tg_send(chat, "🗑 Usuario eliminado")
            USER_STATE.pop(chat)

    if "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])
        guardar_usuario(chat)

        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "Login OK" if ok else "Error", botones())

        elif action == "REFRESH":
            tg_edit(chat, msg_id, str(len(homeserve.obtener())), botones())

        elif action == "CURSO":
            servicios = homeserve.obtener_servicios_curso()
            texto = "📋 Servicios\n\n" + "\n\n".join(
                f"{s['servicio']} - {s['direccion']} - {s['fec_caduca']}"
                for s in servicios
            )
            tg_edit(chat, msg_id, texto, botones())

        elif action == "NUM_SERV":
            tg_edit(chat, msg_id, "📦 Servicios", botones_num_serv())

        elif action == "ADD_SERV":
            SERV_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id, "Escribe servicios", botones_num_serv())

        elif action == "DEL_SERV":
            clear_services(chat)
            tg_edit(chat, msg_id, "Borrado", botones_num_serv())

        elif action == "VIEW_SERV":
            tg_edit(chat, msg_id, read_services(chat) or "Vacío", botones_num_serv())

        elif action == "DOWN_SERV":
            tg_doc(chat, file_path(chat))

        elif action == "WEB":
            s = homeserve.obtener()
            if s:
                sid, txt = list(s.items())[0]
                tg_edit(chat, msg_id, txt, botones_servicio(sid))
            else:
                tg_edit(chat, msg_id, "Sin servicios", botones())

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "Menú", botones())

        elif action == "USUARIOS":
            tg_edit(chat, msg_id, "\n".join(obtener_usuarios()), botones_usuarios())

        elif action == "ADD_USER":
            USER_STATE[chat] = "ADD_USER"
            tg_send(chat, "Envía ID")

        elif action == "DEL_USER":
            USER_STATE[chat] = "DEL_USER"
            tg_send(chat, "Envía ID")

        elif action == "LIST_USERS":
            tg_edit(chat, msg_id, "\n".join(obtener_usuarios()) or "Vacío", botones_usuarios())

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            try:
                r = homeserve.session.get(f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}")
                tg_edit(chat, msg_id, "OK" if "error" not in r.text.lower() else "Error", botones())
            except:
                tg_edit(chat, msg_id, "Error", botones())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, "Rechazado", botones())

        elif action == "CAMBIAR":
            tg_edit(chat, msg_id, "Selecciona", lista_servicios(homeserve.obtener_curso()))

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, sid, botones_estado(sid))

        elif action.startswith("ESTADO_"):
            _, sid, est = action.split("_")
            msg = homeserve.cambiar_estado(sid, est)[1]
            tg_edit(chat, msg_id, msg, botones_estado(sid))

    return jsonify(ok=True)

# ---------------- START ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
