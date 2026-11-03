"""Pruebas simuladas de los adaptadores reales, sin abrir red ni cámara."""
from __future__ import annotations

import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from common.hmac_protocol import face_attestation_signature, nfc_response_signature
from kiosk_ui.adapters.real.biometrics import FaceVerifier, FingerprintVerifier
from kiosk_ui.adapters.real.nfc import NfcCardReader
from kiosk_ui.core.models import StepResult
from simulators.nfc_server import build_handler


class FakeApi:
    def __init__(self):
        self.uid = None
        self.face_payload = None

    def start_session(self, uid):
        self.uid = uid
        return "backend-session"

    def face_challenge(self, ref):
        return {"challenge": "c" * 32, "records": [{"voterId": 7, "faceEmbedding": "encrypted"}]}

    def submit_face(self, ref, challenge, matched, voter_id, attestation):
        expected = face_attestation_signature(b"\x22" * 32, ref, challenge, voter_id, matched)
        if attestation != expected:
            return {"faceOk": False}
        self.face_payload = (matched, voter_id)
        return {"faceOk": matched}


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeNfcHttp:
    def __init__(self, key, alter=False, uid="04A1B2C3", status="ok", wrong_nonce=False):
        self.key = key
        self.alter = alter
        self.uid = uid
        self.status = status
        self.wrong_nonce = wrong_nonce

    def post(self, url, json, timeout):
        assert url.endswith("/v1/nfc/scan")
        expires = int(time.time()) + 10
        uid = self.uid
        signature = nfc_response_signature(
            self.key, json["deviceId"], json["sessionId"], json["nonce"],
            json["sequence"], self.status, uid, expires,
        )
        payload = {
            "deviceId": json["deviceId"], "sessionId": json["sessionId"],
            "nonce": "00" * 16 if self.wrong_nonce else json["nonce"],
            "sequence": json["sequence"], "status": self.status,
            "uid": uid, "expiresAt": expires, "hmac": signature,
        }
        if self.alter:
            payload["uid"] = "FFFFFFFF"
        return FakeResponse(payload)


class NfcAdapterTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()

    def reader(self, alter=False):
        reader = NfcCardReader(self.api, "http://nfc.test", "11" * 32, "nfc-test")
        reader._http = FakeNfcHttp(reader.key, alter)
        return reader

    def test_valid_signed_card_starts_backend_session(self):
        result = self.reader().wait_for_card(threading.Event())
        self.assertTrue(result.ok)
        self.assertEqual(result.voter_ref, "backend-session")
        self.assertEqual(self.api.uid, "04A1B2C3")

    def test_altered_response_is_not_accepted(self):
        result = self.reader(alter=True).wait_for_card(threading.Event())
        self.assertFalse(result.ok)
        self.assertIsNone(self.api.uid)

    def test_timeout_invalid_uid_and_wrong_nonce(self):
        for kwargs in ({"status": "timeout"}, {"uid": "AA"}, {"wrong_nonce": True}):
            with self.subTest(kwargs=kwargs):
                api = FakeApi()
                reader = NfcCardReader(api, "http://nfc.test", "11" * 32, "nfc-test")
                reader._http = FakeNfcHttp(reader.key, **kwargs)
                self.assertFalse(reader.wait_for_card(threading.Event()).ok)
                self.assertIsNone(api.uid)

    def test_disconnect_and_cancellation(self):
        reader = self.reader()
        reader._http.post = Mock(side_effect=requests.ConnectionError())
        self.assertFalse(reader.wait_for_card(threading.Event()).ok)
        cancelled = threading.Event()
        cancelled.set()
        self.assertFalse(reader.wait_for_card(cancelled).ok)


class NfcHttpIntegrationTest(unittest.TestCase):
    def test_real_http_roundtrip_with_simulator(self):
        key = b"\x11" * 32
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), build_handler(key, "nfc-test", "04A1B2C3", "ok")
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = FakeApi()
            reader = NfcCardReader(
                api, f"http://127.0.0.1:{server.server_port}", "11" * 32, "nfc-test"
            )
            result = reader.wait_for_card(threading.Event())
            self.assertTrue(result.ok)
            self.assertEqual(api.uid, "04A1B2C3")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class FakeCamera:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def capture_single_encoding(self):
        return [0.0] * 128


class BiometricAdapterTest(unittest.TestCase):
    def test_face_attestation_is_bound_to_session(self):
        api = FakeApi()
        verifier = FaceVerifier(
            api, "22" * 32, camera_factory=FakeCamera,
            matcher=lambda captured, records: SimpleNamespace(voter_id=7),
        )
        result = verifier.verify("backend-session", threading.Event())
        self.assertTrue(result.ok)
        self.assertEqual(api.face_payload, (True, 7))

    def test_fingerprint_only_accepts_backend_confirmation(self):
        class Api:
            calls = 0
            def request_fingerprint_command(self, ref):
                return {"commandId": "command"}
            def session_status(self, ref):
                self.calls += 1
                return {"fingerprintOk": self.calls > 1, "fingerprintCommandPending": True}
        result = FingerprintVerifier(Api(), wait_s=1, poll_s=0.001).verify("ref", threading.Event())
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
