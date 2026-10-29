"""Data quality checks. These run first and they are not a formality.

In historian data the large majority of apparent anomalies are artifacts: compression,
zero-order-held lab values, join duplicates, snapshot rows, frozen transmitters. Every one
of them will produce a confident false finding downstream if it is not caught here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..findings import Finding
from ..prep import Context
from . import check

SRC_COMPRESSION = "Historian deadband/exception compression and its effect on derived statistics (Thornhill, Choudhury & Shah, J.Process Control 2004, 'The impact of compression on data-driven process analyses')"


@check("dq_timestamp_regularity", "data_quality",
       description="Unparseable, duplicate, out-of-order timestamps and cadence gaps")
def dq_timestamp_regularity(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    idx = pd.Series(ctx.raw.index)

    n_nat = int(idx.isna().sum())
    if n_nat:
        out.append(Finding(
            check_id="dq_timestamp_regularity", unit_id=ctx.unit_id, severity="high",
            summary=f"{n_nat} row(s) have an unparseable timestamp.",
            statistic={"unparseable_rows": n_nat},
            interpretation="Rows without a valid timestamp cannot be ordered or differenced. "
                           "Any rolling or rate-of-change result computed over them is undefined.",
            next_step="Fix or drop these rows at the export step, not in the analysis.",
        ))

    valid = idx.dropna()
    n_dup = int(valid.duplicated().sum())
    if n_dup:
        out.append(Finding(
            check_id="dq_timestamp_regularity", unit_id=ctx.unit_id, severity="medium",
            summary=f"{n_dup} duplicate timestamp(s).",
            statistic={"duplicate_timestamps": n_dup},
            interpretation="Duplicates usually mean an export ran twice or a join fanned out. "
                           "They double-weight those samples in every aggregate.",
            next_step="De-duplicate on timestamp before analysis and confirm which copy is authoritative.",
        ))

    if not valid.is_monotonic_increasing:
        out.append(Finding(
            check_id="dq_timestamp_regularity", unit_id=ctx.unit_id, severity="medium",
            summary="Timestamps are not in increasing order.",
            interpretation="Rolling windows and diffs assume time order. Unsorted input silently "
                           "produces wrong rates of change.",
            next_step="Sort by timestamp at load.",
        ))

    if len(valid) > 3:
        deltas = valid.sort_values().diff().dropna()
        modal = deltas.mode()
        if len(modal):
            modal_td = modal.iloc[0]
            off = deltas[deltas > modal_td * 1.5]
            regular_frac = float((deltas == modal_td).mean())
            if len(off):
                gap_start = valid.sort_values().iloc[int(np.argmax(deltas.to_numpy() > modal_td * 1.5))]
                out.append(Finding(
                    check_id="dq_timestamp_regularity", unit_id=ctx.unit_id,
                    severity="low" if len(off) < 5 else "medium",
                    summary=f"{len(off)} gap(s) longer than 1.5x the modal sample interval ({modal_td}).",
                    statistic={"modal_interval": str(modal_td), "gaps": len(off),
                               "largest_gap": str(deltas.max()),
                               "regular_fraction": round(regular_frac, 3)},
                    window=(str(gap_start), str(valid.max())),
                    interpretation="Window-based statistics defined in samples (a 7-sample mean) "
                                   "silently change their time span across a gap. Define windows in "
                                   "time units, or resample to a regular grid first.",
                    next_step="Confirm whether gaps are outages (meaningful) or export failures (not).",
                    source=SRC_COMPRESSION,
                ))
    return out


@check("dq_duplicate_series", "data_quality",
       description="Columns that are exact duplicates of a mapped role")
def dq_duplicate_series(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for role, cands in ctx.resolution.duplicate_candidates.items():
        primary = cands[0]
        for dup in cands[1:]:
            a = pd.to_numeric(ctx.raw[primary], errors="coerce")
            b = pd.to_numeric(ctx.raw[dup], errors="coerce")
            both = a.notna() & b.notna()
            identical = bool(both.any() and np.allclose(a[both], b[both], equal_nan=True))
            out.append(Finding(
                check_id="dq_duplicate_series", unit_id=ctx.unit_id,
                severity="low" if identical else "medium", roles=[role],
                summary=(f"Column {dup!r} duplicates role {role!r} "
                         f"({'identical values' if identical else 'DIFFERENT values'})."),
                statistic={"primary": primary, "duplicate": dup, "identical": identical,
                           "compared_samples": int(both.sum())},
                interpretation=("A join artifact. Harmless if identical, but it doubles the role in "
                                "any 'all columns' operation such as correlation matrices or PCA, "
                                "inflating that variable's weight."
                                if identical else
                                "Two columns claim to be the same measurement and disagree. One of "
                                "them is wrong and every downstream result depends on which."),
                next_step="Drop the duplicate at the data-prep step and fix the join that created it.",
            ))
    return out


@check("dq_partial_rows", "data_quality",
       description="Rows where most mapped roles are empty (snapshot/append artifacts)")
def dq_partial_rows(ctx: Context) -> list[Finding]:
    info = ctx.meta.get("invalid_rows")
    if not info:
        return []
    n = info["count"]
    stamps = info["timestamps"]
    return [Finding(
        check_id="dq_partial_rows", unit_id=ctx.unit_id, severity="medium",
        summary=f"{n} row(s) have fewer than half of the expected measurements populated.",
        statistic={"partial_rows": n, "timestamps": stamps[:5],
                   "min_fill_fraction": round(info["min_fill_fraction"], 3),
                   "action": "blanked before all non-data-quality checks"},
        window=(stamps[0], stamps[-1]),
        interpretation="Near-empty rows are usually snapshot or append artifacts rather than real "
                       "samples. They are invisible in a line chart but they corrupt last-value "
                       "reads, diffs at the boundary, and any 'current state' summary.",
        next_step="Confirm these are export artifacts and filter them before analysis.",
    )]


@check("dq_flatline", "data_quality",
       description="Frozen sensor: long runs of an identical value on a measured role")
def dq_flatline(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    card_roles = ctx.card.roles
    n = len(ctx.X)
    min_run = max(5, int(0.03 * n))

    for role in ctx.X.columns:
        spec = card_roles.get(role, {})
        if spec.get("kind") not in ("sensor", "calculated"):
            continue
        if spec.get("control_role") == "CV":
            continue  # a controlled variable sitting on setpoint is expected, not frozen
        s = ctx.X[role].dropna()
        if len(s) < min_run * 2:
            continue
        grp = (s != s.shift()).cumsum()
        runs = s.groupby(grp).agg(["size", "first"])
        worst = runs[runs["size"] >= min_run].sort_values("size", ascending=False)
        if worst.empty:
            continue
        longest = int(worst.iloc[0]["size"])
        value = float(worst.iloc[0]["first"])
        frac = float(runs[runs["size"] >= min_run]["size"].sum() / len(s))
        out.append(Finding(
            check_id="dq_flatline", unit_id=ctx.unit_id,
            severity="high" if frac > 0.3 else "medium", roles=[role],
            summary=f"Role {role!r} holds a constant value for up to {longest} consecutive samples.",
            statistic={"longest_run": longest, "held_value": value,
                       "fraction_in_long_runs": round(frac, 3), "min_run_threshold": min_run},
            interpretation="A measured signal that does not move is usually a frozen transmitter, a "
                           "failed poll holding last-good, or a manually entered constant. Its "
                           "variance is fake, so it will look like the most stable and most "
                           "trustworthy tag in the dataset while carrying no information.",
            next_step=f"Confirm whether {role!r} is genuinely instrumented or is a constant entered upstream.",
            source=SRC_COMPRESSION,
        ))
    return out


@check("dq_zero_order_hold", "data_quality",
       description="Lab roles held constant between assays, and the staleness that creates")
def dq_zero_order_hold(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for role, spec in ctx.card.roles.items():
        if spec.get("kind") != "lab" or role not in ctx.X.columns:
            continue
        s = ctx.X[role].dropna()
        if len(s) < 10:
            continue
        changes = int((s != s.shift()).sum()) - 1
        if changes <= 0:
            continue
        eff_interval = len(s) / max(changes, 1)
        runs = (s != s.shift()).cumsum().value_counts()

        if eff_interval < 2.0:
            # Updates nearly every sample: this is not an assay being held, so the role is
            # mis-declared. That matters, because a lab role is treated as a slow
            # confounder and a computed one is not.
            out.append(Finding(
                check_id="dq_zero_order_hold", unit_id=ctx.unit_id, severity="low", roles=[role],
                summary=(f"Role {role!r} is declared kind 'lab' with a "
                         f"{spec.get('update_interval', 'unspecified')} cadence but changes on "
                         f"{changes} of {len(s)} samples."),
                statistic={"updates": changes, "samples": len(s),
                           "effective_update_interval_samples": round(float(eff_interval), 2),
                           "declared_update_interval": spec.get("update_interval", "unspecified")},
                interpretation="A value that moves every sample is not a raw assay held between "
                               "samples; it is interpolated, temperature-corrected, or modelled. "
                               "Treating a modelled property as an independent lab measurement makes "
                               "it look like corroborating evidence when it is partly derived from "
                               "the same drivers as the thing it is corroborating.",
                next_step=f"Confirm how {role!r} is produced and set its card `kind` accordingly.",
            ))
            continue

        out.append(Finding(
            check_id="dq_zero_order_hold", unit_id=ctx.unit_id,
            severity="medium" if eff_interval >= 5 else "low", roles=[role],
            summary=(f"Lab role {role!r} updates only every ~{eff_interval:.1f} samples "
                     f"({changes} distinct updates over {len(s)} samples) and is held constant between assays."),
            statistic={"updates": changes, "samples": len(s),
                       "effective_update_interval_samples": round(float(eff_interval), 2),
                       "longest_hold_samples": int(runs.max()),
                       "declared_update_interval": spec.get("update_interval", "unspecified")},
            interpretation="Lab values are zero-order-held between samples. Anything computed from "
                           "them inherits that staleness: the modelled value is right on assay day "
                           "and progressively wrong until the next one, which puts a sawtooth into "
                           "the residual that resets at each assay. That sawtooth is a model "
                           "artifact and must not be read as process behaviour.",
            next_step="Interpolate lab properties against a measured driver (temperature) instead of "
                      "holding them, or restrict residual trending to assay days.",
            source="Zero-order-hold artifact from merging lab cadence into a SCADA frame",
        ))
    return out


@check("dq_rail_saturation", "data_quality",
       description="Repeated exact values pinned at the extremes of an otherwise continuous signal")
def dq_rail_saturation(ctx: Context) -> list[Finding]:
    """A clipped signal looks like a measurement and is not one.

    When a transmitter hits the end of its calibrated range, or a model clamps an input to
    stay in its valid domain, the recorded value stops tracking the process and sits on the
    rail. In a line chart this is invisible. It does real damage in three ways: the true
    excursion is censored so the peak is understated, the rail value is the most repeated
    value in the series so it drags the mean and compresses the variance, and anyone
    calibrating a `normal` band from the observed min and max will anchor it to a number the
    instrument invented.

    The signature is a pile-up of the exact min or exact max in a signal that is otherwise
    near-continuous. A genuinely continuous measurement almost never repeats its own extreme.

    Detection happens in prep so that phys_range shares the same definition; this check only
    reports it.
    """
    out: list[Finding] = []
    for role, info in ctx.meta.get("rails", {}).items():
        hits = info["rails"]
        n_distinct = int(ctx.X[role].nunique())
        out.append(Finding(
            check_id="dq_rail_saturation", unit_id=ctx.unit_id,
            severity="medium" if info["pinned_fraction"] >= 0.02 else "low", roles=[role],
            summary=(f"Role {role!r} is pinned at "
                     + " and ".join(f"{h['end']} {h['value']:,.4g} on {h['samples']} sample(s)"
                                    for h in hits)
                     + f", against {n_distinct} distinct values overall."),
            statistic=info,
            interpretation="A continuous measurement does not repeat its own extreme this often. "
                           "The value is clipped, either by the transmitter range or by a clamp "
                           "applied upstream to keep a model input in its valid domain. The true "
                           "excursions are censored, so the peak is understated and the variance is "
                           "compressed.",
            next_step=(f"Do not calibrate the {role!r} band from the observed min and max; use the "
                       f"unclamped interior instead. Confirm the transmitter span and find the clamp "
                       f"in the source calculation."),
            source=SRC_COMPRESSION,
        ))
    return out


@check("dq_missing", "data_quality", description="Null fraction per required role")
def dq_missing(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for role in ctx.card.required_roles():
        if role not in ctx.X.columns:
            out.append(Finding(
                check_id="dq_missing", unit_id=ctx.unit_id, severity="high", roles=[role],
                summary=f"Required role {role!r} is not present in the dataset.",
                interpretation="Checks depending on this role cannot run; the analysis is partial.",
                next_step=f"Locate the historian tag for {role!r} and add it to the tag map.",
            ))
            continue
        frac = float(ctx.X[role].isna().mean())
        if frac > 0.05:
            out.append(Finding(
                check_id="dq_missing", unit_id=ctx.unit_id,
                severity="high" if frac > 0.4 else "low", roles=[role],
                summary=f"Role {role!r} is {frac:.1%} null.",
                statistic={"null_fraction": round(frac, 4)},
                interpretation="Gaps bias any statistic computed without accounting for them and "
                               "silently shorten rolling windows.",
                next_step="Determine whether nulls are outages, bad-quality codes, or export failures.",
            ))
    for role, n in ctx.coercion_failures.items():
        out.append(Finding(
            check_id="dq_missing", unit_id=ctx.unit_id, severity="medium", roles=[role],
            summary=f"Role {role!r} has {n} non-numeric value(s) that were coerced to null.",
            statistic={"coercion_failures": n},
            interpretation="Text in a numeric column is usually a quality code, a 'Bad', or a "
                           "units suffix. Coercing it to null hides a state the plant was reporting.",
            next_step="Recover the original strings and map quality codes explicitly.",
        ))
    return out
