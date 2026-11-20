# 01 · Introducción

Este proyecto es un prototipo de casilla de votación electrónica. La persona presenta una tarjeta registrada, coloca un dedo en el lector y mira a una cámara. La urna muestra las candidaturas de su región y permite revisar las selecciones antes del envío. El personal de operación puede consultar los resultados agregados y el estado de la casilla desde un navegador.

## Problema y objetivo

La casilla debe decidir si puede abrir la boleta, ofrecer las candidaturas correctas y evitar un segundo registro para la misma persona. También debe comunicar un fallo de identificación, una desconexión o un envío cuya confirmación se perdió. El diseño combina lecturas de dispositivos, reglas del padrón, un registro transaccional y dos interfaces con funciones distintas. [Controlador de la urna](../kiosk_ui/core/controller.py) · [Validaciones y registro del voto](../backend.py) · [Panel web](../dashboard/src/App.tsx)

| Pregunta | Cómo la resuelve el prototipo |
| --- | --- |
| ¿A quién corresponde esta tarjeta? | Busca el UID leído en el padrón y comprueba habilitación y voto previo. |
| ¿Coincide la identidad con el registro? | Compara el slot de huella y, por defecto, la representación facial del votante asociado a la sesión. |
| ¿Qué puede elegir esta persona? | Presenta presidencia municipal, gubernatura y presidencia según municipio, estado y ámbito nacional. |
| ¿Se registró el voto? | La API confirma el registro tras guardar tres filas de selección y marcar a la persona como participante en una transacción. |
| ¿Qué puede revisar el operador? | Resultados agrupados, participación, estado de los componentes, eventos técnicos, alertas de rechazo y un pronóstico condicionado a la disponibilidad de datos. |

## Alcance comprobable

El modelo corresponde a una elección implícita con tres cargos obligatorios, un identificador de urna configurado y una pareja de lectores. No hay una tabla de jornadas, boletas completas persistidas ni una API de administración electoral multijornada. Las filas de selección carecen de una clave hacia el votante o la sesión. El padrón conserva quién participó y las marcas técnicas conservan tiempos de eventos. [Modelos y rutas](../backend.py) · [Telemetría](../dashboard_api.py)

Hay dos formas de conocer la aplicación. El modo demo de la urna usa servicios simulados y datos ficticios. El modo real invoca FastAPI, los lectores y la cámara, con PostgreSQL como destino documentado y SQLite para pruebas locales. La validación del prototipo en un entorno aislado y su alcance físico se detallan por separado. [Instalación](09-guia-instalacion.md) · [Evidencias](12-pruebas-evidencias.md)
