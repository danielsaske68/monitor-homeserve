import unittest
from datetime import datetime

from main import (
    calcular_fecha_caducidad,
    extraer_direccion_servicio,
    ordenar_ruta_servicios,
    siguiente_estado_automatico,
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


if __name__ == "__main__":
    unittest.main()
