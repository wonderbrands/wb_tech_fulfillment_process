{
    'name': 'WB Tech Fulfillment Process',
    'version': '18.0.1.4.0',
    'summary': 'Propagación de marketplace y documento origen entre PFUL y DFUL',
    'description': '''
        Gestiona la lógica de negocio específica del proceso de fulfillment:
        - El rol de cada tipo de operación (Pick / Despacho) se declara en un
          campo propio, en lugar de deducirse del nombre del tipo.
        - Cuando se crea un DFUL (Despacho), propaga la ubicación de marketplace
          desde/hacia el PFUL (Pick) que lo originó.
        - Ajusta location_dest_id de los moves del DFUL al marketplace correcto.
        - Propaga el documento origen (número de cita del marketplace) del PFUL
          al DFUL, para que ambos queden ligados por el mismo identificador.
        - Consolida los backorders de un mismo PFUL en el DFUL original, para
          poder surtir el Pick en varias rondas sin abrir un despacho por ronda.
        - Comparte el operador entre los Pick abiertos de una misma cadena.
        - Congela la fecha programada del Despacho: es la fecha de entrega, no
          la de la ultima validacion de Pick.
        - Da a cada Pick parcial su propio traslado por lote.
    ''',
    'author': 'Wonderbrands Tech',
    'category': 'Inventory',
    'depends': ['stock', 'wmds'],
    'data': [
        'views/fulfillment_picking_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
