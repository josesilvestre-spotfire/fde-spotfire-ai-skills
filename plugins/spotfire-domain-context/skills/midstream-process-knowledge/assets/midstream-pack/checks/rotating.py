"""Rotating equipment checks contributed by the midstream-process pack.

These encode physics the engine has no business knowing. The general library can tell you
a series is trending; only a pump curve tells you that trending head without holding flow
constant measures the throughput schedule rather than the pump.

Loaded by `tssme.packs.load_pack_checks()` via the `check_modules` entry in `pack.yaml`,
and registered into the same registry as the general checks, so `requires` gating, regime
conditioning and report routing all work identically. Needs the tssme engine from the
analyzing-process-time-series skill on the Python path; scipy is optional.
"""

from __future__ import annotations

import pandas as pd

from tssme.checks import check
from tssme.findings import Finding
from tssme.prep import Context
from tssme.robust import theil_sen


@check("sme_head_deficit_at_matched_flow", "sme", requires=("pump_head", "flow"),
       description="Pump head degradation measured within flow bands, never across them")
def sme_head_deficit_at_matched_flow(ctx: Context) -> list[Finding]:
    """Head must be compared at matched flow.

    A centrifugal pump's head falls with flow by design, so raw head trended against time
    mostly measures how throughput changed. Binning by flow first is what turns it into a
    measurement of the pump.
    """
    idx = ctx.X.index
    if not isinstance(idx, pd.DatetimeIndex):
        return []
    days = pd.Series((idx - idx.min()).total_seconds() / 86400.0, index=idx)

    band = ctx.regime
    if band is None:
        return []

    d = pd.DataFrame({"head": ctx.X["pump_head"], "days": days, "band": band}).dropna()
    if len(d) < 40:
        return []

    rows = []
    for key, grp in d.groupby("band"):
        if len(grp) < 15:
            continue
        span = float(grp["days"].max() - grp["days"].min())
        if span < 45:
            continue
        slope, _, lo, hi = theil_sen(grp["head"].to_numpy(), grp["days"].to_numpy(), 0.95)
        mean_head = float(grp["head"].mean())
        if mean_head <= 0:
            continue
        rows.append({"band": str(key), "n": len(grp), "span_days": span,
                     "pct_per_year": 100.0 * slope * 365.0 / mean_head,
                     "significant": (lo > 0) or (hi < 0),
                     "mean_head_ft": mean_head})
    if len(rows) < 3:
        return []

    r = pd.DataFrame(rows)
    weights = r["n"] / r["n"].sum()
    wavg = float((r["pct_per_year"] * weights).sum())
    n_down = int((r["pct_per_year"] < 0).sum())
    n_sig_down = int(((r["pct_per_year"] < 0) & r["significant"]).sum())
    agreement = n_down / len(r)

    base_stat = {"weighted_pct_per_year": round(wavg, 3), "bands_analysed": len(r),
                 "bands_declining": n_down, "bands_significant_decline": n_sig_down,
                 "band_agreement": round(agreement, 2),
                 "per_band": r.round(3).to_dict("records")}

    if abs(wavg) < 1.0:
        return [Finding(
            check_id="sme_head_deficit_at_matched_flow", unit_id=ctx.unit_id, severity="info",
            roles=["pump_head", "flow"],
            summary=(f"No head degradation at matched flow "
                     f"({wavg:+.2f}%/yr across {len(r)} flow bands)."),
            statistic=base_stat,
            interpretation="Head at matched flow is stable, so the unit's hydraulic performance "
                           "is not degrading over this record. Any change in discharge pressure is "
                           "therefore driven by throughput or by the line, not by the pump.",
            kind="verified", confidence="confirmed",
            source="Head measured at matched flow per the pump H-Q curve (Karassik, Pump Handbook 4ed, Ch.2)",
        )]

    if agreement < 0.6 and (1.0 - agreement) < 0.6:
        # Bands disagree on the sign: neither wear nor a clean instrument story.
        return [Finding(
            check_id="sme_head_deficit_at_matched_flow", unit_id=ctx.unit_id, severity="medium",
            roles=["pump_head", "flow"],
            summary=(f"Head trend at matched flow is inconsistent across flow bands "
                     f"({n_down} of {len(r)} declining, weighted {wavg:+.2f}%/yr)."),
            statistic=base_stat,
            interpretation="A real degradation shows up in most flow bands with the same sign. When "
                           "bands disagree, the per-band trends are being driven by which part of the "
                           "record each band happens to cover rather than by the pump. The weighted "
                           "average is not interpretable as wear.",
            next_step="Check whether flow bands are confounded with season or with distinct operating "
                      "campaigns before trending head at all.",
            confidence="unconfirmed",
            source="Head measured at matched flow per the pump H-Q curve (Karassik, Pump Handbook 4ed, Ch.2)",
        )]

    sev = "high" if abs(wavg) >= 3.0 and max(agreement, 1.0 - agreement) >= 0.75 else "medium"
    direction = "declining" if wavg < 0 else "rising"
    return [Finding(
        check_id="sme_head_deficit_at_matched_flow", unit_id=ctx.unit_id, severity=sev,
        roles=["pump_head", "flow"],
        window=(str(d.index.min()), str(d.index.max())),
        summary=(f"Pump head at matched flow is {direction} at {wavg:+.2f}%/yr, consistent across "
                 f"{n_down} of {len(r)} flow bands."),
        statistic=base_stat,
        interpretation=("Because head is compared only within flow bands, this is not an artifact of "
                        "changing throughput. A sustained decline at matched flow is the classic "
                        "signature of impeller or wear-ring degradation. A rise at matched flow is "
                        "not a physical improvement and points to transmitter drift or an SG error "
                        "in the head conversion."),
        next_step=("Trend motor amps at matched flow to separate hydraulic wear from instrument "
                   "drift, then confirm with a vibration survey and wear-ring clearance at the next "
                   "overhaul."),
        confidence="corroborated",
        source="Centrifugal wear degradation (Karassik, Pump Handbook 4ed, Ch.2 and Ch.12); "
               + "Theil-Sen robust slope (Sen, JASA 1968)",
    )]
