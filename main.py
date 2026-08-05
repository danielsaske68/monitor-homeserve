import os
import time
import threading
import logging
import re
import requests
import sqlite3
from urllib.parse import quote_plus
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

# =========================================================
# CONFIG
# =========================================================

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
INTERVALO = int(os.getenv("INTERVALO_SEGUNDOS", 40))
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"
SERVICIOS_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bot")

app = Flask(__name__)

# =========================================================
# STATE & DB
# =========================================================

SERVICIOS_ACTUALES = {}
USER_STATE = {}
SERV_STATE = {}

DATA_DIR = "/data"
DB_PATH = os.path.join(DATA_DIR, "usuarios.db")
os.makedirs(DATA_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                chat_id TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seguimiento (
                sid TEXT PRIMARY KEY,
                estado TEXT,
                fecha_cambio TIMESTAMP,
                ultimo_aviso TIMESTAMP
            )
        """)
        conn.commit()

def guardar_usuario(chat_id):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
        conn.commit()

def obtener_usuarios():
    with get_db() as conn:
        cursor = conn.execute("SELECT chat_id FROM usuarios")
        return [r["chat_id"] for r in cursor.fetchall()]

def eliminar_usuario(chat_id):
    with get_db() as conn:
        conn.execute("DELETE FROM usuarios WHERE chat_id=?", (str(chat_id),))
        conn.commit()

def registrar_seguimiento(sid, estado):
    with get_db() as conn:
        ahora = datetime.now()
        conn.execute("""
            INSERT INTO seguimiento (sid, estado, fecha_cambio, ultimo_aviso)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sid) DO UPDATE SET
                estado=excluded.estado,
                fecha_cambio=excluded.fecha_cambio,
                ultimo_aviso=excluded.ultimo_aviso
        """, (sid, estado, ahora, ahora))
        conn.commit()

init_db()

# =========================================================
# FILES
# =========================================================

def file_path(chat):
    return os.path.join(DATA_DIR, f"servicios_{chat}.txt")

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def read_services(chat):
    try:
        with open(file_path(chat), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def clear_services(chat):
    path = file_path(chat)
    if os.path.exists(path):
        open(path, "w").close()

# =========================================================
# TELEGRAM
# =========================================================

tg_session = requests.Session()

def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    try:
        tg_session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error tg_send: {e}")

def tg_edit(chat, msg_id, text, markup=None):
    payload = {"chat_id": chat, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    try:
        tg_session.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error tg_edit: {e}")

def tg_answer(callback_id):
    try:
        tg_session.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
    except Exception as e:
        logger.error(f"Error tg_answer: {e}")

# =========================================================
# BOTONES
# =========================================================

def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"}, {"text": "🔄 Refresh", "callback_data": "REFRESH"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}, {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}],
            [{"text": "📋 Servicios en curso", "callback_data": "CURSO"}],
            [{"text": "📦 Número de servicios", "callback_data": "NUM_SERV"}],
            [{"text": "📊 Baremo", "callback_data": "BAREMO"}]
        ]
    }

def botones_num_serv():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar servicio", "callback_data": "ADD_SERV"}],
            [{"text": "🗑 Eliminar archivo", "callback_data": "DEL_SERV"}],
            [{"text": "📥 Descargar", "callback_data": "DOWN_SERV"}],
            [{"text": "👁 Ver", "callback_data": "VIEW_SERV"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_NUM_SERV"}]
        ]
    }

def botones_usuarios():
    return {
        "inline_keyboard": [
            [{"text": "➕ Agregar", "callback_data": "ADD_USER"}],
            [{"text": "🗑 Eliminar", "callback_data": "DEL_USER"}],
            [{"text": "📋 Listar", "callback_data": "LIST_USERS"}],
            [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
        ]
    }

def botones_servicio(sid):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aceptar", "callback_data": f"ACEPTAR_{sid}"}, {"text": "❌ Rechazar", "callback_data": f"RECHAZAR_{sid}"}],
            [{"text": "⬅️ Volver", "callback_data": "WEB"}]
        ]
    }

def botones_estado(sid):
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 En espera de cliente", "callback_data": f"ESTADO_{sid}_348"},
                {"text": "🟢 En espera por confirmación", "callback_data": f"ESTADO_{sid}_318"}
            ],
            [
                {"text": "🟠 En Espera de otro Gremio", "callback_data": f"ESTADO_{sid}_320"}
            ],
            [{"text": "⬅️ Volver", "callback_data": "CAMBIAR"}]
        ]
    }

def lista_curso(servicios):
    botones_lista = [[{"text": f"👁 {sid}", "callback_data": f"SEL_{sid}"}] for sid in servicios]
    botones_lista.append([{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}])
    return {"inline_keyboard": botones_lista}

def lista_cambio(servicios):
    botones_lista = [[{"text": f"🛠 {sid}", "callback_data": f"CAMSEL_{sid}"}] for sid in servicios]
    botones_lista.append([{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}])
    return {"inline_keyboard": botones_lista}

# =========================================================
# HOMESERVE CLASS
# =========================================================

class HomeServe:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Connection": "keep-alive"
        })
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504], raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def login(self):
        try:
            self.session.get(LOGIN_URL, timeout=10)
            r = self.session.post(
                LOGIN_URL,
                data={"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"},
                timeout=10
            )
            return "error" not in r.text.lower()
        except Exception as e:
            logger.error(f"Login Exception: {e}")
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
        except Exception as e:
            logger.warning(f"Error obtener, re-intentando login: {e}")
            if self.login():
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
                except Exception as ex:
                    logger.error(f"Error definitivo obtener: {ex}")
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
        except Exception as e:
            logger.error(f"Error obtener_curso: {e}")
            self.login()
            return {}

    def cambiar_estado(self, sid, estado):
        try:
            fecha = datetime.now() + timedelta(days=3)
            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            fecha_str = fecha.strftime("%d/%m/%Y")

            if estado == "348":
                obs = "Pendiente de localizar a asegurado"
            elif estado == "318":
                obs = "En espera de Profesional por confirmación del Siniestro"
            elif estado == "320":
                obs = "En espera de Profesional por espera de otro gremio"
            else:
                obs = "Cambio de estado tramitado desde bot"

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
            registrar_seguimiento(sid, estado)
            return True, f"✅ Estado {estado} aplicado ({fecha_str})"
        except Exception as e:
            return False, f"❌ Error: {e}"

homeserve = HomeServe()

# =========================================================
# BACKGROUND LOOPS (MONITOR & RECORDATORIOS)
# =========================================================

def loop():
    global SERVICIOS_ACTUALES
    homeserve.login()

    while True:
        try:
            logger.info("🔎 [MONITOR] Consultando asignación de nuevos servicios...")
            actuales = homeserve.obtener()
            logger.info(f"📊 [MONITOR] Servicios encontrados en la web: {len(actuales)}")

            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    logger.info(f"🚨 [NUEVO SERVICIO] Detectado servicio ID: {sid}")
                    for u in obtener_usuarios():
                        tg_send(u, f"🆕 <b>Nuevo servicio</b>\n\n{txt}", botones_servicio(sid))
             
            SERVICIOS_ACTUALES = actuales
            time.sleep(INTERVALO)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(10)

def loop_recordatorios():
    while True:
        try:
            time.sleep(3600)
            with get_db() as conn:
                cursor = conn.execute("SELECT sid, estado, fecha_cambio, ultimo_aviso FROM seguimiento WHERE estado IN ('348', '320')")
                registros = cursor.fetchall()
              
                ahora = datetime.now()
                for r in registros:
                    ultimo_aviso = datetime.strptime(r["ultimo_aviso"], "%Y-%m-%d %H:%M:%S.%f") if "." in r["ultimo_aviso"] else datetime.strptime(r["ultimo_aviso"], "%Y-%m-%d %H:%M:%S")
                  
                    if (ahora - ultimo_aviso).total_seconds() >= 86400:
                        txt = (
                            f"⏰ <b>RECORDATORIO DE SEGUIMIENTO</b>\n\n"
                            f"El servicio <b>{r['sid']}</b> lleva pendiente en estado <b>{r['estado']}</b>.\n"
                            f"¿Has podido hablar con el cliente o avanzar con la avería?"
                        )
                        for u in obtener_usuarios():
                            tg_send(u, txt, botones_estado(r['sid']))
                      
                        conn.execute("UPDATE seguimiento SET ultimo_aviso=? WHERE sid=?", (ahora, r["sid"]))
                        conn.commit()
        except Exception as e:
            logger.error(f"Error en loop_recordatorios: {e}")

threading.Thread(target=loop, daemon=True).start()
threading.Thread(target=loop_recordatorios, daemon=True).start()

# =========================================================
# WEBHOOK
# =========================================================

@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json or {}

    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        guardar_usuario(chat)

        if chat in SERV_STATE:
            msg_edit = SERV_STATE[chat]["msg_id"]
            if text.upper() == "TERMINAR":
                SERV_STATE.pop(chat)
                tg_edit(chat, msg_edit, "✅ Servicios guardados correctamente", botones_num_serv())
            else:
                add_service(chat, text)
                actual = read_services(chat)
                tg_edit(chat, msg_edit, f"✅ Guardado ✔️\n\n{actual}\n\nEscribe otro o TERMINAR", botones_num_serv())
            return jsonify(ok=True)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())

        if chat in USER_STATE:
            if USER_STATE[chat] == "ADD_USER":
                guardar_usuario(text)
                tg_send(chat, "✅ Usuario añadido")
                USER_STATE.pop(chat)
            elif USER_STATE[chat] == "DEL_USER":
                eliminar_usuario(text)
                tg_send(chat, "🗑 Usuario eliminado")
                USER_STATE.pop(chat)

    elif "callback_query" in data:
        cq = data["callback_query"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq["data"]

        tg_answer(cq["id"])
        guardar_usuario(chat)

        if action == "LOGIN":
            ok = homeserve.login()
            tg_edit(chat, msg_id, "✅ Login OK" if ok else "❌ Error Login", botones())

        elif action == "REFRESH":
            total = len(homeserve.obtener())
            tg_edit(chat, msg_id, f"🔄 {total} servicios", botones())

        elif action == "WEB":
            servicios = homeserve.obtener()
            if not servicios:
                tg_edit(chat, msg_id, "❌ Sin servicios", botones())
            else:
                tg_edit(chat, msg_id, f"🌐 {len(servicios)} servicios encontrados", botones())
                for sid, txt in servicios.items():
                    tg_send(chat, txt, botones_servicio(sid))

        elif action == "CURSO":
            curso = homeserve.obtener_curso()
            tg_edit(
                chat, msg_id,
                "📋 Servicios en curso" if curso else "❌ No hay servicios en curso",
                lista_curso(curso) if curso else botones()
            )

        elif action == "CAMBIAR":
            curso = homeserve.obtener_curso()
            tg_edit(
                chat, msg_id,
                "🛠 Selecciona servicio",
                lista_cambio(curso) if curso else botones()
            )

        elif action.startswith("CAMSEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"🛠 <b>Cambiar estado del servicio</b>\n\n<b>{sid}</b>", botones_estado(sid))

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            try:
                url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
                r = homeserve.session.get(url, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")
              
                datos = {}
                for tr in soup.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) >= 2:
                        clave = tds[0].get_text(" ", strip=True).replace(":", "").upper()
                        valor = tds[1].get_text(" ", strip=True)
                        datos[clave] = valor

                servicio = datos.get("SERVICIO", sid)
                cliente = datos.get("CLIENTE", "")
                telefonos = datos.get("TELEFONOS", "")
                domicilio = datos.get("DOMICILIO", "")
                poblacion = datos.get("POBLACION-PROVINCIA", "")
                comentarios = datos.get("COMENTARIOS", "")
                comentarios = "\n".join(comentarios.splitlines()[:5])

                direccion_completa = f"{domicilio}, {poblacion}".strip(", ")
                query_mapa = quote_plus(direccion_completa)
                gmaps_url = f"https://www.google.com/maps/search/?api=1&query={query_mapa}"
                waze_url = f"https://waze.com/ul?q={query_mapa}&navigate=yes"

                numeros = re.findall(r"\b\d{9}\b", telefonos)
                telefonos_formateados = ""
                for num in numeros:
                    telefonos_formateados += f"📞 <a href='tel:+34{num}'>{num}</a> (Llamar)\n"
                if not telefonos_formateados:
                    telefonos_formateados = telefonos

                texto = (
                    f"📋 <b>SERVICIO:</b> {servicio}\n\n"
                    f"👤 <b>CLIENTE:</b> {cliente}\n\n"
                    f"📞 <b>TELÉFONOS:</b>\n{telefonos_formateados}\n"
                    f"🏠 <b>DOMICILIO:</b> {domicilio}\n"
                    f"📍 <b>POBLACIÓN:</b> {poblacion}\n\n"
                    f"📝 <b>COMENTARIOS:</b>\n{comentarios}"
                )

                inline_kb = [
                    [{"text": "📍 Google Maps", "url": gmaps_url}, {"text": "🚙 Waze", "url": waze_url}],
                    [{"text": "🛠 Cambiar Estado", "callback_data": f"CAMSEL_{sid}"}],
                    [{"text": "⬅️ Volver", "callback_data": "CURSO"}]
                ]

                tg_edit(chat, msg_id, texto, {"inline_keyboard": inline_kb})
            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error obteniendo servicio:\n{e}", botones())

        elif action.startswith("ESTADO_"):
            _, sid, estado = action.split("_")
            ok, msg = homeserve.cambiar_estado(sid, estado)
            tg_edit(chat, msg_id, msg, botones_estado(sid))

        elif action == "NUM_SERV":
            tg_edit(chat, msg_id, "📦 Número de servicios", botones_num_serv())

        elif action == "ADD_SERV":
            SERV_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id, "✍️ Escribe servicios.\n\nTERMINAR para acabar", botones_num_serv())

        elif action == "DEL_SERV":
            clear_services(chat)
            tg_edit(chat, msg_id, "🗑 Archivo eliminado", botones_num_serv())

        elif action == "VIEW_SERV":
            contenido = read_services(chat)
            tg_edit(chat, msg_id, contenido if contenido else "Vacío", botones_num_serv())

        elif action == "DOWN_SERV":
            path = file_path(chat)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    requests.post(f"{TELEGRAM_API}/sendDocument", data={"chat_id": chat}, files={"document": f}, timeout=15)

        elif action == "BACK_NUM_SERV":
            tg_edit(chat, msg_id, "📦 Menú", botones())

        elif action == "BAREMO":
            texto_baremo = (
                "📊 <b>CONSULTA DE BAREMO Y TARIFAS</b>\n\n"
                "Selecciona o consulta las condiciones y valores económicos asociados a las intervenciones y siniestros."
            )
            keyboard_baremo = {
                "inline_keyboard": [
                    [{"text": "🌐 Ver Baremo Oficial", "url": "https://web.multiassistance.com/w3multi/documentos/cat3/Baremo2013.pdf"}],
                    [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
                ]
            }
            tg_edit(chat, msg_id, texto_baremo, keyboard_baremo)

        elif action == "USUARIOS":
            tg_edit(chat, msg_id, "👥 Usuarios", botones_usuarios())

        elif action == "ADD_USER":
            USER_STATE[chat] = "ADD_USER"
            tg_send(chat, "Envía ID")

        elif action == "DEL_USER":
            USER_STATE[chat] = "DEL_USER"
            tg_send(chat, "Envía ID")

        elif action == "LIST_USERS":
            usuarios = "\n".join(obtener_usuarios())
            tg_edit(chat, msg_id, usuarios if usuarios else "Vacío", botones_usuarios())

        elif action.startswith("ACEPTAR_"):
            sid = action.split("_")[1]
            try:
                url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
                r = homeserve.session.get(url, timeout=15)
                html = r.text.lower()
                errores = ["error", "illegal", "denegado", "caducada", "no autorizado", "acceso inválido"]
                if any(e in html for e in errores):
                    tg_edit(chat, msg_id, f"❌ Error al aceptar servicio {sid}", botones())
                else:
                    tg_edit(chat, msg_id, f"✅ Servicio {sid} aceptado correctamente", botones())
            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error: {e}", botones())

        elif action.startswith("RECHAZAR_"):
            sid = action.split("_")[1]
            homeserve.cambiar_estado(sid, "348")
            tg_edit(chat, msg_id, "❌ Rechazado", botones())

        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "🏠 Menú", botones())

    return jsonify(ok=True)

# =========================================================
# PANEL NUBE RAILWAY (SECURED)
# =========================================================

def comprobar_login():
    auth = request.authorization
    return auth and auth.username == ADMIN_USER and auth.password == ADMIN_PASS

@app.route("/")
def nube():
    if not comprobar_login():
        return ("Acceso denegado", 401, {"WWW-Authenticate": 'Basic realm="Nube Railway"'})

    archivos = os.listdir(DATA_DIR)
    html = """
    <!doctype html>
    <html>
    <head><title>Nube Railway</title>
    <style>body{font-family:Arial;margin:40px;} button{padding:8px;} a{margin:5px;}</style>
    </head>
    <body>
    <h1>☁️ Nube Railway</h1>
    <h3>/data</h3>
    <form action="/subir" method="post" enctype="multipart/form-data">
        <input type="file" name="archivo">
        <button>📥 Subir</button>
    </form>
    <hr>
    {% for archivo in archivos %}
    <p>
    📄 <b>{{archivo}}</b>
    <a href="/descargar/{{archivo}}">⬇ Descargar</a>
    <a href="/eliminar/{{archivo}}" onclick="return confirm('¿Eliminar?')">🗑 Eliminar</a>
    </p>
    {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html, archivos=archivos)

@app.route("/subir", methods=["POST"])
def subir_archivo():
    if not comprobar_login():
        return "No autorizado", 401

    archivo = request.files.get("archivo")
    if archivo and archivo.filename:
        filename = secure_filename(archivo.filename)
        archivo.save(os.path.join(DATA_DIR, filename))

    return 'Archivo subido correctamente<br><a href="/">Volver</a>'

@app.route("/descargar/<nombre>")
def descargar_archivo(nombre):
    if not comprobar_login():
        return "No autorizado", 401
    return send_from_directory(DATA_DIR, secure_filename(nombre), as_attachment=True)

@app.route("/eliminar/<nombre>")
def eliminar_archivo(nombre):
    if not comprobar_login():
        return "No autorizado", 401
      
    filename = secure_filename(nombre)
    if filename == "usuarios.db":
        return '❌ No puedes eliminar usuarios.db<br><a href="/">Volver</a>'

    ruta = os.path.join(DATA_DIR, filename)
    if os.path.exists(ruta):
        os.remove(ruta)

    return '✅ Archivo eliminado<br><a href="/">Volver</a>'

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
