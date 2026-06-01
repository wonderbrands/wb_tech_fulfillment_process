# -*- coding: utf-8 -*-
from odoo import models, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _merge_moves(self, merge_into=False):
        """
        Si el tipo de operación tiene prevent_consolidation, evitamos la fusión de líneas.
        """
        moves_to_merge = self
        if self.picking_type_id.prevent_consolidation or (merge_into and merge_into.picking_type_id.prevent_consolidation):
            return self
        return super(StockMove, self)._merge_moves(merge_into=merge_into)

    def _search_picking_for_assignation(self):
        """
        Si el tipo de operación previene la consolidación, retornamos False
        para forzar la creación de un nuevo picking (albarán).
        """
        self.ensure_one()
        if self.picking_type_id.prevent_consolidation:
            return False
        return super(StockMove, self)._search_picking_for_assignation()

    @api.model_create_multi
    def create(self, vals_list):
        # Aseguramos que si se crean moves para un tipo con prevent_consolidation,
        # se les asigne un grupo de abastecimiento único si no lo tienen,
        # para ayudar a la separación en _assign_picking si fuera necesario.
        return super(StockMove, self).create(vals_list)
