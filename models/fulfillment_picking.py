import logging

from odoo import models, fields, api
# NOTA Odoo 19: `odoo.osv.expression` desaparece; `AND` y `TRUE_LEAF` se
# sustituyen por el nuevo `odoo.fields.Domain`. Solo se usan en
# `_search_picking_for_assignation_domain` y `_search_picking_for_assignation`.
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# Nombres con los que se bautizaron los tipos de operación antes de que el rol
# fuera un dato explícito. Ya NO se usan en runtime: sirven únicamente como
# semilla para marcar `ful_role` en las bases que vienen de una versión previa
# (ver `seed_ful_roles`). Una vez migradas, renombrar el tipo desde la interfaz
# deja de romper la lógica.
LEGACY_FUL_TYPE_NAMES = (
    ('pick', 'Resurtido a Ful: Pick'),
    ('dispatch', 'Resurtido a Ful: Despacho'),
)

FUL_ROLES = [
    ('pick', 'Fulfillment: Pick (PFUL)'),
    ('dispatch', 'Fulfillment: Despacho (DFUL)'),
]

# Estados en los que un DFUL ya no admite movimientos nuevos.
CLOSED_STATES = {
    'done': 'validado',
    'cancel': 'cancelado',
}


def seed_ful_roles(env):
    """Marca `ful_role` en los tipos de operación que aún no lo tienen.

    Replica el emparejamiento por subcadena que hacía la versión anterior, de
    modo que una base existente conserve exactamente el mismo comportamiento
    tras actualizar. Solo toca los tipos sin rol asignado: una configuración
    hecha a mano nunca se sobrescribe.
    """
    picking_type = env['stock.picking.type'].with_context(active_test=False)
    for role, legacy_name in LEGACY_FUL_TYPE_NAMES:
        types = picking_type.search([
            ('name', 'ilike', legacy_name),
            ('ful_role', '=', False),
        ])
        if types:
            types.write({'ful_role': role})
            _logger.info(
                "wb_tech_fulfillment_process: ful_role=%s asignado a %s tipo(s) de operación: %s",
                role, len(types), ', '.join(types.mapped('display_name')),
            )


class FulfillmentPicking(models.Model):
    """
    Extiende stock.picking para gestionar la propagación de marketplace_location
    y del documento origen entre operaciones PFUL (Pick) y DFUL (Despacho).
    """
    _inherit = 'stock.picking'

    marketplace_location = fields.Many2one(
        "stock.location",
        string="Ubicación del marketplace",
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Ubicación física del marketplace a la que se despachará la "
             "mercancía. Se propaga al albarán de despacho generado por este "
             "Pick, y pasa a ser su ubicación de destino.",
    )

    # Se expone el rol en el picking para que la vista pueda condicionar sin
    # depender del nombre visible del tipo de operación.
    picking_type_ful_role = fields.Selection(
        related='picking_type_id.ful_role',
        string='Rol en fulfillment',
        store=True,
    )

    def _ful_backorder_root(self):
        """Retorna el albarán original del que desciende este backorder.

        Odoo encadena `backorder_id` hacia el padre inmediato cada vez que se
        valida parcialmente (`stock.picking._create_backorder_picking`), así que
        con varias rondas de pickeo queda PFUL-C → PFUL-B → PFUL-A. Subir hasta
        la raíz da el identificador del trabajo completo: el PFUL tal como se
        planeó, sin importar en cuántas partes se acabe surtiendo.
        """
        self.ensure_one()
        picking = self
        seen = {picking.id}
        while picking.backorder_id and picking.backorder_id.id not in seen:
            picking = picking.backorder_id
            seen.add(picking.id)
        return picking

    def _ful_backorder_family(self):
        """Retorna la cadena completa de backorders: la raíz y sus descendientes."""
        family = self.browse()
        for picking in self:
            frontier = picking._ful_backorder_root()
            while frontier:
                family |= frontier
                frontier = frontier.backorder_ids - family
        return family

    # ------------------------------------------------------------------
    # Operador compartido por la cadena
    # ------------------------------------------------------------------

    def write(self, vals):
        res = super().write(vals)
        if 'operator' in vals and not self.env.context.get('ful_operator_sync'):
            self._ful_propagate_operator(vals['operator'])
        return res

    def _ful_propagate_operator(self, operator_id):
        """Mantiene un mismo operador en toda la cadena de PFUL.

        El backorder nace con el operador del padre porque `operator` se copia,
        pero a partir de ahí los dos registros van por su cuenta: reasignar el
        trabajo en un eslabón dejaba al resto con el operador anterior.

        Solo se propaga a los albaranes **abiertos**: uno ya validado o
        cancelado registra quién surtió esa parte, y reescribirlo falsearía el
        histórico.
        """
        for picking in self.filtered(lambda p: p.picking_type_ful_role == 'pick'):
            hermanos = picking._ful_backorder_family().filtered(
                lambda p: p != picking
                and p.state not in ('done', 'cancel')
                and p.operator.id != operator_id
            )
            if hermanos:
                hermanos.with_context(ful_operator_sync=True).write(
                    {'operator': operator_id})

    # ------------------------------------------------------------------
    # Fecha programada del despacho
    # ------------------------------------------------------------------

    @api.depends('move_ids.state', 'move_ids.date', 'move_type')
    def _compute_scheduled_date(self):
        """Congela la fecha programada de los DFUL.

        El cálculo del core toma la fecha de los movimientos, y el movimiento
        que empuja la regla trae la hora de validación del PFUL. Resultado: el
        DFUL corría su fecha programada en cada ronda de pickeo, cuando esa
        fecha es el compromiso de entrega y no debe moverse.

        Se conserva el valor ya almacenado, así que ni los DFUL abiertos ni el
        histórico cambian: simplemente dejan de desplazarse. El valor inicial lo
        fija `_ful_sync_scheduled_date` al crear el despacho, y el usuario puede
        seguir ajustándolo a mano porque el `inverse` sigue activo.
        """
        congelados = self.filtered(
            lambda p: p.picking_type_ful_role == 'dispatch' and p.scheduled_date
        )
        conservados = {p.id: p.scheduled_date for p in congelados}
        super(FulfillmentPicking, self - congelados)._compute_scheduled_date()
        for picking in congelados:
            picking.scheduled_date = conservados[picking.id]

    # ------------------------------------------------------------------
    # Lote propio por cada parcial
    # ------------------------------------------------------------------

    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        backorders._ful_assign_own_batch()
        return backorders

    def _ful_assign_own_batch(self):
        """Cada parcial de fulfillment estrena su propio traslado por lote.

        `stock.picking.batch.batch_id` está declarado con `copy=False`, así que
        el backorder nunca heredaba el lote del padre y se quedaba suelto. Y
        heredarlo tampoco serviría: para cuando nace el backorder, el lote del
        padre suele estar ya validado y no admite albaranes nuevos.

        Solo afecta a los backorders que se creen a partir de ahora.
        """
        batch_model = self.env['stock.picking.batch']
        for picking in self.filtered(
                lambda p: p.picking_type_ful_role == 'pick' and not p.batch_id):
            batch = batch_model.create({
                'picking_type_id': picking.picking_type_id.id,
                'company_id': picking.company_id.id,
                'operator': picking.operator.id,
                'picking_ids': [(4, picking.id)],
            })
            # Los lotes de fulfillment se trabajan en curso, no en borrador:
            # el picker debe encontrarlo listo.
            batch.action_confirm()
            self.env['wmds.log'].sudo().create({
                'pick': picking.id,
                'log': f"Lote creado para el parcial: {batch.name}",
                'user': self.env.user.id,
            })


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    ful_role = fields.Selection(
        FUL_ROLES,
        string="Rol en fulfillment",
        help="Define el papel de este tipo de operación dentro del flujo de "
             "fulfillment. El módulo usa este campo —y no el nombre del tipo— "
             "para decidir entre qué albaranes propagar la ubicación del "
             "marketplace y el documento origen (número de cita).",
    )

    no_merge_destination = fields.Boolean(
        string="No consolidar destinos",
        help="Al validar, cada cadena de albaranes origen genera su propio albarán "
             "destino. Los backorders de un mismo albarán se consideran la misma "
             "cadena y se consolidan en un único destino.",
    )


class FulfillmentStockMove(models.Model):
    _inherit = 'stock.move'

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    def _split_by_origin(self):
        """Retorna True si el move debe forzar separación por cadena de origen
        según la configuración de su tipo de operación o del origen."""
        self.ensure_one()
        if not self.move_orig_ids:
            return False
        return self.picking_type_id.no_merge_destination or any(
            self.move_orig_ids.mapped('picking_id.picking_type_id.no_merge_destination')
        )

    def _ful_source_pickings(self):
        """Retorna los PFUL que originan estos movimientos."""
        return self.move_orig_ids.picking_id.filtered(
            lambda p: p.picking_type_id.ful_role == 'pick'
        )

    def _ful_origin_root_ids(self):
        """IDs de los albaranes raíz que originan estos movimientos.

        Se agrupa por la raíz de la cadena de backorders y no por el albarán
        concreto, para que un PFUL surtido en varias partes alimente siempre el
        mismo DFUL en lugar de abrir uno nuevo por cada ronda de pickeo.
        """
        return tuple(sorted({
            picking._ful_backorder_root().id
            for picking in self.move_orig_ids.picking_id
        }))

    def _ful_candidate_dest_location_ids(self):
        """Ubicaciones destino que identifican al DFUL de esta cadena.

        El move que empuja la regla llega con el destino de la ruta
        (`stock.rule._push_prepare_move_copy_values`), pero el DFUL ya existente
        pudo haber sido reapuntado al marketplace por este mismo módulo. Ambos
        valores designan al mismo despacho, así que la búsqueda debe aceptarlos.
        """
        self.ensure_one()
        location_ids = set()
        dest = self.location_dest_id.id or self.picking_type_id.default_location_dest_id.id
        if dest:
            location_ids.add(dest)
        marketplaces = self._ful_source_pickings()._ful_backorder_family().marketplace_location
        location_ids.update(marketplaces.ids)
        return sorted(location_ids)

    def _ful_closed_sibling_dispatches(self, origin=None):
        """DFUL ya cerrados generados por la misma cadena de PFUL que estos moves.

        Se buscan por dos vías porque ninguna basta sola:

        - **Por el encadenamiento de movimientos.** Es exacto, pero no sobrevive
          a una cancelación: `stock.move._action_cancel` termina con
          `write({'move_orig_ids': [(5, 0, 0)]})` (`stock_move.py:2048`), que
          borra el vínculo. Un DFUL cancelado queda inalcanzable por esta vía.
        - **Por documento origen.** Sobrevive a la cancelación y es, además, lo
          que identifica la cita de cara al usuario, que es de lo que avisa.
        """
        dispatches = self.env['stock.picking']
        family = self._ful_source_pickings()._ful_backorder_family()
        if family:
            dispatches |= family.move_ids.move_dest_ids.picking_id
        if origin:
            dispatches |= self.env['stock.picking'].search([
                ('picking_type_ful_role', '=', 'dispatch'),
                ('origin', '=', origin),
                ('state', 'in', list(CLOSED_STATES)),
            ])
        return dispatches.filtered(
            lambda p: p.picking_type_id.ful_role == 'dispatch'
            and p.state in CLOSED_STATES
        )

    def _ful_log(self, picking, mensaje):
        self.env['wmds.log'].sudo().create({
            'pick': picking.id,
            'log': mensaje,
            'user': self.env.user.id,
        })

    # ------------------------------------------------------------------
    # Asignación de albarán destino
    # ------------------------------------------------------------------

    def _key_assign_picking(self):
        keys = super()._key_assign_picking()
        if self._split_by_origin():
            keys += (self._ful_origin_root_ids(),)
        return keys

    def _search_picking_for_assignation_domain(self):
        """Amplía el dominio base para que el DFUL de la cadena siga siendo visible.

        El dominio del core descarta dos candidatos que aquí sí son válidos:
        el DFUL cuya hoja ya se imprimió, y el DFUL cuyo destino fue reapuntado
        al marketplace por este módulo.
        """
        domain = super()._search_picking_for_assignation_domain()
        if not self._split_by_origin():
            return domain

        # Las hojas se SUSTITUYEN, nunca se eliminan. El dominio casi siempre
        # llega con operadores explícitos —`stock_picking_batch` le añade un
        # '|' para las olas, y `sale_stock_renting` también lo amplía—, y quitar
        # una hoja de un dominio en notación prefija descuadra la aridad de los
        # operadores. Una sustitución 1 a 1 preserva la estructura sea cual sea.
        dest_location_ids = self._ful_candidate_dest_location_ids()
        rebuilt = []
        for leaf in domain:
            field = leaf[0] if isinstance(leaf, (list, tuple)) and len(leaf) == 3 else None
            # Que la hoja del DFUL ya se haya impreso no lo vuelve un destino
            # equivocado para el backorder: preferimos agregarle los movimientos
            # y reimprimir, antes que abrir un segundo DFUL para la misma cita.
            if field == 'printed':
                rebuilt.append(expression.TRUE_LEAF)
                continue
            if field == 'location_dest_id' and len(dest_location_ids) > 1:
                rebuilt.append(('location_dest_id', 'in', dest_location_ids))
                continue
            rebuilt.append(leaf)
        return rebuilt

    def _search_picking_for_assignation(self):
        picking = super()._search_picking_for_assignation()
        if not self._split_by_origin():
            return picking
        roots = self._ful_origin_root_ids()
        if not roots:
            return picking
        if picking and picking.move_ids._ful_origin_root_ids() == roots:
            return picking

        # El core busca con `limit=1`, así que pudo devolver el DFUL de otra
        # cadena aunque el de esta exista; rendirse ahí abriría un despacho de
        # más. Se repite la búsqueda acotada a los albaranes alimentados por
        # esta cadena: así el filtrado lo hace SQL en una sola consulta en vez
        # de recorrer en Python todos los despachos abiertos del almacén.
        family = self._ful_source_pickings()._ful_backorder_family()
        if not family:
            return self.env['stock.picking']
        domain = expression.AND([
            self._search_picking_for_assignation_domain(),
            [('move_ids.move_orig_ids.picking_id', 'in', family.ids)],
        ])
        # `order='id asc'` fija cuál gana si la cadena arrastra varios DFUL
        # abiertos: siempre el más antiguo, el de la raíz. El orden por defecto
        # de stock.picking (`priority desc, scheduled_date asc, id desc`) haría
        # que dependiera de la prioridad y la fecha, es decir, del azar.
        for candidate in self.env['stock.picking'].search(domain, order='id asc'):
            # Coincidencia exacta: un DFUL sin movimientos encadenados, o de
            # otra cadena, no es destino válido para este backorder.
            if candidate.move_ids._ful_origin_root_ids() == roots:
                return candidate
        return self.env['stock.picking']

    # ------------------------------------------------------------------
    # Propagación PFUL <-> DFUL
    # ------------------------------------------------------------------

    def _assign_picking_post_process(self, new=False):
        super()._assign_picking_post_process(new=new)
        # Corre tanto al crear el DFUL como al agregarle los movimientos de un
        # backorder posterior, por eso no se filtra por `new`.
        picking = self.mapped('picking_id')
        if len(picking) != 1 or picking.picking_type_id.ful_role != 'dispatch':
            return
        pful_pick = self._ful_source_pickings()
        if not pful_pick:
            return
        # El orden de un recordset obtenido por navegación no está garantizado;
        # se ordena para que "el primero" sea siempre el PFUL más antiguo de la
        # cadena y la elección no dependa del azar.
        first_pful = pful_pick.sorted('id')[0]

        self._ful_sync_origin(picking, first_pful, new=new)
        self._ful_sync_marketplace(picking, first_pful)

        if new:
            self._ful_sync_scheduled_date(picking, first_pful)
            self._ful_warn_split_dispatch(picking)
        else:
            # Solo se anuncia como consolidación lo que de verdad lo es: a este
            # método también se llega al agregar movimientos por otros motivos.
            backorders = pful_pick.filtered(lambda p: p.backorder_id)
            if backorders:
                self._ful_log(picking, "Backorder consolidado en este despacho: %s"
                              % ', '.join(backorders.mapped('name')))

    def _ful_sync_origin(self, picking, pful, new=False):
        """Deja en el DFUL un único documento origen: el de la raíz de la cadena.

        Odoo lo escribe por dos vías y ninguna sirve aquí:

        - al crear el DFUL usa el origin de los moves, que la regla push rellena
          con el nombre del albarán origen (`WH/PFUL/00456`);
        - al agregarle moves concatena con comas el origin de cada move nuevo
          (`stock.move._assign_picking_values`), con lo que el campo crecería
          una entrada por cada ronda de pickeo:
          `APPT-8891,WH/PFUL/00456-001,WH/PFUL/00456-002...`

        Se toma el valor de la raíz y no del eslabón actual para que las tres
        rondas de un mismo PFUL escriban siempre lo mismo. Si la raíz no tiene
        número de cita se usa su nombre, de modo que el campo quede igualmente
        limpio en lugar de acumular los nombres de los backorders.
        """
        root = pful._ful_backorder_root()
        deseado = root.origin or root.name
        if not deseado or picking.origin == deseado:
            return
        anterior = picking.origin
        picking.write({'origin': deseado})
        self._ful_log(picking, (
            f"Documento origen vinculado desde {root.name}: {deseado}" if new
            else f"Documento origen restaurado a {deseado} al consolidar "
                 f"{pful.name} (Odoo lo había dejado en «{anterior}»)"
        ))

    def _ful_sync_scheduled_date(self, picking, pful):
        """Hereda al DFUL la fecha programada del PFUL raíz.

        Sin esto el despacho nace con la hora de validación del Pick: el cálculo
        del core toma la fecha de los movimientos y el que empuja la regla trae
        esa hora. Lo que importa aquí es la fecha de entrega planificada, que es
        la del Pick original.

        Solo se escribe al crear el DFUL (`new=True`): ningún despacho ya
        existente se toca. A partir de ahí la fecha queda congelada por
        `stock.picking._compute_scheduled_date`.
        """
        root = pful._ful_backorder_root()
        if not root.scheduled_date or picking.scheduled_date == root.scheduled_date:
            return
        if picking.state in ('done', 'cancel'):
            # El `inverse` del campo rechaza un albarán cerrado.
            return
        picking.scheduled_date = root.scheduled_date
        self._ful_log(
            picking,
            f"Fecha programada heredada de {root.name}: {root.scheduled_date}",
        )

    def _ful_sync_marketplace(self, picking, pful):
        """Apunta el DFUL —y sus movimientos— a la ubicación del marketplace."""
        loc = pful.marketplace_location
        if not loc:
            # El marketplace lo define la ruta: se devuelve a toda la cadena,
            # no solo al eslabón que se acaba de validar, para que los
            # backorders siguientes ya lo traigan puesto.
            if picking.location_dest_id:
                family = pful._ful_backorder_family().filtered(
                    lambda p: p.marketplace_location != picking.location_dest_id
                )
                if family:
                    family.sudo().write({'marketplace_location': picking.location_dest_id.id})
            return

        # La cabecera se sincroniza campo por campo y no en bloque: al agregar
        # movimientos, el core borra `partner_id` si los socios difieren
        # (`stock.move._assign_picking_values`), y `location_dest_id` depende de
        # él (`stock.picking._compute_location_id`), así que puede haber
        # revertido al destino por defecto del tipo de operación aunque
        # `marketplace_location` siguiera correcto.
        vals = {}
        marketplace_changed = picking.marketplace_location != loc
        if marketplace_changed:
            vals['marketplace_location'] = loc.id
        if picking.location_dest_id != loc:
            vals['location_dest_id'] = loc.id
        if vals:
            picking.write(vals)

        # Los movimientos recién agregados llegan con el destino de la ruta, así
        # que hay que reapuntarlos. Y con ellos sus líneas: una línea ya
        # reservada conserva la ubicación vieja y mandaría la mercancía al lugar
        # equivocado al validar.
        moves = picking.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.location_dest_id != loc
        )
        if moves:
            moves.sudo().write({'location_dest_id': loc.id})
            lines = moves.move_line_ids.filtered(lambda l: l.location_dest_id != loc)
            if lines:
                lines.sudo().write({'location_dest_id': loc.id})

        if marketplace_changed:
            self._ful_log(picking, f"Marketplace vinculado desde PFUL: {loc.complete_name}")

    def _ful_warn_split_dispatch(self, picking):
        """Avisa cuando la cita queda repartida en más de un DFUL.

        Solo ocurre si el DFUL de la cadena ya estaba validado o cancelado
        cuando llegó el backorder: no se le pueden agregar movimientos, y la
        mercancía no puede quedarse detenida, así que se abre uno nuevo.
        """
        # `picking.origin` ya trae el origen canónico de la cadena: a este
        # método se llega después de `_ful_sync_origin`.
        closed = self._ful_closed_sibling_dispatches(origin=picking.origin) - picking
        if not closed:
            return
        aviso = (
            "Este despacho se creó aparte: el despacho %s de la misma cita ya está %s, "
            "así que el backorder no pudo agregarse a él. La cita queda en dos despachos."
        ) % (closed[0].name, CLOSED_STATES[closed[0].state])
        picking.message_post(body=aviso)
        self._ful_log(picking, aviso)
