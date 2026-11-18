"""Datos ficticios para desarrollar el dashboard SIN hardware ni base real.

    python scripts/seed_dashboard_demo.py --reset                 # puebla la BD de DATABASE_URL
    python scripts/seed_dashboard_demo.py --heartbeat http://127.0.0.1:8000   # simula el latido de la urna

Por seguridad se niega a tocar una base que no sea SQLite salvo con --i-know-this-is-not-production.
Todos los nombres, tarjetas y huellas son sinteticos.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATES = {  # entidad normalizada -> padron ficticio
    "CIUDAD DE MEXICO": 420, "JALISCO": 300, "MEXICO": 380, "NUEVO LEON": 260, "VERACRUZ": 240,
    "PUEBLA": 200, "GUANAJUATO": 180, "YUCATAN": 90, "OAXACA": 120, "SINALOA": 100, "CHIHUAHUA": 110,
    "BAJA CALIFORNIA": 120,
}
PRESIDENTIAL = [("Candidato A", 32.5), ("Candidato B", 28.7), ("Candidato C", 22.1), ("Candidato D", 16.7)]


def heartbeat_loop(base: str) -> None:
    import requests

    key = os.environ.get("DEVICE_KEY", "")
    print("Enviando latidos a", base, "(Ctrl+C para detener)")
    while True:
        try:
            r = requests.post(f"{base}/api/v1/device/heartbeat", headers={"X-Device-Key": key},
                              json={"components": {"nfc": "online", "camera": "online"}}, timeout=5)
            print(time.strftime("%H:%M:%S"), r.status_code)
        except Exception as exc:  # noqa: BLE001
            print("error:", exc)
        time.sleep(15)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="borra votantes, candidatos, votos y eventos antes de poblar")
    parser.add_argument("--heartbeat", metavar="URL", help="en lugar de poblar, envia latidos periodicos")
    parser.add_argument("--participation", type=float, default=0.62, help="fraccion de votantes que ya voto")
    parser.add_argument("--i-know-this-is-not-production", action="store_true")
    args = parser.parse_args()
    if args.heartbeat:
        heartbeat_loop(args.heartbeat.rstrip("/"))
        return

    os.environ.setdefault("DATABASE_URL", "sqlite:///demo.db")
    os.environ.setdefault("DEVICE_KEY", "demo-device-key")
    os.environ.setdefault("ADMIN_KEY", "demo-admin-key")
    os.environ.setdefault("FINGERPRINT_HMAC_KEY", "11" * 32)
    os.environ.setdefault("FACE_ATTESTATION_KEY", "22" * 32)
    os.environ.setdefault("FACE_ENCRYPTION_KEYS", json.dumps({"demo": base64.b64encode(secrets.token_bytes(32)).decode()}))
    os.environ.setdefault("FACE_ACTIVE_KEY_ID", "demo")
    if not os.environ["DATABASE_URL"].startswith("sqlite") and not args.i_know_this_is_not_production:
        sys.exit("Rechazado: DATABASE_URL no es SQLite. Este script es solo para desarrollo.")

    from sqlalchemy import delete
    from sqlmodel import Session, select

    import backend
    import dashboard_api as dash
    from face_crypto import encrypt_embedding

    rng = random.Random(2026)
    envelope = encrypt_embedding([0.0] * 128)
    with Session(backend.engine) as db:
        if args.reset:
            for model in (dash.DashboardEvent, dash.DeviceHeartbeat, backend.Ballot, backend.FingerprintCommand,
                          backend.VoteSession, backend.Voter, backend.Candidate):
                db.exec(delete(model))
            db.commit()
        if db.exec(select(backend.Voter)).first():
            sys.exit("La base ya tiene votantes; use --reset.")

        voters, slot = [], 0
        for state, size in STATES.items():
            rate = min(0.95, max(0.15, rng.gauss(args.participation, 0.16)))
            for i in range(size):
                slot += 1
                voters.append(backend.Voter(
                    fullName=f"Persona Ficticia {slot}", cardUid=f"{slot:08X}", fingerprintSlot=slot,
                    faceEmbedding=envelope, stateName=state, municipalityName="MUNICIPIO",
                    hasVoted=rng.random() < rate))
        db.add_all(voters)
        db.add_all([backend.Candidate(name=name, office="PRESIDENT") for name, _ in PRESIDENTIAL])
        db.commit()

        voted = sum(v.hasVoted for v in voters)
        cands = db.exec(select(backend.Candidate).order_by(backend.Candidate.id)).all()
        weights = [w for _, w in PRESIDENTIAL]
        db.add_all([backend.Ballot(candidateId=rng.choices(cands, weights)[0].id) for _ in range(voted)])

        now = dash.utc_now()
        tz = dash._local_timezone()  # noqa: SLF001
        start = datetime.now(tz).replace(hour=8, minute=0, second=0, microsecond=0)
        if start.astimezone(timezone.utc) > now:
            start -= timedelta(days=1)
        span = max(60.0, (now - start.astimezone(timezone.utc)).total_seconds())
        events = []
        for _ in range(voted):  # curva con mas afluencia a media jornada
            t = start.astimezone(timezone.utc) + timedelta(seconds=span * rng.betavariate(2.2, 1.8))
            events.append(dash.DashboardEvent(createdAt=dash.to_naive_utc(t), kind="vote", device="Urna 01", status="ok"))
            for kind in ("access", "face"):
                events.append(dash.DashboardEvent(createdAt=dash.to_naive_utc(t - timedelta(seconds=40)), kind=kind,
                                                  device="Urna 01", status="ok"))
            events.append(dash.DashboardEvent(createdAt=dash.to_naive_utc(t - timedelta(seconds=70)), kind="fingerprint",
                                              device="Lector de huellas", status="ok"))
        for _ in range(max(2, voted // 40)):
            kind = rng.choice(["fingerprint", "face", "access"])
            t = now - timedelta(seconds=rng.randint(60, int(span)))
            events.append(dash.DashboardEvent(createdAt=dash.to_naive_utc(t), kind=kind,
                                              device="Lector de huellas" if kind == "fingerprint" else "Urna 01",
                                              status="rejected"))
        db.add_all(events)
        for component, status in (("kiosk", "online"), ("nfc", "online"), ("camera", "online")):
            db.merge(dash.DeviceHeartbeat(component=component, status=status, reportedAt=dash.to_naive_utc(now)))
        db.merge(backend.DeviceReplayGuard(deviceId=backend.FINGERPRINT_DEVICE_ID, lastSequence=1, updatedAt=now))
        db.commit()
    print(f"Listo: {len(voters)} votantes, {voted} votos, {len(events)} eventos. Clave admin: {os.environ['ADMIN_KEY']}")


if __name__ == "__main__":
    main()
