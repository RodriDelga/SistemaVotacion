# Documentación técnica del sistema de votación electrónica

**TC1004B — Implementación de Internet de las Cosas · Tecnológico de Monterrey**

La urna comprueba la identidad con una tarjeta, una huella y, en la configuración predeterminada, el rostro. Después presenta una boleta de tres cargos. FastAPI registra los votos en la base y el panel web muestra resultados, participación y estado operativo.

| Documento | Contenido |
| --- | --- |
| [01 · Introducción](01-introduccion.md) | Problema, objetivo y alcance del prototipo |
| [02 · Arquitectura general](02-arquitectura-general.md) | Componentes y recorrido de los datos |
| [03 · Sistemas digitales](03-sistemas-digitales.md) | Estados, secuencia, decisiones y manejo de fallos |
| [04 · Base de datos](04-base-de-datos.md) | Modelo ER, diccionario, transacciones y privacidad |
| [05 · Usabilidad](05-usabilidad.md) | Pantallas, navegación y evaluación de las interfaces |
| [06 · Inteligencia](06-inteligencia.md) | Verificación, alertas biométricas y pronóstico |
| [07 · Sensores y actuadores](07-sensores-actuadores.md) | Inventario, cableado y evidencia física |
| [08 · Comunicación y protocolos](08-comunicacion-protocolos.md) | Interfaces, tiempos, autenticación y mensajes |
| [09 · Instalación](09-guia-instalacion.md) | Demo, panel local y despliegue de la urna |
| [10 · Guía de usuario](10-guia-usuario.md) | Votación, recuperación y recorrido del panel |
| [11 · API y arquitectura de software](11-api-software.md) | Módulos, rutas y contratos |
| [12 · Pruebas y evidencias](12-pruebas-evidencias.md) | Resultados, límites y procedimientos de validación |
| [13 · Glosario](13-glosario.md) | Términos empleados en la documentación |
| [14 · Cobertura de la rúbrica](14-cobertura-rubrica.md) | Trazabilidad de requisitos y estado de la evidencia |
| [Índice de diagramas](diagramas/README.md) | Ubicación de los diagramas Mermaid |

Para conocer el sistema, empiece por la introducción y la arquitectura. Para ejecutarlo, consulte la instalación y la guía de usuario. Para evaluarlo, use la matriz de la rúbrica junto con las pruebas y el inventario físico.

La revisión se basó en el árbol disponible de código y documentación. Las guías previas de [Raspberry Pi](RASPBERRY_PI.md), [cableado](CONEXIONES_HARDWARE.md), [protocolo](PROTOCOLO.md) y [seguridad](SEGURIDAD_KIOSK.md) conservan contexto operativo. La serie numerada incorpora el panel, las variantes `_Tec` y las verificaciones de esta entrega. Los archivos ZIP del directorio raíz se trataron como paquetes de distribución, con el código descomprimido de la copia activa como referencia.
