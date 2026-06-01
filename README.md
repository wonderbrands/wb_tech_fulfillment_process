# WB Tech Fulfillment Process (Odoo 18)

Este módulo especializado para Odoo 18 Enterprise gestiona la integridad de los flujos de resurtido a Marketplaces (Fulfillment), garantizando una trazabilidad 1:1 entre las etapas de recolección (Pick) y despacho (Dispatch).

## 1. Funcionalidades Principales

### A. Control de Consolidación 1:1
Por defecto, Odoo intenta optimizar el inventario agrupando múltiples movimientos en un solo albarán (Picking) o fusionando líneas del mismo producto. Este módulo permite anular ese comportamiento para operaciones críticas donde cada paquete o envío debe ser tratado de forma individual e independiente.

*   **Evita la fusión de líneas:** Si envías 10 unidades del Producto A en dos momentos distintos, se mantendrán como dos líneas separadas.
*   **Forza Albaranes Individuales:** Cada movimiento de stock generará su propio documento de transferencia (DFUL), evitando que se mezclen pedidos de diferentes orígenes.

### B. Propagación de Ubicación de Marketplace
Automatiza la sincronización de la ubicación de destino final entre los pasos de la ruta de fulfillment:
*   Si el despacho (DFUL) tiene definida una ubicación (ej: MLSR/Existencias), esta se propaga al registro de recolección (PFUL) original.
*   Asegura que todos los movimientos de stock internos apunten al marketplace correcto de forma automática.

## 2. Configuración para el Usuario

Para activar estas funciones, siga estos pasos:

1.  Vaya a **Inventario > Configuración > Tipos de Operación**.
2.  Busque y seleccione el tipo de operación donde desea evitar la agrupación (ejemplo: **Resurtido a Ful: Despacho** o **DFUL**).
3.  En la pestaña de **Configuración**, localice el campo **"Prevenir Consolidación de Transferencias"**.
4.  Active el check (True).
5.  Guarde los cambios.

*Nota: Todas las operaciones que tengan este check desactivado seguirán funcionando con la lógica estándar de Odoo.*

## 3. Flujo de Trabajo (Operación)

1.  Al validar un **PFUL (Pick)**, Odoo genera automáticamente el **DFUL (Dispatch)** vinculado.
2.  Gracias a este módulo, el DFUL se creará como un documento único, incluso si hay otros despachos pendientes hacia el mismo destino.
3.  La ubicación del Marketplace se mostrará en el formulario del albarán para una validación rápida.
4.  Cualquier cambio en la ubicación de destino del despacho actualizará automáticamente los registros vinculados y quedará registrado en el log del sistema (**WMDS Log**).

## 4. Requisitos Técnicos

*   **Odoo Version:** 18.0 Enterprise / Community.
*   **Dependencias:** 
    *   `stock`: Módulo base de inventario.
    *   `wmds`: Sistema de logs y trazabilidad de Wonderbrands.

## 5. Seguridad y Aislamiento

Este desarrollo ha sido diseñado bajo el principio de **"No Interferencia"**. El código solo se ejecuta si detecta que el Tipo de Operación tiene activado el flag de prevención. No afecta procesos de Ventas, Compras o Manufactura estándar a menos que se configure explícitamente para ello.
