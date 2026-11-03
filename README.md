# Sistema de votación electrónica — kiosk_ui integrado

Aplicación principal **Python + CustomTkinter**, FastAPI en la Raspberry Pi, PostgreSQL/Neon y dos ESP32 independientes por WiFi. Conserva el reconocimiento facial local con AES-256-GCM y el programa del sensor R307/AS608. `mainFrontend.py` no forma parte del proyecto integrado.

## Contenido

- `kiosk_ui/`: interfaz, controlador, puertos, mocks y adaptadores reales.
- `backend.py`: API y modelos SQLModel existentes, reforzados con HMAC y anti-repetición.
- `face_crypto.py`, `face_local.py`, `enroll_face.py`: cifrado, captura/comparación y enrolamiento local.
- `firmware/nfc_esp32/`: PN532 bajo órdenes autenticadas; nunca escanea por iniciativa propia.
- `firmware/fingerprint_esp32/`: máquina de estados original con peticiones y respuestas HMAC.
- `common/hmac_protocol.py`: canonicalización compartida y firmas.
- `simulators/nfc_server.py`: simulador del contrato NFC para pruebas.
- `tests/` y `kiosk_ui/tests/`: pruebas unitarias, simuladas y de integración local.
- `docs/`: inventario, diagramas, protocolo, instalación y resultados de pruebas.

## Inicio rápido con simulación

No requiere hardware, FastAPI ni base de datos. Todos los nombres son ficticios.

```bash
python -m pip install customtkinter Pillow
python -m kiosk_ui.main --demo --delay 0.4
```

En la bienvenida, elija un escenario y pulse **Simular tarjeta**. El envío solo ocurre al pulsar **ENVIAR VOTO**.

## Ejecución real

1. Complete `.env` a partir de `.env.example`; no use los valores de ejemplo como secretos.
2. Configure y compile por separado los dos firmware, cada uno con su `secrets.h` y su propia clave.
3. Prepare Neon y los datos administrativos reales fuera de las pruebas automatizadas.
4. Inicie FastAPI y después kiosk_ui:

```bash
set -a; source .env; set +a
uvicorn backend:app --host 0.0.0.0 --port 8000
# En otro proceso, con el mismo entorno:
python -m kiosk_ui.main --fullscreen
```

Consulte `docs/RASPBERRY_PI.md` antes del despliegue. El modo real exige dispositivos y servicios configurados; una cámara, red o backend ausente detiene el paso correspondiente.

## Pruebas

```bash
python -m unittest discover -s tests -v
python -m unittest kiosk_ui.tests.test_controller -v
```

La suite utiliza SQLite temporal, servidores simulados y datos sintéticos. No necesita ni modifica Neon. Los resultados y la matriz de pruebas físicas pendientes están en `docs/PRUEBAS.md`.

## Documentación

- `docs/INSPECCION.md`: inventario, problemas y decisiones.
- `docs/ARQUITECTURA.md`: diagrama de componentes y secuencia completa.
- `docs/PROTOCOLO.md`: HMAC, canonicalización, claves y rotación.
- `docs/RASPBERRY_PI.md`: instalación, firmware, ejecución y servicios.
- `docs/BITACORA.md`: cambios por etapa y alcance verificado.

## Alcance funcional importante

El contrato recibido representa una **elección implícita** con tres cargos obligatorios. No existen tablas de elecciones ni historial por elección; no se han inventado. Una futura multi-elección requiere migración aditiva y pruebas específicas. La autenticación de tarjeta se basa en UID PN532 y no equivale a autenticación criptográfica de la tarjeta. El reconocimiento facial no incorpora detección de vida robusta. Estas limitaciones deben resolverse antes de considerar el sistema apto para una elección oficial.
