# Bitácora de integración por etapas

## Etapa 1 — Inspección

- Se reconstruyó la estructura `kiosk_ui` y se inventariaron backend, biometría y firmware.
- Se excluyó `mainFrontend.py` por decisión del proyecto.
- Hallazgos: NFC solo por serie, huella sin HMAC, clave insegura por defecto, orden de cargos inverso, rostro basado en booleano y entrega de todos los embeddings.
- Resultado: `docs/INSPECCION.md` y `docs/ARQUITECTURA.md`.

## Etapa 2 — ESP32 NFC

- Se sustituyó la lectura autónoma por servidor HTTP que solo escanea tras una orden válida.
- Se añadieron HMAC-SHA256, dispositivo, sesión, acción, nonce, secuencia persistente y expiración NTP.
- Se añadió adaptador WiFi y simulador con el mismo contrato.
- Archivos: `firmware/nfc_esp32/`, `kiosk_ui/adapters/real/nfc.py`, `common/hmac_protocol.py`, `simulators/nfc_server.py`.
- Pruebas: firma válida, alteración, nonce, UID, timeout, desconexión y HTTP simulado. Sin prueba física ni compilación.

## Etapa 3 — ESP32 de huellas

- Se conservaron enrolamiento, búsqueda local, máquina de estados, entrega y menú de diagnóstico.
- Se firmaron las peticiones y respuestas, con clave independiente, nonce, secuencia persistente y NTP.
- Backend persiste controles anti-repetición y mantiene consumo atómico de comandos.
- Archivos: `firmware/fingerprint_esp32/`, `backend.py`, `kiosk_ui/adapters/real/biometrics.py`.
- Pruebas: coincidencia, rechazo, HMAC, repetición, intentos y estados. Sensor físico pendiente.

## Etapa 4 — Reconocimiento facial

- Se conservó AES-256-GCM con nonce de 12 bytes, tag, AAD, key ID y rotación.
- Se hicieron imports de cámara perezosos para permitir pruebas sin dlib/OpenCV cargado.
- Se limitó el desafío al registro cifrado del votante de sesión.
- Se añadió atestación HMAC vinculada a sesión, desafío, votante y decisión.
- Archivos: `face_crypto.py` (conservado), `face_local.py`, `backend.py`, adaptador facial y pruebas.
- Pruebas: cifrado, integridad, rotación, comparación, ambigüedad, cámara ausente, cero/varios rostros y atestación. Cámara física pendiente.

## Etapa 5 — Backend

- Se reutilizaron rutas y campos existentes; se eliminó el valor por defecto de `DEVICE_KEY`.
- Se corrigió el orden a alcalde, gobernador y presidente.
- Se conservaron validaciones de habilitación, residencia, región, elección implícita y voto anterior.
- Se añadieron tablas no destructivas para nonce/secuencia.
- Pruebas: integración completa con SQLite temporal, duplicados, residencia y expiración. Neon pendiente.

## Etapa 6 — Interfaz gráfica

- Se añadió la fase VERIFIED y la pantalla «Identidad verificada correctamente», sin datos personales.
- Se mantuvieron hilos, cola, actualizaciones Tk en hilo principal, cancelación, inactividad y bloqueo de doble envío.
- `main.py` ahora compone servicios reales por defecto y `--demo` explícito.
- Prueba gráfica virtual completa superada. Pantalla táctil pendiente.

## Etapa 7 — Registro de votos

- Se conectó el contrato real `presidentId/governorId/mayorId` mediante el adaptador.
- Se conservaron revisión, envío explícito, transacción, claim atómico y voto anónimo.
- Red/5xx/respuesta inválida producen incertidumbre sin reintento; 4xx definitivo produce rechazo.
- Pruebas de envío único, éxito confirmado, rechazo e incertidumbre superadas.

## Etapa 8 — Pruebas integrales

- 31 pruebas automáticas superadas y smoke test gráfico superado.
- Integración NFC sobre HTTP local simulado y flujo backend completo con datos sintéticos.
- No se afirma integración física ni funcionamiento con Neon.

## Etapa 9 — Documentación

- Se añadieron instalación, configuración, protocolos, diagramas, `.env.example`, ejemplos de `secrets.h`, pruebas y límites.
- Pendiente antes de operación oficial: matriz física de `docs/PRUEBAS.md`, estrategia multi-elección si se requiere, endurecimiento de kiosco y evaluación independiente de seguridad/liveness.
