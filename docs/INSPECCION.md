# Inspección inicial e inventario

La entrega recibida contenía archivos sueltos, no el repositorio completo. Se reconstruyó la jerarquía indicada por el README y se conservaron los módulos funcionales. No se inspeccionó ni integró `mainFrontend.py`, conforme a la decisión del proyecto.

| Componente | Ubicación original | Lenguaje | Función | Estado recibido | Comunicación y dependencias | Problemas detectados | Reutilización |
|---|---|---|---|---|---|---|---|
| Entrada de UI | `kiosk_ui/main.py` | Python | Composición de la demo | Funcional como simulación | CustomTkinter, MockKit | Solo conocía mocks | Sustituida por composición real/demo |
| Modelos | `core/models.py` | Python | Datos de flujo | Funcional | Dataclasses | Sin fase de identidad verificada | Conservado y ampliado |
| Puertos | `core/ports.py` | Python | Contratos de adaptadores | Provisional | Protocol | Sin cancelación backend | Conservado y completado |
| Controlador | `core/controller.py` | Python | Estado, hilos y cola | Funcional | `queue.Queue`, `threading` | Iba directo del rostro a boleta; no cancelaba sesión | Conservado y corregido |
| Mocks | `adapters/mock.py` | Python | Escenarios ficticios | Funcional | Sin red | Boleta con cargos no requeridos | Conservado; boleta ajustada |
| UI | `ui/app_window.py` | Python | Pantallas CustomTkinter | Funcional | Tkinter/CustomTkinter | No existía pantalla neutra de identidad | Conservada; pantalla añadida |
| Tema y fotos | `ui/theme.py`, `ui/photos.py` | Python | Estilo e imágenes | Funcional | Pillow | Sin fotos reales definidas | Conservados sin cambios funcionales |
| Pruebas UI/core | `tests/test_controller.py` | Python | Flujo y doble envío | Funcional | unittest | Contrato actualizado por fase VERIFIED | Conservadas y ampliadas en la suite |
| Backend | `backend.py` | Python | FastAPI, SQLModel, votos | Parcialmente integrado | HTTP, PostgreSQL/SQLite | Clave por defecto; orden incorrecto; rostro booleano; devolvía todos los embeddings; huella sin HMAC | Conservado; seguridad y orden corregidos |
| Modelos DB | `backend.py` | Python/SQLModel | Votantes, candidatos, sesiones y votos | Funcional para una elección implícita | Neon/PostgreSQL o SQLite | No hay entidad Election ni varias elecciones por votante | Conservado; añadidos nonce/secuencia |
| NFC | `lectorNFC.ino` | C++ Arduino | Lee UID PN532 | Incompleto para el sistema | SPI al PN532; salida Serial | Sin WiFi, órdenes ni autenticación; lectura autónoma | Lógica PN532 reutilizada en firmware nuevo |
| Huella | `esp32_huella_test_3.ino` | C++ Arduino | Enrola, busca y reporta slot | Funcional según el código; no probado físicamente | UART local al sensor; WiFi/HTTP a API | Clave compartida, sin firma ni respuesta auténtica | Máquina de estados y enrolamiento conservados |
| Cifrado facial | `face_crypto.py` | Python | AES-256-GCM y key ring | Funcional | cryptography | Ninguno crítico | Conservado |
| Rostro local | `face_local.py` | Python | Cámara, un rostro, distancia y ambigüedad | Funcional según código | OpenCV, dlib/face_recognition | Import pesado impedía pruebas aisladas | Conservado; imports perezosos |
| Enrolamiento | `enroll_face.py` | Python | Enrolamiento administrativo | Funcional según código | API admin, cámara | Requiere operador y cámara | Conservado |
| Generación de clave | `generate_face_key.py` | Python | Genera 32 bytes base64 | Funcional | secrets | No persiste clave | Conservado |
| Frontend consola | `mainFrontend.py` | Python | Cliente de consola | Descartado por requisito | requests | Contratos antiguos y muestra datos | Excluido deliberadamente |

## Variables de entorno identificadas

`DATABASE_URL`, `DB_SSLMODE`, `DEVICE_KEY`, `ADMIN_KEY`, `REQUIRE_FACE`, `MAX_FACE_ATTEMPTS`, `SESSION_TIMEOUT_SECONDS`, `FINGERPRINT_COMMAND_TIMEOUT_SECONDS`, `API_BASE_URL`, `FACE_ENCRYPTION_KEYS`, `FACE_ACTIVE_KEY_ID`, `CAMERA_INDEX`, `FACE_CAPTURE_SCALE`, `FACE_DISTANCE_THRESHOLD` y `FACE_AMBIGUITY_MARGIN`.

La integración añade claves y parámetros independientes para NFC, huella y atestación facial. Todos están descritos en `.env.example`.

## Decisiones y límites del contrato existente

- El esquema recibido representa **una elección implícita**: `Voter.hasVoted` impide un segundo voto y no existe una entidad de elecciones. No se inventaron elecciones ni estados de habilitación. Soportar varias elecciones exige una migración aditiva y reglas funcionales nuevas.
- Los tres cargos existentes son obligatorios y se devuelven en el orden **MAYOR → GOVERNOR → PRESIDENT**.
- El voto anónimo conserva filas `Ballot(candidateId)` sin `voterId` ni `sessionId`; la barrera de duplicado es una actualización atómica sobre `Voter.hasVoted`.
- La verificación facial en ejecución es dirigida al votante de la sesión, por lo que solo viaja su envelope cifrado. La función de comparación conserva el margen de ambigüedad para pruebas o usos con múltiples registros.
- PN532 con `MIFARE_ISO14443A` lee UID; no autentica criptográficamente la tarjeta. Un UID puede ser clonable. Los tres factores y la habilitación backend siguen siendo necesarios.
