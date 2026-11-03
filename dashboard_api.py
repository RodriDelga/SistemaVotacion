# Description: API administrativa del dashboard web. Modulo aditivo: no modifica tablas ni rutas
# existentes. Aporta login de administrador, resultados, participacion, estado del sistema,
# bitacora tecnica sin identidad, heartbeat del kiosco y exportacion CSV.
# Integracion: dos lineas al final de backend.py (ver docs/DASHBOARD_MANUAL.md).
"""Dashboard web de la urna IoT.

Principios (ver docs/DASHBOARD_DECISIONES.md):

* Aditivo: solo crea las tablas ``dashboardevent`` y ``deviceheartbeat``.
* Privacidad: la bitacora guarda tipo, dispositivo, estado y hora. Nunca sesion,
  votante, tarjeta, huella, rostro ni candidato elegido.
* Las claves ``X-Device-Key`` y ``X-Admin-Key`` nunca llegan al navegador: el
  administrador inicia sesion con ``ADMIN_KEY`` y recibe una cookie HttpOnly.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydanticField, NaiveDatetime
from sqlalchemy import case, delete, func, text
from sqlmodel import Field, Session, SQLModel, col, select

log = logging.getLogger("dashboard")

COOKIE_NAME = "dashboard_session"
ADMIN_PREFIX = "/api/v1/admin"
OFFICES = {
    "PRESIDENT": "Presidente de México",
    "GOVERNOR": "Gobernador",
    "MAYOR": "Presidente Municipal",
}
EVENT_LABELS = {
    "access": ("Acceso autorizado", "Acceso rechazado"),
    "fingerprint": ("Huella verificada", "Huella rechazada"),
    "face": ("Rostro verificado", "Rostro rechazado"),
    "vote": ("Voto registrado", "Voto rechazado"),
    "cancel": ("Sesión cancelada", "Cancelación rechazada"),
}
STATUS_LABELS = {"ok": "Exitoso", "rejected": "Rechazado", "error": "Error"}
CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# --------------------------------------------------------------------------- tablas
class DashboardEvent(SQLModel, table=True):
    """Evento tecnico anonimo. Sin sesion, votante, tarjeta ni seleccion."""

    id: Optional[int] = Field(default=None, primary_key=True)
    createdAt: NaiveDatetime = Field(index=True)  # UTC sin zona; sqlmodel>=0.0.4x rechaza datetime ingenuo sin esta anotacion
    kind: str = Field(index=True)  # access | fingerprint | face | vote | cancel
    device: str
    status: str  # ok | rejected | error


class DeviceHeartbeat(SQLModel, table=True):
    """Ultimo estado reportado por componente (kiosk, nfc, camera)."""

    component: str = Field(primary_key=True)
    status: str
    reportedAt: NaiveDatetime


# ---------------------------------------------------------------------- configuracion
@dataclass(frozen=True)
class BackendBindings:
    """Objetos de backend.py que se inyectan para evitar importaciones circulares."""

    engine: Any
    verify_device_key: Callable
    device_key: str
    Voter: Any
    Candidate: Any
    Ballot: Any
    DeviceReplayGuard: Any
    fingerprint_device_id: str
    normalize_region: Callable[[str], str]


def _local_timezone() -> tzinfo:
    name = os.getenv("DASHBOARD_TIMEZONE", "America/Mexico_City")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # tzdata ausente (p. ej. Windows sin el paquete tzdata)
        log.warning("Zona horaria %s no disponible; se usa UTC-6 fijo.", name)
        return timezone(timedelta(hours=-6))


@dataclass(frozen=True)
class DashboardConfig:
    admin_key: str
    session_secret: bytes
    session_ttl: int
    cookie_secure: bool
    heartbeat_ttl: int
    booth_label: str
    election_title: str
    event_retention_days: int
    max_failures: int
    lock_seconds: int
    tz: tzinfo

    @staticmethod
    def from_env() -> "DashboardConfig":
        admin_key = os.getenv("ADMIN_KEY", "")
        explicit = os.getenv("DASHBOARD_SESSION_SECRET", "")
        if explicit:
            secret = hashlib.sha256(explicit.encode("utf-8")).digest()
        else:  # derivada: rotar ADMIN_KEY invalida todas las sesiones
            secret = hmac.new(admin_key.encode("utf-8"), b"dashboard-session-key-v1", hashlib.sha256).digest()
        truthy = {"1", "true", "si", "yes", "on"}
        return DashboardConfig(
            admin_key=admin_key,
            session_secret=secret,
            session_ttl=int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "28800")),
            cookie_secure=os.getenv("DASHBOARD_COOKIE_SECURE", "false").strip().lower() in truthy,
            heartbeat_ttl=int(os.getenv("DASHBOARD_HEARTBEAT_TTL_SECONDS", "45")),
            booth_label=os.getenv("DASHBOARD_BOOTH_LABEL", "Urna 01"),
            election_title=os.getenv("DASHBOARD_ELECTION_TITLE", "Votación Electrónica 2026"),
            event_retention_days=int(os.getenv("DASHBOARD_EVENT_RETENTION_DAYS", "30")),
            max_failures=int(os.getenv("DASHBOARD_LOGIN_MAX_FAILURES", "5")),
            lock_seconds=int(os.getenv("DASHBOARD_LOGIN_LOCK_SECONDS", "300")),
            tz=_local_timezone(),
        )


# ----------------------------------------------------------------------- utilidades
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_naive_utc(value: datetime) -> datetime:
    """La base guarda UTC sin zona; los filtros usan el mismo formato en SQLite y PostgreSQL."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def to_aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_range_bound(raw: Optional[str], tz: tzinfo, end_of_day: bool) -> Optional[datetime]:
    """Acepta YYYY-MM-DD (dia local) o ISO 8601; devuelve UTC sin zona."""
    if not raw:
        return None
    try:
        if len(raw) == 10:
            day = date.fromisoformat(raw)
            local = datetime(day.year, day.month, day.day, tzinfo=tz)
            if end_of_day:
                local += timedelta(days=1)
            return to_naive_utc(local)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Fecha inválida; use YYYY-MM-DD o ISO 8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return to_naive_utc(parsed)


def csv_safe(value: Any) -> Any:
    """Neutraliza inyeccion de formulas al abrir el CSV en Excel/Sheets."""
    if isinstance(value, str) and value.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + value
    return value


# ------------------------------------------------------------------- sesion y login
class SessionSigner:
    """Token sin estado: ``v1.<exp>.<nonce>.<hmac>``. La revocacion vive en memoria."""

    def __init__(self, secret: bytes, ttl: int) -> None:
        self._secret = secret
        self._ttl = ttl
        self._revoked: dict[str, int] = {}
        self._lock = threading.Lock()

    def _sign(self, expires: int, nonce: str) -> str:
        message = f"dashboard-session-v1\n{expires}\n{nonce}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def issue(self) -> tuple[str, int]:
        expires = int(time.time()) + self._ttl
        nonce = secrets.token_hex(12)
        return f"v1.{expires}.{nonce}.{self._sign(expires, nonce)}", expires

    def verify(self, token: Optional[str]) -> bool:
        if not token:
            return False
        parts = token.split(".")
        if len(parts) != 4 or parts[0] != "v1":
            return False
        try:
            expires = int(parts[1])
        except ValueError:
            return False
        if expires < int(time.time()):
            return False
        if not hmac.compare_digest(parts[3], self._sign(expires, parts[2])):
            return False
        with self._lock:
            return parts[2] not in self._revoked

    def revoke(self, token: Optional[str]) -> None:
        if not token or not self.verify(token):
            return
        _, expires, nonce, _ = token.split(".")
        now = int(time.time())
        with self._lock:
            self._revoked = {key: exp for key, exp in self._revoked.items() if exp >= now}
            self._revoked[nonce] = int(expires)


class LoginThrottle:
    """Bloqueo por IP tras N fallos consecutivos."""

    def __init__(self, max_failures: int, lock_seconds: int) -> None:
        self._max = max_failures
        self._lock_seconds = lock_seconds
        self._state: dict[str, tuple[int, float]] = {}
        self._mutex = threading.Lock()

    def remaining_lock(self, key: str) -> int:
        with self._mutex:
            failures, locked_until = self._state.get(key, (0, 0.0))
            return max(0, int(locked_until - time.time()))

    def register_failure(self, key: str) -> None:
        with self._mutex:
            failures, locked_until = self._state.get(key, (0, 0.0))
            if locked_until and locked_until < time.time():
                failures, locked_until = 0, 0.0
            failures += 1
            if failures >= self._max:
                locked_until = time.time() + self._lock_seconds
                failures = 0
            self._state[key] = (failures, locked_until)

    def register_success(self, key: str) -> None:
        with self._mutex:
            self._state.pop(key, None)


class LoginRequest(BaseModel):
    password: str = PydanticField(min_length=1, max_length=256)


class HeartbeatRequest(BaseModel):
    components: dict[Literal["nfc", "camera"], Literal["online", "offline"]] = PydanticField(default_factory=dict)


# ------------------------------------------------------------------- instalacion
def install_dashboard(app: FastAPI, bindings: BackendBindings, config: Optional[DashboardConfig] = None) -> None:
    cfg = config or DashboardConfig.from_env()
    b = bindings
    signer = SessionSigner(cfg.session_secret, cfg.session_ttl)
    throttle = LoginThrottle(cfg.max_failures, cfg.lock_seconds)
    SQLModel.metadata.create_all(b.engine, tables=[DashboardEvent.__table__, DeviceHeartbeat.__table__])

    def get_db():
        with Session(b.engine) as db:
            yield db

    # ---- dependencias de seguridad
    def require_admin(request: Request) -> None:
        if not signer.verify(request.cookies.get(COOKIE_NAME)):
            raise HTTPException(status_code=401, detail="Sesión no válida o expirada")

    def require_csrf_header(request: Request) -> None:
        # Defensa en profundidad junto a SameSite=Strict: un formulario cruzado no puede fijar esta cabecera.
        if request.headers.get("X-Requested-With") != "dashboard":
            raise HTTPException(status_code=403, detail="Cabecera de solicitud ausente")

    admin = APIRouter(prefix=ADMIN_PREFIX)
    protected = APIRouter(prefix=ADMIN_PREFIX, dependencies=[Depends(require_admin)])
    device = APIRouter(prefix="/api/v1/device")

    # ============================================================== autenticacion
    @admin.post("/login", dependencies=[Depends(require_csrf_header)])
    def login(body: LoginRequest, request: Request, response: Response):
        if not cfg.admin_key:
            raise HTTPException(status_code=503, detail="ADMIN_KEY no está configurada en el servidor")
        client = request.client.host if request.client else "unknown"
        wait = throttle.remaining_lock(client)
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Demasiados intentos. Reintente en {wait} s",
                                headers={"Retry-After": str(wait)})
        if not secrets.compare_digest(body.password.encode("utf-8"), cfg.admin_key.encode("utf-8")):
            throttle.register_failure(client)
            raise HTTPException(status_code=401, detail="Credencial incorrecta")
        throttle.register_success(client)
        token, expires = signer.issue()
        response.set_cookie(
            COOKIE_NAME, token, max_age=cfg.session_ttl, httponly=True, samesite="strict",
            secure=cfg.cookie_secure, path=ADMIN_PREFIX,
        )
        return {"authenticated": True, "role": "Administrador", "expiresAt": expires}

    @admin.post("/logout", dependencies=[Depends(require_csrf_header)])
    def logout(request: Request, response: Response):
        signer.revoke(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path=ADMIN_PREFIX)
        return {"authenticated": False}

    @admin.get("/me")
    def me(request: Request):
        # Responde 200 siempre para que el SPA decida sin generar errores en consola.
        ok = signer.verify(request.cookies.get(COOKIE_NAME))
        return {"authenticated": ok, "role": "Administrador" if ok else None}

    # ================================================================== metadatos
    @protected.get("/meta")
    def meta(db: Session = Depends(get_db)):
        voter_states = db.exec(select(b.Voter.stateName).distinct()).all()
        candidate_states = db.exec(select(b.Candidate.stateName).where(col(b.Candidate.stateName).is_not(None)).distinct()).all()
        states = sorted({s for s in [*voter_states, *candidate_states] if s})
        return {
            "title": cfg.election_title,
            "timezone": str(cfg.tz),
            "offices": [{"code": code, "label": label} for code, label in OFFICES.items()],
            "states": states,
            "pollSeconds": 5,
            "serverTime": utc_now().isoformat(),
        }

    # ================================================================== resultados
    def candidate_rows(db: Session, office: Optional[str], state: Optional[str]):
        Candidate, Ballot = b.Candidate, b.Ballot
        query = (
            select(Candidate.id, Candidate.name, Candidate.office, Candidate.stateName,
                   Candidate.municipalityName, func.count(Ballot.id))
            .join(Ballot, Ballot.candidateId == Candidate.id, isouter=True)
            .group_by(Candidate.id, Candidate.name, Candidate.office, Candidate.stateName, Candidate.municipalityName)
            .order_by(col(Candidate.id))
        )
        if office:
            code = office.upper()
            if code not in OFFICES:
                raise HTTPException(status_code=422, detail="Cargo desconocido")
            query = query.where(Candidate.office == code)
        if state:
            query = query.where(Candidate.stateName == b.normalize_region(state))
        return db.exec(query).all()

    def build_results(db: Session, office: Optional[str], state: Optional[str]) -> dict:
        rows = candidate_rows(db, office, state)
        # El porcentaje se calcula dentro de cada region (cargo + estado + municipio):
        # mezclar candidatos de regiones distintas daria porcentajes sin sentido.
        group_totals: dict[tuple, int] = {}
        for _, _, row_office, row_state, row_muni, votes in rows:
            key = (row_office, row_state, row_muni)
            group_totals[key] = group_totals.get(key, 0) + votes
        candidates = []
        for candidate_id, name, row_office, row_state, row_muni, votes in rows:
            total = group_totals[(row_office, row_state, row_muni)]
            candidates.append({
                "candidateId": candidate_id, "name": name, "office": row_office,
                "stateName": row_state, "municipalityName": row_muni, "votes": votes,
                "percent": round(votes / total * 100, 2) if total else 0.0,
                "regionTotal": total,
            })
        return {
            "asOf": utc_now().isoformat(),
            "office": office.upper() if office else None,
            "state": b.normalize_region(state) if state else None,
            "totalVotes": sum(group_totals.values()),
            "candidates": candidates,
        }

    @protected.get("/results")
    def results(office: Optional[str] = None, state: Optional[str] = None, db: Session = Depends(get_db)):
        return build_results(db, office, state)

    # ================================================================ participacion
    def build_participation(db: Session) -> dict:
        Voter = b.Voter
        voted_expr = func.sum(case((col(Voter.hasVoted).is_(True), 1), else_=0))
        rows = db.exec(select(Voter.stateName, func.count(Voter.id), voted_expr).group_by(Voter.stateName)
                       .order_by(Voter.stateName)).all()
        by_state = []
        registered = voted = 0
        for state_name, reg, vot in rows:
            vot = int(vot or 0)
            registered += reg
            voted += vot
            by_state.append({
                "state": state_name, "registered": reg, "voted": vot,
                "participation": round(vot / reg * 100, 2) if reg else 0.0,
            })
        total_events = db.exec(select(func.count(DashboardEvent.id)).where(
            DashboardEvent.kind == "vote", DashboardEvent.status == "ok")).one()
        return {
            "asOf": utc_now().isoformat(),
            "registered": registered, "voted": voted, "pending": registered - voted,
            "participation": round(voted / registered * 100, 2) if registered else 0.0,
            # votos anteriores a la instalacion de la bitacora: no aparecen en la serie horaria
            "untrackedVotes": max(0, voted - total_events),
            "byState": by_state,
        }

    @protected.get("/participation")
    def participation(db: Session = Depends(get_db)):
        return build_participation(db)

    @protected.get("/timeline")
    def timeline(date_from: Optional[str] = Query(default=None, alias="from"),
                 date_to: Optional[str] = Query(default=None, alias="to"),
                 bucket: Literal["auto", "hour", "day"] = "auto",
                 db: Session = Depends(get_db)):
        start = parse_range_bound(date_from, cfg.tz, end_of_day=False)
        end = parse_range_bound(date_to, cfg.tz, end_of_day=True)
        registered = db.exec(select(func.count(b.Voter.id))).one()
        query = select(DashboardEvent.createdAt).where(DashboardEvent.kind == "vote", DashboardEvent.status == "ok")
        stamps = [to_aware_utc(item) for item in db.exec(query.order_by(DashboardEvent.createdAt)).all()]
        if not stamps:
            return {"bucket": "hour", "registered": registered, "points": []}
        start_aware = to_aware_utc(start) if start else stamps[0]
        end_aware = to_aware_utc(end) if end else utc_now()
        if end_aware <= start_aware:
            raise HTTPException(status_code=422, detail="El rango de fechas es inválido")
        span_hours = (end_aware - start_aware).total_seconds() / 3600
        step = "day" if bucket == "day" or (bucket == "auto" and span_hours > 48) else "hour"

        def floor(moment: datetime) -> datetime:
            local = moment.astimezone(cfg.tz)
            local = local.replace(minute=0, second=0, microsecond=0)
            return local.replace(hour=0) if step == "day" else local

        delta = timedelta(days=1) if step == "day" else timedelta(hours=1)
        cumulative = sum(1 for stamp in stamps if stamp < start_aware)
        counts: dict[datetime, int] = {}
        for stamp in stamps:
            if start_aware <= stamp < end_aware:
                key = floor(stamp)
                counts[key] = counts.get(key, 0) + 1
        points = []
        cursor = floor(start_aware)
        last = floor(min(end_aware, utc_now()))
        guard = 0
        while cursor <= last and guard < 800:
            votes = counts.get(cursor, 0)
            cumulative += votes
            points.append({
                "timestamp": cursor.isoformat(),
                "label": cursor.strftime("%d/%m") if step == "day" else cursor.strftime("%H:%M"),
                "votes": votes, "cumulativeVotes": cumulative,
                "cumulativePercent": round(cumulative / registered * 100, 2) if registered else 0.0,
            })
            cursor = (cursor + delta).astimezone(cfg.tz)
            guard += 1
        return {"bucket": step, "registered": registered, "points": points}

    # =============================================================== estado del sistema
    def fresh(reported_at: Optional[datetime]) -> bool:
        return reported_at is not None and (utc_now() - to_aware_utc(reported_at)).total_seconds() <= cfg.heartbeat_ttl

    def build_system(db: Session) -> dict:
        beats = {row.component: row for row in db.exec(select(DeviceHeartbeat)).all()}
        kiosk = beats.get("kiosk")
        kiosk_fresh = fresh(kiosk.reportedAt if kiosk else None)

        def from_beat(component: str) -> tuple[str, Optional[datetime]]:
            row = beats.get(component)
            if row is None:
                return "unknown", None
            if not kiosk_fresh:  # sin kiosco vivo el dato esta obsoleto
                return "unknown", to_aware_utc(row.reportedAt)
            return row.status, to_aware_utc(row.reportedAt)

        started = time.perf_counter()
        try:
            db.exec(text("SELECT 1"))
            db_status, db_ms = "online", round((time.perf_counter() - started) * 1000, 1)
        except Exception:
            db_status, db_ms = "offline", None

        guard = db.get(b.DeviceReplayGuard, b.fingerprint_device_id)
        fp_seen = to_aware_utc(guard.updatedAt) if guard else None
        fp_status = "unknown" if guard is None else ("online" if fresh(fp_seen) else "offline")
        nfc_status, nfc_seen = from_beat("nfc")
        cam_status, cam_seen = from_beat("camera")
        if kiosk is None:
            kiosk_status = "unknown"
        else:
            kiosk_status = "online" if kiosk_fresh else "offline"
        # "Red": hay comunicacion si alguno de los equipos que hablan con el servidor esta vivo.
        if kiosk_fresh or fp_status == "online":
            net_status = "online"
        elif kiosk is None and guard is None:
            net_status = "unknown"
        else:
            net_status = "offline"
        components = [
            {"id": "kiosk", "label": "Urna electrónica", "status": kiosk_status,
             "lastSeen": to_aware_utc(kiosk.reportedAt).isoformat() if kiosk else None},
            {"id": "camera", "label": "Cámara", "status": cam_status, "lastSeen": cam_seen.isoformat() if cam_seen else None},
            {"id": "nfc", "label": "Lector RFID", "status": nfc_status, "lastSeen": nfc_seen.isoformat() if nfc_seen else None},
            {"id": "fingerprint", "label": "Lector de huellas", "status": fp_status, "lastSeen": fp_seen.isoformat() if fp_seen else None},
            {"id": "database", "label": "Base de datos", "status": db_status, "latencyMs": db_ms,
             "lastSeen": utc_now().isoformat()},
            {"id": "network", "label": "Red", "status": net_status, "lastSeen": None},
        ]
        statuses = {item["status"] for item in components}
        overall = "offline" if "offline" in statuses else ("unknown" if "unknown" in statuses else "online")
        return {"asOf": utc_now().isoformat(), "overall": overall, "heartbeatTtlSeconds": cfg.heartbeat_ttl,
                "components": components}

    @protected.get("/system")
    def system(db: Session = Depends(get_db)):
        return build_system(db)

    # =================================================================== bitacora
    def event_payload(row: DashboardEvent) -> dict:
        ok_label, bad_label = EVENT_LABELS.get(row.kind, (row.kind, row.kind))
        local = to_aware_utc(row.createdAt).astimezone(cfg.tz)
        return {
            "id": row.id, "timestamp": local.isoformat(), "kind": row.kind,
            "event": ok_label if row.status == "ok" else bad_label,
            "device": row.device, "status": row.status, "statusLabel": STATUS_LABELS.get(row.status, row.status),
        }

    def events_query(start: Optional[datetime], end: Optional[datetime], kind: Optional[str]):
        query = select(DashboardEvent)
        if start:
            query = query.where(DashboardEvent.createdAt >= start)
        if end:
            query = query.where(DashboardEvent.createdAt < end)
        if kind:
            if kind not in EVENT_LABELS:
                raise HTTPException(status_code=422, detail="Tipo de evento desconocido")
            query = query.where(DashboardEvent.kind == kind)
        return query.order_by(col(DashboardEvent.createdAt).desc(), col(DashboardEvent.id).desc())

    @protected.get("/events")
    def events(limit: int = Query(default=20, ge=1, le=200),
               date_from: Optional[str] = Query(default=None, alias="from"),
               date_to: Optional[str] = Query(default=None, alias="to"),
               kind: Optional[str] = None, db: Session = Depends(get_db)):
        start = parse_range_bound(date_from, cfg.tz, False)
        end = parse_range_bound(date_to, cfg.tz, True)
        rows = db.exec(events_query(start, end, kind).limit(limit)).all()
        return {"asOf": utc_now().isoformat(), "events": [event_payload(row) for row in rows]}

    # ================================================================== analiticas
    @protected.get("/analytics")
    def analytics(date_from: Optional[str] = Query(default=None, alias="from"),
                  date_to: Optional[str] = Query(default=None, alias="to"), db: Session = Depends(get_db)):
        start = parse_range_bound(date_from, cfg.tz, False)
        end = parse_range_bound(date_to, cfg.tz, True)
        query = select(DashboardEvent.kind, DashboardEvent.status, func.count(DashboardEvent.id)).group_by(
            DashboardEvent.kind, DashboardEvent.status)
        if start:
            query = query.where(DashboardEvent.createdAt >= start)
        if end:
            query = query.where(DashboardEvent.createdAt < end)
        table: dict[str, dict[str, int]] = {kind: {"ok": 0, "rejected": 0, "error": 0} for kind in EVENT_LABELS}
        for kind, status, count in db.exec(query).all():
            table.setdefault(kind, {"ok": 0, "rejected": 0, "error": 0})[status] = count
        summary = []
        flags: list[str] = []
        level = "NORMAL"
        for kind, counts in table.items():
            total = sum(counts.values())
            failed = counts["rejected"] + counts["error"]
            rate = round(failed / total, 4) if total else 0.0
            summary.append({"kind": kind, "label": EVENT_LABELS[kind][0].split()[0], "ok": counts["ok"],
                            "rejected": counts["rejected"], "error": counts["error"], "total": total, "failureRate": rate})
            name = EVENT_LABELS[kind][0].split()[0].lower()
            if kind in {"fingerprint", "face"} and total >= 5 and rate > 0.30:
                level = "ALERTA"
                flags.append(f"Tasa de rechazo alta en {name} (>30%).")
            # Un conteo absoluto crece solo con el volumen de votos: se exige ademas una tasa relevante.
            if failed >= 10 and rate > 0.10:
                level = "PRECAUCIÓN" if level != "ALERTA" else level
                flags.append(f"Más de 10 rechazos y tasa superior al 10% en {name}.")
        return {"asOf": utc_now().isoformat(), "status": level, "auditFlags": flags, "byKind": summary}

    # =================================================================== exportacion
    def csv_response(name: str, header: list[str], rows: list[list[Any]]) -> Response:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        for row in rows:
            writer.writerow([csv_safe(cell) for cell in row])
        payload = "﻿" + buffer.getvalue()  # BOM: Excel abre UTF-8 correctamente
        return Response(content=payload.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @protected.get("/export/{dataset}.csv")
    def export(dataset: Literal["results", "participation", "events"],
               date_from: Optional[str] = Query(default=None, alias="from"),
               date_to: Optional[str] = Query(default=None, alias="to"),
               db: Session = Depends(get_db)):
        stamp = datetime.now(cfg.tz).strftime("%Y%m%d-%H%M")
        if dataset == "results":
            data = build_results(db, None, None)
            rows = [[c["office"], c["stateName"] or "", c["municipalityName"] or "", c["name"], c["votes"], c["percent"]]
                    for c in data["candidates"]]
            return csv_response(f"resultados-{stamp}.csv", ["Cargo", "Estado", "Municipio", "Candidato", "Votos", "Porcentaje"], rows)
        if dataset == "participation":
            data = build_participation(db)
            rows = [[s["state"], s["registered"], s["voted"], s["participation"]] for s in data["byState"]]
            return csv_response(f"participacion-{stamp}.csv", ["Estado", "Registrados", "Votaron", "Participación %"], rows)
        start = parse_range_bound(date_from, cfg.tz, False)
        end = parse_range_bound(date_to, cfg.tz, True)
        rows = [[e["timestamp"], e["event"], e["device"], e["statusLabel"]]
                for e in map(event_payload, db.exec(events_query(start, end, None).limit(5000)).all())]
        return csv_response(f"eventos-{stamp}.csv", ["Fecha/Hora", "Evento", "Dispositivo", "Estado"], rows)

    # =================================================================== heartbeat
    @device.post("/heartbeat", dependencies=[Depends(b.verify_device_key)])
    def heartbeat(body: HeartbeatRequest, db: Session = Depends(get_db)):
        now = utc_now()
        reported = {"kiosk": "online", **body.components}
        for component, status in reported.items():
            db.merge(DeviceHeartbeat(component=component, status=status, reportedAt=to_naive_utc(now)))
        db.commit()
        return {"status": "ok", "serverTime": now.isoformat()}

    app.include_router(admin)
    app.include_router(protected)
    app.include_router(device)

    # ============================================================ middleware de eventos
    event_rules: list[tuple[re.Pattern, str]] = [
        (re.compile(r"^/api/v1/session/start$"), "access"),
        (re.compile(r"^/api/v1/session/[^/]+/fingerprint$"), "fingerprint"),
        (re.compile(r"^/api/v1/session/[^/]+/face$"), "face"),
        (re.compile(r"^/api/v1/session/[^/]+/vote$"), "vote"),
        (re.compile(r"^/api/v1/session/[^/]+/cancel$"), "cancel"),
    ]
    prune_state = {"last": 0.0}
    prune_lock = threading.Lock()

    def classify(request: Request) -> Optional[str]:
        if request.method != "POST":
            return None
        for pattern, kind in event_rules:
            if pattern.match(request.url.path):
                return kind
        return None

    def is_authenticated_source(request: Request, kind: str) -> bool:
        """Solo se registran peticiones autenticadas; evita que ruido externo llene la bitacora."""
        if kind == "fingerprint":
            return hasattr(request.state, "fingerprint_device")
        supplied = request.headers.get("X-Device-Key", "")
        return bool(b.device_key) and secrets.compare_digest(supplied.encode("utf-8"), b.device_key.encode("utf-8"))

    def store_event(kind: str, status_code: int) -> None:
        status = "ok" if status_code < 400 else ("error" if status_code >= 500 else "rejected")
        device_name = "Lector de huellas" if kind == "fingerprint" else cfg.booth_label
        with Session(b.engine) as db:
            db.add(DashboardEvent(createdAt=to_naive_utc(utc_now()), kind=kind, device=device_name, status=status))
            db.commit()
            with prune_lock:
                due = time.time() - prune_state["last"] > 3600
                prune_state["last"] = time.time() if due else prune_state["last"]
            if due:
                cutoff = to_naive_utc(utc_now() - timedelta(days=cfg.event_retention_days))
                db.exec(delete(DashboardEvent).where(DashboardEvent.createdAt < cutoff))
                db.commit()

    @app.middleware("http")
    async def dashboard_middleware(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        try:
            kind = classify(request)
            if kind and is_authenticated_source(request, kind):
                await run_in_threadpool(store_event, kind, response.status_code)
        except Exception:  # la bitacora jamas debe afectar el flujo de votacion
            log.exception("No se pudo registrar el evento tecnico")
        if path.startswith(ADMIN_PREFIX) or path.startswith("/dashboard"):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        if path.startswith(ADMIN_PREFIX):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ================================================================ archivos estaticos
    dist = Path(os.getenv("DASHBOARD_DIST", str(Path(__file__).resolve().parent / "dashboard" / "dist")))
    if dist.is_dir():
        app.mount("/dashboard", StaticFiles(directory=dist, html=True), name="dashboard")
        log.info("Dashboard servido en /dashboard desde %s", dist)
    else:
        log.warning("No existe %s; compile el frontend (npm run build en dashboard/).", dist)
