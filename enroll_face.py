#!/usr/bin/env python3
"""Enrolamiento administrativo: el operador elige el votante, nunca el reconocedor."""
import os
import sys

import requests

from face_local import FaceRejected, FaceVerificationError, capture_encrypted_enrollment
from face_crypto import FaceCryptoError

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
TIMEOUT = 10


def api(method, path, **kwargs):
    try:
        response = requests.request(
            method, API_BASE_URL + path, headers={"X-Admin-Key": ADMIN_KEY}, timeout=TIMEOUT, **kwargs
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        # No se incluye el cuerpo de la petición ni las credenciales.
        status = getattr(exc.response, "status_code", "sin conexión")
        raise RuntimeError(f"La operación administrativa falló ({status}).") from exc


def main():
    if not ADMIN_KEY:
        raise RuntimeError("Define ADMIN_KEY en el entorno antes de enrolar.")
    voters = api("GET", "/api/v1/voters")
    if not voters:
        raise RuntimeError("No hay votantes. Primero crea el registro administrativo correspondiente.")
    for voter in voters:
        existing = "con rostro" if voter["hasFace"] else "sin rostro"
        print(f"{voter['voterId']}: {voter['fullName']} ({existing})")
    voter_id = int(input("ID interno del votante seleccionado por el operador: ").strip())
    selected = next((item for item in voters if item["voterId"] == voter_id), None)
    if selected is None:
        raise RuntimeError("El ID no pertenece a un votante existente.")
    replace = False
    if selected["hasFace"]:
        replace = input("Ya existe un rostro. Escribe REEMPLAZAR para autorizarlo: ").strip() == "REEMPLAZAR"
        if not replace:
            print("Operación cancelada; el registro anterior se conserva.")
            return
    input("Coloca a la persona autorizada frente a la cámara y pulsa Enter: ")
    envelope = capture_encrypted_enrollment()
    api("PUT", f"/api/v1/voters/{voter_id}/face", json={"faceEmbedding": envelope, "confirmReplacement": replace})
    print("Registro facial cifrado almacenado correctamente.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, FaceRejected, FaceVerificationError, FaceCryptoError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nEnrolamiento cancelado.", file=sys.stderr)
        sys.exit(130)
