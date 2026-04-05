import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

USUARIO = os.getenv("USUARIO")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
SERVICIOS_EN_CURSO_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=lista_servicios_total"

# ---------------- LOGIN ----------------
session = requests.Session()

payload = {
    "CODIGO": USUARIO,
    "PASSW": PASSWORD,
    "BTN": "Aceptar"
}

session.get(LOGIN_URL)
r = session.post(LOGIN_URL, data=payload)

if "error" in r.text.lower():
    print("Login falló")
    exit()
else:
    print("Login OK")

# ---------------- OBTENER SERVICIOS ----------------
r = session.get(SERVICIOS_EN_CURSO_URL)
soup = BeautifulSoup(r.text, "html.parser")

# Encontrar todos los servicios por ID (7-8 dígitos)
servicios = []
for tag in soup.find_all(text=True):
    if tag.strip().isdigit() and (7 <= len(tag.strip()) <= 8):
        servicios.append(tag.strip())

print(f"Servicios encontrados: {servicios}")

# ---------------- INSPECCIONAR BOTONES DE CADA SERVICIO ----------------
for servicio_id in servicios:
    print(f"\n--- Servicio {servicio_id} ---")
    # Aquí asumimos que hay una URL de detalle por servicio (ajusta si es diferente)
    detalle_url = f"https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=detalle_servicio&id={servicio_id}"
    r_detalle = session.get(detalle_url)
    soup_detalle = BeautifulSoup(r_detalle.text, "html.parser")

    # Buscar todos los botones y enlaces
    botones = soup_detalle.find_all(["a", "button", "input"])
    for b in botones:
        texto = b.get_text(strip=True) if b.name != "input" else b.get("value", "")
        if texto:
            print(f"Botón / enlace: {texto}")

    # Si hay un botón llamado "Cambio de estado", entrar a su href (si es <a>)
    cambio_estado = soup_detalle.find("a", string=lambda x: x and "Cambio de estado" in x)
    if cambio_estado:
        href = cambio_estado.get("href")
        if href:
            print(f"\nEntrando a Cambio de estado de {servicio_id} ({href})")
            r_estado = session.get(href)
            soup_estado = BeautifulSoup(r_estado.text, "html.parser")
            print("Contenido de la página de Cambio de Estado:")
            print(soup_estado.get_text("\n")[:500])  # Mostrar solo los primeros 500 caracteres
