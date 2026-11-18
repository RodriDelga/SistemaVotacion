"""Adaptadores SIMULADOS para la demostración y las pruebas.

Todos los votantes, candidatos y respuestas son ficticios. No hay hardware ni
red. Se reemplazarán por adaptadores reales cuando se inspeccione el código
existente; la interfaz no importa este módulo (solo main.py lo hace).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Mapping

from kiosk_ui.core.controller import Services
from kiosk_ui.core.models import Candidate, Position, StepResult, SubmitOutcome, SubmitResult


@dataclass(frozen=True)
class Scenario:
    label: str
    voter_ref: str
    card_ok: bool = True
    fingerprint_ok: bool = True
    face_ok: bool = True
    ballot_ok: bool = True
    submit: SubmitOutcome = SubmitOutcome.REGISTERED


HAPPY = Scenario("Votante 1 · flujo normal (voto registrado)", "DEMO-001")
CARD_FAIL = Scenario("Votante 2 · tarjeta rechazada", "DEMO-002", card_ok=False)
FINGER_FAIL = Scenario("Votante 3 · la huella no coincide", "DEMO-003", fingerprint_ok=False)
FACE_FAIL = Scenario("Votante 4 · rostro no reconocido", "DEMO-004", face_ok=False)
BALLOT_FAIL = Scenario("Votante 5 · error al cargar la boleta", "DEMO-005", ballot_ok=False)
ALREADY_VOTED = Scenario("Votante 6 · el backend rechaza el voto", "DEMO-006", submit=SubmitOutcome.REJECTED)
UNCERTAIN = Scenario("Votante 7 · resultado incierto (sin respuesta)", "DEMO-007", submit=SubmitOutcome.UNCERTAIN)
SCENARIOS = (HAPPY, CARD_FAIL, FINGER_FAIL, FACE_FAIL, BALLOT_FAIL, ALREADY_VOTED, UNCERTAIN)


def _cands(pos_id: str, entries: list[tuple[str, str]]) -> tuple[Candidate, ...]:
    return tuple(Candidate(f"{pos_id}-{i + 1}", name, pos_id, party) for i, (name, party) in enumerate(entries))


BALLOT = (
    Position("MAYOR", "Presidente Municipal", _cands("MAYOR", [
        ("Mariana Ejemplo Soto", "Partido Ejemplo"), ("Rodrigo Muestra Ibarra", "Partido Muestra"), ("Lucía Demo Fuentes", "Partido Demo")])),
    Position("GOVERNOR", "Gobernador", _cands("GOVERNOR", [
        ("Héctor Prueba Lagos", "Partido Ejemplo"), ("Valeria Simulada Ríos", "Partido Muestra")])),
    Position("PRESIDENT", "Presidente de la República", _cands("PRESIDENT", [
        ("Tomás Ficticio Arce", "Partido Ejemplo"), ("Irene Demo Salas", "Partido Demo"), ("Joaquín Muestra Peña", "Partido Muestra")])),
)


class MockKit:
    """Agrupa los cuatro adaptadores simulados y los controles de la demo."""

    def __init__(self, delay: float = 1.2) -> None:
        self.delay = delay
        self.scenarios = SCENARIOS
        self._by_label = {s.label: s for s in SCENARIOS}
        self._by_ref = {s.voter_ref: s for s in SCENARIOS}
        self._tap_event = threading.Event()
        self._admin_tap_event = threading.Event()
        self._admin_card_uid: str = "ADMIN001"
        self._tapped = HAPPY
        self.waiting = threading.Event()   # activo mientras el lector espera una tarjeta
        self.submit_count = 0
        self.submitted: list[dict[str, str]] = []
        self.is_locked = False
        self.lock_reason = ""
        self.incident_id: Optional[str] = None
        self.photo_status: Optional[str] = None
        self.locked_at: Optional[str] = None
        self.admin_cards = {"ADMIN001", "ADMIN_DEMO"}
        self.incident_log: list[dict] = []
        self.fingerprint_attempts: dict[str, int] = {}
        self.face_attempts: dict[str, int] = {}
        self.card_reader = _MockCardReader(self)
        self.fingerprint = _MockFingerprint(self)
        self.face = _MockFace(self)
        self.backend = _MockBackend(self)

    @property
    def scenario_labels(self) -> list[str]:
        return [s.label for s in self.scenarios]

    def services(self) -> Services:
        return Services(self.card_reader, self.fingerprint, self.face, self.backend)

    def tap(self, label: str) -> bool:
        """Simula acercar una tarjeta. Se ignora si el lector no está esperando."""
        if not self.waiting.is_set():
            return False
        self._tapped = self._by_label[label]
        self._tap_event.set()
        return True

    def lock(self, reason: str) -> None:
        self.is_locked = True
        self.lock_reason = reason
        self.incident_id = str(uuid.uuid4())
        self.locked_at = datetime.now(timezone.utc).isoformat()
        self.photo_status = "PHOTO_PENDING"

    def tap_admin_card(self, card_uid: str = "ADMIN001") -> None:
        """Simula acercar una tarjeta de administrador."""
        self._admin_card_uid = card_uid
        self._admin_tap_event.set()

    def _scenario(self, voter_ref: str) -> Scenario:
        return self._by_ref[voter_ref]

    @staticmethod
    def _pause(cancel: threading.Event, seconds: float) -> bool:
        """Espera sin ignorar la cancelación. False si se canceló."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if cancel.is_set():
                return False
            time.sleep(0.02)
        return not cancel.is_set()


_CANCELLED = StepResult(False, "Operación cancelada.")


class _MockCardReader:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def wait_for_card(self, cancel: threading.Event) -> StepResult:
        kit = self._kit
        if kit.is_locked:
            return StepResult(False, "El dispositivo está bloqueado por motivos de seguridad.", is_locked=True)
        kit.waiting.set()
        try:
            while not cancel.is_set():
                if kit._tap_event.wait(0.1):
                    kit._tap_event.clear()
                    kit.waiting.clear()   # ya no acepta otra tarjeta
                    sc = kit._tapped
                    if not kit._pause(cancel, 0.4 * kit.delay):
                        return _CANCELLED
                    if not sc.card_ok:
                        return StepResult(False, "Tarjeta no reconocida. Intente de nuevo o solicite ayuda.")
                    return StepResult(True, "Tarjeta válida", sc.voter_ref)
            return _CANCELLED
        finally:
            kit.waiting.clear()

    def read_admin_card(self, cancel: threading.Event, incident_id: str) -> Optional[dict]:
        kit = self._kit
        while not cancel.is_set():
            if kit._admin_tap_event.wait(0.1):
                kit._admin_tap_event.clear()
                return {"sessionId": incident_id, "uid": kit._admin_card_uid}
        return None


class _MockFingerprint:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if self._kit.is_locked:
            return StepResult(False, "Dispositivo bloqueado por seguridad.", attempts_remaining=0, is_locked=True, auth_type="FINGERPRINT")
        if not self._kit._pause(cancel, self._kit.delay):
            return _CANCELLED
        sc = self._kit._scenario(voter_ref)
        if sc.fingerprint_ok:
            return StepResult(True, "Huella verificada", auth_type="FINGERPRINT")

        attempts = self._kit.fingerprint_attempts.get(voter_ref, 0) + 1
        self._kit.fingerprint_attempts[voter_ref] = attempts
        remaining = max(0, 5 - attempts)
        if remaining <= 0:
            self._kit.lock("Se agotaron los intentos de huella dactilar")
            return StepResult(False, "Se superó el límite de intentos permitidos. Dispositivo bloqueado.", attempts_remaining=0, is_locked=True, auth_type="FINGERPRINT", error_kind="locked")
        return StepResult(False, "La huella dactilar no coincide con la identidad registrada.", attempts_remaining=remaining, is_locked=False, auth_type="FINGERPRINT", error_kind="mismatch")


class _MockFace:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if self._kit.is_locked:
            return StepResult(False, "Dispositivo bloqueado por seguridad.", attempts_remaining=0, is_locked=True, auth_type="FACE")
        if not self._kit._pause(cancel, self._kit.delay):
            return _CANCELLED
        sc = self._kit._scenario(voter_ref)
        if sc.face_ok:
            return StepResult(True, "Rostro verificado", auth_type="FACE")

        attempts = self._kit.face_attempts.get(voter_ref, 0) + 1
        self._kit.face_attempts[voter_ref] = attempts
        remaining = max(0, 5 - attempts)
        if remaining <= 0:
            self._kit.lock("Se agotaron los intentos de reconocimiento facial")
            return StepResult(False, "Se superó el límite de intentos de reconocimiento facial. Dispositivo bloqueado.", attempts_remaining=0, is_locked=True, auth_type="FACE", error_kind="locked")
        return StepResult(False, "El rostro no coincide con la identidad registrada.", attempts_remaining=remaining, is_locked=False, auth_type="FACE", error_kind="mismatch")


class _MockBackend:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def load_ballot(self, voter_ref: str) -> tuple[Position, ...]:
        time.sleep(0.4 * self._kit.delay)
        if self._kit.is_locked:
            raise ConnectionError("Dispositivo bloqueado por seguridad")
        if not self._kit._scenario(voter_ref).ballot_ok:
            raise ConnectionError("Backend simulado no disponible")
        return BALLOT

    def submit_vote(self, voter_ref: str, selections: Mapping[str, str]) -> SubmitResult:
        kit = self._kit
        if kit.is_locked:
            return SubmitResult(SubmitOutcome.REJECTED, "El dispositivo está bloqueado por seguridad.")
        kit.submit_count += 1
        kit.submitted.append(dict(selections))
        time.sleep(1.5 * kit.delay)
        outcome = kit._scenario(voter_ref).submit
        if outcome is SubmitOutcome.REGISTERED:
            return SubmitResult(outcome, "Gracias por participar.", "DEMO-" + uuid.uuid4().hex[:8].upper())
        if outcome is SubmitOutcome.REJECTED:
            return SubmitResult(outcome, "El sistema indica que este votante ya emitió su voto. (Simulado)")
        return SubmitResult(outcome, "Tiempo de espera agotado sin respuesta del servidor. (Simulado)")

    def cancel_session(self, voter_ref: str) -> None:
        return None

    def check_lock(self) -> dict:
        return {
            "isLocked": self._kit.is_locked,
            "reason": self._kit.lock_reason,
            "lockedAt": self._kit.locked_at,
            "incidentId": self._kit.incident_id,
            "photoStatus": self._kit.photo_status,
        }

    def unlock_device(self, scan: dict) -> dict:
        if scan["uid"] not in self._kit.admin_cards or scan["sessionId"] != self._kit.incident_id:
            raise PermissionError("Tarjeta de administrador no autorizada")
        self._kit.is_locked = False
        self._kit.lock_reason = ""
        self._kit.fingerprint_attempts.clear()
        self._kit.face_attempts.clear()
        return {"success": True, "isLocked": False}

    def report_incident(self, incident_id: str, photo_bytes: Optional[bytes]) -> dict:
        if self._kit.photo_status == "PHOTO_PENDING":
            self._kit.incident_log.append({"id": incident_id, "photo_len": len(photo_bytes or b"")})
            self._kit.photo_status = "PHOTO_STORED" if photo_bytes else "CAMERA_ERROR"
        return {"success": True, "incidentId": incident_id, "status": self._kit.photo_status}
