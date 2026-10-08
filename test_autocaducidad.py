import base64
import base64
import unittest
from datetime import datetime

from main import (
    calcular_fecha_caducidad,
    extraer_direccion_servicio,
    ordenar_ruta_servicios,
    siguiente_estado_automatico,
    validar_orden_ruta,
)


class AutoCaducidadTests(unittest.TestCase):
    def test_calcular_fecha_caducidad_ignora_fines_de_semana(self):
        self.assertEqual(
            calcular_fecha_caducidad(datetime(2026, 9, 5, 10, 0)),
            datetime(2026, 9, 8, 10, 0).date()
        )

    def test_siguiente_estado_automatico(self):
        self.assertEqual(siguiente_estado_automatico("348"), "318")
        self.assertEqual(siguiente_estado_automatico("320"), "318")
        self.assertEqual(siguiente_estado_automatico("318"), "318")

    def test_extraer_direccion_servicio_nuevo(self):
        texto = (
            "16037705 Manitas fontanero Libre Para el 07/10/26 De 08:00 a 20:00 "
            "VALENCIA (46007) C/ CL CALLOSA D'EN SARRIA 2B atasco en fregadero de la cocina "
            "se necesita bomba de presión informo de las condiciones"
        )
        self.assertEqual(
            extraer_direccion_servicio(texto),
            "C/ CL CALLOSA D'EN SARRIA 2B"
        )

    def test_extraer_direccion_servicio_en_curso(self):
        texto = (
            "15712066 Servicio urgente 18/09/2026 10:00 11:00 AVENIDA DEL MAR 31 3ºA "
            "VALENCIA (46012) AVERIA EN CALDERA EN EL BAÑO"
        )
        self.assertEqual(
            extraer_direccion_servicio(texto),
            "AVENIDA DEL MAR 31 3ºA"
        )

    def test_ordenar_ruta_servicios_prioriza_horario_y_zona(self):
        items = [
            ("A", "Paterna - Carrer Espigol 19"),
            ("B", "La Pobla de Farnals - Carrer Vicent Galmes 34"),
            ("C", "Meliana - Carrer Glories Valencianes 8"),
            ("D", "Rafelbunyol - Carrer Filomena Bernet 2"),
        ]
        ordered = ordenar_ruta_servicios(items)
        self.assertEqual([sid for sid, _ in ordered], ["A", "C", "D", "B"])

    def test_validar_orden_ruta(self):
        rows = [
            {"orden": 0, "direccion": "Calle A 1"},
            {"orden": 1, "direccion": "Calle B 2"},
            {"orden": 2, "direccion": "Calle C 3"},
        ]
        validado = validar_orden_ruta(rows)
        self.assertTrue(validado["ok"])
        self.assertEqual(validado["hora_esperada"], ["09:00", "10:00", "11:00"])

    def test_panel_nube_muestra_botones_exportar_importar(self):
        from main import app

        client = app.test_client()
        auth = base64.b64encode(b"admin:1234").decode("utf-8")
        response = client.get("/", headers={"Authorization": f"Basic {auth}"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Exportar", response.data)
        self.assertIn(b"Importar", response.data)

    def test_importar_ruta_asigna_horarios_con_margen_de_1_hora(self):
        from main import importar_ruta_desde_texto, obtener_ruta_diaria

        chat_id = "ruta_import_test"
        texto = "Calle A 1\nCalle B 2\nCalle C 3"

        count = importar_ruta_desde_texto(chat_id, texto)
        rows = obtener_ruta_diaria(chat_id)

        self.assertEqual(count, 3)
        self.assertEqual([row["orden"] for row in rows], [0, 1, 2])
        self.assertEqual([f"{9 + row['orden']:02d}:00" for row in rows], ["09:00", "10:00", "11:00"])


if __name__ == "__main__":
    unittest.main()
