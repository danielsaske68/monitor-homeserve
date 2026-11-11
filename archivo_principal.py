import os
import time
import threading
import re
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename

from config import ADMIN_USER, ADMIN_PASS, DATA_DIR, SERVICIOS_CURSO_URL, logger
from database import (init_db, guardar_usuario, obtener_usuarios, eliminar_usuario, 
                      guardar_ruta_diaria, obtener_ruta_diaria, limpiar_ruta_dia, 
                      eliminar_servicio_ruta, completar_ruta_diaria, activar_ruta_diaria)
from utils import (parsear_fecha_ruta, formatear_fecha_ruta, etiqueta_fecha_ruta, 
                   extraer_fecha_caducidad, normalizar_texto, extraer_numeros_telefono, 
                   limpiar_direccion_importada, construir_mensaje_cita)
from homeserve_client import homeserve
from bot_actions import (tg_send, tg_edit, tg_delete_message, tg_answer, 
                         obtener_datos_servicio, direccion_para_mapa, botones)

app = Flask(__name__)
init_db()

SERVICIOS_ACTUALES = {}
USER_STATE = {}
SERV_STATE = {}
BAREMO_STATE = {}
BUSCAR_STATE = {}
IMPORTAR_STATE = {}
RUTA_FECHA_STATE = {}
AJUSTAR_RUTA_STATE = {}
WHATSAPP_TEL_STATE = {}

BAREMOS_DATA = []
try:
    from baremos import BAREMOS_DATA
except ImportError:
    try:
        from baremos import BAREMOS_DB as BAREMOS_DATA
    except ImportError:
        pass

def parsear_servicios_texto(texto):
    if texto is None:
        return {}
    text = str(texto).replace("\r", " ").replace("\u00a0", " ")
    servicios = {}
    if "<a" in text or "<td" in text:
        soup = BeautifulSoup(text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "ver_servicioencurso" not in href or "Servicio=" not in href:
                continue
            match_sid = re.search(r"Servicio=(\d{7,8})", href)
            if not match_sid:
                continue
            sid = match_sid.group(1)
            if sid in servicios:
                continue
            row = link.find_parent("tr")
            if not row:
                continue
            cols = row.find_all("td")
            if len(cols) >= 3:
                profesion = cols[1].get_text(strip=True)
                direccion_cruda = cols[2].get_text(strip=True)
                row_text = f"{profesion} {direccion_cruda}"
                direccion = limpiar_direccion_importada(row_text) or extraer_direccion_servicio(row_text) or direccion_cruda
                servicios[sid] = direccion
    return servicios

def ordenar_ruta_servicios(items):
    prioridad = {"paterna": 0, "meliana": 1, "rafelbunyol": 2, "pobla de farnals": 3, "valencia": 4}
    def score(item):
        sid, texto = item
        texto_norm = normalizar_texto(str(texto or ""))
        prior = 99
        for nombre, value in prioridad.items():
            if nombre in texto_norm:
                prior = value
                break
        return (prior, texto_norm, sid)
    return sorted(items, key=score)

def resumen_servicio_alerta(texto):
    direccion = extraer_direccion_servicio(texto)
    texto_limpio = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(texto_limpio) > 300:
        texto_limpio = texto_limpio[:297] + "..."
    if direccion:
        return f"🆕 <b>Nuevo servicio</b>\n📍 <b>Dirección:</b> {direccion}\n📝 <b>Comentario:</b> {texto_limpio}"
    return f"🆕 <b>Nuevo servicio</b>\n📝 <b>Comentario:</b> {texto_limpio}"

def loop():
    global SERVICIOS_ACTUALES
    homeserve.login()
    while True:
        try:
            actuales = homeserve.obtener()
            for sid, txt in actuales.items():
                if sid not in SERVICIOS_ACTUALES:
                    mensaje_nuevo = resumen_servicio_alerta(txt)
                    for u in obtener_usuarios():
                        tg_send(u, mensaje_nuevo, botones())
            SERVICIOS_ACTUALES = actuales
            time.sleep(40)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            homeserve.login()
            time.sleep(10)

threading.Thread(target=loop, daemon=True).start()

@app.route("/telegram_webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    if "message" in data:
        chat = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        msg_id = data["message"].get("message_id")
        guardar_usuario(chat)
        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())
            return jsonify(ok=True)
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
        elif action == "BACK_MENU":
            tg_edit(chat, msg_id, "🏠 Menú", botones())
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)