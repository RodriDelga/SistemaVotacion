"""Adaptador WiFi para la ESP32 dedicada exclusivamente al lector PN532."""
from __future__ import annotations
# En kiosk_ui/adapters/real/nfc.py
from kiosk_ui.led_control import encender_tarjeta

import logging
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
log = logging.getLogger(__name__)


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

    def wait_for_card(self, cancel: threading.Event) -> StepResult:
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.")
        session_id = str(uuid.uuid4())
        nonce = secrets.token_hex(16)
        sequence = time.time_ns() // 1_000_000
        expires_at = int(time.time()) + self.command_ttl
        payload = {
            "deviceId": self.device_id, "sessionId": session_id, "action": "scan",
            "nonce": nonce, "sequence": sequence, "expiresAt": expires_at,
        }
        payload["hmac"] = nfc_command_signature(
            self.key, self.device_id, session_id, "scan", nonce, sequence, expires_at
        )
        try:
            response = self._http.post(
                self.base_url + "/v1/nfc/scan", json=payload,
                timeout=(self.connect_timeout, self.read_timeout),
            )
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("NFC comunicacion fallo: %r", exc)
            return StepResult(False, "No se pudo comunicar con el lector NFC. Solicite ayuda.")
        log.warning("NFC http=%s status=%s detail=%s", response.status_code,
                    data.get("status") if isinstance(data, dict) else None,
                    data.get("detail") if isinstance(data, dict) else None)
        if cancel.is_set():
            return StepResult(False, "Operación cancelada.")
        if response.status_code != 200 or not isinstance(data, dict):
            return StepResult(False, "El lector NFC rechazó la orden. Solicite ayuda.")
        if not self._valid_response(data, session_id, nonce, sequence):
            log.warning("NFC respuesta no valida: deviceId=%r sessionOk=%s nonceOk=%s seqOk=%s expiresAt=%r ahora=%s",
                        data.get("deviceId"), data.get("sessionId") == session_id,
                        data.get("nonce") == nonce, data.get("sequence") == sequence,
                        data.get("expiresAt"), int(time.time()))
            return StepResult(False, "La respuesta del lector NFC no es auténtica. Operación detenida.")
        status = data.get("status")
        if status == "timeout":
            return StepResult(False, "No se detectó una tarjeta a tiempo. Intente de nuevo.")
        if status != "ok":
            return StepResult(False, "No se pudo leer la tarjeta. Intente de nuevo o solicite ayuda.")
        uid = data.get("uid", "")
        log.warning("NFC uid largo=%s", len(uid) if isinstance(uid, str) else None)
        if not isinstance(uid, str) or not _UID_RE.fullmatch(uid):
            return StepResult(False, "La lectura NFC está incompleta o es inválida.")
        try:
            backend_session = self.api.start_session(uid)
            encender_tarjeta()
            return StepResult(True, "Tarjeta validada", backend_session)
        except ApiError as exc:
            log.warning("start_session fallo: status=%s msg=%s", exc.status_code, exc)
            if exc.status_code == 404:
                return StepResult(False, "La tarjeta no está asociada a un votante habilitado.")
            if exc.status_code == 403:
                return StepResult(False, "La tarjeta no permite iniciar una votación. Solicite ayuda.")
            return StepResult(False, "No se pudo validar la tarjeta con el servicio local.")
        return StepResult(True, "Tarjeta validada", backend_session)

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
