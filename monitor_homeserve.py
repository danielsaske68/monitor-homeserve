import os
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import json
import logging
import sys

# Leer variables de entorno
USUARIO = os.getenv('USUARIO', '16205')
CONTRASEÑA = os.getenv('CONTRASEÑA', 'Aventura60,')
TOKEN_TELEGRAM = os.getenv('TOKEN_TELEGRAM', '')
CHAT_ID = os.getenv('CHAT_ID', '')
INTERVALO_SEGUNDOS = 120

# URLs
URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

ARCHIVO_SERVICIOS = "servicios_alertados.json"

# ============ LOGGING ============
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

# ============ FUNCIONES ============

class MonitorHomeServe:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.servicios_alertados = self.cargar_servicios_alertados()
    
    def cargar_servicios_alertados(self):
        """Carga los servicios ya alertados desde archivo JSON"""
        if os.path.exists(ARCHIVO_SERVICIOS):
            try:
                with open(ARCHIVO_SERVICIOS, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                logger.warning("No se pudo cargar archivo de servicios")
                return {}
        return {}
    
    def guardar_servicios_alertados(self):
        """Guarda los servicios alertados en archivo JSON"""
        try:
            with open(ARCHIVO_SERVICIOS, 'w', encoding='utf-8') as f:
                json.dump(self.servicios_alertados, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error al guardar servicios: {e}")
    
    def login(self):
        """Realiza el login en HomeServe"""
        try:
            logger.info("[INICIO] Intentando login en HomeServe...")
            
            response = self.session.get(URL_LOGIN, timeout=10)
            logger.info(f"[LOGIN] GET inicial - Status: {response.status_code}")
            
            payload = {
                'CODIGO': USUARIO,
                'PASSW': CONTRASEÑA,
                'ACEPT': 'Aceptar'
            }
            
            logger.info(f"[LOGIN] Enviando login con CODIGO={USUARIO}...")
            response = self.session.post(
                URL_LOGIN,
                data=payload,
                timeout=10,
                allow_redirects=True
            )
            
            logger.info(f"[LOGIN] POST - Status: {response.status_code}")
            
            indicadores_exito = [
                'prof_asignacion',
                'logout',
                'Cerrar sesion',
                'SALIR',
                'bienvenido',
                'dashboard',
                'panel'
            ]
            
            login_exitoso = any(indicator in response.text.lower() for indicator in indicadores_exito)
            
            if not login_exitoso:
                logger.info("[LOGIN] Verificando login intentando acceder a servicios...")
                response_servicios = self.session.get(URL_SERVICIOS, timeout=10)
                
                if response_servicios.status_code == 200:
                    if 'prof_asignacion' in response_servicios.text.lower():
                        logger.info("[EXITO] Login exitoso!")
                        login_exitoso = True
            
            if login_exitoso:
                logger.info("[EXITO] Login realizado correctamente!")
                return True
            else:
                logger.error("[FALLO] Login fallido")
                return False
                
        except requests.RequestException as e:
            logger.error(f"[ERROR] Error en login: {e}")
            return False
    
    def obtener_servicios(self):
        """Obtiene los servicios nuevos de la página"""
        try:
            logger.info("[SERVICIOS] Obteniendo servicios nuevos...")
            response = self.session.get(URL_SERVICIOS, timeout=10)
            logger.info(f"[SERVICIOS] Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"[SERVICIOS] Error en la solicitud: {response.status_code}")
                return {}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            servicios = {}
            
            filas = soup.find_all('tr')
            logger.info(f"[SERVICIOS] Total de filas encontradas: {len(filas)}")
            
            for i, fila in enumerate(filas):
                celdas = fila.find_all('td')
                if len(celdas) >= 3:
                    try:
                        numero = celdas[0].get_text(strip=True)
                        tipo = celdas[1].get_text(strip=True)
                        estado = celdas[2].get_text(strip=True)
                        
                        if numero.replace('.', '').replace(',', '').isdigit() and len(numero) >= 6:
                            servicios[numero] = {
                                'tipo': tipo,
                                'estado': estado,
                                'fecha_detectado': datetime.now().isoformat()
                            }
                            logger.info(f"[SERVICIOS] Encontrado: {numero} | {tipo} | {estado}")
                    except Exception as e:
                        logger.debug(f"[SERVICIOS] Error fila {i}: {e}")
            
            logger.info(f"[SERVICIOS] Total encontrados: {len(servicios)}")
            return servicios
            
        except requests.RequestException as e:
            logger.error(f"[ERROR] Error al obtener servicios: {e}")
            return {}
    
    def enviar_alerta_telegram(self, numero, tipo, estado):
        """Envía alerta por Telegram"""
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
            
            mensaje = f"""NUEVO SERVICIO DISPONIBLE

Numero: {numero}
Tipo: {tipo}
Estado: {estado}
Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"""
            
            payload = {
                'chat_id': CHAT_ID,
                'text': mensaje
            }
            
            logger.info(f"[TELEGRAM] Enviando alerta para servicio {numero}...")
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"[TELEGRAM] Alerta enviada exitosamente para {numero}")
                return True
            else:
                logger.error(f"[TELEGRAM] Error HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"[TELEGRAM] Excepcion: {e}")
            return False
    
    def procesar_servicios(self, servicios_nuevos):
        """Procesa servicios y alerta sobre los nuevos"""
        servicios_alertados = 0
        
        for numero, datos in servicios_nuevos.items():
            if numero not in self.servicios_alertados:
                logger.info(f"[NUEVO] Servicio detectado: {numero}")
                
                if self.enviar_alerta_telegram(numero, datos['tipo'], datos['estado']):
                    self.servicios_alertados[numero] = datos
                    self.guardar_servicios_alertados()
                    servicios_alertados += 1
                    time.sleep(1)
        
        return servicios_alertados
    
    def ejecutar(self):
        """Loop principal de monitoreo"""
        logger.info("=" * 60)
        logger.info("INICIANDO MONITOR HOMESERVE")
        logger.info(f"Intervalo de monitoreo: {INTERVALO_SEGUNDOS} segundos")
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
                    logger.warning("Sin servicios. Reconectando...")
                    if not self.login():
                        intento_reconexion += 1
                        if intento_reconexion > 3:
                            logger.error("Demasiados intentos. Abortando...")
                            break
                
                logger.info(f"Proximo chequeo en {INTERVALO_SEGUNDOS} segundos...")
                time.sleep(INTERVALO_SEGUNDOS)
                
            except KeyboardInterrupt:
                logger.info("Monitoreo detenido por usuario")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(INTERVALO_SEGUNDOS)

# ============ MAIN ============
if __name__ == "__main__":
    monitor = MonitorHomeServe()
    monitor.ejecutar()
