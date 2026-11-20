# 09 · Guía de instalación

## Urna de demostración sin hardware

Abra una terminal con entorno gráfico y sitúese en la raíz del proyecto. Use Python 3 con Tk disponible. La revisión usó Python 3.12 en Windows. En Raspberry Pi OS, la guía previa instala `python3-tk` para habilitar la interfaz.

```bash
python -m pip install customtkinter Pillow
python -m kiosk_ui.main --demo --delay 0.4
```

Seleccione un escenario y pulse **Simular tarjeta**. La demo reproduce la interacción y no necesita la base, la red ni los lectores. `--delay` solo cambia el ritmo de simulación. [Punto de entrada](../kiosk_ui/main.py) · [Escenarios](../kiosk_ui/adapters/mock.py)

## Panel web con SQLite y datos ficticios

Instale Python y Node.js con npm. Se usaron Python 3.12 y Node.js 22 para verificaciones locales. Cree una base nueva para la demo y abra FastAPI desde la raíz, después de preparar el frontend. Los valores del ejemplo son identificadores públicos solo para esta ejecución local.

```bash
cd dashboard
npm ci
npm run build
cd ..
python -m pip install fastapi "uvicorn[standard]" sqlmodel requests cryptography numpy Pillow
export DATABASE_URL="sqlite:///dashboard-academico-demo.db"
export DEVICE_KEY="solo-demo-dispositivo-local"
export ADMIN_KEY="solo-demo-admin-local"
export DASHBOARD_COOKIE_SECURE=false
python scripts/seed_dashboard_demo.py
python -m uvicorn backend:app --host 127.0.0.1 --port 8000
```

En PowerShell, sustituya las cuatro líneas `export` por las siguientes asignaciones antes de poblar o arrancar el servidor.

```powershell
$env:DATABASE_URL = 'sqlite:///dashboard-academico-demo.db'
$env:DEVICE_KEY = 'solo-demo-dispositivo-local'
$env:ADMIN_KEY = 'solo-demo-admin-local'
$env:DASHBOARD_COOKIE_SECURE = 'false'
```

Abra `http://127.0.0.1:8000/dashboard/` e ingrese la contraseña de demo. Si el archivo ya tiene registros y necesita empezar de nuevo, elija otro nombre de archivo. El sembrador produce un padrón ficticio y resultados de presidencia para navegación. La boleta completa exige candidaturas de los tres cargos. Para simular latidos, en otra terminal con el mismo `DEVICE_KEY` ejecute `python scripts/seed_dashboard_demo.py --heartbeat http://127.0.0.1:8000`. El pronóstico se habilita con dos fechas ISO 8601 con desfase y solo entrega una proyección cuando las observaciones reúnen las condiciones descritas en inteligencia. [Sembrador](../scripts/seed_dashboard_demo.py) · [Frontend](../dashboard/package.json) · [Pronóstico](06-inteligencia.md)

Para desarrollo del frontend, `npm run dev` dentro de `dashboard/` sirve `http://localhost:5173/dashboard/` y reenvía `/api` al backend local. `VITE_API_TARGET` cambia ese destino si hace falta. [Configuración Vite](../dashboard/vite.config.ts)

## Urna real en un entorno de prueba

1. Use Raspberry Pi OS de 64 bits con entorno gráfico según la guía de despliegue. Prepare cámara, pantalla, dos ESP32, PN532, módulo de huella compatible, indicadores, alimentación y red de casilla. Revise primero señales y alimentación en el [inventario y las tablas de cableado](07-sensores-actuadores.md).
2. Prepare una base PostgreSQL de pruebas y su URL `postgresql+psycopg://`. Use un rol con acceso a las tablas y permisos de creación si FastAPI las va a inicializar. Para una base existente, revise diferencias de esquema y haga respaldo antes de una migración. `create_all` solo crea tablas ausentes.
3. Configure Arduino IDE o arduino-cli con core ESP32, ArduinoJson 6, Adafruit PN532 y Adafruit Fingerprint Sensor Library, según las guías del repositorio. Compile un sketch por placa. Use las carpetas base para SSID/contraseña o los sketches `_Tec` para la configuración empresarial. Huella Tec requiere un core que provea `esp_eap_client.h`.
4. En cada carpeta de firmware, cree o configure `secrets.h` a partir del ejemplo de esa variante. Configure credenciales de red, `NTP_SERVER`, identificador y clave exclusiva del canal. En huella, `API_BASE_URL` debe apuntar a la IP enrutable de la Pi, con puerto 8000 en este ejemplo. La URL del NFC debe apuntar a la ESP32 del PN532. Reserve direcciones en la red de laboratorio si cambian con DHCP.
5. Instale las dependencias de Python. La captura facial puede requerir compilar dlib. Los paquetes de compilación están descritos en la [guía de Raspberry Pi](RASPBERRY_PI.md). Para los LED compruebe la disponibilidad de `gpiozero` y el acceso GPIO dentro del mismo entorno de Python.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "import tkinter, cv2, face_recognition, customtkinter"
```

## Configuración de la Pi y arranque

Prepare un `.env` local desde [el ejemplo](../.env.example) si aún no existe. Limite sus permisos al usuario de servicio. Los procesos leen variables del entorno y necesitan cargarlas antes de arrancar.

| Variables | Uso |
| --- | --- |
| `DATABASE_URL`, `DB_SSLMODE` | URL del almacenamiento y modo TLS de PostgreSQL. `DB_SSLMODE` vale `require` por defecto. |
| `DEVICE_KEY`, `ADMIN_KEY` | Credencial de la urna y credencial administrativa. Genere valores aleatorios y distintos. |
| `KIOSK_DEVICE_ID`, `NFC_DEVICE_ID`, `FINGERPRINT_DEVICE_ID` | Identificadores configurados en backend y firmware donde corresponda. |
| `NFC_ESP32_URL`, `API_BASE_URL` | NFC alcanzable desde la Pi y API local de la urna, normalmente `http://127.0.0.1:8000`. |
| `NFC_HMAC_KEY`, `FINGERPRINT_HMAC_KEY`, `FACE_ATTESTATION_KEY` | Tres claves HMAC independientes de 32 bytes expresados en 64 caracteres hexadecimales. Las dos primeras tienen pareja en los sketches correspondientes. |
| `FACE_ENCRYPTION_KEYS`, `FACE_ACTIVE_KEY_ID` | Objeto JSON de identificadores y claves AES de 32 bytes en base64. El identificador activo debe existir en el objeto. Configúrelos en los procesos locales de enrolamiento y captura facial. |
| `REQUIRE_FACE`, `MAX_FACE_ATTEMPTS`, `CAMERA_INDEX`, `FACE_CAPTURE_TIMEOUT_SECONDS` | Para el flujo completo use `REQUIRE_FACE=true`. Valores predeterminados de intentos, índice y límite facial: 5, 0 y 15 s. |
| `SESSION_TIMEOUT_SECONDS`, `FINGERPRINT_COMMAND_TIMEOUT_SECONDS`, `DEVICE_MAX_SKEW_SECONDS` | Vigencia de sesión, vigencia de orden de huella y ventana temporal del backend. Valores predeterminados: 300, 60 y 120 s. |
| `INCIDENT_PHOTO_RETENTION_DAYS` | Plazo de disponibilidad de evidencias, 30 días por defecto. |
| `DASHBOARD_SESSION_SECRET`, `DASHBOARD_COOKIE_SECURE`, `DASHBOARD_DIST`, `DASHBOARD_TIMEZONE` | Firma del panel, cookie segura bajo HTTPS, ruta de compilación y zona horaria. |
| `DASHBOARD_HEARTBEAT_TTL_SECONDS`, `DASHBOARD_EVENT_RETENTION_DAYS` | Vigencia del latido y retención de eventos técnicos. Valores predeterminados: 45 s y 30 días. |
| `DASHBOARD_ELECTION_OPENS_AT`, `DASHBOARD_ELECTION_CLOSES_AT` | Ventana de pronóstico. Por ejemplo, `2026-11-20T08:00:00-06:00` a `2026-11-20T18:00:00-06:00`. |

Para obtener un valor HMAC nuevo ejecute `python -c "import secrets; print(secrets.token_hex(32))"` una vez por clave. `python generate_face_key.py` genera una clave facial. Mantenga los valores generados en la configuración local. [Variables y límites](../backend.py) · [Configuración web](../dashboard_api.py) · [Claves faciales](../face_crypto.py)

```bash
# Terminal 1, en la Raspberry Pi
source .venv/bin/activate
set -a
. ./.env
set +a
env -u FACE_ENCRYPTION_KEYS -u FACE_ACTIVE_KEY_ID python -m uvicorn backend:app --host 0.0.0.0 --port 8000

# Terminal 2, en una sesión gráfica de la misma Pi
source .venv/bin/activate
set -a
. ./.env
set +a
python -m kiosk_ui.main --fullscreen --inactivity 120
```

Use primero un padrón de pruebas. Abra `http://127.0.0.1:8000/docs` para inspeccionar la API. El menú serie de la ESP32 de huella a 115 200 baudios ofrece `e` para enrolar en un slot. Cree el votante con ese slot y su UID, agregue candidaturas nacionales, estatales y municipales y ejecute `python enroll_face.py` con el entorno local. El script pide escoger el votante y confirmar explícitamente un reemplazo. Enrole también una tarjeta administrativa de prueba antes de verificar el bloqueo. [Contrato API](11-api-software.md) · [Despliegue detallado](../GUIA_DESPLIEGUE_REAL.md) · [Alta administrativa](SEGURIDAD_KIOSK.md)

### Verificación y errores frecuentes

| Síntoma | Qué comprobar |
| --- | --- |
| FastAPI falla al iniciar | URL válida, controlador psycopg, acceso de red/TLS, permisos y que la configuración esté en el proceso. |
| `/dashboard/` devuelve 404 | Que `dashboard/dist` exista al iniciar FastAPI o que `DASHBOARD_DIST` apunte al build. Reinicie después de compilar. |
| El panel vuelve al inicio de sesión | Cookie vigente y mismo origen. Una cookie con `DASHBOARD_COOKIE_SECURE=true` requiere HTTPS en el despliegue. |
| El panel informa una zona horaria inesperada | Revise `DASHBOARD_TIMEZONE` y la disponibilidad de datos de zona. Si la zona solicitada no carga, el backend usa UTC−6 fijo y registra un aviso. |
| NFC da 503, timeout o rechazo | Consulte `GET /v1/nfc/health`, verifique SPI, alimentación, IP, NTP e identificador/clave del canal. Un 404 puede indicar firmware previo al endpoint de estado. |
| Huella espera y no avanza | Revise UART cruzada, monitor serie, API desde el ESP32, sincronización NTP y la orden. Si hay rechazo biométrico, compruebe el slot enrolado. |
| Rostro falla al preparar la verificación | Revise plantilla cifrada enrolada, clave local, permisos de cámara e índice. La API admite `REQUIRE_FACE=false`, pero la urna actual sigue invocando el desafío y falla con esa configuración. |
| Una luz se queda apagada | Revise polaridad, resistencia, GPIO y si `gpiozero` inicializó el pin. El adaptador de respaldo ignora las órdenes GPIO. |
| La boleta no carga | Debe existir al menos un candidato elegible por cargo en la región del votante. |
| El backend devuelve 423 | Consulte el estado y siga el procedimiento de la tarjeta administrativa. |
| La confirmación del voto se pierde | Detenga nuevos intentos para esa sesión y derive la revisión a la persona operadora. |

El puerto de FastAPI debe poder alcanzarse desde la ESP32 de huella en el montaje. La guía de laboratorio delimita acceso a la red de casilla. La configuración de HTTPS y servicios se describe en las guías de despliegue. [Raspberry Pi](RASPBERRY_PI.md) · [Comprobaciones reproducibles](12-pruebas-evidencias.md)
