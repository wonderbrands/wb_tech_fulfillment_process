# WB Tech Fulfillment Process

Módulo para Odoo 18 que gestiona la propagación de la ubicación de marketplace y del documento origen entre operaciones **PFUL** (Pick) y **DFUL** (Despacho) en el proceso de fulfillment.

## Funcionalidades

### 1. Rol de fulfillment declarado en el tipo de operación

El módulo necesita saber qué tipo de operación es el Pick y cuál es el Despacho. Ese dato vive en el
campo **"Rol en fulfillment"** (`ful_role`) del tipo de operación, con dos valores posibles:

| Valor | Significado |
|---|---|
| `pick` | Fulfillment: Pick (PFUL) |
| `dispatch` | Fulfillment: Despacho (DFUL) |

Antes el rol se deducía del **nombre** del tipo (`'Resurtido a Ful: Pick'`). Eso significaba que
renombrar el tipo desde la interfaz rompía la lógica **sin producir ningún error**: simplemente
dejaba de propagarse nada. Con el campo explícito, el nombre del tipo es libre.

### 2. Propagación de `marketplace_location`

Cuando se valida un PFUL y Odoo crea automáticamente el DFUL:

- **PFUL → DFUL:** Si el PFUL tiene definida una **Ubicación del marketplace**, esta se propaga automáticamente como ubicación de destino (`location_dest_id`) del DFUL y de todos sus movimientos.
- **DFUL → PFUL:** Si el PFUL no tiene definida una ubicación de marketplace, se toma la ubicación de destino que trae el DFUL (desde la ruta/configuración) y se propaga al PFUL como `marketplace_location`.

### 3. Propagación del documento origen (número de cita)

El campo **Documento origen** (`origin`) del PFUL contiene el **número de cita** que asigna el
marketplace. Al generarse el DFUL, ese valor se copia al DFUL para que ambas operaciones queden
ligadas por el mismo identificador y la búsqueda funcione desde cualquiera de los dos lados.

- Sustituye el valor que Odoo asigna por defecto (el **nombre** del PFUL, p. ej. `WH/PFUL/00456`).
- El DFUL conserva **una sola cita**. Si más tarde se le agregan movimientos, la cita del PFUL más
  antiguo de la cadena se conserva — no se sobrescribe ni se acumula.
- Si el PFUL no tiene documento origen, el DFUL conserva el valor por defecto de Odoo.
- Queda registrado en `wmds.log`.

Mantener una sola cita exige corregir a Odoo en dos momentos, porque el core escribe el `origin` por
dos vías y ninguna sirve aquí:

| Momento | Qué hace el core | Qué hace el módulo |
|---|---|---|
| Al crear el DFUL | Toma el `origin` de los movimientos, que la regla push rellenó con el nombre del albarán origen (`stock.rule._push_prepare_move_copy_values`) | Lo sustituye por la cita |
| Al consolidar un backorder | Concatena con comas el `origin` de cada movimiento nuevo (`stock.move._assign_picking_values`), con lo que el campo crecería a `APPT-8891,WH/PFUL/00456-001,WH/PFUL/00456-002...` | Restaura la cita |

Como el backorder es una copia del PFUL, arrastra la misma cita: consolidar nunca cambia el valor.

> ℹ️ Compartir el número de cita entre el PFUL y su DFUL es el objetivo del cambio: es lo que
> mantiene ligadas ambas operaciones. Como consecuencia, el número de cita ya no identifica a un
> solo albarán — cualquier consulta que espere un único registro debe filtrar además por tipo de
> operación.

### 4. Un DFUL por cadena de PFUL (pickeo en varias rondas)

Por defecto Odoo consolida PFUL no emparentados en un solo DFUL. Este módulo lo evita: **cada cadena
de PFUL genera su propio DFUL**. Se controla con el flag **"No consolidar destinos"** del tipo de
operación.

La unidad de agrupación es la **cadena de backorders**, no el albarán suelto. Eso permite que el
picker surta un PFUL grande en varias rondas sin que se multipliquen los despachos:

```
PFUL-A (100 pz) ──validar 20──→ DFUL-1 (20 pz)   ← se crea
       └─ backorder PFUL-B (80 pz)
                   ──validar 20──→ DFUL-1 (40 pz)  ← se consolida
                   └─ backorder PFUL-C (60 pz)
                              ──validar 20──→ DFUL-1 (60 pz)
```

Dos PFUL **sin parentesco** siguen generando DFUL separados: solo cambió el criterio de "mismo
origen", de *mismo albarán* a *misma cadena*.

Para lograrlo el módulo amplía el dominio con el que Odoo busca el albarán destino, que descartaba
dos candidatos perfectamente válidos:

| Condición del core | Por qué se relaja |
|---|---|
| `printed = False` | Que la hoja del DFUL ya se imprimiera no lo vuelve un destino equivocado. Se prefiere agregarle los movimientos y reimprimir, antes que abrir un segundo despacho para la misma cita. |
| `location_dest_id = <destino de la ruta>` | El módulo reapunta el destino del DFUL al marketplace, mientras que el movimiento que empuja la regla llega con el destino de la ruta. Ambos valores designan al mismo despacho, así que se aceptan los dos. |

Además, el core busca con `limit=1` y su orden por defecto (`priority desc, scheduled_date asc,
id desc`) puede devolver el DFUL de otra cadena aunque el correcto exista. El módulo repite entonces
la búsqueda **acotada a los albaranes alimentados por esta cadena**, de modo que el filtrado lo hace
SQL en una sola consulta en vez de recorrer en Python todos los despachos abiertos del almacén, y
ordenada por `id asc` para que gane siempre el más antiguo si la cadena arrastra varios.

La coincidencia de cadena es **exacta**: un DFUL sin movimientos encadenados, o de otra cadena, no es
destino válido. Antes se aceptaba cualquier candidato sin encadenar, lo que permitía que un backorder
acabara en un despacho ajeno con la cita y el marketplace de otra cadena.

#### Cuando el DFUL ya está cerrado

Si el DFUL de la cadena ya se validó o canceló cuando llega el backorder, no admite movimientos
nuevos. La mercancía no puede quedarse detenida, así que **se abre un DFUL nuevo** y se publica un
aviso en el chatter y en `wmds.log`:

> Este despacho se creó aparte: el despacho WH/DFUL/00123 de la misma cita ya está validado, así que
> el backorder no pudo agregarse a él. La cita queda en dos despachos.

Los despachos hermanos se localizan por **dos vías**, porque ninguna basta sola:

| Vía | Alcance |
|---|---|
| Encadenamiento de movimientos | Exacto, pero **no sobrevive a una cancelación**: `stock.move._action_cancel` termina con `write({'move_orig_ids': [(5, 0, 0)]})`, que borra el vínculo |
| Documento origen | Sobrevive a la cancelación, y es lo que identifica la cita de cara al usuario |

Sin la segunda, el aviso nunca se disparaba con un DFUL **cancelado** — solo con uno validado.

### 5. Operador compartido por la cadena

El campo **Operador** (`operator`, que aporta `wmds`) se copia al backorder, pero a partir de ahí los
dos registros iban por su cuenta: reasignar el trabajo en un eslabón dejaba al resto con el operador
anterior. Ahora, al cambiarlo en cualquier Pick de fulfillment, se replica a toda la cadena.

> Solo alcanza a los albaranes **abiertos**. Un Pick ya validado o cancelado registra quién surtió esa
> parte concreta, y reescribirlo falsearía el histórico.

### 6. Fecha programada del despacho congelada

`scheduled_date` es un campo calculado y almacenado cuyo cálculo toma la fecha de los movimientos
(`stock.picking._compute_scheduled_date`). Como el movimiento que empuja la regla trae la **hora de
validación** del Pick, el despacho corría su fecha en cada ronda de pickeo.

En el proceso de fulfillment esa fecha es el **compromiso de entrega**, así que el módulo:

1. Al crear el DFUL le hereda la fecha programada del **PFUL raíz**, no la de validación.
2. A partir de ahí la congela: consolidar backorders ya no la mueve.

El `inverse` del campo sigue activo, así que un ajuste manual se respeta y el módulo no lo pisa. La
congelación conserva el valor almacenado, de modo que ningún despacho existente cambia: simplemente
deja de desplazarse.

### 7. Un lote por cada parcial

`stock.picking.batch_id` está declarado con **`copy=False`**, así que el backorder nunca heredaba el
lote del padre y quedaba suelto. Heredarlo tampoco serviría: cuando nace el backorder, el lote del
padre suele estar ya validado y no admite albaranes nuevos.

Cada Pick parcial estrena por tanto **su propio traslado por lote**, confirmado (`in_progress`) y con
el **operador** heredado, para que el picker lo encuentre listo. Los despachos no entran a ningún
lote.

> La agrupación automática nativa de Odoo 18 (`auto_batch` en el tipo de operación) no sirve aquí:
> solo agrupa por contacto, país o ubicación, y como todos los Pick comparten origen y destino
> acabarían en un único lote gigante.

### 8. Campos en la interfaz

El campo **"Ubicación del marketplace"** se muestra (y es obligatorio) en el formulario de los
albaranes cuyo tipo de operación tiene `ful_role = 'pick'`. Solo admite ubicaciones **internas** de
la compañía del albarán, para evitar que se capture por error una virtual o de proveedor.

El rol se almacena en el albarán (`picking_type_ful_role`), lo que habilita dos filtros en la vista
de búsqueda de albaranes: **Fulfillment: Pick** y **Fulfillment: Despacho**.

## Configuración

1. Ve a **Inventario → Configuración → Tipos de operación**
2. Abre el tipo de operación que haga de **Pick** y pon **"Rol en fulfillment" = Fulfillment: Pick (PFUL)**
3. Abre el tipo de operación que haga de **Despacho** y pon **"Rol en fulfillment" = Fulfillment: Despacho (DFUL)**
4. En el tipo de **Despacho**, activa el flag **"No consolidar destinos"**
5. Guarda los cambios

> El flag "No consolidar destinos" también puede activarse en el tipo de **Pick** — el módulo lo detecta desde cualquiera de los dos lados.

### Migración desde 18.0.1.0.0

No hay que configurar nada a mano al actualizar. El módulo asigna `ful_role` automáticamente a los
tipos de operación cuyo nombre contenga `Resurtido a Ful: Pick` o `Resurtido a Ful: Despacho`,
replicando el emparejamiento de la versión anterior:

- **Instalación nueva:** vía `post_init_hook`.
- **Actualización de una base existente:** vía `migrations/18.0.1.1.0/post-seed_ful_roles.py`.

Solo se tocan los tipos que **no** tengan rol asignado, así que una configuración hecha a mano nunca
se sobrescribe. Si algún tipo quedara sin marcar (porque fue renombrado antes de actualizar), basta
con asignarle el rol desde el formulario.

## Uso

### Flujo básico

1. Crea un PFUL (tipo de operación con `ful_role = pick`)
2. Captura el **Documento origen** con el número de cita del marketplace
3. Opcionalmente, define **"Ubicación del marketplace"**
4. Valida el PFUL
5. El módulo crea automáticamente un DFUL con:
   - El mismo **documento origen** (número de cita) del PFUL
   - La ubicación de marketplace del PFUL como ubicación de destino
   - Un DFUL por cadena de PFUL

### Pickeo en varias rondas

El picker no tiene que surtir el PFUL completo de una sola vez:

1. El PFUL se crea por la cantidad total (p. ej. 100 pz) y se asigna a un operador
2. El operador surte una parte (p. ej. 20 pz) y **valida el PFUL generando backorder**
3. Odoo crea el backorder con las 80 pz restantes, y el módulo crea el **DFUL** con las 20 surtidas
4. En la siguiente ronda el operador surte otras 20 pz y valida el backorder
5. Esas 20 pz **se agregan al mismo DFUL** — no se crea uno nuevo
6. Se repite hasta agotar la cantidad

El DFUL acumula las piezas de todas las rondas conservando una sola cita. Ver
[Un DFUL por cadena de PFUL](#4-un-dful-por-cadena-de-pful-pickeo-en-varias-rondas) para el detalle.

> ⚠️ Si el DFUL se valida antes de que termine el pickeo, las rondas siguientes ya no pueden
> agregarse a él y se abre un segundo despacho, con aviso en el chatter.

### Sin marketplace definido

Si el PFUL no tiene definida una ubicación de marketplace:
- El DFUL se crea con la ubicación de destino configurada en la ruta
- Esa ubicación se propaga al PFUL como `marketplace_location`

## Tests

```
odoo -c odoo.conf -d <BD> -u wb_tech_fulfillment_process \
     --workers=0 --stop-after-init --test-enable --test-tags=wb_ful
```

26 tests que montan el flujo real —tipos con `ful_role`, regla push, validaciones parciales con
confirmación de backorder— en lugar de simular la cadena a mano. Cubren:

| Clase | Qué asegura |
|---|---|
| `TestFulfillmentRole` | El rol sale del campo y no del nombre; la siembra no pisa configuración manual |
| `TestFulfillmentConsolidacion` | 2 y 3 rondas en un solo DFUL; raíz de la cadena; DFUL impreso; DFUL cerrado; cadenas sin parentesco separadas |
| `TestFulfillmentPropagacion` | La cita no se contamina; origen limpio aun sin cita; marketplace en moves **y líneas**; retorno a toda la cadena |
| `TestFulfillmentDominio` | El dominio ampliado sigue siendo válido con `stock_picking_batch` encima, y queda intacto sin el flag |
| `TestFulfillmentOperador` | Se propaga al backorder, se sincroniza la cadena abierta, y el histórico no se reescribe |
| `TestFulfillmentFechaProgramada` | El DFUL hereda la fecha del Pick, no se mueve en 3 rondas, respeta el ajuste manual, y los albaranes ajenos mantienen el cálculo del core |
| `TestFulfillmentLote` | Cada parcial estrena lote con el operador correcto; el despacho no recibe lote; sin rol no se crea nada |

Los tipos de operación de prueba se llaman deliberadamente *"TEST ... Nombre Arbitrario"*: si la
lógica volviera a depender del nombre, la suite se cae.

## Dependencias

- `stock` — Módulo base de inventario
- `wmds` — Módulo interno de Wonderbrands Tech (logs, y el campo `picking_type_id_name`)

## Technical Reference

### Modelos

| Clase | Modelo | Descripción |
|---|---|---|
| `FulfillmentPicking` | `stock.picking` | Agrega `marketplace_location` y el related `picking_type_ful_role` |
| `StockPickingType` | `stock.picking.type` | Agrega `ful_role` y el flag `no_merge_destination` |
| `FulfillmentStockMove` | `stock.move` | Lógica de separación 1:1 y propagación de marketplace y documento origen |

### Métodos sobrescritos

- **`stock.move._key_assign_picking()`** — Agrupa por la **raíz de la cadena de backorders**, no por el albarán origen concreto
- **`stock.move._search_picking_for_assignation_domain()`** — Relaja las condiciones `printed` y `location_dest_id` para que el DFUL de la cadena siga siendo visible
- **`stock.move._search_picking_for_assignation()`** — Recorre todos los candidatos (el core usa `limit=1`) y devuelve el que pertenece a la cadena
- **`stock.move._assign_picking_post_process()`** — Propaga `origin`, `scheduled_date` y `marketplace_location`, tanto al crear el DFUL como al consolidarle un backorder
- **`stock.picking._compute_scheduled_date()`** — Congela la fecha de los DFUL conservando el valor almacenado
- **`stock.picking._create_backorder()`** — Da a cada Pick parcial su propio traslado por lote
- **`stock.picking.write()`** — Replica el cambio de `operator` a la cadena abierta

### Auxiliares

| Método | Modelo | Qué hace |
|---|---|---|
| `_ful_backorder_root()` | `stock.picking` | Sube por `backorder_id` hasta el albarán original de la cadena |
| `_ful_backorder_family()` | `stock.picking` | La raíz más todos sus descendientes |
| `_ful_source_pickings()` | `stock.move` | Los PFUL que originan los movimientos (`ful_role == 'pick'`) |
| `_ful_origin_root_ids()` | `stock.move` | IDs de las raíces de origen; es la clave de agrupación |
| `_ful_candidate_dest_location_ids()` | `stock.move` | Destinos que identifican al DFUL: el de la ruta y el del marketplace |
| `_ful_closed_sibling_dispatches(origin)` | `stock.move` | DFUL ya cerrados de la misma cadena, por encadenamiento **y** por documento origen |
| `_ful_propagate_operator()` | `stock.picking` | Replica el operador a los eslabones **abiertos** de la cadena |
| `_ful_assign_own_batch()` | `stock.picking` | Crea un lote propio para cada Pick parcial |
| `_ful_sync_origin()` | `stock.move` | Deja la cita en el DFUL, corrigiendo al core |
| `_ful_sync_scheduled_date()` | `stock.move` | Hereda al DFUL la fecha programada del Pick raíz |
| `_ful_sync_marketplace()` | `stock.move` | Apunta DFUL, movimientos **y líneas** al marketplace |
| `_ful_warn_split_dispatch()` | `stock.move` | Avisa si la cita quedó en dos despachos |
| `seed_ful_roles(env)` | — | Asigna `ful_role` a los tipos que aún no lo tienen, desde `LEGACY_FUL_TYPE_NAMES`. Lo invocan el `post_init_hook` y el script de migración |

### Sobre `LEGACY_FUL_TYPE_NAMES`

Es la única referencia a los nombres `'Resurtido a Ful: ...'` que queda en el código, y **no se usa
en runtime**: existe solo como semilla de migración. La lógica del flujo depende exclusivamente de
`ful_role`.

## Versiones

| Versión | Cambios |
|---|---|
| 18.0.1.4.0 | El operador se comparte entre los Pick abiertos de una misma cadena; la fecha programada del Despacho se hereda del Pick raíz y queda congelada; cada Pick parcial estrena su propio traslado por lote. **Sin migración de datos**: no añade campos y no reescribe nada existente |
| 18.0.1.3.0 | Suite de 16 tests; coincidencia exacta de cadena al buscar el DFUL (antes un backorder podía caer en un despacho ajeno); búsqueda acotada por SQL en vez de recorrido en Python; `location_dest_id` se resincroniza aunque el core lo haya revertido al borrar `partner_id`; el documento origen queda limpio aun sin número de cita; el marketplace vuelve a toda la cadena; el aviso de cita repartida ya detecta DFUL **cancelados**; `marketplace_location` restringido a ubicaciones internas de la compañía; rol almacenado y filtrable |
| 18.0.1.2.0 | Los backorders de un mismo PFUL se consolidan en el DFUL original en lugar de abrir uno por ronda de pickeo; se corrige la contaminación del `origin` al consolidar; las `move_line_ids` también se reapuntan al marketplace; aviso cuando la cita queda repartida por tener el DFUL ya cerrado |
| 18.0.1.1.0 | El rol del tipo de operación se declara en el campo `ful_role` en vez de deducirse del nombre; propagación del `origin` (número de cita) del PFUL al DFUL; se elimina el campo duplicado `picking_type_id_name` (lo provee `wmds`) |
| 18.0.1.0.0 | Versión inicial |
