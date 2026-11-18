# Guía de puesta en marcha con Neon y hardware real

Esta guía lleva el sistema (urna, dos ESP32, backend y dashboard) de cero a una **prueba de extremo a extremo en un entorno de staging**. Se apoya en `docs/RASPBERRY_PI.md`, `docs/PROTOCOLO.md`, `docs/PRUEBAS.md` y `ARQUITECTURA_DEL_PROYECTO.md`; aquí se ordenan en una secuencia con comprobaciones.

> **Estado de verificación.** Esta guía no se ha ejecutado contra Neon ni contra hardware real: ni el proyecto original (`docs/PRUEBAS.md`: «no hubo acceso a hardware físico») ni el trabajo del dashboard lo hicieron. Los pasos son los documentados en el repositorio más las comprobaciones que se recomiendan para cada uno. Si un paso falla, la sección 12 reúne los problemas más probables.
>
> **Alcance.** Es una guía de **pruebas y staging**. El propio README advierte que el sistema no es apto para una elección oficial (UID NFC sin autenticación criptográfica, reconocimiento facial sin detección de vida, una sola elección implícita). No lo use con datos reales de votantes sin una revisión de seguridad independiente.

## 0. Mapa de lo que se va a montar

```
Admin (laptop) ──HTTP──┐
                       ▼
Pantalla táctil ── kiosk_ui ──HTTP 127.0.0.1:8000──► FastAPI (backend.py + dashboard_api.py) ◄──HTTPS/TLS──► Neon
Cámara ───────────┘   │  ▲                              ▲
LEDs GPIO 17/27/22 ◄──┘  └─HTTP firmado (HMAC)─► ESP32 NFC (PN532)        │
                                                  ESP32 Huella (R307) ──HTTP firmado (HMAC) ──┘
```

Todo el hardware de la casilla va en una misma red WiFi de 2.4 GHz. Las ESP32 **no** se conectan a la Pi por USB (solo para programarlas).

## 1. Lista de verificación previa

| Elemento | Detalle |
|---|---|
| Raspberry Pi | Raspberry Pi OS 64 bits, Python 3.10+, acceso a Internet (Neon) y a la red de la casilla |
| Cámara | USB (UVC) o CSI visible como `/dev/video0` (el código usa `cv2.VideoCapture(CAMERA_INDEX)`, 1280×720) |
| Pantalla | Táctil, 800×480 u otra; sesión gráfica con `DISPLAY` |
| ESP32 NFC + PN532 | SPI: SCK 18, MISO 19, MOSI 23, SS 5 |
| ESP32 huellas + R307/AS608 | Sensor TX → GPIO16, sensor RX → GPIO17, 57 600 baudios |
| LEDs en la Pi | Tarjeta GPIO 17, huella GPIO 27, rostro GPIO 22 (con resistencia) |
| Red | Router 2.4 GHz, WPA2/WPA3; IP estática o reserva DHCP para la Pi y la ESP32 NFC |
| Equipo de desarrollo | Arduino IDE o `arduino-cli`, Node ≥ 20 (solo para compilar el dashboard) |
| Cuenta Neon | Con permiso para crear un **proyecto o rama de staging** |

**Alimentación de los sensores.** El código advierte que no todos los modelos de PN532/R307 aceptan 3.3 V ni usan los mismos colores de cable. Revise la hoja de datos de su módulo antes de energizar; la tensión correcta depende de su montaje y no la fija el software.

## 2. Neon (base de datos de staging)

1. En la consola de Neon cree un proyecto **nuevo para staging**, o una *rama* de la base (`branch`) a partir de la base de pruebas. **No use la base de una elección real.**
2. Copie la cadena de conexión (rol con permisos de lectura y escritura). Tendrá este aspecto:
   `postgresql://usuario:CLAVE@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`
3. Para evitar ambigüedades con el controlador, use el prefijo de psycopg 3, que es el que instala `requirements.txt`:
   `postgresql+psycopg://usuario:CLAVE@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`
   (Con algunas versiones de SQLAlchemy, el prefijo simple `postgresql://` intenta usar `psycopg2` y falla con «No module named psycopg2».)
4. El backend fuerza TLS por defecto (`DB_SSLMODE=require`, tiempo de conexión 10 s). No lo desactive.
5. Si la cadena incluye `channel_binding=require` y la conexión falla, pruebe sin ese parámetro.
6. Neon suspende los cómputos inactivos: la **primera** consulta tras un rato puede tardar unos segundos. Es normal; `pool_pre_ping` ya reconecta.

**Comprobación (desde la Pi, antes de instalar nada más):**

```bash
python3 - <<'PY'
import os, psycopg
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(url, connect_timeout=10) as c:
    print(c.execute("select version()").fetchone()[0])
PY
```

Debe imprimir la versión de PostgreSQL. Si falla por timeout, revise la salida a Internet (443 y el puerto de Postgres 5432) y la hora de la Pi.

**Qué crea el backend en Neon.** Al arrancar, `SQLModel.metadata.create_all` crea las tablas que falten (votantes, candidatos, votos, sesiones, órdenes de huella, nonces) y, por el dashboard, `dashboardevent` y `deviceheartbeat`. No hay sistema de migraciones: si ya hay datos, haga primero una copia de la rama.

## 3. Preparar la Raspberry Pi

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk python3-dev build-essential cmake \
  libopenblas-dev liblapack-dev libatlas-base-dev libgl1 git
sudo timedatectl set-ntp true          # la hora correcta es obligatoria (HMAC y expiraciones)
timedatectl                             # "System clock synchronized: yes"

sudo mkdir -p /opt/votacion && sudo chown $USER /opt/votacion
git clone https://github.com/RodriDelga/SistemaVotacion /opt/votacion
cd /opt/votacion
git checkout feature/dashboard-web      # o main, una vez fusionada la rama

python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`face-recognition` compila dlib y puede tardar bastante en la Pi. Compruebe las importaciones sin abrir la interfaz:

```bash
python -c "import fastapi, sqlmodel, cv2, face_recognition, customtkinter; print('ok')"
python -c "import tkinter; print(tkinter.TkVersion)"
```

**Cámara y GPIO:**

```bash
ls /dev/video*                          # debe existir /dev/video0
sudo usermod -aG video,gpio $USER       # cierre sesión y vuelva a entrar
python - <<'PY'
import cv2
cap = cv2.VideoCapture(0)
ok, frame = cap.read()
print("camara ok" if ok else "SIN IMAGEN", None if not ok else frame.shape)
PY
```

## 4. Claves y archivo `.env`

El README menciona un `.env.example`, pero **ese archivo no existe en el repositorio**. Cree `.env` con esta plantilla.

Genere un valor **distinto** para cada clave de 64 caracteres hexadecimales:

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # repetir para cada clave
python generate_face_key.py                                 # clave AES en base64 (32 bytes)
```

> Ponga entre **comillas simples** todo valor con caracteres especiales (`{ } " & $ !`), sobre todo el JSON del key ring y la contraseña de Neon si los tiene. Sin ellas, `source .env` altera el valor sin avisar.

```ini
# --- Base de datos ---
DATABASE_URL=postgresql+psycopg://USUARIO:CLAVE@HOST/neondb?sslmode=require
DB_SSLMODE=require

# --- Autenticación (todas distintas entre sí) ---
DEVICE_KEY=<token_hex(32)>              # kiosk_ui <-> backend
ADMIN_KEY=<token_hex(32)>               # enrolamiento y login del dashboard
NFC_HMAC_KEY=<64 hex>                   # Pi <-> ESP32 NFC (la MISMA va en el firmware NFC)
FINGERPRINT_HMAC_KEY=<64 hex>           # ESP32 huellas <-> backend (la MISMA va en el firmware de huellas)
FACE_ATTESTATION_KEY=<64 hex>

# --- Cifrado facial (key ring JSON: id -> clave base64 de generate_face_key.py) ---
FACE_ENCRYPTION_KEYS='{"k1":"<base64 de 32 bytes>"}'
FACE_ACTIVE_KEY_ID=k1

# --- Direcciones ---
API_BASE_URL=http://127.0.0.1:8000      # kiosk_ui -> backend (misma Pi)
NFC_ESP32_URL=http://192.168.1.51       # IP de la ESP32 NFC (reserva DHCP)
NFC_DEVICE_ID=nfc-esp32-01
FINGERPRINT_DEVICE_ID=fingerprint-esp32-01
CAMERA_INDEX=0

# --- Dashboard (opcionales; valores por defecto entre paréntesis) ---
DASHBOARD_TIMEZONE=America/Mexico_City
DASHBOARD_BOOTH_LABEL=Urna 01
DASHBOARD_COOKIE_SECURE=false           # true solo si se sirve por HTTPS
# DASHBOARD_SESSION_SECRET=             # (se deriva de ADMIN_KEY)
# DASHBOARD_HEARTBEAT_TTL_SECONDS=45
# DASHBOARD_DIST=dashboard/dist
```

```bash
chmod 600 .env
set -a; source .env; set +a
python - <<'PY'
import os
need = ["DATABASE_URL","DEVICE_KEY","ADMIN_KEY","NFC_HMAC_KEY","FINGERPRINT_HMAC_KEY",
        "FACE_ATTESTATION_KEY","FACE_ENCRYPTION_KEYS","FACE_ACTIVE_KEY_ID"]
missing = [n for n in need if not os.getenv(n)]
raise SystemExit("Faltan: " + ", ".join(missing) if missing else "Configuración completa")
PY
```

Guarde las claves en un gestor de contraseñas. **Nunca** suba `.env` ni `secrets.h` al repositorio (el `.gitignore` ya excluye `.env`).

> El key ring facial es importante: sin la clave con la que se cifraron los rostros no se pueden descifrar. Haga copia de las claves **antes** de enrolar a nadie.

## 5. Dashboard: compilar y copiar

En su equipo de desarrollo (con Node ≥ 20):

```bash
cd dashboard
npm ci
npm run build                            # genera dashboard/dist
scp -r dist usuario@IP_DE_LA_PI:/opt/votacion/dashboard/
```

El backend sirve esa carpeta en `/dashboard/`. Si la Pi no tiene `dist`, el log mostrará «No existe …/dist» y `/dashboard/` dará 404 (el resto del backend funciona).

## 6. Primer arranque del backend (solo, sin hardware)

```bash
cd /opt/votacion && source .venv/bin/activate
set -a; source .env; set +a
uvicorn backend:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` es **necesario**: la ESP32 de huellas llegará por la IP WiFi de la Pi, no por `127.0.0.1`.

Comprobaciones desde otra terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/dashboard/     # 200
curl -s -H "X-Device-Key: $DEVICE_KEY" http://127.0.0.1:8000/api/v1/candidates  # [] la primera vez
```

Abra `http://IP_DE_LA_PI:8000/dashboard/` desde su laptop (misma red) e ingrese con `ADMIN_KEY`. Con la base vacía verá participación 0 % y, en Estado del sistema: Base de datos «En línea», Red «En línea», lo demás «Sin datos»/«Sin conexión». **Eso es correcto en este punto.** Si la base aparece «Sin conexión», vuelva a la sección 2.

### Pronóstico de participación

Configure en el `.env` del backend la apertura y el cierre de su jornada con fechas ISO 8601 y el desfase UTC aplicable. Estos valores son un ejemplo.

```dotenv
DASHBOARD_ELECTION_OPENS_AT=2026-11-17T08:00:00-06:00
DASHBOARD_ELECTION_CLOSES_AT=2026-11-17T18:00:00-06:00
```

Reinicie FastAPI con esas variables y compile el dashboard con `npm run build`. En **Reportes → Participación**, la sección **Pronóstico de participación** usa el horario configurado. El selector de fechas aplica a los reportes históricos.

El modelo requiere al menos 100 votos con marca de tiempo y 60 minutos desde la apertura. La cifra se publica cuando el ajuste tiene suficiente confianza. Si el total de votantes que ya votaron difiere del total de votos exitosos de la bitácora, el panel informa que la serie no se puede confirmar. Al cierre muestra la participación observada si la serie está completa. El backend reutiliza el resultado hasta 60 segundos entre consultas.

## 7. Cargar datos de prueba en Neon (staging)

Use solo datos **ficticios**. Con el backend en marcha:

```bash
# Candidatos (usan X-Device-Key). Región según el cargo.
curl -s -X POST http://127.0.0.1:8000/api/v1/candidates -H "X-Device-Key: $DEVICE_KEY" \
  -H "Content-Type: application/json" -d '{"name":"Candidato A","office":"PRESIDENT"}'
# Repita para B, C y D. Para GOVERNOR: añada "stateName"; para MAYOR: "stateName" y "municipalityName".

# Votante de prueba (usa X-Admin-Key). El UID es el de la tarjeta de prueba; el slot, el de la huella.
curl -s -X POST http://127.0.0.1:8000/api/v1/voters -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fullName":"Votante Prueba","cardUid":"04A1B2C3","fingerprintSlot":1,"stateName":"Ciudad de México","municipalityName":"Cuauhtémoc"}'
```

> **Importante.** El sistema exige **tres cargos** por voto (presidente, gobernador y alcalde): para que un votante pueda votar tiene que haber al menos un candidato de cada cargo en **su** estado y municipio. Los estados y municipios se normalizan a MAYÚSCULAS sin acentos.

Para descubrir el UID real de su tarjeta, hágala leer por la ESP32 NFC en el paso 9 y use el UID que registra el sistema (los rechazos aparecerán como «Acceso rechazado» en el dashboard).

## 8. Compilar y cargar las dos ESP32

En el Arduino IDE (o `arduino-cli`) con el *core* ESP32 instalado. Librerías: **Adafruit PN532**, **Adafruit Fingerprint Sensor Library** y **ArduinoJson versión 6** (el firmware usa `StaticJsonDocument`).

**ESP32 NFC** (`firmware/nfc_esp32/`):
1. Copie `secrets.h.example` a `secrets.h` y complete: `WIFI_SSID`, `WIFI_PASSWORD`, `NFC_DEVICE_ID`, `NFC_HMAC_KEY_HEX` (la **misma** que `NFC_HMAC_KEY` del `.env`) y `NTP_SERVER`.
2. Seleccione su placa, compile y cargue. Abra el monitor serie (solo diagnóstico).
3. Anote la IP que imprime y póngala como reserva DHCP; úsela en `NFC_ESP32_URL`.

**ESP32 de huellas** (`firmware/fingerprint_esp32/`):
1. `secrets.h`: WiFi, `API_BASE_URL` = `http://IP_WIFI_DE_LA_PI:8000` (**no** `127.0.0.1`), `FINGERPRINT_DEVICE_ID`, `FINGERPRINT_HMAC_KEY_HEX` (la misma que `FINGERPRINT_HMAC_KEY`), `NTP_SERVER`.
2. Compile y cargue.

Ambas necesitan **NTP** (acceso a `pool.ntp.org` o el servidor que ponga en `NTP_SERVER`); sin hora válida rechazan las órdenes por expiración.

**Comprobación en el dashboard.** Con el backend corriendo y la ESP32 de huellas encendida, en **Inicio → Estado del sistema** la tarjeta «Lector de huellas» debe pasar a **En línea** en unos segundos: la ESP32 consulta periódicamente `GET /api/v1/device/fingerprint-command/pending` y el dashboard lo toma como latido. Si sigue «Sin conexión»: IP/URL de la Pi, firewall, hora NTP o clave HMAC distinta.

## 9. Enrolar huella y rostro del votante de prueba

1. **Huella.** Con el menú local de la ESP32 de huellas (monitor serie) enrole la huella en el **slot 1** (el mismo `fingerprintSlot` que cargó en el paso 7).
2. **Rostro.** Con `ADMIN_KEY` y el key ring configurados, en la Pi:
   ```bash
   python enroll_face.py     # elija explícitamente al votante; el embedding se cifra con AES-256-GCM
   ```
3. Compruebe que el votante figura con rostro: `curl -s -H "X-Admin-Key: $ADMIN_KEY" http://127.0.0.1:8000/api/v1/voters` (`hasFace: true`).

## 10. Arrancar la interfaz de la urna

En la sesión gráfica de la Pi, en otro proceso con el mismo entorno:

```bash
cd /opt/votacion && source .venv/bin/activate
set -a; source .env; set +a
python -m kiosk_ui.main --fullscreen --inactivity 120
```

(`--show-exit` solo para desarrollo; F11 alterna pantalla completa, Esc la abandona, Ctrl+Q cierra.)

**Latido de la urna para el dashboard.** En modo real, `kiosk_ui` envía `POST /api/v1/device/heartbeat` al iniciar y cada 15 segundos con la configuración predeterminada. Usa `API_BASE_URL` y `DEVICE_KEY`. La cámara se comprueba consultando las capacidades V4L2 del nodo `/dev/videoN` indicado por `CAMERA_INDEX`.

Para el RFID, cargue el sketch NFC actualizado que corresponda a su red (`nfc_esp32` o `nfc_esp32_Tec`). Desde la Pi, `curl -i "${NFC_ESP32_URL%/}/v1/nfc/health"` debe devolver `200` cuando el PN532 responde y el reloj del ESP32 está sincronizado. `503` indica que el lector aún no está listo y `404` indica que el firmware no ofrece la consulta de estado. Las lecturas de tarjeta siguen disponibles con el firmware anterior.

## 11. Prueba de extremo a extremo

Con el dashboard abierto en la laptop (Resultados en tiempo real y Estado del sistema) y la urna en pantalla completa:

| # | Acción | Resultado esperado | Dónde verlo |
|---|---|---|---|
| 1 | Acercar la tarjeta registrada | Se inicia sesión; LED de tarjeta | Registros: «Acceso autorizado» |
| 2 | Poner la huella del slot 1 | Huella verificada; LED de huella | Registros: «Huella verificada» |
| 3 | Mirar a la cámara | Rostro verificado; LED de rostro | Registros: «Rostro verificado» |
| 4 | Elegir candidatos y **ENVIAR VOTO** | Pantalla de éxito | Registros: «Voto registrado»; Resultados y participación suben en ≤ 5 s |
| 5 | Repetir con la misma tarjeta | Rechazado (ya votó) | Registros: «Acceso rechazado» |
| 6 | Tarjeta no registrada | Rechazado | «Acceso rechazado» |
| 7 | Huella de otra persona / rostro distinto | Rechazado | «Huella rechazada» / «Rostro rechazado» |

**Verificación contra la base (importante).** Compare el dashboard con una consulta SQL directa en Neon (consola SQL de Neon):

```sql
select count(*) as votos from ballot;
select count(*) filter (where "hasVoted") as votaron, count(*) as padron from voter;
select c.name, count(b.id) as votos
from candidate c left join ballot b on b."candidateId" = c.id
group by c.name order by c.id;
```

Los números deben coincidir con el dashboard (Votos emitidos, Total de votantes y el porcentaje de cada candidato). Los nombres de columna pueden variar según cómo SQLModel los cree; compruebe con `\d voter` y `\d ballot`.

**Privacidad.** Revise que `ballot` contiene solo `candidateId` (sin votante ni sesión) y que `dashboardevent` no guarda tarjeta, votante ni candidato.

## 12. Solución de problemas

| Síntoma | Causa probable y qué hacer |
|---|---|
| Backend no arranca: error de conexión a la BD | Cadena `DATABASE_URL` mal copiada, falta `+psycopg`, sin salida al puerto 5432, o Neon despertando. Repita la comprobación de la sección 2. |
| `ModuleNotFoundError: psycopg2` | Use el prefijo `postgresql+psycopg://`. |
| `/dashboard/` da 404 | Falta copiar `dashboard/dist` (sección 5) o `DASHBOARD_DIST` apunta mal. |
| Login del dashboard responde 503 | `ADMIN_KEY` vacía en el entorno del backend. |
| Login responde 429 | Bloqueo tras 5 intentos; espere 5 min o reinicie el backend. |
| «Lector de huellas» sigue «Sin conexión» | ESP32 sin WiFi/NTP, `API_BASE_URL` con la IP equivocada o `127.0.0.1`, puerto 8000 bloqueado por el firewall, o `FINGERPRINT_HMAC_KEY` distinta entre firmware y `.env`. Revise el monitor serie. |
| La urna no lee tarjetas | `NFC_ESP32_URL` incorrecta (cambió la IP por DHCP), clave `NFC_HMAC_KEY` distinta, o sin NTP en la ESP32. |
| Cámara sin imagen | `CAMERA_INDEX` incorrecto, usuario sin grupo `video`, cámara CSI no expuesta como V4L2. |
| «Aún no hay datos» pese a haber votado | El votante no tiene candidatos de los tres cargos en su región, o el voto no llegó al backend; mire el log de uvicorn. |
| Cámara/RFID/Urna en «Sin datos» | Compruebe que `kiosk_ui` esté abierto en modo real, que `API_BASE_URL` y `DEVICE_KEY` coincidan con el backend y que la ESP32 NFC tenga el sketch actualizado (sección 10). |
| Tras reiniciar una ESP32 rechaza órdenes | Secuencia/nonce: no reinicie contadores a mano; si cambió de base o de backend, use una base/clave nueva (ver `docs/RASPBERRY_PI.md` §4). |
| Fechas/horas desfasadas en el dashboard | `DASHBOARD_TIMEZONE` o reloj de la Pi sin NTP. |

## 13. Servicios y red para operar (resumen)

- **Backend** como servicio `systemd`: `WorkingDirectory=/opt/votacion`, `EnvironmentFile=/opt/votacion/.env`, `ExecStart=/opt/votacion/.venv/bin/uvicorn backend:app --host 0.0.0.0 --port 8000`, `Restart=on-failure`.
- **Interfaz** dentro de la sesión gráfica del usuario de casilla (no como servicio sin `DISPLAY`).
- **Firewall:** puerto 8000 solo desde la subred de la casilla; salida a Neon solo por TLS. El dashboard comparte ese puerto, así que el equipo del administrador debe estar en esa subred (o usar un proxy HTTPS; en ese caso ponga `DASHBOARD_COOKIE_SECURE=true`).
- Un solo proceso de uvicorn (el bloqueo de login y la revocación de sesiones viven en memoria).

## 14. Después de la prueba

1. Complete la lista de **pruebas físicas pendientes** de `docs/PRUEBAS.md` (tarjetas de 4/7/10 bytes, dedo retenido, reconexión WiFi, reloj incorrecto, reinicio de ESP32/Pi, cámara con mala luz y varias personas, apagado durante cada fase, doble voto concurrente contra Neon).
2. Vacíe o elimine la rama de staging de Neon cuando termine; no deje datos de prueba junto a datos reales.
3. Anote los resultados reales en `docs/PRUEBAS.md`; hoy solo documenta pruebas simuladas.
