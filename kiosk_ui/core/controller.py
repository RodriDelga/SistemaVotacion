"""Controlador del flujo de votación. No depende de Tkinter.

Modelo de hilos
---------------
* Las operaciones que pueden bloquear (hardware, red) corren en hilos trabajadores.
* Los hilos NUNCA tocan el estado ni la UI: solo dejan su resultado en una
  queue.Queue (`_inbox`).
* La UI llama a `pump()` periódicamente con after() desde el hilo principal de
  Tkinter. `pump()` procesa los resultados, cambia el estado y avisa por
  `on_change`. Así todo cambio de estado y todo acceso a widgets ocurre en el
  hilo principal.
"""
from __future__ import annotations
from kiosk_ui.led_control import apagar_todos

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from kiosk_ui.core.models import (
    Candidate, Phase, Position, Step, StepResult, StepStatus, SubmitOutcome, SubmitResult,
)
from kiosk_ui.core.ports import CardReader, FaceVerifier, FingerprintVerifier, VotingBackend

log = logging.getLogger(__name__)

UNCERTAIN_MESSAGE = (
    "No se pudo confirmar si su voto fue registrado. No lo envíe de nuevo: "
    "avise al personal responsable para verificar el estado antes de volver a intentarlo."
)
_DEFAULT_FAIL = {
    Step.CARD: "No se pudo validar la tarjeta.",
    Step.FINGERPRINT: "No se pudo verificar la huella.",
    Step.FACE: "No se pudo verificar el rostro.",
}


@dataclass(frozen=True)
class Services:
    card_reader: CardReader
    fingerprint: FingerprintVerifier
    face: FaceVerifier
    backend: VotingBackend


class VotingController:
    def __init__(self, services: Services) -> None:
        self._svc = services
        self._inbox: queue.Queue = queue.Queue()
        self._gen = 0                      # sesión actual; invalida resultados viejos
        self._cancel = threading.Event()   # cancela esperas de hardware de la sesión
        self.on_change: Optional[Callable[[], None]] = None
        self._init_state()

    # ------------------------------------------------------------ estado
    def _init_state(self) -> None:
        self.phase = Phase.IDLE
        self.steps: dict[Step, StepStatus] = {s: StepStatus.PENDING for s in Step}
        self.failed_step: Optional[Step] = None
        self.step_message = ""
        self.ballot: tuple[Position, ...] = ()
        self.position_index = 0
        self.selections: dict[str, str] = {}   # selección temporal; NO es el voto registrado
        self.editing_from_review = False
        self.submit_result: Optional[SubmitResult] = None
        self.error_message = ""
        self._voter_ref: Optional[str] = None  # nunca se muestra ni se registra en logs
        self._submit_started = False           # candado de doble envío

    @property
    def current_position(self) -> Optional[Position]:
        if self.ballot and 0 <= self.position_index < len(self.ballot):
            return self.ballot[self.position_index]
        return None

    @property
    def can_continue(self) -> bool:
        pos = self.current_position
        return pos is not None and pos.id in self.selections

    @property
    def is_complete(self) -> bool:
        return bool(self.ballot) and all(p.id in self.selections for p in self.ballot)

    def selected_candidate(self, position: Position) -> Optional[Candidate]:
        cid = self.selections.get(position.id)
        return next((c for c in position.candidates if c.id == cid), None)

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    # --------------------------------------------------- hilos y mensajes
    def _spawn(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        gen = self._gen

        def runner() -> None:
            try:
                result: Any = work()
            except Exception as exc:  # el detalle no se muestra al votante
                log.warning("Fallo en tarea de fondo: %s", type(exc).__name__)
                result = exc
            self._inbox.put((gen, done, result))

        threading.Thread(target=runner, daemon=True, name="kiosk-worker").start()

    def pump(self) -> None:
        """Procesa resultados de los hilos. Llamar solo desde el hilo principal."""
        while True:
            try:
                gen, done, result = self._inbox.get_nowait()
            except queue.Empty:
                return
            if gen == self._gen:   # descarta resultados de sesiones ya canceladas
                done(result)

    def _cancel_backend_session(self, voter_ref: Optional[str]) -> None:
        if not voter_ref:
            return
        def cancel() -> None:
            try:
                self._svc.backend.cancel_session(voter_ref)
            except Exception:
                # La expiración del backend sigue siendo la barrera final.
                log.warning("No se pudo cancelar una sesión al salir")
        threading.Thread(target=cancel, daemon=True, name="kiosk-cancel").start()

    def shutdown(self) -> None:
        apagar_todos()
        self._cancel.set()
        self._cancel_backend_session(self._voter_ref)
        self._voter_ref = None
        self._gen += 1

    # ----------------------------------------------------- inicio / reinicio
    def reset(self) -> None:
        """Descarta la sesión y vuelve a esperar tarjeta. Ignorado mientras se envía un voto."""
        if self.phase is Phase.SUBMITTING:
            return
        apagar_todos()
        self._cancel.set()
        self._cancel_backend_session(self._voter_ref)
        self._gen += 1
        self._cancel = threading.Event()
        self._init_state()
        self._notify()
        cancel = self._cancel
        self._spawn(lambda: self._svc.card_reader.wait_for_card(cancel), self._on_card)

    # ------------------------------------------------------ autenticación
    def _on_card(self, result: Any) -> None:
        result = self._as_step_result(result, Step.CARD)
        self.phase = Phase.AUTH
        if result.ok and result.voter_ref:
            self._voter_ref = result.voter_ref
            self.steps[Step.CARD] = StepStatus.OK
            self._start_step(Step.FINGERPRINT)
        else:
            self._fail_step(Step.CARD, result.message)

    def _start_step(self, step: Step) -> None:
        verifier = self._svc.fingerprint if step is Step.FINGERPRINT else self._svc.face
        self.steps[step] = StepStatus.ACTIVE
        self.failed_step = None
        self.step_message = ""
        self._notify()
        ref, cancel = self._voter_ref, self._cancel
        self._spawn(lambda: verifier.verify(ref, cancel), lambda r: self._on_step(step, r))

    def _on_step(self, step: Step, result: Any) -> None:
        result = self._as_step_result(result, step)
        if not result.ok:
            self._fail_step(step, result.message)
            return
        self.steps[step] = StepStatus.OK
        if step is Step.FINGERPRINT:
            self._start_step(Step.FACE)
        else:
            self.phase = Phase.VERIFIED
            self._notify()

    def _fail_step(self, step: Step, message: str) -> None:
        apagar_todos()
        self.steps[step] = StepStatus.FAILED
        self.failed_step = step
        self.step_message = message or _DEFAULT_FAIL[step]
        self._notify()

    @staticmethod
    def _as_step_result(result: Any, step: Step) -> StepResult:
        if isinstance(result, StepResult):
            return result
        return StepResult(False, "Error del dispositivo. Intente de nuevo o solicite ayuda.")

    def retry_step(self) -> None:
        """Reintenta el paso fallido (acción explícita del votante)."""
        if self.phase is not Phase.AUTH or self.failed_step is None:
            return
        if self.failed_step is Step.CARD:
            self.reset()
        else:
            self._start_step(self.failed_step)

    # ------------------------------------------------------------- boleta
    def continue_to_ballot(self) -> None:
        if self.phase is Phase.VERIFIED:
            self._load_ballot()

    def _load_ballot(self) -> None:
        self.phase = Phase.LOADING
        self._notify()
        ref = self._voter_ref
        self._spawn(lambda: self._svc.backend.load_ballot(ref), self._on_ballot)

    def _on_ballot(self, result: Any) -> None:
        if isinstance(result, Exception):
            return self._fail("No se pudo cargar la boleta. Avise al personal responsable.")
        ok = isinstance(result, tuple) and result and all(
            isinstance(p, Position) and p.candidates for p in result)
        if not ok:
            return self._fail("No hay una boleta disponible. Avise al personal responsable.")
        self.ballot = result
        self.position_index = 0
        self.phase = Phase.SELECTING
        self._notify()

    def _fail(self, message: str) -> None:
        apagar_todos()
        self.error_message = message
        self._cancel_backend_session(self._voter_ref)
        self.ballot = ()
        self.selections.clear()
        self._voter_ref = None
        self.phase = Phase.ERROR
        self._notify()

    # ---------------------------------------------------------- selección
    def select(self, position_id: str, candidate_id: str) -> None:
        if self.phase is not Phase.SELECTING:
            return
        pos = next((p for p in self.ballot if p.id == position_id), None)
        if pos and any(c.id == candidate_id for c in pos.candidates):
            self.selections[position_id] = candidate_id
            self._notify()

    def next_position(self) -> None:
        if self.phase is not Phase.SELECTING or not self.can_continue:
            return
        last = self.position_index >= len(self.ballot) - 1
        if (last or self.editing_from_review) and self.is_complete:
            self.editing_from_review = False
            self.phase = Phase.REVIEW
        elif not last:
            self.position_index += 1
        self._notify()

    def back(self) -> None:
        if self.phase is Phase.SELECTING and self.position_index > 0 and not self.editing_from_review:
            self.position_index -= 1
            self._notify()

    def edit(self, index: int) -> None:
        """Desde la revisión, vuelve a un cargo para cambiar la elección."""
        if self.phase is Phase.REVIEW and 0 <= index < len(self.ballot):
            self.position_index = index
            self.editing_from_review = True
            self.phase = Phase.SELECTING
            self._notify()

    # -------------------------------------------------------------- envío
    def submit(self) -> bool:
        """Envía el voto. Solo se acepta UNA vez por sesión; devuelve si se inició."""
        if self.phase is not Phase.REVIEW or self._submit_started or not self.is_complete:
            return False
        self._submit_started = True
        self.phase = Phase.SUBMITTING
        ref, payload = self._voter_ref, dict(self.selections)
        self._notify()
        self._spawn(lambda: self._svc.backend.submit_vote(ref, payload), self._on_submit)
        return True

    def _on_submit(self, result: Any) -> None:
        apagar_todos()
        if not isinstance(result, SubmitResult):
            # Excepción o respuesta inesperada: no sabemos si el backend registró el voto.
            result = SubmitResult(SubmitOutcome.UNCERTAIN, "")
        self.submit_result = result
        # Ya no se necesitan: se borran de memoria sin importar el resultado.
        self.selections.clear()
        self.ballot = ()
        self._voter_ref = None
        self.phase = Phase.RESULT
        self._notify()
