#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import json
import logging
import sys

# ===== VARIABLES DE ENTORNO =====
USUARIO = os.getenv('USUARIO', '16205')
CONTRASEÑA = os.getenv('CONTRASEÑA', 'Aventura60,')
TOKEN_TELEGRAM = os.getenv('TOKEN_TELEGRAM', '')
CHAT_ID = os.getenv('CHAT_ID', '')
INTERVALO_SEGUNDOS = int(os.getenv('INTERVALO_SEGUNDOS', '120'))

URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"
ARCHIVO_SERVICIOS = "servicios_alertados.json"

# ===== LOGGING =====
class UTF8LogHandler(logging.FileHandler):
    def __init__(self, filename):
        super().__init__(filename, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        UTF8LogHandler('monitor_homeserve.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ===== CLASE MONITOR =====
class MonitorHomeServe:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.servicios_alertados = self.cargar_servicios_alertados()
    
    def cargar_servicios_alertados(self):
        if os.path.exists(ARCHIVO_SERVICIOS):
            try:
                with open(ARCHIVO_SERVICIOS, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                logger.warning("No se pudo cargar archivo de servicios")
                return {}
        return {}
    
    def guardar_servicios_alertados(self):
        try:
            with open(ARCHIVO_SERVICIOS, 'w', encoding='utf-8') as f:
                json.dump(self.servicios_alertados, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error al guardar servicios: {e}")
    
    def login(self):
        try:
            logger.info("[INICIO] Intentando login en HomeServe...")
            response = self.session.get(URL_LOGIN, timeout=10)
            payload = {'CODIGO': USUARIO, 'PASSW': CONTRASEÑA, 'ACEPT': 'Aceptar'}
            response = self.session.post(URL_LOGIN, data=payload, timeout=10, allow_redirects=True)
            indicadores_exito = ['prof_asignacion','logout','cerrar sesion','bienvenido','dashboard','panel']
            login_exitoso = any(indicator in response.text.lower() for indicator in indicadores_exito)
            if login_exitoso:
                logger.info("[EXITO] Login realizado correctamente!")
            else:
                logger.error("[FALLO] Login fallido")
            return login_exitoso
        except requests.RequestException as e:
            logger.error(f"[ERROR] Error en login: {e}")
            return False
    
    def obtener_servicios(self):
        try:
            response = self.session.get(URL_SERVICIOS, timeout=10)
            if response.status_code != 200:
                return {}
            soup = BeautifulSoup(response.text, 'html.parser')
            servicios = {}
            for fila in soup.find_all('tr'):
                celdas = fila.find_all('td')
                if len(celdas) >= 3:
                    numero = celdas[0].get_text(strip=True)
                    tipo = celdas[1].get_text(strip=True)
                    estado = celdas[2].get_text(strip=True)
                    if numero.replace('.', '').replace(',', '').isdigit() and len(numero) >= 6:
                        servicios[numero] = {'tipo': tipo, 'estado': estado, 'fecha_detectado': datetime.now().isoformat()}
            return servicios
        except requests.RequestException as e:
            logger.error(f"[ERROR] Error al obtener servicios: {e}")
            return {}
    
    def enviar_alerta_telegram(self, numero, tipo, estado):
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
            mensaje = f"NUEVO SERVICIO DISPONIBLE\nNumero: {numero}\nTipo: {tipo}\nEstado: {estado}\nHora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            payload = {'chat_id': CHAT_ID, 'text': mensaje}
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[TELEGRAM] Excepcion: {e}")
            return False
    
    def procesar_servicios(self, servicios_nuevos):
        alertas = 0
        for numero, datos in servicios_nuevos.items():
            if numero not in self.servicios_alertados:
                if self.enviar_alerta_telegram(numero, datos['tipo'], datos['estado']):
                    self.servicios_alertados[numero] = datos
                    self.guardar_servicios_alertados()
                    alertas += 1
                    time.sleep(1)
        return alertas
    
    def ejecutar(self):
        logger.info("=" * 60)
        logger.info("INICIANDO MONITOR HOMESERVE")
        logger.info(f"Intervalo: {INTERVALO_SEGUNDOS} segundos")
        logger.info("=" * 60)
        if not self.login():
            logger.error("No se pudo hacer login. Abortando...")
            return
        intento_reconexion = 0
        while True:
            try:
                servicios = self.obtener_servicios()
                if servicios:
                    alertas = self.procesar_servicios(servicios)
                    if alertas > 0:
                        logger.info(f"Nuevos servicios alertados: {alertas}")
                    intento_reconexion = 0
                else:
                    if not self.login():
                        intento_reconexion += 1
                        if intento_reconexion > 3:
                            logger.error("Demasiados intentos. Abortando...")
                            break
                time.sleep(INTERVALO_SEGUNDOS)
            except KeyboardInterrupt:
                logger.info("Monitoreo detenido por usuario")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(INTERVALO_SEGUNDOS)

# ===== ENTRY POINT =====
if __name__ == "__main__":
    monitor = MonitorHomeServe()
    monitor.ejecutar()
