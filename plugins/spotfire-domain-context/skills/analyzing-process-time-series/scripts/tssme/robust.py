"""Rank correlation and robust slope, with or without scipy.

The Python environment bundled with Spotfire Analyst 15.0 carries numpy and pandas but not
scipy. These two functions are the only statistics the engine and its packs need from
scipy, so each one uses scipy when it can be imported and an exact NumPy implementation of
the same method when it cannot. Both paths return the same numbers on untied data; the
tests in `tests/test_tssme.py` compare them.

    spearman(x, y)               -> (rho, two-sided p-value)
    theil_sen(y, x, confidence)  -> (slope, intercept, lo_slope, hi_slope)
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

try:  # pragma: no cover - depends on the environment
    from scipy import stats as _scipy_stats
except ImportError:  # pragma: no cover
    _scipy_stats = None


def have_scipy() -> bool:
    return _scipy_stats is not None


# ------------------------------------------------------------------ incomplete beta

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(log_front) * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, dof: float) -> float:
    """Two-sided p-value of Student's t with `dof` degrees of freedom."""
    if not np.isfinite(t):
        return 0.0
    return betainc(dof / 2.0, 0.5, dof / (dof + t * t))


# ------------------------------------------------------------------------ spearman

def spearman(x, y) -> tuple[float, float]:
    """Spearman rank correlation and its two-sided p-value (t approximation, n - 2 dof),
    the same statistic scipy.stats.spearmanr reports."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if _scipy_stats is not None:
        res = _scipy_stats.spearmanr(x, y)
        return float(res[0]), float(res[1])
    return spearman_numpy(x, y)


def spearman_numpy(x, y) -> tuple[float, float]:
    """The NumPy path of `spearman`, callable directly so tests can compare it."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    rx = pd.Series(x).rank(method="average").to_numpy()
    ry = pd.Series(y).rank(method="average").to_numpy()
    rx, ry = rx - rx.mean(), ry - ry.mean()
    denom = math.sqrt(float(rx @ rx) * float(ry @ ry))
    if denom == 0 or n < 3:
        return float("nan"), float("nan")
    rho = float(rx @ ry) / denom
    rho = max(-1.0, min(1.0, rho))
    dof = n - 2
    if abs(rho) >= 1.0:
        return rho, 0.0
    t = rho * math.sqrt(dof / ((1.0 - rho) * (1.0 + rho)))
    return rho, t_two_sided_p(t, dof)


# ----------------------------------------------------------------------- theil-sen

def _tie_counts(v: np.ndarray) -> np.ndarray:
    _, counts = np.unique(v, return_counts=True)
    return counts[counts > 1]


def theil_sen(y, x, confidence: float = 0.95) -> tuple[float, float, float, float]:
    """Theil-Sen slope with Sen's (1968) confidence interval.

    Returns (slope, intercept, lo_slope, hi_slope). The intercept is
    median(y) - slope * median(x). Matches scipy.stats.theilslopes with its default
    `method='separate'`.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if _scipy_stats is not None:
        res = _scipy_stats.theilslopes(y, x, alpha=confidence)
        return float(res[0]), float(res[1]), float(res[2]), float(res[3])
    return theil_sen_numpy(y, x, confidence)


def theil_sen_numpy(y, x, confidence: float = 0.95) -> tuple[float, float, float, float]:
    """The NumPy path of `theil_sen`, callable directly so tests can compare it."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    dx = x[:, None] - x
    dy = y[:, None] - y
    pos = dx > 0
    slopes = np.sort(dy[pos] / dx[pos])
    if slopes.size == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    slope = float(np.median(slopes))
    intercept = float(np.median(y) - slope * np.median(x))

    alpha = 1.0 - confidence if confidence > 0.5 else confidence
    z = NormalDist().inv_cdf(alpha / 2.0)            # negative
    n = len(y)
    nt = len(slopes)
    sigsq = (n * (n - 1) * (2 * n + 5)
             - sum(int(k) * (int(k) - 1) * (2 * int(k) + 5) for k in _tie_counts(x))
             - sum(int(k) * (int(k) - 1) * (2 * int(k) + 5) for k in _tie_counts(y))) / 18.0
    try:
        sigma = math.sqrt(sigsq)
        ru = min(int(np.round((nt - z * sigma) / 2.0)), nt - 1)
        rl = max(int(np.round((nt + z * sigma) / 2.0)) - 1, 0)
        lo, hi = float(slopes[rl]), float(slopes[ru])
    except (ValueError, IndexError):
        lo, hi = float("nan"), float("nan")
    return slope, intercept, lo, hi
