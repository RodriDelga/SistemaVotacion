# Resultados de pruebas

Fecha de ejecución en el entorno de integración: 2026-11-01.

## Resumen verificable

| Suite | Resultado | Alcance |
|---|---:|---|
| `python -m unittest discover -s tests -v` | **17/17 pasaron** | Backend, HMAC, AES-GCM, cámara simulada y adaptadores |
| `python -m unittest kiosk_ui.tests.test_controller -q` | **14/14 pasaron** | Controlador, selección, revisión, cancelación y envío |
| `xvfb-run ... python tests/ui_smoke.py` | **Pasó** | Recorrido gráfico virtual completo |
| **Total de pruebas unitarias/integración** | **31/31 pasaron** | Ninguna usa datos o votos reales |

Los tres `ConnectionError` registrados durante las pruebas del controlador son excepciones inducidas para verificar manejo de errores; las pruebas correspondientes terminaron en `ok`.

## Cobertura automatizada

### NFC

- Respuesta válida y UID entregado al inicio de sesión backend.
- HTTP real contra simulador con comando y respuesta firmados.
- Respuesta alterada, nonce incorrecto y UID incompleto: rechazados.
- Timeout y desconexión: no continúan.
- Cancelación antes de la lectura.
- En firmware: validación de dispositivo, acción, nonce, secuencia, expiración y HMAC. **Compilación y ejecución física pendientes.**

### Huella

- Orden creada por kiosk y consultada por dispositivo con HMAC.
- Slot correcto vinculado al votante de la tarjeta.
- Slot incorrecto: rechazo y contador de intentos.
- HMAC inválido: 401.
- Reenvío idéntico con nonce/secuencia repetidos: rechazado.
- Respuestas backend firmadas verificadas en las pruebas.
- Sesión cerrada/expirada y comando de un solo uso en backend.
- La lectura R307/AS608 y los estados del firmware se conservaron, pero no se probaron físicamente.

### Rostro y cifrado

- AES-256-GCM roundtrip; nonce de 12 bytes y ciphertext/tag de 1040 bytes.
- Rotación de key ID, AAD, envelope inválido, tamaño incorrecto, NaN y manipulación.
- Coincidencia, rostro incorrecto, ambigüedad y registro corrupto.
- Cero rostros, más de un rostro y cámara no disponible con dobles de cámara.
- Atestación HMAC válida; atestación incorrecta rechazada sin aceptar `matched: true` aislado.
- Backend entrega únicamente el envelope del votante de la sesión.

### Backend y voto

- Sesión válida, tarjeta desconocida, votante deshabilitado y sesión expirada.
- Boleta bloqueada antes de completar factores.
- Orden `MAYOR → GOVERNOR → PRESIDENT`.
- Candidato de otra región excluido de boleta y rechazado al enviar.
- Flujo NFC/sesión → huella → rostro → boleta → voto con SQLite temporal.
- Voto duplicado: sesión cerrada y nuevo inicio rechazado.
- Tres filas de voto anónimas sin `voterId`/`sessionId`.
- Error de backend, respuesta inesperada y excepción tratados como inciertos por el controlador/adaptador.

### Interfaz y controlador

- Flujo completo, selección obligatoria, modificación desde revisión.
- Nada se envía antes de ENVIAR VOTO.
- Doble clic/doble llamada: una sola operación.
- Reset ignorado mientras se envía.
- Rechazo, incertidumbre y excepción nunca se muestran como éxito.
- Fallos de tarjeta, huella, rostro y boleta; reintento y cancelación.
- Pantalla virtual: bienvenida → NFC/huella/rostro simulados → «Identidad verificada correctamente» → boleta → revisión → confirmación.

## Pruebas físicas pendientes (no afirmadas)

1. Compilar ambos firmware con el core ESP32 y versiones exactas de librerías elegidas.
2. Verificar PN532 por SPI, detección de tarjetas de 4/7/10 bytes, retiro y reconexión WiFi.
3. Verificar R307/AS608, enrolamiento, lectura correcta/incorrecta, dedo retenido y reconexión.
4. Validar NTP con reloj incorrecto, WiFi interrumpido y pérdida de backend durante entrega.
5. Probar nonce/secuencia tras reiniciar cada ESP32 y tras reiniciar la Pi/backend.
6. Probar cámara real, iluminación, rostro incorrecto, varias personas, encuadre y tiempos en Raspberry Pi.
7. Ejecutar enrolamiento administrativo y rotación de claves en staging.
8. Conectar una base Neon de staging; verificar TLS, latencia, pérdida de red y concurrencia de dos votos para el mismo votante.
9. Validar UI en la pantalla táctil real, 800×480 u otra resolución, fuentes, escalado, inactividad y modo kiosco.
10. Probar apagado/cierre inesperado durante cada fase y procedimiento operativo ante envío incierto.
11. Realizar revisión de seguridad independiente, pruebas de clonación UID y evaluación de presentación de fotografías/vídeos al sistema facial.
12. Definir y probar multi-elección solo después de una migración aditiva; el esquema actual tiene una elección implícita.

No se ejecutaron operaciones contra Neon, no se modificaron votantes reales, no se emitieron votos reales y no hubo acceso a hardware físico.
