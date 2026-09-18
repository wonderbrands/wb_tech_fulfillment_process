# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class FulfillmentPicking(models.Model):
    """
    Extiende stock.picking para gestionar la propagación de marketplace_location
    entre operaciones PFUL (Resurtido a Ful: Pick) y DFUL (Resurtido a Ful: Despacho).

    Cuando Odoo crea un DFUL a partir de un PFUL, este override de create:
      1. Navega de los moves del DFUL → move_orig_ids → picking PFUL origen
      2. Si el DFUL ya tiene location_dest_id → lo propaga al PFUL como marketplace_location
      3. Si el PFUL ya tenía marketplace_location → lo aplica al DFUL (y a su location_dest_id)
      4. Tras el create, ajusta location_dest_id de todos los moves del DFUL al marketplace
      5. Registra el evento en wmds.log
    """

    _inherit = 'stock.picking'

    marketplace_location = fields.Many2one(
        "stock.location",
        string="Ubicación del marketplace",
    )

    @api.model
    def create(self, vals):
        # ── Lógica DFUL/PFUL: propagar marketplace_location ──────────────────
        if 'picking_type_id' in vals:
            picking_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])

            if picking_type.name and 'Resurtido a Ful: Despacho' in picking_type.name:
                pful_pick = self.env['stock.picking']

                # Navegar de los moves del DFUL hacia el PFUL origen vía move_orig_ids
                if 'move_ids' in vals:
                    orig_move_ids = []
                    for move_cmd in vals['move_ids']:
                        if move_cmd[0] in (0, 1) and isinstance(move_cmd[2], dict) and 'move_orig_ids' in move_cmd[2]:
                            for orig_cmd in move_cmd[2]['move_orig_ids']:
                                if orig_cmd[0] == 4:
                                    orig_move_ids.append(orig_cmd[1])
                                elif orig_cmd[0] == 6:
                                    orig_move_ids.extend(orig_cmd[2])

                    if orig_move_ids:
                        pful_pick = self.env['stock.move'].sudo().browse(orig_move_ids).mapped('picking_id').filtered(
                            lambda p: 'Resurtido a Ful: Pick' in (p.picking_type_id.name or '')
                        )

                if pful_pick:
                    first_pful = pful_pick[0]
                    if vals.get('location_dest_id'):
                        # DFUL tiene destino definido → propagarlo al PFUL
                        first_pful.sudo().write({'marketplace_location': vals['location_dest_id']})
                        vals['marketplace_location'] = vals['location_dest_id']
                    elif first_pful.marketplace_location:
                        # PFUL ya tenía marketplace_location → aplicarlo al DFUL
                        vals['marketplace_location'] = first_pful.marketplace_location.id
                        vals['location_dest_id'] = first_pful.marketplace_location.id

        res = super(FulfillmentPicking, self).create(vals)

        # Tras create: sincronizar location_dest_id de los moves del DFUL al marketplace
        if (
            res.marketplace_location
            and res.picking_type_id.name
            and 'Resurtido a Ful: Despacho' in res.picking_type_id.name
        ):
            res.move_ids.write({'location_dest_id': res.marketplace_location.id})
            self.env['wmds.log'].sudo().create({
                'pick': res.id,
                'log': f"Ubicación de destino del marketplace vinculada: {res.marketplace_location.complete_name}",
                'user': self.env.user.id,
            })

        return res
