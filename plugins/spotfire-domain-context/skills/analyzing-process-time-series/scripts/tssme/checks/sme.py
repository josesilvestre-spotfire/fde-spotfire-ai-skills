"""SME checks: the ones that read the card's knowledge, not just the statistics.

`sme_signature_match` is the payoff of the whole design. A statistical detector says "this
is unusual". A signature match says "this pattern across these roles, at this onset rate,
with these alternatives excluded, is consistent with the failure mode the card names" --
and carries that mode's field verification step with it.

It is general on purpose: it reads `failure_modes`, `signature`, `confounders`,
`differentials` and `onset` off whatever card it is handed, and knows nothing about the
domain those came from. A check that encodes actual physics belongs in a pack
(`pack.yaml: check_modules`), not here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..findings import Finding, SEVERITY_ORDER
from ..prep import Context, regime_normalise
from . import check
from .confounders import run_confounders

_SEV_BY_RANK = {v: k for k, v in SEVERITY_ORDER.items()}

# What an observed direction is allowed to satisfy.
_MATCHES: dict[str, set[str]] = {
    "up": {"up", "sharp_up"},
    "sharp_up": {"sharp_up"},
    "down": {"down", "sharp_down"},
    "sharp_down": {"sharp_down"},
    "unchanged": {"unchanged", "flat"},
    "flat": {"flat", "unchanged"},
    "erratic": {"erratic"},
}

_FAST_ONSETS = {"instant", "hours"}
_SLOW_ONSETS = {"weeks", "months"}


def _downgrade(severity: str, steps: int) -> str:
    return _SEV_BY_RANK[max(0, SEVERITY_ORDER[severity] - steps)]


def _observed_direction(ctx: Context, role: str, win: pd.Series, base: pd.Series) -> dict | None:
    if role not in ctx.X.columns:
        return None
    s = ctx.X[role]
    w, b = s[win].dropna(), s[base].dropna()
    if len(w) < 1 or len(b) < 5:
        return None
    b_sd = float(b.std())
    if not np.isfinite(b_sd) or b_sd == 0:
        return {"label": "flat", "delta_sd": 0.0, "var_ratio": 1.0, "max_jump_sd": 0.0}
    delta = float((w.mean() - b.mean()) / b_sd)
    var_ratio = float((w.std() ** 2) / (b_sd ** 2)) if len(w) > 2 else 1.0
    dsd = float(s.diff().std() or 0)
    jump = float(s.diff()[win].abs().max() / dsd) if dsd > 0 and win.any() else 0.0

    if var_ratio > 2.5 and abs(delta) < 2:
        label = "erratic"
    elif delta > 2 and jump > 3:
        label = "sharp_up"
    elif delta > 1:
        label = "up"
    elif delta < -2 and jump > 3:
        label = "sharp_down"
    elif delta < -1:
        label = "down"
    elif abs(delta) < 0.5 and var_ratio < 1.5:
        label = "flat"
    else:
        label = "unchanged"
    return {"label": label, "delta_sd": round(delta, 2),
            "var_ratio": round(var_ratio, 2), "max_jump_sd": round(jump, 2)}


def _propose_windows(ctx: Context, z_thresh: float = 2.5, merge_gap: int = 2,
                     max_windows: int = 8) -> list[tuple[pd.Series, dict]]:
    """Candidate anomaly windows from regime-normalised excursions on card-relevant roles."""
    roles: list[str] = []
    for fm in ctx.card.failure_modes:
        for r in fm.get("signature", {}):
            if r in ctx.X.columns and r not in roles:
                roles.append(r)

    n = len(ctx.X)
    proposals: list[tuple[pd.Series, dict]] = []
    for role in roles:
        z = regime_normalise(ctx.X[role], ctx.regime)
        hot = (z.abs() > z_thresh).fillna(False).to_numpy()
        if not hot.any():
            continue
        # merge runs separated by small gaps
        idx = np.flatnonzero(hot)
        groups: list[list[int]] = []
        for i in idx:
            if groups and i - groups[-1][-1] <= merge_gap:
                groups[-1].append(int(i))
            else:
                groups.append([int(i)])
        for g in groups:
            mask = np.zeros(n, dtype=bool)
            mask[g[0]:g[-1] + 1] = True
            m = pd.Series(mask, index=ctx.X.index)
            peak = float(z.abs().to_numpy()[g].max())
            proposals.append((m, {"anchor_role": role, "peak_z": round(peak, 2),
                                  "length": int(g[-1] - g[0] + 1)}))

    proposals.sort(key=lambda p: -p[1]["peak_z"])
    # de-duplicate heavily overlapping windows
    kept: list[tuple[pd.Series, dict]] = []
    for m, meta in proposals:
        if any((m & k).sum() / max(int(m.sum()), 1) > 0.5 for k, _ in kept):
            continue
        kept.append((m, meta))
        if len(kept) >= max_windows:
            break
    return kept


@check("sme_signature_match", "sme",
       description="Match multi-tag failure-mode signatures from the card, with confounders excluded")
def sme_signature_match(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    windows = _propose_windows(ctx)
    if not windows:
        return out

    for win, wmeta in windows:
        base = ~win
        start, end = ctx.X.index[win.to_numpy()][0], ctx.X.index[win.to_numpy()][-1]
        observed = {}
        for fm in ctx.card.failure_modes:
            for role in fm.get("signature", {}):
                if role not in observed:
                    obs = _observed_direction(ctx, role, win, base)
                    if obs:
                        observed[role] = obs

        # Pass 1: which modes are consistent with this window at all.
        candidates: dict[str, float] = {}
        for fm in ctx.card.failure_modes:
            sig = fm.get("signature", {})
            ev = {r: d for r, d in sig.items() if r in observed}
            if len(ev) < 2:
                continue
            sc = sum(1 for r, want in ev.items()
                     if observed[r]["label"] in _MATCHES.get(want, {want})) / len(ev)
            if sc >= 0.6:
                candidates[fm["id"]] = sc

        # Pass 2: emit, each one aware of the competing diagnoses for the same window.
        for fm in ctx.card.failure_modes:
            if fm["id"] not in candidates:
                continue
            sig = fm.get("signature", {})
            evaluable = {r: d for r, d in sig.items() if r in observed}
            matched = {r: observed[r]["label"] for r, want in evaluable.items()
                       if observed[r]["label"] in _MATCHES.get(want, {want})}
            score = candidates[fm["id"]]

            # Competing faults: named differentials that also match, plus any other match.
            declared = [d for d in fm.get("differentials", []) if d in candidates]
            undeclared = [m for m in candidates
                          if m != fm["id"] and m not in declared]
            competing = declared + undeclared

            # Onset discrimination: a "weeks" mode that arrives as a step is not that mode.
            anchor = wmeta["anchor_role"]
            anchor_jump = observed.get(anchor, {}).get("max_jump_sd", 0.0)
            onset_conflict = ""
            if fm["onset"] in _SLOW_ONSETS and wmeta["length"] <= 2:
                onset_conflict = (f"card onset is '{fm['onset']}' but the excursion lasts only "
                                  f"{wmeta['length']} sample(s)"
                                  + (f" and arrives as a {anchor_jump:.1f} sd step" if anchor_jump > 4 else ""))
            if fm["onset"] in _FAST_ONSETS and wmeta["length"] > 10 and anchor_jump < 2:
                onset_conflict = (f"card onset is '{fm['onset']}' but the change develops over "
                                  f"{wmeta['length']} samples")

            statuses, evidence = run_confounders(ctx, fm, win, base)
            unresolved = [k for k, v in statuses.items() if v == "not_ruled_out"]
            untested = [k for k, v in statuses.items() if v == "untested"]

            severity = fm["severity"]
            confidence = "unconfirmed"
            if (not unresolved and not untested and score == 1.0
                    and not onset_conflict and not competing):
                confidence = "confirmed"
            elif not unresolved and score >= 0.6 and not onset_conflict:
                confidence = "corroborated"
            if unresolved:
                severity = _downgrade(severity, 1)
            if onset_conflict:
                severity = _downgrade(severity, 1)
            if untested and not unresolved:
                severity = _downgrade(severity, 1)

            reason_bits = []
            if unresolved:
                reason_bits.append("not ruled out: " + ", ".join(
                    f"{c} ({evidence[c].get('reason', '')})" for c in unresolved))
            if untested:
                reason_bits.append("untested: " + ", ".join(untested))
            if onset_conflict:
                reason_bits.append(onset_conflict)
            if competing:
                reason_bits.append(
                    "the same window also matches " + ", ".join(
                        f"{m} ({candidates[m]:.0%})" for m in competing)
                    + (" [declared differential]" if declared else " [NOT declared as a differential on the card]"))

            observed_text = ", ".join(
                "{}={}".format(r, observed[r]["label"]) for r in evaluable)
            interpretation = (
                f"{score:.0%} of the card signature for '{fm['name']}' is present over this "
                f"window ({observed_text}). "
            )
            if confidence == "confirmed":
                interpretation += ("Every alternative explanation the card names was tested and "
                                   "excluded, so this is a diagnosis rather than an observation.")
            else:
                interpretation += ("This is a candidate, not a diagnosis: "
                                   + "; ".join(reason_bits) + ".")

            out.append(Finding(
                check_id="sme_signature_match", unit_id=ctx.unit_id, severity=severity,
                roles=sorted(evaluable), window=(str(start), str(end)),
                summary=(f"Signature consistent with '{fm['name']}' over {start} to {end} "
                         f"(match {score:.0%}, confidence {confidence})."),
                statistic={"failure_mode": fm["id"], "match_score": round(score, 2),
                           "anchor_role": anchor, "peak_z": wmeta["peak_z"],
                           "window_samples": wmeta["length"], "card_onset": fm["onset"],
                           "competing_modes": {m: round(candidates[m], 2) for m in competing},
                           "matched_roles": sorted(matched),
                           "observed": {r: observed[r] for r in evaluable},
                           "confounder_evidence": evidence},
                interpretation=interpretation,
                confounders_tested=statuses,
                kind="candidate",
                confidence=confidence,
                next_step=" ".join(fm.get("verify_in_field", []))
                          or "Correlate with the operations log for this window.",
                source=fm.get("source", ""),
            ))
    return out
