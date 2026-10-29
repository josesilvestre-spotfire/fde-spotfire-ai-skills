"""
==============================================================================
 Score Pump Health  (v1.0)
 Ranks the pumps by a 0-100 health score for the example app
 (assets/examples/fragments/datafunctions.json). Reads the PUMP_CURVES table written
 by Calculate Pump Curves (the DXP builder therefore runs that function
 first), PUMP_DATA rows limited by the active filtering scheme and by the
 Fleet Filters scheme, and the MotorCurrentLimit document property.
   Curve penalty = 40 x (1 - R squared) of the pump's head-capacity fit
                   (a poorer fit means the curve is drifting: wear, recirculation)
   Load penalty  = 40 x clip((P95 motor current / limit - 0.8) / 0.4, 0, 1)
                   (none below 80 % of the current limit, full at 120 %)
   Trip penalty  = 20 x clip(tripped share of samples / 0.10, 0, 1)
   Health Score  = 100 - the three penalties (higher is healthier)
 Runtime packages: numpy, pandas (both bundled with Spotfire's Python).
------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name               type     document property     notes
  PUMP_CURVES        Table    (table PUMP_CURVES)   all columns; output of Calculate Pump Curves
  operatingData      Table    (PUMP_DATA columns)   Pump ID, Motor Current (A), Status; limited by the active filtering scheme
  fleetCurrent       Column   (PUMP_DATA column)    Real; [PUMP_DATA].[Motor Current (A)] limited by filtering scheme "Fleet Filters"
  MotorCurrentLimit  Value    MotorCurrentLimit     Real (A)
  fleetAvgCurrent    Value    (expression)          Real; Avg([PUMP_DATA].[Motor Current (A)]) limited by the active filtering scheme
  reviewWindow       Value    (constant 7 days)     TimeSpan; Next Review = asOfDate + reviewWindow
  asOfDate           Value    (constant 2026-06-30) Date
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name               type     destination
  PUMP_HEALTH        Table    new data table "PUMP_HEALTH" (replace on refresh)
  OutWorstPumpId     Value    document property OutWorstPumpId (String)
------------------------------------------------------------------------------
 PUMP_HEALTH - one row per pump with a fitted curve: rank (1 = least healthy),
               score and its drivers (pump health ranking table / bar chart)
 Refresh: automatic (registered and run once at build by the DXP builder).
==============================================================================
"""
import datetime

import numpy as np
import pandas as pd

HEALTH_COLUMNS = ["Pump ID", "Rank", "Health Score", "Curve R Squared", "P95 Motor Current (A)",
                  "Load Ratio", "Relative Load", "Trip Share (%)", "Samples",
                  "Fleet P95 Current (A)", "Next Review"]
INT_COLS = ["Rank", "Samples"]
REAL_COLS = ["Health Score", "Curve R Squared", "P95 Motor Current (A)", "Load Ratio",
             "Relative Load", "Trip Share (%)", "Fleet P95 Current (A)"]


def _sample_curves():
    """Synthetic stand-in for PUMP_CURVES so this file also runs outside Spotfire."""
    return pd.DataFrame({"Pump ID": ["P-101", "P-102", "P-201"],
                         "R Squared": [0.97, 0.88, 0.93]})


def _sample_operating_data():
    """Synthetic stand-in for the PUMP_DATA columns of operatingData."""
    rng = np.random.default_rng(7)
    n = 120
    return pd.DataFrame({
        "Pump ID": np.repeat(["P-101", "P-102", "P-201"], n),
        "Motor Current (A)": np.concatenate([rng.normal(95.0, 6.0, n), rng.normal(112.0, 8.0, n),
                                             rng.normal(101.0, 5.0, n)]),
        "Status": np.where(rng.random(3 * n) < 0.04, "Tripped", "Running"),
    })


# ============================== STAGING: INPUTS ==============================
try:
    PUMP_CURVES
except NameError:
    PUMP_CURVES = _sample_curves()
try:
    operatingData
except NameError:
    operatingData = _sample_operating_data()
try:
    fleetCurrent
except NameError:
    fleetCurrent = operatingData["Motor Current (A)"]
try:
    MotorCurrentLimit
except NameError:
    MotorCurrentLimit = 120.0
try:
    fleetAvgCurrent
except NameError:
    fleetAvgCurrent = float(pd.to_numeric(operatingData["Motor Current (A)"], errors="coerce").mean())
try:
    reviewWindow
except NameError:
    reviewWindow = datetime.timedelta(days=7)
try:
    asOfDate
except NameError:
    asOfDate = datetime.date(2026, 6, 30)
MotorCurrentLimit = (120.0 if MotorCurrentLimit is None or float(MotorCurrentLimit) <= 0.0
                     else float(MotorCurrentLimit))
fleetAvgCurrent = float("nan") if fleetAvgCurrent is None else float(fleetAvgCurrent)
reviewWindow = pd.Timedelta(days=7) if reviewWindow is None else pd.Timedelta(reviewWindow)
asOfDate = pd.Timestamp(2026, 6, 30) if asOfDate is None else pd.Timestamp(asOfDate)
# ============================================================================

ops = pd.DataFrame({
    "Pump ID": operatingData["Pump ID"].astype(str),
    "Current": pd.to_numeric(operatingData["Motor Current (A)"], errors="coerce"),
    "Tripped": operatingData["Status"].astype(str) == "Tripped",
})
fleet = pd.to_numeric(pd.Series(fleetCurrent), errors="coerce").dropna()
fleet_p95 = float(fleet.quantile(0.95)) if len(fleet) else np.nan
if not np.isfinite(fleetAvgCurrent) or fleetAvgCurrent <= 0.0:
    fleetAvgCurrent = float(ops["Current"].mean()) if ops["Current"].notna().any() else np.nan
next_review = asOfDate + reviewWindow

r2_by_pump = {}
if "Pump ID" in PUMP_CURVES.columns and "R Squared" in PUMP_CURVES.columns:
    for pump_id, r2 in zip(PUMP_CURVES["Pump ID"].astype(str),
                           pd.to_numeric(PUMP_CURVES["R Squared"], errors="coerce")):
        r2_by_pump[pump_id] = r2

records = []
for pump_id, g in ops.groupby("Pump ID", sort=True):
    if pump_id not in r2_by_pump:
        continue                                       # only pumps with a fitted curve
    current = g["Current"].dropna()
    if len(current) == 0:
        continue
    r2 = float(r2_by_pump[pump_id])
    r2 = min(max(r2, 0.0), 1.0) if np.isfinite(r2) else 0.0
    p95 = float(current.quantile(0.95))
    load_ratio = p95 / MotorCurrentLimit
    trip_share = float(g["Tripped"].mean())
    curve_penalty = 40.0 * (1.0 - r2)
    load_penalty = 40.0 * min(max((load_ratio - 0.8) / 0.4, 0.0), 1.0)
    trip_penalty = 20.0 * min(max(trip_share / 0.10, 0.0), 1.0)
    records.append({
        "Pump ID": str(pump_id),
        "Rank": 0,
        "Health Score": 100.0 - curve_penalty - load_penalty - trip_penalty,
        "Curve R Squared": r2,
        "P95 Motor Current (A)": p95,
        "Load Ratio": load_ratio,
        "Relative Load": (float(current.mean()) / fleetAvgCurrent
                          if np.isfinite(fleetAvgCurrent) and fleetAvgCurrent > 0.0 else np.nan),
        "Trip Share (%)": 100.0 * trip_share,
        "Samples": len(g),
        "Fleet P95 Current (A)": fleet_p95,
        "Next Review": next_review,
    })

# ============================== STAGING: OUTPUTS =============================
PUMP_HEALTH = pd.DataFrame(records, columns=HEALTH_COLUMNS)
PUMP_HEALTH = PUMP_HEALTH.sort_values(["Health Score", "Pump ID"]).reset_index(drop=True)
PUMP_HEALTH["Rank"] = np.arange(1, len(PUMP_HEALTH) + 1)            # 1 = least healthy
OutWorstPumpId = str(PUMP_HEALTH["Pump ID"].iloc[0]) if len(PUMP_HEALTH) else ""

# ===================== OUTPUT DTYPE COERCION =====================
for c in INT_COLS:
    PUMP_HEALTH[c] = pd.to_numeric(PUMP_HEALTH[c], errors="coerce").fillna(0).astype("int64")
for c in REAL_COLS:
    PUMP_HEALTH[c] = pd.to_numeric(PUMP_HEALTH[c], errors="coerce").astype("float64")
PUMP_HEALTH["Pump ID"] = PUMP_HEALTH["Pump ID"].astype(str)
PUMP_HEALTH["Next Review"] = pd.to_datetime(PUMP_HEALTH["Next Review"])
# =================================================================

if __name__ == "__main__":
    assert list(PUMP_HEALTH.columns) == HEALTH_COLUMNS
    assert all(str(PUMP_HEALTH[c].dtype) == "int64" for c in INT_COLS)
    assert all(str(PUMP_HEALTH[c].dtype) == "float64" for c in REAL_COLS)
    assert str(PUMP_HEALTH["Next Review"].dtype).startswith("datetime64")
    assert len(PUMP_HEALTH) == 3 and list(PUMP_HEALTH["Rank"]) == [1, 2, 3]
    assert isinstance(OutWorstPumpId, str) and OutWorstPumpId == PUMP_HEALTH["Pump ID"].iloc[0]
