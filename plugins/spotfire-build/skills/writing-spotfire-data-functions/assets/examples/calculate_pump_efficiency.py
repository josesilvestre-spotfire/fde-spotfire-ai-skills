"""
==============================================================================
 Calculate Pump Efficiency                                  version 1.0.0
 Hydraulic power and efficiency of every pump reading, a summary per pump
 and the fleet KPIs shown in the KPI band of the Pump Overview page.
==============================================================================

Spotfire Python data function. The same file runs unchanged in Spotfire, in
VS Code and in Jupyter. Without inputs it generates three synthetic pumps.

Method: hydraulic (water) horsepower WHP = Q * H * SG / 3960, with Q in US
gal/min, H in ft and SG dimensionless (3960 = 33,000 ft-lbf/min per hp
divided by 8.33 lb per US gal of water). Efficiency (%) = WHP / shaft hp
* 100. Flow arrives in bbl/d: 1 bbl = 42 US gal, 1 d = 1440 min.

------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name                 type    data type   binding                                default
  readings             Table   all         table PUMP_READINGS, all columns       required
  TargetEfficiencyPct  Value   Real        document property TargetEfficiencyPct  65.0
  MinPoints            Value   Integer     document property MinPoints            24
  specificGravity      Value   Real        constant                               1.0
------------------------------------------------------------------------------
  readings columns: Asset (String), Timestamp (UTC) (DateTime),
  Flow Rate (bbl/d) (Real), Head (ft) (Real), Shaft Power (hp) (Real)
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name                     type    destination
  PUMP_EFFICIENCY          Table   new data table PUMP_EFFICIENCY (replace on refresh)
  PUMP_EFFICIENCY_SUMMARY  Table   new data table PUMP_EFFICIENCY_SUMMARY (replace on refresh)
  PumpsBelowTarget         Value   document property PumpsBelowTarget (LongInteger)
  FleetEfficiencyText      Value   document property FleetEfficiencyText (String)
  StatusMessage            Value   document property StatusMessage (String)
------------------------------------------------------------------------------
  PUMP_EFFICIENCY          -> Efficiency Trend (line chart, one line per Asset)
  PUMP_EFFICIENCY_SUMMARY  -> Pump Ranking (table, colored by Status)
  FleetEfficiencyText      -> KPI band label "Fleet efficiency (%)"
------------------------------------------------------------------------------
REGISTRATION
  Type: Python script. Refresh: automatic (it reruns when a bound property
  changes). Packages: numpy, pandas (both bundled with Spotfire).
------------------------------------------------------------------------------
"""
import numpy as np
import pandas as pd

GPM_PER_BBL_PER_DAY = 42.0 / 1440.0
WHP_DIVISOR = 3960.0


def synthetic_readings():
    """Three pumps, 72 hourly readings each. Pump C wears over time, and a
    few shaft power readings are missing, as in real historian data."""
    rng = np.random.default_rng(7)
    rows = []
    start = pd.Timestamp("2026-01-01 00:00:00")
    for asset, flow, head, eff, wear in (("Pump A", 2400.0, 820.0, 0.72, 0.0),
                                          ("Pump B", 1800.0, 760.0, 0.68, 0.0),
                                          ("Pump C", 2100.0, 790.0, 0.66, 0.0015)):
        for hour in range(72):
            q = flow * (1.0 + rng.normal(0.0, 0.02))
            h = head * (1.0 + rng.normal(0.0, 0.01))
            e = eff - wear * hour
            whp = q * GPM_PER_BBL_PER_DAY * h / WHP_DIVISOR
            shaft = whp / e if hour % 31 != 5 else np.nan
            rows.append((asset, start + pd.Timedelta(hours=hour), q, h, shaft))
    return pd.DataFrame(rows, columns=["Asset", "Timestamp (UTC)",
                                       "Flow Rate (bbl/d)", "Head (ft)",
                                       "Shaft Power (hp)"])


# ============================== STAGING: INPUTS ==============================
# Spotfire passes an input that is registered but not bound as None, so each
# default covers both a missing name and None.
try:
    readings
except NameError:
    readings = None
if readings is None:
    readings = synthetic_readings()

try:
    TargetEfficiencyPct
except NameError:
    TargetEfficiencyPct = None
if TargetEfficiencyPct is None:
    TargetEfficiencyPct = 65.0
TargetEfficiencyPct = float(TargetEfficiencyPct)

try:
    MinPoints
except NameError:
    MinPoints = None
if MinPoints is None:
    MinPoints = 24
MinPoints = int(MinPoints)

try:
    specificGravity
except NameError:
    specificGravity = None
if specificGravity is None:
    specificGravity = 1.0
specificGravity = float(specificGravity)
# =============================================================================


# ================================== ENGINE ===================================
def efficiency_rows(data, sg):
    """Row-level hydraulic power and efficiency. Rows without a positive
    shaft power get a missing efficiency (np.nan), never None."""
    out = data[["Asset", "Timestamp (UTC)", "Flow Rate (bbl/d)", "Head (ft)",
                "Shaft Power (hp)"]].copy()
    out["Timestamp (UTC)"] = pd.to_datetime(out["Timestamp (UTC)"], errors="coerce")
    for c in ("Flow Rate (bbl/d)", "Head (ft)", "Shaft Power (hp)"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    gpm = out["Flow Rate (bbl/d)"] * GPM_PER_BBL_PER_DAY
    out["Hydraulic Power (hp)"] = gpm * out["Head (ft)"] * sg / WHP_DIVISOR
    shaft = out["Shaft Power (hp)"].where(out["Shaft Power (hp)"] > 0)
    out["Efficiency (%)"] = out["Hydraulic Power (hp)"] / shaft * 100.0
    return out.sort_values(["Asset", "Timestamp (UTC)"]).reset_index(drop=True)


def pump_summary(rows, target_pct, min_points):
    """One row per pump: valid readings, mean efficiency and a status."""
    grouped = rows.groupby("Asset")
    summary = pd.DataFrame({
        "Readings": grouped["Efficiency (%)"].count(),
        "Mean Efficiency (%)": grouped["Efficiency (%)"].mean(),
        "Missing Shaft Power": grouped["Shaft Power (hp)"].apply(
            lambda s: int(s.isna().sum())),
    }).reset_index()
    status = np.where(summary["Readings"] < min_points, "Not enough data",
                      np.where(summary["Mean Efficiency (%)"] < target_pct,
                               "Below target", "On target"))
    summary["Status"] = status
    return summary


rows = efficiency_rows(readings, specificGravity)
summary = pump_summary(rows, TargetEfficiencyPct, MinPoints)
fleet = rows["Efficiency (%)"].mean()
# =============================================================================


# ============================== STAGING: OUTPUTS =============================
# Every registered output is assigned exactly once, on every code path.
PUMP_EFFICIENCY = rows
PUMP_EFFICIENCY_SUMMARY = summary
PumpsBelowTarget = int((summary["Status"] == "Below target").sum())
FleetEfficiencyText = "-" if pd.isna(fleet) else "%.1f" % float(fleet)
StatusMessage = "%d pumps, %d readings, %d below %.0f %% efficiency" % (
    len(summary), len(rows), PumpsBelowTarget, TargetEfficiencyPct)

# ========================== OUTPUT DTYPE COERCION ============================
# Numeric columns get a numeric dtype and text columns object dtype. Under
# pandas 3 a text column has the dtype "str", which the SBDF writer refuses,
# and Spotfire then does not create the output table.
for c in ("Flow Rate (bbl/d)", "Head (ft)", "Shaft Power (hp)",
          "Hydraulic Power (hp)", "Efficiency (%)"):
    PUMP_EFFICIENCY[c] = pd.to_numeric(PUMP_EFFICIENCY[c], errors="coerce").astype("float64")
PUMP_EFFICIENCY["Asset"] = PUMP_EFFICIENCY["Asset"].astype(object)

for c in ("Readings", "Missing Shaft Power"):
    PUMP_EFFICIENCY_SUMMARY[c] = pd.to_numeric(
        PUMP_EFFICIENCY_SUMMARY[c], errors="coerce").astype("Int64")
PUMP_EFFICIENCY_SUMMARY["Mean Efficiency (%)"] = pd.to_numeric(
    PUMP_EFFICIENCY_SUMMARY["Mean Efficiency (%)"], errors="coerce").astype("float64")
for c in ("Asset", "Status"):
    PUMP_EFFICIENCY_SUMMARY[c] = PUMP_EFFICIENCY_SUMMARY[c].astype(object)

PumpsBelowTarget = int(PumpsBelowTarget)
FleetEfficiencyText = str(FleetEfficiencyText)
StatusMessage = str(StatusMessage)
# =============================================================================


if __name__ == "__main__":
    # Standalone smoke test. Spotfire never runs this block.
    assert len(PUMP_EFFICIENCY) == 216, len(PUMP_EFFICIENCY)
    assert list(PUMP_EFFICIENCY_SUMMARY["Asset"]) == ["Pump A", "Pump B", "Pump C"]
    for table in (PUMP_EFFICIENCY, PUMP_EFFICIENCY_SUMMARY):
        for c in table.columns:
            assert str(table[c].dtype) != "str", c
    assert type(PumpsBelowTarget) is int and PumpsBelowTarget == 1
    assert type(FleetEfficiencyText) is str and type(StatusMessage) is str
    assert PUMP_EFFICIENCY["Efficiency (%)"].isna().sum() == 9
    print(StatusMessage)
    print(PUMP_EFFICIENCY_SUMMARY.to_string(index=False))
