# Dashboard web — manual del desarrollador

Panel de administración de la urna IoT: resultados en tiempo real, participación, estado de los equipos, bitácora técnica y reportes. Decisiones y motivos: `docs/DASHBOARD_DECISIONES.md`.

## 1. Arquitectura

```mermaid
flowchart LR
    ADM[Navegador del administrador] -->|cookie HttpOnly, /api/v1/admin/*, polling 5 s| API
    ADM -->|HTML/JS estáticos| STATIC[/dashboard/ → dashboard/dist]
    subgraph PI[Raspberry Pi · FastAPI backend.py]
        API[dashboard_api.py<br/>install_dashboard]
        MW[middleware: bitácora anónima]
        STATIC
    end
    KIOSK[kiosk_ui] -->|POST /api/v1/device/heartbeat<br/>X-Device-Key| API
    KIOSK -->|flujo de voto existente| MW
    FP[ESP32 huellas] -->|HMAC existente| MW
    API <--> DB[(SQLite / Neon)]
    MW --> DB
```

- **Backend:** `dashboard_api.py` es un módulo **aditivo**; `backend.py` solo lo instala con `install_dashboard(app, BackendBindings(...))` (10 líneas al final).
- **Frontend:** `dashboard/` (React 18 + Vite 5 + TypeScript). Se compila a `dashboard/dist` y FastAPI lo sirve en `/dashboard/`. Mismo origen → la cookie de sesión funciona sin CORS.
- **Seguridad:** `DEVICE_KEY` y `ADMIN_KEY` nunca llegan al navegador. La bitácora no contiene identidad ni selecciones.

## 2. Estructura

```
dashboard_api.py                 API admin (login, métricas, bitácora, heartbeat, CSV, estáticos)
tests/test_dashboard.py          15 pruebas de la API (SQLite temporal, datos ficticios)
scripts/seed_dashboard_demo.py   Datos ficticios + simulador de heartbeat
dashboard/
  src/
    api.ts                       Cliente HTTP (cookie, cabecera CSRF, manejo de 401)
    types.ts                     Contratos de la API
    App.tsx                      Sesión, metadatos y enrutado por hash
    hooks/usePolling.ts          Consulta periódica con datos previos y pausa en segundo plano
    pages/                       Overview (Estado del sistema) · Results · Reports · Placeholder
    components/                  Shell, Login, Donut, LineChart, BarList, MexicoMap, Avatar, Bits, Icons
    lib/                         format (es-MX, zona horaria) · states (mapa, alias) · palette
    assets/mexico-states.json    Mapa generado (no editar a mano)
    styles.css                   Tokens de diseño (colores del diseño) y estilos
  scripts/build_map.py           Regenera el mapa desde el GeoJSON
```

## 3. Puesta en marcha rápida (sin hardware)

```bash
# 1) Backend (desde la raíz del repo)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # en un equipo sin cámara basta: fastapi uvicorn sqlmodel psycopg pydantic requests cryptography numpy httpx
export DATABASE_URL=sqlite:///demo.db DEVICE_KEY=demo-device-key ADMIN_KEY=demo-admin-key
python scripts/seed_dashboard_demo.py --reset          # votantes, votos y eventos ficticios
uvicorn backend:app --port 8000

# 2) Frontend en modo desarrollo (otra terminal)
cd dashboard && npm ci && npm run dev                  # http://localhost:5173/dashboard/
#   /api se reenvía a http://127.0.0.1:8000 (VITE_API_TARGET para cambiarlo)

# 3) (opcional) Simular la urna viva: Cámara/RFID/Urna «En línea»
python scripts/seed_dashboard_demo.py --heartbeat http://127.0.0.1:8000
```

Inicie sesión con `ADMIN_KEY` (`demo-admin-key` en el ejemplo). El *seed* se niega a escribir en una base que no sea SQLite.

## 4. Variables de entorno (backend)

| Variable | Defecto | Uso |
|---|---|---|
| `ADMIN_KEY` | — (obligatoria) | Clave de inicio de sesión. Sin ella el login responde 503. |
| `DEVICE_KEY` | — | Ya existente; autentica el heartbeat de la urna. |
| `DASHBOARD_SESSION_SECRET` | derivada de `ADMIN_KEY` | Secreto de firma de la cookie. |
| `DASHBOARD_SESSION_TTL_SECONDS` | `28800` | Duración de la sesión. |
| `DASHBOARD_COOKIE_SECURE` | `false` | `true` si se sirve por HTTPS. |
| `DASHBOARD_HEARTBEAT_TTL_SECONDS` | `45` | Tras este tiempo sin latido la urna figura «Sin conexión». |
| `DASHBOARD_BOOTH_LABEL` | `Urna 01` | Nombre mostrado en la bitácora. |
| `DASHBOARD_ELECTION_TITLE` | `Votación Electrónica 2026` | Título de la barra superior. |
| `DASHBOARD_TIMEZONE` | `America/Mexico_City` | Zona para fechas, rangos y serie horaria. En Windows instale `tzdata`. |
| `DASHBOARD_EVENT_RETENTION_DAYS` | `30` | Purga horaria de eventos antiguos. |
| `DASHBOARD_LOGIN_MAX_FAILURES` / `_LOCK_SECONDS` | `5` / `300` | Bloqueo por IP. |
| `DASHBOARD_DIST` | `dashboard/dist` | Carpeta del frontend compilado. |

## 5. Referencia de la API

Prefijo `/api/v1/admin`. Todo excepto `login` y `me` exige la cookie `dashboard_session` (401 si falta o expiró). `login` y `logout` exigen `X-Requested-With: dashboard`. Respuestas con `Cache-Control: no-store`.

| Método y ruta | Parámetros | Devuelve |
|---|---|---|
| `POST /login` | `{password}` | Fija cookie; `{authenticated, role, expiresAt}`. 401 clave incorrecta · 429 bloqueo (`Retry-After`) |
| `POST /logout` | — | Revoca la sesión |
| `GET /me` | — | `{authenticated, role}` (siempre 200) |
| `GET /meta` | — | `{title, timezone, offices[], states[], pollSeconds, serverTime}` |
| `GET /results` | `office`, `state` | `{asOf, totalVotes, candidates[{candidateId,name,office,stateName,municipalityName,votes,percent,regionTotal}]}` |
| `GET /participation` | — | `{registered, voted, pending, participation, untrackedVotes, byState[{state,registered,voted,participation}]}` |
| `GET /timeline` | `from`, `to` (`YYYY-MM-DD` o ISO), `bucket=auto\|hour\|day` | `{bucket, registered, points[{timestamp,label,votes,cumulativeVotes,cumulativePercent}]}` |
| `GET /system` | — | `{overall, components[{id,label,status,lastSeen,latencyMs?}]}`; `status`: `online\|offline\|unknown` |
| `GET /events` | `limit≤200`, `from`, `to`, `kind` | `{events[{id,timestamp,kind,event,device,status,statusLabel}]}` |
| `GET /analytics` | `from`, `to` | `{status: NORMAL\|PRECAUCIÓN\|ALERTA, auditFlags[], byKind[]}` |
| `GET /export/{results\|participation\|events}.csv` | `from`, `to` (solo `events`) | CSV UTF-8 con BOM |
| `POST /api/v1/device/heartbeat` | Cabecera `X-Device-Key`; `{components:{nfc?,camera?: online\|offline}}` | `{status, serverTime}` |

Componentes de `/system`: `kiosk`, `camera`, `nfc`, `fingerprint`, `database`, `network`.

## 6. Cómo extender el frontend

**Nueva vista.** 1) Cree `src/pages/MiVista.tsx`. 2) Añádala a `NAV` en `components/Shell.tsx` y a la lista de rutas en `App.tsx`. 3) Consulte datos con `usePolling`:

```tsx
const { data, error, loading, updatedAt } = usePolling((signal) => api.system(signal), pollMs);
```

`usePolling(fetcher, ms, deps)` reintenta cada `ms`, vuelve a consultar al cambiar `deps`, conserva `data` si hay un error (`<StaleNotice>` lo avisa) y se pausa si la pestaña está oculta.

**Nuevo endpoint.** Declare el tipo en `types.ts`, el método en `api.ts` (`request<T>` ya añade cookie y cabecera CSRF y vuelve al login ante 401) y la ruta en `dashboard_api.py` con `@protected.get(...)` (hereda la verificación de sesión).

**Estilos.** Colores y medidas están en variables CSS al inicio de `styles.css` (`--navy-900`, `--blue-600`, …).

**Mapa.** `lib/states.ts` convierte los nombres de la base (MAYÚSCULAS sin acentos) al identificador del mapa y maneja alias (`ESTADO DE MEXICO` → `MEXICO`). Si aparece una entidad gris cuando hay datos, agregue su alias ahí.

## 7. Pruebas y verificación

```bash
python -m unittest tests.test_dashboard -v     # API (15 pruebas)
cd dashboard && npm run typecheck && npm test  # tipos y utilidades
npm run build                                  # produce dashboard/dist
```

La suite de la API comprueba: CSRF y cookie HttpOnly/Strict, clave de dispositivo que no abre el panel, revocación y token alterado, bloqueo tras fallos, porcentajes por región, bitácora sin identidad, heartbeat, CSV a prueba de fórmulas y cabeceras de seguridad.

## 8. Despliegue en la Raspberry Pi

1. Compile en su equipo (`npm ci && npm run build`) y copie `dashboard/dist/` a la Pi, o instale Node ≥ 20 allí.
2. Configure `ADMIN_KEY` (larga y aleatoria) y, si hay HTTPS, `DASHBOARD_COOKIE_SECURE=true`.
3. Inicie `uvicorn backend:app --host 0.0.0.0 --port 8000` (un solo proceso). Abra `http://IP-DE-LA-PI:8000/dashboard/`.
4. Restrinja el acceso al puerto 8000 (firewall/VLAN); el panel comparte puerto con la API de la urna. Detrás de un proxy use `--proxy-headers` para que el bloqueo por IP use la IP real.
5. El inicio del backend crea `dashboardevent` y `deviceheartbeat`; no modifica ninguna tabla existente.

## 9. Integrar el heartbeat en la urna (pendiente en `kiosk_ui`)

Sin latidos la urna, la cámara y el RFID figuran «Sin datos». Enviar cada ≤ 15 s (TTL 45 s) desde un hilo de la urna:

```python
import requests, threading, time

def heartbeat_loop(api_base: str, device_key: str, nfc_ok, camera_ok):
    while True:
        try:
            requests.post(f"{api_base}/api/v1/device/heartbeat", headers={"X-Device-Key": device_key},
                          json={"components": {"nfc": "online" if nfc_ok() else "offline",
                                               "camera": "online" if camera_ok() else "offline"}},
                          timeout=5)
        except requests.RequestException:
            pass  # el panel lo interpretará como «Sin conexión» al vencer el TTL
        time.sleep(15)

threading.Thread(target=heartbeat_loop, args=(API_BASE_URL, DEVICE_KEY, nfc_ok, camera_ok), daemon=True).start()
```

`nfc_ok`/`camera_ok` son funciones que devuelven `True/False` según la última comprobación real de cada dispositivo.

## 10. Privacidad y reglas que no deben romperse

- No añada a `DashboardEvent` ni a ninguna respuesta del panel: sesión, votante, UID de tarjeta, huella, rostro o candidato elegido.
- Los votos siguen anónimos; el panel solo cuenta `Ballot.candidateId`.
- No exponga `X-Device-Key`/`X-Admin-Key` al navegador ni guarde la clave en `localStorage`.
- No cargue scripts/fuentes de CDNs: la CSP (`default-src 'self'`) los bloquearía y la urna puede estar sin internet.

## 11. Solución de problemas

| Síntoma | Causa probable |
|---|---|
| `/dashboard/` da 404 y el log dice «No existe …/dist» | Falta `npm run build` o `DASHBOARD_DIST` apunta mal. |
| Login responde 503 | `ADMIN_KEY` vacía en el entorno del backend. |
| Login responde 429 | Bloqueo por 5 fallos; espere `Retry-After` o reinicie el backend. |
| Vuelve al login solo | La cookie expiró (8 h) o se rotó `ADMIN_KEY`. |
| Registros recientes vacíos | No hay actividad aún; busque «No se pudo registrar el evento técnico» en el log. |
| Cámara/RFID «Sin datos» | La urna no envía heartbeat (§9). |
| Lector de huellas «Sin conexión» | La ESP32 no ha consultado órdenes en 45 s. |
| Entidad gris en el mapa con datos | Alias faltante en `lib/states.ts`. |
| Con HTTPS la sesión no persiste | Falta `DASHBOARD_COOKIE_SECURE=true`, o hay proxy que cambia el esquema. |
