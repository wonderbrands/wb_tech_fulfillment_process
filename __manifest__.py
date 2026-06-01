{
    'name': 'WB Tech Fulfillment Process',
    'version': '18.0.1.0.0',
    'summary': 'Control de consolidación 1:1 y propagación de marketplace en fulfillment',
    'description': '''
        Módulo para Odoo 18 Enterprise que:
        - Permite prevenir la consolidación de movimientos de stock (Relación 1:1 PFUL-DFUL).
        - Añade configuración por tipo de operación (prevent_consolidation).
        - Propaga la ubicación de marketplace entre recolección y despacho.
    ''',
    'author': 'Wonderbrands Tech',
    'category': 'Inventory',
    'depends': ['stock', 'wmds'],
    'data': [
        'views/stock_picking_type_views.xml',
        'views/fulfillment_picking_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
