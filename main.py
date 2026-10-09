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

# Importar la base de datos de baremos asegurando el nombre correcto
try:
    from baremos import BAREMOS_DATA
except ImportError:
    try:
        from baremos import BAREMOS_DB as BAREMOS_DATA
    except ImportError:
        BAREMOS_DATA = []

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
BAREMO_STATE = {}
CITA_STATE = {}
VIEW_STATE = {}
BUSCAR_STATE = {}
IMPORTAR_STATE = {}
RUTA_FECHA_STATE = {}
AJUSTAR_RUTA_STATE = {}

DATA_DIR = "/data"
DB_PATH = os.path.join(DATA_DIR, "usuarios.db")
os.makedirs(DATA_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def calcular_fecha_caducidad(fecha_estado):
    fecha = fecha_estado.date() + timedelta(days=3)
    while fecha.weekday() >= 5:
        fecha += timedelta(days=1)
    return fecha


def extraer_fecha_caducidad(texto):
    fechas = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto or "")
    if not fechas:
        return None
    try:
        return max(datetime.strptime(f, "%d/%m/%Y").date() for f in fechas)
    except ValueError:
        return None


def siguiente_estado_automatico(estado):
    return "318" if estado in ("348", "320") else estado


def parsear_servicios_texto(texto):
    """Extrae la dirección completa del servicio para exportar/importar rutas.

    La dirección completa incluye código postal y población cuando están presentes.
    La limpieza estricta para Google Maps/Waze sigue viviendo en extraer_direccion_servicio().
    """
    if texto is None:
        return {}

    text = str(texto).replace("\r", " ").replace("\u00a0", " ")

    lineas_directas = {}
    for linea in text.splitlines():
        linea_limpia = linea.strip()
        if not linea_limpia:
            continue
        match = re.match(r"^\s*(\d{7,8})\s*(?:\|\s*|[-–—:]\s*)(.+?)\s*$", linea_limpia)
        if not match:
            continue
        sid = match.group(1)
        valor = match.group(2).strip()
        if not valor:
            continue
        direccion = limpiar_direccion_importada(valor) or extraer_direccion_servicio(valor)
        if direccion and sid not in lineas_directas:
            lineas_directas[sid] = direccion
    if lineas_directas:
        return lineas_directas

    if "<a" in text and "ver_servicioencurso" in text:
        soup = BeautifulSoup(text, "html.parser")
        servicios = {}
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
            if row is not None:
                row_text = row.get_text(" ", strip=True)
            else:
                row_text = " ".join(part.get_text(" ", strip=True) for part in link.parent.find_all() if part.get_text(" ", strip=True)) if getattr(link.parent, "find_all", None) else ""

            if not row_text:
                continue
            row_text = row_text.replace(sid, "", 1).strip(" -:|/")
            direccion = limpiar_direccion_importada(row_text) or extraer_direccion_servicio(row_text)
            if direccion:
                servicios[sid] = direccion

        if servicios:
            return servicios

    matches = list(re.finditer(r"\b\d{7,8}\b", text))
    if not matches:
        return {}

    servicios = {}
    for idx, match in enumerate(matches):
        sid = match.group(0)
        fin = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        bloque = text[match.start():fin]
        bloque = re.sub(r"\s+", " ", bloque).strip()
        direccion = limpiar_direccion_importada(bloque) or extraer_direccion_servicio(bloque)
        if direccion and sid not in servicios:
            servicios[sid] = direccion
    return servicios


def ordenar_ruta_servicios(items):
    """Devuelve los servicios ordenados por zona y horario para una ruta del día."""
    prioridad = {
        "paterna": 0,
        "meliana": 1,
        "rafelbunyol": 2,
        "pobla de farnals": 3,
        "valencia": 4,
    }

    def score(item):
        sid, texto = item
        texto_norm = normalizar_texto(str(texto or ""))
        direccion = extraer_direccion_servicio(texto) or texto_norm
        direccion_norm = normalizar_texto(direccion)
        prior = 99
        for nombre, value in prioridad.items():
            if nombre in texto_norm or nombre in direccion_norm:
                prior = value
                break
        return (prior, direccion_norm, sid)

    return sorted(items, key=score)


def limpiar_direccion(direccion):
    if not direccion:
        return ""
    texto = re.sub(r"\s+", " ", str(direccion)).strip()
    texto = re.sub(r"^(?:\d{6,8}\s+)+", "", texto)
    texto = re.sub(r"^(?:\d{1,2}:\d{2}\s+)+", "", texto)
    texto = re.sub(r"^(?:[A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)\s*\(\d{5}\)\s+", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+VALENCIA\s*\(\d{5}\)\s*$", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^(?:[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]*?\d{2}/\d{2}/\d{4}\s+)", "", texto, flags=re.IGNORECASE)
    texto = texto.strip(" ,;:.-/")
    return texto


def extraer_direccion_servicio(texto):
    if not texto:
        return ""

    txt = str(texto).replace("\r", " ").replace("\n", " ").replace("\u00a0", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", txt):
        return ""

    txt = re.sub(r"^\d{7,8}\s*(?:\|\s*)?", "", txt)
    txt = re.sub(r"^(?:manitas\s+fontanero|fontanero|manitas)\s*", "", txt, flags=re.IGNORECASE)

    if re.fullmatch(r"(?:Libre\s+Para\s+el\s+\d{2}/\d{2}/\d{2,4}\s+De\s+\d{2}:\d{2}\s+a\s+\d{2}:\d{2}(?:\s+VALENCIA\s*\(\d{5}\))?|\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}\s+de\s+\d{2}:\d{2}\s+a\s+\d{2}:\d{2}(?:\s+VALENCIA\s*\(\d{5}\))?|\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s*a\s*\d{2}:\d{2}(?:\s+VALENCIA\s*\(\d{5}\))?)", txt, flags=re.IGNORECASE):
        if not re.search(r"(?i)\b(?:avenida|avda|avd|avinguda|carrer|carrera|cra|carretera|ctra|ctr|c\s*/\s*cl|calle|cl|cr|paseo|plaza|travessia|travesia|ronda|urb|urbanizacion|cami|pza|rua)\b", txt):
            return ""

    palabras_clave = [
        "AVENIDA", "AVDA", "AVD", "AVINGUDA", "CARRER", "CARRERA", "CRA", "CARRETERA",
        "CTRA", "CTR", "C/CL", "C/ CL", "C / CL", "CALLE", "CL", "CR", "PASEO", "PLAZA",
        "TRAVESIA", "TRAVESSIA", "RONDA", "URB", "URBANIZACION", "CAMI", "PZA", "RUA"
    ]

    pos = None
    for kw in palabras_clave:
        pattern = r"(?i)(?<![A-Za-zÁÉÍÓÚÑáéíóúñ])" + re.escape(kw).replace(r"\ ", r"\s*") + r"(?![A-Za-zÁÉÍÓÚÑáéíóúñ])"
        match = re.search(pattern, txt)
        if match:
            pos = match.start() if pos is None else min(pos, match.start())

    if pos is None:
        patrones = [
            r"(?i)\b(?:av(?:inguda)?|avd|avenida|carrer(?:a)?|cra|carretera|ctra|c\s*/\s*cl|calle|cami|paseo|plaza|ronda|trav(?:ess)?ia|pza)\b",
            r"(?i)\bc\s*/\s*cl\b",
            r"(?i)\bc\s+\w+"
        ]
        for pattern in patrones:
            match = re.search(pattern, txt)
            if match:
                pos = match.start() if pos is None else min(pos, match.start())

    if pos is None:
        pos = 0

    base = txt[pos:]

    base = re.sub(r"\s+(?:en\s+espera\s+de\s+profesional|por\s+confirmacion\s+del\s+siniestro|por\s+pendiente\s+de\s+citar\s+al\s+cliente|atasco|averia|avería|informo|se\s+necesita|necesita)\b.*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+\d{2}/\d{2}/\d{4}\s+(?:\d{2}/\d{2}/\d{4}\s+)?(?:de\s+\d{2}:\d{2}\s+a\s+\d{2}:\d{2})?.*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+\d{2}:\d{2}\s*a\s*\d{2}:\d{2}.*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+\d{2}/\d{2}/\d{4}.*$", "", base)
    base = re.sub(r"\s+\d{2}:\d{2}\s*\d{2}:\d{2}.*$", "", base)
    base = re.sub(r"^(?:\d{1,2}:\d{2}\s+)+", "", base)
    base = re.sub(r"^(?:[A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)\s*\(\d{5}\)\s+", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+VALENCIA\s*\(\d{5}\)\s*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+(?:MELIANA|PATERNA|RAFELBUNYOL|VALENCIA|ALBALAT\s+DELS\s+SORELLS|MASAMAGRELL|POBLA\s+DE\s+FARNALS)\s*[-,]?(?:\(?\d{5}\)?)?\s*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+\d{5}-[A-ZÁÉÍÓÚÑ\s\-]+$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+\(\d{5}\)\s*$", "", base)

    direccion = limpiar_direccion(base)
    if direccion and re.search(r"\d", direccion):
        return direccion

    if re.search(r"\d", txt):
        candidato = limpiar_direccion(txt)
        if candidato and re.search(r"\d", candidato) and not re.fullmatch(r".*\d{2}/\d{2}/\d{4}.*", candidato, flags=re.IGNORECASE):
            return candidato
    return ""


def resumen_servicio_alerta(texto):
    direccion = extraer_direccion_servicio(texto)
    texto_limpio = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(texto_limpio) > 300:
        texto_limpio = texto_limpio[:297] + "..."

    if direccion:
        return f"🆕 <b>Nuevo servicio</b>\n📍 <b>Dirección:</b> {direccion}\n📝 <b>Comentario:</b> {texto_limpio}"

    return f"🆕 <b>Nuevo servicio</b>\n📝 <b>Comentario:</b> {texto_limpio}"


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
                ultimo_aviso TIMESTAMP,
                fecha_caducidad TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ruta_diaria (
                chat_id TEXT,
                sid TEXT,
                fecha TEXT,
                direccion TEXT,
                orden INTEGER,
                completado INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, sid, fecha)
            )
        """)
        columnas = [r[1] for r in conn.execute("PRAGMA table_info(seguimiento)").fetchall()]
        if "fecha_caducidad" not in columnas:
            conn.execute("ALTER TABLE seguimiento ADD COLUMN fecha_caducidad TIMESTAMP")
        conn.commit()

def guardar_ruta_diaria(chat_id, sid, direccion, fecha=None, orden=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ruta_diaria (chat_id, sid, fecha, direccion, orden, completado)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(chat_id, sid, fecha) DO UPDATE SET
                direccion=excluded.direccion,
                orden=COALESCE(excluded.orden, ruta_diaria.orden),
                completado=COALESCE(ruta_diaria.completado, 0)
            """,
            (str(chat_id), str(sid), fecha, direccion, orden if orden is not None else 999)
        )
        conn.commit()


def obtener_ruta_diaria(chat_id, fecha=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sid, direccion, orden, completado FROM ruta_diaria WHERE chat_id=? AND fecha=? ORDER BY orden ASC, sid ASC",
            (str(chat_id), fecha),
        ).fetchall()
    return [dict(r) for r in rows]


def limpiar_ruta_dia(chat_id, fecha=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM ruta_diaria WHERE chat_id=? AND fecha=?",
            (str(chat_id), fecha),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


def fecha_ruta_predeterminada():
    return (datetime.now().date() + timedelta(days=1)).isoformat()


def fecha_ruta_activa(chat_id):
    if chat_id not in RUTA_FECHA_STATE or not RUTA_FECHA_STATE[chat_id]:
        RUTA_FECHA_STATE[chat_id] = fecha_ruta_predeterminada()
    return RUTA_FECHA_STATE[chat_id]


def formatear_fecha_ruta(fecha=None):
    if fecha is None:
        fecha = datetime.now().date()
    if isinstance(fecha, str):
        fecha = parsear_fecha_ruta(fecha)
    if fecha is None:
        return "hoy"
    return fecha.strftime("%d/%b").lower()


def etiqueta_fecha_ruta(fecha=None):
    if fecha is None:
        fecha = datetime.now().date()
    if isinstance(fecha, str):
        fecha = parsear_fecha_ruta(fecha)
    hoy = datetime.now().date()
    if fecha == hoy:
        return "Hoy"
    return formatear_fecha_ruta(fecha)


def parsear_fecha_ruta(texto):
    valor = (texto or "").strip()
    if not valor:
        return datetime.now().date() + timedelta(days=1)

    clave = valor.lower()
    if clave in {"hoy", "today", "actual", "current"}:
        return datetime.now().date()
    if clave in {"mañana", "dia siguiente", "día siguiente", "siguiente", "next"}:
        return datetime.now().date() + timedelta(days=1)

    if re.fullmatch(r"\d{1,2}/\d{1,2}", valor):
        try:
            return datetime.strptime(f"{valor}/{datetime.now().year}", "%d/%m/%Y").date()
        except ValueError:
            return datetime.now().date() + timedelta(days=1)

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m", "%d-%m"):
        try:
            return datetime.strptime(valor, fmt).date()
        except ValueError:
            continue

    return datetime.now().date() + timedelta(days=1)


def mover_ruta_fecha(chat_id, fecha_origen, fecha_destino):
    origen = fecha_origen or datetime.now().date().isoformat()
    destino = fecha_destino or origen
    if origen == destino:
        return 0

    rows = obtener_ruta_diaria(chat_id, origen)
    if not rows:
        return 0

    with get_db() as conn:
        conn.execute("DELETE FROM ruta_diaria WHERE chat_id=? AND fecha=?", (str(chat_id), destino))
        for row in rows:
            conn.execute(
                "INSERT INTO ruta_diaria (chat_id, sid, fecha, direccion, orden, completado) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id, sid, fecha) DO UPDATE SET direccion=excluded.direccion, orden=excluded.orden, completado=excluded.completado",
                (str(chat_id), str(row["sid"]), destino, row["direccion"], row["orden"], row.get("completado", 0)),
            )
        conn.commit()
    return len(rows)


def actualizar_fecha_ruta_estado(chat_id, fecha_destino, fecha_origen=None):
    fecha_origen = fecha_origen or RUTA_FECHA_STATE.get(chat_id, datetime.now().date().isoformat())
    fecha_destino = fecha_destino.isoformat() if hasattr(fecha_destino, "isoformat") else str(fecha_destino)

    if fecha_origen == fecha_destino:
        RUTA_FECHA_STATE[chat_id] = fecha_destino
        return {"updated": True, "same_date": True, "moved": 0}

    moved = mover_ruta_fecha(chat_id, fecha_origen, fecha_destino)
    if moved:
        RUTA_FECHA_STATE[chat_id] = fecha_destino
        return {"updated": True, "same_date": False, "moved": moved}

    return {"updated": False, "same_date": False, "moved": 0}


def activar_ruta_diaria(chat_id, sid, fecha=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE ruta_diaria SET completado = 0 WHERE chat_id=? AND sid=? AND fecha=?",
            (str(chat_id), str(sid), fecha),
        )
        conn.commit()


def completar_ruta_diaria(chat_id, sid, fecha=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE ruta_diaria SET completado = 1 WHERE chat_id=? AND sid=? AND fecha=?",
            (str(chat_id), str(sid), fecha),
        )
        conn.commit()


def es_servicio_bloqueado(texto):
    if texto is None:
        return False
    normalizado = normalizar_texto(str(texto)).lower()
    tokens = [
        "candado",
        "bloqueado",
        "servicio bloqueado",
        "en tratamiento por homeserve",
        "tratamiento por homeserve",
    ]
    return any(token in normalizado for token in tokens)


def exportar_ruta_dia(chat_id, fecha=None, refrescar=False):
    fecha = fecha or datetime.now().date().isoformat()
    rows = obtener_ruta_diaria(chat_id, fecha)
    if refrescar or not rows:
        servicios = homeserve.obtener_curso() or {}
        rutas = []
        for sid, texto in servicios.items():
            bloque = re.sub(r"\s+", " ", str(texto or "")).strip()
            if bloque:
                rutas.append((sid, bloque))
        rutas_ordenadas = ordenar_ruta_servicios(rutas)
        with get_db() as conn:
            conn.execute("DELETE FROM ruta_diaria WHERE chat_id=? AND fecha=?", (str(chat_id), fecha))
            conn.commit()
        for idx, (sid, direccion) in enumerate(rutas_ordenadas):
            guardar_ruta_diaria(chat_id, sid, direccion, fecha=fecha, orden=idx)
        rows = obtener_ruta_diaria(chat_id, fecha)

    rows = sorted(rows, key=lambda r: (int(r.get("orden", 999) or 999), str(r.get("sid", ""))))
    lines = []
    for row in rows:
        direccion = limpiar_direccion_importada(row.get("direccion", ""))
        sid = str(row.get("sid", "") or "").strip()
        if not direccion:
            continue
        if sid and sid.upper().startswith("RUTA_"):
            lines.append(direccion)
        elif sid:
            lines.append(f"{sid}|{direccion}")
        else:
            lines.append(direccion)
    return "\n".join(lines)


def limpiar_direccion_importada(texto):
    if texto is None:
        return ""

    texto = str(texto).strip()
    if not texto:
        return ""

    texto = re.sub(r"^\s*\*+\s*", "", texto)
    texto = re.sub(r"^\d{1,2}:\d{2}\s*[-–]\s*", "", texto)
    texto = re.sub(r"^\s*\d{7,8}\s*(?:[-–—:|]\s*)?", "", texto)
    texto = texto.split("|")[-1].strip() if "|" in texto else texto
    texto = re.sub(r"(?i)\b(?:en espera de profesional|por confirmacion del siniestro|siniestro)\b.*$", "", texto)
    texto = re.sub(r"\s+de\s+\d{2}:\d{2}\s+a\s+\d{2}:\d{2}.*$", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}.*$", "", texto)
    texto = re.sub(r"\s+\d{2}/\d{2}/\d{4}.*$", "", texto)
    texto = re.sub(r"\s+\d{2}:\d{2}\s*[-–]?\s*\d{2}:\d{2}.*$", "", texto)
    texto = texto.strip(" \t\n\r-–—.,;:")
    texto = re.sub(r"\s+", " ", texto)

    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", texto):
        return ""
    if re.fullmatch(r"\d{8,}", texto):
        return ""
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", texto):
        return ""
    if re.search(r"\b(?:de|del|por|para|en)\b\s+\d{2}:\d{2}\s+a\s+\d{2}:\d{2}", texto, flags=re.IGNORECASE):
        return ""
    return texto


def importar_ruta_desde_texto(chat_id, texto, fecha=None):
    texto = texto or ""
    fecha = fecha or datetime.now().date().isoformat()

    entradas = []
    patrón = re.compile(r"(?<!\d)(\d{7,8})\s*(?:\|\s*|[-–—:]\s*)(.*?)(?=(?:\s*(?:\d{7,8}\s*(?:\||[-–—:]))|$))", flags=re.DOTALL)
    for match in patrón.finditer(texto):
        sid = match.group(1).strip()
        direccion = match.group(2).strip()
        if sid and direccion:
            entradas.append((sid, direccion))

    if not entradas:
        lineas = [line.strip() for line in texto.splitlines() if line.strip()]
        for idx, linea in enumerate(lineas):
            sid = f"RUTA_{idx + 1:03d}"
            direccion = linea
            match = re.match(r"^\s*(\d{7,8})\s*(?:\|\s*|[-–—:]\s*)(.+?)\s*$", linea)
            if match:
                sid, direccion = match.group(1), match.group(2).strip()
            elif "|" in linea:
                partes = [p.strip() for p in linea.split("|", 1)]
                if len(partes) == 2 and partes[1]:
                    sid, direccion = partes[0] or sid, partes[1]
            elif "\t" in linea:
                partes = [p.strip() for p in linea.split("\t", 1)]
                if len(partes) == 2 and partes[1]:
                    sid, direccion = partes[0] or sid, partes[1]
            entradas.append((sid, direccion))

    if not entradas:
        return 0

    with get_db() as conn:
        conn.execute("DELETE FROM ruta_diaria WHERE chat_id=? AND fecha=?", (str(chat_id), fecha))
        conn.commit()

    count = 0
    for idx, (sid, direccion) in enumerate(entradas):
        direccion = limpiar_direccion_importada(direccion)
        if not direccion:
            continue
        guardar_ruta_diaria(chat_id, sid, direccion, fecha=fecha, orden=idx)
        count += 1

    return count


def generar_ruta_dia(chat_id, servicios=None, refrescar=False):
    today = datetime.now().date().isoformat()
    rows = obtener_ruta_diaria(chat_id, today)

    if refrescar or not rows:
        servicios = servicios or homeserve.obtener_curso() or {}
        rutas = []
        for sid, texto in servicios.items():
            bloque = re.sub(r"\s+", " ", str(texto or "")).strip()
            if bloque:
                rutas.append((sid, bloque))

        rutas_ordenadas = ordenar_ruta_servicios(rutas)
        with get_db() as conn:
            conn.execute("DELETE FROM ruta_diaria WHERE chat_id=? AND fecha=?", (str(chat_id), today))
            conn.commit()
        for i, (sid, direccion) in enumerate(rutas_ordenadas):
            guardar_ruta_diaria(chat_id, sid, direccion, fecha=today, orden=i)
        rows = obtener_ruta_diaria(chat_id, today)

    active_rows = [r for r in rows if not r.get("completado")]
    return sorted(active_rows, key=lambda r: (int(r.get("orden", 999) or 999), str(r.get("sid", ""))))


def validar_orden_ruta(rows):
    """Comprueba que la ruta tiene orden secuencial desde las 09:00."""
    if not rows:
        return {"ok": True, "issues": [], "hora_esperada": []}

    issues = []
    esperadas = []
    for idx, row in enumerate(rows):
        hora = 9 + idx
        esperadas.append(f"{hora:02d}:00")
        orden = int(row.get("orden", idx) or 0)
        if orden != idx:
            issues.append(f"orden[{idx}]={orden} no coincide con la posición esperada {idx}")
        if not str(row.get("direccion", "")).strip():
            issues.append(f"fila[{idx}] sin dirección válida")

    ok = not issues
    return {"ok": ok, "issues": issues, "hora_esperada": esperadas}


def saludo_actual():
    hora_actual = datetime.now().hour
    if 6 <= hora_actual < 12:
        return "buenos días"
    if 12 <= hora_actual < 21:
        return "buenas tardes"
    return "buenas noches"


def formatear_hora_humana(hora_texto):
    try:
        hora_str = str(hora_texto).strip()
        if not hora_str:
            return "9 am"
        hh, mm = hora_str.split(":", 1)
        h = int(hh)
        m = int(mm)
        suffix = "am" if h < 12 else "pm"
        if h == 0:
            h = 12
        elif h > 12:
            h -= 12
        return f"{h}:{m:02d} {suffix}"
    except Exception:
        return str(hora_texto).strip() or "9 am"


def construir_mensaje_cita(direccion, hora_texto, fecha_texto=None):
    direccion = (direccion or "su domicilio").strip()
    hora_texto = str(hora_texto or "9:00").strip()
    fecha_texto = str(fecha_texto or "").strip()
    hora_humana = formatear_hora_humana(hora_texto)
    saludo = saludo_actual()

    if fecha_texto:
        fecha_texto = fecha_texto.strip()
        if fecha_texto.lower() == "hoy":
            fecha_texto = "Hoy"
        elif fecha_texto.lower() == "mañana":
            fecha_texto = "mañana"
        return f"Hola {saludo}, soy el fontanero del seguro. Le hablo por el servicio que tiene en {direccion} para {fecha_texto} a las {hora_humana}."

    fecha_default = etiqueta_fecha_ruta(datetime.now().date() + timedelta(days=1))
    return f"Hola {saludo}, soy el fontanero del seguro. Le hablo por el servicio que tiene en {direccion} para {fecha_default} a las {hora_humana}."


def generar_mensaje_cita_sid(sid, fecha_hora=None):
    try:
        datos, _ = obtener_datos_servicio(sid)
    except Exception:
        return None

    telefonos = datos.get("TELEFONOS", "")
    numeros = re.findall(r"\b\d{9}\b", telefonos)
    if not numeros:
        return None

    telefono = numeros[0]
    direccion = (datos.get("DOMICILIO", "") or "").strip()
    poblacion = (datos.get("POBLACION-PROVINCIA", "") or "").strip()
    ubicacion_str = f"{direccion}, {poblacion}".strip(", ")

    if fecha_hora:
        try:
            dt = datetime.strptime(str(fecha_hora), "%d/%m/%Y %H:%M")
            fecha_fmt = etiqueta_fecha_ruta(dt.date())
            hora_fmt = dt.strftime("%H:%M")
        except ValueError:
            fecha_fmt = etiqueta_fecha_ruta(datetime.now().date() + timedelta(days=1))
            hora_fmt = str(fecha_hora).split()[-1] if " " in str(fecha_hora) else "9:00"
    else:
        fecha_fmt = etiqueta_fecha_ruta(datetime.now().date() + timedelta(days=1))
        hora_fmt = "09:00"

    mensaje = construir_mensaje_cita(ubicacion_str, hora_fmt, fecha_fmt)
    return telefono, mensaje


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

def registrar_seguimiento(sid, estado, fecha_caducidad=None):
    with get_db() as conn:
        ahora = datetime.now()
        fecha_cad = fecha_caducidad or calcular_fecha_caducidad(ahora)
        conn.execute("""
            INSERT INTO seguimiento (sid, estado, fecha_cambio, ultimo_aviso, fecha_caducidad)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sid) DO UPDATE SET
                estado=excluded.estado,
                fecha_cambio=excluded.fecha_cambio,
                ultimo_aviso=excluded.ultimo_aviso,
                fecha_caducidad=excluded.fecha_caducidad
        """, (sid, estado, ahora, ahora, fecha_cad))
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

# =========================================================
# BOTONES
# =========================================================

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


def botones_todos_estados():
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 Todos: cliente", "callback_data": "TODOS_348"},
                {"text": "🟢 Todos: confirmación", "callback_data": "TODOS_318"}
            ],
            [
                {"text": "🟠 Todos: otro gremio", "callback_data": "TODOS_320"}
            ],
            [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
        ]
    }


def botones_num_serv():    return {
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

def direccion_para_mapa(texto_servicio="", domicilio="", poblacion=""):
    if texto_servicio:
        direccion = extraer_direccion_servicio(texto_servicio)
        if direccion:
            return re.sub(r"[\[\]\*\/\,\.]+", " ", direccion).strip()

    base = f"{domicilio}, {poblacion}".strip(", ")
    if not base:
        return ""

    direccion = extraer_direccion_servicio(base)
    if direccion:
        return re.sub(r"[\[\]\*\/\,\.]+", " ", direccion).strip()

    dir_limpia = re.sub(r"[\[\]\*\/\,\.]+", " ", base)
    dir_limpia = re.sub(r"\s+", " ", dir_limpia).strip()
    return dir_limpia


def botones_servicio(sid, texto_servicio=""):
    gmaps_url = "https://www.google.com/maps"
    waze_url = "https://waze.com"

    direccion = direccion_para_mapa(texto_servicio)
    if direccion:
        query_mapa = quote_plus(direccion)
        gmaps_url = f"https://www.google.com/maps/search/?api=1&query={query_mapa}"
        waze_url = f"https://waze.com/ul?q={query_mapa}&navigate=yes"

    return {
        "inline_keyboard": [
            [{"text": "📍 Google Maps", "url": gmaps_url}, {"text": "🚙 Waze", "url": waze_url}],
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


def normalizar_texto(texto):
    if not texto:
        return ""
    mapa = {
        "á": "a", "à": "a", "ä": "a", "â": "a",
        "é": "e", "è": "e", "ë": "e", "ê": "e",
        "í": "i", "ì": "i", "ï": "i", "î": "i",
        "ó": "o", "ò": "o", "ö": "o", "ô": "o",
        "ú": "u", "ù": "u", "ü": "u", "û": "u",
        "ñ": "n", "ç": "c",
    }
    txt = "".join(mapa.get(ch, ch) for ch in str(texto).lower())
    txt = txt.replace("\n", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def obtener_datos_servicio(sid):
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
    return datos, r.text


def mostrar_servicio(chat, msg_id, sid):
    try:
        datos, raw_html = obtener_datos_servicio(sid)

        servicio = datos.get("SERVICIO", sid)
        cliente = datos.get("CLIENTE", "")
        telefonos = datos.get("TELEFONOS", "")
        domicilio = datos.get("DOMICILIO", "")
        poblacion = datos.get("POBLACION-PROVINCIA", "")
        comentarios = datos.get("COMENTARIOS", "")
        comentarios = "\n".join(comentarios.splitlines()[:5])
        caducidad = extraer_fecha_caducidad(raw_html)
        str_caducidad = caducidad.strftime("%d/%m/%Y") if caducidad else "No disponible"

        direccion_completa = direccion_para_mapa(domicilio=domicilio, poblacion=poblacion)
        query_mapa = quote_plus(direccion_completa) if direccion_completa else quote_plus(f"{domicilio}, {poblacion}".strip(", "))
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
            f"📍 <b>POBLACIÓN:</b> {poblacion}\n"
            f"📅 <b>CADUCIDAD:</b> {str_caducidad}\n\n"
            f"📝 <b>COMENTARIOS:</b>\n{comentarios}"
        )

        curso = homeserve.obtener_curso()
        ordered = list(curso.keys())
        if sid in ordered:
            idx = ordered.index(sid)
            prev_sid = ordered[idx - 1] if idx > 0 else ordered[-1]
            next_sid = ordered[(idx + 1) % len(ordered)]
        else:
            prev_sid = sid
            next_sid = sid

        inline_kb = [
            [{"text": "📍 Google Maps", "url": gmaps_url}, {"text": "🚙 Waze", "url": waze_url}],
            [{"text": "💬 Cita WhatsApp", "callback_data": f"CITAWAP_{sid}"}, {"text": "💾 Guardar servicio", "callback_data": f"GUARDARSERV_{sid}"}],
            [{"text": "🛠 Cambiar Estado", "callback_data": f"CAMSEL_{sid}"}],
            [{"text": "", "callback_data": f"NAV_{prev_sid}_prev"}, {"text": "", "callback_data": f"NAV_{next_sid}_next"}],
            [{"text": "⬅️ Volver", "callback_data": "CURSO"}]
        ]
        inline_kb[3][0]["text"] = f"⬅️ {prev_sid}"
        inline_kb[3][1]["text"] = f"{next_sid} ➡️"

        tg_edit(chat, msg_id, texto, {"inline_keyboard": inline_kb})
    except Exception as e:
        tg_edit(chat, msg_id, f"❌ Error obteniendo servicio:\n{e}", botones())

def formato_lista_servicio(sid, texto=""):
    fecha = extraer_fecha_caducidad(texto)
    if fecha:
        return f"👁 {sid} | Cad. {fecha.strftime('%d/%m/%Y')}"
    return f"👁 {sid}"


def formato_lista_cambio(sid, texto=""):
    fecha = extraer_fecha_caducidad(texto)
    if fecha:
        return f"🛠 {sid} | Cad. {fecha.strftime('%d/%m/%Y')}"
    return f"🛠 {sid}"


def lista_curso(servicios):
    botones_lista = [
        [{"text": formato_lista_servicio(sid, texto), "callback_data": f"SEL_{sid}"}]
        for sid, texto in servicios.items()
    ]
    botones_lista.append([{"text": "🔎 Buscar servicio", "callback_data": "BUSCAR_SERV"}])
    botones_lista.append([{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}])
    return {"inline_keyboard": botones_lista}


def lista_cambio(servicios):
    botones_lista = [
        [{"text": formato_lista_cambio(sid, texto), "callback_data": f"CAMSEL_{sid}"}]
        for sid, texto in servicios.items()
    ]
    botones_lista.append([
        {"text": "🔁 Cambiar automáticos", "callback_data": "AUTO_TODOS"},
        {"text": "🛠 Cambiar todos", "callback_data": "CAMBIAR_TODOS"}
    ])
    botones_lista.append([{"text": "🔎 Buscar servicio", "callback_data": "BUSCAR_SERV"}])
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
            fecha_caducidad = calcular_fecha_caducidad(datetime.now())

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
            registrar_seguimiento(sid, estado, fecha_caducidad)
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
                    mensaje_nuevo = resumen_servicio_alerta(txt)
                    for u in obtener_usuarios():
                        tg_send(u, mensaje_nuevo, botones_servicio(sid, txt))
            
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
        msg_id = data["message"].get("message_id")

        guardar_usuario(chat)

        if text == "/start":
            tg_send(chat, "🤖 Bot activo", botones())
            return jsonify(ok=True)

        if chat in CITA_STATE:
            state_info = CITA_STATE[chat]
            msg_id = state_info["msg_id"]
            telefono = state_info["telefono"]
            base_msg = state_info["base_msg"]
            
            mensaje_final = f"{base_msg} para {text}."
            whatsapp_url = f"https://wa.me/34{telefono}?text={quote_plus(mensaje_final)}"
            
            kb = {
                "inline_keyboard": [
                    [{"text": "💬 Enviar por WhatsApp", "url": whatsapp_url}],
                    [{"text": "⬅️ Volver al servicio", "callback_data": f"SEL_{state_info['sid']}"}]
                ]
            }
            CITA_STATE.pop(chat)
            tg_send(chat, f"✅ Mensaje preparado:\n\n<code>{mensaje_final}</code>", kb)
            return jsonify(ok=True)

        if chat in BAREMO_STATE:
            state_info = BAREMO_STATE[chat]
            msg_id = state_info["msg_id"]
            
            busqueda = text.lower().strip()
            resultados = []
            
            for item in BAREMOS_DATA:
                codigo, nombre, precio = item
                texto_item = f"{codigo} {nombre}".lower()
                
                if any(p in texto_item for p in busqueda.split()):
                    resultados.append({
                        "codigo": codigo,
                        "nombre": nombre,
                        "precio": precio
                    })
            
            if not resultados:
                respuesta = f"❌ No se han encontrado resultados para: <b>{text}</b>.\n\nEscribe otra palabra clave para seguir buscando:"
            else:
                respuesta = f"🔍 <b>Resultados para:</b> {text}\n\n"
                for res in resultados[:10]:
                    c = res["codigo"]
                    n = res["nombre"]
                    p = res["precio"]
                    respuesta += f"<code>{c}</code>\n{n}\n<b>{p}</b>\n\n"
                
                if len(resultados) > 10:
                    respuesta += f"<i>(Mostrando 10 de {len(resultados)} coincidencias...)</i>\n"
            
            kb = {
                "inline_keyboard": [
                    [{"text": "🔍 Buscar otro", "callback_data": "SEARCH_BAREMO"}],
                    [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
                ]
            }
            
            tg_edit(chat, msg_id, respuesta, kb)
            return jsonify(ok=True)

        # Búsqueda por servicio: teléfono o dirección
        if chat in BUSCAR_STATE:
            state_info = BUSCAR_STATE.pop(chat)
            msg_id = state_info.get("msg_id") or msg_id
            query = text.strip()
            if not query:
                tg_edit(chat, msg_id, "❌ Escribe un número o parte de la dirección para buscar.", botones())
                return jsonify(ok=True)

            qnorm = normalizar_texto(query)
            digits = re.sub(r"\D", "", query)
            matches = []
            servicios = homeserve.obtener_curso()

            for sid, texto in servicios.items():
                hay_coincidencia = False
                valores_total = texto
                try:
                    datos, _ = obtener_datos_servicio(sid)
                    valores_total = " ".join(str(v) for v in datos.values()) + " " + texto
                    cliente = normalizar_texto(datos.get("CLIENTE", ""))
                    domicilio = normalizar_texto(datos.get("DOMICILIO", ""))
                    telefonos = normalizar_texto(datos.get("TELEFONOS", ""))
                    poblacion = normalizar_texto(datos.get("POBLACION-PROVINCIA", ""))
                    valores_extra = " ".join(filter(None, [cliente, domicilio, telefonos, poblacion]))
                    valores_total = f"{valores_extra} {texto}"
                except Exception:
                    pass

                if qnorm and qnorm in normalizar_texto(valores_total):
                    hay_coincidencia = True
                if digits and digits in re.sub(r"\D", "", valores_total):
                    hay_coincidencia = True

                if hay_coincidencia:
                    matches.append((sid, texto))

            if not matches:
                tg_edit(chat, msg_id, f"❌ No se encontraron servicios para: <b>{query}</b>", botones())
                return jsonify(ok=True)
            if len(matches) == 1:
                mostrar_servicio(chat, msg_id, matches[0][0])
                return jsonify(ok=True)

            texto = f"🔎 <b>Resultados para:</b> {query}\n\n"
            kb = {"inline_keyboard": []}
            for sid, texto_serv in matches[:30]:
                label = formato_lista_servicio(sid, texto_serv)
                kb["inline_keyboard"].append([{"text": label, "callback_data": f"SEL_{sid}"}])
            kb["inline_keyboard"].append([{"text": "⬅️ Volver", "callback_data": "CURSO"}])
            tg_edit(chat, msg_id, texto, kb)
            return jsonify(ok=True)

        if chat in IMPORTAR_STATE:
            state_info = IMPORTAR_STATE.pop(chat)
            msg_edit = state_info["msg_id"]
            count = importar_ruta_desde_texto(chat, text)
            if count:
                RUTA_FECHA_STATE[chat] = fecha_ruta_predeterminada()
                tg_edit(chat, msg_edit, f"✅ Ruta importada correctamente ({count} servicios)", {"inline_keyboard": [[{"text": "🧭 Ver ruta", "callback_data": "RUTA_DEL_DIA"}]]})
            else:
                tg_edit(chat, msg_edit, "❌ No se pudieron leer direcciones válidas. Reenvía una lista con una dirección por línea.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})
            tg_delete_message(chat, msg_id)
            return jsonify(ok=True)

        if chat in AJUSTAR_RUTA_STATE:
            state_info = AJUSTAR_RUTA_STATE.pop(chat)
            fecha_obj = parsear_fecha_ruta(text)
            fecha_origen = fecha_ruta_activa(chat)
            if not fecha_obj:
                tg_edit(chat, state_info["msg_id"], "❌ Fecha no válida. Ejemplos: 15/10, 15/10/2026 o 'mañana'.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})
                tg_delete_message(chat, msg_id)
                return jsonify(ok=True)

            fecha_destino = fecha_obj.isoformat()
            fecha_label = etiqueta_fecha_ruta(fecha_obj)
            resultado = actualizar_fecha_ruta_estado(chat, fecha_destino, fecha_origen)
            if resultado["updated"]:
                tg_edit(chat, state_info["msg_id"], f"✅ Ruta ajustada para {fecha_label}. La hora se mantiene por defecto del sistema.", {"inline_keyboard": [[{"text": "🧭 Ver ruta", "callback_data": "RUTA_DEL_DIA"}]]})
            else:
                tg_edit(chat, state_info["msg_id"], "❌ No hay servicios para ajustar en esta ruta.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})
            tg_delete_message(chat, msg_id)
            return jsonify(ok=True)

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
                total = len(servicios)
                for idx, (sid, txt) in enumerate(servicios.items(), start=1):
                    resumen = f"🆕 <b>Servicio {idx}/{total}</b>\n\n{resumen_servicio_alerta(txt)}"
                    tg_edit(chat, msg_id, resumen, botones_servicio(sid, txt))

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

        elif action == "CAMBIAR_TODOS":
            tg_edit(chat, msg_id, "🛠 Selecciona estado para todos los servicios", botones_todos_estados())

        elif action == "BUSCAR_SERV":
            BUSCAR_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id, "🔎 Escribe número de teléfono o parte de la dirección para buscar el servicio:\n\n(Escribe por ejemplo: 961234567 o AVENIDA DE LA CRUZ)", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "CURSO"}]]})

        elif action == "AUTO_TODOS":
            servicios = homeserve.obtener_curso()
            if not servicios:
                tg_edit(chat, msg_id, "❌ No hay servicios en curso", botones())
                return jsonify(ok=True)

            today = datetime.now().date()
            changed = 0
            skipped_not_due = 0
            skipped_no_seguimiento = 0
            no_change_needed = 0
            errors = 0
            changed_no_seguimiento = 0
            failed_no_seguimiento = 0

            with get_db() as conn:
                for sid, texto in servicios.items():
                    fecha_web = extraer_fecha_caducidad(texto)
                    if not fecha_web or fecha_web > today:
                        skipped_not_due += 1
                        continue

                    row = conn.execute("SELECT sid, estado FROM seguimiento WHERE sid=?", (sid,)).fetchone()
                    if row:
                        estado_actual = row["estado"]
                        nuevo_estado = siguiente_estado_automatico(estado_actual)
                        if nuevo_estado == estado_actual:
                            no_change_needed += 1
                            continue

                        ok, _ = homeserve.cambiar_estado(sid, nuevo_estado)
                        if ok:
                            changed += 1
                        else:
                            errors += 1
                    else:
                        # No seguimiento: intentar cambiar a estado por defecto (318)
                        skipped_no_seguimiento += 1
                        default_target = "318"
                        ok, _ = homeserve.cambiar_estado(sid, default_target)
                        if ok:
                            changed_no_seguimiento += 1
                        else:
                            failed_no_seguimiento += 1

            parts = [f"✅ Actualizados (con seguimiento): {changed}"]
            parts.append(f"✅ Actualizados (sin seguimiento): {changed_no_seguimiento}")
            parts.append(f"❎ No caducados/pendientes: {skipped_not_due}")
            parts.append(f"🟡 Sin seguimiento (intentados): {skipped_no_seguimiento}")
            parts.append(f"ℹ️ Ya en siguiente estado: {no_change_needed}")
            if failed_no_seguimiento:
                parts.append(f"⚠️ Fallos al cambiar sin seguimiento: {failed_no_seguimiento}")
            if errors:
                parts.append(f"⚠️ Errores: {errors}")

            tg_edit(chat, msg_id, "\n".join(parts), botones())

        elif action.startswith("TODOS_"):
            estado = action.split("_", 1)[1]
            servicios = homeserve.obtener_curso()
            if not servicios:
                tg_edit(chat, msg_id, "❌ No hay servicios en curso", botones())
                return jsonify(ok=True)

            ok_count = 0
            for sid in servicios:
                ok, _ = homeserve.cambiar_estado(sid, estado)
                if ok:
                    ok_count += 1

            tg_edit(chat, msg_id, f"✅ Cambiados {ok_count}/{len(servicios)} servicios al estado {estado}", botones())

        elif action.startswith("CAMSEL_"):
            sid = action.split("_")[1]
            tg_edit(chat, msg_id, f"🛠 <b>Cambiar estado del servicio</b>\n\n<b>{sid}</b>", botones_estado(sid))

        elif action.startswith("SEL_"):
            sid = action.split("_")[1]
            mostrar_servicio(chat, msg_id, sid)

        elif action.startswith("NAV_"):
            parts = action.split("_")
            if len(parts) >= 3:
                sid = parts[1]
                direction = parts[2]
                curso = homeserve.obtener_curso()
                ordered = list(curso.keys())
                if sid not in ordered:
                    tg_edit(chat, msg_id, "❌ No se encontró el servicio en la lista actual.", botones())
                else:
                    idx = ordered.index(sid)
                    if direction == "next":
                        new_idx = (idx + 1) % len(ordered)
                    else:
                        new_idx = (idx - 1) % len(ordered)
                    new_sid = ordered[new_idx]
                    mostrar_servicio(chat, msg_id, new_sid)
            else:
                tg_edit(chat, msg_id, "❌ Acción de navegación inválida", botones())

        elif action.startswith("GUARDARSERV_"):
            sid = action.split("_")[1]
            try:
                add_service(chat, sid)
                
                url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
                r = homeserve.session.get(url, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")
                datos = {}
                for tr in soup.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) >= 2:
                        datos[tds[0].get_text(" ", strip=True).replace(":", "").upper()] = tds[1].get_text(" ", strip=True)

                domicilio = datos.get("DOMICILIO", "")
                poblacion = datos.get("POBLACION-PROVINCIA", "")
                direccion_completa = direccion_para_mapa(domicilio=domicilio, poblacion=poblacion)
                query_mapa = quote_plus(direccion_completa) if direccion_completa else quote_plus(f"{domicilio}, {poblacion}".strip(", "))
                gmaps_url = f"https://www.google.com/maps/search/?api=1&query={query_mapa}"
                waze_url = f"https://waze.com/ul?q={query_mapa}&navigate=yes"

                updated_kb = {
                    "inline_keyboard": [
                        [{"text": "📍 Google Maps", "url": gmaps_url}, {"text": "🚙 Waze", "url": waze_url}],
                        [{"text": "💬 Cita WhatsApp", "callback_data": f"CITAWAP_{sid}"}, {"text": "✅ Guardado con éxito", "callback_data": "NOOP"}],
                        [{"text": "🛠 Cambiar Estado", "callback_data": f"CAMSEL_{sid}"}],
                        [{"text": "⬅️ Volver", "callback_data": "CURSO"}]
                    ]
                }
                
                payload = {
                    "chat_id": chat,
                    "message_id": msg_id,
                    "reply_markup": updated_kb
                }
                tg_session.post(f"{TELEGRAM_API}/editMessageReplyMarkup", json=payload, timeout=5)

            except Exception as e:
                logger.error(f"Error al guardar servicio: {e}")

        elif action.startswith("CITAWAP_"):
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

                telefonos = datos.get("TELEFONOS", "")
                domicilio = datos.get("DOMICILIO", "")
                poblacion = datos.get("POBLACION-PROVINCIA", "")

                numeros = re.findall(r"\b\d{9}\b", telefonos)
                if not numeros:
                    tg_edit(chat, msg_id, "❌ No se encontró un número de teléfono válido para este servicio.", botones())
                    return jsonify(ok=True)
                
                primer_telefono = numeros[0]

                hora_actual = datetime.now().hour
                if 6 <= hora_actual < 12:
                    saludo = "días"
                elif 12 <= hora_actual < 21:
                    saludo = "tardes"
                else:
                    saludo = "noches"

                dir_limpia = domicilio.strip() if domicilio else "su domicilio"
                pob_limpia = poblacion.strip() if poblacion else ""
                ubicacion_str = f"en {dir_limpia}, {pob_limpia}".strip(", ")

                base_mensaje = f"Hola buenas {saludo}, soy el fontanero del seguro. Le llamo por el servicio que tiene {ubicacion_str}"

                kb = {
                    "inline_keyboard": [
                        [{"text": "✅ Sí, agregar fecha y hora", "callback_data": f"CITA_YES_{sid}_{primer_telefono}"}],
                        [{"text": "❌ Enviar sin fecha", "callback_data": f"CITA_NO_{sid}_{primer_telefono}"}],
                        [{"text": "⬅️ Volver", "callback_data": f"SEL_{sid}"}]
                    ]
                }
                tg_edit(chat, msg_id, f"💬 <b>Gestión de Cita WhatsApp</b>\n\nMensaje base:\n<i>{base_mensaje}</i>\n\n¿Deseas agregar fecha y hora para la cita?", kb)
            except Exception as e:
                tg_edit(chat, msg_id, f"❌ Error al preparar mensaje de WhatsApp:\n{e}", botones())

        elif action.startswith("CITA_NO_"):
            parts = action.split("_")
            sid = parts[2]
            telefono = parts[3]
            
            hora_actual = datetime.now().hour
            saludo = "días" if 6 <= hora_actual < 12 else ("tardes" if 12 <= hora_actual < 21 else "noches")
            
            url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
            r = homeserve.session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            datos = {}
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    datos[tds[0].get_text(" ", strip=True).replace(":", "").upper()] = tds[1].get_text(" ", strip=True)

            dir_limpia = datos.get("DOMICILIO", "").strip()
            pob_limpia = datos.get("POBLACION-PROVINCIA", "").strip()
            ubicacion_str = f"en {dir_limpia}, {pob_limpia}".strip(", ")

            mensaje_final = f"Hola buenas {saludo}, soy el fontanero del seguro. Le llamo por el servicio que tiene {ubicacion_str}."
            whatsapp_url = f"https://wa.me/34{telefono}?text={quote_plus(mensaje_final)}"

            kb = {
                "inline_keyboard": [
                    [{"text": "💬 Enviar por WhatsApp", "url": whatsapp_url}],
                    [{"text": "⬅️ Volver al servicio", "callback_data": f"SEL_{sid}"}]
                ]
            }
            tg_edit(chat, msg_id, f"✅ Mensaje preparado:\n\n<code>{mensaje_final}</code>", kb)

        elif action.startswith("CITA_YES_"):
            parts = action.split("_")
            sid = parts[2]
            telefono = parts[3]
            
            hora_actual = datetime.now().hour
            saludo = "días" if 6 <= hora_actual < 12 else ("tardes" if 12 <= hora_actual < 21 else "noches")
            
            url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
            r = homeserve.session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            datos = {}
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    datos[tds[0].get_text(" ", strip=True).replace(":", "").upper()] = tds[1].get_text(" ", strip=True)

            dir_limpia = datos.get("DOMICILIO", "").strip()
            pob_limpia = datos.get("POBLACION-PROVINCIA", "").strip()
            ubicacion_str = f"en {dir_limpia}, {pob_limpia}".strip(", ")

            base_msg = f"Hola buenas {saludo}, soy el fontanero del seguro. Le llamo por el servicio que tiene {ubicacion_str}"

            CITA_STATE[chat] = {
                "msg_id": msg_id,
                "sid": sid,
                "telefono": telefono,
                "base_msg": base_msg
            }
            tg_edit(chat, msg_id, "✍️ Escribe a continuación la fecha y hora de la cita (ej. <i>mañana a las 10:00</i> o <i>el martes 25 a las 16:30</i>):", {"inline_keyboard": [[{"text": "⬅️ Cancelar", "callback_data": f"SEL_{sid}"}]]})

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

        elif action == "SEARCH_BAREMO":
            BAREMO_STATE[chat] = {"msg_id": msg_id}
            texto_busqueda = (
                "🔍 <b>BÚSQUEDA DE BAREMOS</b>\n\n"
                "Escribe a continuación la palabra o frase que deseas buscar (ej. <i>latiguillo</i>, <i>sustitucion</i>):"
            )
            keyboard_busqueda = {
                "inline_keyboard": [
                    [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
                ]
            }
            tg_edit(chat, msg_id, texto_busqueda, keyboard_busqueda)

        elif action == "RUTA_DEL_DIA":
            fecha_actual = fecha_ruta_activa(chat)
            rows = [r for r in obtener_ruta_diaria(chat, fecha_actual) if not r.get("completado")]
            fecha_label = etiqueta_fecha_ruta(fecha_actual)

            if not rows:
                tg_edit(
                    chat,
                    msg_id,
                    f"🧭 <b>Ruta del día</b>\n📅 <b>{fecha_label}</b>\n\nPulsa <b>Exportar</b> para sacar los servicios activos de la web y luego importa la lista ordenada.",
                    {"inline_keyboard": [
                        [{"text": "📤 Exportar", "callback_data": "EXPORTAR_RUTA"}, {"text": "📥 Importar", "callback_data": "IMPORTAR_RUTA"}],
                        [{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]
                    ]}
                )
                return jsonify(ok=True)

            texto = f"🧭 <b>Ruta del día</b>\n📅 <b>{fecha_label}</b>"
            kb = {"inline_keyboard": []}
            for idx, row in enumerate(rows[:20], start=1):
                orden = int(row.get("orden", idx - 1) or 0)
                hora = 9 + orden
                tiempo = f"{hora:02d}:00"
                kb["inline_keyboard"].append([
                    {"text": f"📞 {tiempo}", "callback_data": f"RUTA_CITAR_{row['sid']}"},
                    {"text": "✅ Hecho", "callback_data": f"RUTA_CHECK_{row['sid']}"}
                ])
            kb["inline_keyboard"].append([
                {"text": "📅 Ajustar", "callback_data": "AJUSTAR_RUTA"},
                {"text": "🧹 Limpiar ruta", "callback_data": "LIMPIAR_RUTA"}
            ])
            kb["inline_keyboard"].append([
                {"text": "⬅️ Volver", "callback_data": "BACK_MENU"}
            ])
            tg_edit(chat, msg_id, texto, kb)

        elif action == "LIMPIAR_RUTA":
            fecha_actual = fecha_ruta_activa(chat)
            deleted = limpiar_ruta_dia(chat, fecha_actual)
            RUTA_FECHA_STATE[chat] = fecha_ruta_predeterminada()
            tg_edit(chat, msg_id, f"🧹 Ruta del día borrada. {deleted} servicios eliminados.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "BACK_MENU"}]]})

        elif action == "AJUSTAR_RUTA":
            AJUSTAR_RUTA_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id, "📅 Ajusta la fecha de la ruta.\n\nPuedes escribir: <code>15/10</code>, <code>15/10/2026</code>, <code>hoy</code> o <code>mañana</code>\n\nLa hora se mantiene por defecto según el sistema.", {
                "inline_keyboard": [
                    [{"text": "📅 Hoy", "callback_data": "AJUSTAR_RUTA_HOY"}, {"text": "📅 Mañana", "callback_data": "AJUSTAR_RUTA_MANANA"}],
                    [{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]
                ]
            })

        elif action == "AJUSTAR_RUTA_HOY":
            fecha_origen = fecha_ruta_activa(chat)
            fecha_obj = datetime.now().date()
            fecha_destino = fecha_obj.isoformat()
            resultado = actualizar_fecha_ruta_estado(chat, fecha_destino, fecha_origen)
            if resultado["updated"]:
                tg_edit(chat, msg_id, f"✅ Ruta ajustada para {etiqueta_fecha_ruta(fecha_obj)}. La hora se mantiene por defecto del sistema.", {"inline_keyboard": [[{"text": "🧭 Ver ruta", "callback_data": "RUTA_DEL_DIA"}]]})
            else:
                tg_edit(chat, msg_id, "❌ No hay servicios para ajustar en esta ruta.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

        elif action == "AJUSTAR_RUTA_MANANA":
            fecha_origen = fecha_ruta_activa(chat)
            fecha_obj = datetime.now().date() + timedelta(days=1)
            fecha_destino = fecha_obj.isoformat()
            resultado = actualizar_fecha_ruta_estado(chat, fecha_destino, fecha_origen)
            if resultado["updated"]:
                tg_edit(chat, msg_id, f"✅ Ruta ajustada para {etiqueta_fecha_ruta(fecha_obj)}. La hora se mantiene por defecto del sistema.", {"inline_keyboard": [[{"text": "🧭 Ver ruta", "callback_data": "RUTA_DEL_DIA"}]]})
            else:
                tg_edit(chat, msg_id, "❌ No hay servicios para ajustar en esta ruta.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

        elif action == "EXPORTAR_RUTA":
            servicios = homeserve.obtener_curso() or {}
            rutas = []
            for sid, texto in servicios.items():
                bloque = re.sub(r"\s+", " ", str(texto or "")).strip()
                if bloque:
                    rutas.append((sid, bloque))
            rutas_ordenadas = ordenar_ruta_servicios(rutas)
            texto = "\n".join(f"{sid}|{direccion}" for sid, direccion in rutas_ordenadas)
            if not texto:
                tg_edit(chat, msg_id, "❌ No hay direcciones para exportar.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})
                return jsonify(ok=True)
            tg_edit(chat, msg_id, f"📤 <b>Direcciones exportadas</b>\n\n<code>{texto}</code>", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

        elif action == "IMPORTAR_RUTA":
            IMPORTAR_STATE[chat] = {"msg_id": msg_id}
            tg_edit(chat, msg_id, "📥 Envíame la lista ordenada de direcciones para importarla a la ruta del día.\n\nRegla: una dirección por línea y sin texto extra.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

        elif action.startswith("RUTA_CITAR_"):
            sid = action.split("_")[-1]
            fecha_actual = fecha_ruta_activa(chat)
            fecha_ruta = datetime.strptime(fecha_actual, "%Y-%m-%d").date()
            with get_db() as conn:
                row = conn.execute(
                    "SELECT orden FROM ruta_diaria WHERE chat_id=? AND sid=? AND fecha=?",
                    (str(chat), str(sid), fecha_actual),
                ).fetchone()

            orden = int((row["orden"] if row else 0) or 0)
            hora_orden = 9 + orden
            fecha_hora = f"{fecha_ruta.strftime('%d/%m/%Y')} {hora_orden:02d}:00"

            info = generar_mensaje_cita_sid(sid, fecha_hora)
            if not info:
                tg_edit(chat, msg_id, f"❌ No se pudo preparar la cita para {sid}.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})
                return jsonify(ok=True)

            telefono, mensaje_final = info
            whatsapp_url = f"https://wa.me/34{telefono}?text={quote_plus(mensaje_final)}"
            kb = {
                "inline_keyboard": [
                    [{"text": "💬 Enviar por WhatsApp", "url": whatsapp_url}],
                    [{"text": "⬅️ Volver a ruta", "callback_data": "RUTA_DEL_DIA"}]
                ]
            }
            tg_edit(chat, msg_id, f"📞 <b>Cita lista</b>\n\n<code>{mensaje_final}</code>", kb)

        elif action.startswith("RUTA_CHECK_"):
            sid = action.split("_")[-1]
            fecha_actual = fecha_ruta_activa(chat)
            completar_ruta_diaria(chat, sid, fecha=fecha_actual)
            tg_edit(chat, msg_id, f"✅ Servicio {sid} marcado como completado en la ruta del día.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

        elif action.startswith("RUTA_REACT_"):
            sid = action.split("_")[-1]
            fecha_actual = fecha_ruta_activa(chat)
            activar_ruta_diaria(chat, sid, fecha=fecha_actual)
            tg_edit(chat, msg_id, f"🔄 Servicio {sid} reactivado para la ruta del día.", {"inline_keyboard": [[{"text": "⬅️ Volver", "callback_data": "RUTA_DEL_DIA"}]]})

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
            BAREMO_STATE.pop(chat, None)
            CITA_STATE.pop(chat, None)
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
    <p><button>📤 Exportar</button> <button>📥 Importar</button></p>
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
