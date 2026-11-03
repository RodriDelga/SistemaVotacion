"""Adaptadores SIMULADOS para la demostración y las pruebas.

Todos los votantes, candidatos y respuestas son ficticios. No hay hardware ni
red. Se reemplazarán por adaptadores reales cuando se inspeccione el código
existente; la interfaz no importa este módulo (solo main.py lo hace).
"""
from __future__ import annotations

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


def _cands(pos_id: str, names: list[str]) -> tuple[Candidate, ...]:
    return tuple(Candidate(f"{pos_id}-{i + 1}", n, pos_id) for i, n in enumerate(names))


BALLOT = (
    Position("MAYOR", "Presidente Municipal", _cands("MAYOR", [
        "Mariana Ejemplo Soto", "Rodrigo Muestra Ibarra", "Lucía Demo Fuentes"])),
    Position("GOVERNOR", "Gobernador", _cands("GOVERNOR", [
        "Héctor Prueba Lagos", "Valeria Simulada Ríos"])),
    Position("PRESIDENT", "Presidente de la República", _cands("PRESIDENT", [
        "Tomás Ficticio Arce", "Irene Demo Salas", "Joaquín Muestra Peña"])),
)


class MockKit:
    """Agrupa los cuatro adaptadores simulados y los controles de la demo."""

    def __init__(self, delay: float = 1.2) -> None:
        self.delay = delay
        self.scenarios = SCENARIOS
        self._by_label = {s.label: s for s in SCENARIOS}
        self._by_ref = {s.voter_ref: s for s in SCENARIOS}
        self._tap_event = threading.Event()
        self._tapped = HAPPY
        self.waiting = threading.Event()   # activo mientras el lector espera una tarjeta
        self.submit_count = 0
        self.submitted: list[dict[str, str]] = []
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


class _MockFingerprint:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if not self._kit._pause(cancel, self._kit.delay):
            return _CANCELLED
        if self._kit._scenario(voter_ref).fingerprint_ok:
            return StepResult(True, "Huella verificada")
        return StepResult(False, "La huella no coincide. Limpie el dedo y vuelva a intentarlo.")


class _MockFace:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if not self._kit._pause(cancel, self._kit.delay):
            return _CANCELLED
        if self._kit._scenario(voter_ref).face_ok:
            return StepResult(True, "Rostro verificado")
        return StepResult(False, "No se reconoció el rostro. Mire de frente a la cámara con buena luz.")


class _MockBackend:
    def __init__(self, kit: MockKit) -> None:
        self._kit = kit

    def load_ballot(self, voter_ref: str) -> tuple[Position, ...]:
        time.sleep(0.4 * self._kit.delay)
        if not self._kit._scenario(voter_ref).ballot_ok:
            raise ConnectionError("Backend simulado no disponible")
        return BALLOT

    def submit_vote(self, voter_ref: str, selections: Mapping[str, str]) -> SubmitResult:
        kit = self._kit
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
        # No hay sesiones externas en la simulación; se conserva el contrato real.
        return None
