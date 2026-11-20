# 14 · Cobertura de la rúbrica TC1004B

La matriz vincula los requisitos a artefactos verificables del proyecto. El estado se refiere a la evidencia disponible para cada fila y no asigna calificaciones.

| Criterio | Requisito | Evidencia encontrada | Archivo de documentación | Estado |
| --- | --- | --- | --- | --- |
| Sistemas Digitales · 40 | Coordinar factores, boleta y emisión del voto. | Flujo con SQLite y servicios simulados, verificaciones regionales y control de estado en [pruebas del backend](../tests/test_backend.py) y [del controlador](../kiosk_ui/tests/test_controller.py). | [Arquitectura](02-arquitectura-general.md) · [Sistemas digitales](03-sistemas-digitales.md) | Verificado mediante código y pruebas. |
| Sistemas Digitales · 40 | Comunicar módulos y mantener disponibilidad con lector y cámara. | HMAC/HTTP comprobado con [adaptadores y simulador](../tests/test_real_adapters.py). SPI, UART y red empresarial están en los sketches. | [Comunicación](08-comunicacion-protocolos.md) | Implementado, pendiente de validación funcional. |
| Bases de Datos · 40 | Modelo, operaciones e integridad de voto. | 14 tablas inspeccionadas en SQLite y transacciones verificadas en [pruebas de backend](../tests/test_backend.py). | [Base de datos](04-base-de-datos.md) | Verificado mediante código y pruebas. |
| Bases de Datos · 40 | Operación contra la base remota de despliegue. | El [motor](../backend.py) configura PostgreSQL/TLS y la guía prevé Neon. Falta prueba remota. | [Instalación](09-guia-instalacion.md) | Implementado, pendiente de validación funcional. |
| Bases de Datos · 40 | Control de acceso a datos faciales e incidentes. | Cifrado y verificación por [test_face](../tests/test_face.py) y acceso/retención por [test_security_kiosk](../tests/test_security_kiosk.py). | [Base de datos](04-base-de-datos.md) · [API](11-api-software.md) | Verificado mediante código y pruebas. |
| Usabilidad · 20 | Recorrido, revisión, confirmación y errores. | Cinco capturas de la urna en ejecución, [controlador probado](../kiosk_ui/tests/test_controller.py) y pantallas de [CustomTkinter](../kiosk_ui/ui/app_window.py). | [Usabilidad](05-usabilidad.md) · [Guía de usuario](10-guia-usuario.md) | Verificado mediante código y pruebas. |
| Usabilidad · 20 | Consultar resultados, estado y reportes en el panel. | [Vistas React](../dashboard/src/pages), [API probada](../tests/test_dashboard.py) y captura del estado del sistema. Hay tres rutas laterales preparatorias. | [Usabilidad](05-usabilidad.md) | Parcialmente implementado. |
| Usabilidad · 20 | Uso táctil y evaluación de accesibilidad. | Controles por clic, estados con texto y atributos ARIA en el panel. Faltan pruebas con usuarios, pantalla y tecnologías de apoyo. | [Usabilidad](05-usabilidad.md) · [Pruebas](12-pruebas-evidencias.md) | No verificable con la evidencia disponible. |
| Inteligencia · 40 | Validar identidad y actuar ante intentos fallidos. | Comparación, conteo, bloqueo y recuperación verificados con [pruebas faciales](../tests/test_face.py) y [de seguridad](../tests/test_security_kiosk.py). | [Inteligencia](06-inteligencia.md) | Verificado mediante código y pruebas. |
| Inteligencia · 40 | Detectar cambios de rechazo y estimar participación. | Reglas de tasa y ráfaga, ajuste logístico y pruebas con datos sintéticos en [test_dashboard](../tests/test_dashboard.py) y [test_forecast](../tests/test_forecast.py). | [Inteligencia](06-inteligencia.md) | Verificado mediante código y pruebas. |
| Sensores y Actuadores · 40 | Al menos dos sensores integrados. | PN532, módulo de huella y cámara con código de integración. Evidencia lógica de [adaptadores](../tests/test_real_adapters.py) y [cámara simulada](../tests/test_face.py). | [Sensores y actuadores](07-sensores-actuadores.md) | Implementado, pendiente de validación funcional. |
| Sensores y Actuadores · 40 | Al menos dos actuadores integrados. | [LED](../kiosk_ui/led_control.py), [buzzer NFC](../firmware/nfc_esp32/nfc_esp32.ino) y [buzzer de huella](../firmware/fingerprint_esp32/fingerprint_esp32.ino) definidos en código. | [Sensores y actuadores](07-sensores-actuadores.md) | Implementado, pendiente de validación funcional. |
| Sensores y Actuadores · 40 | Demostración física de dos sensores y dos actuadores. | Las pruebas disponibles reproducen contratos y estados mediante simulación. Faltan observaciones del montaje completo. | [Pruebas físicas](12-pruebas-evidencias.md) | No verificable con la evidencia disponible. |

## Evidencia que completaría cada criterio

| Criterio | Trabajo de validación recomendado |
| --- | --- |
| Sistemas Digitales | Compilar ambos sketches y registrar un recorrido integrado en la Pi, incluyendo expiración o desconexión y recuperación. |
| Bases de Datos | Ejecutar el voto y una prueba concurrente de envío en PostgreSQL de staging, verificar TLS y registrar el esquema efectivo. |
| Usabilidad | Observar el recorrido en pantalla táctil real, medir legibilidad y probar teclado y lector de pantalla en las interfaces aplicables. |
| Inteligencia | Medir rechazos y alertas en casos controlados del montaje. Evaluar el pronóstico con varias series etiquetadas y conservar medidas de error. |
| Sensores y Actuadores | Grabar tarjeta, huella, un LED y un buzzer en funcionamiento. Adjuntar pinout del módulo, tensiones medidas y resultado esperado/observado. |
