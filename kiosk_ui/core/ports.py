"""Contratos que deben cumplir los adaptadores.

PROVISIONALES: reflejan lo que la interfaz necesita, no el código real del
proyecto. Se ajustarán tras inspeccionar los módulos de RFID/NFC, ESP32, huella,
rostro y FastAPI. Los métodos bloquean; el controlador los ejecuta siempre en
hilos trabajadores. Los que esperan al usuario reciben un threading.Event
`cancel` y deben regresar pronto cuando se active.
"""
from __future__ import annotations

import threading
from typing import Mapping, Optional, Protocol, Sequence

from kiosk_ui.core.models import Position, StepResult, SubmitResult


class CardReader(Protocol):
    def wait_for_card(self, cancel: threading.Event) -> StepResult:
        """Espera una tarjeta y la valida. Devuelve voter_ref si es válida."""

    def read_admin_card(self, cancel: threading.Event, incident_id: str) -> Optional[dict]:
        """Devuelve la lectura NFC autenticada y vinculada al incidente."""


class FingerprintVerifier(Protocol):
    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult: ...


class FaceVerifier(Protocol):
    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult: ...


class VotingBackend(Protocol):
    def load_ballot(self, voter_ref: str) -> tuple[Position, ...]:
        """Devuelve los cargos y candidatos. Lanza una excepción si falla."""

    def submit_vote(self, voter_ref: str, selections: Mapping[str, str]) -> SubmitResult:
        """Envía {position_id: candidate_id}."""

    def cancel_session(self, voter_ref: str) -> None:
        """Cancela la sesión del backend al abandonar el flujo."""

    def check_lock(self) -> dict: ...

    def unlock_device(self, scan: dict) -> dict: ...

    def report_incident(self, incident_id: str, photo_bytes: Optional[bytes]) -> dict: ...


class DemoHooks(Protocol):
    """Solo para la demostración: permite simular la lectura de una tarjeta."""
    scenario_labels: Sequence[str]

    def tap(self, label: str) -> bool: ...
