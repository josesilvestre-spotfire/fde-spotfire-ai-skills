"""Relational checks: the card's invariants, compiled and evaluated against the data.

This is where SME knowledge becomes an executable assertion. An invariant is a statement
the process cannot violate. When one breaks, either the physics is wrong (it is not) or
the data is (it usually is), or something real and serious has changed.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..findings import Finding
from ..prep import Context
from ..robust import spearman
from . import check
from ._gates import missing_operands, not_evaluated, unmet_precondition


def _ns(ctx: Context) -> dict:
    ns = {c: ctx.X[c] for c in ctx.X.columns}
    ns.update({"np": np, "pd": pd, "abs": abs})
    return ns


def _operand_mask(ctx: Context, expr: str) -> pd.Series:
    """Rows where every column the expression touches is actually present.

    This must come from the OPERANDS, never from the result. A pandas comparison against
    NaN evaluates to False rather than NaN, so a blanked row silently reads as a failed
    inequality and outranks every real finding in the report.
    """
    names = set(re.findall(r"[A-Za-z_]\w*", expr)) & set(ctx.X.columns)
    mask = pd.Series(True, index=ctx.X.index)
    for n in names:
        mask &= ctx.X[n].notna()
    return mask


@check("rel_identity", "relational",
       description="Card identity and balance invariants (a == b, within tolerance)")
def rel_identity(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for inv in ctx.card.invariants:
        # A balance is an identity with a tolerance wide enough for metering uncertainty.
        if inv["kind"] not in ("identity", "balance"):
            continue
        if (skip := unmet_precondition(ctx, inv, "rel_not_evaluated")) is not None:
            out.append(skip)
            continue
        if "==" not in inv["expr"]:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     "the expression is not of the form `a == b`"))
            continue
        gone = missing_operands(ctx, inv["expr"])
        if gone:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"{', '.join(gone)} not in this dataset"))
            continue
        lhs_s, rhs_s = inv["expr"].split("==", 1)
        ns = _ns(ctx)
        try:
            lhs = eval(lhs_s.strip(), {"__builtins__": {}}, ns)  # noqa: S307 - card-authored
            rhs = eval(rhs_s.strip(), {"__builtins__": {}}, ns)  # noqa: S307
        except Exception as exc:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"the expression failed ({type(exc).__name__})"))
            continue
        diff = (pd.Series(lhs) - pd.Series(rhs)).dropna()
        if diff.empty:
            continue
        tol_abs = inv.get("tol_abs")
        tol = inv.get("tol")
        if tol_abs is not None:
            bad = diff.abs() > tol_abs
            tol_desc = f"|diff| > {tol_abs}"
        else:
            denom = pd.Series(rhs).abs().replace(0, np.nan)
            bad = (diff.abs() / denom) > (tol or 0.01)
            tol_desc = f"relative diff > {tol or 0.01}"
        if not bad.any():
            out.append(Finding(
                check_id="rel_identity", unit_id=ctx.unit_id, severity="info",
                summary=f"Invariant {inv['id']!r} holds across all {len(diff)} samples.",
                statistic={"max_abs_diff": float(diff.abs().max()), "samples": int(len(diff))},
                interpretation="The source-system calculation is internally consistent, so findings "
                               "built on it rest on a verified identity.",
                kind="verified", confidence="confirmed", source=inv.get("source", ""),
            ))
            continue
        out.append(Finding(
            check_id="rel_identity", unit_id=ctx.unit_id,
            severity=inv.get("severity", "high"),
            summary=f"Invariant {inv['id']!r} ({inv['expr']}) fails on {int(bad.sum())} sample(s).",
            statistic={"violations": int(bad.sum()), "samples": int(len(diff)),
                       "max_abs_diff": float(diff.abs().max()),
                       "mean_diff": float(diff.mean()), "tolerance": tol_desc},
            window=(str(diff.index[bad][0]), str(diff.index[bad][-1])),
            interpretation="A definitional identity does not fail for process reasons. Either the "
                           "source-system formula changed, the columns are misaligned, or an input "
                           "was updated without recomputing the derived column.",
            next_step="Recompute the derived column from its inputs and compare against the stored column.",
            source=inv.get("source", ""),
        ))
    return out


@check("rel_inequality", "relational", description="Card inequality invariants (a > b)")
def rel_inequality(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for inv in ctx.card.invariants:
        if inv["kind"] != "inequality":
            continue
        if (skip := unmet_precondition(ctx, inv, "rel_not_evaluated")) is not None:
            out.append(skip)
            continue
        gone = missing_operands(ctx, inv["expr"])
        if gone:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"{', '.join(gone)} not in this dataset"))
            continue
        try:
            ok = eval(inv["expr"], {"__builtins__": {}}, _ns(ctx))  # noqa: S307 - card-authored
        except Exception as exc:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"the expression failed ({type(exc).__name__})"))
            continue
        ok = pd.Series(ok, index=ctx.X.index)
        evaluable = _operand_mask(ctx, inv["expr"])
        bad = evaluable & (~ok.fillna(False).astype(bool))
        if not bad.any():
            out.append(Finding(
                check_id="rel_inequality", unit_id=ctx.unit_id, severity="info",
                summary=(f"Invariant {inv['id']!r} ({inv['expr']}) holds across all "
                         f"{int(evaluable.sum())} evaluable samples."),
                statistic={"evaluable_samples": int(evaluable.sum()),
                           "skipped_incomplete_rows": int((~evaluable).sum())},
                interpretation="The ordering the physics requires is present throughout, so tag "
                               "assignment and sign conventions for these roles are sound.",
                kind="verified", confidence="confirmed", source=inv.get("source", ""),
            ))
            continue
        out.append(Finding(
            check_id="rel_inequality", unit_id=ctx.unit_id,
            severity=inv.get("severity", "high"),
            summary=f"Invariant {inv['id']!r} ({inv['expr']}) is violated on {int(bad.sum())} sample(s).",
            statistic={"violations": int(bad.sum()), "evaluable_samples": int(evaluable.sum())},
            window=(str(ok.index[bad][0]), str(ok.index[bad][-1])),
            interpretation="This ordering is required by the physics of the unit. A violation means "
                           "swapped tags, a sign or unit error, or equipment that was not running "
                           "while the data still claims it was.",
            next_step="Verify tag assignment and engineering units, then check the run status over this window.",
            source=inv.get("source", ""),
        ))
    return out


@check("rel_power_law", "relational", description="Fitted exponent of a power-law relationship")
def rel_power_law(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    pat = re.compile(r"^\s*(\w+)\s*~\s*(\w+)\s*\*\*\s*n\s*$")
    for inv in ctx.card.invariants:
        if inv["kind"] != "power_law":
            continue
        if (skip := unmet_precondition(ctx, inv, "rel_not_evaluated")) is not None:
            out.append(skip)
            continue
        m = pat.match(inv["expr"])
        if not m:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     "the expression is not of the form `y ~ x ** n`"))
            continue
        ycol, xcol = m.group(1), m.group(2)
        gone = [c for c in (ycol, xcol) if c not in ctx.X.columns]
        if gone:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"{', '.join(gone)} not in this dataset"))
            continue
        d = ctx.X[[xcol, ycol]].dropna()
        d = d[(d[xcol] > 0) & (d[ycol] > 0)]
        if len(d) < 20:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"only {len(d)} positive paired samples (20 needed)"))
            continue
        lx, ly = np.log(d[xcol].to_numpy()), np.log(d[ycol].to_numpy())
        n_fit, intercept = np.polyfit(lx, ly, 1)
        resid = ly - (n_fit * lx + intercept)
        r2 = 1.0 - float(np.var(resid) / np.var(ly)) if np.var(ly) > 0 else float("nan")
        expected = float(inv.get("expected", 1.8))
        tol = float(inv.get("tol", 0.25))
        dev = abs(n_fit - expected)
        if dev <= tol:
            out.append(Finding(
                check_id="rel_power_law", unit_id=ctx.unit_id, severity="info",
                roles=[ycol, xcol],
                summary=(f"{ycol} scales as {xcol}^{n_fit:.2f} (expected {expected}), consistent "
                         f"with the card."),
                statistic={"fitted_exponent": round(float(n_fit), 3), "expected": expected,
                           "tolerance": tol, "r_squared": round(r2, 4), "samples": int(len(d))},
                interpretation="The measured relationship matches the physical model, so the flow "
                               "measurement, the line geometry, and the friction model are mutually "
                               "consistent.",
                kind="verified", confidence="confirmed", source=inv.get("source", ""),
            ))
            continue
        out.append(Finding(
            check_id="rel_power_law", unit_id=ctx.unit_id,
            severity=inv.get("severity", "medium"), roles=[ycol, xcol],
            summary=(f"{ycol} scales as {xcol}^{n_fit:.2f}, off the expected {expected} "
                     f"by {dev:.2f} (tolerance {tol})."),
            statistic={"fitted_exponent": round(float(n_fit), 3), "expected": expected,
                       "deviation": round(float(dev), 3), "tolerance": tol,
                       "r_squared": round(r2, 4), "samples": int(len(d))},
            interpretation="The exponent encodes the flow regime and the geometry. A value below "
                           "expectation suggests the drop is not purely friction (a fixed term such "
                           "as static head is mixed in); above expectation suggests a restriction "
                           "that worsens with rate, or a flow measurement error that scales.",
            next_step="Re-fit within a single flow band and confirm line diameter, length, and "
                      "elevation change against the asset record.",
            source=inv.get("source", ""),
        ))
    return out


@check("rel_monotonic", "relational", description="Monotonic relationship between two roles")
def rel_monotonic(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    pat = re.compile(r"^\s*(\w+)\s+(increasing|decreasing)\s+in\s+(\w+)\s*$")
    for inv in ctx.card.invariants:
        if inv["kind"] != "monotonic":
            continue
        if (skip := unmet_precondition(ctx, inv, "rel_not_evaluated")) is not None:
            out.append(skip)
            continue
        m = pat.match(inv["expr"])
        if not m:
            out.append(not_evaluated(
                ctx, inv, "rel_not_evaluated",
                "the expression is not of the form `y increasing|decreasing in x`"))
            continue
        ycol, direction, xcol = m.group(1), m.group(2), m.group(3)
        gone = [c for c in (ycol, xcol) if c not in ctx.X.columns]
        if gone:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"{', '.join(gone)} not in this dataset"))
            continue
        d = ctx.X[[xcol, ycol]].dropna()
        if len(d) < 20:
            out.append(not_evaluated(ctx, inv, "rel_not_evaluated",
                                     f"only {len(d)} paired samples (20 needed)"))
            continue
        rho, p = spearman(d[xcol].to_numpy(), d[ycol].to_numpy())
        want_negative = direction == "decreasing"
        ok = (rho < 0) if want_negative else (rho > 0)
        if ok or p > 0.05:
            continue
        out.append(Finding(
            check_id="rel_monotonic", unit_id=ctx.unit_id,
            severity=inv.get("severity", "medium"), roles=[ycol, xcol],
            summary=(f"{ycol} is expected to be {direction} in {xcol} but the measured rank "
                     f"correlation is {rho:+.2f} (p={p:.1e})."),
            statistic={"spearman_rho": round(float(rho), 3), "p_value": float(p),
                       "expected_direction": direction, "samples": int(len(d))},
            interpretation="When the measured relationship inverts the expected one, the observed "
                           "points are being driven by something other than the relationship under "
                           "test, most often a system change that moved both variables together.",
            next_step="Re-examine within a single operating regime before concluding anything about "
                      "the equipment.",
            source=inv.get("source", ""),
        ))
    return out
