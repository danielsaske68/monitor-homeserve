import unittest
from datetime import datetime

from main import calcular_fecha_caducidad, siguiente_estado_automatico


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


if __name__ == "__main__":
    unittest.main()
