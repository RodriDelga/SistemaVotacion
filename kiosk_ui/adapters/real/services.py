"""Composición de adaptadores reales; la UI no conoce hardware ni red."""
from __future__ import annotations

from functools import partial

from kiosk_ui.core.controller import Services
from kiosk_ui.adapters.real.api_client import VotingApi
from kiosk_ui.adapters.real.heartbeat import run_heartbeat
from kiosk_ui.adapters.real.nfc import NfcCardReader
from kiosk_ui.adapters.real.biometrics import FaceVerifier, FingerprintVerifier, capture_incident_photo


def build_real_services() -> Services:
    api = VotingApi()
    card_reader = NfcCardReader(api)
    return Services(
        card_reader=card_reader,
        fingerprint=FingerprintVerifier(api),
        face=FaceVerifier(api),
        backend=api,
        capture_incident_photo=capture_incident_photo,
        run_heartbeat=partial(run_heartbeat, nfc=card_reader),
    )
