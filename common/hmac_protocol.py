"""Canonicalización y firmas HMAC-SHA256 compartidas por Raspberry Pi y pruebas.

Las claves se configuran como 32 bytes en hexadecimal (64 caracteres). Nunca se
registran mensajes, UID ni claves en los logs.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def load_hex_key(env_name: str) -> bytes:
    raw = os.getenv(env_name, "").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} debe contener 32 bytes en hexadecimal.") from exc
    if len(key) != 32:
        raise RuntimeError(f"{env_name} debe contener exactamente 32 bytes (64 caracteres hex).")
    return key


def sign_hex(key: bytes, canonical: str) -> str:
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def signature_matches(provided: str, expected: str) -> bool:
    return isinstance(provided, str) and hmac.compare_digest(provided.lower(), expected)


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fingerprint_request_signature(
    key: bytes,
    method: str,
    path: str,
    body: bytes,
    device_id: str,
    timestamp: int,
    nonce: str,
    sequence: int,
) -> str:
    canonical = "\n".join((
        "esp32-request-v1", method.upper(), path, body_sha256(body), device_id,
        str(timestamp), nonce, str(sequence),
    ))
    return sign_hex(key, canonical)


def fingerprint_response_signature(
    key: bytes,
    body: bytes,
    device_id: str,
    timestamp: int,
    request_nonce: str,
    response_nonce: str,
) -> str:
    canonical = "\n".join((
        "esp32-response-v1", device_id, str(timestamp), request_nonce,
        response_nonce, body_sha256(body),
    ))
    return sign_hex(key, canonical)


def nfc_command_signature(
    key: bytes,
    device_id: str,
    session_id: str,
    action: str,
    nonce: str,
    sequence: int,
    expires_at: int,
) -> str:
    canonical = "\n".join((
        "nfc-command-v1", device_id, session_id, action, nonce,
        str(sequence), str(expires_at),
    ))
    return sign_hex(key, canonical)


def nfc_response_signature(
    key: bytes,
    device_id: str,
    session_id: str,
    nonce: str,
    sequence: int,
    status: str,
    uid: str,
    expires_at: int,
) -> str:
    canonical = "\n".join((
        "nfc-response-v1", device_id, session_id, nonce, str(sequence),
        status, uid, str(expires_at),
    ))
    return sign_hex(key, canonical)


def face_attestation_signature(
    key: bytes,
    session_id: str,
    challenge: str,
    voter_id: int | None,
    matched: bool,
) -> str:
    canonical = "\n".join((
        "face-attestation-v1", session_id, challenge,
        "" if voter_id is None else str(voter_id), "true" if matched else "false",
    ))
    return sign_hex(key, canonical)
