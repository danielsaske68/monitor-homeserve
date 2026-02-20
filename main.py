import os
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import logging
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Leer variables de entorno
USUARIO = os.getenv('USUARIO', '16205')
CONTRASEÑA = os.getenv('CONTRASEÑA', 'Aventura60,')
TOKEN_TELEGRAM = os.getenv('TOKEN_TELEGRAM', '')
CHAT_ID = os.getenv('CHAT_ID', '')
INTERVALO_SEGUNDOS = int(os.getenv('INTERVALO_SEGUNDOS', '120'))

# Variables de base de datos
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME', 'postgres')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT', '5432')

# URLs
URL_LOGIN = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=PROF_PASS&utm_source=homeserve.es&utm_medium=referral&utm_campaign=homeserve_footer&utm_content=profesionales"
URL_SERVICIOS = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=prof_asignacion"

# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ============ BASE DE DATOS ============

class BaseDatos:
    def __init__(self):
        try:
            self.conn = psycopg2.connect(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                port=DB_PORT
            )
            logger.info("[BD] Conexion a base de datos exitosa")
        except Exception as e:
            logger.error(f"[BD] Error conectando: {e}")
            self.conn = None
    
    def servicio_existe(self, numero):
        """Verifica si el servicio ya fue alertado"""
        if not self.conn:
            return False
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id FROM servicios_alertados WHERE numero = %s", (numero,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"[BD] Error verificando servicio: {e}")
            return False
    
    def guardar_servicio(self, numero, tipo, estado):
        """Guarda un nuevo servicio en la base de datos"""
        if not self.conn:
            return False
        
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO servicios_alertados (numero, tipo, estado) VALUES (%s, %s, %s)",
                    (numero, tipo, estado)
                )
            self.conn.commit()
            logger.info(f"[BD] Servicio {numero} guardado en BD")
            return True
        except Exception as e:
            logger.error(f"[BD] Error guardando servicio: {e}")
            self.conn.rollback()
            return False
    
    def obtener_servicios(self):
        """Obtiene todos los servicios alertados"""
        if not self.conn:
            return {}
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT numero, tipo, estado FROM servicios_alertados")
                servicios = {}
                for row in cur.fetchall():
                    servicios[row['numero']] = {
                        'tipo': row['tipo'],
                        'estado': row['estado']
                    }
                return servicios
        except Exception as e:
            logger.error(f"[BD] Error obteniendo servicios: {e}")
            return {}
    
    def cerrar(self):
        """Cierra la conexion a BD"""
        if self.conn:
            self.conn.close()
            logger.info("[BD] Conexion cerrada")

# ============ MONITOR ============

class MonitorHomeServe:
    def __init__(self, bd):
        self.bd = bd
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
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
                                'estado': estado
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
        """Procesa servicios y alerta sobre los NUEVOS"""
        servicios_alertados = 0
        
        for numero, datos in servicios_nuevos.items():
            # Verificar si el servicio YA existe en la BD
            if not self.bd.servicio_existe(numero):
                logger.info(f"[NUEVO] Servicio detectado: {numero}")
                
                # Enviar alerta
                if self.enviar_alerta_telegram(numero, datos['tipo'], datos['estado']):
                    # Guardar en BD
                    self.bd.guardar_servicio(numero, datos['tipo'], datos['estado'])
                    servicios_alertados += 1
                    time.sleep(1)
            else:
                logger.info(f"[ANTIGUO] Servicio ya conocido: {numero}")
        
        return servicios_alertados
    
    def ejecutar(self):
        """Loop principal de monitoreo"""
        logger.info("=" * 60)
        logger.info("INICIANDO MONITOR HOMESERVE")
        logger.info(f"Intervalo de monitoreo: {INTERVALO_SEGUNDOS} segundos")
        logger.info("=" * 60)
        
        while not self.login():
    logger.error("Login fallido. Reintentando en 30 segundos...")
    time.sleep(30)
        
        intento_reconexion = 0
        
        while True:
            try:
                servicios = self.obtener_servicios()
                
                if servicios:
                    alertas = self.procesar_servicios(servicios)
                    if alertas > 0:
                        logger.info(f"NUEVOS servicios alertados: {alertas}")
                    intento_reconexion = 0
                else:
                    logger.warning("Sin servicios. Reconectando...")
                    if not self.login():
                        intento_reconexion += 1
                        if intento_reconexion > 3:
    logger.error("Demasiados intentos. Esperando 60 segundos antes de reintentar...")
    time.sleep(60)
    intento_reconexion = 0
                
                logger.info(f"Proximo chequeo en {INTERVALO_SEGUNDOS} segundos...")
                time.sleep(INTERVALO_SEGUNDOS)
                
            except KeyboardInterrupt:
                logger.info("Monitoreo detenido por usuario")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(INTERVALO_SEGUNDOS)
            finally:
                # Asegurar que la conexion siga abierta
                if self.bd.conn is None:
                    logger.warning("Reconectando a BD...")
                    self.bd = BaseDatos()

# ============ MAIN ============
if __name__ == "__main__":
    bd = BaseDatos()
    if bd.conn:
        monitor = MonitorHomeServe(bd)
        try:
            monitor.ejecutar()
        finally:
            bd.cerrar()
    else:
        logger.error("No se pudo conectar a la base de datos. Abortando...")
