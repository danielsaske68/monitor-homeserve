import os
import sys
import subprocess
import re
from datetime import datetime
import fitz  # PyMuPDF: pip install PyMuPDF
import customtkinter as ctk
from tkinter import filedialog, messagebox

def ruta_app(carpeta, archivo=None):
    base = os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
    ruta = os.path.join(base, carpeta)
    if archivo:
        ruta = os.path.join(ruta, archivo)
    return ruta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA_RESULTADOS = ruta_app("resultados_pagos")
os.makedirs(CARPETA_RESULTADOS, exist_ok=True)

class VerificadorPagosFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color="#101820")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="#121b29", corner_radius=18, border_width=1, border_color="#2d435d")
        header.grid(row=0, column=0, padx=20, pady=(18, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        titulo = ctk.CTkLabel(header, text="🔍 Verificador de Pagos por PDF", font=("Arial", 22, "bold"), text_color="#4ea3ff")
        titulo.grid(row=0, column=0, padx=16, pady=(14, 12), sticky="w")

        controles_frame = ctk.CTkFrame(self, fg_color="#171f2a", corner_radius=16, border_width=1, border_color="#2d435d")
        controles_frame.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")
        controles_frame.grid_columnconfigure(1, weight=1)

        self.btn_pdf = ctk.CTkButton(controles_frame, text="📄 Seleccionar PDF de Liquidación", command=self.seleccionar_pdf, fg_color="#0f6cbd", hover_color="#0d5ea8", height=36, font=("Arial", 12, "bold"))
        self.btn_pdf.grid(row=0, column=0, padx=(16, 10), pady=12)

        self.lbl_pdf_path = ctk.CTkLabel(controles_frame, text="Ningún PDF seleccionado", text_color="#9bb7d3", font=("Arial", 12))
        self.lbl_pdf_path.grid(row=0, column=1, sticky="w", pady=12)

        cuerpo_frame = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo_frame.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        cuerpo_frame.grid_columnconfigure(0, weight=1)
        cuerpo_frame.grid_columnconfigure(1, weight=1)
        cuerpo_frame.grid_rowconfigure(1, weight=1)

        panel_izq = ctk.CTkFrame(cuerpo_frame, fg_color="#171f2a", corner_radius=16, border_width=1, border_color="#2d435d")
        panel_izq.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        panel_izq.grid_columnconfigure(0, weight=1)
        panel_izq.grid_rowconfigure(1, weight=1)

        panel_der = ctk.CTkFrame(cuerpo_frame, fg_color="#171f2a", corner_radius=16, border_width=1, border_color="#2d435d")
        panel_der.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        panel_der.grid_columnconfigure(0, weight=1)
        panel_der.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panel_izq, text="Códigos a verificar (uno por línea):", font=("Arial", 13, "bold"), text_color="#dfeaff").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 8))
        ctk.CTkLabel(panel_der, text="Resultados de la verificación:", font=("Arial", 13, "bold"), text_color="#dfeaff").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 8))

        self.txt_codigos = ctk.CTkTextbox(panel_izq, font=("Consolas", 12), height=16, corner_radius=10, fg_color="#111820", border_width=1, border_color="#3c4c5c")
        self.txt_codigos.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self.placeholder_codigos = "INSERTE NUEVOS SERVICIOS PARA REVISAR"
        self.txt_codigos.insert("1.0", self.placeholder_codigos)
        self.txt_codigos.configure(text_color="gray")

        self.txt_codigos.bind("<FocusIn>", self.on_focus_in_codigos)
        self.txt_codigos.bind("<FocusOut>", self.on_focus_out_codigos)

        self.txt_resultados = ctk.CTkTextbox(panel_der, font=("Consolas", 12), height=16, corner_radius=10, fg_color="#111820", border_width=1, border_color="#3c4c5c")
        self.txt_resultados.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self.placeholder_resultados = "Resultado invisible una vez termine ya"
        self.txt_resultados.insert("1.0", self.placeholder_resultados)
        self.txt_resultados.configure(text_color="gray", state="disabled")

        acciones_frame = ctk.CTkFrame(self, fg_color="transparent")
        acciones_frame.grid(row=3, column=0, padx=20, pady=18, sticky="ew")
        acciones_frame.grid_columnconfigure(0, weight=1)
        acciones_frame.grid_columnconfigure(1, weight=1)

        btn_verificar = ctk.CTkButton(acciones_frame, text="🚀 Verificar y Generar TXT Separado", command=self.ejecutar_verificacion, height=42, fg_color="#2b8a3e", hover_color="#237032", font=("Arial", 14, "bold"))
        btn_verificar.grid(row=0, column=0, padx=(0, 10), sticky="ew")

        self.btn_abrir_carpeta = ctk.CTkButton(acciones_frame, text="📂 Abrir Carpeta de Resultados", command=self.abrir_carpeta_destino, height=42, fg_color="#3d4b59", hover_color="#4f5e70", font=("Arial", 14, "bold"), state="disabled")
        self.btn_abrir_carpeta.grid(row=0, column=1, padx=(10, 0), sticky="ew")

        self.ruta_pdf_seleccionado = ""
        self.ultima_ruta_salida = ""
        self.es_placeholder_activo = True

    def on_focus_in_codigos(self, event):
        if self.es_placeholder_activo:
            self.txt_codigos.delete("1.0", "end")
            self.txt_codigos.configure(text_color=("black", "white"))
            self.es_placeholder_activo = False

    def on_focus_out_codigos(self, event):
        contenido = self.txt_codigos.get("1.0", "end-1c").strip()
        if not contenido:
            self.es_placeholder_activo = True
            self.txt_codigos.delete("1.0", "end")
            self.txt_codigos.insert("1.0", self.placeholder_codigos)
            self.txt_codigos.configure(text_color="gray")

    def seleccionar_pdf(self):
        archivo = filedialog.askopenfilename(
            title="Seleccionar archivo PDF de liquidación",
            filetypes=[("Archivos PDF", "*.pdf"), ("Todos los archivos", "*.*")]
        )
        if archivo:
            self.ruta_pdf_seleccionado = archivo
            self.lbl_pdf_path.configure(text=os.path.basename(archivo), text_color="#3b8ed0")

    def ejecutar_verificacion(self):
        if not self.ruta_pdf_seleccionado or not os.path.exists(self.ruta_pdf_seleccionado):
            messagebox.showwarning("Advertencia", "Selecciona un archivo PDF válido primero.")
            return

        if self.es_placeholder_activo:
            messagebox.showwarning("Advertencia", "Ingresa al menos un código válido para verificar.")
            return

        raw_text_codigos = self.txt_codigos.get("1.0", "end-1c")
        lista_codigos = [c.strip() for c in raw_text_codigos.splitlines() if c.strip() and c.strip() != self.placeholder_codigos]

        if not lista_codigos:
            messagebox.showwarning("Advertencia", "Ingresa al menos un código para verificar.")
            return

        try:
            doc = fitz.open(self.ruta_pdf_seleccionado)
            
            pagados = []
            no_pagados = []
            suma_total_cobrar = 0.0

            for codigo in lista_codigos:
                encontrado = False
                datos_extraidos = {}
                
                for pagina in doc:
                    texto_pagina = pagina.get_text()
                    if codigo in texto_pagina:
                        encontrado = True
                        lineas = texto_pagina.split('\n')
                        for i, linea in enumerate(lineas):
                            if codigo in linea:
                                inicio_contexto = max(0, i - 2)
                                fin_contexto = min(len(lineas), i + 12)
                                bloque_contexto = " ".join(lineas[inicio_contexto:fin_contexto])
                                
                                nums = re.findall(r'\d+[.,]\d{2}', bloque_contexto)
                                
                                if len(nums) >= 3:
                                    if "Contado" in bloque_contexto or "No Contado" in bloque_contexto:
                                        if len(nums) >= 4:
                                            datos_extraidos["imp_cobrado"] = nums[0]
                                            datos_extraidos["baremo"] = nums[1]
                                            datos_extraidos["base"] = nums[2]
                                            datos_extraidos["total"] = nums[3]
                                        else:
                                            datos_extraidos["imp_cobrado"] = "0,00"
                                            datos_extraidos["baremo"] = nums[0]
                                            datos_extraidos["base"] = nums[1]
                                            datos_extraidos["total"] = nums[2]
                                    else:
                                        datos_extraidos["imp_cobrado"] = "N/A"
                                        datos_extraidos["baremo"] = nums[0]
                                        datos_extraidos["base"] = nums[1]
                                        datos_extraidos["total"] = nums[2]
                                else:
                                    datos_extraidos["imp_cobrado"] = "N/A"
                                    datos_extraidos["baremo"] = "0,00"
                                    datos_extraidos["base"] = "0,00"
                                    datos_extraidos["total"] = "0,00"
                                    
                                # Acumular el total a cobrar convirtiéndolo a float (reemplazando coma por punto)
                                val_total_str = datos_extraidos.get("total", "0,00").replace(".", "").replace(",", ".")
                                try:
                                    suma_total_cobrar += float(val_total_str)
                                except ValueError:
                                    pass
                                break
                        break
                
                if encontrado:
                    pagados.append({"codigo": codigo, "datos": datos_extraidos})
                else:
                    no_pagados.append(codigo)

            os.makedirs(CARPETA_RESULTADOS, exist_ok=True)

            # Nomenclatura correlativa por fecha (ej: 05/Agost_001)
            fecha_actual = datetime.now()
            meses_es = {
                1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                7: "Jul", 8: "Agost", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
            }
            dia_str = fecha_actual.strftime("%d")
            mes_str = meses_es.get(fecha_actual.month, fecha_actual.strftime("%b"))
            prefijo_fecha = f"{dia_str}_{mes_str}"

            archivos_existentes = os.listdir(CARPETA_RESULTADOS)
            contador = 1
            for archivo_ex in archivos_existentes:
                if archivo_ex.startswith(prefijo_fecha) and archivo_ex.endswith(".txt"):
                    contador += 1

            sufijo_correlativo = f"{contador:03d}"
            nombre_archivo_salida = f"{prefijo_fecha}_{sufijo_correlativo}.txt"
            self.ultima_ruta_salida = os.path.join(CARPETA_RESULTADOS, nombre_archivo_salida)
            
            with open(self.ultima_ruta_salida, "w", encoding="utf-8") as f:
                f.write("==================================================\n")
                f.write("      INFORME DE VERIFICACIÓN DE PAGOS SEPARADO   \n")
                f.write("==================================================\n\n")
                
                f.write(f"--- [✔] PAGADOS ({len(pagados)}) ---\n")
                if pagados:
                    for item in pagados:
                        f.write(f"  • Código: {item['codigo']}\n")
                        f.write(f"    - Importe cobrado al cliente: {item['datos'].get('imp_cobrado', 'N/A')}\n")
                        f.write(f"    - Baremo de referencia:       {item['datos'].get('baremo', 'N/A')}\n")
                        f.write(f"    - Base imponible:             {item['datos'].get('base', 'N/A')}\n")
                        f.write(f"    - Total a cobrar:             {item['datos'].get('total', 'N/A')}\n\n")
                    
                    # Formatear la suma total de vuelta al formato con coma decimal
                    suma_formateada = f"{suma_total_cobrar:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    f.write(f"==================================================\n")
                    f.write(f"  SUMA TOTAL DE TOTALES A COBRAR: {suma_formateada}\n")
                    f.write(f"==================================================\n\n")
                else:
                    f.write("  (Ninguno)\n\n")
                
                f.write(f"--- [❌] AÚN NO PAGADOS ({len(no_pagados)}) ---\n")
                if no_pagados:
                    for cod in no_pagados:
                        f.write(f"  • {cod}\n")
                else:
                    f.write("  (Ninguno)\n")

            # Construir texto para mostrar en pantalla de la app
            texto_pantalla = f"=== [✔] PAGADOS ({len(pagados)}) ===\n"
            if pagados:
                for item in pagados:
                    texto_pantalla += f"• Código: {item['codigo']}\n"
                    texto_pantalla += f"  Imp. Cobrado Cliente: {item['datos'].get('imp_cobrado', 'N/A')}\n"
                    texto_pantalla += f"  Baremo Referencia:    {item['datos'].get('baremo', 'N/A')}\n"
                    texto_pantalla += f"  Base Imponible:       {item['datos'].get('base', 'N/A')}\n"
                    texto_pantalla += f"  Total a Cobrar:       {item['datos'].get('total', 'N/A')}\n\n"
                
                suma_formateada = f"{suma_total_cobrar:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                texto_pantalla += f"--------------------------------------------------\n"
                texto_pantalla += f"SUMA TOTAL DE TOTALES A COBRAR: {suma_formateada}\n"
                texto_pantalla += f"--------------------------------------------------\n\n"
            else:
                texto_pantalla += "(Ninguno)\n\n"

            texto_pantalla += f"=== [❌] AÚN NO PAGADOS ({len(no_pagados)}) ===\n" + ("\n".join([f"• {c}" for c in no_pagados]) if no_pagados else "(Ninguno)")
            texto_pantalla += f"\n\n[✔] Archivo TXT guardado:\n{nombre_archivo_salida}"

            self.txt_resultados.configure(state="normal")
            self.txt_resultados.delete("1.0", "end")
            self.txt_resultados.insert("1.0", texto_pantalla)
            self.txt_resultados.configure(text_color=("black", "white"))
            
            self.btn_abrir_carpeta.configure(state="normal", fg_color="#1f6aa5", hover_color="#144875")
            
            messagebox.showinfo("Éxito", f"Verificación completada. Guardado como: {nombre_archivo_salida}")

        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un error: {e}")

    def abrir_carpeta_destino(self):
        if os.path.exists(CARPETA_RESULTADOS):
            os.startfile(CARPETA_RESULTADOS)
        else:
            messagebox.showwarning("Aviso", "La carpeta de resultados aún no ha sido creada.")