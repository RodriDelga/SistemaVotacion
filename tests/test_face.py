"""Pruebas de AES-256-GCM y comparación facial sin cámara ni datos reales."""
from __future__ import annotations

import base64
import json
import os
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np

os.environ["FACE_ENCRYPTION_KEYS"] = json.dumps({
    "old": base64.b64encode(b"A" * 32).decode(),
    "active": base64.b64encode(b"B" * 32).decode(),
})
os.environ["FACE_ACTIVE_KEY_ID"] = "active"

from face_crypto import FaceCryptoError, decrypt_embedding, encrypt_embedding, validate_envelope_format
from face_local import FaceCamera, FaceRejected, FaceVerificationError, identify_face


class FaceCryptoTest(unittest.TestCase):
    def test_roundtrip_rotation_and_aad(self):
        values = np.linspace(-1, 1, 128)
        envelope = encrypt_embedding(values)
        validate_envelope_format(envelope)
        self.assertTrue(np.allclose(decrypt_embedding(envelope), values))
        payload = json.loads(envelope)
        self.assertEqual(len(base64.b64decode(payload["nonce"])), 12)
        self.assertEqual(len(base64.b64decode(payload["data"])), 1040)
        self.assertEqual(payload["kid"], "active")
        payload["kid"] = "old"  # cambia AAD y clave: debe fallar autenticación
        with self.assertRaises(FaceCryptoError):
            decrypt_embedding(json.dumps(payload))

    def test_tamper_and_invalid_envelopes(self):
        payload = json.loads(encrypt_embedding([0.0] * 128))
        raw = bytearray(base64.b64decode(payload["data"]))
        raw[0] ^= 1
        payload["data"] = base64.b64encode(raw).decode()
        with self.assertRaises(FaceCryptoError):
            decrypt_embedding(json.dumps(payload))
        for invalid in ("", "{}", "not-json", json.dumps({"v": 1})):
            with self.assertRaises(FaceCryptoError):
                validate_envelope_format(invalid)
        with self.assertRaises(FaceCryptoError):
            encrypt_embedding([0.0] * 127)
        with self.assertRaises(FaceCryptoError):
            encrypt_embedding([float("nan")] + [0.0] * 127)


class FaceComparisonTest(unittest.TestCase):
    def setUp(self):
        self.known = np.zeros(128)
        self.record = {"voterId": 7, "faceEmbedding": encrypt_embedding(self.known)}

    def test_match_and_wrong_face(self):
        match = identify_face(np.full(128, 0.01), [self.record], threshold=0.55)
        self.assertEqual(match.voter_id, 7)
        with self.assertRaises(FaceRejected):
            identify_face(np.full(128, 2.0), [self.record], threshold=0.55)

    def test_ambiguity_and_corrupt_record(self):
        other = {"voterId": 8, "faceEmbedding": encrypt_embedding(np.full(128, 0.01))}
        with self.assertRaises(FaceRejected):
            identify_face(np.zeros(128), [self.record, other], threshold=0.55, ambiguity_margin=0.2)
        with self.assertRaises(FaceVerificationError):
            identify_face(np.zeros(128), [{"voterId": 8, "faceEmbedding": "bad"}])


class FaceCameraLogicTest(unittest.TestCase):
    def camera(self):
        camera = FaceCamera()
        camera.cap = SimpleNamespace(read=lambda: (True, np.zeros((20, 20, 3), dtype=np.uint8)))
        camera._cv2 = SimpleNamespace(
            resize=lambda frame, *args, **kwargs: frame,
            cvtColor=lambda frame, code: frame,
            COLOR_BGR2RGB=1,
        )
        return camera

    def test_zero_and_multiple_faces(self):
        for locations in ([], [(0, 1, 2, 3), (4, 5, 6, 7)]):
            module = ModuleType("face_recognition")
            module.face_locations = lambda *args, _locations=locations, **kwargs: _locations
            with self.subTest(count=len(locations)), patch.dict("sys.modules", {"face_recognition": module}):
                with self.assertRaises(FaceRejected):
                    self.camera().capture_single_encoding()

    def test_camera_unavailable(self):
        cap = SimpleNamespace(isOpened=lambda: False, release=lambda: None)
        module = ModuleType("cv2")
        module.VideoCapture = lambda index: cap
        with patch.dict("sys.modules", {"cv2": module}):
            with self.assertRaises(FaceVerificationError):
                with FaceCamera():
                    pass


if __name__ == "__main__":
    unittest.main()
