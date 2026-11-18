"""Pruebas de bloqueo, evidencia y desbloqueo del Kiosk."""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import unittest
import uuid

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import Mock, patch
from PIL import Image

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import Session, select

from tests.test_backend import backend
from common.hmac_protocol import (
    face_attestation_signature, fingerprint_request_signature,
    nfc_response_signature,
)
from face_crypto import encrypt_embedding
from kiosk_ui.core.controller import Services, VotingController
from kiosk_ui.core.models import Phase
from kiosk_ui.adapters.mock import MockKit


class SecurityKioskIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.sequence = 0

    @classmethod
    def tearDownClass(cls):
        backend.engine.dispose()

    def setUp(self):
        env = patch.dict(os.environ, {"FINGERPRINT_HMAC_KEY": "33" * 32, "FACE_ATTESTATION_KEY": "44" * 32,
                                     "NFC_HMAC_KEY": "55" * 32})
        env.start()
        self.addCleanup(env.stop)
        self.key = bytes.fromhex(os.environ["FINGERPRINT_HMAC_KEY"])
        with Session(backend.engine) as db:
            for model in (
                backend.IncidentPhoto, backend.KioskUnlockAudit, backend.SecurityIncident, backend.KioskLock, backend.AdminCard,
                backend.DeviceNonce, backend.DeviceReplayGuard, backend.Ballot,
                backend.FingerprintCommand, backend.VoteSession, backend.Voter,
                backend.Candidate,
            ):
                db.exec(delete(model))
            db.commit()

            # Enrolar votante de prueba
            self.voter = backend.Voter(
                fullName="Votante de Prueba",
                cardUid="04A1B2C3",
                fingerprintSlot=1,
                faceEmbedding=encrypt_embedding([0.0] * 128),
                stateName="ESTADO",
                municipalityName="MUNICIPIO",
                isEnabled=True,
                hasVoted=False,
            )
            db.add(self.voter)

            # Enrolar tarjeta de administrador autorizada
            self.admin_card = backend.AdminCard(
                cardUid="AABBCCDD",
                adminName="Administrador Electoral Central",
                isEnabled=True,
                createdAt=backend.getUtcNow(),
            )
            db.add(self.admin_card)

            # Enrolar candidatos
            db.add_all([
                backend.Candidate(name="Alcalde A", office="MAYOR", party="PARTIDO_A", stateName="ESTADO", municipalityName="MUNICIPIO"),
                backend.Candidate(name="Gobernador B", office="GOVERNOR", party="PARTIDO_B", stateName="ESTADO"),
                backend.Candidate(name="Presidente C", office="PRESIDENT", party="PARTIDO_C"),
            ])
            db.commit()
            db.refresh(self.voter)
            self.voter_id = self.voter.id

    def kiosk(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Device-Key"] = "test-kiosk-key"
        headers.setdefault("X-Device-Id", "kiosk-01")
        return self.client.request(method, path, headers=headers, **kwargs)

    def admin(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Admin-Key"] = "test-admin-key"
        return self.client.request(method, path, headers=headers, **kwargs)

    def device_fp(self, method, path, payload=None):
        self.sequence += 1
        content = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        signature = fingerprint_request_signature(
            self.key, method, path, content, "fingerprint-esp32-01",
            timestamp, nonce, self.sequence,
        )
        headers = {
            "X-Device-Id": "fingerprint-esp32-01",
            "X-Timestamp": str(timestamp),
            "X-Nonce": nonce,
            "X-Sequence": str(self.sequence),
            "X-Signature": signature,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return self.client.request(method, path, headers=headers, content=content)

    def start_session(self, card_uid="04A1B2C3"):
        return self.kiosk("POST", "/api/v1/session/start", json={"cardUid": card_uid})

    def request_and_fail_fp(self, session_id, slot=99):
        cmd = self.kiosk("POST", f"/api/v1/session/{session_id}/fingerprint-command")
        self.assertEqual(cmd.status_code, 200)
        command_id = cmd.json()["commandId"]
        return self.device_fp("POST", f"/api/v1/session/{session_id}/fingerprint", {
            "commandId": command_id,
            "fingerprintSlot": slot,
        })

    # ==========================================================================
    # 1. UX Y MANEJO DE INTENTOS DACTILARES
    # ==========================================================================
    def test_fingerprint_single_failure_returns_attempt_count(self):
        """Un intento fallido de huella debe devolver 401 inmediatamente con intento 1 de 5."""
        res_start = self.start_session()
        self.assertEqual(res_start.status_code, 200)
        session_id = res_start.json()["sessionId"]

        # Intento con slot erróneo (huella que no coincide)
        res_fp = self.request_and_fail_fp(session_id, slot=99)
        self.assertEqual(res_fp.status_code, 401)
        self.assertIn("Huella no coincide", res_fp.json()["detail"])
        self.assertIn("Intento 1 de 5", res_fp.json()["detail"])

        # Verificar estado de sesión: intentos restantes = 4, NO bloqueado
        status = self.kiosk("GET", f"/api/v1/session/{session_id}").json()
        self.assertFalse(status["fingerprintOk"])
        self.assertEqual(status["fingerprintAttempts"], 1)
        self.assertEqual(status["fingerprintAttemptsRemaining"], 4)
        self.assertFalse(status["fingerprintLocked"])
        self.assertFalse(status["kioskLocked"])

    # ==========================================================================
    # 2. LÍMITE DE INTENTOS DACTILARES Y BLOQUEO GLOBAL DEL KIOSK
    # ==========================================================================
    def test_fingerprint_exhaustion_locks_global_kiosk(self):
        """Al fallar 5 intentos dactilares, se bloquea el dispositivo Kiosk globalmente."""
        res_start = self.start_session()
        session_id = res_start.json()["sessionId"]

        # Realizar 4 intentos fallidos
        for i in range(1, 5):
            res = self.request_and_fail_fp(session_id, slot=99)
            self.assertEqual(res.status_code, 401)

        # El 5to intento fallido debe bloquear
        res_final = self.request_and_fail_fp(session_id, slot=99)
        self.assertEqual(res_final.status_code, 401)
        self.assertIn("verificacion bloqueada", res_final.json()["detail"])

        self.assertEqual(self.kiosk("GET", f"/api/v1/session/{session_id}").status_code, 423)
        with Session(backend.engine) as db:
            self.assertEqual(backend.getFingerprintAttemptCount(db, session_id), 5)
            self.assertTrue(db.get(backend.VoteSession, session_id).isClosed)

        # Verificar endpoint de estado de bloqueo del Kiosk
        lock_res = self.kiosk("GET", "/api/v1/kiosk/lock")
        self.assertEqual(lock_res.status_code, 200)
        lock_data = lock_res.json()
        self.assertTrue(lock_data["isLocked"])
        self.assertEqual(lock_data["lockedByAttemptType"], "FINGERPRINT")
        self.assertEqual(lock_data["photoStatus"], "PHOTO_PENDING")
        self.assertEqual(len(self.admin("GET", "/api/v1/security/incidents").json()), 1)

    # ==========================================================================
    # 3. LÍMITE DE INTENTOS FACIALES Y BLOQUEO GLOBAL DEL KIOSK
    # ==========================================================================
    def test_face_exhaustion_locks_global_kiosk(self):
        """Al fallar 5 intentos faciales, se bloquea el dispositivo Kiosk globalmente."""
        res_start = self.start_session()
        session_id = res_start.json()["sessionId"]

        self.assertEqual(self.request_and_fail_fp(session_id).status_code, 401)
        # Validar huella correctamente
        cmd = self.kiosk("POST", f"/api/v1/session/{session_id}/fingerprint-command")
        command_id = cmd.json()["commandId"]
        fp_ok = self.device_fp("POST", f"/api/v1/session/{session_id}/fingerprint", {
            "commandId": command_id,
            "fingerprintSlot": 1,
        })
        self.assertEqual(fp_ok.status_code, 200)

        # 5 intentos faciales fallidos
        for attempt in range(1, 6):
            challenge_res = self.kiosk("GET", f"/api/v1/session/{session_id}/face-challenge")
            self.assertEqual(challenge_res.status_code, 200)
            challenge = challenge_res.json()["challenge"]

            attestation = face_attestation_signature(
                bytes.fromhex(os.environ["FACE_ATTESTATION_KEY"]),
                session_id, challenge, self.voter_id, False,
            )
            res_face = self.kiosk("POST", f"/api/v1/session/{session_id}/face", json={
                "challenge": challenge,
                "matched": False,
                "voterId": self.voter_id,
                "attestation": attestation,
            })
            self.assertEqual(res_face.status_code, 401)
            self.assertIn(f"Intento {attempt} de 5", res_face.json()["detail"])
            if attempt < 5:
                status = self.kiosk("GET", f"/api/v1/session/{session_id}").json()
                self.assertEqual(status["faceAttemptsRemaining"], 5 - attempt)
                self.assertEqual(status["fingerprintAttempts"], 1)

        # Verificar bloqueo global tras el 5to intento
        lock_res = self.kiosk("GET", "/api/v1/kiosk/lock")
        self.assertEqual(lock_res.status_code, 200)
        self.assertTrue(lock_res.json()["isLocked"])
        self.assertEqual(lock_res.json()["lockedByAttemptType"], "FACE")

    # ==========================================================================
    # 4. RECHAZO DE OPERACIONES CUANDO EL KIOSK ESTÁ BLOQUEADO (HTTP 423)
    # ==========================================================================
    def test_operations_rejected_with_423_when_locked(self):
        """Cuando el Kiosk está bloqueado, endpoints clave devuelven HTTP 423."""
        # Bloquear el Kiosk explícitamente
        self.kiosk("POST", "/api/v1/kiosk/lock", json={
            "deviceId": "kiosk-01",
            "reason": "Bloqueo de prueba",
            "authType": "MANUAL",
        })

        # Intentar iniciar nueva sesión -> 423
        start_res = self.start_session()
        self.assertEqual(start_res.status_code, 423)
        self.assertIn("bloqueado por seguridad", start_res.json()["detail"])

        # Intentar consultar boleta -> 423
        dummy_session = str(uuid.uuid4())
        ballot_res = self.kiosk("GET", f"/api/v1/session/{dummy_session}/ballot")
        self.assertEqual(ballot_res.status_code, 423)

        # Intentar votar -> 423
        vote_res = self.kiosk("POST", f"/api/v1/session/{dummy_session}/vote", json={
            "presidentId": 1, "governorId": 2, "mayorId": 3,
        })
        self.assertEqual(vote_res.status_code, 423)

    def scan(self, incident_id, uid="AABBCCDD"):
        scan = {
            "deviceId": backend.NFC_DEVICE_ID, "sessionId": incident_id, "uid": uid,
            "sequence": time.time_ns() // 1_000_000, "expiresAt": int(time.time()) + 30,
            "nonce": secrets.token_hex(16), "status": "ok",
        }
        scan["hmac"] = nfc_response_signature(
            b"\x55" * 32, scan["deviceId"], scan["sessionId"], scan["nonce"], scan["sequence"],
            scan["status"], scan["uid"], scan["expiresAt"],
        )
        return {"scan": scan}

    def biometric_incident(self):
        session_id = self.start_session().json()["sessionId"]
        for _ in range(backend.MAX_FINGERPRINT_ATTEMPTS):
            self.assertEqual(self.request_and_fail_fp(session_id).status_code, 401)
        return self.kiosk("GET", "/api/v1/kiosk/lock").json()["incidentId"]

    def test_unlock_requires_authenticated_fresh_signed_card_and_is_audited(self):
        previous_session = self.start_session().json()["sessionId"]
        lock = self.kiosk("POST", "/api/v1/kiosk/lock", json={}).json()
        incident_id = lock["incidentId"]
        with Session(backend.engine) as db:
            self.assertTrue(db.get(backend.KioskLock, backend.DEFAULT_KIOSK_DEVICE_ID).isLocked)
        scan = self.scan(incident_id)
        endpoint = "/api/v1/kiosk/unlock"
        self.assertEqual(self.client.post(endpoint, json=scan).status_code, 401)
        self.assertEqual(self.admin("POST", endpoint, json=scan).status_code, 401)
        self.assertEqual(self.kiosk("POST", endpoint, json={"cardUid": "AABBCCDD"}).status_code, 422)
        self.assertEqual(self.kiosk("POST", endpoint, json=self.scan(incident_id, "FFFFFFFF")).status_code, 403)
        forged = self.scan(incident_id, "FFFFFFFF")
        forged["scan"]["uid"] = "AABBCCDD"
        self.assertEqual(self.kiosk("POST", endpoint, json=forged).status_code, 403)
        forged["scan"]["hmac"] = "z" * 64
        self.assertEqual(self.kiosk("POST", endpoint, json=forged).status_code, 422)
        self.assertEqual(self.kiosk("POST", "/api/v1/session/start",
                                    headers={"X-Device-Id": "other"}, json={"cardUid": "04A1B2C3"}).status_code, 423)
        self.assertEqual(self.kiosk("POST", endpoint, json=scan).status_code, 200)
        self.assertEqual(self.kiosk("POST", endpoint, json=scan).status_code, 200)
        with Session(backend.engine) as db:
            audits = db.exec(select(backend.KioskUnlockAudit)).all()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].adminName, "Administrador Electoral Central")
        self.assertEqual(self.kiosk("GET", f"/api/v1/session/{previous_session}").status_code, 410)
        self.assertEqual(self.start_session().status_code, 200)
        self.kiosk("POST", "/api/v1/kiosk/lock", json={})
        self.assertEqual(self.kiosk("POST", endpoint, json=scan).status_code, 403)

    def test_photo_auth_validation_idempotence_and_retention(self):
        incident_id = self.biometric_incident()
        output = BytesIO()
        Image.new("RGB", (4, 4), "red").save(output, format="JPEG")
        jpeg = output.getvalue()
        endpoint = "/api/v1/security/incidents"
        path = f"{endpoint}/{incident_id}/photo"
        payload = {"id": incident_id, "photoBase64": base64.b64encode(jpeg).decode()}
        self.assertEqual(self.kiosk("POST", endpoint, json={**payload, "photoBase64": "AAAA"}).status_code, 422)
        self.assertEqual(self.kiosk("POST", endpoint, json={**payload, "id": str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(self.kiosk("POST", endpoint, json=payload).json()["status"], "PHOTO_STORED")
        self.assertEqual(self.kiosk("POST", endpoint, json={"id": incident_id, "captureFailed": True}).json()["status"], "PHOTO_STORED")
        self.assertEqual(self.kiosk("GET", path).status_code, 401)
        photo = self.admin("GET", path)
        self.assertEqual(photo.content, jpeg)
        self.assertEqual(photo.headers["cache-control"], "no-store")
        with Session(backend.engine) as db:
            photo = db.get(backend.IncidentPhoto, incident_id)
            photo.capturedAt = backend.photo_cutoff()
            db.commit()
        self.assertEqual(self.admin("GET", path).status_code, 404)
        self.assertEqual(self.admin("DELETE", f"{endpoint}/expired-photos").json(), {"deleted": 1})
        self.assertFalse(self.admin("GET", endpoint).json()[0]["hasPhoto"])

    def test_camera_failure_keeps_lock(self):
        incident_id = self.biometric_incident()
        response = self.kiosk("POST", "/api/v1/security/incidents",
                              json={"id": incident_id, "captureFailed": True})
        self.assertEqual(response.json()["status"], "CAMERA_ERROR")
        self.assertEqual(self.start_session().status_code, 423)

    def test_admin_can_enroll_and_disable_card(self):
        path = "/api/v1/admin/cards"
        card = {"cardUid": "01020304", "adminName": "Supervisor"}
        self.assertEqual(self.kiosk("POST", path, json=card).status_code, 401)
        self.assertEqual(self.admin("POST", path, json=card).status_code, 200)
        self.assertEqual(self.admin("POST", path, json={**card, "isEnabled": False}).status_code, 200)
        cards = {item["cardUid"]: item for item in self.admin("GET", path).json()}
        self.assertFalse(cards[card["cardUid"]]["isEnabled"])
        lock = self.kiosk("POST", "/api/v1/kiosk/lock", json={}).json()
        self.assertEqual(self.kiosk("POST", "/api/v1/kiosk/unlock",
                                    json=self.scan(lock["incidentId"], card["cardUid"])).status_code, 403)

    def test_concurrent_lock_is_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.kiosk("POST", "/api/v1/kiosk/lock", json={}), range(4)))
        self.assertTrue(all(res.status_code == 200 for res in results))
        self.assertEqual(len({res.json()["incidentId"] for res in results}), 1)

    def pump_until(self, controller, predicate):
        end = time.monotonic() + 5
        while not predicate() and time.monotonic() < end:
            controller.pump()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_controller_recovers_existing_lock_and_retries_same_photo(self):
        kit = MockKit(delay=0.01)
        kit.lock("Prueba de bloqueo persistente")
        report = Mock(side_effect=[ConnectionError(), {"status": "PHOTO_STORED"}])
        kit.backend.report_incident = report
        capture = Mock(return_value=b"jpeg")
        controller = VotingController(Services(kit.card_reader, kit.fingerprint, kit.face, kit.backend, capture))
        self.addCleanup(controller.shutdown)
        controller.reset()
        self.pump_until(controller, lambda: controller.phase is Phase.LOCKED)
        controller.reset()
        self.assertIs(controller.phase, Phase.LOCKED)
        self.pump_until(controller, lambda: controller.photo_status == "PHOTO_STORED")
        capture.assert_called_once_with()
        self.assertEqual([call.args for call in report.call_args_list], [(kit.incident_id, b"jpeg")] * 2)
        kit.tap_admin_card("INVALIDA")
        self.pump_until(controller, lambda: "Tarjeta no autorizada" in controller.admin_unlock_message)
        kit.tap_admin_card("ADMIN001")
        self.pump_until(controller, lambda: controller.phase is Phase.IDLE)
        self.assertFalse(controller.is_locked)

    def test_controller_does_not_read_voter_card_without_backend(self):
        kit = MockKit(delay=0.01)
        original = kit.backend.check_lock
        kit.backend.check_lock = Mock(side_effect=[ConnectionError(), original()])
        controller = VotingController(kit.services())
        self.addCleanup(controller.shutdown)
        controller.reset()
        self.pump_until(controller, lambda: controller.phase is Phase.AUTH)
        self.assertFalse(kit.waiting.is_set())
        controller.retry_step()
        self.pump_until(controller, kit.waiting.is_set)
