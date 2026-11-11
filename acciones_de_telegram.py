import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from config import TELEGRAM_API, logger, BASE_URL
from utils import extraer_fecha_caducidad, extraer_direccion_servicio

tg_session = requests.Session()

def tg_send(chat, text, markup=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    try:
        res = tg_session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        data = res.json()
        if data.get("ok"):
            return data["result"]["message_id"]
    except Exception as e:
        logger.error(f"Error tg_send: {e}")
    return None

def tg_edit(chat, msg_id, text, markup=None):
    payload = {"chat_id": chat, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    try:
        tg_session.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error tg_edit: {e}")

def tg_delete_message(chat, msg_id):
    if msg_id is None:
        return
    try:
        tg_session.post(f"{TELEGRAM_API}/deleteMessage", json={"chat_id": chat, "message_id": msg_id}, timeout=5)
    except Exception as e:
        logger.error(f"Error tg_delete_message: {e}")

def tg_answer(callback_id):
    try:
        tg_session.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
    except Exception as e:
        logger.error(f"Error tg_answer: {e}")

def obtener_datos_servicio(sid, homeserve_inst):
    url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
    r = homeserve_inst.session.get(url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    datos = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            clave = tds[0].get_text(" ", strip=True).replace(":", "").upper()
            valor = tds[1].get_text(" ", strip=True)
            datos[clave] = valor
    return datos, r.text

def direccion_para_mapa(texto_servicio="", domicilio="", poblacion=""):
    if texto_servicio:
        direccion = extraer_direccion_servicio(texto_servicio)
        if direccion:
            return re.sub(r"[\[\]\*\/\,\.]+", " ", direccion).strip()
    base = f"{domicilio}, {poblacion}".strip(", ")
    return re.sub(r"\s+", " ", base).strip()

def botones():
    return {
        "inline_keyboard": [
            [{"text": "🔐 Login", "callback_data": "LOGIN"}, {"text": "🧭 Ruta del día", "callback_data": "RUTA_DEL_DIA"}],
            [{"text": "🌐 Web", "callback_data": "WEB"}, {"text": "👥 Usuarios", "callback_data": "USUARIOS"}],
            [{"text": "🛠 Cambiar estado", "callback_data": "CAMBIAR"}],
            [{"text": "📋 Servicios en curso", "callback_data": "CURSO"}, {"text": "📦 Número de servicios", "callback_data": "NUM_SERV"}],
            [{"text": "🔍 Buscar Baremo", "callback_data": "SEARCH_BAREMO"}]
        ]
    }