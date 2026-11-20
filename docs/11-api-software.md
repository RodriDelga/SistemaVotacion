# 11 · Arquitectura de software y API

La interfaz de la urna muestra el estado del controlador. El controlador delega lecturas y solicitudes a adaptadores, de modo que la demo y la urna real comparten la navegación. FastAPI concentra las reglas de la votación y el panel consulta un módulo de la misma aplicación.

| Módulo | Responsabilidad y dependencias |
| --- | --- |
| [Entrada de urna](../kiosk_ui/main.py) · [Pantallas](../kiosk_ui/ui/app_window.py) | CustomTkinter y Pillow. Selecciona servicios reales o simulados, inicia el controlador y actualiza la interfaz desde el hilo gráfico. |
| [Controlador](../kiosk_ui/core/controller.py) · [Modelos](../kiosk_ui/core/models.py) · [Puertos](../kiosk_ui/core/ports.py) | Estados, selección y cancelación. Ejecuta trabajos en hilos y recibe sus resultados en una cola. Descarta resultados de generaciones de sesión anteriores. |
| [Adaptadores reales](../kiosk_ui/adapters/real) · [Mocks](../kiosk_ui/adapters/mock.py) | Los primeros usan `requests`, lectores, API, GPIO y cámara. Los mocks suministran casos ficticios con las mismas interfaces de servicios. |
| [Backend](../backend.py) | FastAPI y Pydantic para HTTP y validación. SQLModel/SQLAlchemy y psycopg o SQLite para persistencia. Define modelos, reglas de sesión, bloqueo y voto. |
| [Módulo web](../dashboard_api.py) · [Modelo de pronóstico](../forecast.py) | Instala rutas y middleware, usa los modelos del backend por inyección y agrega eventos/latidos. NumPy calcula el pronóstico. |
| [Panel React](../dashboard/src/App.tsx) · [Cliente web](../dashboard/src/api.ts) · [Vite](../dashboard/vite.config.ts) | TypeScript y React. Navegación por hash y consultas de mismo origen. FastAPI sirve la compilación en `/dashboard/` si existe el directorio. |
| [Firma común](../common/hmac_protocol.py) · [Cifrado facial](../face_crypto.py) · [Captura](../face_local.py) · [Enrolamiento](../enroll_face.py) | Canonicalización HMAC, cifrado autenticado del vector y operación local de cámara. |
| [Firmware](../firmware) · [Simulador NFC](../simulators/nfc_server.py) | Sketches de los ESP32 y servidor HTTP de pruebas para el contrato NFC. |

## Cómo leer los contratos

Las rutas de las dos primeras tablas son relativas a `/api/v1`. Use `/docs` y `/openapi.json` del FastAPI local para ver esquemas Pydantic y parámetros completos. Aquí se resumen los contratos y resultados operativos. Las respuestas de éxito de estas rutas usan 200. Los errores suelen incluir `detail`. Una entrada que no cumple el esquema produce 422.

| Credencial | Uso |
| --- | --- |
| Dispositivo | `X-Device-Key` para operaciones de urna, resultados de dispositivo y latido. |
| Administración por clave | `X-Admin-Key` para padrón, tarjetas administrativas, consulta de incidentes y purga. |
| Huella | Cabeceras HMAC, timestamp, nonce y secuencia. Usa su propia clave. |
| Navegador | Cookie firmada `dashboard_session` para las consultas protegidas del panel. |

FastAPI rechaza claves incorrectas o ausentes con 401. Las mutaciones de votación y varias lecturas de sesión devuelven 423 si la urna está bloqueada. La consulta de órdenes de huella devuelve `active:false` cuando hay bloqueo. [Autenticación y reglas](../backend.py) · [Contratos físicos y firmas](08-comunicacion-protocolos.md)

## Padrón, sesión y resultados

| Método y ruta | Entrada | Respuesta o errores de dominio | Acceso |
| --- | --- | --- | --- |
| GET `/voters` | — | Lista de ID, nombre, existencia de rostro y participación. | Administración por clave |
| POST `/voters` | `fullName, cardUid, fingerprintSlot, stateName, municipalityName`, y `faceEmbedding` opcional. | ID y región. 409 por UID/slot duplicado, 422 por región vacía o plantilla malformada. | Administración por clave |
| PUT `/voters/{voterId}/face` | ID entero en ruta, `faceEmbedding` y `confirmReplacement` opcional. | `faceEnrolled`. 404 si el votante no existe, 409 si falta confirmar un reemplazo, 422 por formato. | Administración por clave |
| GET `/candidates` | `office` opcional. | Candidaturas del catálogo, con cargo, región y partido. | Dispositivo |
| POST `/candidates` | `name, office`, con `party, stateName, municipalityName` opcionales según cargo. | Candidato creado. 422 por cargo o región incompatibles. | Dispositivo |
| POST `/session/start` | `cardUid`. | ID de sesión y nombre. 404 si no existe el UID, 403 si no puede votar. | Dispositivo |
| GET `/session/active` | — | Sesión abierta reciente válida, o `active:false`. Puede incluir nombre. | Dispositivo |
| GET `/session/{sessionId}` | ID de sesión. | Estado, intentos, orden pendiente y disponibilidad para votar. 404 o 410 si no está activa. | Dispositivo |
| POST `/session/{sessionId}/cancel` | ID de sesión. | `cancelled` o `alreadyClosed`. 404 si falta la sesión. | Dispositivo |
| POST `/session/{sessionId}/fingerprint-command` | ID de sesión. | Orden, vigencia e intentos. 409 si ya se verificó o se agotaron intentos. 404/410 según sesión. | Dispositivo |
| GET `/device/fingerprint-command/pending` | Cabeceras firmadas. | Disponibilidad y IDs de la orden y sesión si procede. 401 de autenticación o 409 de repetición. | Huella |
| POST `/session/{sessionId}/fingerprint` | `commandId, fingerprintSlot`. | Estado de sesión tras coincidencia. 401 por intento fallido o firma inválida, 404 si falta orden, 409 por repetición o entrega ya procesada, 410 por orden o sesión vencida/cerrada y 422 por slot negativo. | Huella |
| GET `/session/{sessionId}/face-challenge` | ID de sesión. | Desafío y un registro facial cifrado. 403 si falta huella, 404/410 por sesión y 409 por verificación ya hecha, deshabilitada o sin registro válido. | Dispositivo |
| POST `/session/{sessionId}/face` | `challenge, matched, attestation`, con `voterId` opcional. | Estado de sesión. 401 por rechazo o atestación inválida, 403 sin huella, 404/410 por sesión, 409 por desafío inválido o exigencia facial desactivada. | Dispositivo |
| GET `/session/{sessionId}/ballot` | ID de sesión. | Nombre y región más candidaturas elegibles por cargo. 403 si faltan factores y 404/410 por sesión. | Dispositivo |
| POST `/session/{sessionId}/vote` | `presidentId, governorId, mayorId`. | `voteRecorded`. 403 por verificaciones o habilitación, 404 por sesión/candidato ausente, 409 por voto previo durante registro, 410 por sesión cerrada/vencida y 422 por cargo/región. | Dispositivo |
| GET `/results` | `office` opcional. | Conteo por candidatura con región y partido. | Dispositivo |
| GET `/dashboard/summary` | — | Padrón, total de participantes, porcentaje y pendientes. | Dispositivo |
| GET `/dashboard/timeline` | — | Serie por hora basada en creación de sesiones cerradas. Incluye cierres distintos del voto. | Dispositivo |
| GET `/analytics/anomalies` | — | Tasa histórica de fallos de órdenes completadas de huella y banderas. | Dispositivo |

La serie de sesiones de `/dashboard/timeline` usa una fuente distinta de `/admin/timeline`. El panel React utiliza la segunda y esta se basa en eventos `vote/ok`. [Backend](../backend.py) · [Serie web](../dashboard_api.py)

## Bloqueo, incidentes y telemetría

| Método y ruta | Entrada | Respuesta o errores de dominio | Acceso |
| --- | --- | --- | --- |
| GET `/kiosk/lock` | — | Estado, motivo, fecha, incidente y estado de evidencia. | Dispositivo |
| POST `/kiosk/lock` | `reason` opcional en el cuerpo. | Bloqueo e identificador de incidente. | Dispositivo |
| POST `/kiosk/unlock` | `scan` con `deviceId, sessionId, nonce, sequence, expiresAt, status, uid, hmac`. | Desbloqueo y nombre administrativo. 403 por evidencia o tarjeta inválida/deshabilitada, 409 por uso anterior incompatible o urna ya desbloqueada. | Dispositivo y lectura NFC firmada |
| POST `/security/incidents` | `id` UUID y `photoBase64` JPEG o `captureFailed:true`. | Estado de incidente y evidencia. 404/409/410 según incidente y vigencia, 422 por JPEG o combinación inválidos. | Dispositivo |
| GET `/security/incidents` | — | Incidentes y metadatos, con información de desbloqueo. | Administración por clave |
| GET `/security/incidents/{incidentId}/photo` | ID de incidente. | JPEG sin caché. 404 si falta o venció. | Administración por clave |
| DELETE `/security/incidents/expired-photos` | — | Cantidad eliminada. | Administración por clave |
| GET `/admin/cards` | — | Tarjetas enroladas y estado de habilitación. | Administración por clave |
| POST `/admin/cards` | `cardUid`, `adminName` e `isEnabled` opcionales. | Alta o actualización por UID. 422 por UID inválido. | Administración por clave |
| POST `/device/heartbeat` | `components` opcional con `nfc` y `camera`, valores `online/offline`. | `status:ok` y hora del servidor. La urna se marca `online`. | Dispositivo |

## API del panel

Las rutas de esta tabla son relativas a `/api/v1/admin`. Login y logout exigen `X-Requested-With: dashboard` y devuelven 403 si falta. La cookie tiene `HttpOnly`, `SameSite=Strict`, alcance `/api/v1/admin` y duración configurable de ocho horas por defecto. `Secure` depende del entorno. Las rutas de lectura protegidas devuelven 401 con cookie ausente, inválida, revocada o expirada. El límite de intentos de login y la revocación se mantienen en memoria por proceso. [Implementación del panel](../dashboard_api.py)

| Método y ruta | Entrada | Resultado |
| --- | --- | --- |
| POST `/login` | `password`, cabecera de panel. | Cookie, rol y vencimiento. 401 si la contraseña es incorrecta, 429 por límite con `Retry-After` y 503 si falta configuración administrativa. |
| POST `/logout` | Cabecera de panel y cookie si existe. | Revoca la sesión válida de este proceso, borra la cookie y devuelve `authenticated:false`. |
| GET `/me` | Cookie si existe. | Estado de autenticación y rol. |
| GET `/meta` | Cookie. | Título, zona horaria, cargos, estados, hora del servidor y cadencia de consulta. |
| GET `/results` | `office, state` opcionales. | Votos y porcentajes por grupo regional. 422 por cargo desconocido. |
| GET `/participation` | — | Participación del padrón total y por estado. |
| GET `/timeline` | `from, to, bucket` opcionales. | Puntos horarios o diarios. `bucket` acepta `auto/hour/day`. 422 por fecha o rango inválidos cuando se valida el rango. |
| GET `/forecast` | Ventana configurada en servidor. | Estado, motivo, datos observados y, cuando corresponde, proyección e intervalo. |
| GET `/system` | — | Estado general y componentes, última observación y vigencia de latido. |
| GET `/events` | `limit` de 1 a 200, `from, to, kind` opcionales. | Eventos técnicos. 422 por filtros inválidos. |
| GET `/analytics` | `from, to` opcionales. | Conteos agrupados, tasas y banderas operativas. 422 por fecha inválida. |
| GET `/export/{dataset}.csv` | `dataset` en `results/participation/events`. `from, to` aplican a eventos. | CSV UTF-8 con descarga. Neutraliza prefijos interpretables como fórmulas. 422 por dataset inválido o fecha inválida en eventos. |

Los filtros temporales admiten día local `YYYY-MM-DD` y fecha ISO 8601. Un día final se traduce al inicio del día siguiente para incluir toda esa jornada en los filtros de borde exclusivo. En modo real, el acceso por tarjeta inicial usa una credencial compartida de la urna y el desbloqueo suma una prueba de lectura vinculada al incidente. [Fechas y sesión web](../dashboard_api.py) · [Modelo de seguridad](04-base-de-datos.md)
