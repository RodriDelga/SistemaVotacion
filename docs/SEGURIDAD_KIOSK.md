# Seguridad del Kiosk

## Instalación y actualización

Instale `requirements.txt` en un entorno virtual. La configuración parte de `.env.example`. Cree `data/` si usa SQLite y restrinja el acceso a la base a la cuenta de servicio. Para PostgreSQL configure `DATABASE_URL` y los ajustes TLS de la instalación. Use valores aleatorios distintos para `DEVICE_KEY`, `ADMIN_KEY`, `NFC_HMAC_KEY`, `FINGERPRINT_HMAC_KEY` y `FACE_ATTESTATION_KEY`. Las claves HMAC son de 32 bytes en hexadecimal. Use `generate_face_key.py` para obtener la clave AES. Configure `FACE_ENCRYPTION_KEYS='{"operacion":"CLAVE_BASE64"}'` y `FACE_ACTIVE_KEY_ID=operacion`. El backend y el Kiosk deben disponer de la clave NFC configurada en el lector.

Use una instancia lógica de backend y una base de datos por Kiosk, con un `KIOSK_DEVICE_ID` estable. La ESP32 de huella está emparejada con esa instancia. Mantenga los relojes sincronizados para validar las firmas. El lector PN532 debe ejecutar uno de los sketches NFC incluidos. Configure el firmware a partir de su `secrets.h.example`.

Detenga los servicios y respalde la base antes de actualizar. Al importar `backend`, SQLModel crea las tablas que falten, incluidas `incidentphoto` y `kioskunlockaudit`. La cuenta que ejecuta esa actualización necesita permisos de creación. Se conservan las tablas y los datos previos. Un bloqueo previo de este Kiosk sigue activo. Si carece de un incidente asociado, la primera consulta autenticada crea una referencia para desbloquear. Compruebe el ID configurado antes de reanudar el servicio.

Las fotos del prototipo en `data/security_photos` pertenecen al almacenamiento anterior. Revise su acceso y su conservación por separado. La API actual sirve únicamente evidencia de la tabla nueva. Revise las tarjetas habilitadas existentes y desactive las de prueba o de procedencia desconocida antes de operar.

## Alta inicial de una tarjeta

Obtenga el UID hexadecimal con el lector de confianza durante el alta presencial y verifique a quién se asigna. Desde la administración local, use `POST /api/v1/admin/cards` con `X-Admin-Key` y un JSON como `{"cardUid":"04A1B2C3","adminName":"Supervisora de turno","isEnabled":true}`. Consulte el registro con `GET /api/v1/admin/cards`. Use el mismo UID con `isEnabled:false` para revocarlo. Mantenga la credencial administrativa fuera de la configuración de la UI y de los lectores. Use TLS o acceso local para la administración y el acceso a evidencia.

El PN532 con el firmware incluido firma su lectura NFC y el backend comprueba que corresponde al bloqueo vigente y que es reciente. El firmware lee el UID de la tarjeta. Una tarjeta con UID clonable conserva ese riesgo. La autenticación criptográfica de la tarjeta requiere confirmar el modelo de tarjeta y provisionar claves compatibles en el lector.

## API

| Método y ruta | Credencial | Uso |
| --- | --- | --- |
| `GET /api/v1/kiosk/lock` | `X-Device-Key` | Devuelve dispositivo, bloqueo, motivo, incidente y estado de evidencia. |
| `POST /api/v1/kiosk/lock` | `X-Device-Key` | Bloquea por intervención operativa. Recibe `reason`. Si ya está bloqueado, devuelve el incidente vigente. |
| `POST /api/v1/kiosk/unlock` | `X-Device-Key` y lectura NFC firmada | Recibe `{"scan":{...}}` con la respuesta del lector y el UUID del incidente como `sessionId`. La lectura debe estar vigente. |
| `POST /api/v1/security/incidents` | `X-Device-Key` | Adjunta evidencia al incidente biométrico activo. Recibe `id` y `photoBase64` con JPEG de hasta 2 MiB, o `captureFailed:true`. Conserva el primer resultado registrado. |
| `GET /api/v1/security/incidents` | `X-Admin-Key` | Lista metadatos y auditoría de desbloqueo. |
| `GET /api/v1/security/incidents/{id}/photo` | `X-Admin-Key` | Descarga el JPEG vigente con `Cache-Control: no-store`. |
| `DELETE /api/v1/security/incidents/expired-photos` | `X-Admin-Key` | Elimina imágenes vencidas. Conserva incidentes y auditoría. |
| `GET /api/v1/admin/cards` | `X-Admin-Key` | Lista tarjetas administrativas. |
| `POST /api/v1/admin/cards` | `X-Admin-Key` | Registra, actualiza o revoca una tarjeta por UID. |

La sesión expone `fingerprintAttemptsRemaining` y `faceAttemptsRemaining`. Los intentos se cuentan de forma independiente por sesión. Los rechazos faciales firmados y las órdenes dactilares completadas actualizan el contador correspondiente. Ante el límite, el backend cierra las sesiones, cancela las órdenes pendientes, registra el incidente y activa el bloqueo en la misma transacción. Las operaciones de votación posteriores reciben HTTP 423. El estado de la ESP32 deja de publicar órdenes pendientes. La UI consulta el bloqueo al arrancar.

## Evidencia y retención

La Raspberry Pi intenta capturar un JPEG dentro de los 30 segundos del evento para reducir el riesgo de fotografiar a otra persona tras un reinicio. Ante fallo de envío, reintenta con los mismos bytes en memoria. Un fallo de cámara queda registrado como `CAMERA_ERROR`. Si se autoriza un desbloqueo con evidencia todavía pendiente, queda registrado como `PHOTO_UNAVAILABLE`.

El JPEG se almacena en la base privada. `INCIDENT_PHOTO_RETENTION_DAYS` vale 30 por defecto. La API impide la descarga al vencer ese plazo. Programe una llamada administrativa diaria a la ruta de purga y aplique la política correspondiente a respaldos y exportaciones. Restrinja el acceso a la base y habilite cifrado de almacenamiento según el entorno.

## Verificación automatizada

Ejecute `python -m pytest -q tests kiosk_ui/tests`. Las pruebas usan SQLite temporal, datos sintéticos y un simulador NFC en loopback. Verifican el flujo de votación, los contadores, el bloqueo, la autorización y auditoría del desbloqueo, la retención de fotos y el comportamiento ante fallos de captura y comunicación.

## Validación física pendiente

Pruebe el PN532 con las tarjetas reales, el sensor de huellas, la cámara, GPIO y un reinicio físico de la Raspberry Pi. Compruebe el flujo con la base PostgreSQL de despliegue y los dos ESP32 conectados antes de operar.
