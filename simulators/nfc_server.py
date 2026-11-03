#!/usr/bin/env python3
"""Simulador del contrato NFC HMAC. Solo pruebas; no emula un PN532 físico."""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common.hmac_protocol import (
    load_hex_key, nfc_command_signature, nfc_response_signature, signature_matches,
)


def build_handler(key: bytes, device_id: str, uid: str, status: str):
    last_sequence = 0
    nonces: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # No registra cuerpos, UID, nonce ni firmas.
            print("Simulador NFC:", fmt % args)

        def do_POST(self):
            nonlocal last_sequence
            if self.path != "/v1/nfc/scan":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                expected = nfc_command_signature(
                    key, data["deviceId"], data["sessionId"], data["action"],
                    data["nonce"], data["sequence"], data["expiresAt"],
                )
                valid = (
                    data["deviceId"] == device_id and data["action"] == "scan"
                    and signature_matches(data["hmac"], expected)
                    and data["sequence"] > last_sequence
                    and data["nonce"] not in nonces
                    and data["expiresAt"] >= int(time.time())
                )
                if not valid:
                    self.send_error(401)
                    return
                last_sequence = data["sequence"]
                nonces.add(data["nonce"])
                returned_uid = uid if status == "ok" else ""
                expires = int(time.time()) + 15
                response = {
                    "deviceId": device_id, "sessionId": data["sessionId"],
                    "nonce": data["nonce"], "sequence": data["sequence"],
                    "status": status, "uid": returned_uid, "expiresAt": expires,
                }
                response["hmac"] = nfc_response_signature(
                    key, device_id, data["sessionId"], data["nonce"], data["sequence"],
                    status, returned_uid, expires,
                )
                body = json.dumps(response, separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.send_error(400)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Simulador NFC HMAC, solo para pruebas")
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--uid", default="04A1B2C3", help="UID ficticio de pruebas")
    parser.add_argument("--status", choices=("ok", "timeout", "invalid_read"), default="ok")
    args = parser.parse_args()
    key = load_hex_key("NFC_HMAC_KEY")
    device_id = os.getenv("NFC_DEVICE_ID", "nfc-esp32-01")
    server = ThreadingHTTPServer((args.listen, args.port), build_handler(key, device_id, args.uid, args.status))
    print(f"Simulador NFC en http://{args.listen}:{args.port}; no usa hardware.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
