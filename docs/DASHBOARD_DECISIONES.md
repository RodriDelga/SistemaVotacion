# Dashboard web — registro de decisiones

Formato: contexto → decisión → alternativas → consecuencias. «Quién» indica si la decisión la tomó el responsable del proyecto o si es una elección técnica del desarrollo que queda **abierta a revisión**.

## A. Decisiones confirmadas por el responsable del proyecto

### D-01 · Adoptar `dashboard_api.py` y auditarlo
- **Contexto.** El espacio de trabajo ya contenía un `dashboard_api.py` sin commit y 10 líneas añadidas al final de `backend.py` (módulo aditivo con login admin, resultados, participación, sistema, bitácora, heartbeat y CSV).
- **Decisión.** Se adopta como la capa de API del dashboard. Se auditó y se cubrió con `tests/test_dashboard.py` (15 pruebas).
- **Alternativas.** Reescribirlo desde cero; usar solo los endpoints ya commiteados con `X-Device-Key`.
- **Consecuencias.** El navegador nunca recibe `DEVICE_KEY` ni `ADMIN_KEY`; el contrato de la API es el de `docs/DASHBOARD_MANUAL.md §5`. Correcciones hechas en la auditoría: ver D-20 y D-21.
- **Quién.** Responsable del proyecto.

### D-02 · Frontend con React + Vite + TypeScript
- **Decisión.** SPA estática en `dashboard/`, compilada a `dashboard/dist` y servida por FastAPI en `/dashboard` (ruta ya prevista por `dashboard_api.py`).
- **Alternativas.** HTML/JS sin build; Vue + Vite.
- **Consecuencias.** Requiere Node ≥ 20 solo para **compilar**; en la Raspberry Pi basta con copiar `dist/`. Dependencias de ejecución mínimas: `react`, `react-dom` y la fuente Inter (autoalojada).
- **Quién.** Responsable del proyecto.

### D-03 · Tiempo real por *polling* cada 5 s
- **Decisión.** Cada vista consulta periódicamente (`pollSeconds` lo entrega `/meta`, hoy 5 s). Sin SSE ni WebSocket.
- **Consecuencias.** Sin estado de conexión en el servidor y compatible con proxies; latencia máxima ≈ 5 s. El *hook* `usePolling` pausa con la pestaña oculta, conserva los últimos datos buenos y muestra «No se pudo actualizar» si falla la red. Migrar a SSE solo requeriría reemplazar ese hook.
- **Quién.** Responsable del proyecto.

### D-04 · Mapa SVG local (sin servicios en línea)
- **Decisión.** `scripts/build_map.py` convierte un GeoJSON de las 32 entidades en rutas SVG (`src/assets/mexico-states.json`, 89 KB). El mapa se pinta con SVG propio.
- **Consecuencias.** Funciona con la urna sin internet. El GeoJSON de origen (`mexicoHigh.json`, repositorio `angelnmara/geojson`) se guarda en `dashboard/scripts/` junto con el script; **conviene verificar su licencia/atribución** antes de una publicación oficial (la geometría proviene de datos públicos de INEGI, pero la licencia del repositorio no se verificó).
- **Quién.** Responsable del proyecto.

## B. Decisiones heredadas de `dashboard_api.py` (auditadas; no confirmadas una a una)

| ID | Decisión | Motivo / consecuencia |
|---|---|---|
| D-10 | Login del administrador con `ADMIN_KEY` → cookie **HttpOnly**, `SameSite=Strict`, token HMAC sin estado (TTL 8 h, `DASHBOARD_SESSION_TTL_SECONDS`) | La clave jamás vive en JS ni en `localStorage`. Rotar `ADMIN_KEY` invalida todas las sesiones. |
| D-11 | `X-Requested-With: dashboard` obligatorio en `login`/`logout` | Defensa CSRF adicional a `SameSite`. |
| D-12 | Bloqueo por IP tras 5 fallos durante 300 s (en memoria) | Frena fuerza bruta. Con varios *workers* de uvicorn cada proceso lleva su cuenta; detrás de un proxy hay que pasar la IP real (`--proxy-headers`). |
| D-13 | Tablas aditivas `dashboardevent` y `deviceheartbeat`; no se tocan tablas existentes | Migración segura (`create_all`). |
| D-14 | Bitácora **anónima**: solo tipo, dispositivo, estado y hora; nunca sesión, votante, tarjeta ni candidato | Mantiene la separación voto/votante de `docs/ARQUITECTURA.md`. |
| D-15 | Eventos capturados por *middleware* de las peticiones autenticadas ya existentes (acceso, huella, rostro, voto, cancelación) | No se modifica el flujo de votación; un fallo al registrar se traga y se loguea. |
| D-16 | Estado de cámara y RFID por *heartbeat* de la urna (`POST /api/v1/device/heartbeat`, TTL 45 s); huellas por el último latido firmado de la ESP32; base de datos con `SELECT 1` | Si la urna no late, cámara/RFID aparecen «Sin datos» en vez de mentir «En línea». |
| D-17 | Exportación CSV con BOM UTF-8 y neutralización de fórmulas (`=`, `+`, `-`, `@`) | Excel abre bien los acentos y no ejecuta inyección de fórmulas. |
| D-18 | Cabeceras de seguridad (CSP `default-src 'self'`, `X-Frame-Options: DENY`, `no-store` en `/api/v1/admin`) | Por eso no hay CDNs ni fuentes externas (D-34). |
| D-19 | Porcentaje de cada candidato calculado **dentro de su región** (cargo + estado + municipio) | Mezclar regiones daría porcentajes sin sentido. |

## C. Correcciones aplicadas en la auditoría

### D-20 · `NaiveDatetime` en las tablas del dashboard
`DashboardEvent.createdAt` y `DeviceHeartbeat.reportedAt` guardan UTC sin zona. Con `sqlmodel` reciente el INSERT fallaba (`Datetime values must have timezone information`) y el *middleware* lo ocultaba: **la bitácora quedaba vacía sin ningún error visible**. Se anotaron como `NaiveDatetime`. Cubierto por `test_events_are_recorded_without_identity`.

### D-21 · Regla de auditoría «PRECAUCIÓN» basada en tasa, no solo en conteo
La regla original disparaba con ≥ 10 rechazos acumulados. En una jornada real con miles de votos eso ocurre siempre y la alerta quedaba permanente (ruido). Ahora exige además tasa de fallo > 10 %. Los nombres de los eventos aparecen en español. La regla «ALERTA» (huella/rostro, ≥ 5 intentos y > 30 % de fallo) no cambió. **Umbrales sujetos a validación del responsable.**

## D. Decisiones de diseño/implementación del desarrollo (abiertas a revisión)

| ID | Decisión | Motivo |
|---|---|---|
| D-30 | **Alcance de pantallas.** La imagen contiene tres pantallas de administración: *Resultados en tiempo real*, *Estado del sistema* y *Reportes y analíticas*. Se implementan esas tres más una pantalla de **inicio de sesión** (no está en el diseño; el API exige autenticación). Eso da las «4 pantallas». | La instrucción habla de las «últimas 4», pero solo tres son del panel admin. **Confirmar** si se esperaba otra. |
| D-31 | «Inicio» = *Estado del sistema*. El diseño marca «Inicio» activo en las dos primeras pantallas; se asignó a Estado del sistema porque ahí viven los registros recientes. | Evita dos ítems apuntando a lo mismo. |
| D-32 | «Participación», «Dispositivo» y «Configuración» aparecen en la barra lateral (como en el diseño) pero muestran un aviso de «fuera de alcance». | No hay diseño ni API para ellas; no se inventaron. |
| D-33 | Seis tarjetas de estado en lugar de cinco: se añade **Lector de huellas** (hardware real del sistema, `docs/ARQUITECTURA.md`). | El diseño omite el sensor R307/AS608. |
| D-34 | Sin librería de gráficas: línea, dona, barras y mapa en SVG propio. Fuente Inter autoalojada (`@fontsource-variable/inter`). | CSP estricta, uso sin internet y bundle de ~90 KB gzip. |
| D-35 | Enrutado por *hash* (`#/resultados`) sin `react-router`. | FastAPI sirve estáticos sin reglas de *fallback*; evita 404 al recargar. |
| D-36 | Mapa: color por **participación** de la entidad (leyenda >70 / 50–70 / 30–50 / <30 % del diseño). «Votos por entidad federativa» = voto de la entidad ÷ votos totales, sobre el padrón por estado de `/participation`. | `Candidate.stateName` solo existe para gobernador/alcalde; la presidencial no tiene estado y el voto es anónimo. |
| D-37 | Selector de **cargo** y **entidad** en Resultados (el diseño solo muestra *Presidente de México*). Gobernador y alcalde exigen entidad; se agrupa por municipio. | El backend soporta los tres cargos; sin filtro los porcentajes mezclarían regiones. |
| D-38 | Colores de candidato por orden (azul, rojo, naranja, morado… del diseño) y silueta genérica como foto. | La API no entrega fotos ni colores de partido; el voto no debe sugerir preferencias por apariencia. |
| D-39 | Reportes: rango por defecto = **hoy**; la serie horaria recorta el tramo inicial sin votos (el diseño arranca a las 8:00). Cuatro pestañas (Participación, Resultados, Dispositivos, Votos por área); el diseño solo muestra la primera, las otras se construyeron con los datos disponibles. | Sin horario oficial de jornada en el sistema. |
| D-40 | Sin modo oscuro ni internacionalización (solo es-MX). | Fuera de alcance del diseño. |

## E. Pendientes y límites conocidos

1. **La urna (`kiosk_ui`) aún no envía el *heartbeat*.** Hasta integrarlo, Cámara/RFID/Urna aparecen «Sin datos». Fragmento listo en `DASHBOARD_MANUAL.md §9`. `scripts/seed_dashboard_demo.py --heartbeat` lo simula.
2. **Una elección implícita** (límite heredado, `docs/INSPECCION.md`). No hay historial por elección.
3. **Revocación de sesión y bloqueo de login en memoria**: se pierden al reiniciar y no se comparten entre *workers*. Aceptable con un solo proceso uvicorn (configuración de la Pi).
4. **El panel admin comparte puerto con la API de la urna** (`0.0.0.0:8000`). Restringir por firewall/VLAN o publicar detrás de un proxy HTTPS (y poner `DASHBOARD_COOKIE_SECURE=true`).
5. **Pruebas previas fallidas, no causadas por el dashboard:** `tests/test_backend.py` (3 pruebas) falla con FastAPI reciente por devolver 422 al enviar JSON sin `Content-Type: application/json` desde el cliente de pruebas; el firmware sí envía la cabecera. `tests/test_real_adapters.py` no importa sin `customtkinter`/`opencv`. Corregir el cliente de pruebas queda fuera de esta tarea.
6. El repositorio versiona `__pycache__/*.pyc` y `README.md` menciona un `.env.example` que no existe. Se añadió `.gitignore`; no se eliminaron archivos ya versionados.
7. Sin pruebas con la Raspberry Pi ni con Neon: validado con SQLite temporal y datos sintéticos.
