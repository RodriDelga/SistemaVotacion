# Sistema de votación electrónica — kiosk_ui integrado

Prototipo de una casilla que verifica la identidad con tarjeta NFC, huella y rostro, presenta las candidaturas de tres cargos y registra las selecciones tras confirmación. La Raspberry Pi aloja la urna **Python + CustomTkinter** y **FastAPI** en el despliegue previsto. Dos ESP32 operan los lectores por Wi-Fi, **PostgreSQL/Neon** almacena los registros y un panel web muestra resultados e indicadores operativos.

La [documentación técnica para TC1004B](docs/README.md) reúne la arquitectura, el modelo de datos, el cableado, la instalación, la guía de usuario y las evidencias de los cinco criterios de la rúbrica.

## Contenido

- `kiosk_ui/`: interfaz, controlador, puertos, mocks y adaptadores reales.
- `backend.py`: API y modelos SQLModel existentes, reforzados con HMAC y anti-repetición.
- `dashboard/`, `dashboard_api.py` y `forecast.py`: interfaz web, reportes, latidos y pronóstico de participación.
- `face_crypto.py`, `face_local.py`, `enroll_face.py`: cifrado, captura/comparación y enrolamiento local.
- `firmware/nfc_esp32/`: PN532 bajo órdenes autenticadas.
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

En la bienvenida, elija un escenario y pulse **Simular tarjeta**. Para terminar el recorrido, complete los tres cargos, pulse **ENVIAR VOTO** y confirme con **Sí, enviar voto**.

Para probar el panel con datos ficticios, siga la [instalación del panel con SQLite](docs/09-guia-instalacion.md).

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
python -m pip install -r requirements-dev.txt
python -m pytest -q tests kiosk_ui/tests
```

Ejecute la suite desde un entorno local sin credenciales de despliegue. Usa SQLite temporal, servidores simulados y datos sintéticos. Consulte los [resultados actuales y las pruebas físicas pendientes](docs/12-pruebas-evidencias.md).

## Documentación

- [Índice técnico](docs/README.md) y [cobertura de la rúbrica](docs/14-cobertura-rubrica.md).
- [Arquitectura general](docs/02-arquitectura-general.md), [sensores y actuadores](docs/07-sensores-actuadores.md) y [modelo de datos](docs/04-base-de-datos.md).
- [Guía de instalación](docs/09-guia-instalacion.md), [guía de usuario](docs/10-guia-usuario.md) y [API](docs/11-api-software.md).
- `docs/INSPECCION.md`: inventario, problemas y decisiones.
- `docs/ARQUITECTURA.md`: diagrama de componentes y secuencia completa.
- `docs/PROTOCOLO.md`: HMAC, canonicalización, claves y rotación.
- `docs/RASPBERRY_PI.md`: instalación, firmware, ejecución y servicios.
- `docs/BITACORA.md`: cambios por etapa y alcance verificado.
- `docs/DASHBOARD_MANUAL.md` y `docs/DASHBOARD_DECISIONES.md`: panel web de administración (`dashboard/`, `dashboard_api.py`) — resultados en tiempo real, estado del sistema y reportes en `/dashboard/`.

## Alcance funcional importante

El contrato recibido representa una **elección implícita** con tres cargos obligatorios. No existen tablas de elecciones ni historial por elección; no se han inventado. Una futura multi-elección requiere migración aditiva y pruebas específicas. La autenticación de tarjeta se basa en UID PN532 y no equivale a autenticación criptográfica de la tarjeta. El reconocimiento facial no incorpora detección de vida robusta. Estas limitaciones deben resolverse antes de considerar el sistema apto para una elección oficial.

## Seguridad del Kiosk

Consulte [Seguridad del Kiosk](docs/SEGURIDAD_KIOSK.md) para la actualización de base de datos, el alta de tarjetas NFC administrativas, el bloqueo persistente, la API de incidentes y la política de retención.
