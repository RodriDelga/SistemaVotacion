# Description: Backend FastAPI del sistema de votacion electronica. Coordina tarjeta y huella,
# administra ordenes para la ESP32 y registra votos anonimos de prueba.
# Student ID: A00000000
# Date: 2026-10-25

import base64
import binascii
import io
import json
import os
import re
import secrets
import unicodedata
import uuid
import time
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from common.hmac_protocol import (
    face_attestation_signature, fingerprint_request_signature,
    fingerprint_response_signature, load_hex_key, nfc_response_signature, signature_matches,
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
DEVICE_KEY = os.getenv("DEVICE_KEY", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
REQUIRE_FACE = os.getenv("REQUIRE_FACE", "true").strip().lower() in {"1", "true", "si", "yes", "on"}
MAX_FACE_ATTEMPTS = int(os.getenv("MAX_FACE_ATTEMPTS", "5"))
SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "300"))
FINGERPRINT_COMMAND_TIMEOUT_SECONDS = int(os.getenv("FINGERPRINT_COMMAND_TIMEOUT_SECONDS", "60"))
MAX_FINGERPRINT_ATTEMPTS = 5
OFFICE_PRESIDENT = "PRESIDENT"
OFFICE_GOVERNOR = "GOVERNOR"
OFFICE_MAYOR = "MAYOR"
OFFICE_ORDER = [OFFICE_MAYOR, OFFICE_GOVERNOR, OFFICE_PRESIDENT]
FINGERPRINT_DEVICE_ID = os.getenv("FINGERPRINT_DEVICE_ID", "fingerprint-esp32-01")
DEVICE_MAX_SKEW_SECONDS = int(os.getenv("DEVICE_MAX_SKEW_SECONDS", "120"))

DEFAULT_KIOSK_DEVICE_ID = os.getenv("KIOSK_DEVICE_ID", "kiosk-01")
INCIDENT_PHOTO_RETENTION_DAYS = max(1, int(os.getenv("INCIDENT_PHOTO_RETENTION_DAYS", "30")))
MAX_PHOTO_BYTES = 2 * 1024 * 1024
NFC_DEVICE_ID = os.getenv("NFC_DEVICE_ID", "nfc-esp32-01")


class Voter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    fullName: str
    cardUid: str = Field(index=True, unique=True)
    fingerprintSlot: int = Field(unique=True)
    faceEmbedding: str
    stateName: str = Field(index=True)
    municipalityName: str = Field(index=True)
    hasVoted: bool = False
    isEnabled: bool = True


class Candidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    party: Optional[str] = Field(default=None)
    office: str = Field(index=True)
    stateName: Optional[str] = Field(default=None, index=True)
    municipalityName: Optional[str] = Field(default=None, index=True)


class VoteSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    voterId: int = Field(foreign_key="voter.id")
    cardOk: bool = True
    fingerprintOk: bool = False
    faceOk: bool = False
    faceAttempts: int = 0
    faceChallenge: Optional[str] = None
    isClosed: bool = False
    createdAt: datetime


class FingerprintCommand(SQLModel, table=True):
    """Orden de lectura vinculada a una unica sesion y procesable una sola vez."""

    id: str = Field(primary_key=True)
    sessionId: str = Field(foreign_key="votesession.id", index=True)
    status: str = Field(default="pending", index=True)  # pending/completed/cancelled/expired
    result: Optional[str] = None  # matched/failed
    fingerprintSlot: Optional[int] = None
    createdAt: datetime
    completedAt: Optional[datetime] = None


class DeviceReplayGuard(SQLModel, table=True):
    """Secuencia persistente por dispositivo; una reiniciada no reabre comandos."""

    deviceId: str = Field(primary_key=True)
    lastSequence: int = 0
    updatedAt: datetime


class DeviceNonce(SQLModel, table=True):
    """Nonce de un solo uso persistido junto con la secuencia."""

    deviceId: str = Field(primary_key=True)
    nonce: str = Field(primary_key=True)
    createdAt: datetime


class Ballot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    candidateId: int = Field(foreign_key="candidate.id")


class AdminCard(SQLModel, table=True):
    """Tarjetas NFC de administradores autorizados para desbloquear la urna."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cardUid: str = Field(index=True, unique=True)
    adminName: str = Field(default="Administrador")
    isEnabled: bool = Field(default=True)
    createdAt: datetime
    updatedAt: Optional[datetime] = None


class KioskLock(SQLModel, table=True):
    """Estado global y persistente de bloqueo del Kiosk."""
    deviceId: str = Field(primary_key=True)
    isLocked: bool = Field(default=False)
    lockedAt: Optional[datetime] = None
    reason: Optional[str] = None
    lockedByAttemptType: Optional[str] = None  # FINGERPRINT / FACE / MANUAL
    incidentId: Optional[str] = None
    unlockedAt: Optional[datetime] = None
    unlockedByCardUid: Optional[str] = None


class SecurityIncident(SQLModel, table=True):
    """Registro de incidente de seguridad con referencia protegida a fotografia."""
    id: str = Field(primary_key=True)
    deviceId: str = Field(index=True)
    timestamp: datetime
    authType: str  # FINGERPRINT / FACE / GENERAL
    eventType: str  # MAX_ATTEMPTS_EXCEEDED / SECURITY_ALERT
    userRef: Optional[str] = None
    photoPath: Optional[str] = None
    status: str = Field(default="OPEN")
    details: Optional[str] = None


class IncidentPhoto(SQLModel, table=True):
    incidentId: str = Field(primary_key=True, foreign_key="securityincident.id")
    jpeg: bytes
    capturedAt: datetime = Field(index=True)


class KioskUnlockAudit(SQLModel, table=True):
    incidentId: str = Field(primary_key=True, foreign_key="securityincident.id")
    adminCardId: int
    scanNonce: str
    adminName: str
    unlockedAt: datetime


class LockKioskRequest(BaseModel):
    reason: str = PydanticField(default="Bloqueo por seguridad", max_length=500)


class NfcScanProof(BaseModel):
    deviceId: str
    sessionId: str
    nonce: str = PydanticField(min_length=16, max_length=128)
    sequence: int = PydanticField(gt=0, le=2**63-1)
    expiresAt: int
    status: Literal["ok"]
    uid: str = PydanticField(pattern=r"^[0-9A-F]{8,20}$")
    hmac: str = PydanticField(pattern=r"^[0-9a-fA-F]{64}$")


class UnlockKioskRequest(BaseModel):
    scan: NfcScanProof


class AdminCardEnrollRequest(BaseModel):
    cardUid: str = PydanticField(min_length=1, max_length=100)
    adminName: str = PydanticField(default="Administrador", min_length=1, max_length=200)
    isEnabled: bool = True


class IncidentReportRequest(BaseModel):
    id: uuid.UUID
    photoBase64: Optional[str] = PydanticField(default=None, max_length=4 * ((MAX_PHOTO_BYTES + 2) // 3))
    captureFailed: bool = False


class EnrollVoterRequest(BaseModel):
    fullName: str = PydanticField(min_length=1, max_length=200)
    cardUid: str = PydanticField(min_length=1, max_length=100)
    fingerprintSlot: int = PydanticField(gt=0)
    faceEmbedding: Optional[str] = PydanticField(default=None, max_length=8192)
    stateName: str = PydanticField(min_length=1, max_length=100)
    municipalityName: str = PydanticField(min_length=1, max_length=100)


class FaceEnrollmentRequest(BaseModel):
    faceEmbedding: str = PydanticField(min_length=1, max_length=8192)
    confirmReplacement: bool = False


class FaceVerificationRequest(BaseModel):
    challenge: str = PydanticField(min_length=32, max_length=100)
    matched: bool
    voterId: Optional[int] = None
    attestation: str = PydanticField(min_length=64, max_length=64)


class CandidateRequest(BaseModel):
    name: str
    party: Optional[str] = None
    office: Literal["PRESIDENT", "GOVERNOR", "MAYOR"]
    stateName: Optional[str] = None
    municipalityName: Optional[str] = None


class StartSessionRequest(BaseModel):
    cardUid: str


class FingerprintRequest(BaseModel):
    commandId: str
    fingerprintSlot: int


class VoteRequest(BaseModel):
    presidentId: int
    governorId: int
    mayorId: int


def createDatabaseEngine():
    engineArguments = {"pool_pre_ping": True}
    if DATABASE_URL.startswith("sqlite"):
        engineArguments["connect_args"] = {"check_same_thread": False}
    else:
        engineArguments["connect_args"] = {"sslmode": os.getenv("DB_SSLMODE", "require"), "connect_timeout": 10}
        engineArguments["pool_timeout"] = 10
    return create_engine(DATABASE_URL, **engineArguments)


engine = createDatabaseEngine()
SQLModel.metadata.create_all(engine)
print("DB en uso:", engine.url.render_as_string(hide_password=True))
app = FastAPI(title="API de votacion electronica")


@app.exception_handler(HTTPException)
async def httpExceptionHandler(request: Request, exc: HTTPException):
    if hasattr(request.state, "fingerprint_device"):
        return signedDeviceResponse(request, {"detail": exc.detail}, exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


def getDbSession():
    with Session(engine) as db:
        yield db


def verifyDeviceKey(deviceKey: str = Header(default="", alias="X-Device-Key")):
    if not DEVICE_KEY or not secrets.compare_digest(deviceKey, DEVICE_KEY):
        raise HTTPException(status_code=401, detail="Credencial de dispositivo invalida")


def verifyAdminKey(adminKey: str = Header(default="", alias="X-Admin-Key")):
    if not ADMIN_KEY or not secrets.compare_digest(adminKey, ADMIN_KEY):
        raise HTTPException(status_code=401, detail="Credencial administrativa invalida")

async def verifyFingerprintDevice(request: Request, db: Session = Depends(getDbSession)):
    """Autentica a la ESP32 de huellas y consume nonce/secuencia antes de actuar."""
    headers = request.headers
    deviceId = headers.get("X-Device-Id", "")
    nonce = headers.get("X-Nonce", "")
    signature = headers.get("X-Signature", "")
    try:
        timestamp = int(headers.get("X-Timestamp", ""))
        sequence = int(headers.get("X-Sequence", ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Cabeceras de dispositivo invalidas") from exc
    if (
        not secrets.compare_digest(deviceId, FINGERPRINT_DEVICE_ID)
        or not (16 <= len(nonce) <= 128) or sequence < 1
        or abs(int(time.time()) - timestamp) > DEVICE_MAX_SKEW_SECONDS
    ):
        raise HTTPException(status_code=401, detail="Mensaje de dispositivo invalido o expirado")
    body = await request.body()
    expected = fingerprint_request_signature(
        load_hex_key("FINGERPRINT_HMAC_KEY"), request.method, request.url.path,
        body, deviceId, timestamp, nonce, sequence,
    )
    if not signature_matches(signature, expected):
        raise HTTPException(status_code=401, detail="Firma de dispositivo invalida")

    guard = db.get(DeviceReplayGuard, deviceId)
    last_sequence = guard.lastSequence if guard else 0
    print(
        f"[DIAGNOSTICO HMAC] "
        f"Secuencia recibida: {sequence} | "
        f"Ultima secuencia aceptada: {last_sequence}"
    )

    now = getUtcNow()
    if guard is None:
        db.add(DeviceReplayGuard(deviceId=deviceId, lastSequence=sequence, updatedAt=now))
    else:
        claim = update(DeviceReplayGuard).where(
            col(DeviceReplayGuard.deviceId) == deviceId,
            col(DeviceReplayGuard.lastSequence) < sequence,
        )
        claimed = db.exec(claim.values(lastSequence=sequence, updatedAt=now))
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Secuencia repetida o fuera de orden")
    if db.get(DeviceNonce, (deviceId, nonce)) is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Nonce repetido")
    db.add(DeviceNonce(deviceId=deviceId, nonce=nonce, createdAt=now))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mensaje de dispositivo repetido") from exc
    request.state.fingerprint_device = {"deviceId": deviceId, "nonce": nonce}

def signedDeviceResponse(request: Request, payload: dict, statusCode: int = 200) -> Response:
    context = request.state.fingerprint_device
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = int(time.time())
    responseNonce = secrets.token_hex(16)
    signature = fingerprint_response_signature(
        load_hex_key("FINGERPRINT_HMAC_KEY"), body, context["deviceId"], timestamp,
        context["nonce"], responseNonce,
    )
    return Response(content=body, status_code=statusCode, media_type="application/json", headers={
        "X-Device-Id": context["deviceId"], "X-Timestamp": str(timestamp),
        "X-Nonce": responseNonce, "X-Signature": signature,
    })


def getUtcNow() -> datetime:
    return datetime.now(timezone.utc)


def toUtcAware(dateValue: datetime) -> datetime:
    if dateValue.tzinfo is None:
        return dateValue.replace(tzinfo=timezone.utc)
    return dateValue


def normalizeCardUid(rawUid: str) -> str:
    cleanedUid = rawUid.upper()
    for separator in [" ", ":", "-"]:
        cleanedUid = cleanedUid.replace(separator, "")
    return cleanedUid


def normalizeRegionName(rawName: str) -> str:
    decomposedName = unicodedata.normalize("NFD", rawName)
    visibleCharacters = [character for character in decomposedName if unicodedata.category(character) != "Mn"]
    withoutAccents = "".join(visibleCharacters)
    return " ".join(withoutAccents.upper().split())


def validateEncryptedEmbedding(envelope: Optional[str]) -> None:
    """El API valida el contenedor, pero nunca descifra ni recibe la clave."""
    if not envelope:
        raise HTTPException(status_code=422, detail="Se requiere un encoding facial cifrado")
    try:
        payload = json.loads(envelope)
        if set(payload) != {"v", "kid", "nonce", "data"} or payload["v"] != 1:
            raise ValueError
        nonce = base64.b64decode(payload["nonce"], validate=True)
        ciphertext = base64.b64decode(payload["data"], validate=True)
        if not isinstance(payload["kid"], str) or not payload["kid"] or len(nonce) != 12 or len(ciphertext) != 1040:
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Encoding facial cifrado malformado") from exc


def hasEncryptedFace(voter: Voter) -> bool:
    try:
        validateEncryptedEmbedding(voter.faceEmbedding)
        return True
    except HTTPException:
        return False


def buildCandidateRegion(request: CandidateRequest):
    stateName = normalizeRegionName(request.stateName or "") or None
    municipalityName = normalizeRegionName(request.municipalityName or "") or None
    if request.office == OFFICE_PRESIDENT and (stateName or municipalityName):
        raise HTTPException(status_code=422, detail="El candidato a presidente es nacional: no lleva estado ni municipio")
    if request.office == OFFICE_GOVERNOR and (stateName is None or municipalityName):
        raise HTTPException(status_code=422, detail="El candidato a gobernador lleva estado y no municipio")
    if request.office == OFFICE_MAYOR and (stateName is None or municipalityName is None):
        raise HTTPException(status_code=422, detail="El candidato a presidente municipal lleva estado y municipio")
    return stateName, municipalityName


def candidateMatchesVoter(candidate: Candidate, voter: Voter) -> bool:
    if candidate.office == OFFICE_PRESIDENT:
        return True
    if candidate.office == OFFICE_GOVERNOR:
        return candidate.stateName == voter.stateName
    return candidate.stateName == voter.stateName and candidate.municipalityName == voter.municipalityName


def validateChosenCandidate(candidate: Optional[Candidate], office: str, voter: Voter):
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if candidate.office != office:
        raise HTTPException(status_code=422, detail="El candidato no corresponde al cargo " + office)
    if not candidateMatchesVoter(candidate, voter):
        raise HTTPException(status_code=422, detail="El candidato no pertenece a la region del votante")


def invalidatePendingFingerprintCommands(db: Session, sessionId: str, newStatus: str = "cancelled"):
    statement = update(FingerprintCommand).where(
        col(FingerprintCommand.sessionId) == sessionId,
        col(FingerprintCommand.status) == "pending",
    )
    db.exec(statement.values(status=newStatus, completedAt=getUtcNow()))


def expireFingerprintCommands(db: Session, sessionId: Optional[str] = None):
    cutoff = getUtcNow() - timedelta(seconds=FINGERPRINT_COMMAND_TIMEOUT_SECONDS)
    statement = update(FingerprintCommand).where(
        col(FingerprintCommand.status) == "pending",
        col(FingerprintCommand.createdAt) < cutoff,
    )
    if sessionId is not None:
        statement = statement.where(col(FingerprintCommand.sessionId) == sessionId)
    db.exec(statement.values(status="expired", completedAt=getUtcNow()))


def getActiveSession(db: Session, sessionId: str) -> VoteSession:
    voteSession = db.get(VoteSession, sessionId)
    if voteSession is None:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    sessionAge = getUtcNow() - toUtcAware(voteSession.createdAt)
    isExpired = sessionAge > timedelta(seconds=SESSION_TIMEOUT_SECONDS)
    if voteSession.isClosed or isExpired:
        if isExpired and not voteSession.isClosed:
            voteSession.isClosed = True
            db.add(voteSession)
        invalidatePendingFingerprintCommands(db, sessionId)
        db.commit()
        raise HTTPException(status_code=410, detail="Sesion cerrada o expirada")
    return voteSession


def getFingerprintAttemptCount(db: Session, sessionId: str) -> int:
    statement = select(func.count(FingerprintCommand.id)).where(
        col(FingerprintCommand.sessionId) == sessionId,
        col(FingerprintCommand.status) == "completed",
        col(FingerprintCommand.result) == "failed",
    )
    return int(db.exec(statement).one())


def hasPendingFingerprintCommand(db: Session, sessionId: str) -> bool:
    statement = select(FingerprintCommand).where(
        col(FingerprintCommand.sessionId) == sessionId,
        col(FingerprintCommand.status) == "pending",
    )
    commands = db.exec(statement).all()
    maxAge = timedelta(seconds=FINGERPRINT_COMMAND_TIMEOUT_SECONDS)
    now = getUtcNow()
    return any(now - toUtcAware(command.createdAt) <= maxAge for command in commands)


def kiosk_state_for_update(db: Session) -> KioskLock:
    """Serialize voting mutations and lock transitions on the configured kiosk row."""
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    row = insert(KioskLock).values(deviceId=DEFAULT_KIOSK_DEVICE_ID, isLocked=False)
    db.exec(row.on_conflict_do_update(index_elements=["deviceId"], set_={"deviceId": row.excluded.deviceId}))
    return db.get(KioskLock, DEFAULT_KIOSK_DEVICE_ID, populate_existing=True)


def is_kiosk_locked(db: Session) -> bool:
    lock = db.get(KioskLock, DEFAULT_KIOSK_DEVICE_ID)
    return bool(lock and lock.isLocked)


def require_kiosk_available(db: Session) -> None:
    if kiosk_state_for_update(db).isLocked:
        raise HTTPException(status_code=423, detail="El dispositivo Kiosk está bloqueado por seguridad")


def lock_kiosk_device(db: Session, reason: str, auth_type: str, session_id: Optional[str] = None) -> KioskLock:
    lock = kiosk_state_for_update(db)
    if lock.isLocked and lock.incidentId and db.get(SecurityIncident, lock.incidentId):
        return lock
    now = getUtcNow()
    incident = SecurityIncident(
        id=str(uuid.uuid4()), deviceId=DEFAULT_KIOSK_DEVICE_ID, timestamp=now,
        authType=auth_type, eventType="MAX_ATTEMPTS_EXCEEDED" if session_id else "SECURITY_ALERT",
        userRef=session_id, status="PHOTO_PENDING" if session_id else "OPEN", details=reason,
    )
    db.add(incident)
    lock.isLocked = True
    lock.lockedAt = now
    lock.reason = reason
    lock.lockedByAttemptType = auth_type
    lock.incidentId = incident.id
    lock.unlockedAt = None
    lock.unlockedByCardUid = None
    db.exec(update(VoteSession).where(col(VoteSession.isClosed).is_(False)).values(isClosed=True))
    db.exec(update(FingerprintCommand).where(col(FingerprintCommand.status) == "pending")
            .values(status="cancelled", completedAt=now))
    return lock


def buildSessionStatus(db: Session, voteSession: VoteSession) -> dict:
    fingerprintAttempts = getFingerprintAttemptCount(db, voteSession.id)
    fingerprintLocked = fingerprintAttempts >= MAX_FINGERPRINT_ATTEMPTS and not voteSession.fingerprintOk
    effectiveFaceOk = voteSession.faceOk or not REQUIRE_FACE
    kioskLocked = is_kiosk_locked(db)
    isReady = voteSession.cardOk and voteSession.fingerprintOk and effectiveFaceOk and not kioskLocked
    return {
        "sessionId": voteSession.id,
        "cardOk": voteSession.cardOk,
        "fingerprintOk": voteSession.fingerprintOk,
        "faceOk": effectiveFaceOk,
        "faceRequired": REQUIRE_FACE,
        "faceAttempts": voteSession.faceAttempts,
        "maxFaceAttempts": MAX_FACE_ATTEMPTS,
        "faceAttemptsRemaining": max(0, MAX_FACE_ATTEMPTS - voteSession.faceAttempts),
        "faceLocked": voteSession.faceAttempts >= MAX_FACE_ATTEMPTS and not effectiveFaceOk,
        "readyToVote": isReady,
        "fingerprintAttempts": fingerprintAttempts,
        "maxFingerprintAttempts": MAX_FINGERPRINT_ATTEMPTS,
        "fingerprintAttemptsRemaining": max(0, MAX_FINGERPRINT_ATTEMPTS - fingerprintAttempts),
        "fingerprintLocked": fingerprintLocked,
        "fingerprintCommandPending": hasPendingFingerprintCommand(db, voteSession.id),
        "kioskLocked": kioskLocked,
    }


def buildCommandResponse(db: Session, command: FingerprintCommand) -> dict:
    attempts = getFingerprintAttemptCount(db, command.sessionId)
    return {
        "commandId": command.id,
        "sessionId": command.sessionId,
        "status": command.status,
        "createdAt": toUtcAware(command.createdAt).isoformat(),
        "commandTimeoutSeconds": FINGERPRINT_COMMAND_TIMEOUT_SECONDS,
        "fingerprintAttempts": attempts,
        "maxFingerprintAttempts": MAX_FINGERPRINT_ATTEMPTS,
        "fingerprintLocked": attempts >= MAX_FINGERPRINT_ATTEMPTS,
    }


def rejectAlreadyVoted(db: Session, voteSession: VoteSession):
    voteSession.isClosed = True
    invalidatePendingFingerprintCommands(db, voteSession.id)
    db.add(voteSession)
    db.commit()
    raise HTTPException(status_code=409, detail="Este votante ya emitio su voto")


@app.post("/api/v1/voters", dependencies=[Depends(verifyAdminKey)])
def enrollVoter(request: EnrollVoterRequest, db: Session = Depends(getDbSession)):
    if request.faceEmbedding:
        validateEncryptedEmbedding(request.faceEmbedding)
    stateName = normalizeRegionName(request.stateName)
    municipalityName = normalizeRegionName(request.municipalityName)
    if stateName == "" or municipalityName == "":
        raise HTTPException(status_code=422, detail="El estado y el municipio son obligatorios")
    voter = Voter(
        fullName=request.fullName.strip(),
        cardUid=normalizeCardUid(request.cardUid),
        fingerprintSlot=request.fingerprintSlot,
        faceEmbedding=request.faceEmbedding or "",
        stateName=stateName,
        municipalityName=municipalityName,
    )
    db.add(voter)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tarjeta o huella ya registradas")
    return {"voterId": voter.id, "stateName": stateName, "municipalityName": municipalityName}


@app.get("/api/v1/voters", dependencies=[Depends(verifyAdminKey)])
def listVoters(db: Session = Depends(getDbSession)):
    voters = db.exec(select(Voter).order_by(col(Voter.id))).all()
    return [{"voterId": voter.id, "fullName": voter.fullName, "hasFace": hasEncryptedFace(voter), "hasVoted": voter.hasVoted} for voter in voters]


@app.put("/api/v1/voters/{voterId}/face", dependencies=[Depends(verifyAdminKey)])
def enrollFace(voterId: int, request: FaceEnrollmentRequest, db: Session = Depends(getDbSession)):
    validateEncryptedEmbedding(request.faceEmbedding)
    voter = db.get(Voter, voterId)
    if voter is None:
        raise HTTPException(status_code=404, detail="Votante no encontrado")
    if hasEncryptedFace(voter) and not request.confirmReplacement:
        raise HTTPException(status_code=409, detail="Ya existe un registro facial; confirme expresamente el reemplazo")
    voter.faceEmbedding = request.faceEmbedding
    db.add(voter)
    db.commit()
    return {"status": "faceEnrolled", "voterId": voter.id}


@app.post("/api/v1/candidates", dependencies=[Depends(verifyDeviceKey)])
def createCandidate(request: CandidateRequest, db: Session = Depends(getDbSession)):
    stateName, municipalityName = buildCandidateRegion(request)
    candidate = Candidate(
        name=request.name,
        party=request.party,
        office=request.office,
        stateName=stateName,
        municipalityName=municipalityName,
    )
    db.add(candidate)
    db.commit()
    return {
        "candidateId": candidate.id,
        "name": candidate.name,
        "party": candidate.party,
        "office": candidate.office,
        "stateName": candidate.stateName,
        "municipalityName": candidate.municipalityName,
    }


@app.get("/api/v1/candidates", dependencies=[Depends(verifyDeviceKey)])
def listCandidates(office: Optional[str] = None, db: Session = Depends(getDbSession)):
    query = select(Candidate).order_by(col(Candidate.id))
    if office is not None:
        query = query.where(Candidate.office == office.upper())
    candidates = db.exec(query).all()
    return [
        {
            "candidateId": candidate.id,
            "name": candidate.name,
            "party": candidate.party,
            "office": candidate.office,
            "stateName": candidate.stateName,
            "municipalityName": candidate.municipalityName,
        }
        for candidate in candidates
    ]


@app.post("/api/v1/session/start", dependencies=[Depends(verifyDeviceKey)])
def startSession(request: StartSessionRequest, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voter = db.exec(select(Voter).where(Voter.cardUid == normalizeCardUid(request.cardUid))).first()
    if voter is None:
        raise HTTPException(status_code=404, detail="Tarjeta no registrada")
    if not voter.isEnabled:
        raise HTTPException(status_code=403, detail="El votante no esta habilitado")
    if voter.hasVoted:
        raise HTTPException(status_code=403, detail="Este votante ya emitio su voto")
    voteSession = VoteSession(id=str(uuid.uuid4()), voterId=voter.id, createdAt=getUtcNow())
    db.add(voteSession)
    db.commit()
    return {"sessionId": voteSession.id, "voterName": voter.fullName}


@app.post("/api/v1/session/{sessionId}/fingerprint-command", dependencies=[Depends(verifyDeviceKey)])
def requestFingerprintCommand(sessionId: str, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voteSession = getActiveSession(db, sessionId)
    expireFingerprintCommands(db, sessionId)
    db.flush()
    sessionStatus = buildSessionStatus(db, voteSession)
    if voteSession.fingerprintOk:
        raise HTTPException(status_code=409, detail="La huella ya fue verificada")
    if sessionStatus["fingerprintLocked"]:
        raise HTTPException(status_code=409, detail="Se agotaron los cinco intentos de huella")

    pendingQuery = select(FingerprintCommand).where(
        col(FingerprintCommand.sessionId) == sessionId,
        col(FingerprintCommand.status) == "pending",
    )
    command = db.exec(pendingQuery).first()
    if command is None:
        command = FingerprintCommand(
            id=str(uuid.uuid4()),
            sessionId=sessionId,
            status="pending",
            createdAt=getUtcNow(),
        )
        db.add(command)
    db.commit()
    return buildCommandResponse(db, command)


@app.get("/api/v1/device/fingerprint-command/pending", dependencies=[Depends(verifyFingerprintDevice)])
def getPendingFingerprintCommand(request: Request, db: Session = Depends(getDbSession)):
    if kiosk_state_for_update(db).isLocked:
        return signedDeviceResponse(request, {"active": False, "command": None})
    expireFingerprintCommands(db)
    db.flush()
    query = select(FingerprintCommand).where(col(FingerprintCommand.status) == "pending")
    query = query.order_by(col(FingerprintCommand.createdAt))
    commands = db.exec(query).all()
    for command in commands:
        try:
            voteSession = getActiveSession(db, command.sessionId)
        except HTTPException as exc:
            if exc.status_code == 410:
                continue
            raise
        sessionStatus = buildSessionStatus(db, voteSession)
        if voteSession.fingerprintOk or sessionStatus["fingerprintLocked"]:
            command.status = "cancelled"
            command.completedAt = getUtcNow()
            db.add(command)
            db.flush()
            continue
        db.commit()
        return signedDeviceResponse(request, {
            "active": True,
            "commandId": command.id,
            "sessionId": command.sessionId,
            "commandTimeoutSeconds": FINGERPRINT_COMMAND_TIMEOUT_SECONDS,
        })
    db.commit()
    return signedDeviceResponse(request, {"active": False, "command": None})


@app.post("/api/v1/session/{sessionId}/fingerprint", dependencies=[Depends(verifyFingerprintDevice)])
def verifyFingerprint(sessionId: str, fingerprintRequest: FingerprintRequest,
                      request: Request, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    if fingerprintRequest.fingerprintSlot < 0:
        raise HTTPException(status_code=422, detail="fingerprintSlot no puede ser negativo")
    commandQuery = select(FingerprintCommand).where(
        col(FingerprintCommand.id) == fingerprintRequest.commandId,
        col(FingerprintCommand.sessionId) == sessionId,
    )
    command = db.exec(commandQuery).first()
    if command is None:
        raise HTTPException(status_code=404, detail="Orden de huella no encontrada para esta sesion")
    if command.status == "completed":
        raise HTTPException(status_code=409, detail="La orden ya fue procesada; no se repitio el intento")
    if command.status != "pending":
        raise HTTPException(status_code=410, detail="La orden fue cancelada o expiro")

    voteSession = getActiveSession(db, sessionId)
    sessionStatus = buildSessionStatus(db, voteSession)
    if voteSession.fingerprintOk or sessionStatus["fingerprintLocked"]:
        invalidatePendingFingerprintCommands(db, sessionId)
        db.commit()
        raise HTTPException(status_code=409, detail="La verificacion de huella ya no admite resultados")
    if getUtcNow() - toUtcAware(command.createdAt) > timedelta(seconds=FINGERPRINT_COMMAND_TIMEOUT_SECONDS):
        command.status = "expired"
        command.completedAt = getUtcNow()
        db.add(command)
        db.commit()
        raise HTTPException(status_code=410, detail="La orden de huella expiro")

    voter = db.get(Voter, voteSession.voterId)
    isMatch = fingerprintRequest.fingerprintSlot > 0 and voter.fingerprintSlot == fingerprintRequest.fingerprintSlot
    previousAttempts = getFingerprintAttemptCount(db, sessionId)
    now = getUtcNow()

    # La actualizacion condicional hace que solo una entrega de la misma orden surta efecto.
    claimQuery = update(FingerprintCommand).where(
        col(FingerprintCommand.id) == command.id,
        col(FingerprintCommand.sessionId) == sessionId,
        col(FingerprintCommand.status) == "pending",
    )
    claimResult = db.exec(claimQuery.values(
        status="completed",
        result="matched" if isMatch else "failed",
        fingerprintSlot=fingerprintRequest.fingerprintSlot,
        completedAt=now,
    ))
    if claimResult.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="La orden ya fue procesada o cancelada")

    if isMatch:
        voteSession.fingerprintOk = True
        db.add(voteSession)
        invalidatePendingFingerprintCommands(db, sessionId)
    elif previousAttempts + 1 >= MAX_FINGERPRINT_ATTEMPTS:
        lock_kiosk_device(
            db,
            reason="Se agotaron los intentos de huella dactilar",
            auth_type="FINGERPRINT", session_id=sessionId,
        )
    db.commit()

    if not isMatch:
        attempts = previousAttempts + 1
        detail = f"Huella no coincide o lectura fallida. Intento {attempts} de {MAX_FINGERPRINT_ATTEMPTS}"
        if attempts >= MAX_FINGERPRINT_ATTEMPTS:
            detail += "; verificacion bloqueada"
        raise HTTPException(status_code=401, detail=detail)
    return signedDeviceResponse(request, buildSessionStatus(db, voteSession))


@app.get("/api/v1/session/{sessionId}/face-challenge", dependencies=[Depends(verifyDeviceKey)])
def getFaceChallenge(sessionId: str, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    if not REQUIRE_FACE:
        raise HTTPException(status_code=409, detail="La verificacion facial esta deshabilitada")
    voteSession = getActiveSession(db, sessionId)
    if not voteSession.fingerprintOk:
        raise HTTPException(status_code=403, detail="Primero debe verificarse la huella")
    if voteSession.faceOk:
        raise HTTPException(status_code=409, detail="El rostro ya fue verificado")
    if voteSession.faceAttempts >= MAX_FACE_ATTEMPTS:
        raise HTTPException(status_code=409, detail="Se agotaron los intentos faciales")
    voter = db.get(Voter, voteSession.voterId)
    if not hasEncryptedFace(voter):
        raise HTTPException(status_code=409, detail="El votante requiere enrolamiento facial; los datos antiguos no se migran automaticamente")
    if not voteSession.faceChallenge:
        voteSession.faceChallenge = secrets.token_urlsafe(32)
        db.add(voteSession)
        db.commit()
    # Verificación dirigida: solo se entrega el registro cifrado del votante
    # asociado a esta sesión, nunca la colección completa de embeddings.
    records = [{"voterId": voter.id, "faceEmbedding": voter.faceEmbedding}]
    return {"challenge": voteSession.faceChallenge, "records": records}


@app.post("/api/v1/session/{sessionId}/face", dependencies=[Depends(verifyDeviceKey)])
def verifyFace(sessionId: str, request: FaceVerificationRequest, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    if not REQUIRE_FACE:
        raise HTTPException(status_code=409, detail="La verificacion facial esta deshabilitada")
    voteSession = getActiveSession(db, sessionId)
    if not voteSession.fingerprintOk:
        raise HTTPException(status_code=403, detail="Primero debe verificarse la huella")
    if voteSession.faceOk:
        return buildSessionStatus(db, voteSession)
    if not voteSession.faceChallenge or not secrets.compare_digest(request.challenge, voteSession.faceChallenge):
        raise HTTPException(status_code=409, detail="Desafio facial inexistente, vencido o ya utilizado")
    expectedAttestation = face_attestation_signature(
        load_hex_key("FACE_ATTESTATION_KEY"), sessionId, request.challenge,
        request.voterId, request.matched,
    )
    if not signature_matches(request.attestation, expectedAttestation):
        raise HTTPException(status_code=401, detail="Atestacion facial invalida")
    previousAttempts = voteSession.faceAttempts
    isValidMatch = request.matched and request.voterId == voteSession.voterId
    # Una sola respuesta por desafio, incluso si llegan solicitudes simultaneas.
    claim = update(VoteSession).where(
        col(VoteSession.id) == sessionId,
        col(VoteSession.faceChallenge) == request.challenge,
        col(VoteSession.faceOk).is_(False),
    )
    claimed = db.exec(claim.values(faceChallenge=None, faceAttempts=VoteSession.faceAttempts + (0 if isValidMatch else 1)))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El desafio facial ya fue utilizado")
    if not isValidMatch:
        attempts = previousAttempts + 1
        if attempts >= MAX_FACE_ATTEMPTS:
            lock_kiosk_device(
                db,
                reason="Se agotaron los intentos de reconocimiento facial",
                auth_type="FACE", session_id=sessionId,
            )
        db.commit()
        detail = f"Rostro no verificado. Intento {attempts} de {MAX_FACE_ATTEMPTS}"
        if attempts >= MAX_FACE_ATTEMPTS:
            detail += "; verificacion bloqueada"
        raise HTTPException(status_code=401, detail=detail)
    voteSession.faceOk = True
    db.add(voteSession)
    db.commit()
    return buildSessionStatus(db, voteSession)


@app.get("/api/v1/session/active", dependencies=[Depends(verifyDeviceKey)])
def getCurrentSession(db: Session = Depends(getDbSession)):
    if is_kiosk_locked(db):
        return {"active": False, "kioskLocked": True}
    query = select(VoteSession).where(col(VoteSession.isClosed).is_(False))
    query = query.order_by(col(VoteSession.createdAt).desc()).limit(20)
    openSessions = db.exec(query).all()
    currentTime = getUtcNow()
    maxAge = timedelta(seconds=SESSION_TIMEOUT_SECONDS)
    validSessions = [item for item in openSessions if currentTime - toUtcAware(item.createdAt) <= maxAge]
    if len(validSessions) == 0:
        return {"active": False}
    currentSession = validSessions[0]
    voter = db.get(Voter, currentSession.voterId)
    sessionStatus = buildSessionStatus(db, currentSession)
    sessionStatus["active"] = True
    sessionStatus["voterName"] = voter.fullName
    return sessionStatus


@app.get("/api/v1/session/{sessionId}", dependencies=[Depends(verifyDeviceKey)])
def getSessionStatus(sessionId: str, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voteSession = getActiveSession(db, sessionId)
    expireFingerprintCommands(db, sessionId)
    db.commit()
    return buildSessionStatus(db, voteSession)


@app.post("/api/v1/session/{sessionId}/cancel", dependencies=[Depends(verifyDeviceKey)])
def cancelSession(sessionId: str, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voteSession = db.get(VoteSession, sessionId)
    if voteSession is None:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    if voteSession.isClosed:
        return {"status": "alreadyClosed", "sessionId": sessionId}
    voteSession.isClosed = True
    invalidatePendingFingerprintCommands(db, sessionId)
    db.add(voteSession)
    db.commit()
    return {"status": "cancelled", "sessionId": sessionId}


@app.get("/api/v1/session/{sessionId}/ballot", dependencies=[Depends(verifyDeviceKey)])
def getBallot(sessionId: str, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voteSession = getActiveSession(db, sessionId)
    sessionStatus = buildSessionStatus(db, voteSession)
    if not sessionStatus["readyToVote"]:
        raise HTTPException(status_code=403, detail="Faltan verificaciones")
    voter = db.get(Voter, voteSession.voterId)
    candidates = db.exec(select(Candidate).order_by(col(Candidate.id))).all()
    offices = []
    for office in OFFICE_ORDER:
        officeCandidates = [
            {"candidateId": candidate.id, "name": candidate.name, "party": candidate.party}
            for candidate in candidates
            if candidate.office == office and candidateMatchesVoter(candidate, voter)
        ]
        offices.append({"office": office, "candidates": officeCandidates})
    return {
        "voterName": voter.fullName,
        "stateName": voter.stateName,
        "municipalityName": voter.municipalityName,
        "offices": offices,
    }


@app.post("/api/v1/session/{sessionId}/vote", dependencies=[Depends(verifyDeviceKey)])
def castVote(sessionId: str, request: VoteRequest, db: Session = Depends(getDbSession)):
    require_kiosk_available(db)
    voteSession = getActiveSession(db, sessionId)
    sessionStatus = buildSessionStatus(db, voteSession)
    if not sessionStatus["readyToVote"]:
        raise HTTPException(status_code=403, detail="Faltan verificaciones")
    voter = db.get(Voter, voteSession.voterId)
    if not voter.isEnabled:
        raise HTTPException(status_code=403, detail="El votante no esta habilitado")
    if voter.hasVoted:
        rejectAlreadyVoted(db, voteSession)
    chosenIds = {
        OFFICE_PRESIDENT: request.presidentId,
        OFFICE_GOVERNOR: request.governorId,
        OFFICE_MAYOR: request.mayorId,
    }
    chosenCandidates = []
    for office in OFFICE_ORDER:
        candidate = db.get(Candidate, chosenIds[office])
        validateChosenCandidate(candidate, office, voter)
        chosenCandidates.append(candidate)
    claimQuery = update(Voter).where(col(Voter.id) == voter.id).where(col(Voter.hasVoted).is_(False))
    claimResult = db.exec(claimQuery.values(hasVoted=True))
    if claimResult.rowcount != 1:
        db.rollback()
        rejectAlreadyVoted(db, voteSession)
    for candidate in chosenCandidates:
        db.add(Ballot(candidateId=candidate.id))
    voteSession.isClosed = True
    invalidatePendingFingerprintCommands(db, sessionId)
    db.add(voteSession)
    db.commit()
    return {"status": "voteRecorded"}


@app.get("/api/v1/results", dependencies=[Depends(verifyDeviceKey)])
def getResults(office: Optional[str] = None, db: Session = Depends(getDbSession)):
    query = select(
        Candidate.id,
        Candidate.name,
        Candidate.party,
        Candidate.office,
        Candidate.stateName,
        Candidate.municipalityName,
        func.count(Ballot.id),
    )
    query = query.join(Ballot, Ballot.candidateId == Candidate.id, isouter=True)
    if office is not None:
        query = query.where(Candidate.office == office.upper())
    query = query.group_by(
        Candidate.id,
        Candidate.name,
        Candidate.party,
        Candidate.office,
        Candidate.stateName,
        Candidate.municipalityName,
    )
    query = query.order_by(col(Candidate.id))
    resultRows = db.exec(query).all()
    return [
        {
            "candidateId": row[0],
            "name": row[1],
            "party": row[2],
            "office": row[3],
            "stateName": row[4],
            "municipalityName": row[5],
            "votes": row[6],
        }
        for row in resultRows
    ]
    
@app.get("/api/v1/dashboard/summary", dependencies=[Depends(verifyDeviceKey)])
def getDashboardSummary(db: Session = Depends(getDbSession)):
    totalVoters = db.exec(select(func.count(Voter.id))).one()
    votedCount = db.exec(select(func.count(Voter.id)).where(Voter.hasVoted == True)).one()
    participationRate = round((votedCount / totalVoters * 100), 2) if totalVoters > 0 else 0.0
    
    return {
        "totalNominalList": totalVoters,
        "totalVotesCast": votedCount,
        "participationPercentage": participationRate,
        "pendingVoters": totalVoters - votedCount
    }

@app.get("/api/v1/dashboard/timeline", dependencies=[Depends(verifyDeviceKey)])
def getVotingTimeline(db: Session = Depends(getDbSession)):
    # Detectamos si la base de datos es PostgreSQL o SQLite
    isPostgres = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")
    
    if isPostgres:
        # Sintaxis nativa de PostgreSQL (Neon)
        dateExpr = func.to_char(VoteSession.createdAt, 'YYYY-MM-DD HH24:00:00')
    else:
        # Sintaxis nativa de SQLite (Local)
        dateExpr = func.strftime('%Y-%m-%d %H:00:00', VoteSession.createdAt)

    statement = (
        select(
            dateExpr.label('hour'),
            func.count(VoteSession.id)
        )
        .where(VoteSession.isClosed == True)
        .group_by('hour')
        .order_by('hour')
    )
    
    rows = db.exec(statement).all()
    return [{"timestamp": row[0], "votes": row[1]} for row in rows]
    
@app.get("/api/v1/analytics/anomalies", dependencies=[Depends(verifyDeviceKey)])
def getAnalytics(db: Session = Depends(getDbSession)):
    # 1. Contar total de intentos de huella ejecutados
    totalCommands = db.exec(
        select(func.count(FingerprintCommand.id))
        .where(FingerprintCommand.status == "completed")
    ).one_or_none() or 0

    # 2. Contar solo los intentos fallidos
    failedAttempts = db.exec(
        select(func.count(FingerprintCommand.id))
        .where(FingerprintCommand.status == "completed")
        .where(FingerprintCommand.result == "failed")
    ).one_or_none() or 0

    # 3. Calcular la tasa real de fallos (Anomaly Score)
    anomalyScore = round(failedAttempts / totalCommands, 4) if totalCommands > 0 else 0.0

    # 4. Determinar estado de la casilla y generar banderas de auditoría
    auditFlags = []
    status = "NORMAL"

    if anomalyScore > 0.30 and totalCommands >= 5:
        status = "ALERTA"
        auditFlags.append("Alta tasa de rechazo biométrico en la casilla (>30% de fallos).")

    if failedAttempts >= 10:
        if status != "ALERTA":
            status = "PRECAUCIÓN"
        auditFlags.append("Se han acumulado más de 10 rechazos de huella durante la jornada.")

    return {
        "status": status,
        "anomalyScore": anomalyScore,
        "totalFingerprintCommands": totalCommands,
        "failedFingerprintAttempts": failedAttempts,
        "auditFlags": auditFlags
    }


# ==============================================================================
# SEGURIDAD INTEGRAL DEL KIOSK: BLOQUEO GLOBAL, DESBLOQUEO ADMIN E INCIDENTES
# ==============================================================================

@app.get("/api/v1/kiosk/lock", dependencies=[Depends(verifyDeviceKey)])
def getKioskLockStatus(db: Session = Depends(getDbSession)):
    lock = db.get(KioskLock, DEFAULT_KIOSK_DEVICE_ID)
    incident = db.get(SecurityIncident, lock.incidentId) if lock and lock.incidentId else None
    if lock and lock.isLocked and incident is None:
        lock = kiosk_state_for_update(db)
        if lock.isLocked:
            lock = lock_kiosk_device(db, lock.reason or "Bloqueo anterior", lock.lockedByAttemptType or "MANUAL")
            db.flush()
            incident = db.get(SecurityIncident, lock.incidentId)
        db.commit()
    return {
        "deviceId": DEFAULT_KIOSK_DEVICE_ID,
        "isLocked": bool(lock and lock.isLocked),
        "reason": lock.reason if lock else None,
        "lockedAt": toUtcAware(lock.lockedAt).isoformat() if lock and lock.lockedAt else None,
        "lockedByAttemptType": lock.lockedByAttemptType if lock else None,
        "incidentId": incident.id if incident else None,
        "photoStatus": incident.status if incident else None,
    }


@app.post("/api/v1/kiosk/lock", dependencies=[Depends(verifyDeviceKey)])
def setKioskLock(lockRequest: LockKioskRequest, db: Session = Depends(getDbSession)):
    lock = lock_kiosk_device(db, lockRequest.reason, "MANUAL")
    db.commit()
    return {"success": True, "deviceId": lock.deviceId, "isLocked": True, "incidentId": lock.incidentId}


@app.post("/api/v1/kiosk/unlock", dependencies=[Depends(verifyDeviceKey)])
def unlockKiosk(unlockRequest: UnlockKioskRequest, db: Session = Depends(getDbSession)):
    scan = unlockRequest.scan
    lock = kiosk_state_for_update(db)
    now = getUtcNow()
    # The signed scan is bound to the specific lock and is accepted only while fresh.
    if (
        scan.deviceId != NFC_DEVICE_ID or scan.sessionId != lock.incidentId
        or not int(now.timestamp()) <= scan.expiresAt <= int(now.timestamp()) + DEVICE_MAX_SKEW_SECONDS
    ):
        raise HTTPException(status_code=403, detail="Lectura administrativa inválida o vencida")
    expected = nfc_response_signature(
        load_hex_key("NFC_HMAC_KEY"), scan.deviceId, scan.sessionId, scan.nonce,
        scan.sequence, scan.status, scan.uid, scan.expiresAt,
    )
    if not signature_matches(scan.hmac, expected):
        raise HTTPException(status_code=403, detail="Firma del lector NFC inválida")
    nonce_key = (f"admin:{scan.deviceId}", scan.nonce)
    if db.get(DeviceNonce, nonce_key):
        audit = db.get(KioskUnlockAudit, scan.sessionId)
        if audit and audit.scanNonce == scan.nonce and not lock.isLocked:
            return {"success": True, "adminName": audit.adminName, "isLocked": False}
        raise HTTPException(status_code=409, detail="Lectura administrativa ya utilizada")
    if not lock.isLocked:
        raise HTTPException(status_code=409, detail="El dispositivo ya está desbloqueado")
    db.add(DeviceNonce(deviceId=nonce_key[0], nonce=nonce_key[1], createdAt=now))
    admin_card = db.exec(select(AdminCard).where(
        AdminCard.cardUid == scan.uid, col(AdminCard.isEnabled).is_(True),
    )).first()
    if admin_card is None:
        db.commit()
        raise HTTPException(status_code=403, detail="Tarjeta de administrador no autorizada o deshabilitada")
    db.add(KioskUnlockAudit(
        incidentId=scan.sessionId, adminCardId=admin_card.id, adminName=admin_card.adminName, scanNonce=scan.nonce, unlockedAt=now,
    ))
    incident = db.get(SecurityIncident, lock.incidentId)
    if incident and incident.status == "PHOTO_PENDING":
        incident.status = "PHOTO_UNAVAILABLE"
    lock.isLocked = False
    lock.unlockedAt = now
    lock.unlockedByCardUid = scan.uid
    db.commit()
    return {"success": True, "adminName": admin_card.adminName, "isLocked": False}


def photo_cutoff() -> datetime:
    return getUtcNow() - timedelta(days=INCIDENT_PHOTO_RETENTION_DAYS)


@app.post("/api/v1/security/incidents", dependencies=[Depends(verifyDeviceKey)])
def reportSecurityIncident(incidentRequest: IncidentReportRequest, db: Session = Depends(getDbSession)):
    lock = kiosk_state_for_update(db)
    incident = db.get(SecurityIncident, str(incidentRequest.id))
    if incident is None or incident.deviceId != DEFAULT_KIOSK_DEVICE_ID or incident.eventType != "MAX_ATTEMPTS_EXCEEDED":
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    if toUtcAware(incident.timestamp) <= photo_cutoff():
        raise HTTPException(status_code=410, detail="Venció el plazo de conservación de evidencia")
    if incident.status == "PHOTO_PENDING":
        if not lock.isLocked or lock.incidentId != incident.id:
            raise HTTPException(status_code=409, detail="El incidente ya no está activo")
        if incidentRequest.photoBase64 and not incidentRequest.captureFailed:
            try:
                jpeg = base64.b64decode(incidentRequest.photoBase64, validate=True)
                if len(jpeg) > MAX_PHOTO_BYTES:
                    raise ValueError("JPEG demasiado grande")
                with Image.open(io.BytesIO(jpeg), formats=["JPEG"]) as image:
                    if image.width * image.height > 8_000_000:
                        raise ValueError("Resolución excesiva")
                    image.load()
            except (ValueError, binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise HTTPException(status_code=422, detail="Evidencia JPEG inválida") from exc
            db.add(IncidentPhoto(incidentId=incident.id, jpeg=jpeg, capturedAt=getUtcNow()))
            incident.status = "PHOTO_STORED"
        elif incidentRequest.captureFailed and not incidentRequest.photoBase64:
            incident.status = "CAMERA_ERROR"
        else:
            raise HTTPException(status_code=422, detail="Indica una foto o un fallo de captura")
    photo = db.get(IncidentPhoto, incident.id) if incident.status == "PHOTO_STORED" else None
    response = {"success": True, "incidentId": incident.id, "status": incident.status,
                "hasPhoto": bool(photo and toUtcAware(photo.capturedAt) > photo_cutoff()), "kioskLocked": lock.isLocked}
    db.commit()
    return response


@app.get("/api/v1/security/incidents", dependencies=[Depends(verifyAdminKey)])
def listSecurityIncidents(db: Session = Depends(getDbSession)):
    photo_ids = set(db.exec(select(IncidentPhoto.incidentId).where(IncidentPhoto.capturedAt > photo_cutoff())).all())
    audits = {audit.incidentId: audit for audit in db.exec(select(KioskUnlockAudit)).all()}
    incidents = db.exec(select(SecurityIncident).order_by(col(SecurityIncident.timestamp).desc())).all()
    return [
        {
            "id": inc.id,
            "deviceId": inc.deviceId,
            "timestamp": toUtcAware(inc.timestamp).isoformat(),
            "authType": inc.authType,
            "eventType": inc.eventType,
            "userRef": inc.userRef,
            "hasPhoto": inc.id in photo_ids,
            "unlockedBy": audits[inc.id].adminName if inc.id in audits else None,
            "unlockedAt": toUtcAware(audits[inc.id].unlockedAt).isoformat() if inc.id in audits else None,
            "status": inc.status,
            "details": inc.details,
        }
        for inc in incidents
    ]


@app.get("/api/v1/security/incidents/{incidentId}/photo", dependencies=[Depends(verifyAdminKey)])
def getSecurityIncidentPhoto(incidentId: str, db: Session = Depends(getDbSession)):
    photo = db.get(IncidentPhoto, incidentId)
    if photo is None or toUtcAware(photo.capturedAt) <= photo_cutoff():
        raise HTTPException(status_code=404, detail="Fotografía de incidente no encontrada")
    return Response(photo.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.delete("/api/v1/security/incidents/expired-photos", dependencies=[Depends(verifyAdminKey)])
def purgeExpiredPhotos(db: Session = Depends(getDbSession)):
    deleted = db.exec(delete(IncidentPhoto).where(IncidentPhoto.capturedAt <= photo_cutoff()))
    count = deleted.rowcount
    db.commit()
    return {"deleted": count}


@app.post("/api/v1/admin/cards", dependencies=[Depends(verifyAdminKey)])
def enrollAdminCard(req: AdminCardEnrollRequest, db: Session = Depends(getDbSession)):
    normalized_uid = normalizeCardUid(req.cardUid)
    if not re.fullmatch(r"[0-9A-F]{8,20}", normalized_uid):
        raise HTTPException(status_code=422, detail="UID NFC inválido")
    existing = db.exec(select(AdminCard).where(AdminCard.cardUid == normalized_uid)).first()
    if existing:
        existing.adminName = req.adminName.strip()
        existing.isEnabled = req.isEnabled
        existing.updatedAt = getUtcNow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return {"success": True, "message": "Tarjeta de administrador actualizada", "id": existing.id}
    admin = AdminCard(
        cardUid=normalized_uid,
        adminName=req.adminName.strip(),
        isEnabled=req.isEnabled,
        createdAt=getUtcNow(),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {"success": True, "message": "Tarjeta de administrador enrolada", "id": admin.id}


@app.get("/api/v1/admin/cards", dependencies=[Depends(verifyAdminKey)])
def listAdminCards(db: Session = Depends(getDbSession)):
    cards = db.exec(select(AdminCard).order_by(col(AdminCard.createdAt).desc())).all()
    return [
        {
            "id": c.id,
            "cardUid": c.cardUid,
            "adminName": c.adminName,
            "isEnabled": c.isEnabled,
            "createdAt": toUtcAware(c.createdAt).isoformat(),
        }
        for c in cards
    ]


# --- Dashboard web (modulo aditivo; ver docs/DASHBOARD_MANUAL.md) ---
from dashboard_api import BackendBindings, install_dashboard  # noqa: E402

install_dashboard(app, BackendBindings(
    engine=engine, verify_device_key=verifyDeviceKey, device_key=DEVICE_KEY,
    Voter=Voter, Candidate=Candidate, Ballot=Ballot, DeviceReplayGuard=DeviceReplayGuard,
    fingerprint_device_id=FINGERPRINT_DEVICE_ID, normalize_region=normalizeRegionName,
))
