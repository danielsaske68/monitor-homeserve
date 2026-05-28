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

# =========================================================
# CONFIG
# =========================================================

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

# =========================================================
# STATE
# =========================================================

SERVICIOS_ACTUALES = {}
USER_STATE = {}
SERV_STATE = {}

# =========================================================
# DATABASE
# =========================================================

DB_PATH = "/data/usuarios.db"

os.makedirs("/data", exist_ok=True)

logger.info(f"DB PATH: {DB_PATH}")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            chat_id TEXT PRIMARY KEY
        )
    """)

    conn.commit()
    conn.close()

def guardar_usuario(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        "INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)",
        (str(chat_id),)
    )

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

    c.execute(
        "DELETE FROM usuarios WHERE chat_id=?",
        (str(chat_id),)
    )

    conn.commit()
    conn.close()

init_db()

# =========================================================
# FILES
# =========================================================

def file_path(chat):
    return f"/data/servicios_{chat}.txt"

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def read_services(chat):
    try:
        with open(file_path(chat), "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def clear_services(chat):
    open(file_path(chat), "w").close()

# =========================================================
# TELEGRAM
# =========================================================

def tg_send(chat, text, markup=None):

    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML"
    }

    if markup:
        payload["reply_markup"] = markup

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json=payload,
        timeout=10
    )

def tg_edit(chat, msg_id, text, markup=None):

    payload = {
        "chat_id": chat,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if markup:
        payload["reply_markup"] = markup

    requests.post(
        f"{TELEGRAM_API}/editMessageText",
        json=payload,
        timeout=10
    )

def tg_answer(callback_id):

    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={
            "callback_query_id": callback_id
        },
        timeout=10
    )

# =========================================================
# BOTONES
# =========================================================

def botones():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "🔐 Login",
                    "callback_data": "LOGIN"
                },
                {
                    "text": "🔄 Refresh",
                    "callback_data": "REFRESH"
                }
            ],

            [
                {
                    "text": "🌐 Web",
                    "callback_data": "WEB"
                },
                {
                    "text": "👥 Usuarios",
                    "callback_data": "USUARIOS"
                }
            ],

            [
                {
                    "text": "🛠 Cambiar estado",
                    "callback_data": "CAMBIAR"
                }
            ],

            [
                {
                    "text": "📋 Servicios en curso",
                    "callback_data": "CURSO"
                }
            ],

            [
                {
                    "text": "📦 Numero de servicios",
                    "callback_data": "NUM_SERV"
                }
            ]
        ]
    }

def botones_num_serv():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "➕ Agregar servicio",
                    "callback_data": "ADD_SERV"
                }
            ],

            [
                {
                    "text": "🗑 Eliminar archivo",
                    "callback_data": "DEL_SERV"
                }
            ],

            [
                {
                    "text": "📥 Descargar",
                    "callback_data": "DOWN_SERV"
                }
            ],

            [
                {
                    "text": "👁 Ver",
                    "callback_data": "VIEW_SERV"
                }
            ],

            [
                {
                    "text": "⬅️ Volver",
                    "callback_data": "BACK_NUM_SERV"
                }
            ]
        ]
    }

def botones_usuarios():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "➕ Agregar",
                    "callback_data": "ADD_USER"
                }
            ],

            [
                {
                    "text": "🗑 Eliminar",
                    "callback_data": "DEL_USER"
                }
            ],

            [
                {
                    "text": "📋 Listar",
                    "callback_data": "LIST_USERS"
                }
            ],

            [
                {
                    "text": "⬅️ Volver",
                    "callback_data": "BACK_MENU"
                }
            ]
        ]
    }

def botones_servicio(sid):

    return {
        "inline_keyboard": [

            [
                {
                    "text": "✅ Aceptar",
                    "callback_data": f"ACEPTAR_{sid}"
                },
                {
                    "text": "❌ Rechazar",
                    "callback_data": f"RECHAZAR_{sid}"
                }
            ],

            [
                {
                    "text": "⬅️ Volver",
                    "callback_data": "WEB"
                }
            ]
        ]
    }

def botones_estado(sid):

    return {
        "inline_keyboard": [

            [
                {
                    "text": "🔴 348 Cliente",
                    "callback_data": f"ESTADO_{sid}_348"
                },
                {
                    "text": "🟢 318 Confirmación",
                    "callback_data": f"ESTADO_{sid}_318"
                }
            ],

            [
                {
                    "text": "⬅️ Volver",
                    "callback_data": "CAMBIAR"
                }
            ]
        ]
    }

def lista_servicios(servicios):

    botones_lista = []

    for sid in servicios:

        botones_lista.append([
            {
                "text": sid,
                "callback_data": f"SEL_{sid}"
            }
        ])

    botones_lista.append([
        {
            "text": "⬅️ Volver",
            "callback_data": "BACK_MENU"
        }
    ])

    return {
        "inline_keyboard": botones_lista
    }

# =========================================================
# HOMESERVE
# =========================================================

class HomeServe:

    def __init__(self):
        self.session = requests.Session()

    def login(self):

        try:

            self.session.get(LOGIN_URL, timeout=10)

            r = self.session.post(
                LOGIN_URL,
                data={
                    "CODIGO": USUARIO,
                    "PASSW": PASSWORD,
                    "BTN": "Aceptar"
                },
                timeout=10
            )

            return "error" not in r.text.lower()

        except:
            return False

    def obtener(self):

        try:

            r = self.session.get(
                ASIGNACION_URL,
                timeout=15
            )

            text = BeautifulSoup(
                r.text,
                "html.parser"
            ).get_text("\n")

            bloques = re.split(
                r"\n(?=\d{7,8}\s)",
                text
            )

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

            r = self.session.get(
                SERVICIOS_CURSO_URL,
                timeout=10
            )

            r.encoding = "latin-1"

            text = BeautifulSoup(
                r.text,
                "html.parser"
            ).get_text("\n")

            bloques = re.split(
                r"\n(?=\d{7,8}\s)",
                text
            )

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

            obs = (
                "Pendiente de localizar a asegurado"
                if estado == "348"
                else "En espera de Profesional por confirmación del Siniestro"
            )

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

            self.session.post(
                BASE_URL,
                data=payload,
                timeout=10
            )

            return True, f"✅ Estado {estado} aplicado ({fecha_str})"

        except Exception as e:

            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# =========================================================
# LOOP
# =========================================================

def loop():

    global SERVICIOS_ACTUALES

    homeserve.login()

    while True:

        try:

            actuales = homeserve.obtener()

            for sid, txt in actuales.items():

                if sid not in SERVICIOS_ACTUALES:

                    for u in obtener_usuarios():

                        tg_send(
                            u,
                            f"🆕 <b>Nuevo servicio</b>\n\n{txt}",
                            botones_servicio(sid)
                        )

            SERVICIOS_ACTUALES = actuales

            time.sleep(INTERVALO)

        except Exception as e:

            logger.error(e)

            homeserve.login()

            time.sleep(10)

threading.Thread(
    target=loop,
    daemon=True
).start()

# =========================================================
# WEBHOOK
# =========================================================

@app.route("/telegram_webhook", methods=["POST"])
def webhook():

    data = request.json

    # =====================================================
    # MENSAJES
    # =====================================================

    if "message" in data:

        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        guardar_usuario(chat)

        # ---------------------------------------------
        # GUARDAR SERVICIOS TXT
        # ---------------------------------------------

        if chat in SERV_STATE:

            data_serv = SERV_STATE[chat]
            msg_edit = data_serv["msg_id"]

            if text.upper() == "TERMINAR":

                SERV_STATE.pop(chat)

                tg_edit(
                    chat,
                    msg_edit,
                    "✅ Servicios guardados correctamente",
                    botones_num_serv()
                )

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

        # ---------------------------------------------
        # START
        # ---------------------------------------------

        if text == "/start":

            tg_send(
                chat,
                "🤖 Bot activo",
                botones()
            )

        # ---------------------------------------------
        # USERS
        # ---------------------------------------------

        if chat in USER_STATE:

            if USER_STATE[chat] == "ADD_USER":

                guardar_usuario(text)

                tg_send(chat, "✅ Usuario añadido")

                USER_STATE.pop(chat)

            elif USER_STATE[chat] == "DEL_USER":

                eliminar_usuario(text)

                tg_send(chat, "🗑 Usuario eliminado")

                USER_STATE.pop(chat)

    # =====================================================
    # CALLBACKS
    # =====================================================

    if "callback_query" in data:

        cq = data["callback_query"]

        chat = cq["message"]["chat"]["id"]

        msg_id = cq["message"]["message_id"]

        action = cq["data"]

        tg_answer(cq["id"])

        guardar_usuario(chat)

        # =================================================
        # LOGIN
        # =================================================

        if action == "LOGIN":

            ok = homeserve.login()

            tg_edit(
                chat,
                msg_id,
                "✅ Login OK" if ok else "❌ Error Login",
                botones()
            )

        # =================================================
        # REFRESH
        # =================================================

        elif action == "REFRESH":

            total = len(homeserve.obtener())

            tg_edit(
                chat,
                msg_id,
                f"🔄 {total} servicios",
                botones()
            )

        # =================================================
        # WEB
        # =================================================

        elif action == "WEB":

            servicios = homeserve.obtener()

            if servicios:

                sid, txt = list(servicios.items())[0]

                tg_edit(
                    chat,
                    msg_id,
                    txt,
                    botones_servicio(sid)
                )

            else:

                tg_edit(
                    chat,
                    msg_id,
                    "❌ Sin servicios",
                    botones()
                )

        # =================================================
        # CURSO
        # =================================================

        elif action == "CURSO":

            curso = homeserve.obtener_curso()

            if not curso:

                tg_edit(
                    chat,
                    msg_id,
                    "❌ No hay servicios en curso",
                    botones()
                )

            else:

                tg_edit(
                    chat,
                    msg_id,
                    "📋 Servicios en curso",
                    lista_servicios(curso)
                )

        # =================================================
        # CAMBIAR ESTADO
        # =================================================

        elif action == "CAMBIAR":

            curso = homeserve.obtener_curso()

            if not curso:

                tg_edit(
                    chat,
                    msg_id,
                    "❌ No hay servicios",
                    botones()
                )

            else:

                tg_edit(
                    chat,
                    msg_id,
                    "🛠 Selecciona servicio",
                    lista_servicios(curso)
                )

        # =================================================
        # SELECCIONAR SERVICIO
        # =================================================

        elif action.startswith("SEL_"):

    sid = action.split("_")[1]

    try:

        url = (
            f"{BASE_URL}"
            f"?w3exec=ver_servicioencurso"
            f"&Servicio={sid}"
            f"&Pag=1"
        )

        r = homeserve.session.get(url, timeout=15)

        soup = BeautifulSoup(r.text, "html.parser")

        datos = {}

        filas = soup.find_all("tr")

        for fila in filas:

            tds = fila.find_all("td")

            if len(tds) >= 2:

                clave = tds[0].get_text(" ", strip=True)
                valor = tds[1].get_text(" ", strip=True)

                clave = clave.replace(":", "").strip()

                datos[clave] = valor

        servicio = datos.get("SERVICIO", sid)
        domicilio = datos.get("DOMICILIO", "No encontrado")
        poblacion = datos.get("POBLACION-PROVINCIA", "No encontrado")

        comentarios = datos.get("COMENTARIOS", "Sin comentarios")

        comentarios = comentarios.strip()

        lineas = comentarios.splitlines()

        comentarios = "\n".join(lineas[:5])

        texto = (
            f"📋 <b>SERVICIO:</b> {servicio}\n\n"
            f"🏠 <b>DOMICILIO:</b>\n{domicilio}\n\n"
            f"📍 <b>POBLACION-PROVINCIA:</b>\n{poblacion}\n\n"
            f"📝 <b>COMENTARIOS:</b>\n{comentarios}"
        )

        tg_edit(
            chat,
            msg_id,
            texto,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Volver",
                            "callback_data": "CURSO"
                        }
                    ]
                ]
            }
        )

    except Exception as e:

        tg_edit(
            chat,
            msg_id,
            f"❌ Error obteniendo servicio:\n\n{e}",
            botones()
        )

        # =================================================
        # CAMBIAR ESTADO REAL
        # =================================================

        elif action.startswith("ESTADO_"):

            try:

                _, sid, estado = action.split("_")

                ok, msg = homeserve.cambiar_estado(
                    sid,
                    estado
                )

                tg_edit(
                    chat,
                    msg_id,
                    msg,
                    botones_estado(sid)
                )

            except Exception as e:

                tg_edit(
                    chat,
                    msg_id,
                    f"❌ Error: {e}",
                    botones()
                )

        # =================================================
        # NUM SERV
        # =================================================

        elif action == "NUM_SERV":

            tg_edit(
                chat,
                msg_id,
                "📦 Numero de servicios",
                botones_num_serv()
            )

        # =================================================
        # ADD SERV
        # =================================================

        elif action == "ADD_SERV":

            SERV_STATE[chat] = {
                "msg_id": msg_id
            }

            tg_edit(
                chat,
                msg_id,
                "✍️ Escribe servicios.\n\nCuando acabes escribe:\nTERMINAR",
                botones_num_serv()
            )

        # =================================================
        # DELETE SERV
        # =================================================

        elif action == "DEL_SERV":

            clear_services(chat)

            tg_edit(
                chat,
                msg_id,
                "🗑 Archivo eliminado",
                botones_num_serv()
            )

        # =================================================
        # VIEW SERV
        # =================================================

        elif action == "VIEW_SERV":

            contenido = read_services(chat)

            tg_edit(
                chat,
                msg_id,
                contenido if contenido else "Vacío",
                botones_num_serv()
            )

        # =================================================
        # DOWNLOAD SERV
        # =================================================

        elif action == "DOWN_SERV":

            path = file_path(chat)

            requests.post(
                f"{TELEGRAM_API}/sendDocument",
                data={
                    "chat_id": chat
                },
                files={
                    "document": open(path, "rb")
                }
            )

        # =================================================
        # BACK NUM
        # =================================================

        elif action == "BACK_NUM_SERV":

            tg_edit(
                chat,
                msg_id,
                "📦 Menú",
                botones()
            )

        # =================================================
        # USERS
        # =================================================

        elif action == "USUARIOS":

            tg_edit(
                chat,
                msg_id,
                "👥 Usuarios",
                botones_usuarios()
            )

        elif action == "ADD_USER":

            USER_STATE[chat] = "ADD_USER"

            tg_send(chat, "Envía ID")

        elif action == "DEL_USER":

            USER_STATE[chat] = "DEL_USER"

            tg_send(chat, "Envía ID")

        elif action == "LIST_USERS":

            usuarios = "\n".join(obtener_usuarios())

            tg_edit(
                chat,
                msg_id,
                usuarios if usuarios else "Vacío",
                botones_usuarios()
            )

        # =================================================
        # ACEPTAR
        # =================================================

        elif action.startswith("ACEPTAR_"):

            sid = action.split("_")[1]

            try:

                url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"

                r = homeserve.session.get(
                    url,
                    timeout=15
                )

                html = r.text.lower()

                errores = [
                    "error",
                    "illegal",
                    "denegado",
                    "caducada",
                    "no autorizado",
                    "acceso inválido"
                ]

                fallo = any(e in html for e in errores)

                ok_visual = (
                    "<table" in html
                    or "<form" in html
                    or "servicio" in html
                )

                if fallo:

                    tg_edit(
                        chat,
                        msg_id,
                        f"❌ Error al aceptar servicio {sid}",
                        botones()
                    )

                elif ok_visual:

                    tg_edit(
                        chat,
                        msg_id,
                        f"✅ Servicio {sid} aceptado correctamente",
                        botones()
                    )

                else:

                    tg_edit(
                        chat,
                        msg_id,
                        f"⚠️ No se pudo confirmar aceptación de {sid}",
                        botones()
                    )

            except Exception as e:

                tg_edit(
                    chat,
                    msg_id,
                    f"❌ {e}",
                    botones()
                )

        # =================================================
        # RECHAZAR
        # =================================================

        elif action.startswith("RECHAZAR_"):

            sid = action.split("_")[1]

            homeserve.cambiar_estado(
                sid,
                "348"
            )

            tg_edit(
                chat,
                msg_id,
                "❌ Rechazado",
                botones()
            )

        # =================================================
        # BACK
        # =================================================

        elif action == "BACK_MENU":

            tg_edit(
                chat,
                msg_id,
                "🏠 Menú",
                botones()
            )

    return jsonify(ok=True)

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
