# -*- coding: utf-8 -*-
from . import models

from .models.fulfillment_picking import seed_ful_roles


def post_init_hook(env):
    """Marca el rol de fulfillment en los tipos de operación ya existentes.

    Solo corre al instalar. Para las bases que ya tenían el módulo instalado,
    el equivalente vive en migrations/18.0.1.1.0/post-seed_ful_roles.py.
    """
    seed_ful_roles(env)
