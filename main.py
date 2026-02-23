# main.py
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Credenciales de HomeServe
USUARIO = "16205"  # reemplaza con tu usuario
CONTRASENA = "Aventura60,"  # reemplaza con tu contraseña

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
ASIGNACION_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"


def obtener_servicios():
    """Función que hace login y obtiene servicios actuales"""
    with requests.Session() as session:
        # Login
        payload = {"usuario": USUARIO, "contrasena": CONTRASENA}
        logging.info("Intentando loguearse en HomeServe...")
        login_response = session.post(LOGIN_URL, data=payload)
        
        if "error" in login_response.text.lower():
            logging.error("Login fallido: revisa usuario y contraseña")
            return {"error": "Login fallido"}

        logging.info("Login exitoso ✅")

        # Obtener página de asignación
        resp = session.get(ASIGNACION_URL)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extraer servicios de 8 dígitos
        servicios = []
        for tag in soup.find_all(text=True):
            text = tag.strip()
            if text.isdigit() and len(text) == 8:
                servicios.append(text)

        logging.info(f"Servicios encontrados: {len(servicios)}")
        return {"servicios": servicios, "cantidad": len(servicios)}


# Endpoints Flask
@app.route("/")
def index():
    return "Monitor HomeServe funcionando 🚀"


@app.route("/test_servicios")
def test_servicios():
    """Endpoint para probar si el login y scraping funcionan"""
    servicios = obtener_servicios()
    return jsonify(servicios)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
