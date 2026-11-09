"""Pruebas del modelo de proyeccion de participacion (forecast.py). Datos sinteticos, sin base de datos."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

import forecast as F

OPEN = datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)
CLOSE = OPEN + timedelta(hours=12)


def logistic_votes(seed: int, registered: int, turnout: float, r: float, t0: float) -> tuple[list[datetime], int]:
    """Jornada sintetica: votos muestreados de una logistica normalizada en [0, 12] h (verdad = turnout)."""
    rng = np.random.default_rng(seed)
    n = int(registered * turnout)
    grid = np.linspace(0, 12, 4001)
    cdf = F._shape(grid, r, t0)
    cdf = cdf / cdf[-1]
    hours = np.interp(rng.random(n), cdf, grid)
    return [OPEN + timedelta(hours=float(h)) for h in hours], n


def at(hours: float) -> datetime:
    return OPEN + timedelta(hours=hours)


class ValidationTest(unittest.TestCase):
    def test_naive_datetimes_rejected(self):
        with self.assertRaises(ValueError):
            F.fit_turnout([], 100, OPEN.replace(tzinfo=None), CLOSE, at(3))
        with self.assertRaises(ValueError):
            F.fit_turnout([], 100, OPEN, CLOSE, at(3).replace(tzinfo=None))

    def test_close_must_follow_open(self):
        with self.assertRaises(ValueError):
            F.fit_turnout([], 100, OPEN, OPEN, at(3))

    def test_interval_range(self):
        for bad in (0, 1, 1.5, -0.2):
            with self.assertRaises(ValueError):
                F.fit_turnout([], 100, OPEN, CLOSE, at(3), interval=bad)


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.votes, self.n = logistic_votes(1, 10000, 0.62, 0.8, 6.0)

    def test_no_registry(self):
        self.assertEqual(F.fit_turnout(self.votes, 0, OPEN, CLOSE, at(5)).status, F.STATUS_NO_REGISTRY)

    def test_before_open(self):
        result = F.fit_turnout(self.votes, 10000, OPEN, CLOSE, OPEN - timedelta(minutes=1))
        self.assertEqual(result.status, F.STATUS_NOT_OPEN)
        self.assertIsNone(result.final_percent)

    def test_closed_reports_actual_count(self):
        result = F.fit_turnout(self.votes, 10000, OPEN, CLOSE, CLOSE + timedelta(hours=1))
        self.assertEqual(result.status, F.STATUS_CLOSED)
        self.assertAlmostEqual(result.final_percent, 100 * self.n / 10000)
        self.assertEqual((result.final_low, result.final_high), (result.final_percent, result.final_percent))

    def test_insufficient_data(self):
        few = [at(0.1), at(0.2), at(0.3)]
        self.assertEqual(F.fit_turnout(few, 1000, OPEN, CLOSE, at(5)).status, F.STATUS_INSUFFICIENT)
        # votos de sobra pero solo 30 minutos de jornada
        burst = [at(i / 1000) for i in range(500)]
        self.assertEqual(F.fit_turnout(burst, 10000, OPEN, CLOSE, at(0.5)).status, F.STATUS_INSUFFICIENT)

    def test_empty_votes_never_raise(self):
        self.assertEqual(F.fit_turnout([], 1000, OPEN, CLOSE, at(5)).status, F.STATUS_INSUFFICIENT)

    def test_no_figure_before_the_peak_has_been_seen(self):
        """A las 4 h de 12 la inflexion (t0 = 5 h) aun no ocurre: se devuelve el rango, nunca una cifra central."""
        for seed in range(1, 6):
            votes, _ = logistic_votes(seed, 10000, 0.45, 1.5, 5.0)
            result = F.fit_turnout(votes, 10000, OPEN, CLOSE, at(4), bootstrap=60)
            self.assertEqual(result.status, F.STATUS_LOW_CONFIDENCE, seed)
            self.assertIsNone(result.final_percent)
            self.assertEqual(result.points, [])
            self.assertLess(result.final_low, result.final_high)


class FitQualityTest(unittest.TestCase):
    def test_recovers_final_turnout_after_the_peak(self):
        for seed, (turnout, r, t0) in enumerate([(0.62, 0.8, 6.0), (0.45, 1.5, 5.0), (0.70, 0.6, 6.5)], start=10):
            votes, n = logistic_votes(seed, 10000, turnout, r, t0)
            result = F.fit_turnout(votes, 10000, OPEN, CLOSE, at(8))
            truth = 100 * n / 10000
            self.assertTrue(result.ok, (turnout, result.status))
            self.assertAlmostEqual(result.final_percent, truth, delta=3.0, msg=f"turnout={turnout}")
            # La cobertura del intervalo (nominal 80 %) se valida de forma agregada en la prueba de calibracion.

    def test_interval_is_roughly_calibrated_late_in_the_day(self):
        """Cobertura empirica del intervalo al 80 % a las 8 h de 12 (jornadas sinteticas con semilla fija)."""
        scenarios = [(0.62, 0.8, 6.0), (0.45, 1.5, 5.0), (0.70, 0.6, 6.5), (0.55, 1.0, 4.0)]
        covered = total = 0
        for i, (turnout, r, t0) in enumerate(scenarios):
            for seed in range(5):
                votes, n = logistic_votes(200 + 10 * i + seed, 10000, turnout, r, t0)
                result = F.fit_turnout(votes, 10000, OPEN, CLOSE, at(8), bootstrap=100)
                self.assertTrue(result.ok)
                total += 1
                covered += result.final_low - 1e-9 <= 100 * n / 10000 <= result.final_high + 1e-9
        self.assertGreaterEqual(covered / total, 0.6)  # nominal 0.8; con 20 jornadas el margen de error es ~ +-9 pts

    def test_deterministic_with_seed(self):
        votes, _ = logistic_votes(3, 5000, 0.6, 0.9, 6.0)
        a = F.fit_turnout(votes, 5000, OPEN, CLOSE, at(7), seed=7)
        b = F.fit_turnout(votes, 5000, OPEN, CLOSE, at(7), seed=7)
        self.assertEqual((a.final_percent, a.final_low, a.final_high), (b.final_percent, b.final_low, b.final_high))

    def test_input_order_and_out_of_window_votes_are_irrelevant(self):
        votes, _ = logistic_votes(4, 5000, 0.6, 0.9, 6.0)
        base = F.fit_turnout(votes, 5000, OPEN, CLOSE, at(8))
        noisy = list(reversed(votes)) + [OPEN - timedelta(hours=3), at(9), at(11)]  # fuera de [apertura, ahora]
        other = F.fit_turnout(noisy, 5000, OPEN, CLOSE, at(8))
        self.assertEqual(base.based_on_votes, other.based_on_votes)
        self.assertAlmostEqual(base.final_percent, other.final_percent, places=9)

    def test_series_is_monotone_bounded_and_well_formed(self):
        votes, _ = logistic_votes(5, 8000, 0.7, 0.7, 6.0)
        now = at(8)
        result = F.fit_turnout(votes, 8000, OPEN, CLOSE, now)
        self.assertTrue(result.ok)
        current = 100 * result.based_on_votes / 8000
        self.assertEqual(result.points[0].timestamp, now)
        self.assertEqual(result.points[-1].timestamp, CLOSE)
        previous = -1.0
        for p in result.points:
            self.assertGreaterEqual(p.percent, previous)
            self.assertGreaterEqual(p.percent, current - 1e-9)
            self.assertLessEqual(p.percent, 100.0 + 1e-9)
            self.assertLessEqual(p.low, p.percent + 1e-9)
            self.assertGreaterEqual(p.high, p.percent - 1e-9)
            previous = p.percent
        self.assertAlmostEqual(result.points[-1].percent, result.final_percent)

    def test_never_exceeds_registry(self):
        votes, _ = logistic_votes(6, 1000, 0.98, 1.0, 5.0)
        result = F.fit_turnout(votes, 1000, OPEN, CLOSE, at(8))
        if result.ok:
            self.assertLessEqual(result.final_high, 100.0 + 1e-9)

    def test_flat_constant_rate_does_not_crash(self):
        votes = [at(h / 20) for h in range(0, 180)]  # 20 votos por hora durante 9 h, sin pico
        result = F.fit_turnout(votes, 1000, OPEN, CLOSE, at(9))
        self.assertIn(result.status, {F.STATUS_OK, F.STATUS_LOW_CONFIDENCE, F.STATUS_NO_FIT})
        if result.ok:
            self.assertGreaterEqual(result.final_percent, 100 * 180 / 1000 - 1e-9)


class BaselineTest(unittest.TestCase):
    def test_constant_rate_is_extrapolated_linearly(self):
        votes = [at(h / 20) for h in range(0, 120)]  # 20 votos/h durante 6 h
        result = F.baseline_recent_rate(votes, 1000, OPEN, CLOSE, at(6))
        self.assertTrue(result.ok)
        # La ventana de 60 min deja fuera el voto del borde: 19 o 20 votos/h segun el criterio (+-0.6 puntos).
        self.assertAlmostEqual(result.final_percent, 100 * (120 + 20 * 6) / 1000, delta=1.0)

    def test_capped_at_registry(self):
        votes = [at(h / 100) for h in range(0, 600)]  # 100 votos/h
        result = F.baseline_recent_rate(votes, 700, OPEN, CLOSE, at(6))
        self.assertEqual(result.final_percent, 100.0)

    def test_statuses(self):
        self.assertEqual(F.baseline_recent_rate([], 100, OPEN, CLOSE, at(5)).status, F.STATUS_INSUFFICIENT)
        self.assertEqual(F.baseline_recent_rate([], 0, OPEN, CLOSE, at(5)).status, F.STATUS_NO_REGISTRY)
        self.assertEqual(F.baseline_recent_rate([], 100, OPEN, CLOSE, OPEN - timedelta(hours=1)).status, F.STATUS_NOT_OPEN)
        self.assertEqual(F.baseline_recent_rate([at(1)], 100, OPEN, CLOSE, CLOSE).status, F.STATUS_CLOSED)


if __name__ == "__main__":
    unittest.main()
