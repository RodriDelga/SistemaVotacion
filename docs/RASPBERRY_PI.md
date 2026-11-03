# Instalación y operación en Raspberry Pi

## 1. Red y hardware

- Raspberry Pi con Raspberry Pi OS de 64 bits, cámara y acceso a Neon.
- ESP32 NFC + PN532 en SPI: SCK 18, MISO 19, MOSI 23, SS 5.
- ESP32 de huellas + R307/AS608: sensor TX → GPIO16, sensor RX → GPIO17. Verifique alimentación en la hoja de datos.
- Red WiFi de 2.4 GHz para las ESP32, preferiblemente segmentada y con WPA2/WPA3.
- No conecte las ESP32 a la Pi como canal USB/serie. El puerto serie solo se usa para programación y diagnóstico local.

Asigne IP estática o reserva DHCP a la ESP32 NFC y a la Pi. Configure `NFC_ESP32_URL` y `API_BASE_URL` coherentemente. La ESP32 de huellas usa la IP WiFi de la Pi en su `secrets.h`; kiosk usa `http://127.0.0.1:8000`.

## 2. Paquetes y Python

```bash
sudo apt update
sudo apt install python3-venv python3-tk python3-dev build-essential cmake \
  libopenblas-dev liblapack-dev libatlas-base-dev libgl1
cd /opt/votacion
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`face-recognition` compila/instala dlib y puede tardar en Raspberry Pi. Compruebe las importaciones sin iniciar la UI:

```bash
python -c "import fastapi, sqlmodel, cv2, face_recognition, customtkinter"
python -c "import tkinter; print(tkinter.TkVersion)"
```

## 3. Configuración segura

```bash
cp .env.example .env
chmod 600 .env
```

Genere valores distintos para cada clave:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python generate_face_key.py   # clave AES en base64
```

Complete `DATABASE_URL` con la cadena TLS de Neon. No ejecute las pruebas contra esa base: la suite siempre fuerza su propio SQLite temporal. `SQLModel.metadata.create_all` crea las tablas faltantes, pero no sustituye un sistema de migraciones. En una instalación con datos, revise primero el plan SQL y respalde según el procedimiento operativo; no se incluye ninguna migración destructiva.

Compruebe que el entorno tiene las claves sin imprimirlas:

```bash
set -a; source .env; set +a
python - <<'PY'
import os
required = ["DATABASE_URL", "DEVICE_KEY", "NFC_HMAC_KEY", "FINGERPRINT_HMAC_KEY", "FACE_ATTESTATION_KEY", "FACE_ENCRYPTION_KEYS"]
missing = [name for name in required if not os.getenv(name)]
raise SystemExit("Faltan: " + ", ".join(missing) if missing else "Configuración presente")
PY
```

## 4. Compilar las dos ESP32

Use Arduino IDE o arduino-cli con el core ESP32. Instale:

- Adafruit PN532.
- Adafruit Fingerprint Sensor Library.
- ArduinoJson (versión 6; el firmware usa `StaticJsonDocument`).

Para cada placa:

1. Abra la carpeta correspondiente de `firmware/`.
2. Copie `secrets.h.example` como `secrets.h`.
3. Complete WiFi, NTP y la clave específica del canal. Nunca comparta la clave NFC con la de huellas.
4. Seleccione el modelo correcto de ESP32, compile y cargue.
5. No copie `secrets.h` al control de versiones.

El firmware NFC requiere NTP para validar expiración. El de huellas incrementa una secuencia persistente y valida también la firma de las respuestas del backend. Si se reemplaza el backend por otro entorno, use una base/clave nueva o una política de secuencias controlada; no reinicie manualmente los contadores durante operación.

## 5. Enrolamiento administrativo

El enrolamiento crea o modifica datos y debe hacerse solo en el entorno autorizado, nunca durante las pruebas automatizadas:

1. Cree votante y candidatos mediante los endpoints administrativos existentes.
2. Enrolle la huella en un slot con el menú local de la ESP32 de huellas.
3. Asocie ese `fingerprintSlot` al votante.
4. Con `ADMIN_KEY` y el key ring facial configurados, ejecute `python enroll_face.py` y seleccione explícitamente el votante.

La UI de votación no ofrece enrolamiento ni muestra los datos usados por estos procedimientos.

## 6. Ejecución

Backend (accesible solo a la red de casilla para la ESP32):

```bash
cd /opt/votacion
source .venv/bin/activate
set -a; source .env; set +a
uvicorn backend:app --host 0.0.0.0 --port 8000
```

Interfaz en otro proceso:

```bash
cd /opt/votacion
source .venv/bin/activate
set -a; source .env; set +a
python -m kiosk_ui.main --fullscreen --inactivity 120
```

`--show-exit` es solo para desarrollo. F11 alterna pantalla completa, Esc la abandona y Ctrl+Q cierra; en un kiosco oficial deben restringirse esas salidas mediante la sesión gráfica o una variante operativa controlada.

## 7. Servicios systemd orientativos

Cree un servicio backend con `WorkingDirectory=/opt/votacion`, `EnvironmentFile=/opt/votacion/.env` y:

```ini
ExecStart=/opt/votacion/.venv/bin/uvicorn backend:app --host 0.0.0.0 --port 8000
Restart=on-failure
```

La UI debe iniciarse dentro de la sesión gráfica del usuario de casilla, no como servicio sin DISPLAY. Configure el arranque automático del entorno gráfico, oculte el cursor solo tras validar la interacción táctil y proteja los archivos `.env` para el usuario del servicio.

## 8. Firewall y recuperación

- Permita puerto 8000 únicamente desde la subred de dispositivos; no lo exponga a Internet.
- Restrinja salida Neon a HTTPS/TLS.
- Si se pierde conexión después de ENVIAR VOTO, la interfaz bloquea reenvíos. El operador debe revisar backend/DB antes de abrir otra sesión.
- No borre tablas para recuperar una sesión. La cancelación y el vencimiento invalidan órdenes pendientes.
- Antes de una jornada real ejecute la lista física de `docs/PRUEBAS.md` y una prueba de concurrencia de doble voto en un entorno de staging con Neon.
