"""Cifrado local de encodings faciales. Nunca registra contenido biométrico."""
import base64
import binascii
import json
import os
import struct
import math
from typing import Dict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FACE_EMBEDDING_SIZE = 128
PLAINTEXT_SIZE = FACE_EMBEDDING_SIZE * 8
NONCE_SIZE = 12
TAG_SIZE = 16
FORMAT_VERSION = 1


class FaceCryptoError(Exception):
    """Error seguro para mostrar; no contiene datos biométricos."""


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise FaceCryptoError("Sobre biométrico malformado.")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise FaceCryptoError("Sobre biométrico malformado.") from exc


def load_key_ring() -> tuple[Dict[str, AESGCM], str]:
    """FACE_ENCRYPTION_KEYS es un JSON {id: clave_base64}; los ids no son secretos."""
    raw_ring = os.getenv("FACE_ENCRYPTION_KEYS", "")
    active_id = os.getenv("FACE_ACTIVE_KEY_ID", "")
    try:
        raw_keys = json.loads(raw_ring)
    except json.JSONDecodeError as exc:
        raise FaceCryptoError("La configuración de claves faciales no es JSON válido.") from exc
    if not isinstance(raw_keys, dict) or not raw_keys or active_id not in raw_keys:
        raise FaceCryptoError("Configura FACE_ENCRYPTION_KEYS y FACE_ACTIVE_KEY_ID.")
    ring = {}
    for key_id, encoded_key in raw_keys.items():
        if not isinstance(key_id, str) or not key_id or len(key_id) > 64:
            raise FaceCryptoError("Identificador de clave inválido.")
        key = _b64decode(encoded_key)
        if len(key) != 32:
            raise FaceCryptoError("Cada clave facial debe contener exactamente 32 bytes.")
        ring[key_id] = AESGCM(key)
    return ring, active_id


def validate_envelope_format(envelope: str) -> None:
    """Validación posible en el servidor, que no posee la clave."""
    if not isinstance(envelope, str) or len(envelope) > 8192:
        raise FaceCryptoError("Sobre biométrico ausente o demasiado grande.")
    try:
        payload = json.loads(envelope)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FaceCryptoError("Sobre biométrico malformado.") from exc
    if not isinstance(payload, dict) or set(payload) != {"v", "kid", "nonce", "data"}:
        raise FaceCryptoError("Formato o versión biométrica no admitidos.")
    if payload["v"] != FORMAT_VERSION or not isinstance(payload["kid"], str) or not payload["kid"]:
        raise FaceCryptoError("Formato o versión biométrica no admitidos.")
    nonce = _b64decode(payload["nonce"])
    ciphertext = _b64decode(payload["data"])
    if len(nonce) != NONCE_SIZE or len(ciphertext) != PLAINTEXT_SIZE + TAG_SIZE:
        raise FaceCryptoError("Tamaño biométrico cifrado inválido.")


def _aad(key_id: str) -> bytes:
    return f"face-encoding-v{FORMAT_VERSION}|{key_id}".encode("utf-8")


def encrypt_embedding(embedding) -> str:
    ring, active_id = load_key_ring()
    try:
        values = [float(value) for value in embedding]
        if len(values) != FACE_EMBEDDING_SIZE or any(not math.isfinite(value) or abs(value) >= 1e6 for value in values):
            raise ValueError
        plaintext = struct.pack("<128d", *values)
    except (TypeError, ValueError, struct.error) as exc:
        raise FaceCryptoError("El encoding debe contener 128 números.") from exc
    if len(plaintext) != PLAINTEXT_SIZE:
        raise FaceCryptoError("El encoding debe contener 128 números.")
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = ring[active_id].encrypt(nonce, plaintext, _aad(active_id))
    return json.dumps(
        {"v": FORMAT_VERSION, "kid": active_id, "nonce": _b64encode(nonce), "data": _b64encode(ciphertext)},
        separators=(",", ":"),
    )


def decrypt_embedding(envelope: str):
    validate_envelope_format(envelope)
    payload = json.loads(envelope)
    ring, _ = load_key_ring()
    cipher = ring.get(payload["kid"])
    if cipher is None:
        raise FaceCryptoError("No está disponible la clave requerida para este registro.")
    try:
        plaintext = cipher.decrypt(_b64decode(payload["nonce"]), _b64decode(payload["data"]), _aad(payload["kid"]))
    except InvalidTag as exc:
        raise FaceCryptoError("La integridad del registro biométrico no es válida.") from exc
    if len(plaintext) != PLAINTEXT_SIZE:
        raise FaceCryptoError("Encoding descifrado con tamaño inválido.")
    values = list(struct.unpack("<128d", plaintext))
    if any(not (-1e6 < value < 1e6) or value != value for value in values):
        raise FaceCryptoError("Encoding descifrado con valores inválidos.")
    return values
