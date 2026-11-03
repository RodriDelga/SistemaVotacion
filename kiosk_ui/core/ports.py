"""Contratos que deben cumplir los adaptadores.

PROVISIONALES: reflejan lo que la interfaz necesita, no el código real del
proyecto. Se ajustarán tras inspeccionar los módulos de RFID/NFC, ESP32, huella,
rostro y FastAPI. Los métodos bloquean; el controlador los ejecuta siempre en
hilos trabajadores. Los que esperan al usuario reciben un threading.Event
`cancel` y deben regresar pronto cuando se active.
"""
from __future__ import annotations

import threading
from typing import Mapping, Protocol, Sequence

from kiosk_ui.core.models import Position, StepResult, SubmitResult


class CardReader(Protocol):
    def wait_for_card(self, cancel: threading.Event) -> StepResult:
        """Espera una tarjeta y la valida. Devuelve voter_ref si es válida."""


class FingerprintVerifier(Protocol):
    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult: ...


class FaceVerifier(Protocol):
    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult: ...


class VotingBackend(Protocol):
    def load_ballot(self, voter_ref: str) -> tuple[Position, ...]:
        """Devuelve los cargos y candidatos. Lanza una excepción si falla."""

    def submit_vote(self, voter_ref: str, selections: Mapping[str, str]) -> SubmitResult:
        """Envía {position_id: candidate_id}. La respuesta debe reflejar al
        backend real; ante cualquier duda debe devolver/lanzar algo que el
        controlador trate como UNCERTAIN."""

    def cancel_session(self, voter_ref: str) -> None:
        """Cancela la sesión del backend al abandonar el flujo."""


class DemoHooks(Protocol):
    """Solo para la demostración: permite simular la lectura de una tarjeta."""
    scenario_labels: Sequence[str]

    def tap(self, label: str) -> bool: ...
