# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    marketplace_location = fields.Many2one(
        "stock.location",
        string="Ubicación del marketplace",
    )

    # Campo técnico para controlar la visibilidad en la vista heredada
    picking_type_id_name = fields.Char(
        related='picking_type_id.name',
        string="Nombre del Tipo de Operación",
        store=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'picking_type_id' in vals:
                picking_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])
                
                # Lógica específica para DFUL (Despacho)
                if picking_type.name and 'Resurtido a Ful: Despacho' in picking_type.name:
                    # Intentamos recuperar el PFUL origen a través de los moves
                    if 'move_ids' in vals:
                        orig_move_ids = []
                        for move_cmd in vals['move_ids']:
                            # Odoo create_multi format: (0, 0, {values})
                            if move_cmd[0] == 0 and 'move_orig_ids' in move_cmd[2]:
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
                                    first_pful.sudo().write({'marketplace_location': vals['location_dest_id']})
                                    vals['marketplace_location'] = vals['location_dest_id']
                                elif first_pful.marketplace_location:
                                    vals['marketplace_location'] = first_pful.marketplace_location.id
                                    vals['location_dest_id'] = first_pful.marketplace_location.id

        pickings = super(StockPicking, self).create(vals_list)

        for res in pickings:
            # Post-procesamiento: sincronizar location_dest_id de los moves si es DFUL
            if (
                res.marketplace_location
                and res.picking_type_id.name
                and 'Resurtido a Ful: Despacho' in res.picking_type_id.name
            ):
                res.move_ids.write({'location_dest_id': res.marketplace_location.id})
                if 'wmds.log' in self.env:
                    self.env['wmds.log'].sudo().create({
                        'pick': res.id,
                        'log': f"Ubicación de destino del marketplace vinculada: {res.marketplace_location.complete_name}",
                        'user': self.env.user.id,
                    })
        return pickings
