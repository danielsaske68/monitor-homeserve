import time
import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
from config import LOGIN_URL, ASIGNACION_URL, BASE_URL, SERVICIOS_CURSO_URL, USUARIO, PASSWORD, logger
from database import registrar_seguimiento
from utils import extraer_fecha_caducidad, calcular_fecha_caducidad

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
            logger.warning(f"Error obtener: {e}")
            if self.login():
                return self.obtener()
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

    def _abrir_formulario_cambio_estado(self, sid):
        url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
        try:
            r0 = self.session.get(url, timeout=10)
            text0 = getattr(r0, "text", "") or ""
            if "BTNCAMBIAESTADO" in text0 or "Elija un nuevo estado" in text0:
                return True

            click_payload = {"Pag": "1", "repaso.x": "17", "repaso.y": "30", "SERVICIO": str(sid)}
            r1 = self.session.post(url, data=click_payload, timeout=15)
            text1 = getattr(r1, "text", "") or ""
            if getattr(r1, "status_code", 200) < 400:
                time.sleep(0.35)
            return "BTNCAMBIAESTADO" in text1 or "Elija un nuevo estado" in text1
        except Exception as exc:
            logger.warning(f"No se pudo abrir formulario para {sid}: {exc}")
            return False

    def _estado_actual_servicio(self, sid):
        try:
            from bot_actions import obtener_datos_servicio
            datos, raw_html = obtener_datos_servicio(sid, self)
            texto_total = " ".join(str(v) for v in datos.values()) + " " + str(raw_html)
            match = re.search(r"\b(?:348|318|320)\b", texto_total)
            if match:
                return match.group(0)
        except Exception:
            pass
        return None

    def cambiar_estado(self, sid, estado):
        try:
            estado_inicial = self._estado_actual_servicio(sid)
            if estado_inicial == estado:
                fecha_caducidad = calcular_fecha_caducidad(datetime.now())
                registrar_seguimiento(sid, estado, fecha_caducidad)
                return True, f"✅ Estado {estado} ya estaba aplicado"

            url = f"{BASE_URL}?w3exec=ver_servicioencurso&Servicio={sid}&Pag=1"
            self.session.get(url, timeout=10)
            self._abrir_formulario_cambio_estado(sid)

            fecha = datetime.now() + timedelta(days=3)
            if fecha.weekday() == 5:
                fecha += timedelta(days=2)
            elif fecha.weekday() == 6:
                fecha += timedelta(days=1)

            fecha_str = fecha.strftime("%d/%m/%Y")
            fecha_caducidad = calcular_fecha_caducidad(datetime.now())

            obs = "Pendiente de localizar a asegurado" if estado == "348" else "Cambio de estado tramitado desde bot"

            payload = {
                "Pag": "1",
                "ESTADO": estado,
                "FECSIG": fecha_str,
                "INFORMO": "on",
                "Observaciones": obs,
                "BTNCAMBIAESTADO": "Aceptar el Cambio"
            }

            respuesta = self.session.post(url, data=payload, timeout=15)
            if getattr(respuesta, "status_code", 200) >= 400:
                return False, f"❌ Error HTTP al cambiar estado de {sid}"

            registrar_seguimiento(sid, estado, fecha_caducidad)
            return True, f"✅ Estado {estado} aplicado ({fecha_str})"
        except Exception as e:
            logger.error(f"Error en cambiar_estado({sid}, {estado}): {e}")
            return False, f"❌ Error: {e}"

homeserve = HomeServe()