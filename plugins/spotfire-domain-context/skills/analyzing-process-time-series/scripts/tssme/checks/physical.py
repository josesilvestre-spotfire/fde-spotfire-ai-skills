"""Physical plausibility: is the number possible at all, before asking if it is unusual."""

from __future__ import annotations

import pandas as pd

from ..findings import Finding
from ..prep import Context
from . import check


@check("phys_range", "physical", description="Values outside card normal band or hard limits")
def phys_range(ctx: Context) -> list[Finding]:
    out: list[Finding] = []

    # Hard limits are a property of the instrument and the metal, so only measured roles
    # carry them.
    for role, spec in ctx.card.roles.items():
        if role not in ctx.X.columns:
            continue
        s = ctx.X[role].dropna()
        if s.empty:
            continue
        limits = spec.get("limits") or {}
        lo, hi = limits.get("lo"), limits.get("hi")
        if lo is None and hi is None:
            continue
        bad = pd.Series(False, index=s.index)
        if lo is not None:
            bad |= s < lo
        if hi is not None:
            bad |= s > hi
        if not bad.any():
            continue
        out.append(Finding(
            check_id="phys_range", unit_id=ctx.unit_id, severity="critical", roles=[role],
            summary=f"Role {role!r} breaches its hard limit on {int(bad.sum())} sample(s).",
            statistic={"violations": int(bad.sum()), "limits": limits,
                       "observed_min": float(s.min()), "observed_max": float(s.max())},
            window=(str(s.index[bad][0]), str(s.index[bad][-1])),
            interpretation="A value outside the mechanical or physical limit is not an "
                           "operating condition, it is a measurement or unit-conversion "
                           "fault. Treat it as a data problem until proven otherwise.",
            next_step=f"Check the {role!r} transmitter range, scaling, and engineering units.",
            source=spec.get("source", ""),
        ))

    # Normal bands are carried by roles AND by derived quantities, because a derived
    # quantity is often where the well-formed band lives.
    for role, spec in ctx.card.banded_specs().items():
        if role not in ctx.X.columns:
            continue
        s = ctx.X[role].dropna()
        if s.empty:
            continue

        # A clamped value is not a measurement, so it cannot be a band excursion either.
        # Without this, the same clipped samples are reported twice: once correctly by
        # dq_rail_saturation and once by this check under a process explanation that is
        # simply wrong.
        rail_mask = ctx.meta.get("rail_masks", {}).get(role)
        n_pinned = 0
        if rail_mask is not None:
            pinned_here = rail_mask.reindex(s.index).fillna(False).to_numpy()
            n_pinned = int(pinned_here.sum())
            s = s[~pinned_here]
            if s.empty:
                continue

        nlo, nhi = spec["normal"]
        outside = (s < nlo) | (s > nhi)
        if not outside.any():
            continue
        frac = float(outside.mean())

        stat = {"outside_fraction": round(frac, 4), "normal": [nlo, nhi],
                "clamped_samples_excluded": n_pinned,
                "observed_min": float(s.min()), "observed_max": float(s.max()),
                "p01": float(s.quantile(0.01)), "p99": float(s.quantile(0.99)),
                "suggested_band": [round(float(s.quantile(0.01)), 4),
                                   round(float(s.quantile(0.99)), 4)]}
        window = (str(s.index[outside][0]), str(s.index[outside][-1]))

        # A normative band is a specification or a model-quality target, not a description
        # of this asset. Missing it a quarter of the time is the finding, not evidence that
        # the target is wrong, so the recalibration branch below must never apply to it.
        if spec.get("band_type") == "normative":
            out.append(Finding(
                check_id="phys_range", unit_id=ctx.unit_id,
                severity="high" if frac >= 0.10 else "medium", roles=[role],
                summary=(f"{role!r} is outside its specified band [{nlo}, {nhi}] on "
                         f"{frac:.1%} of samples (observed {float(s.min()):,.4g} to "
                         f"{float(s.max()):,.4g})."),
                statistic=stat | {"band_type": "normative"}, window=window,
                interpretation=("This band is a specification, not a description of how this asset "
                                "happens to run, so a high excursion rate does not mean the band "
                                "needs widening. It means the unit spends that fraction of its time "
                                "off-spec, or the model behind the band is wrong."),
                next_step=(f"Do not widen this band. Establish why {role!r} sits outside it: for a "
                           "model residual, reconcile the model; for a process spec, treat the "
                           "excursion time as the finding."),
                source=spec.get("source", ""),
            ))
            continue

        # For a descriptive band, severity is deliberately NOT monotonic in the excursion
        # fraction. A handful of excursions is a process event worth explaining. A quarter
        # of the record outside the band is evidence the card is wrong about this asset,
        # and escalating it would bury real findings under the analyst's own assumption.
        if frac >= 0.20:
            out.append(Finding(
                check_id="phys_range", unit_id=ctx.unit_id, severity="low", roles=[role],
                summary=(f"Card band for {role!r} does not fit this asset: {frac:.0%} of samples "
                         f"fall outside [{nlo}, {nhi}], observed range "
                         f"{float(s.min()):,.4g} to {float(s.max()):,.4g}."),
                statistic=stat | {"band_type": "descriptive"}, window=window,
                interpretation=("This is a card calibration problem, not a plant problem. A band that "
                                "excludes a quarter of normal operation was written from too small a "
                                "sample. Escalating it would bury real findings under the analyst's "
                                "own assumption."),
                next_step=(f"Widen the {role!r} band toward the observed 1st-99th percentile "
                           f"{stat['suggested_band']} and cite the asset's design basis, or confirm "
                           "this asset really does run outside its design envelope. Check "
                           "dq_rail_saturation first: never calibrate a band from clamped extremes."),
                source=spec.get("source", ""),
            ))
        else:
            out.append(Finding(
                check_id="phys_range", unit_id=ctx.unit_id,
                severity="medium" if frac < 0.05 else "low", roles=[role],
                summary=(f"Role {role!r} is outside its expected band [{nlo}, {nhi}] "
                         f"on {frac:.1%} of samples."),
                statistic=stat | {"band_type": "descriptive"}, window=window,
                interpretation=("A small excursion fraction is a process event to explain rather than "
                                "a band problem. Check what the unit was doing over these samples."),
                next_step="Correlate the excursions with the operations log and the card's failure modes.",
                source=spec.get("source", ""),
            ))
    return out
