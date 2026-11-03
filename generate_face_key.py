#!/usr/bin/env python3
"""Genera una clave para introducir manualmente en el almacén de secretos; no la persiste."""
import base64
import secrets

print(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
