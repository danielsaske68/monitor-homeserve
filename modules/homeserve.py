import time
import os
import json
import subprocess
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
import keyboard
import sys
import ctypes

# =========================================================
# CONFIGURACIÓN
# =========================================================
USUARIO = "16205"
CONTRASENA = "Aventura69."

UMBRAL_GENERAL = 0.45

# Ruta base calculada con mayor tolerancia
BASE_HOME = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Homeserve"
)

if not os.path.exists(BASE_HOME):
    BASE_HOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Homeserve")

ADB = os.path.join(BASE_HOME, "adb.exe")
ARCHIVO_SERVICIOS = os.path.join(BASE_HOME, "servicios.txt")
ARCHIVO_OK = os.path.join(BASE_HOME, "servicios_ok.txt")
ARCHIVO_PROGRESO = os.path.join(BASE_HOME, "progreso.json")

pyautogui.PAUSE = 0.005

# =========================================================
# CONTROL DEL BOT
# =========================================================
BOT_PAUSADO = False
BOT_DETENIDO = False
BOT_EN_EJECUCION = False

BOT_ESTADO = "INICIO"
SERVICIO_ACTUAL = None
PASO_ACTUAL = None


def deshabilitar_quickedit_cmd():
    """Desactiva el QuickEdit de la consola de Windows para evitar que se ponga en pausa al hacer clic."""
    if os.name == 'nt':
        try:
            kernel32 = ctypes.windll.kernel32
            # STD_INPUT_HANDLE = -10
            hInput = kernel32.GetStdHandle(-10)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(hInput, ctypes.byref(mode))
            # ENABLE_QUICK_EDIT_MODE = 0x0040, ENABLE_INSERT_MODE = 0x0020
            mode.value &= ~0x0040
            mode.value &= ~0x0020
            kernel32.SetConsoleMode(hInput, mode)
        except Exception:
            pass


def log(mensaje):
    """Función para imprimir mensajes instantáneamente en consola"""
    print(mensaje, flush=True)


def iniciar_teclas_control():
    def pausa():
        global BOT_PAUSADO
        BOT_PAUSADO = True
        log("[TECLA] BOT PAUSADO (Pulsado F8)")

    def continuar():
        global BOT_PAUSADO
        BOT_PAUSADO = False
        log("[TECLA] BOT CONTINUANDO (Pulsado F9)")

    def detener():
        global BOT_DETENIDO
        BOT_DETENIDO = True
        log("[TECLA] BOT DETENIDO (Pulsado F10)")

    try:
        keyboard.add_hotkey("f8", pausa)
        keyboard.add_hotkey("f9", continuar)
        keyboard.add_hotkey("f10", detener)
        log("[+] Atajos de teclado registrados (F8: Pausa, F9: Continuar, F10: Detener)")
    except Exception as e:
        log(f"[!] Advertencia al registrar atajos (requiere permisos de Admin): {e}")


def ruta_archivo(nombre):
    return os.path.join(BASE_HOME, nombre)


def guardar_progreso(servicio, estado):
    datos = {
        "servicio": servicio,
        "estado": estado,
        "hora": time.strftime("%d/%m/%Y %H:%M:%S")
    }
    try:
        with open(ARCHIVO_PROGRESO, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=4)
    except Exception as e:
        log(f"[-] Error guardando progreso: {e}")


def cambiar_estado(servicio, estado):
    global BOT_ESTADO, SERVICIO_ACTUAL, PASO_ACTUAL
    BOT_ESTADO = estado
    SERVICIO_ACTUAL = servicio
    PASO_ACTUAL = estado

    guardar_progreso(servicio, estado)
    log(f"[ESTADO] {estado}")


def controlar_bot():
    global BOT_PAUSADO, BOT_DETENIDO

    while BOT_PAUSADO:
        if BOT_DETENIDO:
            log("[STOP] Bot detenido durante pausa")
            raise RuntimeError("Bot detenido manualmente por el usuario")

        log("[PAUSA] Bot en espera. Pulsa F9 para continuar...")
        time.sleep(1)

    if BOT_DETENIDO:
        log("[STOP] Bot detenido")
        raise RuntimeError("Bot detenido manualmente por el usuario")


def esperar_segundos(segundos):
    for _ in range(int(segundos * 2)):
        controlar_bot()
        time.sleep(0.5)


def enfocar_scrcpy():
    try:
        ventanas = (
            gw.getWindowsWithTitle('scrcpy')
            or gw.getWindowsWithTitle('POCO')
            or gw.getWindowsWithTitle('M2007J20CG')
        )
        if ventanas:
            win = ventanas[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.5)
            return True
    except Exception as e:
        log(f"[-] Error enfocando ventana scrcpy: {e}")
    return False


def click_humano(x, y, duracion=0.30):
    controlar_bot()
    pyautogui.moveTo(x, y, duration=duracion)
    controlar_bot()
    pyautogui.click()
    controlar_bot()


def adb_texto(texto):
    controlar_bot()
    subprocess.run(
        f'"{ADB}" shell input text "{texto}"',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    controlar_bot()


def adb_back():
    controlar_bot()
    subprocess.run(
        f'"{ADB}" shell input keyevent 4',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def adb_enter():
    controlar_bot()
    subprocess.run(
        f'"{ADB}" shell input keyevent 66',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def obtener_coordenadas_visuales(ruta_imagen, umbral=UMBRAL_GENERAL):
    if not os.path.exists(ruta_imagen):
        log(f"[-] Imagen no encontrada en disco: {ruta_imagen}")
        return None

    pantalla = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
    plantilla = cv2.imread(ruta_imagen)

    if plantilla is None:
        log(f"[-] No se pudo leer la imagen: {ruta_imagen}")
        return None

    resultado = cv2.matchTemplate(pantalla, plantilla, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(resultado)

    log(f"[*] Buscando {os.path.basename(ruta_imagen)} | Confianza: {round(max_val, 2)}")
    if max_val >= umbral:
        x = max_loc[0] + plantilla.shape[1] // 2
        y = max_loc[1] + plantilla.shape[0] // 2
        return (x, y)
    return None


def buscar_y_click(imagen, umbral=UMBRAL_GENERAL, espera=1):
    pos = obtener_coordenadas_visuales(imagen, umbral)
    if pos:
        click_humano(pos[0], pos[1])
        time.sleep(espera)
        return True
    return False


def esperar_imagen(imagen, timeout=15, umbral=UMBRAL_GENERAL):
    inicio = time.time()
    while time.time() - inicio < timeout:
        controlar_bot()
        pos = obtener_coordenadas_visuales(imagen, umbral)
        if pos:
            return pos
        time.sleep(0.5)
    return None


def comprobar_popup():
    for img in [ruta_archivo('boton_aceptar_real.png'), ruta_archivo('btn_aceptar_aviso.png')]:
        if buscar_y_click(img, umbral=0.42, espera=1):
            log("[VIGILANTE] Popup aceptado")
            return True
    return False


def ejecutar_firma_json(tipo, ref_x, ref_y):
    archivo = (
        ruta_archivo('mauricio.json')
        if tipo == "profesional"
        else ruta_archivo('ausente_1.json')
    )

    if not os.path.exists(archivo):
        log(f"[-] Archivo de firma no encontrado: {archivo}")
        return

    with open(archivo, 'r') as f:
        trazos = json.load(f)

    if not trazos:
        log("[-] El archivo de firma está vacío.")
        return

    offset_x = ref_x - trazos[0]['pos'][0]
    offset_y = ref_y - trazos[0]['pos'][1]

    if tipo == "profesional":
        offset_y += 20
    else:
        offset_x += 20

    for evento in trazos:
        controlar_bot()
        x = evento['pos'][0] + offset_x
        y = evento['pos'][1] + offset_y

        pyautogui.moveTo(x, y)
        if evento['action'] == 'down':
            pyautogui.mouseDown()
        elif evento['action'] == 'up':
            pyautogui.mouseUp()

    pyautogui.mouseUp()
    log(f"[+] Firma {tipo} ejecutada.")


def hacer_clic_boton(img_nombre, y_min, y_max):
    if not os.path.exists(img_nombre):
        log(f"[-] No se encontró imagen: {img_nombre}")
        return None

    pantalla = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
    zona = pantalla[y_min:y_max, 0:pantalla.shape[1]]
    plantilla = cv2.imread(img_nombre)

    if plantilla is None:
        return None

    resultado = cv2.matchTemplate(zona, plantilla, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(resultado)

    log(f"[*] Buscando {os.path.basename(img_nombre)} zona {y_min}-{y_max} | Confianza: {round(max_val, 2)}")

    if max_val >= 0.40:
        x = max_loc[0] + plantilla.shape[1] // 2
        y = max_loc[1] + plantilla.shape[0] // 2 + y_min
        click_humano(x, y)
        return (x, y)
    return None


def cargar_servicios():
    if not os.path.exists(ARCHIVO_SERVICIOS):
        log(f"[-] No existe el archivo de servicios en: {ARCHIVO_SERVICIOS}")
        return []

    with open(ARCHIVO_SERVICIOS, "r", encoding="utf-8") as f:
        return [linea.strip() for linea in f if linea.strip()]


def marcar_ok(servicio):
    try:
        with open(ARCHIVO_OK, "a", encoding="utf-8") as f:
            f.write(servicio + "\n")
    except Exception as e:
        log(f"[-] Error registrando servicio completado: {e}")


def procesar_servicio(NUM_SERVICIO):
    log("\n==================================================")
    log(f"BUSCAR SERVICIO: {NUM_SERVICIO}")
    log("==================================================")

    cambiar_estado(NUM_SERVICIO, "BUSCANDO_SERVICIO")

    pos_barra = esperar_imagen(ruta_archivo('barra_buscar.png'), timeout=10)

    if pos_barra:
        click_humano(pos_barra[0], pos_barra[1])
        time.sleep(0.5)

        log(f"[*] Introduciendo servicio: {NUM_SERVICIO}")
        adb_texto(NUM_SERVICIO)
        time.sleep(0.5)
        adb_back()
        time.sleep(0.5)

        if buscar_y_click(ruta_archivo('boton_lupa.png')):
            log("[+] Servicio buscado con lupa.")
        else:
            adb_enter()
            log("[+] Servicio buscado con ENTER.")

        log("[*] Esperando carga...")
        esperar_segundos(5)

    log("\n==================================================")
    log("CREAR ALBARÁN")
    log("==================================================")

    cambiar_estado(NUM_SERVICIO, "CREANDO_ALBARAN")
    pos_albaran = esperar_imagen(ruta_archivo('boton_albaran.png'), timeout=15, umbral=0.40)

    if pos_albaran:
        click_humano(pos_albaran[0], pos_albaran[1])
        log("[+] Click en Crear Albarán.")
        time.sleep(2)

    log("\n==================================================")
    log("POPUP")
    log("==================================================")

    comprobar_popup()

    log("\n==================================================")
    log("CARGANDO FIRMAS")
    log("==================================================")
    esperar_segundos(10)

    log("\n==================================================")
    log("FIRMA PROFESIONAL")
    log("==================================================")

    cambiar_estado(NUM_SERVICIO, "FIRMA_PROFESIONAL")
    pos = hacer_clic_boton(ruta_archivo("boton_firmar_general.png"), 0, 540)

    if pos:
        time.sleep(2)
        ejecutar_firma_json("profesional", pos[0], pos[1])
        time.sleep(1)
        hacer_clic_boton(ruta_archivo('boton_aceptar_firma.png'), 0, 1080)
        log("[+] Firma profesional completada.")
        time.sleep(4)

    log("\n==================================================")
    log("FIRMA CLIENTE")
    log("==================================================")

    cambiar_estado(NUM_SERVICIO, "FIRMA_CLIENTE")
    pos = hacer_clic_boton(ruta_archivo("boton_firmar_general.png"), 540, 1080)

    if pos:
        time.sleep(2)
        ejecutar_firma_json("cliente", pos[0], pos[1])
        time.sleep(1)
        hacer_clic_boton(ruta_archivo('boton_aceptar_firma.png'), 0, 1080)
        log("[+] Firma cliente completada.")
        esperar_segundos(5)

    log("\n==================================================")
    log("IMPRIMIR / ENVIAR")
    log("==================================================")

    cambiar_estado(NUM_SERVICIO, "ENVIANDO")
    pos_env = esperar_imagen(ruta_archivo('boton_imprimir_enviar.png'), timeout=20)

    if pos_env:
        click_humano(pos_env[0], pos_env[1])
        log("[+] Documento enviado.")

        log("\n==================================================")
        log("POPUP FINAL")
        log("==================================================")
        esperar_segundos(12)

        log("[*] Buscando botón 'Ir a detalles del servicio'...")
        if buscar_y_click(ruta_archivo('ir_detalles_servicio.png'), umbral=0.40, espera=5):
            log("[+] Ir a detalles del servicio pulsado.")
        else:
            log("[-] No se encontró ir_detalles_servicio.png")

        log("[*] Esperando carga pantalla detalles...")
        time.sleep(6)

        log("[*] Buscando botón atrás...")
        pos_atras = esperar_imagen(ruta_archivo('boton_atras.png'), timeout=10, umbral=0.35)

        if pos_atras:
            click_humano(pos_atras[0], pos_atras[1])
            log("[+] Botón atrás pulsado.")
        else:
            log("[-] No se encontró boton_atras.png")
    else:
        log("[-] No se encontró botón imprimir/enviar.")


def iniciar_homeserve():
    deshabilitar_quickedit_cmd()  # Previene congelamientos al hacer clic en el CMD
    iniciar_teclas_control()

    log("==================================================")
    log("        AUTOMATIZACIÓN HOMESERVE STARTED")
    log("==================================================")
    log(f"[*] Carpeta de trabajo (BASE_HOME): {BASE_HOME}")

    SCRCPY = os.path.join(BASE_HOME, "scrcpy.exe")

    log("[*] Comprobando scrcpy...")
    if not enfocar_scrcpy():
        log("[*] scrcpy no enfocado/encontrado, abriendo...")
        if os.path.exists(SCRCPY):
            subprocess.Popen([SCRCPY, "--max-fps=60", "--video-bit-rate=4M"], shell=True)

            # Espera dinámica inteligente: aguarda hasta 15 segundos a que scrcpy aparezca y se enfoque
            listo = False
            for _ in range(30):
                time.sleep(0.5)
                if enfocar_scrcpy():
                    listo = True
                    break

            if listo:
                log("[+] scrcpy abierto y enfocado correctamente")
                time.sleep(2)  # Pausa extra de seguridad para que scrcpy renderice el espejo
            else:
                log("[-] No se pudo enfocar la ventana de scrcpy tras ejecutarlo")
        else:
            log(f"[-] ERROR CRÍTICO: No existe el ejecutable scrcpy.exe en {SCRCPY}")

    servicios = cargar_servicios()
    log(f"[+] Servicios cargados: {len(servicios)}")

    if not servicios:
        log("[-] No hay servicios pendientes para procesar.")
        return

    for servicio in servicios:
        log("\n==================================================")
        log(f"PROCESANDO SERVICIO: {servicio}")
        log("==================================================")

        try:
            cambiar_estado(servicio, "INICIANDO")
            procesar_servicio(servicio)
            marcar_ok(servicio)
            cambiar_estado(servicio, "FINALIZADO")
            log(f"[✓] Servicio {servicio} completado con éxito.")
        except RuntimeError as e:
            log(f"[!] BOT DETENIDO POR EL USUARIO (F10): {e}")
            break
        except Exception as e:
            log(f"[x] Error inesperado en servicio {servicio}: {e}")

        time.sleep(3)

    global BOT_DETENIDO, BOT_PAUSADO
    BOT_DETENIDO = False
    BOT_PAUSADO = False

    log("\n==================================================")
    log("EJECUCIÓN FINALIZADA / DETENIDA")
    log("==================================================")


if __name__ == "__main__":
    try:
        iniciar_homeserve()
    except Exception as err:
        print(f"\n[ERROR EN EJECUCIÓN MAIN]: {err}", flush=True)