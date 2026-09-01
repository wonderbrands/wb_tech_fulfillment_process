# WB Tech Fulfillment Process

Módulo para Odoo 18 que gestiona la propagación de la ubicación de marketplace entre operaciones **PFUL** (Resurtido a Ful: Pick) y **DFUL** (Resurtido a Ful: Despacho) en el proceso de fulfillment.

## Funcionalidades

### 1. Propagación de `marketplace_location`

Cuando se valida un PFUL y Odoo crea automáticamente el DFUL:

- **PFUL → DFUL:** Si el PFUL tiene definida una **Ubicación del marketplace**, esta se propaga automáticamente como ubicación de destino (`location_dest_id`) del DFUL y de todos sus movimientos.
- **DFUL → PFUL:** Si el PFUL no tiene definida una ubicación de marketplace, se toma la ubicación de destino que trae el DFUL (desde la ruta/configuración) y se propaga al PFUL como `marketplace_location`.

### 2. Propagación del documento origen (número de cita)

El campo **Documento origen** (`origin`) del PFUL contiene el **número de cita** que asigna el
marketplace. Al generarse el DFUL, ese valor se copia al DFUL para que ambas operaciones queden
ligadas por el mismo identificador y la búsqueda funcione desde cualquiera de los dos lados.

- Sustituye el valor que Odoo asigna por defecto (el **nombre** del PFUL, p. ej. `WH/PFUL/00456`).
- Si un DFUL termina alimentado por varios PFUL (validación parcial / backorders, o con la
  consolidación activada), los números de cita se **acumulan separados por comas y sin duplicados**:
  `APPT-8891,APPT-8892`.
- La propagación ocurre también cuando se **agregan** movimientos a un DFUL ya existente, no solo
  al crearlo.

> ℹ️ Compartir el número de cita entre el PFUL y su DFUL es el objetivo del cambio: es lo que
> mantiene ligadas ambas operaciones. Como consecuencia, el número de cita ya no identifica a un
> solo albarán — cualquier consulta que espere un único registro debe filtrar además por tipo de
> operación. El consumidor externo actual ya contempla este caso.

### 3. Relación 1:1 entre PFUL y DFUL

Por defecto Odoo consolida múltiples PFUL en un solo DFUL. Este módulo evita esa consolidación, garantizando que **cada PFUL genere su propio DFUL**.

Esto se controla mediante el flag **"No consolidar destinos"** disponible en el formulario del tipo de operación.

La relación 1:1 se calcula contra el **PFUL raíz**, no contra el albarán concreto: si un PFUL se
surte en varias partes, sus backorders se agrupan en el **mismo DFUL** (ver siguiente sección).

### 4. Backorders del PFUL agrupados en un solo DFUL

Un PFUL puede surtirse en partes sin saturar la operación: cuando se valida parcialmente, Odoo crea
un backorder con el resto, y ese backorder alimenta el **mismo DFUL** que la primera validación en
lugar de abrir uno nuevo.

- El agrupamiento usa la **raíz de la cadena de backorders** (`backorder_id` recorrido hasta arriba),
  así que da igual en cuántas partes se surta el PFUL.
- El DFUL **crece después de creado**: al validar cada backorder se le suman las piezas y Odoo
  fusiona las líneas del mismo producto. Un DFUL abierto en pantalla cambiará de cantidades.
- Se reutiliza el DFUL **aunque su hoja ya se haya impreso**; en ese caso hay que **reimprimir**.
- Dos PFUL distintos que **no** estén encadenados por backorder siguen generando DFUL distintos,
  aunque compartan número de cita.

> ℹ️ Si el DFUL de esa cadena ya fue **validado o cancelado**, el backorder no puede agregarse a él.
> En ese caso **se crea un DFUL nuevo** — la mercancía nunca se queda detenida — y se deja aviso en
> el chatter del despacho y en `wmds.log` indicando que la cita quedó repartida en dos despachos.

### 5. Campo visible en PFUL

El campo **"Ubicación del marketplace"** se muestra en el formulario del PFUL, permitiendo al usuario definir manualmente la ubicación de destino que se propagará al DFUL.

## Configuración

1. Ve a **Inventario → Configuración → Tipos de operación**
2. Abre el tipo de operación **"Resurtido a Ful: Despacho"** (o el que uses como DFUL)
3. Activa el flag **"No consolidar destinos"** en la pestaña General
4. Guarda los cambios

> El flag también puede activarse en el tipo de operación **"Resurtido a Ful: Pick"** (PFUL) — el módulo lo detecta desde cualquiera de los dos lados.

## Uso

### Flujo básico

1. Crea un PFUL (Resurtido a Ful: Pick)
2. Opcionalmente, define **"Ubicación del marketplace"** en el PFUL
3. Valida el PFUL
4. El módulo crea automáticamente un DFUL (Resurtido a Ful: Despacho) con:
   - La ubicación de marketplace del PFUL como ubicación de destino
   - Relación 1:1 (un DFUL por cada PFUL)

### Sin marketplace definido

Si el PFUL no tiene definida una ubicación de marketplace:
- El DFUL se crea con la ubicación de destino configurada en la ruta
- Esa ubicación se propaga al PFUL como `marketplace_location`

## Dependencias

- `stock` — Módulo base de inventario
- `wmds` — Módulo interno de Wonderbrands Tech (logs)

## Technical Reference

### Modelos

| Clase | Modelo | Descripción |
|---|---|---|
| `FulfillmentPicking` | `stock.picking` | Agrega campo `marketplace_location` y `picking_type_id_name` |
| `StockPickingType` | `stock.picking.type` | Agrega flag `no_merge_destination` |
| `FulfillmentStockMove` | `stock.move` | Lógica de separación 1:1 y propagación de marketplace y origen |

### Métodos sobrescritos

- **`stock.move._key_assign_picking()`** — Incluye los IDs de los pickings origen en la clave de agrupamiento para evitar consolidación
- **`stock.move._search_picking_for_assignation()`** — Rechaza pickings existentes con orígenes diferentes cuando el flag `no_merge_destination` está activo
- **`stock.move._search_picking_for_assignation_domain()`** — Permite reutilizar un DFUL ya impreso (elimina la condición `printed = False` de Odoo) en este flujo
- **`stock.move._assign_picking_post_process()`** — Propaga `origin` y `marketplace_location` entre PFUL y DFUL después de asignar los movimientos, tanto si el DFUL se acaba de crear como si se le agregaron movimientos

### Auxiliares

- **`stock.move._ful_source_pickings()`** — Retorna los PFUL que originan los movimientos, vía `move_orig_ids.picking_id`
- **`stock.move._merge_ful_origin(current, new_values)`** — Une documentos origen separados por comas, sin duplicados y conservando los existentes
- **`stock.move._ful_origin_root_ids()`** — IDs de los PFUL raíz que originan los movimientos; es la clave de agrupamiento del DFUL
- **`stock.move._ful_closed_sibling_dispatches()`** — DFUL ya validados o cancelados generados por la misma cadena de PFUL
- **`stock.picking._ful_backorder_root()`** — Sube por `backorder_id` hasta el albarán original (con guarda contra ciclos)
- **`stock.picking._ful_backorder_family()`** — La cadena completa de backorders: la raíz y todos sus descendientes

Los nombres de los tipos de operación están centralizados en las constantes `FUL_PICK_TYPE` y
`FUL_DISPATCH_TYPE` de `models/fulfillment_picking.py`.

## Versiones

| Versión | Cambios |
|---|---|
| 18.0.1.2.0 | Los backorders de un PFUL se agrupan en el DFUL original (agrupamiento por raíz de backorder); se reutiliza el DFUL aunque esté impreso; si ese DFUL ya está cerrado se abre uno nuevo y se avisa |
| 18.0.1.1.0 | Propagación de `origin` (número de cita) del PFUL al DFUL; la propagación ahora también ocurre al agregar movimientos a un DFUL existente (antes solo al crearlo) |
| 18.0.1.0.0 | Versión inicial |
