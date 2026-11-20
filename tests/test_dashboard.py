"""API administrativa del dashboard: autenticación, métricas, bitácora anónima y CSV.

Datos totalmente ficticios y SQLite temporal (mismo entorno que test_backend.py).
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path(_TMP.name) / "dash.db"))
os.environ.setdefault("DEVICE_KEY", "test-kiosk-key")
os.environ.setdefault("ADMIN_KEY", "test-admin-key")
os.environ.setdefault("FINGERPRINT_HMAC_KEY", "11" * 32)
os.environ.setdefault("FACE_ATTESTATION_KEY", "22" * 32)
os.environ.setdefault("FACE_ENCRYPTION_KEYS", json.dumps({"test": base64.b64encode(b"F" * 32).decode()}))
os.environ.setdefault("FACE_ACTIVE_KEY_ID", "test")
os.environ.setdefault("SESSION_TIMEOUT_SECONDS", "300")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import backend  # noqa: E402
import dashboard_api as dash  # noqa: E402
from face_crypto import encrypt_embedding  # noqa: E402
from tests.test_forecast import OPEN, CLOSE, logistic_votes  # noqa: E402

ADMIN = os.environ["ADMIN_KEY"]
DEVICE = os.environ["DEVICE_KEY"]
CSRF = {"X-Requested-With": "dashboard"}


def _wipe():
    with Session(backend.engine) as db:
        for model in (dash.DashboardEvent, dash.DeviceHeartbeat, backend.DeviceNonce, backend.DeviceReplayGuard,
                      backend.Ballot, backend.FingerprintCommand, backend.VoteSession, backend.Voter,
                      backend.Candidate):
            db.exec(delete(model))
        db.commit()


class DashboardApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)

    def setUp(self):
        _wipe()
        self.client.cookies.clear()

    # ------------------------------------------------------------- utilidades
    def login(self):
        r = self.client.post("/api/v1/admin/login", json={"password": ADMIN}, headers=CSRF)
        self.assertEqual(r.status_code, 200, r.text)

    def seed(self):
        with Session(backend.engine) as db:
            voters = []
            for i, state in enumerate(["CIUDAD DE MEXICO"] * 3 + ["JALISCO"] * 2):
                voters.append(backend.Voter(
                    fullName=f"Persona {i}", cardUid=f"04A1B2C{i}", fingerprintSlot=i + 1,
                    faceEmbedding=encrypt_embedding([0.0] * 128), stateName=state,
                    municipalityName="MUN", hasVoted=i < 3))
            db.add_all(voters)
            db.add_all([
                backend.Candidate(name="Candidato A", office="PRESIDENT"),
                backend.Candidate(name="Candidato B", office="PRESIDENT"),
                backend.Candidate(name="Gob CDMX", office="GOVERNOR", stateName="CIUDAD DE MEXICO"),
            ])
            db.commit()
            ids = {c.name: c.id for c in db.exec(select(backend.Candidate)).all()}
            for _ in range(2):
                db.add(backend.Ballot(candidateId=ids["Candidato A"]))
            db.add(backend.Ballot(candidateId=ids["Candidato B"]))
            db.commit()

    # ------------------------------------------------------------------ auth
    def test_login_requires_csrf_header_and_valid_password(self):
        r = self.client.post("/api/v1/admin/login", json={"password": ADMIN})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/v1/admin/login", json={"password": "mala"}, headers=CSRF)
        self.assertEqual(r.status_code, 401)
        self.login()
        self.assertTrue(self.client.get("/api/v1/admin/me").json()["authenticated"])

    def test_cookie_is_httponly_and_strict(self):
        r = self.client.post("/api/v1/admin/login", json={"password": ADMIN}, headers=CSRF)
        header = r.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=strict", header)
        self.assertNotIn(ADMIN, r.text)

    def test_protected_routes_need_session(self):
        for path in ("meta", "results", "participation", "timeline", "forecast", "system", "events", "analytics",
                     "export/results.csv"):
            self.assertEqual(self.client.get(f"/api/v1/admin/{path}").status_code, 401, path)

    def test_device_key_does_not_open_admin_api(self):
        r = self.client.get("/api/v1/admin/results", headers={"X-Device-Key": DEVICE, "X-Admin-Key": ADMIN})
        self.assertEqual(r.status_code, 401)

    def test_logout_revokes_session(self):
        self.login()
        token = self.client.cookies.get("dashboard_session")
        self.client.post("/api/v1/admin/logout", headers=CSRF)
        self.client.cookies.set("dashboard_session", token, path="/api/v1/admin")
        self.assertEqual(self.client.get("/api/v1/admin/results").status_code, 401)

    def test_tampered_token_rejected(self):
        self.login()
        token = self.client.cookies.get("dashboard_session")
        parts = token.split(".")
        parts[1] = str(int(parts[1]) + 99999)
        self.client.cookies.clear()
        self.client.cookies.set("dashboard_session", ".".join(parts), path="/api/v1/admin")
        self.assertEqual(self.client.get("/api/v1/admin/results").status_code, 401)

    # ------------------------------------------------------------- métricas
    def test_results_percent_are_per_region(self):
        self.seed()
        self.login()
        data = self.client.get("/api/v1/admin/results", params={"office": "PRESIDENT"}).json()
        self.assertEqual(data["totalVotes"], 3)
        by_name = {c["name"]: c for c in data["candidates"]}
        self.assertEqual(by_name["Candidato A"]["votes"], 2)
        self.assertAlmostEqual(by_name["Candidato A"]["percent"], 66.67, places=2)
        # un candidato sin votos en una region sin votos no divide entre cero
        everything = self.client.get("/api/v1/admin/results").json()
        gob = next(c for c in everything["candidates"] if c["name"] == "Gob CDMX")
        self.assertEqual(gob["percent"], 0.0)
        self.assertEqual(self.client.get("/api/v1/admin/results", params={"office": "XYZ"}).status_code, 422)

    def test_participation(self):
        self.seed()
        self.login()
        data = self.client.get("/api/v1/admin/participation").json()
        self.assertEqual((data["registered"], data["voted"], data["pending"]), (5, 3, 2))
        self.assertEqual(data["participation"], 60.0)
        states = {s["state"]: s for s in data["byState"]}
        self.assertEqual(states["CIUDAD DE MEXICO"]["participation"], 100.0)
        self.assertEqual(states["JALISCO"]["participation"], 0.0)

    def test_empty_database_does_not_break(self):
        self.login()
        for path in ("results", "participation", "timeline", "system", "events", "analytics", "meta"):
            self.assertEqual(self.client.get(f"/api/v1/admin/{path}").status_code, 200, path)
        self.assertEqual(self.client.get("/api/v1/admin/participation").json()["participation"], 0.0)

    # --------------------------------------------------- bitácora y privacidad
    def test_events_are_recorded_without_identity(self):
        self.seed()
        r = self.client.post("/api/v1/session/start", json={"cardUid": "04:A1:B2:C3"},
                             headers={"X-Device-Key": DEVICE})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.post("/api/v1/session/start", json={"cardUid": "FF:FF"}, headers={"X-Device-Key": DEVICE})
        # peticion sin clave: no debe ensuciar la bitacora
        self.client.post("/api/v1/session/start", json={"cardUid": "FF:FF"})
        with Session(backend.engine) as db:
            rows = db.exec(select(dash.DashboardEvent)).all()
        self.assertEqual(sorted(r.status for r in rows), ["ok", "rejected"])
        self.assertTrue(all(row.kind == "access" for row in rows))
        columns = set(dash.DashboardEvent.model_fields)
        self.assertEqual(columns, {"id", "createdAt", "kind", "device", "status"})
        self.login()
        events = self.client.get("/api/v1/admin/events").json()["events"]
        self.assertEqual(len(events), 2)
        self.assertNotIn("04A1B2C3", json.dumps(events))

    def test_timeline_and_analytics(self):
        self.seed()
        now = dash.utc_now()
        with Session(backend.engine) as db:
            for minutes, status in ((5, "ok"), (4, "ok"), (3, "rejected")):
                db.add(dash.DashboardEvent(createdAt=dash.to_naive_utc(now - timedelta(minutes=minutes)),
                                           kind="vote", device="Urna 01", status=status))
            for _ in range(6):
                db.add(dash.DashboardEvent(createdAt=dash.to_naive_utc(now), kind="fingerprint",
                                           device="Lector de huellas", status="rejected"))
            db.commit()
        self.login()
        timeline = self.client.get("/api/v1/admin/timeline").json()
        self.assertEqual(timeline["registered"], 5)
        self.assertEqual(timeline["points"][-1]["cumulativeVotes"], 2)
        analytics = self.client.get("/api/v1/admin/analytics").json()
        self.assertEqual(analytics["status"], "ALERTA")
        self.assertEqual(self.client.get("/api/v1/admin/timeline", params={"from": "no-es-fecha"}).status_code, 422)

    def dashboard_client(self, window=None):
        app = FastAPI()
        config = replace(dash.DashboardConfig.from_env(), forecast_window=window)
        dash.install_dashboard(app, dash.BackendBindings(
            engine=backend.engine, verify_device_key=backend.verifyDeviceKey, device_key=DEVICE,
            Voter=backend.Voter, Candidate=backend.Candidate, Ballot=backend.Ballot,
            DeviceReplayGuard=backend.DeviceReplayGuard, fingerprint_device_id=backend.FINGERPRINT_DEVICE_ID,
            normalize_region=backend.normalizeRegionName,
        ), config)
        client = TestClient(app)
        self.addCleanup(client.close)
        response = client.post("/api/v1/admin/login", json={"password": ADMIN}, headers=CSRF)
        self.assertEqual(response.status_code, 200)
        return client

    # ------------------------------------------------------- ráfagas de rechazos
    def add_biometric_counts(self, db, timestamp, kind, *, ok, rejected, error=0):
        for status, count in (("ok", ok), ("rejected", rejected), ("error", error)):
            db.add_all(dash.DashboardEvent(
                createdAt=dash.to_naive_utc(timestamp), kind=kind, device="Urna 01", status=status,
            ) for _ in range(count))

    def test_biometric_burst_uses_recent_rate_and_caches_it_for_live_reports(self):
        client = self.dashboard_client()
        now = OPEN + timedelta(hours=6)
        with Session(backend.engine) as db:
            self.add_biometric_counts(db, now - timedelta(minutes=30), "fingerprint", ok=79, rejected=1)
            self.add_biometric_counts(db, now - timedelta(minutes=9), "fingerprint", ok=18, rejected=6)
            self.add_biometric_counts(db, now - timedelta(minutes=1), "fingerprint", ok=0, rejected=0, error=2)
            db.commit()

        url = "/api/v1/admin/analytics"
        with (
            patch.object(dash, "utc_now", return_value=now) as clock,
            patch.object(dash, "time", wraps=dash.time) as cache_clock,
            patch.object(dash, "_biometric_burst_flags", wraps=dash._biometric_burst_flags) as calculate,
        ):
            cache_clock.monotonic.return_value = 100
            data = client.get(url).json()
            self.assertEqual(data["status"], "PRECAUCIÓN")
            self.assertEqual(len(data["auditFlags"]), 1)
            self.assertIn("6 de 24 en 10 minutos (25%)", data["auditFlags"][0])

            archived = client.get(url, params={"to": (now - timedelta(hours=1)).isoformat()}).json()
            self.assertEqual(archived["auditFlags"], [])
            cache_clock.monotonic.return_value = 159
            self.assertEqual(client.get(url).json()["auditFlags"], data["auditFlags"])
            calculate.assert_called_once()

            cache_clock.monotonic.return_value = 160
            clock.return_value = now + timedelta(minutes=1, seconds=1)
            self.assertEqual(client.get(url).json()["auditFlags"], [])
            self.assertEqual(calculate.call_count, 2)

    def test_biometric_burst_requires_history_and_a_change_in_rate(self):
        client = self.dashboard_client()
        now = OPEN + timedelta(hours=6)
        with Session(backend.engine) as db:
            self.add_biometric_counts(db, now - timedelta(minutes=30), "fingerprint", ok=5, rejected=0)
            self.add_biometric_counts(db, now - timedelta(minutes=2), "fingerprint", ok=2, rejected=8)
            self.add_biometric_counts(db, now - timedelta(minutes=30), "face", ok=30, rejected=10)
            self.add_biometric_counts(db, now - timedelta(minutes=2), "face", ok=18, rejected=6)
            db.commit()

        with patch.object(dash, "utc_now", return_value=now):
            data = client.get("/api/v1/admin/analytics").json()
        self.assertEqual(data["status"], "ALERTA")
        self.assertTrue(any(">30%" in flag for flag in data["auditFlags"]))
        self.assertFalse(any(flag.startswith("Ráfaga") for flag in data["auditFlags"]))

    # ------------------------------------------------------- pronóstico
    def test_forecast_schedule_requires_an_offset_and_order(self):
        env = {"DASHBOARD_ELECTION_OPENS_AT": "2026-11-08T08:00:00-06:00",
               "DASHBOARD_ELECTION_CLOSES_AT": "2026-11-08T18:00:00-06:00"}
        with patch.dict(os.environ, env):
            opens, closes = dash.DashboardConfig.from_env().forecast_window
            self.assertEqual(opens.hour, 14)
            self.assertEqual(closes - opens, timedelta(hours=10))
        with patch.dict(os.environ, {**env, "DASHBOARD_ELECTION_OPENS_AT": "2026-11-08T08:00:00"}):
            self.assertIsNone(dash.DashboardConfig.from_env().forecast_window)
        with patch.dict(os.environ, {**env, "DASHBOARD_ELECTION_CLOSES_AT": env["DASHBOARD_ELECTION_OPENS_AT"]}):
            self.assertIsNone(dash.DashboardConfig.from_env().forecast_window)

    def test_forecast_hides_incomplete_history(self):
        self.seed()
        self.assertEqual(self.dashboard_client().get("/api/v1/admin/forecast").json()["status"], "not_configured")
        client = self.dashboard_client((OPEN, CLOSE))
        with patch.object(dash, "utc_now", return_value=OPEN + timedelta(hours=2)):
            data = client.get("/api/v1/admin/forecast").json()
        self.assertEqual(data["status"], "incomplete_history")
        self.assertNotIn("finalPercent", data)

    def test_forecast_tracks_the_window_reuses_fit_and_uses_observations_at_close(self):
        registered = 1600
        now = OPEN + timedelta(hours=8)
        synthetic, _ = logistic_votes(10, registered, 0.62, 0.8, 6.0)
        seen = [stamp for stamp in synthetic if stamp <= now]
        envelope = encrypt_embedding([0.0] * 128)
        with Session(backend.engine) as db:
            db.add_all(backend.Voter(
                fullName="Persona de prueba", cardUid=f"{i:08X}", fingerprintSlot=i + 1,
                faceEmbedding=envelope, stateName="JALISCO", municipalityName="MUN",
                hasVoted=i <= len(seen),
            ) for i in range(registered))
            db.add_all(dash.DashboardEvent(createdAt=dash.to_naive_utc(stamp), kind="vote", device="Urna 01", status=status)
                       for stamp, status in [(stamp, "ok") for stamp in [*seen, OPEN - timedelta(hours=1)]]
                       + [(now, "rejected")])
            db.commit()

        client = self.dashboard_client((OPEN, CLOSE))
        with patch.object(dash, "utc_now", return_value=OPEN - timedelta(minutes=1)):
            self.assertEqual(client.get("/api/v1/admin/forecast").json()["status"], "not_open")
        with patch.object(dash, "utc_now", return_value=OPEN + timedelta(minutes=10)):
            early_client = self.dashboard_client((OPEN, CLOSE))
            self.assertEqual(early_client.get("/api/v1/admin/forecast").json()["status"], "insufficient_data")
        with patch.object(dash, "utc_now", return_value=now), patch.object(dash, "fit_turnout", wraps=dash.fit_turnout) as fit:
            data = client.get("/api/v1/admin/forecast").json()
            self.assertEqual(data["status"], "ok", data.get("reason"))
            self.assertEqual(data["basedOnVotes"], len(seen))
            self.assertAlmostEqual(data["finalPercent"], 62, delta=6)
            self.assertEqual(data["points"][-1]["timestamp"], CLOSE.isoformat())
            self.assertEqual(data["observed"][-1]["timestamp"], now.isoformat())
            self.assertEqual(client.get("/api/v1/admin/forecast").json(), data)
            fit.assert_called_once()
        with patch.object(dash, "utc_now", return_value=CLOSE):
            closed = client.get("/api/v1/admin/forecast").json()
        self.assertEqual(closed["status"], "closed")
        self.assertAlmostEqual(closed["finalPercent"], len(seen) * 100 / registered)
        self.assertEqual(closed["points"], [])

    # ------------------------------------------------------- sistema/heartbeat
    def test_heartbeat_drives_system_status(self):
        self.login()
        before = {c["id"]: c["status"] for c in self.client.get("/api/v1/admin/system").json()["components"]}
        self.assertEqual(before["kiosk"], "unknown")
        self.assertEqual(before["database"], "online")
        bad = self.client.post("/api/v1/device/heartbeat", json={"components": {"nfc": "online"}})
        self.assertIn(bad.status_code, (401, 403))
        ok = self.client.post("/api/v1/device/heartbeat", headers={"X-Device-Key": DEVICE},
                              json={"components": {"nfc": "online", "camera": "offline"}})
        self.assertEqual(ok.status_code, 200, ok.text)
        data = self.client.get("/api/v1/admin/system").json()
        statuses = {c["id"]: c["status"] for c in data["components"]}
        self.assertEqual((statuses["kiosk"], statuses["nfc"], statuses["camera"]), ("online", "online", "offline"))
        self.assertEqual(data["overall"], "offline")
        rejected = self.client.post("/api/v1/device/heartbeat", headers={"X-Device-Key": DEVICE},
                                    json={"components": {"database": "online"}})
        self.assertEqual(rejected.status_code, 422)

    def test_omitted_component_expires_even_when_kiosk_still_reports(self):
        self.login()
        before = self.client.get("/api/v1/admin/system").json()
        old_time = dash.utc_now() - timedelta(seconds=before["heartbeatTtlSeconds"] + 5)
        headers = {"X-Device-Key": DEVICE}
        with patch.object(dash, "utc_now", return_value=old_time):
            first = self.client.post("/api/v1/device/heartbeat", headers=headers,
                                     json={"components": {"nfc": "online"}})
        self.assertEqual(first.status_code, 200)
        latest = self.client.post("/api/v1/device/heartbeat", headers=headers,
                                  json={"components": {"camera": "online"}})
        self.assertEqual(latest.status_code, 200)

        components = {c["id"]: c for c in self.client.get("/api/v1/admin/system").json()["components"]}
        self.assertEqual(components["kiosk"]["status"], "online")
        self.assertEqual(components["camera"]["status"], "online")
        self.assertEqual(components["nfc"]["status"], "unknown")
        self.assertIsNotNone(components["nfc"]["lastSeen"])

    # ------------------------------------------------------------------- CSV
    def test_csv_export_is_formula_safe(self):
        with Session(backend.engine) as db:
            db.add(backend.Candidate(name="=HYPERLINK(\"http://x\")", office="PRESIDENT"))
            db.commit()
        self.login()
        r = self.client.get("/api/v1/admin/export/results.csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("'=HYPERLINK", r.text)
        self.assertEqual(self.client.get("/api/v1/admin/export/otro.csv").status_code, 422)

    def test_security_headers_and_no_store(self):
        self.login()
        r = self.client.get("/api/v1/admin/meta")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])

    def test_zz_login_throttle_locks_after_failures(self):
        statuses = [self.client.post("/api/v1/admin/login", json={"password": "x"}, headers=CSRF).status_code
                    for _ in range(6)]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(statuses[5], 429)
        # incluso la clave correcta queda bloqueada durante el castigo
        r = self.client.post("/api/v1/admin/login", json={"password": ADMIN}, headers=CSRF)
        self.assertEqual(r.status_code, 429)
        self.assertIn("retry-after", r.headers)


if __name__ == "__main__":
    unittest.main()
