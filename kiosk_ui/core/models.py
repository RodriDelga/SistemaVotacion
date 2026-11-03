"""Modelos de datos compartidos entre la interfaz, el controlador y los adaptadores.

No contiene lógica ni dependencias de Tkinter. Solo guarda lo mínimo necesario:
no hay campos para datos biométricos.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Step(str, Enum):
    """Pasos de verificación de identidad, en el orden en que se muestran."""
    CARD = "card"
    FINGERPRINT = "fingerprint"
    FACE = "face"


class StepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    OK = "ok"
    FAILED = "failed"


class Phase(str, Enum):
    """Fase global de la sesión de voto."""
    IDLE = "idle"              # bienvenida, esperando tarjeta
    AUTH = "auth"              # verificando tarjeta / huella / rostro
    VERIFIED = "verified"      # identidad validada, sin mostrar datos personales
    LOADING = "loading"        # cargando la boleta
    SELECTING = "selecting"    # eligiendo candidatos
    REVIEW = "review"          # revisando la selección
    SUBMITTING = "submitting"  # voto enviado, esperando respuesta
    RESULT = "result"          # respuesta del backend recibida
    ERROR = "error"            # error antes de poder votar


class SubmitOutcome(str, Enum):
    REGISTERED = "registered"  # el backend confirmó el registro
    REJECTED = "rejected"      # el backend respondió que NO lo registró
    UNCERTAIN = "uncertain"    # no se puede saber si se registró


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    position_id: str
    photo_path: Optional[str] = None  # None -> la UI dibuja un avatar de ejemplo


@dataclass(frozen=True)
class Position:
    id: str
    title: str
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class StepResult:
    """Resultado de un paso de verificación.

    voter_ref es una referencia opaca al votante (solo la usa el controlador
    para pedir la boleta y enviar el voto). La UI nunca la muestra.
    """
    ok: bool
    message: str = ""
    voter_ref: Optional[str] = None


@dataclass(frozen=True)
class SubmitResult:
    outcome: SubmitOutcome
    message: str = ""
    receipt: Optional[str] = None  # solo se muestra si el backend lo devuelve
