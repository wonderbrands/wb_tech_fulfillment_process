# -*- coding: utf-8 -*-
"""Asigna `ful_role` a los tipos de operación de fulfillment ya existentes.

Hasta la 18.0.1.0.0 el rol se deducía del nombre del tipo de operación. Este
script traduce esa convención a un dato explícito, para que la actualización no
cambie el comportamiento de ninguna base en producción.
"""
import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.wb_tech_fulfillment_process.models.fulfillment_picking import seed_ful_roles

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    seed_ful_roles(env)
    _logger.info("wb_tech_fulfillment_process: migración de ful_role completada")
