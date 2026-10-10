# -*- coding: utf-8 -*-
"""Andamiaje común: monta un flujo PFUL -> DFUL de verdad.

Los tests no simulan la cadena a mano: validan albaranes y dejan que Odoo
dispare la regla push, que es donde vive el comportamiento que nos interesa.
"""
from odoo.tests.common import TransactionCase


class FulfillmentCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        view = cls.warehouse.view_location_id

        Location = cls.env['stock.location']
        cls.loc_stock = cls.warehouse.lot_stock_id
        cls.loc_salida = Location.create({
            'name': 'TEST Salida Ful', 'usage': 'internal', 'location_id': view.id})
        cls.loc_ruta = Location.create({
            'name': 'TEST Destino Ruta', 'usage': 'internal', 'location_id': view.id})
        cls.loc_marketplace = Location.create({
            'name': 'TEST Marketplace', 'usage': 'internal', 'location_id': view.id})

        PickingType = cls.env['stock.picking.type']
        # Nombres deliberadamente ajenos a 'Resurtido a Ful': el rol debe salir
        # de `ful_role` y no del nombre.
        cls.type_pick = PickingType.create({
            'name': 'TEST Surtido Nombre Arbitrario',
            'code': 'internal', 'sequence_code': 'TPFUL',
            'warehouse_id': cls.warehouse.id,
            'default_location_src_id': cls.loc_stock.id,
            'default_location_dest_id': cls.loc_salida.id,
            'ful_role': 'pick',
        })
        cls.type_dispatch = PickingType.create({
            'name': 'TEST Despacho Nombre Arbitrario',
            'code': 'internal', 'sequence_code': 'TDFUL',
            'warehouse_id': cls.warehouse.id,
            'default_location_src_id': cls.loc_salida.id,
            'default_location_dest_id': cls.loc_ruta.id,
            'ful_role': 'dispatch',
            'no_merge_destination': True,
        })

        # Regla push: al terminar en loc_salida, empuja hacia el despacho.
        cls.route = cls.env['stock.route'].create({
            'name': 'TEST Ruta Ful',
            'product_selectable': True,
            'rule_ids': [(0, 0, {
                'name': 'TEST Salida -> Despacho',
                'action': 'push',
                'picking_type_id': cls.type_dispatch.id,
                'location_src_id': cls.loc_salida.id,
                'location_dest_id': cls.loc_ruta.id,
                'auto': 'manual',
            })],
        })

        cls.product = cls.env['product.product'].create({
            'name': 'TEST Producto Ful',
            'is_storable': True,
            'route_ids': [(6, 0, cls.route.ids)],
        })

    # -- utilidades -------------------------------------------------------

    def _abastecer(self, qty):
        self.env['stock.quant']._update_available_quantity(
            self.product, self.loc_stock, qty)

    def _crear_pful(self, qty, origin=None, marketplace=None):
        pful = self.env['stock.picking'].create({
            'picking_type_id': self.type_pick.id,
            'location_id': self.loc_stock.id,
            'location_dest_id': self.loc_salida.id,
            'origin': origin,
            'move_ids': [(0, 0, {
                'name': self.product.name,
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
                'location_id': self.loc_stock.id,
                'location_dest_id': self.loc_salida.id,
            })],
        })
        if marketplace:
            pful.marketplace_location = marketplace
        pful.action_confirm()
        pful.action_assign()
        return pful

    def _validar_parcial(self, pful, qty):
        """Valida `qty` del PFUL confirmando el backorder. Retorna el backorder.

        `button_validate` no cierra el albarán cuando queda cantidad pendiente:
        devuelve la acción del asistente `stock.backorder.confirmation`. Hay que
        instanciarlo con el contexto que trae la acción y confirmarlo, que es
        justo lo que hace el usuario en pantalla.
        """
        move = pful.move_ids[0]
        move.quantity = qty
        move.picked = True
        res = pful.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            wizard = self.env[res['res_model']].with_context(**res['context']).create({})
            wizard.process()
        return self.env['stock.picking'].search([('backorder_id', '=', pful.id)])

    def _reservar(self, picking):
        """Reserva el albarán si tiene algo que reservar."""
        if picking and picking.state not in ('done', 'cancel') and picking.move_ids:
            picking.action_assign()
        return picking

    def _dfuls_de(self, pful):
        """Todos los DFUL alimentados por la cadena de `pful`.

        No basta con navegar `move_dest_ids`: al cancelar un albarán, Odoo borra
        el encadenamiento (`stock.move._action_cancel` hace
        `write({'move_orig_ids': [(5, 0, 0)]})`), con lo que un DFUL cancelado
        se vuelve invisible por esa vía. Se completa buscando por origen.
        """
        family = pful._ful_backorder_family()
        root = pful._ful_backorder_root()
        por_cadena = family.move_ids.move_dest_ids.picking_id
        por_origen = self.env['stock.picking'].search([
            ('picking_type_id', '=', self.type_dispatch.id),
            ('origin', '=', root.origin or root.name),
        ])
        return (por_cadena | por_origen).filtered(
            lambda p: p.picking_type_id == self.type_dispatch
        ).sorted('id')
