"""Adaptadores de huella (ESP32 vía API local) y rostro (cámara local)."""
from __future__ import annotations
from kiosk_ui.led_control import encender_huella, encender_rostro

import os
import threading
import time
from typing import Callable, Optional

from common.hmac_protocol import face_attestation_signature, load_hex_key
from face_crypto import FaceCryptoError
from face_local import FaceCamera, FaceRejected, FaceVerificationError, identify_face
from kiosk_ui.adapters.real.api_client import ApiError, VotingApi
from kiosk_ui.core.models import StepResult


class FingerprintVerifier:
    """Crea una orden de un solo uso; la ESP32 firma el resultado hacia FastAPI."""

    def __init__(self, api: VotingApi, wait_s: Optional[float] = None,
                 poll_s: Optional[float] = None) -> None:
        self.api = api
        self.wait_s = wait_s or float(os.getenv("FINGERPRINT_WAIT_SECONDS", "75"))
        self.poll_s = poll_s or float(os.getenv("FINGERPRINT_POLL_SECONDS", "1"))

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        deadline = time.monotonic() + self.wait_s
        command_requested = False
        while not cancel.is_set() and time.monotonic() < deadline:
            try:
                if not command_requested:
                    self.api.request_fingerprint_command(voter_ref)
                    command_requested = True
                status = self.api.session_status(voter_ref)
                if status.get("fingerprintOk") is True:
                    encender_huella()
                    return StepResult(True, "Huella verificada")
                if status.get("fingerprintLocked") is True:
                    return StepResult(False, "Se agotaron los intentos de huella. Solicite ayuda.")
                if not status.get("fingerprintCommandPending"):
                    command_requested = False
            except ApiError as exc:
                if exc.status_code in (401, 403, 404, 409, 410):
                    return StepResult(False, "No se pudo verificar la huella. Intente de nuevo o solicite ayuda.")
                # Los errores de red se vuelven a consultar hasta el límite; no se
                # entrega ni fabrica un resultado biométrico desde la interfaz.
            cancel.wait(self.poll_s)
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.")
        return StepResult(False, "Tiempo de espera agotado para la huella. Intente de nuevo.")


class FaceVerifier:
    def __init__(self, api: VotingApi, key_hex: Optional[str] = None,
                 camera_factory: Callable = FaceCamera, matcher: Callable = identify_face) -> None:
        self.api = api
        self.key = load_hex_key("FACE_ATTESTATION_KEY") if key_hex is None else bytes.fromhex(key_hex)
        if len(self.key) != 32:
            raise ValueError("La clave de atestación facial debe tener 32 bytes")
        self.camera_factory = camera_factory
        self.matcher = matcher

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.")
        try:
            data = self.api.face_challenge(voter_ref)
            challenge = data["challenge"]
            records = data["records"]
            if len(records) != 1:
                raise FaceVerificationError("El servicio no limitó el registro facial al votante de la sesión.")
            with self.camera_factory() as camera:
                captured = camera.capture_single_encoding()
            if cancel.is_set():
                return StepResult(False, "Operación cancelada.")
            match = self.matcher(captured, records)
            matched, voter_id = True, int(match.voter_id)
        except FaceRejected:
            matched, voter_id = False, None
        except (FaceVerificationError, FaceCryptoError, ApiError, KeyError, TypeError, ValueError):
            return StepResult(False, "No se pudo completar la verificación facial. Revise la cámara o solicite ayuda.")
        attestation = face_attestation_signature(self.key, voter_ref, challenge, voter_id, matched)
        try:
            status = self.api.submit_face(voter_ref, challenge, matched, voter_id, attestation)
        except ApiError as exc:
            if exc.status_code == 401:
                return StepResult(False, "El rostro no coincide. Mire de frente a la cámara con buena luz.")
            return StepResult(False, "No se pudo validar el resultado facial. Intente de nuevo o solicite ayuda.")
        if matched and status.get("faceOk") is True:
            encender_rostro()
            return StepResult(True, "Rostro verificado")
        return StepResult(False, "El rostro no fue verificado. Intente de nuevo o solicite ayuda.")
