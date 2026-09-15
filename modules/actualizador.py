import customtkinter as ctk
import threading
import requests
import zipfile
import os
import sys
import json
import shutil
import subprocess

class ActualizadorFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="#101820")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="#121b29", corner_radius=18, border_width=1, border_color="#2d435d")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)

        titulo = ctk.CTkLabel(
            header,
            text="Actualizador de Gestor PRO",
            font=("Arial", 28, "bold"),
            text_color="#4ea3ff"
        )
        titulo.grid(row=0, column=0, pady=(20, 8), sticky="n")

        self.estado = ctk.CTkLabel(
            header,
            text="Pulsa el botón para comprobar si existen actualizaciones.",
            font=("Arial", 15),
            text_color="#dfeaff"
        )
        self.estado.grid(row=1, column=0, pady=(0, 16), sticky="n")

        self.barra = ctk.CTkProgressBar(header, width=500, progress_color="#0f6cbd")
        self.barra.grid(row=2, column=0, pady=(0, 18), sticky="ew", padx=18)
        self.barra.set(0)

        self.boton = ctk.CTkButton(
            header,
            text="Buscar actualizaciones",
            command=self.buscar_actualizaciones,
            height=40,
            width=250,
            fg_color="#0f6cbd",
            hover_color="#0d5ea8",
            font=("Arial", 14, "bold")
        )
        self.boton.grid(row=3, column=0, pady=(0, 18))

        log_panel = ctk.CTkFrame(self, fg_color="#171f2a", corner_radius=18, border_width=1, border_color="#2d435d")
        log_panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        log_panel.grid_rowconfigure(0, weight=1)
        log_panel.grid_columnconfigure(0, weight=1)

        self.log = ctk.CTkTextbox(log_panel, width=700, height=300, fg_color="#111820", border_width=1, border_color="#3c4c5c", font=("Consolas", 11))
        self.log.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

    def escribir(self, texto):
        self.log.insert("end", texto + "\n")
        self.log.see("end")

    def buscar_actualizaciones(self):
        self.boton.configure(state="disabled")
        self.log.delete("0.0", "end")
        threading.Thread(
            target=self.proceso_actualizacion,
            daemon=True
        ).start()

    def proceso_actualizacion(self):
        try:
            GITHUB_USER = "danielsaske68"
            GITHUB_REPO = "GestorPro"
            URL_VERSION_REMOTE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/version.json"
            URL_ZIP_REPO = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/archive/refs/heads/main.zip"

            self.estado.configure(text="Conectando con GitHub...")
            self.barra.set(0.05)
            self.escribir("✔ Conectando con GitHub...")

            # Directorio base (funciona tanto en script como en .exe)
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                is_exe = True
            else:
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                is_exe = False

            version_path = os.path.join(base_dir, "version.json")
            
            local_version = "1.0.0"
            if os.path.exists(version_path):
                with open(version_path, "r", encoding="utf-8") as f:
                    local_version = json.load(f).get("version", "1.0.0")

            # Normalizar versiones: quitar prefijo 'v' y convertir partes a enteros
            def parse_version(v):
                if isinstance(v, str):
                    v_str = v.strip()
                    if v_str.startswith("v") or v_str.startswith("V"):
                        v_str = v_str[1:]
                    parts = [p for p in v_str.split('.')]
                    nums = []
                    for p in parts:
                        try:
                            nums.append(int(''.join(ch for ch in p if ch.isdigit())))
                        except Exception:
                            nums.append(0)
                    # Asegurar 3 componentes (major.minor.patch)
                    while len(nums) < 3:
                        nums.append(0)
                    return tuple(nums[:3])
                return (0,0,0)

            parsed_local = parse_version(local_version)

            self.escribir(f"📍 Versión local actual: {local_version}")
            
            # Consultar versión remota en GitHub
            response = requests.get(URL_VERSION_REMOTE, timeout=10)
            if response.status_code != 200:
                raise Exception(f"No se pudo conectar (Código HTTP {response.status_code})")
            
            # Limpiamos posibles caracteres invisibles o de control
            contenido_texto = response.text.strip()
            try:
                # Usamos strict=False para permitir caracteres de control en el string
                remote_data = json.loads(contenido_texto, strict=False)
            except Exception:
                # Si aun así falla, extraemos el texto directamente
                remote_data = json.loads(response.content.decode('utf-8-sig'), strict=False)

            remote_version = remote_data.get("version", "1.0.0")
            parsed_remote = parse_version(remote_version)
            self.escribir(f"📍 Versión en el servidor: {remote_version}")

            # Comparación semántica sencilla (major, minor, patch)
            if parsed_local == parsed_remote:
                self.barra.set(1.0)
                self.estado.configure(text="Gestor PRO está actualizado.")
                self.escribir("✔ No hay actualizaciones pendientes.")
                self.boton.configure(state="normal")
                return
            elif parsed_local > parsed_remote:
                # Local más nueva que remota (caso inusual)
                self.barra.set(1.0)
                self.estado.configure(text="Versión local más reciente que la servidor.")
                self.escribir("⚠ La versión local es más reciente que la disponible en el servidor.")
                self.boton.configure(state="normal")
                return
            else:
                # parsed_remote > parsed_local → hay actualización
                self.escribir(f"⬆️ Nueva versión disponible: {remote_version} (local: {local_version})")

            # Descarga con cálculo de porcentaje en tiempo real
            self.estado.configure(text="Descargando actualización...")
            self.escribir("⬇ Iniciando descarga del paquete...")

            zip_path = os.path.join(base_dir, "update.zip")
            response_zip = requests.get(URL_ZIP_REPO, stream=True, timeout=30)
            
            total_size = int(response_zip.headers.get('content-length', 0))
            downloaded_size = 0

            with open(zip_path, "wb") as f:
                for chunk in response_zip.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            percent = downloaded_size / total_size
                            barra_val = 0.10 + (percent * 0.50)
                            self.barra.set(barra_val)
                            
                            percent_int = int(percent * 100)
                            if percent_int % 20 == 0: 
                                self.estado.configure(text=f"Descargando... {percent_int}%")

            self.escribir("✔ Descarga completada al 100%.")
            self.barra.set(0.65)

            self.estado.configure(text="Instalando archivos...")
            self.escribir("📦 Reemplazando archivos y carpetas...")

            extract_dir = os.path.join(base_dir, "temp_update")
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            extracted_folders = os.listdir(extract_dir)
            source_folder = os.path.join(extract_dir, extracted_folders[0])

            # Autodetección de elementos a actualizar
            items_a_actualizar = os.listdir(source_folder)

            for item in items_a_actualizar:
                if item.startswith('.'):
                    continue

                src_item = os.path.join(source_folder, item)
                dst_item = os.path.join(base_dir, item)

                if os.path.exists(src_item):
                    try:
                        if os.path.isdir(src_item):
                            if os.path.exists(dst_item):
                                try:
                                    shutil.rmtree(dst_item, ignore_errors=True)
                                except Exception:
                                    pass
                            
                            if not os.path.exists(dst_item):
                                shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            else:
                                for root, dirs, files in os.walk(src_item):
                                    rel_path = os.path.relpath(root, src_item)
                                    dest_subpath = os.path.join(dst_item, rel_path)
                                    os.makedirs(dest_subpath, exist_ok=True)
                                    for file in files:
                                        s_file = os.path.join(root, file)
                                        d_file = os.path.join(dest_subpath, file)
                                        try:
                                            shutil.copy2(s_file, d_file)
                                        except PermissionError:
                                            self.escribir(f"  -> Omitido (en uso por Windows): {item}/{file}")
                        else:
                            # Si es un archivo ejecutable nuevo (.exe) y estamos corriendo como .exe, 
                            # lo guardamos temporalmente con otro nombre para aplicarlo mediante el script .bat
                            if is_exe and item.endswith(".exe"):
                                nuevo_exe_path = os.path.join(base_dir, "nuevo_" + item)
                                shutil.copy2(src_item, nuevo_exe_path)
                                self.escribir(f"  -> Preparado nuevo ejecutable: {item}")
                            else:
                                shutil.copy2(src_item, dst_item)
                                self.escribir(f"  -> Actualizado: {item}")
                    except Exception as sub_err:
                        self.escribir(f"  -> No se pudo actualizar {item}: {sub_err}")

            # Limpiar zip temporal pero mantener la carpeta extraída por si hay un .exe nuevo
            if os.path.exists(zip_path):
                os.remove(zip_path)

            self.barra.set(1.0)
            self.estado.configure(text="¡Actualización completada con éxito!")
            self.escribir("🎉 Archivos actualizados correctamente.")

            # Si estamos corriendo como .exe y hay un ejecutable nuevo pendiente de actualizar
            if is_exe:
                # Buscamos si se descargó algún nuevo_*.exe
                exe_actual_nombre = os.path.basename(sys.executable)
                nuevo_exe_encontrado = os.path.join(base_dir, "nuevo_" + exe_actual_nombre)

                if os.path.exists(nuevo_exe_encontrado):
                    self.escribir("🔄 Actualizando archivo ejecutable principal (.exe)...")
                    
                    # Creamos un script .bat temporal para reemplazar el .exe y reiniciar la app
                    bat_path = os.path.join(base_dir, "actualizar.bat")
                    with open(bat_path, "w", encoding="utf-8") as bat_file:
                        bat_file.write(f"""@echo off
timeout /t 2 /nobreak > nul
del /f /q "{sys.executable}"
move /y "{nuevo_exe_encontrado}" "{sys.executable}"
start "" "{sys.executable}"
del "%~f0"
""")
                    
                    self.escribir("🚀 Reiniciando aplicación para aplicar los cambios...")
                    # Lanzamos el .bat y cerramos la app actual
                    subprocess.Popen(bat_path, shell=True)
                    os._exit(0)

            # Limpieza general si no es .exe compilado
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)

            self.boton.configure(state="normal")
            
        except Exception as e:
            self.estado.configure(text="Error en la actualización.")
            self.escribir(f"❌ Error crítico: {str(e)}")
            self.boton.configure(state="normal")
