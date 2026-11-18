"""Adaptador WiFi para la ESP32 dedicada exclusivamente al lector PN532."""
from __future__ import annotations
# En kiosk_ui/adapters/real/nfc.py
from kiosk_ui.led_control import encender_tarjeta

import os
import re
import secrets
import threading
import time
import uuid
from typing import Optional

import requests

from common.hmac_protocol import (
    load_hex_key, nfc_command_signature, nfc_response_signature, signature_matches,
)
from kiosk_ui.core.models import StepResult
from kiosk_ui.adapters.real.api_client import ApiError, VotingApi

_UID_RE = re.compile(r"^[0-9A-F]{8,20}$")


class NfcCardReader:
    def __init__(self, api: VotingApi, base_url: Optional[str] = None,
                 key_hex: Optional[str] = None, device_id: Optional[str] = None) -> None:
        self.api = api
        self.base_url = (base_url or os.getenv("NFC_ESP32_URL", "http://192.168.1.51")).rstrip("/")
        if key_hex is None:
            self.key = load_hex_key("NFC_HMAC_KEY")
        else:
            try:
                self.key = bytes.fromhex(key_hex)
            except ValueError as exc:
                raise ValueError("Clave NFC inválida") from exc
            if len(self.key) != 32:
                raise ValueError("La clave NFC debe tener 32 bytes")
        self.device_id = device_id or os.getenv("NFC_DEVICE_ID", "nfc-esp32-01")
        self.connect_timeout = float(os.getenv("NFC_CONNECT_TIMEOUT_SECONDS", "3"))
        self.read_timeout = float(os.getenv("NFC_READ_TIMEOUT_SECONDS", "35"))
        self.command_ttl = int(os.getenv("NFC_COMMAND_TTL_SECONDS", "30"))
        self._http = requests.Session()
        self._io_lock = threading.Lock()

    def wait_for_card(self, cancel: threading.Event) -> StepResult:
        try:
            scan = self._scan(cancel, str(uuid.uuid4()))
            if scan is None:
                return StepResult(False, "No se detectó una tarjeta a tiempo. Intente de nuevo.")
            backend_session = self.api.start_session(scan["uid"])
        except ApiError as exc:
            if exc.status_code == 423:
                return StepResult(False, "El dispositivo está bloqueado por seguridad.", is_locked=True)
            if exc.status_code == 404:
                return StepResult(False, "La tarjeta no está asociada a un votante habilitado.")
            if exc.status_code == 403:
                return StepResult(False, "La tarjeta no permite iniciar una votación. Solicite ayuda.")
            return StepResult(False, str(exc))
        encender_tarjeta()
        return StepResult(True, "Tarjeta validada", backend_session)

    def read_admin_card(self, cancel: threading.Event, incident_id: str) -> Optional[dict]:
        return self._scan(cancel, incident_id)

    def probe_health(self) -> bool | None:
        # El servidor del ESP32 atiende una petición a la vez.
        if not self._io_lock.acquire(blocking=False):
            return None
        try:
            response = self._http.get(
                self.base_url + "/v1/nfc/health", timeout=(1, 3), allow_redirects=False,
            )
            if response.status_code == 404:  # firmware anterior a la consulta de estado
                return None
            return response.status_code == 200 and response.json() == {"status": "online"}
        except (requests.RequestException, ValueError):
            return False
        finally:
            self._io_lock.release()

    def _scan(self, cancel: threading.Event, session_id: str) -> Optional[dict]:
        with self._io_lock:
            if cancel.is_set():
                return None
            nonce = secrets.token_hex(16)
            sequence = time.time_ns() // 1_000_000
            expires_at = int(time.time()) + self.command_ttl
            payload = {
                "deviceId": self.device_id, "sessionId": session_id, "action": "scan",
                "nonce": nonce, "sequence": sequence, "expiresAt": expires_at,
                "hmac": nfc_command_signature(
                    self.key, self.device_id, session_id, "scan", nonce, sequence, expires_at,
                ),
            }
            try:
                response = self._http.post(
                    self.base_url + "/v1/nfc/scan", json=payload,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise ApiError("No se pudo comunicar con el lector NFC. Solicite ayuda.") from exc
        if cancel.is_set():
            return None
        if response.status_code != 200 or not isinstance(data, dict):
            raise ApiError("El lector NFC rechazó la orden. Solicite ayuda.")
        if not self._valid_response(data, session_id, nonce, sequence):
            raise ApiError("La respuesta del lector NFC no es auténtica.")
        if data["status"] == "timeout":
            return None
        if data["status"] != "ok" or not _UID_RE.fullmatch(data["uid"]):
            raise ApiError("No se pudo leer una tarjeta NFC válida.")
        return data

    def _valid_response(self, data: dict, session_id: str, nonce: str, sequence: int) -> bool:
        uid = data.get("uid", "")
        status = data.get("status")
        expires_at = data.get("expiresAt")
        if (
            data.get("deviceId") != self.device_id
            or data.get("sessionId") != session_id
            or data.get("nonce") != nonce
            or data.get("sequence") != sequence
            or not isinstance(status, str) or not isinstance(uid, str)
            or not isinstance(expires_at, int) or expires_at < int(time.time())
        ):
            return False
        expected = nfc_response_signature(
            self.key, self.device_id, session_id, nonce, sequence, status, uid, expires_at
        )
        return signature_matches(data.get("hmac", ""), expected)
