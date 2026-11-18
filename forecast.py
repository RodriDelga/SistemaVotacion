"""Proyeccion de participacion (modelo puro, sin dependencias del backend).

Ajusta una curva logistica a los votos acumulados de la jornada y proyecta la participacion final y su
evolucion hasta el cierre, con un intervalo por *bootstrap* de las marcas de tiempo.

    C(t) = K * g(t),   g(t) = (f(t) - f(0)) / (1 - f(0)),   f(t) = 1 / (1 + exp(-r (t - t0)))

* ``t`` son horas desde la apertura; ``g(0) = 0`` (a la apertura no hay votos) y ``g -> 1``.
* ``K`` es el total final de votos y se acota a ``[votos_actuales, padron]``.

Ajuste: los votos se tratan como un proceso de Poisson no homogeneo con intensidad ``K g'(t)``. Agrupados en
intervalos de ~5 min, los conteos son multinomiales con probabilidades ``(g(b_j+1) - g(b_j)) / g(ahora)``; se
maximiza esa verosimilitud sobre ``(r, t0)`` (r en 1/h, t0 en h) con una rejilla gruesa y refinamientos sucesivos.
Dado ``(r, t0)``, el estimador de maxima verosimilitud de ``K`` es cerrado: ``K = votos / g(ahora)``.
Solo requiere ``numpy`` (sin scipy), apto para la Pi.

Intervalo: union de dos fuentes de incertidumbre. (1) *Bootstrap* de los conteos por intervalo (ruido de muestreo
del ajuste) mas llegadas futuras Poisson (los votos que faltan son aleatorios aunque la curva fuera exacta); domina
al final de la jornada. (2) Region de verosimilitud perfil: todos los ``(r, t0)`` cuya log-verosimilitud
queda a menos de ``chi2(1, nivel) / 2`` del maximo; recoge la ambiguedad estructural del inicio del dia (pocos votos
admiten curvas muy distintas, incluida «la jornada ya termino»), que el bootstrap por si solo no puede expresar.

Por que no minimos cuadrados sobre el acumulado: sus errores estan fuertemente correlacionados y, con pocos votos,
prefiere de forma enganosa un ajuste «la jornada ya termino» (K ~ votos actuales) frente a la curva verdadera.

Contrato: todas las fechas son *aware* (con zona horaria). No hay acceso a base de datos ni a la hora del sistema:
``now`` se pasa como argumento para que el calculo sea determinista y probable.

Limites asumidos (documentados en docs/DASHBOARD_DECISIONES.md): una curva suave y unimodal por jornada;
el intervalo refleja el ruido de muestreo, no un evento atipico (por ejemplo, una urna fuera de servicio).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import NormalDist
from typing import Sequence

import numpy as np

MODEL_LOGISTIC = "logistic"
MODEL_RECENT_RATE = "recent_rate"

STATUS_OK = "ok"
STATUS_NOT_OPEN = "not_open"
STATUS_CLOSED = "closed"
STATUS_INSUFFICIENT = "insufficient_data"
STATUS_NO_REGISTRY = "no_registry"
STATUS_NO_FIT = "no_fit"
STATUS_LOW_CONFIDENCE = "low_confidence"

REASONS = {
    STATUS_NOT_OPEN: "La jornada aún no ha iniciado.",
    STATUS_CLOSED: "La jornada ya cerró; el resultado es el conteo real.",
    STATUS_INSUFFICIENT: "Aún no hay suficientes votos para proyectar.",
    STATUS_NO_REGISTRY: "No hay padrón registrado.",
    STATUS_NO_FIT: "No fue posible ajustar un modelo estable con los datos actuales.",
    STATUS_LOW_CONFIDENCE: "Aún es pronto: el rango de proyección es demasiado amplio para dar una cifra.",
}

# Limites de busqueda (1/h y horas). r = 0.15 es una jornada casi lineal; r = 4 es un pico muy concentrado.
R_MIN, R_MAX = 0.15, 4.0
STEP_MINUTES = 15  # separacion de los puntos proyectados


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    percent: float  # estimacion central, % del padron
    low: float
    high: float


@dataclass(frozen=True)
class Forecast:
    status: str
    model: str
    reason: str | None = None
    based_on_votes: int = 0
    registered: int = 0
    final_percent: float | None = None
    final_low: float | None = None
    final_high: float | None = None
    interval: float = 0.8
    points: list[ForecastPoint] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


# ------------------------------------------------------------------ nucleo numerico
def _shape(t: np.ndarray, r: np.ndarray | float, t0: np.ndarray | float) -> np.ndarray:
    """g(t): logistica normalizada para que g(0)=0. Admite parametros con forma broadcastable."""
    f = 1.0 / (1.0 + np.exp(np.clip(-np.asarray(r) * (t - np.asarray(t0)), -60, 60)))
    f0 = 1.0 / (1.0 + np.exp(np.clip(np.asarray(r) * np.asarray(t0), -60, 60)))
    return (f - f0) / (1.0 - f0)


def _bin_counts(hours: np.ndarray, elapsed: float) -> tuple[np.ndarray, np.ndarray]:
    """Conteos de votos en intervalos de ~5 min entre 0 y ``elapsed`` (bordes incluidos)."""
    steps = max(8, int(np.ceil(elapsed * 60 / 5)))
    edges = np.linspace(0.0, elapsed, steps + 1)
    counts, _ = np.histogram(hours, bins=edges)
    return edges, counts.astype(float)


def _profile_loglik(edges: np.ndarray, counts: np.ndarray, r: np.ndarray, t0: np.ndarray) -> np.ndarray:
    """Log-verosimilitud multinomial de los conteos para cada (r, t0); r y t0 con la misma forma."""
    g = _shape(edges, r[..., None], t0[..., None])  # (..., bordes)
    total = np.maximum(g[..., -1], 1e-300)
    p = np.maximum(np.diff(g, axis=-1), 1e-300) / total[..., None]
    return (counts * np.log(p)).sum(axis=-1)


def _fit(edges: np.ndarray, counts: np.ndarray, horizon: float, registered: int, refine_rounds: int = 3):
    """Maxima verosimilitud de (r, t0) y K = votos / g(ahora), acotado a [votos, padron]. Devuelve (K, r, t0, loglik)."""
    n_now = float(counts.sum())
    elapsed = float(edges[-1])
    r_axis = np.exp(np.linspace(np.log(R_MIN), np.log(R_MAX), 26))
    t_axis = np.linspace(-1.0, horizon + 4.0, 40)
    r_span = (np.log(R_MIN), np.log(R_MAX))
    t_span = (float(t_axis[0]), float(t_axis[-1]))
    best = None
    for round_ in range(refine_rounds + 1):
        rr, tt = np.meshgrid(r_axis, t_axis, indexing="ij")
        ll = _profile_loglik(edges, counts, rr, tt)
        i = np.unravel_index(np.argmax(ll), ll.shape)
        best = (float(ll[i]), float(rr[i]), float(tt[i]))
        if round_ == refine_rounds:
            break
        shrink = 0.35 ** (round_ + 1)
        half_r = (r_span[1] - r_span[0]) * shrink / 2
        half_t = (t_span[1] - t_span[0]) * shrink / 2
        log_r = np.log(best[1])
        r_axis = np.exp(np.clip(np.linspace(log_r - half_r, log_r + half_r, 9), r_span[0], r_span[1]))
        t_axis = np.clip(np.linspace(best[2] - half_t, best[2] + half_t, 9), t_span[0], t_span[1])
    if not np.isfinite(best[0]):
        return None
    g_now = float(_shape(np.array([elapsed]), best[1], best[2])[0])
    k = n_now / g_now if g_now > 1e-12 else float(registered)
    return float(np.clip(k, n_now, registered)), best[1], best[2], best[0]


def _profile_region(edges: np.ndarray, counts: np.ndarray, horizon: float, registered: int,
                    ll_best: float, threshold: float):
    """(K, r, t0) de todos los puntos de una rejilla fina con loglik >= maximo - threshold."""
    n_now = float(counts.sum())
    r_axis = np.exp(np.linspace(np.log(R_MIN), np.log(R_MAX), 60))
    t_axis = np.linspace(-1.0, horizon + 4.0, 120)
    rr, tt = np.meshgrid(r_axis, t_axis, indexing="ij")
    ll = _profile_loglik(edges, counts, rr, tt)
    keep = ll >= max(ll_best, float(ll.max())) - threshold
    r_in, t_in = rr[keep], tt[keep]
    g_now = _shape(np.full(r_in.shape, edges[-1]), r_in, t_in)
    k = np.clip(n_now / np.maximum(g_now, 1e-12), n_now, registered)
    return k, r_in, t_in


def _future_hours(elapsed: float, total: float) -> np.ndarray:
    step = STEP_MINUTES / 60.0
    points = list(np.arange(elapsed, total, step)) + [total]
    return np.array(sorted(set(round(p, 9) for p in points)))


def _validate_inputs(opens: datetime, closes: datetime, now: datetime) -> None:
    for name, value in (("opens", opens), ("closes", closes), ("now", now)):
        if value.tzinfo is None:
            raise ValueError(f"{name} debe incluir zona horaria")
    if closes <= opens:
        raise ValueError("closes debe ser posterior a opens")


def _hours_since(opens: datetime, values: Sequence[datetime]) -> np.ndarray:
    return np.array(sorted((v - opens).total_seconds() / 3600.0 for v in values), dtype=float)


# --------------------------------------------------------------------- API publica
def fit_turnout(
    timestamps: Sequence[datetime],
    registered: int,
    opens: datetime,
    closes: datetime,
    now: datetime,
    *,
    min_votes: int = 100,
    min_minutes: int = 60,
    bootstrap: int = 200,
    interval: float = 0.8,
    max_interval_width: float = 30.0,
    min_done_fraction: float = 0.6,
    max_done_fraction: float = 0.95,
    early_day_fraction: float = 0.5,
    seed: int | None = 0,
) -> Forecast:
    """Proyecta la participacion final. Nunca lanza por falta de datos: devuelve ``status`` y ``reason``.

    Antes del pico de la jornada la curva logistica no esta identificada (muchos finales posibles ajustan igual de
    bien). Si el intervalo final mide mas de ``max_interval_width`` puntos porcentuales se devuelve
    ``low_confidence`` con el rango pero SIN cifra central ni serie, para no mostrar una precision falsa. Tambien
    se rechaza un ajuste que supone ya emitido ``max_done_fraction`` de los votos antes de ``early_day_fraction``
    de la jornada (artefacto de pocos datos). ``min_done_fraction`` exige haber visto ya el pico de la jornada.
    """
    _validate_inputs(opens, closes, now)
    if not 0.0 < interval < 1.0:
        raise ValueError("interval debe estar entre 0 y 1")
    if registered <= 0:
        return Forecast(STATUS_NO_REGISTRY, MODEL_LOGISTIC, REASONS[STATUS_NO_REGISTRY])
    if now < opens:
        return Forecast(STATUS_NOT_OPEN, MODEL_LOGISTIC, REASONS[STATUS_NOT_OPEN], registered=registered)

    seen = [t for t in timestamps if opens <= t <= min(now, closes)]
    n_now = len(seen)
    if now >= closes:
        pct = 100.0 * n_now / registered
        return Forecast(STATUS_CLOSED, MODEL_LOGISTIC, REASONS[STATUS_CLOSED], n_now, registered, pct, pct, pct, interval)

    elapsed = (now - opens).total_seconds() / 3600.0
    total = (closes - opens).total_seconds() / 3600.0
    if n_now < min_votes or elapsed * 60.0 < min_minutes:
        return Forecast(STATUS_INSUFFICIENT, MODEL_LOGISTIC, REASONS[STATUS_INSUFFICIENT], n_now, registered)

    hours = _hours_since(opens, seen)
    edges, counts = _bin_counts(hours, elapsed)
    fit = _fit(edges, counts, total, registered)
    if fit is None:
        return Forecast(STATUS_NO_FIT, MODEL_LOGISTIC, REASONS[STATUS_NO_FIT], n_now, registered)

    future = _future_hours(elapsed, total)

    def curve(k: float, r: float, t0: float) -> np.ndarray:
        # Monotona y nunca por debajo de lo ya votado.
        return np.maximum.accumulate(np.clip(k * _shape(future, r, t0), n_now, registered))

    k, r, t0, ll_best = fit
    centre = curve(k, r, t0)

    rng = np.random.default_rng(seed)

    def predictive_path(k_: float, r_: float, t0_: float) -> np.ndarray:
        """Trayectoria simulada: votos actuales + llegadas Poisson de cada tramo futuro (incertidumbre del proceso)."""
        expected = k_ * _shape(future, r_, t0_)
        lam = np.maximum(np.diff(expected, prepend=expected[0]), 0.0)
        return np.minimum(n_now + np.cumsum(rng.poisson(lam)), registered).astype(float)

    # (1) bootstrap de los conteos por intervalo + ruido de las llegadas futuras (Poisson)
    curves = []
    for _ in range(max(0, bootstrap)):
        sample = rng.multinomial(n_now, counts / n_now).astype(float)
        refit = _fit(edges, sample, total, registered, refine_rounds=2)
        if refit is not None:
            curves.append(predictive_path(*refit[:3]))
    tail = (1.0 - interval) / 2.0 * 100.0
    if len(curves) >= 20:
        stack = np.vstack(curves)
        low = np.percentile(stack, tail, axis=0)
        high = np.percentile(stack, 100.0 - tail, axis=0)
    else:
        low = high = centre
    # (2) region de verosimilitud perfil: curvas de todos los (r, t0) casi tan buenos como el maximo
    threshold = 0.5 * NormalDist().inv_cdf((1.0 + interval) / 2.0) ** 2
    k_in, r_in, t_in = _profile_region(edges, counts, total, registered, ll_best, threshold)
    if k_in.size:
        region = np.clip(k_in[:, None] * _shape(future[None, :], r_in[:, None], t_in[:, None]), n_now, registered)
        region = np.maximum.accumulate(region, axis=1)
        low = np.minimum(low, region.min(axis=0))
        high = np.maximum(high, region.max(axis=0))
    low = np.minimum(low, centre)
    high = np.maximum(high, centre)

    # Reglas de madurez/plausibilidad sobre la fraccion de la jornada que el ajuste da por completada.
    #  * Madurez: K solo es identificable tras observar el punto de inflexion (fraccion completada ~0.5); si el ajuste
    #    esta por debajo de ``min_done_fraction`` el pico aun no se ha visto y cualquier cifra es extrapolacion.
    #  * Plausibilidad: dar por emitido ``max_done_fraction`` de los votos con menos de ``early_day_fraction`` de la
    #    jornada transcurrida (p. ej. 95 % a las 2 h de 12) es un artefacto de pocos datos.
    done = float(_shape(np.array([elapsed]), r, t0)[0])
    immature = done < min_done_fraction
    implausible = done >= max_done_fraction and elapsed / total < early_day_fraction
    if immature or implausible:
        return Forecast(STATUS_LOW_CONFIDENCE, MODEL_LOGISTIC, REASONS[STATUS_LOW_CONFIDENCE], n_now, registered,
                        None, float(low[-1] * 100.0 / registered), float(high[-1] * 100.0 / registered), interval)

    to_pct = 100.0 / registered
    if (high[-1] - low[-1]) * to_pct > max_interval_width:
        return Forecast(STATUS_LOW_CONFIDENCE, MODEL_LOGISTIC, REASONS[STATUS_LOW_CONFIDENCE], n_now, registered,
                        None, float(low[-1] * to_pct), float(high[-1] * to_pct), interval)
    points = [
        ForecastPoint(opens + timedelta(hours=float(h)), float(c * to_pct), float(lo * to_pct), float(hi * to_pct))
        for h, c, lo, hi in zip(future, centre, low, high)
    ]
    return Forecast(
        STATUS_OK, MODEL_LOGISTIC, None, n_now, registered,
        float(centre[-1] * to_pct), float(low[-1] * to_pct), float(high[-1] * to_pct), interval, points,
    )


def baseline_recent_rate(
    timestamps: Sequence[datetime],
    registered: int,
    opens: datetime,
    closes: datetime,
    now: datetime,
    *,
    window_minutes: int = 60,
    min_votes: int = 30,
    min_minutes: int = 60,
) -> Forecast:
    """Linea base para comparar: votos actuales + (ritmo de la ultima ventana) x (horas restantes), acotado al padron."""
    _validate_inputs(opens, closes, now)
    if registered <= 0:
        return Forecast(STATUS_NO_REGISTRY, MODEL_RECENT_RATE, REASONS[STATUS_NO_REGISTRY])
    if now < opens:
        return Forecast(STATUS_NOT_OPEN, MODEL_RECENT_RATE, REASONS[STATUS_NOT_OPEN], registered=registered)
    seen = [t for t in timestamps if opens <= t <= min(now, closes)]
    n_now = len(seen)
    if now >= closes:
        pct = 100.0 * n_now / registered
        return Forecast(STATUS_CLOSED, MODEL_RECENT_RATE, REASONS[STATUS_CLOSED], n_now, registered, pct, pct, pct)
    elapsed_min = (now - opens).total_seconds() / 60.0
    if n_now < min_votes or elapsed_min < min_minutes:
        return Forecast(STATUS_INSUFFICIENT, MODEL_RECENT_RATE, REASONS[STATUS_INSUFFICIENT], n_now, registered)
    window = min(window_minutes, elapsed_min)
    recent = sum(1 for t in seen if t > now - timedelta(minutes=window))
    rate_per_h = recent / (window / 60.0)
    remaining = (closes - now).total_seconds() / 3600.0
    final = float(min(registered, n_now + rate_per_h * remaining))
    pct = 100.0 * final / registered
    return Forecast(STATUS_OK, MODEL_RECENT_RATE, None, n_now, registered, pct, pct, pct)
