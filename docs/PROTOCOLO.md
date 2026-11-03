# Protocolos de autenticación

Todos los HMAC son SHA-256, representados como 64 caracteres hexadecimales en minúsculas. Las claves tienen 32 bytes, son independientes y se comparan en tiempo constante. No se incluyen secretos, UID ni datos biométricos en logs.

## 1. NFC: Raspberry Pi ↔ ESP32 NFC

Endpoint de la ESP32: `POST /v1/nfc/scan`.

Orden JSON:

```json
{
  "deviceId": "nfc-esp32-01",
  "sessionId": "uuid-local",
  "action": "scan",
  "nonce": "32 hex aleatorios",
  "sequence": 1780000000000,
  "expiresAt": 1780000000,
  "hmac": "64 hex"
}
```

Canonicalización, con saltos `\n` literales:

```text
nfc-command-v1\ndeviceId\nsessionId\naction\nnonce\nsequence\nexpiresAt
```

La ESP32 valida identidad, acción, HMAC, nonce no utilizado, secuencia estrictamente creciente y expiración NTP. La secuencia se conserva con Preferences y los últimos nonces en memoria. La Pi usa milisegundos Unix como secuencia creciente incluso tras reiniciar.

Respuesta:

```text
nfc-response-v1\ndeviceId\nsessionId\nnonce\nsequence\nstatus\nuid\nexpiresAt
```

La Pi exige que sesión, nonce y secuencia coincidan con su orden, que el plazo siga vigente y que el HMAC sea válido. Estados: `ok`, `timeout`, `invalid_read`. Solo `ok` con UID hexadecimal de 4–10 bytes continúa.

## 2. Huella: ESP32 ↔ FastAPI

Se conserva el contrato JSON existente. La autenticación viaja en cabeceras:

- `X-Device-Id`
- `X-Timestamp`: Unix en segundos.
- `X-Nonce`: aleatorio, de un solo uso.
- `X-Sequence`: entero creciente, persistente.
- `X-Signature`: HMAC de la petición.

Petición:

```text
esp32-request-v1\nMETHOD\n/path\nSHA256_hex(body)\ndeviceId\ntimestamp\nnonce\nsequence
```

Respuesta:

```text
esp32-response-v1\ndeviceId\ntimestamp\nrequestNonce\nresponseNonce\nSHA256_hex(rawBody)
```

La respuesta incluye `X-Device-Id`, `X-Timestamp`, `X-Nonce` y `X-Signature`. La ESP32 no acepta un `fingerprintOk` o una orden si la respuesta no es auténtica. FastAPI persiste nonce y secuencia en `DeviceNonce` y `DeviceReplayGuard`; las órdenes `FingerprintCommand` además se consumen una sola vez.

Una firma inválida o una repetición no produce una lectura válida. Los resultados tardíos de órdenes vencidas/canceladas se descartan. El slot devuelto por el sensor se compara en backend con el slot del votante asociado a la tarjeta: no basta con que la huella exista en el sensor.

## 3. Atestación facial local → FastAPI

La atestación evita que un cliente con solo la clave general envíe `matched: true` como prueba suficiente. Requiere la clave local independiente `FACE_ATTESTATION_KEY`.

```text
face-attestation-v1\nsessionId\nchallenge\nvoterId\nmatched(true|false)
```

El desafío se consume una sola vez. Una atestación incorrecta se rechaza antes de consumir un intento biométrico. El backend vuelve a exigir NFC, huella, rostro, habilitación y ausencia de voto previo antes de aceptar candidatos o voto.

## 4. Claves, provisión y rotación

Generar cada secreto por separado:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Para el key ring facial:

```bash
python generate_face_key.py
```

- `DEVICE_KEY`: servicio local Pi ↔ FastAPI.
- `NFC_HMAC_KEY`: solo Pi y ESP32 NFC; el mismo valor se coloca manualmente en `secrets.h` de esa ESP32.
- `FINGERPRINT_HMAC_KEY`: solo FastAPI y ESP32 de huellas.
- `FACE_ATTESTATION_KEY`: proceso local de kiosk y FastAPI en la Pi.
- `FACE_ENCRYPTION_KEYS`: key ring AES-GCM, solo entorno confiable de la Pi; nunca en Neon.
- `ADMIN_KEY`: enrolamiento administrativo.

Para reemplazar una clave HMAC, provisionar primero el servidor y luego el dispositivo durante una ventana de mantenimiento; no hay período de clave dual para HMAC. Conservar la clave facial anterior en el key ring al activar una nueva permite descifrar registros antiguos; los nuevos usan `FACE_ACTIVE_KEY_ID`. No registrar valores en archivos de log ni confirmar `secrets.h`/`.env` al repositorio.

## 5. TLS y red

HMAC no cifra. En la red local se exige WiFi WPA2/WPA3, segmentación y firewall. FastAPI debe exponerse solo a la red de casilla para que la ESP32 de huellas lo alcance; kiosk usa `127.0.0.1`. Neon usa TLS (`sslmode=require`). HTTPS adicional en las ESP32 requiere provisión de CA/certificados y validación de reloj; no se afirma que esté desplegado. Para producción se recomienda un endpoint TLS local con certificados gestionados, sin eliminar HMAC mientras se requiera protección de mensaje y anti-repetición a nivel de aplicación.
