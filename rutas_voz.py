from flask import request, jsonify

def registrar_rutas_voz(app, homeserve, tg_send, obtener_usuarios):
    """
    Aquí vamos a meter todas las rutas que escuchan a Google Assistant.
    Recibimos 'app', 'homeserve', 'tg_send' y 'obtener_usuarios' desde el main.py
    para poder usarlas sin problemas.
    """

    # 1. Ruta para consultar servicios en curso
    @app.route("/api/google/curso", methods=["GET", "POST"])
    def google_curso():
        try:
            curso = homeserve.obtener_curso()
            if not curso:
                return jsonify({"speech": "No tienes ningún servicio en curso en este momento."})
            
            total = len(curso)
            # Cogemos solo los primeros 5 para que Google no se tire 10 minutos hablando si hay muchos
            ids = ", ".join(list(curso.keys())[:5])
            
            mensaje = f"Tienes {total} servicios en curso. Los números son: {ids}."
            return jsonify({"speech": mensaje})
            
        except Exception as e:
            return jsonify({"speech": f"Hubo un error al consultar: {e}"})

    # 2. Ruta para iniciar sesión
    @app.route("/api/google/login", methods=["GET", "POST"])
    def google_login():
        ok = homeserve.login()
        texto = "Inicio de sesión en HomeServe realizado con éxito." if ok else "Error al iniciar sesión en HomeServe."
        return jsonify({"speech": texto})
        
    # (Más adelante añadiremos aquí las de cambiar estado, web, etc.)
