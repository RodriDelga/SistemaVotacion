# 08 · Comunicación y protocolos

Las interfaces de placa resuelven lecturas y señales a corta distancia. HTTP comunica procesos y dispositivos con mensajes estructurados. La autenticación distingue las solicitudes del kiosco, los lectores y el personal administrativo. [Firmas](../common/hmac_protocol.py) · [Adaptadores](../kiosk_ui/adapters/real) · [Referencia de protocolo](PROTOCOLO.md)

| Enlace y medio | Protocolo y datos | Frecuencia, fallos y protección |
| --- | --- | --- |
| Tarjeta → PN532, radio de proximidad | ISO 14443 A en la llamada `readPassiveTargetID`. El UID se convierte de 4–10 bytes a 8–20 caracteres hexadecimales. | Lecturas en ventanas de 150 ms durante el escaneo de hasta 20 s. Una longitud inválida produce `invalid_read`. El UID identifica una tarjeta en el padrón. |
| PN532 ↔ ESP32 NFC, cables | SPI, reloj, selección y transferencias mediante Adafruit PN532. | El firmware inicializa el módulo, consulta su versión y ejecuta `SAMConfig`. El escaneo se rechaza si el lector o el reloj no están listos. |
| Sensor ↔ ESP32 de huella, cables | UART2 57 600, 8N1, comandos de la biblioteca Adafruit Fingerprint. | El firmware verifica el sensor, espera dedo y convierte la imagen. El modo automático consulta el sensor en pasos con intervalo de 50 ms y usa un límite de 10 s de espera de dedo. Un fallo puede reportarse como slot 0. |
| Pi ↔ ESP32 NFC, Wi-Fi LAN | HTTP JSON, puerto 80. `POST /v1/nfc/scan`, `GET /v1/nfc/health`. | Orden firmada por escaneo. TTL de orden 30 s por defecto, timeout de conexión 3 s y lectura 35 s en la Pi. El firmware persiste la última secuencia y recuerda 16 nonces en RAM. La respuesta firmada vence 15 s después de generarse. Salud devuelve 200/503 y no está firmada. |
| ESP32 de huella ↔ FastAPI, Wi-Fi LAN | HTTP JSON con cabeceras y HMAC. La ESP32 consulta una orden y entrega su resultado. | Consulta cada 2 s en el ciclo disponible, timeout HTTP 5 s y reintento de entrega cada 3 s ante fallos recuperables. La orden vence a los 60 s por defecto en la API. Cada petición usa nonce nuevo y secuencia persistida en la ESP32. La API persiste secuencia y nonce. |
| ESP32 ↔ servicio de hora, red | NTP mediante `configTime`. | Sincronización para validar timestamps y expiraciones. Huella valida desfase en ambas direcciones, con 120 s en el firmware y 120 s como valor predeterminado en el backend. |
| Urna ↔ FastAPI, loopback previsto | HTTP JSON con `X-Device-Key`. Sesión, boleta, voto, bloqueo y latido. | El adaptador espera 8 s por defecto. La urna consulta el estado de huella cada 1 s hasta 75 s por defecto. Un envío sin confirmación se muestra como incierto. |
| Urna → FastAPI, red local o loopback | HTTP JSON de latido. Reporta estado observado de PN532 y cámara. | Cada 15 s con la configuración predeterminada. Estados sin actualizar pierden vigencia a los 45 s. La cámara se sondea en Linux mediante V4L2 sin abrir flujo de video. Una cámara ocupada o un lector ocupado pueden omitirse en el reporte. |
| Cámara ↔ Pi, interfaz física sin confirmar | Captura OpenCV por índice. La salida de incidentes es JPEG. | Captura durante enrolamiento, verificación o incidente. El timeout facial predeterminado de la urna es 15 s. Los cuadros ordinarios se procesan localmente. |
| GPIO → indicadores, cables | Niveles digitales para LED y pulsos o PWM para buzzers, según sketch. | Activación por evento, con apagado de LED al reiniciar sesión, ante fallos y al concluir el envío. |
| Navegador ↔ FastAPI, red o localhost | HTTP de mismo origen. HTML, JS, JSON y CSV. | Cookie de administración y cabecera en login/logout. Consultas del panel típicamente cada 5, 10 o 15 s según la vista. Pronóstico cada 60 s. |
| FastAPI ↔ PostgreSQL, TCP/IP | SQL a través de psycopg y SQLAlchemy. | Consultas y commits según cada petición. TLS requerido por defecto mediante `sslmode=require`. SQLite accede a archivo local. |
| Operador ↔ ESP32, monitor serie | Serie local a 115 200 baudios. | Carga y diagnóstico, incluido enrolamiento de huella. El tráfico normal de voto entre la Pi y ESP32 usa Wi-Fi. |

Las variantes base usan SSID y contraseña. Las carpetas `_Tec` configuran autenticación empresarial con identidad, usuario y contraseña. En NFC seleccionan la API EAP del core de ESP32 según la versión. Huella Tec incluye `esp_eap_client.h`. No hay evidencia de prueba de asociación en la red institucional. [NFC Tec](../firmware/nfc_esp32_Tec/nfc_esp32_Tec.ino) · [Huella Tec](../firmware/fingerprint_esp32_Tec/fingerprint_esp32_Tec.ino)

## Ejemplos del contrato con datos sintéticos

| Mensaje | Método y forma |
| --- | --- |
| Orden de escaneo | `POST /v1/nfc/scan` con `{"deviceId":"nfc-esp32-01","sessionId":"UUID-DE-ESCANEO-DEMO","action":"scan","nonce":"NONCE-DE-EJEMPLO-0001","sequence":1700000000000,"expiresAt":1700000030,"hmac":"FIRMA-OMITIDA"}` |
| Respuesta del lector | `{"deviceId":"nfc-esp32-01","sessionId":"UUID-DE-ESCANEO-DEMO","nonce":"NONCE-DE-EJEMPLO-0001","sequence":1700000000000,"status":"ok","uid":"A1B2C3D4","expiresAt":1700000015,"hmac":"FIRMA-OMITIDA"}` |
| Apertura de sesión | `POST /api/v1/session/start` con `{"cardUid":"A1B2C3D4"}`. Devuelve `sessionId` y `voterName`. El UUID del escaneo normal es distinto del ID de sesión que asigna FastAPI. |
| Consulta de orden | `GET /api/v1/device/fingerprint-command/pending`. Puede responder `{"active":false,"command":null}` o entregar identificadores de orden y sesión, más el timeout. |
| Resultado de huella | `POST /api/v1/session/{sessionId}/fingerprint` con `{"commandId":"ID-DE-ORDEN-DEMO","fingerprintSlot":12}`. |
| Latido | `POST /api/v1/device/heartbeat` con `{"components":{"nfc":"online","camera":"offline"}}`. |
| Emisión de voto | `POST /api/v1/session/{sessionId}/vote` con `{"mayorId":3,"governorId":7,"presidentId":11}`. El éxito devuelve `{"status":"voteRecorded"}`. |

Los nombres de campos y valores de estado corresponden al código. Los identificadores, UID y tiempos son ficticios y las firmas se omiten. [Construcción NFC](../kiosk_ui/adapters/real/nfc.py) · [Firmware de huella](../firmware/fingerprint_esp32/fingerprint_esp32.ino) · [Cliente del backend](../kiosk_ui/adapters/real/api_client.py)

## Autenticación y pertinencia

- NFC firma un conjunto ordenado de campos con HMAC-SHA256. El adaptador comprueba identificador, contexto, nonce, secuencia, vencimiento y firma. Para el desbloqueo la API vuelve a verificar la lectura, la vincula al incidente vigente y consume su nonce. El voto normal solo envía el UID a FastAPI después de la verificación en la Pi.
- Huella usa `X-Device-Id`, `X-Timestamp`, `X-Nonce`, `X-Sequence` y `X-Signature` en la petición. La firma cubre método, ruta, SHA-256 del cuerpo y metadatos. Las respuestas firmadas incluyen el nonce de la solicitud en el cálculo. La API devuelve rechazos de aplicación firmados una vez autenticada la petición. Un rechazo previo a autenticación puede llegar sin firma y la ESP32 lo trata como respuesta no autenticada.
- La atestación facial firma ID de sesión, desafío, ID del votante evaluado y resultado. La clave de atestación es distinta de la clave AES-GCM del vector facial. El backend solo necesita la primera para esta verificación.
- HMAC autentica el origen con una clave compartida y protege la integridad. El HTTP local de los sketches y las URLs de ejemplo deja el contenido visible en su trayecto. El despliegue documentado delimita la red de casilla y prevé HTTPS para el panel cuando se habilita la cookie segura.
- SPI y UART coinciden con las bibliotecas de los módulos elegidos, y HTTP permite expresar órdenes, estados y errores sin un broker adicional. Son ventajas derivadas de la topología y de los contratos observados. El código no incluye medidas comparativas de latencia o confiabilidad entre protocolos. [Firmas y formato](../common/hmac_protocol.py) · [Validaciones](../backend.py) · [Panel](../dashboard_api.py)
