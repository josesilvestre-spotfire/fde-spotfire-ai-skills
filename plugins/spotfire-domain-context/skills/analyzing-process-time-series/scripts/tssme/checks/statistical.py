"""Statistical checks, all of them regime-conditioned and autocorrelation-aware.

Two rules govern this module:
  1. Never compare a value to a baseline drawn from a different operating regime.
  2. Never use a naive standard error on a process series. Process data is autocorrelated;
     the naive SEM overstates significance, often by a large factor, and is the single most
     common source of confident nonsense in trend analysis.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..findings import Finding
from ..prep import Context, regime_normalise, _cusum_segments
from . import check
from ._gates import not_evaluated, unmet_precondition

SRC_AUTOCORR = ("Effective sample size under autocorrelation, n_eff = n(1-r1)/(1+r1) "
                "(Bayley & Hammersley 1946; Wilks, Statistical Methods in the Atmospheric Sciences)")
SRC_THEILSEN = "Theil-Sen robust slope estimator (Sen, JASA 1968), preferred over OLS for trend in the presence of outliers"


def _lag1(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 10:
        return 0.0
    x = x - x.mean()
    denom = float(np.dot(x, x))
    if denom == 0:
        return 0.0
    return float(np.dot(x[:-1], x[1:]) / denom)


def _n_eff(x: np.ndarray) -> tuple[float, float]:
    """Effective sample size after autocorrelation, and the lag-1 coefficient."""
    r1 = _lag1(x)
    n = int(np.isfinite(x).sum())
    r1 = min(max(r1, -0.99), 0.99)
    return max(n * (1 - r1) / (1 + r1), 2.0), r1


def _signature_roles(ctx: Context) -> list[str]:
    roles: list[str] = []
    for fm in ctx.card.failure_modes:
        for r in fm.get("signature", {}):
            if r in ctx.X.columns and r not in roles:
                roles.append(r)
    return roles


@check("stat_residual_bias", "statistical",
       description="Is a model-residual role centred on zero, accounting for autocorrelation")
def stat_residual_bias(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    pat = re.compile(r"^\s*mean\((\w+)\)\s+in\s+\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]\s*$")
    for inv in ctx.card.invariants:
        if inv["kind"] != "range":
            continue
        m = pat.match(inv["expr"])
        if not m:
            out.append(not_evaluated(ctx, inv, "stat_not_evaluated",
                                     "the expression is not of the form `mean(x) in [lo, hi]`"))
            continue
        if (skip := unmet_precondition(ctx, inv, "stat_not_evaluated")) is not None:
            out.append(skip)
            continue
        role, lo, hi = m.group(1), float(m.group(2)), float(m.group(3))
        if role not in ctx.X.columns:
            out.append(not_evaluated(ctx, inv, "stat_not_evaluated",
                                     f"{role} not in this dataset"))
            continue
        s = ctx.X[role].dropna()
        if len(s) < 20:
            out.append(not_evaluated(ctx, inv, "stat_not_evaluated",
                                     f"only {len(s)} samples of {role} (20 needed)"))
            continue
        x = s.to_numpy(dtype=float)
        mean = float(np.mean(x))
        n_eff, r1 = _n_eff(x)
        sem = float(np.std(x, ddof=1) / np.sqrt(n_eff))
        t = mean / sem if sem > 0 else np.nan
        inside = lo <= mean <= hi
        if inside:
            out.append(Finding(
                check_id="stat_residual_bias", unit_id=ctx.unit_id, severity="info", roles=[role],
                summary=f"{role} is centred at {mean:+.2f}, inside the expected band [{lo}, {hi}].",
                statistic={"mean": round(mean, 3), "band": [lo, hi], "n": int(len(x)),
                           "n_effective": round(n_eff, 1), "lag1_autocorr": round(r1, 3)},
                interpretation="The model is unbiased, so departures from zero can be read as process changes.",
                kind="verified", confidence="confirmed", source=inv.get("source", ""),
            ))
            continue
        out.append(Finding(
            check_id="stat_residual_bias", unit_id=ctx.unit_id,
            severity=inv.get("severity", "medium"), roles=[role],
            summary=(f"{role} is biased at {mean:+.2f} (expected within [{lo}, {hi}]), "
                     f"t={t:.1f} on {n_eff:.0f} effective samples."),
            statistic={"mean": round(mean, 3), "band": [lo, hi], "t_statistic": round(float(t), 2),
                       "n": int(len(x)), "n_effective": round(n_eff, 1),
                       "lag1_autocorr": round(r1, 3), "sem_autocorr_adjusted": round(sem, 4)},
            interpretation="A model residual with a persistent offset means the model is "
                           "mis-calibrated, not that the process is drifting. Until the bias is "
                           "explained, every threshold set on this residual inherits it, and the "
                           "magnitude of any excursion is measured from the wrong zero.",
            next_step="Reconcile the constant terms in the model first: line roughness, an omitted "
                      "static-head or elevation term, and instrument zero offsets. Only then trend it.",
            source=inv.get("source", "") + " | " + SRC_AUTOCORR,
        ))
    return out


def _band_adjusted_trend(y: pd.Series, t: pd.Series, g: pd.Series | None) -> dict | None:
    """Time slope with operating regime carried as a fixed effect.

    Z-scoring within regime -- the obvious approach -- is WRONG for trend detection: it
    subtracts each band's own mean, which absorbs exactly the drift you are looking for
    whenever band membership is correlated with time (it usually is, because throughput
    follows the season). Instead fit  y ~ intercept + slope*t + band effects  so the band
    absorbs the level while the slope stays interpretable.

    The standard error is inflated by sqrt(n/n_eff) because process residuals are
    autocorrelated and the naive OLS error would overstate significance.
    """
    d = pd.DataFrame({"y": y, "t": t, "g": g if g is not None else "all"}).dropna()
    if len(d) < 30:
        return None
    counts = d["g"].value_counts()
    d = d[d["g"].isin(counts[counts >= 3].index)]
    if len(d) < 30:
        return None

    yv = d["y"].to_numpy(dtype=float)
    tv = d["t"].to_numpy(dtype=float)
    if d["g"].nunique() > 1:
        G = pd.get_dummies(d["g"], drop_first=True).to_numpy(dtype=float)
        A = np.column_stack([np.ones(len(d)), tv, G])
    else:
        A = np.column_stack([np.ones(len(d)), tv])

    beta, *_ = np.linalg.lstsq(A, yv, rcond=None)
    resid = yv - A @ beta
    k = A.shape[1]
    dof = max(len(d) - k, 1)
    sigma2 = float(resid @ resid) / dof
    cov = np.linalg.pinv(A.T @ A)
    se_naive = float(np.sqrt(max(sigma2 * cov[1, 1], 0.0)))
    n_eff, r1 = _n_eff(resid)
    inflation = float(np.sqrt(len(d) / n_eff))
    se = se_naive * inflation
    slope = float(beta[1])
    tstat = slope / se if se > 0 else np.nan
    return {
        "slope_per_day": slope, "se": se, "t": tstat,
        "ci95": (slope - 1.96 * se, slope + 1.96 * se),
        "bands": int(d["g"].nunique()), "samples": int(len(d)),
        "span_days": float(tv.max() - tv.min()),
        "residual_sd": float(np.std(resid, ddof=1)),
        "lag1_autocorr": r1, "se_inflation": inflation,
    }


@check("stat_regime_drift", "statistical",
       description="Time trend with operating regime as a fixed effect, autocorrelation-adjusted")
def stat_regime_drift(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    idx = ctx.X.index
    if not isinstance(idx, pd.DatetimeIndex):
        return out
    days = pd.Series((idx - idx.min()).total_seconds() / 86400.0, index=idx)

    for role in _signature_roles(ctx):
        fit = _band_adjusted_trend(ctx.X[role], days, ctx.regime)
        if fit is None:
            continue
        lo, hi = fit["ci95"]
        if lo <= 0 <= hi:
            continue
        total = fit["slope_per_day"] * fit["span_days"]
        if fit["residual_sd"] <= 0:
            continue
        total_sd = total / fit["residual_sd"]
        if abs(total_sd) < 1.0:
            continue

        per_month = fit["slope_per_day"] * 30.0
        units = ctx.card.roles.get(role, {}).get("units", "")
        direction = "rising" if fit["slope_per_day"] > 0 else "falling"
        sev = "high" if abs(total_sd) > 2.5 else "medium"

        out.append(Finding(
            check_id="stat_regime_drift", unit_id=ctx.unit_id, severity=sev, roles=[role],
            summary=(f"{role} is {direction} at {per_month:+.3g} {units}/month after removing the "
                     f"operating-regime effect (t={fit['t']:+.1f}, "
                     f"{total_sd:+.1f} residual sd over {fit['span_days']:.0f} days)."),
            window=(str(idx.min()), str(idx.max())),
            statistic={"slope_per_month": round(per_month, 4),
                       "ci95_per_month": [round(lo * 30, 4), round(hi * 30, 4)],
                       "t_statistic": round(float(fit["t"]), 2),
                       "total_change": round(total, 3),
                       "total_change_residual_sd": round(total_sd, 2),
                       "regime_bands_in_model": fit["bands"],
                       "samples": fit["samples"],
                       "lag1_autocorr": round(fit["lag1_autocorr"], 3),
                       "se_inflation_for_autocorr": round(fit["se_inflation"], 2)},
            interpretation=("Operating regime is carried in the model as a fixed effect rather than "
                            "removed by within-band z-scoring, so this slope is not an artifact of "
                            "the unit running harder or softer over the period, and it has not been "
                            "absorbed by the regime either. That makes it a genuine change in the "
                            "equipment, the fluid, or the instrument."),
            next_step="Match the onset against the card's failure modes; a slope sustained over weeks "
                      "points to deposition or wear rather than a discrete event.",
            source=SRC_AUTOCORR,
        ))
    return out


@check("stat_changepoint", "statistical",
       description="Step changes in regime-normalised signals, clustered across correlated roles")
def stat_changepoint(ctx: Context, min_shift_sd: float = 2.0, cluster_samples: int = 10) -> list[Finding]:
    """One physical event moves many tags at once.

    Reporting a step separately for discharge pressure, actual drop, theoretical drop and
    pump head is four findings for one event, and it buries the real signal. Detect per
    role, then cluster by timestamp and report the event once with its corroborating tags.

    The shift is measured in units of WITHIN-SEGMENT sd, not of the whole series. Measured
    against the whole series a clean two-level step is capped at 2.0 sd no matter how large
    it is, because the series' own sd grows with the step; the cleaner the step, the closer
    to exactly 2.0. Any threshold near that value would then reject the most obvious steps
    in the data. Pooled within-segment sd is the noise the step has to stand out from, and
    the resulting effect size is unbounded.
    """
    detections: list[dict] = []
    for role in _signature_roles(ctx):
        z = regime_normalise(ctx.X[role], ctx.regime).dropna()
        if len(z) < 40:
            continue
        seg = pd.Series(_cusum_segments(z, threshold=8.0), index=z.index)
        if int(seg.nunique()) < 2:
            continue
        means = z.groupby(seg).agg(["mean", "size", "std"])
        means = means[means["size"] >= 5]
        if len(means) < 2:
            continue
        dof = (means["size"] - 1).sum()
        pooled = float(np.sqrt(((means["size"] - 1) * means["std"].fillna(0) ** 2).sum() / dof)) if dof > 0 else 0.0
        if not np.isfinite(pooled) or pooled <= 0:
            continue
        shifts = (means["mean"].diff().abs() / pooled).dropna()
        if shifts.empty or float(shifts.max()) < min_shift_sd:
            continue
        big = int(shifts.idxmax())
        boundary = seg[seg == big].index.min()
        detections.append({"role": role, "boundary": boundary,
                           "shift_sd": float(shifts.max()),
                           "pos": int(z.index.get_loc(boundary)),
                           "segments": int(seg.nunique())})
    if not detections:
        return []

    # CUSUM signals a change only after enough evidence accumulates, and that lag scales
    # inversely with the size of the shift: roughly threshold/(shift-drift) samples. Two
    # tags responding to the SAME physical event therefore trip days apart, the bigger
    # mover first. Clustering on a window narrower than that lag splits one event back into
    # one finding per tag, which is the noise this function exists to remove.
    detections.sort(key=lambda d: d["pos"])
    clusters: list[list[dict]] = []
    for det in detections:
        if clusters and det["pos"] - clusters[-1][-1]["pos"] <= cluster_samples:
            clusters[-1].append(det)
        else:
            clusters.append([det])

    out: list[Finding] = []
    for cl in clusters:
        lead = max(cl, key=lambda d: d["shift_sd"])
        roles = [d["role"] for d in cl]
        corroborated = len(cl) > 1
        out.append(Finding(
            check_id="stat_changepoint", unit_id=ctx.unit_id,
            severity="high" if (corroborated and lead["shift_sd"] >= 2.5) else "medium",
            roles=roles, window=(str(cl[0]["boundary"]), str(cl[-1]["boundary"])),
            summary=(f"Step change at {lead['boundary']} across {len(cl)} role(s) "
                     f"({', '.join(roles)}), largest {lead['shift_sd']:.1f} sd on {lead['role']}."),
            statistic={"roles_stepping": {d["role"]: round(d["shift_sd"], 2) for d in cl},
                       "detected_at": {d["role"]: str(d["boundary"]) for d in cl},
                       "lead_role": lead["role"],
                       "largest_shift_sd": round(lead["shift_sd"], 2),
                       "cluster_span_samples": cl[-1]["pos"] - cl[0]["pos"],
                       "shift_measured_against": "pooled within-segment sd",
                       "min_shift_threshold_sd": min_shift_sd},
            interpretation=("A step, not a ramp. Steps come from discrete causes: a valve position, "
                            "an injection change, a batch interface, a control change, or an "
                            "instrument recalibration. Deposition and wear do not step."
                            + (" Several tags move together at the same timestamp, which points to "
                               "one physical event rather than an instrument fault on any single tag."
                               if corroborated else
                               " Only one tag moves, which is more consistent with an instrument "
                               "fault than a process event.")),
            confidence="corroborated" if corroborated else "unconfirmed",
            next_step="Pull the operations log and SCADA change record for this timestamp before "
                      "considering any equipment explanation.",
            source="CUSUM change detection (Page, Biometrika 1954)",
        ))
    return out


@check("stat_detector_firing_rate", "statistical",
       description="Audit existing event/detector columns for firing rates that cannot be informative")
def stat_detector_firing_rate(ctx: Context) -> list[Finding]:
    """A detector that fires on most samples is not a detector.

    This audits event flags already present in the dataset, which is how you catch a
    threshold that was tuned by eye and never checked against its own base rate.
    """
    out: list[Finding] = []
    n = len(ctx.raw)
    for col in ctx.resolution.detector_columns:
        s = pd.to_numeric(ctx.raw[col], errors="coerce")
        valid = s.notna()
        if valid.sum() < 10:
            continue
        fires = (s.fillna(0) != 0)
        rate = float(fires.sum() / max(int(valid.sum()), 1))

        # Count events, not samples: contiguous runs of firing.
        runs = int(((fires.astype(int).diff() == 1) | (fires & (fires.index == fires.index[0]))).sum())

        if rate >= 0.20:
            out.append(Finding(
                check_id="stat_detector_firing_rate", unit_id=ctx.unit_id, severity="high",
                summary=(f"Detector column {col!r} fires on {rate:.0%} of samples "
                         f"({int(fires.sum())} of {int(valid.sum())})."),
                statistic={"firing_rate": round(rate, 3), "firing_samples": int(fires.sum()),
                           "valid_samples": int(valid.sum()), "event_runs": runs},
                interpretation=("At this rate the flag carries almost no information: it is close to "
                                "the base rate of the signal itself, so it cannot separate normal from "
                                "abnormal. A rate-of-change detector thresholded at zero fires on "
                                "roughly half of all samples by construction, because half of the "
                                "changes in any mean-reverting series are positive."),
                next_step=("Threshold on the magnitude of the change relative to its own regime-"
                           "conditioned distribution, not on its sign. Target a firing rate consistent "
                           "with the expected event base rate, typically low single-digit percent."),
                source="Base-rate discipline in alarm design (EEMUA 191; ISA-18.2 alarm rationalisation)",
            ))
        elif rate == 0.0:
            out.append(Finding(
                check_id="stat_detector_firing_rate", unit_id=ctx.unit_id, severity="low",
                summary=f"Detector column {col!r} never fires.",
                statistic={"firing_rate": 0.0, "valid_samples": int(valid.sum())},
                interpretation="An unfired detector is untested. It provides no evidence of health; "
                               "it may simply be mis-wired or thresholded out of reach.",
                next_step="Verify the threshold against the observed range of its input.",
            ))
        elif rate > 0.10:
            out.append(Finding(
                check_id="stat_detector_firing_rate", unit_id=ctx.unit_id, severity="medium",
                summary=f"Detector column {col!r} fires on {rate:.0%} of samples.",
                statistic={"firing_rate": round(rate, 3), "firing_samples": int(fires.sum()),
                           "valid_samples": int(valid.sum()), "event_runs": runs},
                interpretation="High enough to swamp a reviewer. Alarm floods train operators to "
                               "ignore the flag, which costs more than having no flag.",
                next_step="Rationalise the threshold against the expected event rate.",
                source="EEMUA 191 alarm rate guidance",
            ))
    return out
