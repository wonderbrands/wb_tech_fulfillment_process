# -*- coding: utf-8 -*-
from odoo import models, fields

class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    prevent_consolidation = fields.Boolean(
        string="Prevenir Consolidación de Transferencias",
        help="Si está marcado, los movimientos de este tipo no se agruparán en el mismo albarán ni se fusionarán sus líneas.",
        default=False
    )
