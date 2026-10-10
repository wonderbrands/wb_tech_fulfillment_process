# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.wb_tech_fulfillment_process.models.fulfillment_picking import seed_ful_roles

from .common import FulfillmentCase


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentRole(FulfillmentCase):
    """El rol sale del campo, nunca del nombre del tipo de operación."""

    def test_rol_independiente_del_nombre(self):
        self._abastecer(10)
        pful = self._crear_pful(10, origin='APPT-ROL', marketplace=self.loc_marketplace)
        self._validar_parcial(pful, 10)
        dfuls = self._dfuls_de(pful)
        self.assertEqual(len(dfuls), 1)
        # Los tipos se llaman 'TEST ... Nombre Arbitrario'; si la lógica
        # dependiera del nombre, nada de esto se habría propagado.
        self.assertEqual(dfuls.origin, 'APPT-ROL')
        self.assertEqual(dfuls.marketplace_location, self.loc_marketplace)

    def test_sin_rol_no_se_propaga(self):
        self.type_dispatch.ful_role = False
        self._abastecer(10)
        pful = self._crear_pful(10, origin='APPT-SINROL', marketplace=self.loc_marketplace)
        self._validar_parcial(pful, 10)
        dfuls = self._dfuls_de(pful)
        self.assertNotEqual(dfuls.origin, 'APPT-SINROL')

    def test_seed_no_pisa_configuracion_manual(self):
        manual = self.env['stock.picking.type'].create({
            'name': 'Resurtido a Ful: Pick', 'code': 'internal',
            'sequence_code': 'TSEED', 'warehouse_id': self.warehouse.id,
            'ful_role': 'dispatch',
        })
        sin_rol = self.env['stock.picking.type'].create({
            'name': 'Resurtido a Ful: Despacho', 'code': 'internal',
            'sequence_code': 'TSEED2', 'warehouse_id': self.warehouse.id,
        })
        seed_ful_roles(self.env)
        self.assertEqual(manual.ful_role, 'dispatch', "no debe sobrescribir lo configurado")
        self.assertEqual(sin_rol.ful_role, 'dispatch', "debe sembrar el que estaba vacío")


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentConsolidacion(FulfillmentCase):
    """Pickeo en varias rondas: todo acaba en un único DFUL."""

    def test_dos_rondas_consolidan(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-2R', marketplace=self.loc_marketplace)
        bo1 = self._validar_parcial(pful, 20)
        self.assertTrue(bo1)
        self.assertEqual(len(self._dfuls_de(pful)), 1)

        self._reservar(bo1)
        self._validar_parcial(bo1, 20)
        dfuls = self._dfuls_de(pful)
        self.assertEqual(len(dfuls), 1, "el backorder debe entrar al DFUL existente")
        self.assertEqual(sum(dfuls.move_ids.mapped('product_uom_qty')), 40)

    def test_tres_rondas_consolidan(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-3R', marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        for _ in range(2):
            self._reservar(bo)
            bo = self._validar_parcial(bo, 20)
        dfuls = self._dfuls_de(pful)
        self.assertEqual(len(dfuls), 1)
        self.assertEqual(sum(dfuls.move_ids.mapped('product_uom_qty')), 60)

    def test_raiz_de_la_cadena(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-RAIZ', marketplace=self.loc_marketplace)
        bo1 = self._validar_parcial(pful, 20)
        self._reservar(bo1)
        bo2 = self._validar_parcial(bo1, 20)
        self.assertEqual(bo2._ful_backorder_root(), pful)
        self.assertEqual(bo2._ful_backorder_family(), pful | bo1 | bo2)

    def test_dful_impreso_sigue_consolidando(self):
        """Regresión: la hoja impresa no debe abrir un segundo despacho."""
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-IMP', marketplace=self.loc_marketplace)
        bo1 = self._validar_parcial(pful, 20)
        self._dfuls_de(pful).printed = True

        self._reservar(bo1)
        self._validar_parcial(bo1, 20)
        self.assertEqual(len(self._dfuls_de(pful)), 1)

    def test_dful_cerrado_abre_otro_y_avisa(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-CER', marketplace=self.loc_marketplace)
        bo1 = self._validar_parcial(pful, 20)
        dful1 = self._dfuls_de(pful)
        dful1.action_cancel()

        self._reservar(bo1)
        self._validar_parcial(bo1, 20)
        dfuls = self._dfuls_de(pful)
        self.assertEqual(len(dfuls), 2, "con el DFUL cerrado hay que abrir otro")
        nuevo = dfuls[-1]
        self.assertTrue(
            any('se creó aparte' in (m.body or '') for m in nuevo.message_ids),
            "debe avisar que la cita quedó repartida")

    def test_pful_sin_parentesco_no_se_mezclan(self):
        self._abastecer(200)
        a = self._crear_pful(50, origin='APPT-A', marketplace=self.loc_marketplace)
        b = self._crear_pful(50, origin='APPT-B', marketplace=self.loc_marketplace)
        self._validar_parcial(a, 50)
        self._validar_parcial(b, 50)
        self.assertNotEqual(self._dfuls_de(a), self._dfuls_de(b),
                            "cadenas distintas deben mantener DFUL separados")


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentPropagacion(FulfillmentCase):
    """Documento origen y ubicación de marketplace."""

    def test_origin_es_la_cita_no_el_nombre(self):
        self._abastecer(50)
        pful = self._crear_pful(50, origin='APPT-9001', marketplace=self.loc_marketplace)
        self._validar_parcial(pful, 50)
        self.assertEqual(self._dfuls_de(pful).origin, 'APPT-9001')

    def test_origin_no_se_contamina_al_consolidar(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-9002', marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        for _ in range(2):
            self._reservar(bo)
            bo = self._validar_parcial(bo, 20)
        origin = self._dfuls_de(pful).origin
        self.assertEqual(origin, 'APPT-9002')
        self.assertNotIn(',', origin, "no debe acumular los nombres de los backorders")

    def test_origin_limpio_aun_sin_cita(self):
        """Sin número de cita el campo debe quedar limpio, no concatenado."""
        self._abastecer(100)
        pful = self._crear_pful(100, marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        self._reservar(bo)
        self._validar_parcial(bo, 20)
        self.assertEqual(self._dfuls_de(pful).origin, pful.name)

    def test_marketplace_llega_a_moves_y_lineas(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-MKT', marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        self._reservar(bo)
        self._validar_parcial(bo, 20)

        dful = self._dfuls_de(pful)
        self.assertEqual(dful.location_dest_id, self.loc_marketplace)
        self.assertEqual(dful.marketplace_location, self.loc_marketplace)
        for move in dful.move_ids:
            self.assertEqual(move.location_dest_id, self.loc_marketplace)
        for line in dful.move_line_ids:
            self.assertEqual(line.location_dest_id, self.loc_marketplace,
                             "las líneas reservadas también deben reapuntarse")

    def test_marketplace_vuelve_del_dful_a_toda_la_cadena(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-RET')
        bo = self._validar_parcial(pful, 20)
        self.assertEqual(pful.marketplace_location, self.loc_ruta)
        self.assertEqual(bo.marketplace_location, self.loc_ruta,
                         "el backorder también debe quedar con el marketplace")


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentDominio(FulfillmentCase):
    """El dominio ampliado debe seguir siendo válido con otros módulos encima."""

    def test_dominio_valido_y_sin_hoja_printed(self):
        self._abastecer(50)
        pful = self._crear_pful(50, origin='APPT-DOM', marketplace=self.loc_marketplace)
        self._validar_parcial(pful, 50)
        move = self._dfuls_de(pful).move_ids[0]

        dominio = move._search_picking_for_assignation_domain()
        hojas = [l for l in dominio if isinstance(l, (list, tuple)) and len(l) == 3]
        self.assertFalse([l for l in hojas if l[0] == 'printed'],
                         "la hoja printed debe haberse sustituido")
        # Regresión: stock_picking_batch mete un '|' en el dominio. Si la
        # sustitución descuadrara la aridad, este search reventaría.
        self.env['stock.picking'].search(dominio)

    def test_dominio_intacto_sin_el_flag(self):
        self.type_dispatch.no_merge_destination = False
        self._abastecer(50)
        pful = self._crear_pful(50, origin='APPT-DOM2')
        self._validar_parcial(pful, 50)
        move = self._dfuls_de(pful).move_ids[0]
        dominio = move._search_picking_for_assignation_domain()
        hojas = [l for l in dominio if isinstance(l, (list, tuple)) and len(l) == 3]
        self.assertTrue([l for l in hojas if l[0] == 'printed'],
                        "sin el flag no debemos tocar el dominio del core")


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentOperador(FulfillmentCase):
    """El operador se comparte en toda la cadena de PFUL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.op_a = cls.env['res.users'].create({
            'name': 'TEST Operador A', 'login': 'test_ful_op_a'})
        cls.op_b = cls.env['res.users'].create({
            'name': 'TEST Operador B', 'login': 'test_ful_op_b'})

    def test_operador_se_propaga_al_backorder(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-OP1', marketplace=self.loc_marketplace)
        pful.operator = self.op_a
        bo = self._validar_parcial(pful, 20)
        self.assertEqual(bo.operator, self.op_a)

    def test_reasignar_sincroniza_la_cadena_abierta(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-OP2', marketplace=self.loc_marketplace)
        pful.operator = self.op_a
        bo1 = self._validar_parcial(pful, 20)
        self._reservar(bo1)
        bo2 = self._validar_parcial(bo1, 20)

        bo2.operator = self.op_b
        self.assertEqual(bo2.operator, self.op_b)
        self.assertEqual(bo1.operator, self.op_a,
                         "un PFUL ya validado conserva quién lo surtió")
        self.assertEqual(pful.operator, self.op_a,
                         "el histórico no se reescribe")

    def test_asignar_tarde_alcanza_a_los_abiertos(self):
        """El caso que hoy se pierde: el operador se asigna tras el backorder."""
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-OP3', marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        self.assertFalse(bo.operator)
        bo.operator = self.op_a
        self.assertEqual(bo.operator, self.op_a)


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentFechaProgramada(FulfillmentCase):
    """La fecha programada del DFUL es la de entrega, no la de validación."""

    def test_dful_hereda_la_fecha_del_pful(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-FE1', marketplace=self.loc_marketplace)
        prevista = pful.scheduled_date
        self._validar_parcial(pful, 20)
        self.assertEqual(self._dfuls_de(pful).scheduled_date, prevista)

    def test_la_fecha_no_se_mueve_en_tres_rondas(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-FE2', marketplace=self.loc_marketplace)
        prevista = pful.scheduled_date
        bo = self._validar_parcial(pful, 20)
        for _ in range(2):
            self._reservar(bo)
            bo = self._validar_parcial(bo, 20)
        dful = self._dfuls_de(pful)
        self.assertEqual(len(dful), 1)
        self.assertEqual(dful.scheduled_date, prevista,
                         "consolidar no debe correr la fecha de entrega")

    def test_ajuste_manual_se_respeta(self):
        from datetime import datetime
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-FE3', marketplace=self.loc_marketplace)
        bo = self._validar_parcial(pful, 20)
        dful = self._dfuls_de(pful)
        a_mano = datetime(2030, 1, 15, 9, 0, 0)
        dful.scheduled_date = a_mano

        self._reservar(bo)
        self._validar_parcial(bo, 20)
        self.assertEqual(dful.scheduled_date, a_mano,
                         "el módulo no debe pisar un ajuste manual")

    def test_otros_albaranes_no_se_congelan(self):
        """Un albarán ajeno al fulfillment mantiene el cálculo del core."""
        self.type_dispatch.ful_role = False
        self._abastecer(50)
        pful = self._crear_pful(50, origin='APPT-FE4')
        self._validar_parcial(pful, 50)
        dful = self._dfuls_de(pful)
        self.assertEqual(dful.scheduled_date, max(dful.move_ids.mapped('date')))


@tagged('post_install', '-at_install', 'wb_ful')
class TestFulfillmentLote(FulfillmentCase):
    """Cada parcial estrena su propio traslado por lote."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.op = cls.env['res.users'].create({
            'name': 'TEST Operador Lote', 'login': 'test_ful_op_lote'})

    def test_cada_parcial_estrena_lote(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-LT1', marketplace=self.loc_marketplace)
        pful.operator = self.op
        bo1 = self._validar_parcial(pful, 20)
        self.assertTrue(bo1.batch_id, "el parcial debe nacer con lote")
        self.assertEqual(bo1.batch_id.operator, self.op)
        self.assertEqual(bo1.batch_id.state, 'in_progress')

        self._reservar(bo1)
        bo2 = self._validar_parcial(bo1, 20)
        self.assertTrue(bo2.batch_id)
        self.assertNotEqual(bo2.batch_id, bo1.batch_id, "un lote por ronda")

    def test_el_dful_no_recibe_lote(self):
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-LT2', marketplace=self.loc_marketplace)
        self._validar_parcial(pful, 20)
        self.assertFalse(self._dfuls_de(pful).batch_id,
                         "solo los Pick parciales entran a un lote")

    def test_sin_rol_no_se_crea_lote(self):
        self.type_pick.ful_role = False
        self._abastecer(100)
        pful = self._crear_pful(100, origin='APPT-LT3')
        bo = self._validar_parcial(pful, 20)
        self.assertFalse(bo.batch_id)
