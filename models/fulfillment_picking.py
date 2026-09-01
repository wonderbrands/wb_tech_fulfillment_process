from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Nombres de los tipos de operación del flujo de fulfillment.
# El emparejamiento por nombre es frágil (renombrar el tipo desde la interfaz
# rompe la lógica sin error); se centraliza aquí para poder sustituirlo más
# adelante por un campo propio en stock.picking.type.
FUL_PICK_TYPE = 'Resurtido a Ful: Pick'
FUL_DISPATCH_TYPE = 'Resurtido a Ful: Despacho'

CLOSED_STATE_LABELS = {
    'done': 'validado',
    'cancel': 'cancelado',
}


class FulfillmentPicking(models.Model):
    """
    Extiende stock.picking para gestionar la propagación de marketplace_location
    entre operaciones PFUL (Resurtido a Ful: Pick) y DFUL (Resurtido a Ful: Despacho).
    """
    _inherit = 'stock.picking'

    marketplace_location = fields.Many2one(
        "stock.location",
        string="Ubicación del marketplace",
    )

    picking_type_id_name = fields.Char(
        related='picking_type_id.name',
        string='Tipo de operación',
    )

    @api.model
    def create(self, vals):
        return super(FulfillmentPicking, self).create(vals)

    def _ful_backorder_root(self):
        """Retorna el albarán original del que desciende este backorder.

        Odoo encadena `backorder_id` cada vez que se valida parcialmente, así que
        subir hasta la raíz da el identificador del trabajo completo: el PFUL tal
        como se planeó, sin importar en cuántas partes se acabe surtiendo.
        """
        self.ensure_one()
        picking = self
        seen = set()
        while picking.backorder_id and picking.backorder_id.id not in seen:
            seen.add(picking.id)
            picking = picking.backorder_id
        return picking

    def _ful_backorder_family(self):
        """Retorna la cadena completa de backorders: la raíz y sus descendientes."""
        family = self.browse()
        for picking in self:
            frontier = picking._ful_backorder_root()
            while frontier:
                family |= frontier
                frontier = frontier.backorder_ids - family
        return family


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    no_merge_destination = fields.Boolean(
        string="No consolidar destinos",
        help="Al validar, cada albarán origen genera su propio albarán destino (1:1) "
             "en lugar de consolidarse en uno solo.",
    )


class FulfillmentStockMove(models.Model):
    _inherit = 'stock.move'

    def _split_by_origin(self):
        """Retorna True si el move debe forzar separación 1:1
        según la configuración de su tipo de operación o del origen."""
        self.ensure_one()
        if not self.move_orig_ids:
            return False
        return self.picking_type_id.no_merge_destination or any(
            self.move_orig_ids.mapped('picking_id.picking_type_id.no_merge_destination')
        )

    def _ful_source_pickings(self):
        """Retorna los PFUL que originan estos movimientos."""
        return self.move_orig_ids.picking_id.filtered(
            lambda p: FUL_PICK_TYPE in (p.picking_type_id.name or '')
        )

    def _ful_origin_root_ids(self):
        """IDs de los albaranes raíz que originan estos movimientos.

        Se agrupa por la raíz de la cadena de backorders y no por el albarán
        concreto, para que un PFUL surtido en varias partes alimente siempre el
        mismo DFUL en lugar de abrir uno nuevo por cada backorder.
        """
        return tuple(sorted({
            picking._ful_backorder_root().id
            for picking in self.move_orig_ids.picking_id
        }))

    def _ful_closed_sibling_dispatches(self):
        """DFUL ya cerrados generados por la misma cadena de PFUL que estos moves."""
        family = self.move_orig_ids.picking_id._ful_backorder_family()
        dispatches = family.move_ids.move_dest_ids.picking_id.filtered(
            lambda p: FUL_DISPATCH_TYPE in (p.picking_type_id.name or '')
        )
        return dispatches.filtered(lambda p: p.state in CLOSED_STATE_LABELS)

    @staticmethod
    def _merge_ful_origin(current, new_values):
        """Une documentos origen en una cadena separada por comas, sin duplicados
        y conservando los que ya estaban."""
        origins = [o.strip() for o in (current or '').split(',') if o.strip()]
        for value in new_values:
            value = (value or '').strip()
            if value and value not in origins:
                origins.append(value)
        return ','.join(origins)

    def _key_assign_picking(self):
        keys = super()._key_assign_picking()
        if self._split_by_origin():
            keys += (self._ful_origin_root_ids(),)
        return keys

    def _search_picking_for_assignation_domain(self):
        domain = super()._search_picking_for_assignation_domain()
        if not self._split_by_origin():
            return domain
        # Que la hoja del DFUL ya se haya impreso no lo vuelve un destino
        # equivocado para el backorder: preferimos agregarle los movimientos y
        # reimprimir, antes que abrir un segundo DFUL para la misma cita.
        return [
            leaf for leaf in domain
            if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == 'printed')
        ]

    def _search_picking_for_assignation(self):
        picking = super()._search_picking_for_assignation()
        if not self._split_by_origin():
            return picking
        roots = self._ful_origin_root_ids()
        if picking:
            existing_roots = picking.move_ids._ful_origin_root_ids()
            if existing_roots and roots and existing_roots != roots:
                picking = self.env['stock.picking']
        if picking:
            return picking

        # Sin DFUL reutilizable: si el de esta cadena ya se cerró, el backorder
        # no tiene a dónde ir y crear otro DFUL rompería el 1:1 con la cita.
        closed = self._ful_closed_sibling_dispatches()
        if closed:
            dispatch = closed[0]
            raise UserError(_(
                "El despacho %(dispatch)s, generado por este mismo Pick, ya está "
                "%(state)s, así que las piezas del backorder no pueden agregarse a él.\n\n"
                "Solicita a sistemas revertir o reabrir %(dispatch)s antes de validar."
            ) % {
                'dispatch': dispatch.name,
                'state': CLOSED_STATE_LABELS[dispatch.state],
            })
        return picking

    def _assign_picking_post_process(self, new=False):
        super()._assign_picking_post_process(new=new)
        # Se ejecuta tanto al crear el DFUL como al agregarle movimientos
        # (p. ej. al validar el backorder de un PFUL), por eso no se filtra
        # por `new`.
        picking = self.mapped('picking_id')
        if len(picking) != 1 or FUL_DISPATCH_TYPE not in (picking.picking_type_id.name or ''):
            return
        pful_pick = self._ful_source_pickings()
        if not pful_pick:
            return

        # El número de cita del marketplace vive en el `origin` del PFUL.
        # En un DFUL nuevo esto sustituye el valor que arma Odoo (el nombre del
        # PFUL); al agregar movimientos a un DFUL existente lo extiende.
        current_origin = False if new else picking.origin
        origin = self._merge_ful_origin(current_origin, pful_pick.mapped('origin'))
        if origin and origin != picking.origin:
            picking.write({'origin': origin})
            self.env['wmds.log'].sudo().create({
                'pick': picking.id,
                'log': f"Origen vinculado desde PFUL: {origin}",
                'user': self.env.user.id,
            })

        if not new:
            self.env['wmds.log'].sudo().create({
                'pick': picking.id,
                'log': "Backorder agregado al despacho: %s" % ', '.join(pful_pick.mapped('name')),
                'user': self.env.user.id,
            })

        first_pful = pful_pick[0]
        if first_pful.marketplace_location:
            loc = first_pful.marketplace_location
            changed = picking.marketplace_location != loc
            if changed:
                picking.write({'marketplace_location': loc.id, 'location_dest_id': loc.id})
            # También los movimientos recién asignados deben apuntar al marketplace.
            picking.move_ids.sudo().write({'location_dest_id': loc.id})
            if changed:
                self.env['wmds.log'].sudo().create({
                    'pick': picking.id,
                    'log': f"Marketplace vinculado desde PFUL: {loc.complete_name}",
                    'user': self.env.user.id,
                })
        elif picking.location_dest_id:
            first_pful.sudo().write({'marketplace_location': picking.location_dest_id.id})
