{
    'name': 'WB Tech Fulfillment Process',
    'version': '18.0.1.1.0',
    'summary': 'Propagación de marketplace y documento origen entre PFUL y DFUL',
    'description': '''
        Gestiona la lógica de negocio específica del proceso de fulfillment:
        - Cuando se crea un DFUL (Resurtido a Ful: Despacho), propaga la
          ubicación de marketplace desde/hacia el PFUL (Resurtido a Ful: Pick)
          que lo originó.
        - Ajusta location_dest_id de los moves del DFUL al marketplace correcto.
        - Propaga el documento origen (número de cita del marketplace) del PFUL
          al DFUL, para que ambos queden ligados por el mismo identificador.
    ''',
    'author': 'Wonderbrands Tech',
    'category': 'Inventory',
    'depends': ['stock', 'wmds'],
    'data': [
        'views/fulfillment_picking_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
