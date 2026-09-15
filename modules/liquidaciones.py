import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from tkcalendar import DateEntry
import os
import sys
import json
import subprocess
import locale
from datetime import datetime

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==============================================================
# PALETA
# ==============================================================
COLOR_BG        = "#101820"
COLOR_CARD      = "#171f2a"
COLOR_CARD_ALT  = "#1d2733"
COLOR_BORDER    = "#2d435d"
COLOR_ROW       = "#1d2733"
COLOR_BLUE      = "#0f6cbd"
COLOR_BLUE_HOV  = "#0d5ea8"
COLOR_RED       = "#d63031"
COLOR_RED_HOV   = "#b71c1c"
COLOR_GRAY_BTN  = "#3d4b59"
COLOR_GRAY_HOV  = "#4f5e70"
COLOR_GREEN     = "#2dd881"
COLOR_TEXT      = "#edf4ff"
COLOR_MUTED     = "#9bb7d3"


class LiquidacionesFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=COLOR_BG)
        self.CARPETA_PDF = "liquidaciones_pdf"
        self.CARPETA_DATA = os.path.join(self.CARPETA_PDF, "data")
        os.makedirs(self.CARPETA_PDF, exist_ok=True)
        os.makedirs(self.CARPETA_DATA, exist_ok=True)
        self.pack(fill="both", expand=True)

        self._cargando = False           # evita autosave durante load
        self._mes_actual = None          # mes cargado actualmente

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ================= HEADER =================
        self.header = ctk.CTkFrame(
            self, fg_color="#121b29", corner_radius=18,
            border_width=1, border_color=COLOR_BORDER,
        )
        self.header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 12))
        self.header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.header, text="💰  LIQUIDACIÓN MENSUAL",
            font=("Segoe UI", 28, "bold"), text_color="#4ea3ff",
        ).grid(row=0, column=0, pady=(18, 6))

        self.mes_seleccionado = ctk.CTkComboBox(
            self.header,
            values=["------ Seleccione Fecha ---------", "ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
                    "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"],
            width=200, height=34, corner_radius=10,
            button_color=COLOR_BLUE, button_hover_color=COLOR_BLUE_HOV,
            border_color=COLOR_BORDER,
            command=self._on_cambio_mes,
        )
        self.mes_seleccionado.set("------ Seleccione Fecha ---------")
        self.mes_seleccionado.grid(row=1, column=0, pady=(0, 18))

        # ================= BODY (3 columnas) =================
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        for i in range(3):
            self.body.grid_columnconfigure(i, weight=1, uniform="cols")
        self.body.grid_rowconfigure(0, weight=1)

        # ---------- COLUMNA 1 ----------
        self.col1 = ctk.CTkFrame(self.body, fg_color="transparent")
        self.col1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.col1.grid_columnconfigure(0, weight=1)
        self.col1.grid_rowconfigure(1, weight=1)   # gastos fijos crece

        # --- Tarjeta FIJA: Datos principales + Recibo ---
        card_datos = ctk.CTkFrame(
            self.col1, fg_color="#1b2530", corner_radius=18,
            border_width=1, border_color=COLOR_BORDER,
        )
        card_datos.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(
            card_datos, text="  📋  DATOS PRINCIPALES",
            font=("Segoe UI", 15, "bold"), text_color="#4ea3ff", anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 6))

        inner = ctk.CTkFrame(
            card_datos, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color=COLOR_BORDER,
        )
        inner.pack(fill="x", padx=10, pady=(0, 10))

        self._label(inner, "Base Factura").pack(anchor="w", padx=12, pady=(12, 4))
        self.e_base = self._entry(inner); self.e_base.pack(fill="x", padx=12)
        self.e_base.bind("<KeyRelease>", self._on_edit)

        self._label(inner, "Transferencia").pack(anchor="w", padx=12, pady=(12, 4))
        self.e_trans = self._entry(inner); self.e_trans.pack(fill="x", padx=12, pady=(0, 12))
        self.e_trans.bind("<KeyRelease>", self._on_edit)

        recibo_box = ctk.CTkFrame(
            card_datos, fg_color="#0f2540", corner_radius=12,
            border_width=1, border_color="#1e3a5f",
        )
        recibo_box.pack(fill="x", padx=10, pady=(0, 12))
        self.lbl_recibo = ctk.CTkLabel(
            recibo_box, text="🧾   RECIBO: 0.00",
            font=("Segoe UI", 18, "bold"), text_color="#4ea3ff",
        )
        self.lbl_recibo.pack(pady=14)

        # --- Tarjeta SEPARADA con scroll: Gastos fijos ---
        card_fijos = ctk.CTkFrame(
            self.col1, fg_color="#1b2530", corner_radius=18,
            border_width=1, border_color=COLOR_BORDER,
        )
        card_fijos.grid(row=1, column=0, sticky="nsew")
        card_fijos.grid_rowconfigure(1, weight=1)
        card_fijos.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_fijos, text="  🏠  GASTOS FIJOS",
            font=("Segoe UI", 14, "bold"), text_color="#4ea3ff", anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))

        scroll_fijos = ctk.CTkScrollableFrame(
            card_fijos, fg_color=COLOR_CARD, corner_radius=12,
            border_color=COLOR_BORDER,
        )
        scroll_fijos.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.cont_fijos = scroll_fijos  # las filas se crean aquí dentro

        self._btn_azul(
            card_fijos, "＋  Añadir gasto fijo",
            lambda: self.ventana_nuevo_registro("fijo")
        ).grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        # ---------- COLUMNA 2: VARIABLES (3 tarjetas independientes) ----------
        self.col2 = ctk.CTkFrame(self.body, fg_color="transparent")
        self.col2.grid(row=0, column=1, sticky="nsew", padx=6)
        self.col2.grid_columnconfigure(0, weight=1)
        for r in range(3):
            self.col2.grid_rowconfigure(r, weight=1, uniform="v")

        self.cont_mat = self._card_scroll(
            self.col2, "  📦  MATERIAL", "＋  Añadir material",
            lambda: self.ventana_nuevo_registro("material"), row=0,
        )
        self.cont_comb = self._card_scroll(
            self.col2, "  ⛽  COMBUSTIBLE", "＋  Añadir combustible",
            lambda: self.ventana_nuevo_registro("combustible"), row=1,
        )
        self.cont_ajustes = self._card_scroll(
            self.col2, "  🔧  AJUSTES MES ANTERIOR", "＋  Añadir ajuste",
            lambda: self.ventana_nuevo_registro("ajuste"), row=2,
        )

        # ---------- COLUMNA 3: EXTRAS ----------
        self.col3 = ctk.CTkScrollableFrame(
            self.body,
            label_text="  ⭐  EXTRAS",
            label_font=("Segoe UI", 15, "bold"),
            label_text_color="#4ea3ff",
            label_fg_color="#1b2530",
            corner_radius=18, fg_color="#1b2530",
            border_width=1, border_color=COLOR_BORDER,
        )
        self.col3.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        self._btn_azul(self.col3, "＋  TF / Bizum",
                       lambda: self.add_extra("Bizum")).pack(fill="x", padx=6, pady=(6, 4))
        self._btn_azul(self.col3, "＋  Efectivo",
                       lambda: self.add_extra("Efectivo")).pack(fill="x", padx=6, pady=(6, 4))
        self.cont_ext = self._contenedor_rows(self.col3)

        # ================= FOOTER =================
        self.footer = ctk.CTkFrame(
            self, fg_color="#121b29", corner_radius=18,
            border_width=1, border_color=COLOR_BORDER, height=90,
        )
        self.footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 18))
        self.footer.grid_columnconfigure(0, weight=1)

        self.lbl_mio = ctk.CTkLabel(
            self.footer, text="💰  MIO: 0.00 €",
            font=("Segoe UI", 28, "bold"), text_color=COLOR_GREEN,
        )
        self.lbl_mio.grid(row=0, column=0, sticky="w", padx=20, pady=18)

        ctk.CTkButton(
            self.footer, text="📄  GENERAR PDF", command=self.generar_pdf,
            width=170, height=44, corner_radius=10,
            fg_color=COLOR_BLUE, hover_color=COLOR_BLUE_HOV,
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=1, padx=(10, 8), pady=18)

        ctk.CTkButton(
            self.footer, text="📁  IR A CARPETA", command=self.abrir_carpeta,
            width=160, height=44, corner_radius=10,
            fg_color=COLOR_GRAY_BTN, hover_color=COLOR_GRAY_HOV,
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=2, padx=(0, 20), pady=18)
       

    # ==============================================================
    # HELPERS UI
    # ==============================================================
    def _label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, font=("Segoe UI", 13),
                            text_color=COLOR_MUTED, anchor="w")

    def _entry(self, parent):
        return ctk.CTkEntry(parent, height=38, corner_radius=8,
                            fg_color="#151515", border_color=COLOR_BORDER,
                            text_color=COLOR_TEXT, font=("Segoe UI", 13))

    def _btn_azul(self, parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command,
                             height=40, corner_radius=10,
                             fg_color=COLOR_BLUE, hover_color=COLOR_BLUE_HOV,
                             font=("Segoe UI", 13, "bold"))

    def formato_fecha(self, fecha):
        try:
            if isinstance(fecha, str):
                fecha = fecha.strip()

                formatos = [
                    "%d/%m/%Y",
                    "%d/%b/%Y",
                    "%d/%B/%Y"
                ]

                fecha_obj = None

                for f in formatos:
                    try:
                        fecha_obj = datetime.strptime(fecha, f)
                        break
                    except:
                        pass

                if not fecha_obj:
                    return fecha

            else:
                fecha_obj = fecha


            meses = [
                "Ene", "Feb", "Mar", "Abr",
                "May", "Jun", "Jul", "Ago",
                "Sep", "Oct", "Nov", "Dic"
            ]

            return f"{fecha_obj.day}/{meses[fecha_obj.month-1]}/{fecha_obj.year}"

        except:
            return fecha


    def ventana_nuevo_registro(self, tipo):
        ventana = ctk.CTkToplevel(self)
        ventana.title("Añadir")
        ventana.geometry("320x260")
        ventana.resizable(False, False)


        # CENTRAR VENTANA EN PANTALLA
        ventana.update_idletasks()

        ancho = 320
        alto = 260

        x = (ventana.winfo_screenwidth() // 2) - (ancho // 2) + 250
        y = (ventana.winfo_screenheight() // 2) - (alto // 2) + 100


        ventana.geometry(f"{ancho}x{alto}+{x}+{y}")

        ventana.grab_set()
        ventana.lift()
        ventana.focus_force()


        if tipo == "fijo":

            ctk.CTkLabel(
                ventana,
                text="Nombre"
            ).pack(anchor="w", padx=30)

            e_nombre = ctk.CTkEntry(ventana)
            e_nombre.pack(fill="x", padx=30, pady=5)


            ctk.CTkLabel(
                ventana,
                text="Importe"
            ).pack(anchor="w", padx=30)

            e_importe = ctk.CTkEntry(ventana)
            e_importe.pack(fill="x", padx=30, pady=5)


        elif tipo in ("material", "combustible"):

            ctk.CTkLabel(
                ventana,
                text="Importe"
            ).pack(anchor="w", padx=30)

            e_importe = ctk.CTkEntry(ventana)
            e_importe.pack(fill="x", padx=30, pady=5)


        elif tipo == "ajuste":

            ctk.CTkLabel(
                ventana,
                text="Concepto"
            ).pack(anchor="w", padx=30)

            e_nombre = ctk.CTkEntry(ventana)
            e_nombre.insert(0, "Mes anterior")
            e_nombre.configure(state="disabled")
            e_nombre.pack(fill="x", padx=30, pady=5)


            ctk.CTkLabel(
                ventana,
                text="Importe"
            ).pack(anchor="w", padx=30)

            e_importe = ctk.CTkEntry(ventana)
            e_importe.pack(fill="x", padx=30, pady=5)



        def guardar():

            importe = e_importe.get()

            if tipo == "fijo":
                self.crear_fila_fijo(
                    e_nombre.get(),
                    importe
                )

            elif tipo == "material":
                e = self.add_fila_doble(self.cont_mat)
                e.insert(0, importe)


            elif tipo == "combustible":
                e = self.add_fila_doble(self.cont_comb)
                e.insert(0, importe)


            elif tipo == "ajuste":
                self.add_ajuste_mes(
                    "Mes anterior",
                    importe
                )


            self.calcular()
            self._autosave()
            ventana.destroy()



        botones = ctk.CTkFrame(
            ventana,
            fg_color="transparent"
        )
        botones.pack(pady=20)


        ctk.CTkButton(
            botones,
            text="GUARDAR",
            command=guardar,
            fg_color=COLOR_BLUE
        ).pack(side="left", padx=10)


        ctk.CTkButton(
            botones,
            text="CANCELAR",
            fg_color=COLOR_RED,
            command=ventana.destroy
        ).pack(side="left", padx=10)

    def _contenedor_rows(self, parent):
        cont = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=10,
                            border_width=1, border_color=COLOR_BORDER)
        cont.pack(fill="x", padx=6, pady=(0, 6))
        return cont

    def _card_scroll(self, parent, titulo, btn_txt, btn_cmd, row):
        """Tarjeta con título + scroll interno + botón añadir. Devuelve el scroll."""
        card = ctk.CTkFrame(parent, fg_color=COLOR_CARD_ALT, corner_radius=18,
                            border_width=1, border_color=COLOR_BORDER)
        card.grid(row=row, column=0, sticky="nsew", pady=(0, 8) if row < 2 else 0)
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=titulo, font=("Segoe UI", 14, "bold"),
                     text_color="#4ea3ff", anchor="w"
                     ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        scroll = ctk.CTkScrollableFrame(card, fg_color=COLOR_CARD,
                                        corner_radius=12, border_color=COLOR_BORDER)
        scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        self._btn_azul(card, btn_txt, btn_cmd).grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        return scroll

    # ==============================================================
    # LÓGICA (sin cambios funcionales)
    # ==============================================================
    def _on_edit(self, *a):
        self.calcular()
        self._autosave()

    def limpiar(self, val):
        texto = str(val.get() if hasattr(val, 'get') else val).replace(',', '.').strip()
        try: return float(texto)
        except ValueError: return 0.0

    def add_fila_doble(self, p):
        f = ctk.CTkFrame(p, fg_color=COLOR_ROW, corner_radius=8)
        f.pack(fill="x", pady=3, padx=4)
        e = ctk.CTkEntry(f, height=30, corner_radius=6, fg_color="#151515",
                         border_color=COLOR_BORDER)
        e.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        e.bind("<KeyRelease>", self._on_edit)
        ctk.CTkButton(f, text="✕", fg_color=COLOR_RED, hover_color=COLOR_RED_HOV,
                      width=32, corner_radius=8,
                      command=lambda: [f.destroy(), self._on_edit()]
                      ).pack(side="right", padx=4, pady=4)
        return e

    def add_ajuste_mes(self, nombre="Mes anterior", valor="0"):
        f = ctk.CTkFrame(self.cont_ajustes, fg_color=COLOR_ROW, corner_radius=8)
        f.pack(fill="x", pady=3, padx=4)
        e_n = ctk.CTkEntry(f, width=140, height=30, corner_radius=6,
                           fg_color="#151515", border_color=COLOR_BORDER)
        e_n.insert(0, nombre); e_n.pack(side="left", padx=6, pady=6)
        e_n.bind("<KeyRelease>", self._on_edit)
        e = ctk.CTkEntry(f, width=70, height=30, corner_radius=6,
                         fg_color="#151515", border_color=COLOR_BORDER)
        e.insert(0, valor); e.pack(side="left", padx=4, pady=6)
        e.bind("<KeyRelease>", self._on_edit)
        ctk.CTkButton(f, text="✕", fg_color=COLOR_RED, hover_color=COLOR_RED_HOV,
                      width=32, corner_radius=8,
                      command=lambda: [f.destroy(), self._on_edit()]
                      ).pack(side="right", padx=6, pady=6)

    def add_extra(self, t, neto="", iva="", irpf="", res="", fecha=None):
        f = ctk.CTkFrame(self.cont_ext, fg_color=COLOR_ROW, corner_radius=8)
        f.pack(fill="x", pady=4, padx=4)
        cab = ctk.CTkFrame(f, fg_color="transparent"); cab.pack(fill="x", padx=4, pady=(4, 0))
        for txt in ["NETO", "IVA", "IRPF", "RESULTADO"]:
            ctk.CTkLabel(cab, text=txt, width=65, text_color=COLOR_MUTED,
                         font=("Segoe UI", 10, "bold")).pack(side="left", padx=2)
        fila = ctk.CTkFrame(f, fg_color="transparent"); fila.pack(fill="x", padx=4, pady=(0, 4))
        c = {"n": ctk.CTkEntry(fila, width=65), "iva": ctk.CTkEntry(fila, width=65),
             "irpf": ctk.CTkEntry(fila, width=65), "res": ctk.CTkEntry(fila, width=70)}
        for v, k in zip([neto, iva, irpf, res], ["n", "iva", "irpf", "res"]):
            if v != "": c[k].insert(0, str(v))
            c[k].pack(side="left", padx=2)

        de = DateEntry(
            fila,
            width=12,
            date_pattern="d/mm/yyyy"
        )

        if fecha:
            try: de.set_date(fecha)
            except Exception: pass
        de.pack(side="left", padx=4)
        ctk.CTkButton(fila, text="✕", width=30, fg_color=COLOR_RED,
                      hover_color=COLOR_RED_HOV,
                      command=lambda: [f.destroy(), self._on_edit()]).pack(side="right")
        c["n"].bind("<KeyRelease>", lambda e: [self.calc_extra(t, c), self._autosave()])
        f.c = c; f.t = t

    def crear_fila_fijo(self, nombre="", importe=""):
        f = ctk.CTkFrame(self.cont_fijos, fg_color=COLOR_ROW, corner_radius=8)
        f.pack(fill="x", pady=3, padx=4)
        e_n = ctk.CTkEntry(f, height=30, corner_radius=6, fg_color="#151515",
                           border_color=COLOR_BORDER, font=("Segoe UI", 11))
        e_n.insert(0, nombre)
        e_n.pack(side="left", fill="x", expand=True, padx=(6, 4), pady=6)
        e_n.bind("<KeyRelease>", self._on_edit)
        e_v = ctk.CTkEntry(f, width=70, height=30, corner_radius=6, justify="center",
                           fg_color="#151515", border_color=COLOR_BORDER,
                           font=("Segoe UI", 11, "bold"))
        e_v.insert(0, importe)
        e_v.pack(side="left", padx=4, pady=6)
        e_v.bind("<KeyRelease>", self._on_edit)
        ctk.CTkButton(f, text="✕", width=32, corner_radius=8,
                      fg_color=COLOR_RED, hover_color=COLOR_RED_HOV,
                      command=lambda: [f.destroy(), self._on_edit()]
                      ).pack(side="right", padx=6, pady=6)
        self.calcular()

    def calc_extra(self, t, c):
        n = self.limpiar(c["n"])
        res = (n - (n * 0.20)) if t == "Bizum" else (n * 0.21 + n * 0.20) * -1
        for k, v in zip(["iva", "irpf", "res"], [n * 0.21, n * 0.20, res]):
            c[k].delete(0, tk.END); c[k].insert(0, f"{v:.2f}")
        self.calcular()

    def calcular(self, *args):
        try:
            bs, tr = self.limpiar(self.e_base), self.limpiar(self.e_trans)
            def s(p, idx): return sum(self.limpiar(w.winfo_children()[idx]) for w in p.winfo_children())
            f = s(self.cont_fijos, 1); a = s(self.cont_ajustes, 1)
            mat = s(self.cont_mat, 0); comb = s(self.cont_comb, 0) / 2
            rec = tr - (bs * 0.21 + (bs - (mat + comb)) * 0.20)
            ex = sum(self.limpiar(w.c["res"]) for w in self.cont_ext.winfo_children() if hasattr(w, "c"))
            self.lbl_recibo.configure(text=f"🧾   RECIBO: {rec:.2f}")
            self.lbl_mio.configure(text=f"💰  MIO: {rec - f + ex + a:.2f} €")
        except: pass

    def numero(self, w):
        try:
            val = w.get() if hasattr(w, 'get') else w
            return float(str(val).replace('€', '').replace(',', '.').strip())
        except: return 0.0

    # ==============================================================
    # PERSISTENCIA POR MES
    # ==============================================================
    def _ruta_mes(self, mes):
        return os.path.join(self.CARPETA_DATA, f"{mes.upper()}.json")

    def _on_cambio_mes(self, nuevo_mes):

        if nuevo_mes == "------ Seleccione Fecha ---------":
            return

        if self._mes_actual and self._mes_actual != nuevo_mes:
            self._guardar_mes(self._mes_actual)

        self._cargar_mes(nuevo_mes)

    def _autosave(self):
        if self._cargando or not self._mes_actual: return
        try: self._guardar_mes(self._mes_actual)
        except Exception: pass

    def _snapshot(self):
        def rows_doble(p):
            out = []
            for w in p.winfo_children():
                hijos = w.winfo_children()
                if hijos: out.append(hijos[0].get())
            return out
        fijos = [(w.winfo_children()[0].get(), w.winfo_children()[1].get())
                 for w in self.cont_fijos.winfo_children()]
        ajustes = [(w.winfo_children()[0].get(), w.winfo_children()[1].get())
                   for w in self.cont_ajustes.winfo_children()]
        extras = []
        for w in self.cont_ext.winfo_children():
            if not hasattr(w, "c"): continue
            fecha = ""
            for x in w.winfo_children():
                for y in x.winfo_children() if hasattr(x, "winfo_children") else []:
                    if isinstance(y, DateEntry):
                        try: fecha = fecha = self.formato_fecha(y.get_date())
                        except Exception: fecha = ""
            extras.append({
                "tipo": w.t,
                "neto": w.c["n"].get(), "iva": w.c["iva"].get(),
                "irpf": w.c["irpf"].get(), "res": w.c["res"].get(),
                "fecha": fecha,
            })
        return {
            "base": self.e_base.get(),
            "transferencia": self.e_trans.get(),
            "material": rows_doble(self.cont_mat),
            "combustible": rows_doble(self.cont_comb),
            "fijos": fijos, "ajustes": ajustes, "extras": extras,
        }

    def _guardar_mes(self, mes):
        with open(self._ruta_mes(mes), "w", encoding="utf-8") as fh:
            json.dump(self._snapshot(), fh, ensure_ascii=False, indent=2)

    def _limpiar_contenedor(self, cont):
        for w in list(cont.winfo_children()): w.destroy()

    def _cargar_mes(self, mes):
        self._cargando = True
        try:
            self._limpiar_contenedor(self.cont_fijos)
            self._limpiar_contenedor(self.cont_mat)
            self._limpiar_contenedor(self.cont_comb)
            self._limpiar_contenedor(self.cont_ajustes)
            self._limpiar_contenedor(self.cont_ext)
            self.e_base.delete(0, tk.END); self.e_trans.delete(0, tk.END)

            ruta = self._ruta_mes(mes)
            if os.path.exists(ruta):
                with open(ruta, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                self.e_base.insert(0, d.get("base", ""))
                self.e_trans.insert(0, d.get("transferencia", ""))
                for n, v in d.get("fijos", []): self.crear_fila_fijo(n, v)
                for v in d.get("material", []):
                    e = self.add_fila_doble(self.cont_mat); e.insert(0, v)
                for v in d.get("combustible", []):
                    e = self.add_fila_doble(self.cont_comb); e.insert(0, v)
                for n, v in d.get("ajustes", []): self.add_ajuste_mes(n, v)
                for ex in d.get("extras", []):
                    fecha = None
                    if ex.get("fecha"):
                        from datetime import date
                        try: fecha = date.fromisoformat(ex["fecha"])
                        except Exception: fecha = None
                    self.add_extra(ex.get("tipo", "Bizum"),
                                   ex.get("neto", ""), ex.get("iva", ""),
                                   ex.get("irpf", ""), ex.get("res", ""), fecha)
            else:
                # defaults primera vez
                for n, imp in [("Internet", "20"), ("Autónomo", "120"),
                               ("Gestor", "80"), ("Vuelo", "102")]:
                    self.crear_fila_fijo(n, imp)

            self._mes_actual = mes
            self.calcular()
        finally:
            self._cargando = False

    # ==============================================================
    # OBTENER DATOS + PDF (sin cambios funcionales)
    # ==============================================================
    def obtener_datos(self):
        datos = {}
        datos["base"] = self.numero(self.e_base)
        datos["transferencia"] = self.numero(self.e_trans)
        datos["mes"] = self.mes_seleccionado.get().upper()
        materiales = []; total_material = 0
        for fila in self.cont_mat.winfo_children():
            if len(fila.winfo_children()) == 0: continue
            importe = self.numero(fila.winfo_children()[0])
            materiales.append({"descripcion": "Material", "importe": importe})
            total_material += importe
        datos["materiales"] = materiales
        datos["total_material"] = total_material
        combustible = []; total_comb = 0
        for fila in self.cont_comb.winfo_children():
            if len(fila.winfo_children()) == 0: continue
            importe = self.numero(fila.winfo_children()[0])
            combustible.append({"descripcion": "Ticket", "importe": importe})
            total_comb += importe
        datos["combustible"] = combustible
        datos["total_combustible"] = total_comb
        fijos = []; total_fijos = 0
        for fila in self.cont_fijos.winfo_children():
            nombre = fila.winfo_children()[0].get()
            importe = self.numero(fila.winfo_children()[1])
            fijos.append({"nombre": nombre, "importe": importe})
            total_fijos += importe
        datos["gastos_fijos"] = fijos; datos["total_fijos"] = total_fijos
        ajustes = []; total_ajustes = 0
        for fila in self.cont_ajustes.winfo_children():
            nombre = fila.winfo_children()[0].get()
            importe = self.numero(fila.winfo_children()[1])
            ajustes.append({"nombre": nombre, "importe": importe})
            total_ajustes += importe
        datos["ajustes"] = ajustes; datos["total_ajustes"] = total_ajustes
        extras = []; total_extras = 0
        for fila in self.cont_ext.winfo_children():
            if not hasattr(fila, "c"): continue
            fecha = ""
            for x in fila.winfo_children():
                for y in x.winfo_children() if hasattr(x, "winfo_children") else []:
                    if isinstance(y, DateEntry): fecha = self.formato_fecha(y.get())
            restante = self.numero(fila.c["res"])
            extras.append({"fecha": fecha, "tipo": fila.t,
                           "neto": self.numero(fila.c["n"]),
                           "iva": self.numero(fila.c["iva"]),
                           "irpf": self.numero(fila.c["irpf"]),
                           "restante": restante})
            total_extras += restante
        datos["extras"] = extras; datos["total_extras"] = total_extras
        datos["restando"] = datos["base"] - datos["total_material"] - datos["total_combustible"] / 2
        datos["iva"] = datos["base"] * 0.21
        datos["irpf"] = datos["restando"] * 0.20
        datos["total_factura"] = datos["base"] * 1.21
        datos["recibo"] = datos["transferencia"] - datos["iva"] - datos["irpf"]
        datos["mio"] = datos["recibo"] - datos["total_fijos"] + datos["total_extras"] + datos["total_ajustes"]
        return datos

    def abrir_carpeta(self):
        path = os.path.realpath(self.CARPETA_PDF)
        if os.name == 'nt': os.startfile(path)
        elif os.uname().sysname == 'Darwin': subprocess.call(["open", path])
        else: subprocess.call(["xdg-open", path])

    def generar_pdf(self):
        try:
            datos = self.obtener_datos()

            # --- 1. OBTENER RUTA BASE REAL (Compatible con PyInstaller / .exe) ---
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))

            cwd_dir = os.getcwd()
            parent_dir = os.path.dirname(base_dir)

            # --- 2. BÚSQUEDA ROBUSTA DEL LOGO ---
            nombres_archivo = ["logo.png", "logo.PNG", "logo.jpg", "logo.jpeg", "LOGO.PNG"]
            rutas_a_probar = [
                base_dir,
                cwd_dir,
                parent_dir,
                r"C:\Users\Admin\Desktop\Pruebas"
            ]

            ruta_logo = None
            for carpeta in rutas_a_probar:
                for nombre in nombres_archivo:
                    # Prueba dentro de la carpeta 'assets'
                    posible_ruta_assets = os.path.join(carpeta, "assets", nombre)
                    if os.path.exists(posible_ruta_assets):
                        ruta_logo = posible_ruta_assets
                        break
                    # Prueba directamente en la raíz por si acaso
                    posible_ruta_raiz = os.path.join(carpeta, nombre)
                    if os.path.exists(posible_ruta_raiz):
                        ruta_logo = posible_ruta_raiz
                        break
                if ruta_logo:
                    break

            # --- 3. CONFIGURACIÓN DE CARPETA Y DOCUMENTO ---
            carpeta_pdf = getattr(self, 'CARPETA_PDF', os.path.join(base_dir, "liquidaciones_pdf"))
            os.makedirs(carpeta_pdf, exist_ok=True)

            mes = self.mes_seleccionado.get().upper()
            filename = os.path.join(carpeta_pdf, f"Liquidacion_{mes}.pdf")

            elements = []
            styles = getSampleStyleSheet()

            # --- 4. INSERTAR LOGO EN EL PDF ---
            if ruta_logo and os.path.exists(ruta_logo):
                img_logo = RLImage(ruta_logo, width=80, height=80)
                img_logo.hAlign = 'CENTER'
                elements.append(img_logo)
                elements.append(Spacer(1, 6))
            else:
                messagebox.showwarning(
                    "Logo no encontrado",
                    f"No se encontró el logo.\nBuscado en: {os.path.join(base_dir, 'assets')}"
                )

            # Título del Informe
            estilo_titulo = ParagraphStyle(
                'TituloPersonalizado', parent=styles['Title'],
                fontSize=18, textColor=colors.black,
                alignment=1, spaceAfter=12
            )
            elements.append(Paragraph(f"INFORME DE LIQUIDACIÓN - {mes}", estilo_titulo))

            # Estilo reutilizable de tablas
            def aplicar_estilo_tabla(t):
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#282828")),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 0), (-1, 0), 8),
                ]))
                return t

            # --- TABLA RESUMEN ---
            bs = datos["base"]; tr = datos["transferencia"]
            tot_fijos = datos["total_fijos"]; tot_ajustes = datos["total_ajustes"]
            restando_gastos = datos["restando"]
            iva_calc = datos["iva"]; irpf_calc = datos["irpf"]
            recibo_final = datos["recibo"]

            data_res = [
                ["CONCEPTO", "VALOR", "RESUMEN", "VALOR"],
                ["BASE IMP.", f"{bs:.2f} €", "REST. GASTOS", f"{restando_gastos:.2f} €"],
                ["IVA (21%)", f"{iva_calc:.2f} €", "IRPF (20%)", f"{irpf_calc:.2f} €"],
                ["TOTAL FACT.", f"{bs + iva_calc:.2f} €", "IVA + IRPF", f"{iva_calc + irpf_calc:.2f} €"],
                ["TRANSFER.", f"{tr:.2f} €", "RECIBO FIN.", f"{recibo_final:.2f} €"]
            ]
            t_res = aplicar_estilo_tabla(Table(data_res, colWidths=[90, 80, 90, 80]))
            t_res.setStyle(TableStyle([
                ('BACKGROUND', (2, 4), (3, 4), colors.yellow),
                ('TEXTCOLOR', (2, 4), (3, 4), colors.black)
            ]))
            elements.append(t_res)
            elements.append(Spacer(1, 20))

            # --- TABLA DESGLOSE DE GASTOS ---
            elements.append(Paragraph("DESGLOSE DE GASTOS", styles["Heading2"]))
            datos_desglose = [["TIPO", "DESCRIPCIÓN", "IMPORTE"]]
            tot_mat = 0; tot_comb = 0

            for w in self.cont_mat.winfo_children():
                if len(w.winfo_children()) > 0:
                    val = self.numero(w.winfo_children()[0])
                    datos_desglose.append(["MATERIAL", "Gasto", f"{val:.2f} €"])
                    tot_mat += val

            for w in self.cont_comb.winfo_children():
                if len(w.winfo_children()) > 0:
                    val = self.numero(w.winfo_children()[0])
                    datos_desglose.append(["COMBUSTIBLE", "Ticket", f"{val:.2f} €"])
                    tot_comb += (val / 2)

            datos_desglose.append(["", "TOTAL MATERIALES", f"{tot_mat:.2f} €"])
            datos_desglose.append(["", "50% COMBUSTIBLE", f"{tot_comb:.2f} €"])
            datos_desglose.append(["", "TOTAL DEDUCIBLE", f"{tot_mat + tot_comb:.2f} €"])
            t_desglose = aplicar_estilo_tabla(Table(datos_desglose, colWidths=[100, 150, 100]))
            t_desglose.setStyle(TableStyle([
                ('BACKGROUND', (1, -1), (2, -1), colors.HexColor("#00FFFF")),
                ('TEXTCOLOR', (1, -1), (2, -1), colors.black)
            ]))
            elements.append(t_desglose)
            elements.append(Spacer(1, 20))

            # --- TABLA GASTOS FIJOS ---
            elements.append(Paragraph("GASTOS FIJOS", styles["Heading2"]))
            datos_fijos = [["CONCEPTO", "IMPORTE"]]
            total_fijos = 0
            for gasto in datos["gastos_fijos"]:
                datos_fijos.append([gasto["nombre"], f'{gasto["importe"]:.2f} €'])
                total_fijos += gasto["importe"]
            datos_fijos.append(["TOTAL GASTOS FIJOS", f"{total_fijos:.2f} €"])

            t_fijos = Table(datos_fijos, colWidths=[200, 100])
            t_fijos.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#282828")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('ALIGN', (0, 1), (0, -2), 'LEFT'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.red),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            elements.append(t_fijos)
            elements.append(Spacer(1, 20))

            # --- TABLA AJUSTES MES ANTERIOR ---
            elements.append(Paragraph("AJUSTES MES ANTERIOR", styles["Heading2"]))
            datos_ajuste = [["CONCEPTO", "IMPORTE"]]
            total_ajustes = sum(self.numero(w.winfo_children()[1]) for w in self.cont_ajustes.winfo_children())
            for ajuste in datos["ajustes"]:
                datos_ajuste.append([ajuste["nombre"], f'{ajuste["importe"]:.2f} €'])
            datos_ajuste.append(["TOTAL AJUSTES", f"{total_ajustes:.2f} €"])

            t_ajuste = Table(datos_ajuste, colWidths=[200, 100])
            t_ajuste.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#282828")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#90EE90")),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
                ('ALIGN', (0, -1), (0, -1), 'LEFT'),
                ('ALIGN', (1, -1), (1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            elements.append(t_ajuste)
            elements.append(Spacer(1, 20))

            # --- TABLA EXTRAS ---
            elements.append(Paragraph("EXTRAS TF / EFECTIVO", styles["Heading2"]))
            datos_ext = [["FECHA", "TIPO", "NETO", "TOTAL"]]
            total_extras = 0
            for extra in datos["extras"]:
                datos_ext.append([
                    extra["fecha"],
                    "TF" if extra["tipo"] == "Bizum" else extra["tipo"],
                    f'{extra["neto"]:.2f} €',
                    f'{extra["restante"]:.2f} €'
                ])
                total_extras += extra["restante"]
            datos_ext.append(["TOTAL NETO", "", "", f"{total_extras:.2f} €"])

            t_ext = Table(datos_ext, colWidths=[80, 80, 80, 80])
            t_ext.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#282828")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#90EE90")),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            elements.append(t_ext)
            elements.append(Spacer(1, 20))

            # --- RESULTADO FINAL (€ MIO) ---
            resultado_mio = tr - (iva_calc + irpf_calc) - total_fijos + total_extras + total_ajustes
            texto_final = f"€ MIO: {resultado_mio:.2f}"
            elements.append(Spacer(1, 10))

            t_mio = Table([[texto_final]], colWidths=[450])
            t_mio.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 22),
                ('TOPPADDING', (0, 0), (-1, -1), 15),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t_mio)

            # --- CONSTRUIR PDF ---
            doc = SimpleDocTemplate(
                filename, pagesize=A4, topMargin=20,
                leftMargin=40, rightMargin=40
            )
            doc.build(elements)

            # Guardar snapshot
            self._guardar_mes(mes)
            messagebox.showinfo("Éxito", f"PDF generado correctamente en:\n{filename}")

        except Exception as e:
            messagebox.showerror("Error", f"Error al generar el PDF: {e}")