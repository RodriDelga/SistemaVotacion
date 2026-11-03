"""Integración FastAPI con SQLite temporal y datos totalmente ficticios."""
from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_TMP.name) / "test.db")
os.environ["DEVICE_KEY"] = "test-kiosk-key"
os.environ["ADMIN_KEY"] = "test-admin-key"
os.environ["FINGERPRINT_HMAC_KEY"] = "11" * 32
os.environ["FACE_ATTESTATION_KEY"] = "22" * 32
_face_key = base64.b64encode(b"F" * 32).decode()
os.environ["FACE_ENCRYPTION_KEYS"] = json.dumps({"test": _face_key})
os.environ["FACE_ACTIVE_KEY_ID"] = "test"
os.environ["SESSION_TIMEOUT_SECONDS"] = "300"

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import Session

import backend
from common.hmac_protocol import (
    face_attestation_signature, fingerprint_request_signature,
    fingerprint_response_signature, signature_matches,
)
from face_crypto import encrypt_embedding


class BackendIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.key = bytes.fromhex(os.environ["FINGERPRINT_HMAC_KEY"])
        cls.sequence = 0

    def setUp(self):
        with Session(backend.engine) as db:
            for model in (
                backend.DeviceNonce, backend.DeviceReplayGuard, backend.Ballot,
                backend.FingerprintCommand, backend.VoteSession, backend.Voter,
                backend.Candidate,
            ):
                db.exec(delete(model))
            db.commit()
        self.voter = backend.Voter(
            fullName="Persona Ficticia", cardUid="04A1B2C3", fingerprintSlot=1,
            faceEmbedding=encrypt_embedding([0.0] * 128), stateName="ESTADO",
            municipalityName="MUNICIPIO",
        )
        with Session(backend.engine) as db:
            db.add(self.voter)
            db.commit()
            db.refresh(self.voter)
            self.voter_id = self.voter.id
            db.add_all([
                backend.Candidate(name="Alcaldía Demo", office="MAYOR", stateName="ESTADO", municipalityName="MUNICIPIO"),
                backend.Candidate(name="Gobernatura Demo", office="GOVERNOR", stateName="ESTADO"),
                backend.Candidate(name="Presidencia Demo", office="PRESIDENT"),
                backend.Candidate(name="Otra Región", office="MAYOR", stateName="OTRO", municipalityName="OTRO"),
            ])
            db.commit()
            self.candidates = db.exec(backend.select(backend.Candidate).order_by(backend.Candidate.id)).all()
            self.ids = {c.name: c.id for c in self.candidates}

    def kiosk(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Device-Key"] = "test-kiosk-key"
        return self.client.request(method, path, headers=headers, **kwargs)

    def device(self, method, path, payload=None, tamper=False, replay=None):
        if replay:
            headers, content = replay
            return self.client.request(method, path, headers=headers, content=content), replay
        self.sequence += 1
        content = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        signature = fingerprint_request_signature(
            self.key, method, path, content, "fingerprint-esp32-01",
            timestamp, nonce, self.sequence,
        )
        if tamper:
            signature = "00" * 32
        headers = {
            "X-Device-Id": "fingerprint-esp32-01", "X-Timestamp": str(timestamp),
            "X-Nonce": nonce, "X-Sequence": str(self.sequence), "X-Signature": signature,
        }
        response = self.client.request(method, path, headers=headers, content=content)
        if response.headers.get("X-Signature"):
            expected = fingerprint_response_signature(
                self.key, response.content, "fingerprint-esp32-01",
                int(response.headers["X-Timestamp"]), nonce, response.headers["X-Nonce"],
            )
            self.assertTrue(signature_matches(response.headers["X-Signature"], expected))
        return response, (headers, content)

    def start(self):
        response = self.kiosk("POST", "/api/v1/session/start", json={"cardUid": "04:A1:B2:C3"})
        self.assertEqual(response.status_code, 200)
        return response.json()["sessionId"]

    def fingerprint(self, session_id, slot=1):
        command = self.kiosk("POST", f"/api/v1/session/{session_id}/fingerprint-command")
        self.assertEqual(command.status_code, 200)
        command_id = command.json()["commandId"]
        pending, _ = self.device("GET", "/api/v1/device/fingerprint-command/pending")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["commandId"], command_id)
        return self.device(
            "POST", f"/api/v1/session/{session_id}/fingerprint",
            {"commandId": command_id, "fingerprintSlot": slot},
        )

    def test_complete_flow_order_privacy_and_duplicate(self):
        session_id = self.start()
        early = self.kiosk("GET", f"/api/v1/session/{session_id}/ballot")
        self.assertEqual(early.status_code, 403)

        result, replay = self.fingerprint(session_id)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["fingerprintOk"])
        repeated, _ = self.device(
            "POST", f"/api/v1/session/{session_id}/fingerprint", replay=replay
        )
        self.assertIn(repeated.status_code, (401, 409))

        challenge = self.kiosk("GET", f"/api/v1/session/{session_id}/face-challenge").json()
        self.assertEqual(len(challenge["records"]), 1)
        self.assertEqual(challenge["records"][0]["voterId"], self.voter_id)
        bad = self.kiosk("POST", f"/api/v1/session/{session_id}/face", json={
            "challenge": challenge["challenge"], "matched": True,
            "voterId": self.voter_id, "attestation": "00" * 32,
        })
        self.assertEqual(bad.status_code, 401)
        attestation = face_attestation_signature(
            b"\x22" * 32, session_id, challenge["challenge"], self.voter_id, True
        )
        face = self.kiosk("POST", f"/api/v1/session/{session_id}/face", json={
            "challenge": challenge["challenge"], "matched": True,
            "voterId": self.voter_id, "attestation": attestation,
        })
        self.assertEqual(face.status_code, 200)
        self.assertTrue(face.json()["readyToVote"])

        ballot = self.kiosk("GET", f"/api/v1/session/{session_id}/ballot")
        self.assertEqual(ballot.status_code, 200)
        self.assertEqual([x["office"] for x in ballot.json()["offices"]],
                         ["MAYOR", "GOVERNOR", "PRESIDENT"])
        self.assertNotIn("Otra Región", str(ballot.json()))
        vote = self.kiosk("POST", f"/api/v1/session/{session_id}/vote", json={
            "mayorId": self.ids["Alcaldía Demo"],
            "governorId": self.ids["Gobernatura Demo"],
            "presidentId": self.ids["Presidencia Demo"],
        })
        self.assertEqual(vote.status_code, 200)
        self.assertEqual(vote.json()["status"], "voteRecorded")
        duplicate = self.kiosk("POST", f"/api/v1/session/{session_id}/vote", json={
            "mayorId": self.ids["Alcaldía Demo"],
            "governorId": self.ids["Gobernatura Demo"],
            "presidentId": self.ids["Presidencia Demo"],
        })
        self.assertEqual(duplicate.status_code, 410)
        new_session = self.kiosk("POST", "/api/v1/session/start", json={"cardUid": "04A1B2C3"})
        self.assertEqual(new_session.status_code, 403)
        with Session(backend.engine) as db:
            rows = db.exec(backend.select(backend.Ballot)).all()
            self.assertEqual(len(rows), 3)
            self.assertFalse(hasattr(rows[0], "voterId"))

    def test_fingerprint_rejections_and_hmac(self):
        session_id = self.start()
        bad, _ = self.device("GET", "/api/v1/device/fingerprint-command/pending", tamper=True)
        self.assertEqual(bad.status_code, 401)
        result, _ = self.fingerprint(session_id, slot=2)
        self.assertEqual(result.status_code, 401)
        status = self.kiosk("GET", f"/api/v1/session/{session_id}")
        self.assertFalse(status.json()["fingerprintOk"])
        self.assertEqual(status.json()["fingerprintAttempts"], 1)

    def test_disabled_unknown_and_expired_session(self):
        unknown = self.kiosk("POST", "/api/v1/session/start", json={"cardUid": "FFFFFFFF"})
        self.assertEqual(unknown.status_code, 404)
        with Session(backend.engine) as db:
            voter = db.get(backend.Voter, self.voter_id)
            voter.isEnabled = False
            db.add(voter)
            db.commit()
        disabled = self.kiosk("POST", "/api/v1/session/start", json={"cardUid": "04A1B2C3"})
        self.assertEqual(disabled.status_code, 403)
        with Session(backend.engine) as db:
            voter = db.get(backend.Voter, self.voter_id)
            voter.isEnabled = True
            db.add(voter)
            db.commit()
        session_id = self.start()
        with Session(backend.engine) as db:
            vote_session = db.get(backend.VoteSession, session_id)
            vote_session.createdAt = backend.getUtcNow() - backend.timedelta(seconds=1000)
            db.add(vote_session)
            db.commit()
        expired = self.kiosk("GET", f"/api/v1/session/{session_id}")
        self.assertEqual(expired.status_code, 410)

    def test_wrong_region_candidate_is_rejected(self):
        session_id = self.start()
        result, _ = self.fingerprint(session_id)
        self.assertEqual(result.status_code, 200)
        challenge = self.kiosk("GET", f"/api/v1/session/{session_id}/face-challenge").json()
        attestation = face_attestation_signature(
            b"\x22" * 32, session_id, challenge["challenge"], self.voter_id, True
        )
        self.kiosk("POST", f"/api/v1/session/{session_id}/face", json={
            "challenge": challenge["challenge"], "matched": True,
            "voterId": self.voter_id, "attestation": attestation,
        })
        vote = self.kiosk("POST", f"/api/v1/session/{session_id}/vote", json={
            "mayorId": self.ids["Otra Región"],
            "governorId": self.ids["Gobernatura Demo"],
            "presidentId": self.ids["Presidencia Demo"],
        })
        self.assertEqual(vote.status_code, 422)
        with Session(backend.engine) as db:
            self.assertEqual(len(db.exec(backend.select(backend.Ballot)).all()), 0)


if __name__ == "__main__":
    unittest.main()
