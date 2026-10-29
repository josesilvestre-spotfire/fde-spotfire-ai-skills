"""Load, resolve, derive, and segment -- everything that must happen before any check runs.

Order matters and is not negotiable:
  1. load raw (keep every column; prior-analysis artifacts are evidence too)
  2. resolve tags to roles for one asset
  3. coerce numerics, keeping a record of what failed to coerce
  4. compute derived roles from card formulas
  5. segment operating regimes

Nothing compares a value to a threshold before step 5. Comparing across regimes is the
most common way to manufacture a false finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .cards import Card
from .resolve import Resolution


@dataclass
class Context:
    """Everything a check needs. Checks receive this and return list[Finding]."""

    card: Card
    resolution: Resolution
    raw: pd.DataFrame                       # original columns, original names, time-indexed
    X: pd.DataFrame                         # role-named numeric frame
    regime: pd.Series | None = None         # regime label per sample
    coercion_failures: dict[str, int] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def unit_id(self) -> str:
        return self.card.unit_id

    def has(self, *roles: str) -> bool:
        return all(r in self.X.columns and self.X[r].notna().any() for r in roles)

    def series(self, role: str) -> pd.Series:
        return self.X[role]

    def window_of(self, mask: pd.Series) -> tuple[str, str] | None:
        idx = self.X.index[mask.fillna(False).to_numpy()]
        if len(idx) == 0:
            return None
        return (str(idx.min()), str(idx.max()))


def load_frame(path: str, time_column: str = "Timestamp") -> pd.DataFrame:
    """Read a CSV export and index it by time. Unparseable timestamps are kept as NaT
    so that dq_timestamp_regularity can see them."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if time_column not in df.columns:
        raise ValueError(f"time column {time_column!r} not in {list(df.columns)[:8]}...")
    ts = pd.to_datetime(df[time_column], errors="coerce", format="mixed")
    df = df.drop(columns=[time_column])
    df.index = pd.Index(ts, name="timestamp")
    return df


def frame_from(df: pd.DataFrame, time_column: str = "Timestamp") -> pd.DataFrame:
    """Index an in-memory frame by time, the same way load_frame indexes a CSV.

    This is the entry point from a Spotfire data function, where the input table arrives
    as a DataFrame rather than as a file. The time column is used when present; otherwise
    the frame must already carry a DatetimeIndex. Unparseable timestamps become NaT and
    stay, exactly as in load_frame.
    """
    if time_column in df.columns:
        ts = pd.to_datetime(df[time_column], errors="coerce", format="mixed")
        out = df.drop(columns=[time_column]).copy()
        out.index = pd.Index(ts, name="timestamp")
        return out
    if isinstance(df.index, pd.DatetimeIndex):
        out = df.copy()
        out.index.name = "timestamp"
        return out
    raise ValueError(
        f"time column {time_column!r} not in {list(df.columns)[:8]}... and the frame has no "
        "DatetimeIndex. Pass the column that holds the timestamps."
    )


def build_context(raw: pd.DataFrame, card: Card, resolution: Resolution) -> Context:
    X = pd.DataFrame(index=raw.index)
    coercion_failures: dict[str, int] = {}

    for role, col in resolution.role_to_column.items():
        s = raw[col]
        num = pd.to_numeric(s, errors="coerce")
        bad = int((s.notna() & num.isna()).sum())
        if bad:
            coercion_failures[role] = bad
        X[role] = num

    ctx = Context(
        card=card, resolution=resolution, raw=raw, X=X,
        coercion_failures=coercion_failures,
    )
    _gate_invalid_rows(ctx)
    _compute_derived(ctx)
    _detect_rails(ctx)
    _segment_regimes(ctx)
    return ctx


def _gate_invalid_rows(ctx: Context) -> None:
    """Data quality gates everything downstream.

    A row with almost nothing in it is an export artifact, not a sample. Left in place it
    produces spurious invariant violations (a blank discharge pressure "below" a blank
    suction pressure) that outrank every real finding. The rows are recorded for
    dq_partial_rows to report, then blanked so no other check sees them.
    """
    roles = list(ctx.resolution.role_to_column)
    if not roles:
        return
    fill = ctx.X[roles].notna().mean(axis=1)
    invalid = fill < 0.5
    if not invalid.any():
        return
    ctx.meta["invalid_rows"] = {
        "count": int(invalid.sum()),
        "timestamps": [str(t) for t in ctx.X.index[invalid.to_numpy()]],
        "min_fill_fraction": float(fill.min()),
    }
    ctx.X.loc[invalid.to_numpy(), :] = np.nan


def _detect_rails(ctx: Context) -> None:
    """Find values pinned at the extremes of an otherwise continuous signal.

    Detected here rather than inside a check so that every check shares one definition of
    what counts as a measurement. A clamped value is not one: it must be reported by
    dq_rail_saturation AND excluded from the band excursions phys_range counts, or the same
    twelve clipped samples get reported twice under two different explanations.
    """
    rails: dict[str, dict] = {}
    masks: dict[str, pd.Series] = {}
    for role in ctx.X.columns:
        spec = ctx.card.roles.get(role, {})
        if spec.get("kind") not in ("sensor", "lab", "calculated"):
            continue
        s = ctx.X[role].dropna()
        if len(s) < 50:
            continue
        distinct_frac = s.nunique() / len(s)
        if distinct_frac < 0.5:
            continue  # coarse or held signal; dq_flatline and dq_zero_order_hold own that

        typical = float(s.value_counts().median())
        hits = []
        for end, val in (("min", float(s.min())), ("max", float(s.max()))):
            n_at = int((s == val).sum())
            if n_at >= 3 and n_at > max(3.0 * typical, 0.01 * len(s)):
                hits.append({"end": end, "value": val, "samples": n_at})
        if not hits:
            continue

        pinned = pd.Series(False, index=ctx.X.index)
        for h in hits:
            pinned |= (ctx.X[role] == h["value"])
        interior = s[(s > s.min()) & (s < s.max())]
        rails[role] = {
            "rails": hits,
            "pinned_samples": int(pinned.sum()),
            "pinned_fraction": round(float(pinned.sum()) / len(s), 4),
            "distinct_fraction": round(float(distinct_frac), 3),
            "median_value_multiplicity": typical,
            "unclamped_range": ([round(float(interior.min()), 4),
                                 round(float(interior.max()), 4)] if len(interior) else None),
        }
        masks[role] = pinned
    if rails:
        ctx.meta["rails"] = rails
        ctx.meta["rail_masks"] = masks


def _compute_derived(ctx: Context) -> None:
    """Evaluate card `derived` formulas in role namespace. A formula that cannot be
    evaluated (missing input role) is skipped and recorded, never faked."""
    skipped = {}
    for d in ctx.card.derived:
        expr, rid = d["expr"], d["id"]
        namespace = {c: ctx.X[c] for c in ctx.X.columns}
        namespace.update({"np": np, "pd": pd})
        try:
            with np.errstate(divide="ignore", invalid="ignore"):
                val = eval(expr, {"__builtins__": {}}, namespace)  # noqa: S307 - card-authored
            ctx.X[rid] = pd.Series(val, index=ctx.X.index).replace([np.inf, -np.inf], np.nan)
        except Exception as exc:  # missing role, bad formula
            skipped[rid] = f"{type(exc).__name__}: {exc}"
    if skipped:
        ctx.meta["derived_skipped"] = skipped


def _segment_regimes(ctx: Context) -> None:
    """Build the regime label. Checks that compare 'now' to 'normal' must do it inside
    a regime, because the plant's normal is a function of how hard it is running."""
    labels = []
    for reg in ctx.card.regimes:
        by = reg["by"]
        if by not in ctx.X.columns:
            continue
        s = ctx.X[by]
        method = reg["method"]
        if method == "bin":
            width = float(reg.get("params", {}).get("width", 1.0))
            lab = (np.floor(s / width) * width).astype("Float64")
            labels.append(lab.astype("string").radd(f"{reg['id']}="))
        elif method == "discrete":
            labels.append(s.astype("string").radd(f"{reg['id']}="))
        elif method == "changepoint":
            labels.append(pd.Series(_cusum_segments(s), index=s.index).astype("string").radd(f"{reg['id']}=seg"))
    if labels:
        out = labels[0]
        for extra in labels[1:]:
            out = out.str.cat(extra, sep="|", na_rep="NA")
        ctx.regime = out
        ctx.meta["regime_count"] = int(out.nunique(dropna=True))


def _cusum_segments(s: pd.Series, threshold: float = 5.0, warmup: int = 30) -> np.ndarray:
    """Minimal CUSUM segmentation. No external changepoint dependency by design --
    this library must run inside a Spotfire data function with numpy and pandas.

    Two details that look like implementation trivia and are not:

    The reference mean is seeded from the first `warmup` samples, NOT from the mean of the
    whole series. Seeding from the global mean guarantees a false changepoint near the
    start of any series that steps or trends: the early data sits a long way below (or
    above) a mean that the later data pulled, so the statistic crosses the threshold within
    a few samples and splits off a spurious opening segment that corresponds to no event.

    After a detection the reference is re-estimated from the next `warmup` samples rather
    than set to the single triggering value. One observation is a noisy reference, and it
    carries the excursion that caused the trigger, which biases every comparison after it.

    The scale stays global on purpose. A noise-only scale, estimated from successive
    differences, would detect faster but shatters a slowly ramping series into dozens of
    segments, and these segments are used as operating regimes. Detection lag is the price:
    expect tens of samples on a shift comparable to the series' own spread, which is why
    callers cluster nearby changepoints instead of matching timestamps exactly.
    """
    x = s.to_numpy(dtype=float)
    seg = np.zeros(len(x), dtype=int)
    finite = np.isfinite(x)
    if finite.sum() < 10:
        return seg
    sd = np.nanstd(x)
    if not np.isfinite(sd) or sd == 0:
        return seg

    def _reference(start: int) -> float:
        window = x[start:start + warmup]
        window = window[np.isfinite(window)]
        if len(window) == 0:
            return float(np.nanmean(x))
        return float(np.mean(window))

    mu = _reference(0)
    pos = neg = 0.0
    current = 0
    for i, v in enumerate(x):
        if not np.isfinite(v):
            seg[i] = current
            continue
        z = (v - mu) / sd
        pos = max(0.0, pos + z - 0.5)
        neg = min(0.0, neg + z + 0.5)
        if pos > threshold or neg < -threshold:
            current += 1
            pos = neg = 0.0
            mu = _reference(i)
        seg[i] = current
    return seg


def regime_normalise(values: pd.Series, regime: pd.Series | None, min_n: int = 5) -> pd.Series:
    """Z-score within regime. Regimes with too few samples return NaN rather than a
    z-score computed from three points."""
    if regime is None:
        mu, sd = values.mean(), values.std()
        return (values - mu) / sd if sd and np.isfinite(sd) else pd.Series(np.nan, index=values.index)
    out = pd.Series(np.nan, index=values.index, dtype=float)
    for key, idx in values.groupby(regime, dropna=True).groups.items():
        block = values.loc[idx]
        if block.notna().sum() < min_n:
            continue
        sd = block.std()
        if sd and np.isfinite(sd) and sd > 0:
            out.loc[idx] = (block - block.mean()) / sd
    return out
