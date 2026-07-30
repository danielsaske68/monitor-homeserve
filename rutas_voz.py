from flask import request, jsonify
from bs4 import BeautifulSoup

BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe"

def registrar_rutas_voz(app, homeserve, tg_send, obtener_usuarios):

    # 1. SERVICIOS EN CURSO
    @app.route("/api/google/curso", methods=["GET", "POST"])
    def google_curso():
        try:
            curso = homeserve.obtener_curso()
            if not curso:
                return jsonify({"speech": "No tienes ningún servicio en curso en este momento."})
            
            total = len(curso)
            ids = ", ".join(list(curso.keys())[:5])
            mensaje = f"Tienes {total} servicios en curso. Los números son: {ids}."
            return jsonify({"speech": mensaje})
        except Exception as e:
            return jsonify({"speech": f"Hubo un error al consultar: {e}"})

    # 2. LOGIN
    @app.route("/api/google/login", methods=["GET", "POST"])
    def google_login():
        ok = homeserve.login()
        texto = "Inicio de sesión en HomeServe realizado con éxito." if ok else "Error al iniciar sesión en HomeServe."
        return jsonify({"speech": texto})
        
    # 3. VER SERVICIOS NUEVOS (WEB)
    @app.route("/api/google/web", methods=["GET", "POST"])
    def google_web():
        servicios = homeserve.obtener()
        if not servicios:
            return jsonify({"speech": "No hay ningún nuevo servicio asignado en la web."})
        
        total = len(servicios)
        ids = ", ".join(list(servicios.keys())[:5])
        return jsonify({"speech": f"Tienes {total} servicios nuevos asignados. Los códigos son: {ids}."})

    # 4. VER DETALLES DE UN SERVICIO
    @app.route("/api/google/detalle", methods=["POST"])
    def google_detalle_servicio():
        data = request.json or {}
        sid = data.get("servicio_id")
        
        if not sid:
            return jsonify({"speech": "Por favor, dime el número de servicio."})

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
            
            respuesta = f"El servicio {sid} pertenece a {cliente}, en la dirección {domicilio}."
            return jsonify({"speech": respuesta})
            
        except Exception as e:
            return jsonify({"speech": f"Error al consultar el detalle del servicio {sid}."})

    # 5. ACEPTAR UN SERVICIO
    @app.route("/api/google/aceptar", methods=["POST"])
    def google_aceptar():
        data = request.json or {}
        sid = data.get("servicio_id")
        
        if not sid:
            return jsonify({"speech": "Falta el número de servicio."})
            
        url = f"{BASE_URL}?w3exec=prof_asignacion&servicio={sid}"
        r = homeserve.session.get(url, timeout=15)
        
        if "error" in r.text.lower():
            msg = f"Hubo un error al intentar aceptar el servicio {sid}."
        else:
            msg = f"Servicio {sid} aceptado correctamente."
            # Avisamos por Telegram a todos los usuarios
            for u in obtener_usuarios():
                tg_send(u, f"🎙️ <b>Voz:</b> Servicio {sid} aceptado.")
                
        return jsonify({"speech": msg})

    # 6. CAMBIAR ESTADO
    @app.route("/api/google/cambiar_estado", methods=["POST"])
    def google_cambiar_estado():
        data = request.json or {}
        sid = data.get("servicio_id")
        estado = data.get("estado", "348") # Ponemos 348 por defecto si no lo dice

        if not sid:
            return jsonify({"speech": "Falta el número de servicio."})

        ok, msg = homeserve.cambiar_estado(sid, estado)
        
        # Avisamos por Telegram a todos los usuarios
        for u in obtener_usuarios():
            tg_send(u, f"🎙️ <b>Voz:</b> {msg}")

        return jsonify({"speech": msg})
