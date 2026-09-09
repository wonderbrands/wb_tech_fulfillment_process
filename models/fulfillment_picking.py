from odoo import models, fields, api

# Nombres de los tipos de operación del flujo de fulfillment.
# El emparejamiento por nombre es frágil (renombrar el tipo desde la interfaz
# rompe la lógica sin error); se centraliza aquí para poder sustituirlo más
# adelante por un campo propio en stock.picking.type.
FUL_PICK_TYPE = 'Resurtido a Ful: Pick'
FUL_DISPATCH_TYPE = 'Resurtido a Ful: Despacho'


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
            orig_picking_ids = tuple(sorted(set(
                self.move_orig_ids.mapped('picking_id').ids
            )))
            keys += (orig_picking_ids,)
        return keys

    def _search_picking_for_assignation(self):
        picking = super()._search_picking_for_assignation()
        if picking and self._split_by_origin():
            existing_origins = picking.move_ids.move_orig_ids.picking_id
            new_origins = self.move_orig_ids.picking_id
            if existing_origins and new_origins and existing_origins != new_origins:
                return self.env['stock.picking']
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
