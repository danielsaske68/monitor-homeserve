import customtkinter as ctk
import threading
import subprocess
import time

from cloud.railway_app import (
    iniciar_servidor,
    loop,
    monitor_webhook,
    volver_a_railway,
    obtener_usuarios
)
from cloud.control import estado
import cloud.control as control


class ServidorLocalFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="#101820")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=0, column=0, sticky="nsew")

        panel = ctk.CTkFrame(outer, fg_color="#171f2a", corner_radius=20, border_width=1, border_color="#2d435d")
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        panel.grid_columnconfigure(0, weight=1)

        titulo = ctk.CTkLabel(
            panel,
            text="☁️ SERVIDOR LOCAL",
            font=("Arial", 30, "bold"),
            text_color="#4ea3ff"
        )
        titulo.grid(row=0, column=0, pady=(24, 18), sticky="n")

        content = ctk.CTkFrame(panel, fg_color="transparent")
        content.grid(row=1, column=0, sticky="n")

        self.estado_frame = ctk.CTkFrame(content, fg_color="transparent")
        self.estado_frame.pack(anchor="center", pady=(0, 12))

        self.luz_estado = ctk.CTkLabel(self.estado_frame, text="●", font=("Arial", 18), text_color="red")
        self.luz_estado.pack(side="left", padx=(0, 8))

        self.estado = ctk.CTkLabel(self.estado_frame, text="Estado general: Apagado", font=("Arial", 18), text_color="#edf4ff")
        self.estado.pack(side="left")

        status_box = ctk.CTkFrame(content, fg_color="transparent")
        status_box.pack(anchor="center", pady=(0, 18))

        def crear_piloto(parent, texto):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            luz = ctk.CTkLabel(frame, text="●", font=("Arial", 18), text_color="#7a7a7a")
            luz.pack(side="left", padx=(0, 8))
            label = ctk.CTkLabel(frame, text=texto, font=("Arial", 18), text_color="#f0f6ff")
            label.pack(side="left")
            frame.pack(anchor="center", pady=6)
            return luz, label

        self.luz_flask, self.piloto_flask = crear_piloto(status_box, "Servidor Flask apagado")
        self.luz_ngrok, self.piloto_ngrok = crear_piloto(status_box, "Ngrok cerrado")
        self.luz_telegram, self.piloto_telegram = crear_piloto(status_box, "Telegram sin conexión")
        self.luz_railway, self.piloto_railway = crear_piloto(status_box, "Railway")

        btn_style = dict(width=430, height=40, corner_radius=10, fg_color="#0f6cbd", hover_color="#0d5ea8", font=("Arial", 13, "bold"), text_color="#edf4ff")

        self.btn_iniciar = ctk.CTkButton(content, text="▶ Iniciar servidor", command=self.iniciar, **btn_style)
        self.btn_iniciar.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_railway = ctk.CTkButton(content, text="☁️ Volver a Railway", command=self.railway, **btn_style)
        self.btn_railway.pack(fill="x", padx=14, pady=10)

        self.btn_detener = ctk.CTkButton(content, text="⛔ Detener", command=self.detener, **btn_style)
        self.btn_detener.pack(fill="x", padx=14, pady=10)

        self.actualizar_pilotos()

        


    def iniciar(self):

        if control.servidor_activo:
            return

        control.servidor_activo = True
        estado["servidor"] = True


        control.ngrok_proceso = subprocess.Popen(
            [
                "ngrok",
                "http",
                "10000"
            ],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

        estado["ngrok"] = True
        estado["telegram"] = True
        estado["railway"] = False

        self.luz_railway.configure(
            text_color="red"
        )

        self.piloto_railway.configure(
            text="Railway desconectado"
        )

        def iniciar_loop_local():

            from cloud.railway_app import homeserve

            print("LOGIN INICIAL LOCAL")

            resultado = homeserve.login()

            print("LOGIN RESULTADO:", resultado)

            loop()


        threading.Thread(
            target=iniciar_loop_local,
            daemon=True
        ).start()

        threading.Thread(
            target=iniciar_servidor,
            daemon=True
        ).start()


        threading.Thread(
            target=monitor_webhook,
            daemon=True
        ).start()


        self.actualizar_pilotos()



    def actualizar_pilotos(self):

        if estado["servidor"]:

            self.luz_flask.configure(
                text_color="green"
            )

            self.piloto_flask.configure(
                text="Servidor Flask activo"
            )

            self.luz_ngrok.configure(
                text_color="green"
            )

            self.piloto_ngrok.configure(
                text="Ngrok conectado"
            )

            self.luz_telegram.configure(
                text_color="green"
            )

            self.piloto_telegram.configure(
                text="Telegram Local activo"
            )

            self.luz_estado.configure(
                text_color="green"
            )

            self.estado.configure(
                text="Estado general: Servidor Local funcionando"
            )

        else:

            self.luz_flask.configure(
                text_color="red"
            )

            self.piloto_flask.configure(
                text="Servidor Flask apagado"
            )

            self.luz_ngrok.configure(
                text_color="red"
            )

            self.piloto_ngrok.configure(
                text="Ngrok cerrado"
            )

            self.luz_telegram.configure(
                text_color="red"
            
            )
            self.piloto_telegram.configure(
                text="Telegram sin conexión"
            )


            self.luz_estado.configure(
                text_color="red"
            )

            self.estado.configure(
                text="Estado general: Apagado"
            )


        self.after(
            1000,
            self.actualizar_pilotos
        )


    def railway(self):

        volver_a_railway()

        estado["railway"] = True
        estado["telegram"] = False

        control.servidor_activo = False

        self.luz_railway.configure(
            text_color="green"
        )

        self.piloto_railway.configure(
            text="Railway activo"
        )

        self.actualizar_pilotos()


    def detener(self):

        if control.ngrok_proceso:
            control.ngrok_proceso.kill()
            control.ngrok_proceso = None

        control.servidor_activo = False

        estado["servidor"] = False
        estado["ngrok"] = False
        estado["telegram"] = False
        estado["railway"] = True

        self.actualizar_pilotos()