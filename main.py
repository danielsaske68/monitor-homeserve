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
logger = logging.getLogger("main")

# ---------------- VARIABLES ----------------
SERVICIOS_ACTUALES = {}
USUARIOS = {}
app = Flask(__name__)

# ---------------- DATABASE ----------------
DB_VOLUME_PATH = "/data/usuarios"
DB_PATH = os.path.join(DB_VOLUME_PATH, "usuarios.db")
os.makedirs(DB_VOLUME_PATH, exist_ok=True)

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                chat_id TEXT PRIMARY KEY,
                last_msg_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.info(f"📁 Base de datos inicializada en: {DB_PATH}")
    except Exception as e:
        logger.error(f"Error inicializando DB: {e}")

def guardar_usuario(chat_id, msg_id=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if msg_id is not None:
            c.execute("INSERT OR IGNORE INTO usuarios (chat_id, last_msg_id) VALUES (?, ?)", (str(chat_id), str(msg_id)))
            c.execute("UPDATE usuarios SET last_msg_id=? WHERE chat_id=?", (str(msg_id), str(chat_id)))
        else:
            c.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
        conn.commit()
        conn.close()
        USUARIOS[str(chat_id)] = msg_id
        logger.info(f"👤 Usuario guardado: {chat_id} (msg_id={msg_id if msg_id else 'Ninguno'})")
    except Exception as e:
        logger.error(f"Error guardando usuario: {e}")

def obtener_usuarios():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT chat_id, last_msg_id FROM usuarios")
        usuarios = [{"chat_id": row[0], "last_msg_id": row[1]} for row in c.fetchall()]
        conn.close()
        for u in usuarios:
            USUARIOS[u["chat_id"]] = u["last_msg_id"]
        return usuarios
    except Exception as e:
        logger.error(f"Error obteniendo usuarios: {e}")
        return []

init_db()
obtener_usuarios()

# ---------------- TELEGRAM ----------------
def enviar(chat, texto, botones=None):
    last_msg_id = USUARIOS.get(str(chat))
    data = {"chat_id": chat, "text": texto, "parse_mode": "HTML"}
    if botones:
        data["reply_markup"] = botones
    try:
        if last_msg_id:
            data["message_id"] = int(last_msg_id)
            resp = requests.post(f"{TELEGRAM_API}/editMessageText", json=data, timeout=10)
        else:
            resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10)
            if resp.ok:
                msg_id = resp.json()["result"]["message_id"]
                guardar_usuario(chat, msg_id)
        return True
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")
        return False

def menu_principal():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"},
             {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": "CAMBIAR_ESTADO"}]
        ]
    }

def botones_servicio(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{servicio_id}"},
             {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{servicio_id}"}]
        ]
    }

def botones_estado(servicio_id):
    return {
        "inline_keyboard": [
            [{"text": "🔴 Pendiente cliente", "callback_data": f"ESTADO_{servicio_id}_348"},
             {"text": "🟢 En espera por confirmar", "callback_data": f"ESTADO_{servicio_id}_318"}]
        ]
    }

def lista_servicios(servicios):
    teclado = []
    for sid in servicios:
        teclado.append([{"text": f"{sid}", "callback_data": f"SEL_{sid}"}])
    return {"inline_keyboard": teclado}

# ---------------- HOMESERVE ----------------
class HomeServe:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        try:
            payload = {"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"}
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(LOGIN_URL, data=payload, timeout=10)
            if "error" in r.text.lower():
                return False
            return True
        except:
            return False

    def obtener(self):
        try:
            r = self.session.get(ASIGNACION_URL, timeout=15)
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    sid = m.group(0)
                    servicios[sid] = " ".join(b.split())
            return servicios
        except:
            return {}

    def obtener_curso(self):
        try:
            r = self.session.get(SERVICIOS_CURSO_URL, timeout=10)
            r.encoding = "latin-1"
            texto = BeautifulSoup(r.text, "html.parser").get_text("\n")
            bloques = re.split(r"\n(?=\d{7,8}\s)", texto)
            servicios = {}
            for b in bloques:
                m = re.search(r"\b\d{7,8}\b", b)
                if m:
                    servicios[m.group(0)] = " ".join(b.split())
            return servicios
        except:
            return {}

    def cambiar_estado(self, servicio_id, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)
            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)
            obs = "Pendiente de localizar a asegurado" if estado=="348" else "En espera de Profesional por confirmación del Siniestro"
            payload = {
                "w3exec": "ver_servicioencurso",
                "Servicio": servicio_id,
                "ESTADO": estado,
                "FECSIG": fecha.strftime("%d/%m/%Y"),
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }
            r = self.session.post(BASE_URL, data=payload, timeout=10)
            return r.status_code==200, f"✅ Estado {estado} aplicado" if r.status_code==200 else f"⚠️ Error {r.status_code}"
        except Exception as e:
            return False, f"❌ Error: {e}"

    def aceptar_servicio(self, servicio_id):
        try:
            r = self.session.post(BASE_URL, data={"w3exec":"prof_asignacion","servicio":servicio_id,"ACEPTAR":"Aceptar"}, timeout=10)
            return r.status_code==200, f"✅ Servicio {servicio_id} aceptado"
        except:
            return False, "❌ Error aceptando"

    def rechazar_servicio(self, servicio_id):
        try:
            r = self.session.post(BASE_URL, data={"w3exec":"prof_asignacion","servicio":servicio_id,"RECHAZAR":"Rechazar"}, timeout=10)
            return r.status_code==200, f"❌ Servicio {servicio_id} rechazado"
        except:
            return False, "❌ Error rechazando"

homeserve = HomeServe()

# ---------------- LOOP ----------------
SERVICIOS_ACTUALES = {}

def bot_loop():
    global SERVICIOS_ACTUALES
    if not homeserve.login():
        logger.error("❌ Login fallido en loop")
    while True:
        actuales = homeserve.obtener()
        for sid, s in actuales.items():
            if sid not in SERVICIOS_ACTUALES:
                for chat_id in USUARIOS:
                    enviar(chat_id, f"🆕 Nuevo servicio\n{s}", botones_servicio(sid))
        SERVICIOS_ACTUALES = actuales
        time.sleep(INTERVALO)

# ---------------- WEBHOOK ----------------
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        msg = data["message"].get("text", "")
        if msg.startswith("/start"):
            enviar(chat, "👋 Hola, en qué puedo ayudar", menu_principal())
            guardar_usuario(chat, None)
        else:
            guardar_usuario(chat, None)
    if "callback_query" in data:
        accion = data["callback_query"]["data"]
        chat = data["callback_query"]["message"]["chat"]["id"]
        guardar_usuario(chat, None)
        # ---------------- CALLBACKS ----------------
        if accion=="LOGIN":
            ok = homeserve.login()
            enviar(chat, "✅ Login OK" if ok else "❌ Error login", menu_principal())
        elif accion=="REFRESH":
            homeserve.obtener()
            enviar(chat, "🔄 Actualizado", menu_principal())
        elif accion=="WEB":
            actuales = homeserve.obtener()
            if actuales:
                texto = "\n".join([f"{s}" for s in actuales.values()])
            else:
                texto = "No hay servicios"
            enviar(chat, texto, menu_principal())
        elif accion=="CAMBIAR_ESTADO":
            curso = homeserve.obtener_curso()
            if curso:
                enviar(chat, "🛠 Selecciona servicio en curso:", lista_servicios(curso))
            else:
                enviar(chat, "⚠️ No hay servicios en curso", menu_principal())
        elif accion.startswith("SEL_"):
            sid = accion.split("_")[1]
            enviar(chat, f"🔧 Servicio {sid}", botones_estado(sid))
        elif accion.startswith("ESTADO_"):
            _, sid, estado = accion.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            enviar(chat, msg, menu_principal())
        elif accion.startswith("ACEPTAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.aceptar_servicio(sid)
            enviar(chat, msg, menu_principal())
        elif accion.startswith("RECHAZAR_"):
            sid = accion.split("_")[1]
            ok, msg = homeserve.rechazar_servicio(sid)
            enviar(chat, msg, menu_principal())
    return jsonify(ok=True)

# ---------------- INICIO ----------------
for u in obtener_usuarios():
    enviar(u["chat_id"], "🤖 Bot activo", menu_principal())

threading.Thread(target=bot_loop, daemon=True).start()

if __name__=="__main__":
    logger.info("🚀 Bot iniciado correctamente")
    app.run(host="0.0.0.0", port=10000)
