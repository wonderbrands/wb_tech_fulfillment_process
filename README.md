# WB Tech Fulfillment Process

Módulo para Odoo 18 que gestiona la propagación de la ubicación de marketplace entre operaciones **PFUL** (Resurtido a Ful: Pick) y **DFUL** (Resurtido a Ful: Despacho) en el proceso de fulfillment.

## Funcionalidades

### 1. Propagación de `marketplace_location`

Cuando se valida un PFUL y Odoo crea automáticamente el DFUL:

- **PFUL → DFUL:** Si el PFUL tiene definida una **Ubicación del marketplace**, esta se propaga automáticamente como ubicación de destino (`location_dest_id`) del DFUL y de todos sus movimientos.
- **DFUL → PFUL:** Si el PFUL no tiene definida una ubicación de marketplace, se toma la ubicación de destino que trae el DFUL (desde la ruta/configuración) y se propaga al PFUL como `marketplace_location`.

### 2. Relación 1:1 entre PFUL y DFUL

Por defecto Odoo consolida múltiples PFUL en un solo DFUL. Este módulo evita esa consolidación, garantizando que **cada PFUL genere su propio DFUL**.

Esto se controla mediante el flag **"No consolidar destinos"** disponible en el formulario del tipo de operación.

### 3. Campo visible en PFUL

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
| `FulfillmentStockMove` | `stock.move` | Lógica de separación 1:1 y propagación de marketplace |

### Métodos sobrescritos

- **`stock.move._key_assign_picking()`** — Incluye los IDs de los pickings origen en la clave de agrupamiento para evitar consolidación
- **`stock.move._search_picking_for_assignation()`** — Rechaza pickings existentes con orígenes diferentes cuando el flag `no_merge_destination` está activo
- **`stock.move._assign_picking_post_process()`** — Propaga `marketplace_location` entre PFUL y DFUL después de asignar los movimientos al nuevo picking

## Versiones

| Versión | Cambios |
|---|---|
| 18.0.1.0.0 | Versión inicial |
