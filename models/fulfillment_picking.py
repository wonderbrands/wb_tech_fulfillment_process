from odoo import models, fields, api


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
        if not new:
            return
        picking = self.mapped('picking_id')
        if len(picking) != 1 or 'Resurtido a Ful: Despacho' not in (picking.picking_type_id.name or ''):
            return
        pful_pick = self.move_orig_ids.mapped('picking_id').filtered(
            lambda p: 'Resurtido a Ful: Pick' in (p.picking_type_id.name or '')
        )
        if not pful_pick:
            return
        first_pful = pful_pick[0]
        if first_pful.marketplace_location:
            loc = first_pful.marketplace_location.id
            picking.write({'marketplace_location': loc, 'location_dest_id': loc})
            picking.move_ids.sudo().write({'location_dest_id': loc})
            self.env['wmds.log'].sudo().create({
                'pick': picking.id,
                'log': f"Marketplace vinculado desde PFUL: {first_pful.marketplace_location.complete_name}",
                'user': self.env.user.id,
            })
        elif picking.location_dest_id:
            first_pful.sudo().write({'marketplace_location': picking.location_dest_id.id})
