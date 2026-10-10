import base64
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

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

    def test_cambiar_estado_rechaza_si_la_web_no_confirma_el_cambio(self):
        from main import HomeServe

        servicio = HomeServe()
        servicio.session = Mock()
        servicio.session.get = Mock(return_value=Mock(text="<html></html>"))
        servicio.session.post = Mock(return_value=Mock(text="<html>OK</html>", status_code=200))

        def fake_obtener_datos_servicio(sid):
            return {"ESTADO": "348"}, "<html>ESTADO 348</html>"

        with patch("main.obtener_datos_servicio", side_effect=fake_obtener_datos_servicio):
            ok, msg = servicio.cambiar_estado("12345678", "318")

        self.assertFalse(ok)
        self.assertIn("no se confirmó", msg.lower())

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

    def test_resumen_servicio_alerta_incluye_comentario_y_mapa_solo_direccion(self):
        from main import botones_servicio, resumen_servicio_alerta

        texto = (
            "16037705 Manitas fontanero Libre Para el 07/10/26 De 08:00 a 20:00 "
            "VALENCIA (46007) C/ CL CALLOSA D'EN SARRIA 2B atasco en fregadero de la cocina "
            "se necesita bomba de presión informo de las condiciones"
        )

        resumen = resumen_servicio_alerta(texto)
        self.assertIn("atasco en fregadero de la cocina", resumen.lower())
        self.assertIn("C/ CL CALLOSA D'EN SARRIA 2B", resumen)
        self.assertIn("google.com/maps/search", botones_servicio("1", texto)["inline_keyboard"][0][0]["url"])
        self.assertNotIn("VALENCIA", botones_servicio("1", texto)["inline_keyboard"][0][0]["url"].upper())
        self.assertNotIn("20:00", botones_servicio("1", texto)["inline_keyboard"][0][0]["url"].upper())

    def test_extraer_direccion_servicio_acepta_prefijos_valencianos(self):
        from main import parsear_servicios_texto

        texto = (
            "16045789|Carrer de la Verge 14 2 2 46001-Valencia\n"
            "16045790|C/CL. MESTRE ALBERT 5 46006-Valencia\n"
            "16045791|Avinguda del Mar 22 46012-Valencia\n"
            "16045792|Carretera de Sagunto 12 46001-Valencia"
        )
        servicios = parsear_servicios_texto(texto)
        self.assertEqual(servicios["16045789"], "Carrer de la Verge 14 2 2 46001-Valencia")
        self.assertEqual(servicios["16045790"], "C/CL. MESTRE ALBERT 5 46006-Valencia")
        self.assertEqual(servicios["16045791"], "Avinguda del Mar 22 46012-Valencia")
        self.assertEqual(servicios["16045792"], "Carretera de Sagunto 12 46001-Valencia")

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

    def test_limpiar_ruta_dia_borra_servicios_guardados(self):
        from main import guardar_ruta_diaria, limpiar_ruta_dia, obtener_ruta_diaria

        chat_id = "ruta_limpiar_test"
        fecha = datetime.now().date().isoformat()
        guardar_ruta_diaria(chat_id, "160001", "Calle A 1", fecha=fecha, orden=0)
        guardar_ruta_diaria(chat_id, "160002", "Calle B 2", fecha=fecha, orden=1)

        deleted = limpiar_ruta_dia(chat_id, fecha)
        rows = obtener_ruta_diaria(chat_id, fecha)

        self.assertEqual(deleted, 2)
        self.assertEqual(rows, [])

    def test_importar_ruta_asigna_horarios_con_margen_de_1_hora(self):
        from main import importar_ruta_desde_texto, obtener_ruta_diaria

        chat_id = "ruta_import_test"
        texto = "Calle A 1\nCalle B 2\nCalle C 3"

        count = importar_ruta_desde_texto(chat_id, texto)
        rows = obtener_ruta_diaria(chat_id)

        self.assertEqual(count, 3)
        self.assertEqual([row["orden"] for row in rows], [0, 1, 2])
        self.assertEqual([f"{9 + row['orden']:02d}:00" for row in rows], ["09:00", "10:00", "11:00"])

    def test_importar_ruta_limpia_direccion_y_descarta_estado(self):
        from main import importar_ruta_desde_texto, obtener_ruta_diaria

        chat_id = "ruta_import_limpieza"
        texto = (
            "16038937|C/Barco 1635 46024-VALENCIA "
            "En espera de Profesional por confirmacion del Siniestro 08/10/2026 08/10/2026 de 08:00 a 20:00"
        )

        count = importar_ruta_desde_texto(chat_id, texto)
        rows = obtener_ruta_diaria(chat_id)

        self.assertEqual(count, 1)
        self.assertTrue(rows[0]["direccion"].startswith("C/Barco 1635 46024-VALENCIA"))
        self.assertNotIn("En espera de Profesional", rows[0]["direccion"])
        self.assertNotIn("08:00 a 20:00", rows[0]["direccion"])

    def test_importar_ruta_acepta_formato_id_guion_direccion(self):
        from main import importar_ruta_desde_texto, obtener_ruta_diaria

        chat_id = "ruta_import_guion"
        texto = "16016046 - Carrer INGENIERO JOAQUIN BENLLOCH 27, valencia"

        count = importar_ruta_desde_texto(chat_id, texto)
        rows = obtener_ruta_diaria(chat_id)

        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["sid"], "16016046")
        self.assertTrue(rows[0]["direccion"].startswith("Carrer INGENIERO JOAQUIN BENLLOCH 27"))
        self.assertNotIn("16016046", rows[0]["direccion"])

    def test_etiqueta_ruta_muestra_hoy_o_dia_siguiente(self):
        from main import etiqueta_fecha_ruta

        self.assertEqual(etiqueta_fecha_ruta(datetime.now().date()), "Hoy")
        self.assertNotIn("Para", etiqueta_fecha_ruta(datetime.now().date() + timedelta(days=1)))

    def test_construir_mensaje_cita_usa_misma_etiqueta_de_fecha(self):
        from main import construir_mensaje_cita

        texto_hoy = construir_mensaje_cita("Calle Falsa 123", "09:00", "Hoy")
        self.assertIn("para mañana", texto_hoy.lower())
        self.assertNotIn("para hoy", texto_hoy.lower())
        self.assertNotIn("para el", texto_hoy.lower())

        texto_manana = construir_mensaje_cita("Calle Falsa 123", "09:00")
        self.assertIn("para mañana", texto_manana.lower())
        self.assertNotIn("para 10/", texto_manana.lower())

        texto_fecha = construir_mensaje_cita("Calle Falsa 123", "09:00", "17/oct")
        self.assertIn("para el 17/oct", texto_fecha.lower())
        self.assertNotIn("para 17/oct", texto_fecha.lower())

    def test_mover_ruta_fecha_no_borra_si_es_la_misma_fecha(self):
        from main import guardar_ruta_diaria, obtener_ruta_diaria, mover_ruta_fecha

        chat_id = "ruta_misma_fecha"
        fecha = datetime.now().date().isoformat()
        guardar_ruta_diaria(chat_id, "160001", "Calle A 1", fecha=fecha, orden=0)
        guardar_ruta_diaria(chat_id, "160002", "Calle B 2", fecha=fecha, orden=1)

        moved = mover_ruta_fecha(chat_id, fecha, fecha)
        rows = obtener_ruta_diaria(chat_id, fecha)

        self.assertEqual(moved, 0)
        self.assertEqual(len(rows), 2)

    def test_mover_ruta_fecha_conserva_la_ruta_original(self):
        from main import guardar_ruta_diaria, obtener_ruta_diaria, mover_ruta_fecha

        chat_id = "ruta_conserva_original"
        origen = datetime.now().date().isoformat()
        destino = (datetime.now().date() + timedelta(days=1)).isoformat()
        guardar_ruta_diaria(chat_id, "160001", "Calle A 1", fecha=origen, orden=0)
        guardar_ruta_diaria(chat_id, "160002", "Calle B 2", fecha=origen, orden=1)

        moved = mover_ruta_fecha(chat_id, origen, destino)
        rows_origen = obtener_ruta_diaria(chat_id, origen)
        rows_destino = obtener_ruta_diaria(chat_id, destino)

        self.assertEqual(moved, 2)
        self.assertEqual(len(rows_origen), 2)
        self.assertEqual(len(rows_destino), 2)

    def test_ajustar_fecha_misma_fecha_actualiza_estado_sin_error(self):
        from main import RUTA_FECHA_STATE, actualizar_fecha_ruta_estado, guardar_ruta_diaria

        chat_id = "ruta_ajuste_misma_fecha"
        fecha = datetime.now().date().isoformat()
        RUTA_FECHA_STATE[chat_id] = fecha
        guardar_ruta_diaria(chat_id, "160001", "Calle A 1", fecha=fecha, orden=0)

        resultado = actualizar_fecha_ruta_estado(chat_id, fecha)

        self.assertTrue(resultado["updated"])
        self.assertTrue(resultado["same_date"])
        self.assertEqual(RUTA_FECHA_STATE[chat_id], fecha)

    def test_export_no_incluye_servicios_en_tratamiento(self):
        from main import es_servicio_bloqueado

        self.assertTrue(es_servicio_bloqueado("En tratamiento por Homeserve"))
        self.assertTrue(es_servicio_bloqueado("CANDADO servicio bloqueado"))
        self.assertFalse(es_servicio_bloqueado("C/Barco 1635 46024-VALENCIA"))

    def test_parsear_servicios_en_texto_lee_todos_los_ids(self):
        from main import parsear_servicios_texto

        texto = (
            "16033015|C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA\n"
            "16029364|C FILOMENA+BERNET, 2 , BAJ 2 46138-RAFELBUNYOL\n"
            "16018743|C/CL/ VICENTE GALMES 34 1 1 46139-POBLA DE FARNALS, LA\n"
            "15914657|AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS\n"
            "16008003|avel-les, 46137, Valencia, España 46137\n"
            "16020450|C GORGOS, 11 , 13 B 46021-VALENCIA"
        )

        servicios = parsear_servicios_texto(texto)

        self.assertEqual(list(servicios.keys())[:3], ["16033015", "16029364", "16018743"])
        self.assertEqual(len(servicios), 6)
        self.assertIn("C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA", servicios["16033015"])

    def test_parsear_servicios_html_no_pierde_direccion_clara(self):
        from main import parsear_servicios_texto

        html = (
            '<a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=15914657&Pag=1">15914657</a>'
            '<font color="#000000">AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS</font>'
            '<a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=16039424&Pag=1">16039424</a>'
            '<font color="#000000">C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL</font>'
        )

        servicios = parsear_servicios_texto(html)
        self.assertEqual(len(servicios), 2)
        self.assertIn("AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS", servicios["15914657"])
        self.assertIn("C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL", servicios["16039424"])

    def test_parsear_servicios_html_con_patron_real_homeserve(self):
        from main import parsear_servicios_texto

        html = '''
        <table>
        <tr>
        <td><a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=16039424&Pag=1">16039424</a></td>
        <td><font color="#000000">C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL</font></td>
        </tr>
        <tr>
        <td><a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=15914657&Pag=1">15914657</a></td>
        <td><font color="#000000">AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS</font></td>
        </tr>
        </table>
        '''

        servicios = parsear_servicios_texto(html)
        self.assertEqual(set(servicios.keys()), {"16039424", "15914657"})
        self.assertIn("C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL", servicios["16039424"])
        self.assertIn("AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS", servicios["15914657"])

    def test_parsear_servicios_html_toma_el_texto_visible_de_la_fila(self):
        from main import parsear_servicios_texto

        html = '''
        <table>
            <tr>
                <td><a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=16039424&Pag=1">16039424</a></td>
                <td>07/10/2026 07/10/2026 de 08:00 a 20:00</td>
            </tr>
            <tr>
                <td><a href="https://www.clientes.homeserve.es/cgi-bin/fccgi.exe?w3exec=ver_servicioencurso&Servicio=15914657&Pag=1">15914657</a></td>
                <td><font color="#000000">AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS</font></td>
            </tr>
        </table>
        '''

        servicios = parsear_servicios_texto(html)
        self.assertNotIn("16039424", servicios)
        self.assertIn("AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS", servicios["15914657"])

    def test_parsear_servicios_id_pipe_rechaza_horario_y_coge_direccion(self):
        from main import parsear_servicios_texto

        texto = (
            "16035845|C/CL. ESPIGOL 19 2 8 46980-PATERNA\n"
            "16033015|C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA\n"
            "16039424|07/10/2026 07/10/2026 de 08:00 a 20:00\n"
        )

        servicios = parsear_servicios_texto(texto)
        self.assertEqual(servicios["16035845"], "C/CL. ESPIGOL 19 2 8 46980-PATERNA")
        self.assertEqual(servicios["16033015"], "C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA")
        self.assertNotIn("16039424", servicios)

    def test_parsear_servicios_id_pipe_reconoce_el_bloque_completo_del_usuario(self):
        from main import parsear_servicios_texto

        texto = (
            "16035845|C/CL. ESPIGOL 19 2 8 46980-PATERNA\n"
            "16033015|C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA\n"
            "16029364|C FILOMENA+BERNET, 2 , BAJ 2 46138-RAFELBUNYOL\n"
            "16018743|C/CL/ VICENTE GALMES 34 1 1 46139-POBLA DE FARNALS, LA\n"
            "15914657|AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS\n"
            "16020450|C GORGOS, 11 , 13 B 46021-VALENCIA\n"
            "16016046|C/ INGENIERO JOAQUIN BENLLOCH 00027 39 46006-VALENCIA\n"
            "16008003|Carrer Caravel-les, 46137, Valencia, España 46137\n"
            "15991779|AV/ BLASCO IBA?EZ 40A 3 2 9 46136-MUSEROS\n"
            "16005226|C/ REI JAUME I 00046 14 46135-ALBALAT DELS SORELLS\n"
            "16033892|C/ TRENCAT 32 20 46138-RAFELBU¥OL\n"
            "16014090|CL MAESTRO+RODRIGO, 36 , 2 2 . 46130-MASSAMAGRELL\n"
        )

        servicios = parsear_servicios_texto(texto)
        self.assertEqual(len(servicios), 12)
        self.assertEqual(list(servicios.keys())[:3], ["16035845", "16033015", "16029364"])
        self.assertIn("16014090", servicios)
        self.assertIn("15991779", servicios)

    def test_parsear_servicios_no_corta_en_cliente_ni_siniestros(self):
        from main import parsear_servicios_texto

        texto = (
            "16038937|C/Barco 1635 46024-VALENCIA En espera de Profesional por Pendiente de citar al cliente 06/10/2026 08/10/2026 08/10/2026 de 08:00 a 20:00 Repsol - Asistencias con cobertura\n"
            "16039424|C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL En espera de Profesional por Pendiente de citar al cliente 06/10/2026 07/10/2026 07/10/2026 de 08:00 a 20:00 LDA Siniestros\n"
        )

        servicios = parsear_servicios_texto(texto)
        self.assertEqual(len(servicios), 2)
        self.assertEqual(servicios["16038937"], "C/Barco 1635 46024-VALENCIA")
        self.assertEqual(servicios["16039424"], "C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL")

    def test_importar_ruta_acepta_bloque_concatenado_sin_saltos(self):
        from main import importar_ruta_desde_texto, obtener_ruta_diaria

        chat_id = "ruta_import_concatenada"
        texto = (
            "16035845|C/CL. ESPIGOL 19 2 8 46980-PATERNA "
            "16033015|C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA "
            "16029364|C FILOMENA+BERNET, 2 , BAJ 2 46138-RAFELBUNYOL "
            "16039424|C MAGDALENA, 111 , 1 4 46138-RAFELBUNYOL "
            "16018743|C/CL/ VICENTE GALMES 34 1 1 46139-POBLA DE FARNALS, LA "
            "15914657|AVD BLASCO IBAÑEZ 18A 1 1 A 46136 MUSEROS VALENCIA 46136-MUSEROS "
            "16020450|C GORGOS, 11 , 13 B 46021-VALENCIA "
            "16016046|C/ INGENIERO JOAQUIN BENLLOCH 00027 39 46006-VALENCIA "
            "16038937|C/Barco 1635 46024-VALENCIA "
            "16008003|Carrer Caravel-les, 46137, Valencia, España 46137 "
            "15991779|AV/ BLASCO IBA?EZ 40A 3 2 9 46136-MUSEROS "
            "16005226|C/ REI JAUME I 00046 14 46135-ALBALAT DELS SORELLS "
            "16033892|C/ TRENCAT 32 20 46138-RAFELBU¥OL "
            "16014090|CL MAESTRO+RODRIGO, 36 , 2 2 . 46130-MASSAMAGRELL"
        )

        count = importar_ruta_desde_texto(chat_id, texto)
        rows = obtener_ruta_diaria(chat_id)

        self.assertEqual(count, 14)
        self.assertEqual({row["sid"] for row in rows}, {
            "16035845", "16033015", "16029364", "16039424", "16018743", "15914657",
            "16020450", "16016046", "16038937", "16008003", "15991779", "16005226",
            "16033892", "16014090"
        })

    def test_generar_ruta_recarga_desde_web_y_no_filtra_por_bloqueo(self):
        from main import generar_ruta_dia, guardar_ruta_diaria, exportar_ruta_dia

        chat_id = "ruta_refresco"
        servicios = {
            "16039424": "16039424 C/ LARGO 45 46003-VALENCIA",
            "16033015": "16033015 C/CL. GLORIES VALENCIANES 8 4 10 46133-MELIANA",
            "16029364": "16029364 C FILOMENA+BERNET, 2 , BAJ 2 46138-RAFELBUNYOL",
        }

        guardar_ruta_diaria(chat_id, "9999999", "Ruta vieja", fecha=datetime.now().date().isoformat(), orden=0)
        rows = generar_ruta_dia(chat_id, servicios, refrescar=True)
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["sid"] for row in rows}, {"16039424", "16033015", "16029364"})

        with patch("main.homeserve.obtener_curso", return_value=servicios):
            text = exportar_ruta_dia(chat_id, refrescar=True)
        self.assertIn("16039424|", text)
        self.assertIn("16033015|", text)
        self.assertNotIn("9999999|", text)


if __name__ == "__main__":
    unittest.main()
