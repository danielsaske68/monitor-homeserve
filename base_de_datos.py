import os
import sqlite3
from datetime import datetime
from config import DB_PATH, DATA_DIR

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

def eliminar_servicio_ruta(chat_id, sid, fecha=None):
    fecha = fecha or datetime.now().date().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM ruta_diaria WHERE chat_id=? AND sid=? AND fecha=?",
            (str(chat_id), str(sid), fecha),
        )
        conn.commit()
    return cursor.rowcount

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

def registrar_seguimiento(sid, estado, fecha_caducidad=None):
    from utils import calcular_fecha_caducidad
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