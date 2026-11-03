"""Captura y comparación facial exclusivamente local; no guarda fotografías."""
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from face_crypto import FaceCryptoError, decrypt_embedding, encrypt_embedding


class FaceVerificationError(Exception):
    """Error operativo que no consume un intento biométrico."""


class FaceRejected(Exception):
    """Resultado biométrico negativo que sí puede consumir un intento."""


@dataclass
class FaceMatch:
    voter_id: int
    distance: float


class FaceCamera:
    def __init__(self, camera_index: Optional[int] = None):
        self.camera_index = int(os.getenv("CAMERA_INDEX", "0") if camera_index is None else camera_index)
        self.scale = max(1, int(os.getenv("FACE_CAPTURE_SCALE", "4")))
        self.cap = None
        self._cv2 = None

    def __enter__(self):
        import cv2
        self._cv2 = cv2
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            raise FaceVerificationError("No se pudo acceder a la cámara.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self._cv2 is not None:
            self._cv2.destroyAllWindows()

    def capture_single_encoding(self):
        import face_recognition
        if self.cap is None or self._cv2 is None:
            raise FaceVerificationError("La cámara no está inicializada.")
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise FaceVerificationError("No se pudo leer un fotograma de la cámara.")
        small = self._cv2.resize(frame, (0, 0), fx=1 / self.scale, fy=1 / self.scale)
        rgb = self._cv2.cvtColor(small, self._cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if len(locations) == 0:
            raise FaceRejected("No se detectó ningún rostro.")
        if len(locations) != 1:
            raise FaceRejected("Se detectó más de un rostro; la verificación requiere exactamente uno.")
        encodings = face_recognition.face_encodings(rgb, locations, model="large")
        if len(encodings) != 1 or np.asarray(encodings[0]).shape != (128,):
            raise FaceRejected("No se pudo obtener un encoding facial válido.")
        return np.asarray(encodings[0], dtype=np.float64)


def identify_face(captured, records, threshold=None, ambiguity_margin=None):
    """Busca el candidato global y exige distancia y separación configurables."""
    threshold = float(os.getenv("FACE_DISTANCE_THRESHOLD", "0.55") if threshold is None else threshold)
    ambiguity_margin = float(os.getenv("FACE_AMBIGUITY_MARGIN", "0.05") if ambiguity_margin is None else ambiguity_margin)
    candidates = []
    for record in records:
        try:
            known = np.asarray(decrypt_embedding(record["faceEmbedding"]), dtype=np.float64)
        except (FaceCryptoError, KeyError, TypeError, ValueError) as exc:
            raise FaceVerificationError("Un registro biométrico no pudo descifrarse; verificación detenida.") from exc
        if known.shape != (128,):
            raise FaceVerificationError("Un registro biométrico tiene un formato inválido.")
        # face_recognition.face_distance usa distancia euclidiana; calcularla
        # aquí permite probar comparación y ambigüedad sin cargar la cámara/dlib.
        distance = float(np.linalg.norm(known - np.asarray(captured, dtype=np.float64)))
        candidates.append(FaceMatch(int(record["voterId"]), distance))
    if not candidates:
        raise FaceVerificationError("No hay registros faciales disponibles.")
    candidates.sort(key=lambda item: item.distance)
    best = candidates[0]
    if not np.isfinite(best.distance) or best.distance > threshold:
        raise FaceRejected("El rostro no coincide con ningún registro admitido.")
    if len(candidates) > 1 and candidates[1].distance - best.distance < ambiguity_margin:
        raise FaceRejected("La coincidencia facial es ambigua.")
    return best


def capture_encrypted_enrollment():
    with FaceCamera() as camera:
        encoding = camera.capture_single_encoding()
    return encrypt_embedding(encoding)
