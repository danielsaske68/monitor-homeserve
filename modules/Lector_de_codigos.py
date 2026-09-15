import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import threading
import requests
import os
import re
import time
from bs4 import BeautifulSoup
from PIL import Image

# =========================================================
# CONFIGURACIÓN
# =========================================================
USUARIO = "16205"
PASSWORD = "Aventura69."
BASE_URL = "https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec="
THEME_COLOR = "#0056b3" 


# --- NUEVO: DEFINIR CARPETA DE DATOS ---
CARPETA_DATOS = "datos_lector"
if not os.path.exists(CARPETA_DATOS):
    os.makedirs(CARPETA_DATOS)


# =========================================================
# APP
# =========================================================
class Lector_de_codigos(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="#101820")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)
        self.parent = parent

        self.session = requests.Session()

        self.left_frame = ctk.CTkFrame(self, corner_radius=18, fg_color="#111c2b", border_color="#28507a", border_width=1)
        self.left_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_frame.grid_columnconfigure(0, weight=1)

        logo_panel = ctk.CTkFrame(self.left_frame, fg_color="#0b1520", corner_radius=16, border_color="#2d5d8e", border_width=1)
        logo_panel.pack(fill="x", padx=12, pady=(12, 10))

        try:
            img = ctk.CTkImage(light_image=Image.open("assets/logo.png"), dark_image=Image.open("assets/logo.png"), size=(120, 120))
            ctk.CTkLabel(logo_panel, image=img, text="").pack(pady=12)
        except:
            ctk.CTkLabel(logo_panel, text="LOGO", font=("Arial", 18, "bold")).pack(pady=30)

        button_panel = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        button_panel.pack(fill="x", padx=10, pady=(0, 10))
        button_panel.grid_columnconfigure(0, weight=1)

        btn_config = {"width": 180, "height": 38, "corner_radius": 10, "fg_color": THEME_COLOR, "font": ("Arial", 12, "bold")}
        ctk.CTkButton(button_panel, text="1. INICIAR SESIÓN", command=self.login, **btn_config).grid(row=0, column=0, sticky="ew", padx=4, pady=6)
        ctk.CTkButton(button_panel, text="2. EXTRAER LISTA", command=lambda: threading.Thread(target=self.listar).start(), **btn_config).grid(row=1, column=0, sticky="ew", padx=4, pady=6)
        ctk.CTkButton(button_panel, text="3. ANALIZAR PENDIENTES", command=lambda: threading.Thread(target=self.pendientes).start(), **btn_config).grid(row=2, column=0, sticky="ew", padx=4, pady=6)
        ctk.CTkButton(button_panel, text="4. LIMPIEZA MASIVA", command=lambda: threading.Thread(target=self.limpiar).start(), **btn_config).grid(row=3, column=0, sticky="ew", padx=4, pady=6)

        ctk.CTkButton(
            button_panel,
            text="📂 IR A CARPETA DATOS",
            command=self.abrir_carpeta,
            fg_color="#444444",
            hover_color="#585858",
            height=38,
            font=("Arial", 12, "bold")
        ).grid(row=4, column=0, sticky="ew", padx=4, pady=(12, 10))

        self.right_frame = ctk.CTkFrame(self, corner_radius=18, fg_color="#1c222b", border_color="#2e425b", border_width=1)
        self.right_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.right_frame.grid_rowconfigure(0, weight=3)
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_columnconfigure(0, weight=1)

        table_container = ctk.CTkFrame(self.right_frame, fg_color="#191f2b", corner_radius=12, border_width=1, border_color="#2d3f57")
        table_container.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 8))
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#1d1d1d", foreground="white", fieldbackground="#1d1d1d", borderwidth=0, font=("Arial", 12), rowheight=28)
        style.configure("Treeview.Heading", background=THEME_COLOR, foreground="white", relief="flat", font=("Arial", 13, "bold"))

        self.tree = ttk.Treeview(table_container, columns=("id", "estado"), show="headings")
        self.tree.heading("id", text="ID REPARACIÓN")
        self.tree.heading("estado", text="ESTADO")
        self.tree.column("id", width=210, anchor="center")
        self.tree.column("estado", width=180, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        log_container = ctk.CTkFrame(self.right_frame, fg_color="#171d28", corner_radius=12, border_width=1, border_color="#2d3f57")
        log_container.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_container.grid_rowconfigure(0, weight=1)
        log_container.grid_columnconfigure(0, weight=1)

        self.log = ctk.CTkTextbox(log_container, height=120, corner_radius=8, fg_color="#111820", border_color="#2e425b", border_width=1, font=("Consolas", 11))
        self.log.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # --- FUNCIONES ---

    def write_log(self, msg):
        self.log.insert("end", f"{msg}\n")
        self.log.see("end")

    def login(self):
        try:
            self.write_log("🔐 Iniciando sesión...")
            self.session.get(BASE_URL + "PROF_PASS")
            res = self.session.post(BASE_URL + "PROF_PASS", data={"CODIGO": USUARIO, "PASSW": PASSWORD, "BTN": "Aceptar"})
            if res.status_code == 200: self.write_log("✅ Sesión iniciada.")
            else: self.write_log("❌ Error login.")
        except Exception as e: self.write_log(f"❌ Error: {e}")

    def listar(self):
        try:
            res = self.session.get(BASE_URL + "recibe_recados&servicio=urgentes")
            servicios = sorted(list(set(re.findall(r"servicio=(\d{6,10})", res.text))))
            self.tree.delete(*self.tree.get_children())
            for s in servicios: self.tree.insert("", "end", values=(s, "CARGADO"))
            with open(os.path.join(CARPETA_DATOS, "pendientes_albaran.txt"), "w", encoding="utf-8") as f: f.write("\n".join(servicios))
            self.write_log(f"✅ Cargados {len(servicios)} servicios.")
        except Exception as e: self.write_log(f"❌ Error listando: {e}")

    def pendientes(self):
        self.write_log("🔍 Analizando estados específicos...")
        self.tree.delete(*self.tree.get_children())
        pendientes_encontrados = [] # Lista para guardar los que fallan
        
        try:
            with open(os.path.join(CARPETA_DATOS, "pendientes_albaran.txt"), "r", encoding="utf-8") as f:
                numeros = [x.strip() for x in f.readlines() if x.strip()]
        except: return

        for num in numeros:
            self.session.post(BASE_URL + "prof_verdatos", data={"SERVICIO": num, "BTNBUSCAR": "Localizar Servicio."})
            detalle = self.session.get(f"{BASE_URL}ver_servicioencurso&Servicio={num}&Pag=1")
            soup = BeautifulSoup(detalle.text, "html.parser")
            
            encontrado = False
            tags = soup.find_all("font")
            for t in tags:
                texto = t.get_text(strip=True).upper()
                if "PENDIENTE DE RECIBIR ALBARÁN" in texto:
                    encontrado = True
                    break
            
            estado = "PENDIENTE ALBARÁN" if encontrado else "OK"
            if encontrado: pendientes_encontrados.append(num) # Guardamos en la lista
            
            self.tree.insert("", "end", values=(num, estado))
            self.write_log(f"{'⚠️' if encontrado else '✅'} {num}: {estado}")
            time.sleep(0.8)
        
        # GUARDAR TXT APARTE
        with open(os.path.join(CARPETA_DATOS, "pendientes_reporte.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(pendientes_encontrados))
            
        self.write_log(f"💾 Reporte guardado en 'pendientes_reporte.txt'")
        self.write_log("🎉 Análisis finalizado.")

    def limpiar(self):
        try:
            res = self.session.get(BASE_URL + "recibe_recados&servicio=urgentes")
            soup = BeautifulSoup(res.text, "html.parser")
            links = [a['href'] for a in soup.find_all("a", href=True) if "servicio=" in a['href']]
            for link in links:
                self.session.get(link)
                time.sleep(0.5)
            self.write_log("🎉 Limpieza finalizada.")
        except Exception as e: self.write_log(f"❌ Error limpieza: {e}")


    def abrir_carpeta(self):
        # Abre la carpeta 'datos_lector' según el sistema operativo
        path = os.path.realpath(CARPETA_DATOS)
        if os.name == 'nt':  # Windows
            os.startfile(path)
        elif os.uname().sysname == 'Darwin':  # macOS
            import subprocess
            subprocess.call(["open", path])
        else:  # Linux
            import subprocess
            subprocess.call(["xdg-open", path]) 
     