"""Composición de adaptadores reales; la UI no conoce hardware ni red."""
from __future__ import annotations

from kiosk_ui.core.controller import Services
from kiosk_ui.adapters.real.api_client import VotingApi
from kiosk_ui.adapters.real.nfc import NfcCardReader
from kiosk_ui.adapters.real.biometrics import FaceVerifier, FingerprintVerifier


def build_real_services() -> Services:
    api = VotingApi()
    return Services(
        card_reader=NfcCardReader(api),
        fingerprint=FingerprintVerifier(api),
        face=FaceVerifier(api),
        backend=api,
    )
