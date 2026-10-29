"""Confounder tests: the benign explanations that must be excluded before a finding stands.

This is the part that separates an SME from a threshold alarm. Every failure mode on a card
names the confounders that produce the same signature. A finding whose confounders are
untested is reported as unconfirmed, never as a diagnosis.

Each test takes (ctx, window_mask, baseline_mask, conf_spec) and returns
(status, evidence) where status is ruled_out | not_ruled_out | untested.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from ..prep import Context

TESTS: dict[str, Callable] = {}


def confounder_test(name: str):
    def deco(fn):
        TESTS[name] = fn
        return fn
    return deco


def _stats(ctx: Context, role: str, win: pd.Series, base: pd.Series) -> dict | None:
    if role not in ctx.X.columns:
        return None
    s = ctx.X[role]
    w, b = s[win].dropna(), s[base].dropna()
    if len(w) < 1 or len(b) < 5:
        return None
    sd = float(b.std())
    if not np.isfinite(sd) or sd == 0:
        sd = float(abs(b.mean()) * 1e-6) or 1e-9
    return {
        "window_mean": float(w.mean()),
        "baseline_mean": float(b.mean()),
        "delta_sd": float((w.mean() - b.mean()) / sd),
        "baseline_sd": sd,
    }


@confounder_test("regime_shift")
def test_regime_shift(ctx: Context, win: pd.Series, base: pd.Series, spec: dict) -> tuple[str, dict]:
    """Was the comparison made within a shared operating regime?

    If the window's regimes also appear in the baseline, the regime-conditioned comparison
    is valid and throughput is excluded as an explanation.
    """
    if ctx.regime is None:
        return "untested", {"reason": "no regime segmentation available"}
    w_reg = set(ctx.regime[win].dropna().unique())
    b_reg = set(ctx.regime[base].dropna().unique())
    shared = w_reg & b_reg
    evidence = {"window_regimes": sorted(map(str, w_reg))[:6],
                "shared_with_baseline": sorted(map(str, shared))[:6],
                "shared_count": len(shared)}
    for role in spec.get("roles", []):
        st = _stats(ctx, role, win, base)
        if st:
            evidence[f"{role}_delta_sd"] = round(st["delta_sd"], 2)
    if shared:
        return "ruled_out", evidence
    return "not_ruled_out", {**evidence,
                             "reason": "window operates in regimes absent from the baseline; "
                                       "the comparison crosses operating points"}


@confounder_test("correlates_with")
def test_correlates_with(ctx: Context, win: pd.Series, base: pd.Series, spec: dict) -> tuple[str, dict]:
    """Did a driver variable move enough to explain the signature by itself?"""
    evidence, moved = {}, []
    tested = False
    for role in spec.get("roles", []):
        st = _stats(ctx, role, win, base)
        if st is None:
            continue
        tested = True
        evidence[f"{role}_delta_sd"] = round(st["delta_sd"], 2)
        evidence[f"{role}_window_mean"] = round(st["window_mean"], 3)
        if abs(st["delta_sd"]) > 1.0:
            moved.append(role)
    if not tested:
        return "untested", {"reason": "driver roles not present in dataset"}
    if moved:
        return "not_ruled_out", {**evidence, "moved": moved,
                                 "reason": f"{', '.join(moved)} shifted more than 1 sd in this window "
                                           "and could produce the same effect"}
    return "ruled_out", evidence


@confounder_test("step_change")
def test_step_change(ctx: Context, win: pd.Series, base: pd.Series, spec: dict) -> tuple[str, dict]:
    """Did the confounding variable step at or just before the window?"""
    evidence, stepped = {}, []
    tested = False
    idx = ctx.X.index
    win_start = idx[win.to_numpy()][0] if win.any() else None
    for role in spec.get("roles", []):
        if role not in ctx.X.columns:
            continue
        s = ctx.X[role]
        if s.notna().sum() < 5:
            continue
        tested = True
        st = _stats(ctx, role, win, base)
        if st:
            evidence[f"{role}_delta_sd"] = round(st["delta_sd"], 2)
        # a discrete jump in the run-up to the window
        d = s.diff().abs()
        sd = float(s.diff().std() or 0)
        if win_start is not None and sd > 0:
            lead = d.loc[:win_start].tail(3)
            jump = float(lead.max()) if len(lead) else 0.0
            evidence[f"{role}_max_jump_sd"] = round(jump / sd, 2)
            if jump / sd > 3.0:
                stepped.append(role)
        if st and abs(st["delta_sd"]) > 2.0 and role not in stepped:
            stepped.append(role)
    if not tested:
        return "untested", {"reason": "confounder roles not present in dataset"}
    if stepped:
        return "not_ruled_out", {**evidence, "stepped": stepped,
                                 "reason": f"{', '.join(stepped)} changed discretely at this window"}
    return "ruled_out", evidence


@confounder_test("zero_order_hold")
def test_zero_order_hold(ctx: Context, win: pd.Series, base: pd.Series, spec: dict) -> tuple[str, dict]:
    """Did a stale lab value refresh at this window, producing a model artifact?"""
    evidence, refreshed = {}, []
    tested = False
    idx = ctx.X.index
    win_idx = idx[win.to_numpy()]
    if len(win_idx) == 0:
        return "untested", {"reason": "empty window"}
    for role in spec.get("roles", []):
        if role not in ctx.X.columns:
            continue
        s = ctx.X[role]
        if s.notna().sum() < 5:
            continue
        tested = True
        changed = s != s.shift()
        n_updates = int(changed.sum()) - 1
        interval = len(s) / max(n_updates, 1)
        evidence[f"{role}_update_interval_samples"] = round(float(interval), 1)
        near = changed.loc[:win_idx[-1]].tail(len(win_idx) + 2)
        if bool(near.any()):
            refreshed.append(role)
    if not tested:
        return "untested", {"reason": "lab roles not present in dataset"}
    if refreshed:
        return "not_ruled_out", {**evidence, "refreshed": refreshed,
                                 "reason": f"{', '.join(refreshed)} refreshed at this window; the "
                                           "residual step may be the model catching up, not the process"}
    return "ruled_out", evidence


def run_confounders(ctx: Context, fm: dict, win: pd.Series, base: pd.Series) -> tuple[dict[str, str], dict]:
    """Run every confounder a failure mode names. Returns (status_map, evidence_map)."""
    registry = ctx.card.confounders
    statuses: dict[str, str] = {}
    evidence: dict[str, dict] = {}
    for cid in fm.get("confounders", []):
        spec = registry.get(cid)
        if spec is None:
            statuses[cid] = "untested"
            evidence[cid] = {"reason": "confounder not defined on card"}
            continue
        fn = TESTS.get(spec["test"])
        if fn is None:
            statuses[cid] = "untested"
            evidence[cid] = {"reason": f"no registered test {spec['test']!r}"}
            continue
        status, ev = fn(ctx, win, base, spec)
        statuses[cid] = status
        evidence[cid] = ev
    return statuses, evidence
