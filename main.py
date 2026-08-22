import os
import re
import requests
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

# Configuración básica / Constantes
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
BASE_URL = "https://reparacionespaez.sistemasici.es/web/index.php"
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

# Diccionario o BD en memoria/local simulada para persistencia simple
SERVICIOS_GUARDADOS = {}


class HomeServeSession:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })


homeserve = HomeServeSession()

# -------------------------------------------------------------------
# Funciones auxiliares para llamadas a la API de Telegram
# -------------------------------------------------------------------

def tg_send(chat_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return requests.post(url, json=payload).json()


def tg_edit(chat_id, message_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return requests.post(url, json=payload).json()


def tg_answer_callback(callback_query_id, text=""):
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return requests.post(url, json=payload)

# -------------------------------------------------------------------
# Generadores de Teclados (Inline Keyboards)
# -------------------------------------------------------------------

def botones_principal():
    return {
        "inline_keyboard": [
            [{"text": "📋 Servicios en Curso", "callback_data": "CURSO"}],
            [{"text": "💾 Mis Servicios Guardados", "callback_data": "VER_GUARDADOS"}]
        ]
    }


def botones_servicio_curso(sid, telefono, texto_servicio=""):
    num_wa = re.sub(r"\D", "", telefono) if telefono else ""
    wa_url = f"https://wa.me/34{num_wa}" if len(num_wa) == 9 else "https://wa.me/"

    gmaps_url = "https://www.google.com/maps"
    waze_url = "https://waze.com"
    if texto_servicio:
        query_mapa = quote_plus(texto_servicio)
        gmaps_url = f"https://www.google.com/maps/search/?api=1&query={query_mapa}"
        waze_url = f"https://waze.com/ul?q={query_mapa}&navigate=yes"

    return {
        "inline_keyboard": [
            [
                {"text": "📍 Google Maps", "url": gmaps_url},
                {"text": "🚙 Waze", "url": waze_url}
            ],
            [
                {"text": "💬 WhatsApp", "url": wa_url},
                {"text": "💾 Guardar Servicio", "callback_data": f"GUARDAR_{sid}"}
            ],
            [
                {"text": "🛠 Cambiar Estado", "callback_data": f"CAMSEL_{sid}"}
            ],
            [
                {"text": "⬅️ Volver", "callback_data": "CURSO"}
            ]
        ]
    }

# -------------------------------------------------------------------
# Gestión de Almacenamiento Local
# -------------------------------------------------------------------

def add_service(chat_id, servicio_info):
    if chat_id not in SERVICIOS_GUARDADOS:
        SERVICIOS_GUARDADOS[chat_id] = []
    if servicio_info not in SERVICIOS_GUARDADOS[chat_id]:
        SERVICIOS_GUARDADOS[chat_id].append(servicio_info)

# -------------------------------------------------------------------
# Procesador principal de eventos/updates
# -------------------------------------------------------------------

def handle_update(update):
    # 1. Manejo de mensajes de texto (/start o menú)
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            tg_send(
                chat_id,
                "👋 <b>Bienvenido al Bot de Gestión de Servicios</b>\n\nSelecciona una opción del menú:",
                botones_principal()
            )
        return

    # 2. Manejo de Callback Queries (Interacciones con botones)
    if "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        chat = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        action = cq.get("data", "")

        tg_answer_callback(cq_id)

        # Volver al menú principal o ver lista en curso
        if action == "CURSO":
            try:
                url = f"{BASE_URL}?w3exec=serviciosencurso"
                r = homeserve.session.get(url, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")

                servicios = []
                # Ajusta las etiquetas según la estructura HTML exacta de la lista
                for a in soup.find_all("a", href=True):
                    if "ver_servicioencurso" in a["href"]:
                        match = re.search(r"Servicio=([^&]+)", a["href"])
                        if match:
                            sid = match.group(1)
                            servicios.append((sid, a.get_text(strip=True) or sid))

                if not servicios:
                    tg_edit(chat, msg_id, "ℹ️ No hay servicios en curso actualmente.", botones_principal())
                    return

                inline_kb = []
                for sid, label in servicios:
                    inline_kb.append([{"text": f"🔧 Servicio {label}", "callback_data": f"SEL_{sid}"}])
                inline_kb.append([{"text": "⬅️ Menú Principal", "callback_data": "MENU_PRINCIPAL"}])

                tg_edit(chat, msg_id, "📋 <b>Servicios en Curso:</b>\nSelecciona uno para ver el detalle:", {"inline_keyboard": inline_kb})

            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error cargando la lista de servicios:\n{e}", botones_principal())

        elif action == "MENU_PRINCIPAL":
            tg_edit(chat, msg_id, "👋 <b>Menú Principal</b>\nSelecciona una opción:", botones_principal())

        # Selección y vista detallada de un Servicio en Curso
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

                numeros = re.findall(r"\b\d{9}\b", telefonos)
                primer_telefono = numeros[0] if numeros else ""

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

                kb = botones_servicio_curso(sid, primer_telefono, direccion_completa)
                tg_edit(chat, msg_id, texto, kb)

            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error obteniendo detalle del servicio:\n{e}", botones_principal())

        # Guardar Servicio
        elif action.startswith("GUARDAR_"):
            sid = action.split("_")[1]
            add_service(chat, f"Servicio: {sid}")
            tg_send(chat, f"✅ Servicio <b>{sid}</b> guardado en tu lista personal.")

        # Ver Lista de Guardados
        elif action == "VER_GUARDADOS":
            guardados = SERVICIOS_GUARDADOS.get(chat, [])
            if not guardados:
                msg_txt = "📂 No tienes ningún servicio guardado."
            else:
                msg_txt = "💾 <b>Tus Servicios Guardados:</b>\n\n" + "\n".join([f"• {s}" for s in guardados])
            
            kb = {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "MENU_PRINCIPAL"}]]}
            tg_edit(chat, msg_id, msg_txt, kb)

        # Cambiar Estado (Placeholder)
        elif action.startswith("CAMSEL_"):
            sid = action.split("_")[1]
            tg_send(chat, f"⚙️ Función para cambiar estado del servicio <b>{sid}</b> en construcción.")


# -------------------------------------------------------------------
# Punto de entrada si usas Flask/Gunicorn (Webhook)
# -------------------------------------------------------------------
if __name__ == "__main__":
    from flask import Flask, request

    app = Flask(__name__)

    @app.route("/", methods=["POST"])
    def webhook():
        if request.method == "POST":
            update = request.get_json(force=True)
            handle_update(update)
            return "OK", 200

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
