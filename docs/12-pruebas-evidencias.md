# 12 · Pruebas y evidencias

## Resultados observados el 20 de noviembre de 2026

Las pruebas utilizaron Python 3.12 y Node.js 22 en Windows. La suite de Python se ejecutó con el directorio local de dependencias y acceso a loopback para las pruebas de integración. La ruta de voto de prueba utilizó SQLite temporal y datos sintéticos.

| Verificación | Resultado esperado | Resultado observado |
| --- | --- | --- |
| `python -m pytest -q -o faulthandler_timeout=15 tests kiosk_ui/tests` | Terminar todas las pruebas del backend, controlador, seguridad, dashboard, pronóstico y adaptadores. | **88 pruebas y 10 subpruebas pasaron**. Una advertencia de obsolescencia por el uso de httpx en Starlette TestClient. |
| `npm test` en `dashboard/` | Pasar las pruebas de formato, mapa y pronóstico. | **8 pruebas pasaron** en dos archivos. |
| `npm run typecheck` y `npm run build` en `dashboard/` | Validar TypeScript y generar la versión estática. | Ambas terminaron con código 0. El build se escribió en un directorio temporal. |
| Inspección de SQLite en memoria y OpenAPI | Crear los modelos y enumerar los contratos. | **14 tablas, 5 claves foráneas declaradas y 42 operaciones HTTP** expuestas en el esquema. |
| Ejecución gráfica con servicios simulados | Avanzar por bienvenida, identidad, selección, revisión y resultado. El simulador debe registrar un solo envío. | Terminó el recorrido y se capturaron cinco pantallas de la ventana real. El conductor de la prueba llamó al controlador para avanzar y enviar. El diálogo de confirmación se verificó por lectura de su código. [Capturas](05-usabilidad.md) |
| Sembrador del panel | Preparar datos ficticios en un archivo SQLite nuevo. | Se crearon padrón, selecciones presidenciales, eventos y estados de prueba en un archivo temporal. |
| Verificación documental | Resolver enlaces locales, analizar sintaxis de Mermaid y cotejar el catálogo con el código. | Enlaces válidos en los 17 Markdown de la entrega, siete diagramas analizados con Mermaid 11.17.2, y coincidencia de las operaciones y tablas con OpenAPI y SQLite. |

El informe anterior conserva una ejecución con entorno gráfico virtual de Linux y resultados históricos. Las cifras de la tabla corresponden a esta revisión. [Registro anterior](PRUEBAS.md) · [Prueba gráfica del repositorio](../tests/ui_smoke.py)

## Ejecutar las pruebas

En la raíz, instale los requisitos de desarrollo en un entorno virtual y use una configuración local sin credenciales de despliegue. La suite completa crea SQLite temporal. `test_dashboard.py` usa `setdefault` para `DATABASE_URL` cuando se ejecuta por separado, así que quite cualquier conexión real del entorno antes de invocar una prueba individual. Las pruebas de adaptadores necesitan comunicación HTTP por loopback.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q -o faulthandler_timeout=15 tests kiosk_ui/tests
cd dashboard
npm ci
npm test
npm run typecheck
npm run build
```

Para ejecutar la prueba gráfica existente, use `python -m tests.ui_smoke` desde la raíz con una sesión gráfica. En Linux sin escritorio use `xvfb-run -a python -m tests.ui_smoke`. Si el recorrido termina, imprime `UI_SMOKE_OK`. La prueba acciona el controlador y abre la ventana con adaptadores simulados, por lo que no mide interacción táctil.

| Archivo | Qué verifica |
| --- | --- |
| [test_backend.py](../tests/test_backend.py) | Flujo completo, HMAC, vencimiento, rechazo regional, prevención de repetición y filas de voto sin vínculo directo al votante. |
| [test_face.py](../tests/test_face.py) | Roundtrip AES-GCM, manipulación de sobres, rotación, comparación y errores con dobles de cámara. |
| [test_real_adapters.py](../tests/test_real_adapters.py) | NFC firmado, validación de respuestas, HTTP contra su simulador, disponibilidad de periféricos, latidos y atestación/estado biométrico. |
| [test_security_kiosk.py](../tests/test_security_kiosk.py) | Bloqueo, 423, concurrencia de bloqueo, tarjeta administrativa, auditoría, formato y retención de foto y recuperación del controlador. |
| [test_dashboard.py](../tests/test_dashboard.py) | Cookie, cabeceras, login/logout, agregación, registros, ráfagas, latidos, exportación y API de pronóstico. |
| [test_forecast.py](../tests/test_forecast.py) | Hora y datos insuficientes, recuperación en datos sintéticos, incertidumbre, cierre, límites del padrón y línea base. |
| [test_controller.py](../kiosk_ui/tests/test_controller.py) | Selección obligatoria, revisión, cancelación, un solo envío, manejo de rechazos e incertidumbre. |
| [ForecastPanel.test.tsx](../dashboard/src/components/ForecastPanel.test.tsx) · [format.test.ts](../dashboard/src/lib/format.test.ts) | Presentación de la proyección e intervalo, baja confianza, formato local, mapa y leyenda. |

## Validación física pendiente

| Prueba | Procedimiento y resultado a registrar |
| --- | --- |
| Compilación y red | Anote placa, versión de core, librerías y variante compilada. Compruebe asociación, NTP y llegada a la API tras reiniciar ambos ESP32. |
| Tarjeta y buzzer NFC | En un padrón ficticio, acerque una tarjeta válida y otra no enrolada. Verifique detección por el PN532 y el efecto acústico de lectura, luego la decisión independiente del padrón. Registre una lectura con su indicador. |
| Huella y buzzer | Enrole una plantilla de prueba y compare una huella que coincida y otra distinta. Registre intento, validación y señal del buzzer. Compruebe que se procesa una sola vez la orden. |
| Cámara y LED | Use un participante autorizado de prueba. Compruebe que la cámara captura un único rostro y que cada LED corresponde al éxito de su factor. Valide también apagado al cancelar o terminar. |
| Flujo completo en la Pi | Recorrer todas las pantallas en el equipo táctil con la API y los periféricos instalados. Confirmar la transacción en una base de staging, la rotación de sesiones y el comportamiento ante desconexión. |
| PostgreSQL/Neon | Verifique conexión TLS, persistencia de las tres filas, concurrencia de envíos para un votante sintético y recuperación tras reiniciar el backend. |
| Bloqueo y evidencia | Ejecute intentos fallidos hasta el bloqueo, reinicie la interfaz, compruebe la persistencia y desbloquee con una tarjeta habilitada. Documente resultados sin publicar biometría ni credenciales. |
| Usabilidad y accesibilidad | Pruebe resolución, contraste, teclado, lector de pantalla y tareas representativas con usuarios nuevos. Anote punto de fallo y cambios sugeridos. |

La revisión actual carece de acceso a las placas, cámara física de la urna, Wi-Fi institucional y Neon de staging. Los resultados de software y las capturas de demo sustentan el comportamiento en el entorno aislado. [Matriz de la rúbrica](14-cobertura-rubrica.md)
