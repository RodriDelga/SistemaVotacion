"""Cliente HTTP del contrato FastAPI existente; no contiene lógica de interfaz."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import requests

from kiosk_ui.core.models import Candidate, Position, SubmitOutcome, SubmitResult

OFFICE_TITLES = {
    "MAYOR": "Presidente Municipal",
    "GOVERNOR": "Gobernador",
    "PRESIDENT": "Presidente de la República",
}
VOTE_FIELDS = {"PRESIDENT": "presidentId", "GOVERNOR": "governorId", "MAYOR": "mayorId"}


@dataclass
class ApiError(Exception):
    message: str
    status_code: Optional[int] = None

    def __str__(self) -> str:
        return self.message


class VotingApi:
    def __init__(self, base_url: Optional[str] = None, device_key: Optional[str] = None,
                 timeout_s: Optional[float] = None) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.device_key = device_key if device_key is not None else os.getenv("DEVICE_KEY", "")
        self.timeout_s = timeout_s or float(os.getenv("API_TIMEOUT_SECONDS", "8"))
        if not self.device_key:
            raise RuntimeError("Configura DEVICE_KEY para el servicio local de la Raspberry Pi.")
        self._http = requests.Session()
        self._http.headers.update({"X-Device-Key": self.device_key})

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = self._http.request(
                method, self.base_url + path, timeout=self.timeout_s, **kwargs
            )
        except requests.RequestException as exc:
            raise ApiError("El servicio local de validación no está disponible.") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError("El servicio local devolvió una respuesta inválida.", response.status_code) from exc
        if not response.ok:
            detail = payload.get("detail", "Operación rechazada.") if isinstance(payload, dict) else "Operación rechazada."
            raise ApiError(str(detail), response.status_code)
        if not isinstance(payload, dict):
            raise ApiError("El servicio local devolvió un formato inválido.", response.status_code)
        return payload

    def start_session(self, card_uid: str) -> str:
        data = self._request("POST", "/api/v1/session/start", json={"cardUid": card_uid})
        session_id = data.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise ApiError("La sesión recibida no es válida.")
        return session_id  # referencia opaca; nunca se muestra en la interfaz

    def request_fingerprint_command(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/session/{session_id}/fingerprint-command")

    def session_status(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/session/{session_id}")

    def face_challenge(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/session/{session_id}/face-challenge")

    def submit_face(self, session_id: str, challenge: str, matched: bool,
                    voter_id: Optional[int], attestation: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/session/{session_id}/face", json={
            "challenge": challenge, "matched": matched, "voterId": voter_id,
            "attestation": attestation,
        })

    def load_ballot(self, session_id: str) -> tuple[Position, ...]:
        data = self._request("GET", f"/api/v1/session/{session_id}/ballot")
        offices = data.get("offices")
        if not isinstance(offices, list):
            raise ApiError("La boleta no tiene un formato válido.")
        positions: list[Position] = []
        for item in offices:
            if not isinstance(item, dict) or item.get("office") not in OFFICE_TITLES:
                raise ApiError("La boleta contiene un cargo no admitido.")
            office = item["office"]
            raw_candidates = item.get("candidates")
            if not isinstance(raw_candidates, list):
                raise ApiError("La boleta contiene candidatos malformados.")
            candidates = []
            for raw in raw_candidates:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    raise ApiError("La boleta contiene un candidato malformado.")
                try:
                    candidate_id = str(int(raw["candidateId"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ApiError("La boleta contiene un identificador inválido.") from exc
                candidates.append(Candidate(candidate_id, raw["name"], office))
            positions.append(Position(office, OFFICE_TITLES[office], tuple(candidates)))
        if [p.id for p in positions] != ["MAYOR", "GOVERNOR", "PRESIDENT"]:
            raise ApiError("La boleta no respeta el orden de cargos configurado.")
        return tuple(positions)

    def submit_vote(self, session_id: str, selections: Mapping[str, str]) -> SubmitResult:
        try:
            payload = {
                field: int(selections[office]) for office, field in VOTE_FIELDS.items()
            }
            data = self._request("POST", f"/api/v1/session/{session_id}/vote", json=payload)
        except ApiError as exc:
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                # Un 4xx definitivo confirma que esta petición no fue aceptada.
                return SubmitResult(SubmitOutcome.REJECTED, str(exc))
            return SubmitResult(SubmitOutcome.UNCERTAIN, "No hubo una confirmación válida del servicio.")
        except (KeyError, TypeError, ValueError):
            return SubmitResult(SubmitOutcome.REJECTED, "La selección no tiene un formato válido.")
        if data.get("status") == "voteRecorded":
            return SubmitResult(SubmitOutcome.REGISTERED, "Gracias por participar.")
        return SubmitResult(SubmitOutcome.UNCERTAIN, "La confirmación del servicio no fue válida.")

    def cancel_session(self, session_id: str) -> None:
        self._request("POST", f"/api/v1/session/{session_id}/cancel")
