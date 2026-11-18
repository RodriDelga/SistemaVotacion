"""Adaptadores de huella (ESP32 vía API local) y rostro (cámara local)."""
from __future__ import annotations
from kiosk_ui.led_control import encender_huella, encender_rostro

import logging
import os
import queue
import threading
import time
from typing import Callable, Optional

from common.hmac_protocol import face_attestation_signature, load_hex_key
from face_local import FaceCamera, FaceRejected, FaceVerificationError, identify_face
from kiosk_ui.adapters.real.api_client import ApiError, VotingApi
from kiosk_ui.core.models import StepResult

log = logging.getLogger(__name__)


def capture_incident_photo() -> Optional[bytes]:
    """Captura un fotograma JPEG desde la cámara para evidencia de seguridad."""
    try:
        with FaceCamera() as cam:
            return cam.capture_photo_bytes()
    except Exception as exc:
        log.warning("No se pudo capturar foto de incidente: %s", exc)
    return None


class FingerprintVerifier:
    """Crea una orden de un solo uso; la ESP32 firma el resultado hacia FastAPI."""

    def __init__(self, api: VotingApi, wait_s: Optional[float] = None,
                 poll_s: Optional[float] = None) -> None:
        self.api = api
        self.wait_s = wait_s or float(os.getenv("FINGERPRINT_WAIT_SECONDS", "75"))
        self.poll_s = poll_s or float(os.getenv("FINGERPRINT_POLL_SECONDS", "1"))

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        deadline = time.monotonic() + self.wait_s
        try:
            initial_status = self.api.session_status(voter_ref)
            if initial_status.get("kioskLocked") or initial_status.get("fingerprintLocked"):
                return StepResult(
                    False,
                    "Se superó el límite de intentos permitidos. Dispositivo bloqueado.",
                    attempts_remaining=0,
                    is_locked=True,
                    auth_type="FINGERPRINT",
                    error_kind="locked",
                )
        except ApiError as exc:
            return StepResult(False, str(exc), is_locked=exc.status_code == 423,
                              auth_type="FINGERPRINT", error_kind="comm_error")
        if initial_status.get("fingerprintOk") is True:
            encender_huella()
            return StepResult(True, "Huella verificada", auth_type="FINGERPRINT")

        base_attempts = initial_status.get("fingerprintAttempts", 0)

        try:
            self.api.request_fingerprint_command(voter_ref)
        except ApiError as exc:
            if exc.status_code == 423:
                return StepResult(
                    False,
                    "El dispositivo está bloqueado por motivos de seguridad.",
                    attempts_remaining=0,
                    is_locked=True,
                    auth_type="FINGERPRINT",
                    error_kind="locked",
                )
            return StepResult(
                False,
                "No se pudo iniciar la lectura de huella. Intente de nuevo.",
                auth_type="FINGERPRINT",
                error_kind="comm_error",
            )

        while not cancel.is_set() and time.monotonic() < deadline:
            try:
                status = self.api.session_status(voter_ref)
                if status.get("fingerprintOk") is True:
                    encender_huella()
                    return StepResult(True, "Huella verificada", auth_type="FINGERPRINT")

                cur_attempts = status.get("fingerprintAttempts", 0)
                attempts_remaining = status.get("fingerprintAttemptsRemaining")

                if status.get("kioskLocked") or status.get("fingerprintLocked"):
                    return StepResult(
                        False,
                        "Se superó el límite de intentos permitidos. Dispositivo bloqueado.",
                        attempts_remaining=0,
                        is_locked=True,
                        auth_type="FINGERPRINT",
                        error_kind="locked",
                    )

                if cur_attempts > base_attempts:
                    return StepResult(
                        False,
                        "La huella dactilar no coincide con la identidad registrada.",
                        attempts_remaining=attempts_remaining,
                        is_locked=False,
                        auth_type="FINGERPRINT",
                        error_kind="mismatch",
                    )
            except ApiError as exc:
                if exc.status_code == 423:
                    return StepResult(
                        False,
                        "El dispositivo está bloqueado por motivos de seguridad.",
                        attempts_remaining=0,
                        is_locked=True,
                        auth_type="FINGERPRINT",
                        error_kind="locked",
                    )
                return StepResult(
                    False,
                    "No se pudo verificar la huella. Intente de nuevo.",
                    auth_type="FINGERPRINT",
                    error_kind="comm_error",
                )

            cancel.wait(self.poll_s)

        if cancel.is_set():
            return StepResult(False, "Operación cancelada.", auth_type="FINGERPRINT")
        return StepResult(
            False,
            "Tiempo de espera agotado para la lectura de huella. Toque Reintentar.",
            auth_type="FINGERPRINT",
            error_kind="timeout",
        )


class FaceVerifier:
    def __init__(self, api: VotingApi, key_hex: Optional[str] = None,
                 camera_factory: Callable = FaceCamera, matcher: Callable = identify_face) -> None:
        self.api = api
        self.key = load_hex_key("FACE_ATTESTATION_KEY") if key_hex is None else bytes.fromhex(key_hex)
        if len(self.key) != 32:
            raise ValueError("La clave de atestación facial debe tener 32 bytes")
        self.camera_factory = camera_factory
        self.matcher = matcher
        self.capture_timeout = float(os.getenv("FACE_CAPTURE_TIMEOUT_SECONDS", "15"))
        self._camera_lock = threading.Lock()

    def _read_face(self, cancel: threading.Event):
        if not self._camera_lock.acquire(blocking=False):
            raise FaceVerificationError("La cámara todavía está ocupada.")
        results: queue.Queue = queue.Queue(maxsize=1)

        def capture() -> None:
            try:
                with self.camera_factory() as camera:
                    result = camera.capture_single_encoding()
            except Exception as exc:
                result = exc
            finally:
                self._camera_lock.release()
            results.put(result)

        threading.Thread(target=capture, daemon=True, name="kiosk-face-camera").start()
        deadline = time.monotonic() + self.capture_timeout
        while not cancel.is_set() and time.monotonic() < deadline:
            try:
                result = results.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(result, Exception):
                raise result
            return result
        raise FaceVerificationError("La captura facial excedió el tiempo de espera.")

    def verify(self, voter_ref: str, cancel: threading.Event) -> StepResult:
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.", auth_type="FACE")

        try:
            data = self.api.face_challenge(voter_ref)
            challenge = data["challenge"]
            records = data["records"]
            if len(records) != 1:
                raise FaceVerificationError("El servicio no limitó el registro facial al votante de la sesión.")
        except ApiError as exc:
            if exc.status_code == 423:
                return StepResult(
                    False,
                    "El dispositivo está bloqueado por motivos de seguridad.",
                    attempts_remaining=0,
                    is_locked=True,
                    auth_type="FACE",
                    error_kind="locked",
                )
            return StepResult(
                False,
                "Error de comunicación con el servicio facial. Intente de nuevo.",
                auth_type="FACE",
                error_kind="comm_error",
            )
        except Exception:
            return StepResult(
                False,
                "Error al preparar la verificación facial. Intente de nuevo.",
                auth_type="FACE",
                error_kind="comm_error",
            )

        try:
            captured = self._read_face(cancel)
        except FaceRejected as exc:
            kind = "multiple_faces" if "más de un rostro" in str(exc).lower() else "no_face"
            return StepResult(False, str(exc), auth_type="FACE", error_kind=kind)
        except FaceVerificationError as exc:
            return StepResult(False, str(exc), auth_type="FACE", error_kind="capture_error")
        except Exception:
            return StepResult(False, "No se pudo capturar el rostro. Revise la cámara.",
                              auth_type="FACE", error_kind="capture_error")
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.", auth_type="FACE")

        try:
            match = self.matcher(captured, records)
            matched, voter_id = True, int(match.voter_id)
        except FaceRejected:
            matched, voter_id = False, None
        except Exception:
            return StepResult(False, "No se pudo completar la validación facial. Solicite ayuda.",
                              auth_type="FACE", error_kind="validation_error")

        attestation = face_attestation_signature(self.key, voter_ref, challenge, voter_id, matched)
        try:
            try:
                status = self.api.submit_face(voter_ref, challenge, matched, voter_id, attestation)
            except ApiError as exc:
                if exc.status_code != 401 and exc.status_code is not None:
                    raise
                status = self.api.session_status(voter_ref)
        except ApiError as exc:
            return StepResult(False, str(exc), is_locked=exc.status_code == 423,
                              auth_type="FACE", error_kind="comm_error")
        if status.get("kioskLocked"):
            return StepResult(False, "Dispositivo bloqueado por seguridad.", is_locked=True, auth_type="FACE")
        if status.get("faceOk") is True:
            encender_rostro()
            return StepResult(True, "Rostro verificado", auth_type="FACE")
        if not matched:
            return StepResult(False, "El rostro no coincide con la identidad registrada.",
                              attempts_remaining=status.get("faceAttemptsRemaining"),
                              auth_type="FACE", error_kind="mismatch")
        return StepResult(False, "No se pudo confirmar el resultado facial. Intente de nuevo.",
                          auth_type="FACE", error_kind="comm_error")
