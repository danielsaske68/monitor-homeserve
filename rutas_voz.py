import os
from flask import request, jsonify
from bs4 import BeautifulSoup

BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"

def file_path(chat):
    return f"/data/servicios_{chat}.txt"

def read_services(chat):
    try:
        with open(file_path(chat), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def add_service(chat, text):
    with open(file_path(chat), "a", encoding="utf-8") as f:
        f.write(text + "\n")

def clear_services(chat):
    open(file_path(chat), "w").close()


def registrar_rutas_voz(app, homeserve, tg_send, obtener_usuarios):

    # =========================================================
    # 1. SERVICIOS EN CURSO
    # =========================================================
    @app.route("/api/google/curso", methods=["GET", "POST"])
    def google_curso():
        try:
            curso = homeserve.obtener_curso()
            if not curso:
                return jsonify({"speech": "No tienes ningún servicio en curso en este momento."})
            
            total = len(curso)
            ids = ", ".join(list(curso.keys())[:5])
            mensaje = f"Tienes {total} servicios en curso. Los primeros son: {ids}."
            return jsonify({"speech": mensaje})
        except Exception as e:
            return jsonify({"speech": f"Error al consultar servicios en curso: {e}"})

    # =========================================================
    # 2. LOGIN
    # =========================================================
    @app.route("/api/google/login", methods=["GET", "POST"])
    def google_login():
        ok = homeserve.login()
        texto = "Inicio de sesión en HomeServe realizado con éxito." if ok else "Error al iniciar sesión en HomeServe."
        return jsonify({"speech": texto})
        
    # =========================================================
    # 3. VER SERVICIOS NUEVOS (WEB / ASIGNACIONES)
    # =========================================================
    @app.route("/api/google/web", methods=["GET", "POST"])
    def google_web():
        servicios = homeserve.obtener()
        if not servicios:
            return jsonify({"speech": "No hay ningún nuevo servicio asignado en la web."})
        
        total = len(servicios)
        ids = ", ".join(list(servicios.keys())[:5])
        return jsonify({"speech": f"Tienes {total} servicios nuevos asignados. Los códigos son: {ids}."})

    # =========================================================
    # 4. DETALLES COMPLETOS DE UN SERVICIO (Cliente, Teléfono, Comentarios...)
    # =========================================================
    @app.route("/api/google/detalle", methods=["POST"])
    def google_detalle_servicio():
        data = request.json or {}
        sid = data.get("servicio_id")
        
        if not sid:
            return jsonify({"speech": "Por favor, especifica el número de servicio."})

        try:
            url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
            r = homeserve.session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            
            datos = {}
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    clave = tds[0].get_text(" ", strip=True).replace(":", "")
                    valor = tds[1].get_text(" ", strip=True)
                    datos[clave] = valor
                    
            cliente = datos.get("CLIENTE", "Desconocido")
            domicilio = datos.get("DOMICILIO", "Desconocido")
            poblacion = datos.get("POBLACION-PROVINCIA", "")
            telefonos = datos.get("TELEFONOS", "Sin teléfono")
            comentarios = datos.get("COMENTARIOS", "Sin comentarios")
            
            # Formatear respuesta de voz concisa pero completa
            respuesta = (
                f"Servicio {sid}. Cliente: {cliente}. "
                f"Dirección: {domicilio}, {poblacion}. "
                f"Teléfono: {telefonos}. "
                f"Notas: {comentarios[:100]}."
            )
            return jsonify({"speech": respuesta})
            
        except Exception as e:
            return jsonify({"speech": f"Error al consultar el detalle del servicio {sid}."})

    # =========================================================
    # 5. ACEPTAR UN SERVICIO
    # =========================================================
    @app.route("/api/google/aceptar", methods=["POST"])
    def google_aceptar():
        data = request.json or {}
        sid = data.get("servicio_id")
        
        if not sid:
            return jsonify({"speech": "Falta el número de servicio."})
            
        try:
            url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
            r = homeserve.session.get(url, timeout=15)
            html = r.text.lower()

            errores = ["error", "illegal", "denegado", "caducada", "no autorizado", "acceso inválido"]
            fallo = any(e in html for e in errores)

            if fallo:
                msg = f"No se pudo aceptar el servicio {sid} debido a un error en el portal."
            else:
                msg = f"Servicio {sid} aceptado correctamente."
                # Notificación por Telegram a todos los usuarios
                for u in obtener_usuarios():
                    tg_send(u, f"🎙️ <b>Voz:</b> Servicio {sid} aceptado.")
                    
            return jsonify({"speech": msg})
        except Exception as e:
            return jsonify({"speech": f"Error de conexión al aceptar el servicio {sid}."})

    # =========================================================
    # 6. RECHAZAR UN SERVICIO (NUEVA FUNCIÓN)
    # =========================================================
    @app.route("/api/google/rechazar", methods=["POST"])
    def google_rechazar():
        data = request.json or {}
        sid = data.get("servicio_id")
        
        if not sid:
            return jsonify({"speech": "Falta el número de servicio a rechazar."})

        # Rechazar aplica el estado 348 por defecto
        ok, msg_estado = homeserve.cambiar_estado(sid, "348")
        
        if ok:
            msg = f"El servicio {sid} ha sido rechazado y cambiado a estado cliente."
            for u in obtener_usuarios():
                tg_send(u, f"🎙️ <b>Voz:</b> Servicio {sid} rechazado (Estado 348).")
        else:
            msg = f"Error al rechazar el servicio {sid}."

        return jsonify({"speech": msg})

    # =========================================================
    # 7. CAMBIAR ESTADO (348 Cliente / 318 Confirmación)
    # =========================================================
    @app.route("/api/google/cambiar_estado", methods=["POST"])
    def google_cambiar_estado():
        data = request.json or {}
        sid = data.get("servicio_id")
        estado = str(data.get("estado", "348")) # 348 o 318

        if not sid:
            return jsonify({"speech": "Falta el número de servicio."})

        ok, msg = homeserve.cambiar_estado(sid, estado)
        
        texto_estado = "348 Pendiente Cliente" if estado == "348" else "318 Confirmación Siniestro"
        
        if ok:
            respuesta_voz = f"Estado del servicio {sid} cambiado a {texto_estado}."
            for u in obtener_usuarios():
                tg_send(u, f"🎙️ <b>Voz:</b> {msg}")
        else:
            respuesta_voz = f"No se pudo cambiar el estado del servicio {sid}."

        return jsonify({"speech": respuesta_voz})

    # =========================================================
    # 8. GESTIÓN DE NOTAS DE SERVICIOS GUARDADAS (NUEVA FUNCIÓN)
    # =========================================================
    @app.route("/api/google/notas_servicios", methods=["GET", "POST"])
    def google_notas_servicios():
        data = request.json or {}
        chat_id = data.get("chat_id")
        accion = data.get("accion", "ver") # 'ver', 'agregar', 'limpiar'
        texto = data.get("texto", "")

        if not chat_id:
            # Si no viene chat_id, usamos el primer usuario registrado en la DB
            usuarios = obtener_usuarios()
            chat_id = usuarios[0] if usuarios else None

        if not chat_id:
            return jsonify({"speech": "No hay ningún usuario registrado para consultar las notas."})

        if accion == "ver":
            contenido = read_services(chat_id)
            if not contenido:
                return jsonify({"speech": "No tienes notas ni servicios guardados en la lista."})
            return jsonify({"speech": f"Tus servicios guardados son: {contenido}"})

        elif accion == "agregar" and texto:
            add_service(chat_id, texto)
            return jsonify({"speech": f"Guardado correctamente: {texto}"})

        elif accion == "limpiar":
            clear_services(chat_id)
            return jsonify({"speech": "Se ha borrado la lista de servicios guardados."})

        return jsonify({"speech": "Acción no válida sobre las notas."})
