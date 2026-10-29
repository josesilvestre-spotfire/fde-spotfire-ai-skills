"""
==============================================================================
 Calculate Pump Curves  (v1.0)
 Fits a head-capacity curve per pump from the PUMP_DATA rows that pass the
 Fleet Filters scheme, for the pump-curve views of the example app
 (assets/examples/fragments/datafunctions.json). Reports the fit quality of the
 selected pump in the OutCurveR2 document property.
   Head (ft) = (discharge - suction pressure, psi) x 2.31 / specific gravity
               (2.31 ft of water per psi; SG of the pumped liquid).
   Curve:      H(Q) = a + b*Q + c*Q^2, ordinary least squares per pump
               (the usual quadratic head-capacity form of a centrifugal pump;
               fitMethod "linear" drops the Q^2 term).
 Runtime packages: numpy, pandas (both bundled with Spotfire's Python).
------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name             type     document property     notes
  PUMP_DATA        Table    (table PUMP_DATA)     all columns; limited by filtering scheme "Fleet Filters"
  flowRate         Column   (PUMP_DATA column)    Real; [PUMP_DATA].[Flow Rate (bbl/d)], every row (fleet reference)
  SelectedPumpId   Value    SelectedPumpId        String
  minPoints        Value    (constant 20)         Integer; fewer rows per pump = no curve
  specificGravity  Value    (constant 0.85)       Real
  fitMethod        Value    (constant "quadratic") String; quadratic or linear
  excludeTripped   Value    (constant True)       Boolean; drop rows with Status "Tripped"
  maxFlow          Value    (expression)          Real; Max([PUMP_DATA].[Flow Rate (bbl/d)])
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name             type     destination
  PUMP_CURVES      Table    new data table "PUMP_CURVES" (replace on refresh)
  OutCurveR2       Value    document property OutCurveR2 (Real)
------------------------------------------------------------------------------
 PUMP_CURVES - one row per pump: curve coefficients and fit quality
               (pump curve table, curve overlays as fitting-model curves)
 Refresh: automatic (registered and run once at build by the DXP builder).
==============================================================================
"""
import numpy as np
import pandas as pd

PSI_TO_FT_WATER = 2.31


def _sample_pump_data():
    """Synthetic stand-in for PUMP_DATA so this file also runs outside Spotfire."""
    rng = np.random.default_rng(42)
    frames = []
    for pump_id, station, shutoff_ft, k in (("P-101", "Station A", 1450.0, 2.0e-7),
                                            ("P-102", "Station A", 1380.0, 2.4e-7),
                                            ("P-201", "Station B", 1520.0, 1.8e-7)):
        n = 96
        flow = rng.uniform(20000.0, 60000.0, n)
        head = shutoff_ft - k * flow ** 2 + rng.normal(0.0, 15.0, n)
        suction = rng.uniform(40.0, 60.0, n)
        frames.append(pd.DataFrame({
            "Timestamp": pd.date_range("2026-01-01", periods=n, freq="h"),
            "Station": station,
            "Pump ID": pump_id,
            "Flow Rate (bbl/d)": flow,
            "Discharge Pressure (psig)": suction + head * 0.85 / PSI_TO_FT_WATER,
            "Suction Pressure (psig)": suction,
            "Motor Current (A)": 60.0 + flow / 600.0 + rng.normal(0.0, 2.0, n),
            "Status": np.where(rng.random(n) < 0.03, "Tripped", "Running"),
        }))
    return pd.concat(frames, ignore_index=True)


# ============================== STAGING: INPUTS ==============================
try:
    PUMP_DATA
except NameError:
    PUMP_DATA = _sample_pump_data()
try:
    flowRate
except NameError:
    flowRate = PUMP_DATA["Flow Rate (bbl/d)"]
try:
    SelectedPumpId
except NameError:
    SelectedPumpId = "P-101"
try:
    minPoints
except NameError:
    minPoints = 20
try:
    specificGravity
except NameError:
    specificGravity = 0.85
try:
    fitMethod
except NameError:
    fitMethod = "quadratic"
try:
    excludeTripped
except NameError:
    excludeTripped = True
try:
    maxFlow
except NameError:
    maxFlow = float(pd.to_numeric(PUMP_DATA["Flow Rate (bbl/d)"], errors="coerce").max())
SelectedPumpId = "" if SelectedPumpId is None else str(SelectedPumpId)
minPoints = 20 if minPoints is None else int(minPoints)
specificGravity = 1.0 if specificGravity is None or float(specificGravity) <= 0.0 else float(specificGravity)
fitMethod = "quadratic" if fitMethod is None else str(fitMethod).strip().lower()
excludeTripped = bool(excludeTripped)
maxFlow = float("nan") if maxFlow is None else float(maxFlow)
# ============================================================================

DEGREE = 1 if fitMethod == "linear" else 2
CURVE_COLUMNS = ["Pump ID", "Points", "Shutoff Head (ft)", "Linear Term (ft per bbl/d)",
                 "Quadratic Term (ft per bbl/d squared)", "R Squared", "Max Observed Flow (bbl/d)",
                 "Head at Fleet Max Flow (ft)", "Fleet Median Flow (bbl/d)"]
INT_COLS = ["Points"]
REAL_COLS = [c for c in CURVE_COLUMNS if c not in INT_COLS and c != "Pump ID"]

rows = PUMP_DATA
if excludeTripped and "Status" in rows.columns:
    rows = rows[rows["Status"].astype(str) != "Tripped"]
work = pd.DataFrame({
    "Pump ID": rows["Pump ID"].astype(str),
    "Q": pd.to_numeric(rows["Flow Rate (bbl/d)"], errors="coerce"),
    "H": (pd.to_numeric(rows["Discharge Pressure (psig)"], errors="coerce")
          - pd.to_numeric(rows["Suction Pressure (psig)"], errors="coerce"))
         * PSI_TO_FT_WATER / specificGravity,
}).dropna()

fleet_flow = pd.to_numeric(pd.Series(flowRate), errors="coerce").dropna()
fleet_median_flow = float(fleet_flow.median()) if len(fleet_flow) else np.nan

records = []
for pump_id, g in work.groupby("Pump ID", sort=True):
    if len(g) < max(minPoints, DEGREE + 1):
        continue
    q = g["Q"].to_numpy(dtype=float)
    h = g["H"].to_numpy(dtype=float)
    coeffs = np.polyfit(q, h, DEGREE)                  # highest power first
    fitted = np.polyval(coeffs, q)
    ss_res = float(np.sum((h - fitted) ** 2))
    ss_tot = float(np.sum((h - h.mean()) ** 2))
    q_eval = maxFlow if np.isfinite(maxFlow) else float(q.max())
    records.append({
        "Pump ID": str(pump_id),
        "Points": len(g),
        "Shutoff Head (ft)": float(coeffs[-1]),
        "Linear Term (ft per bbl/d)": float(coeffs[-2]),
        "Quadratic Term (ft per bbl/d squared)": float(coeffs[0]) if DEGREE == 2 else 0.0,
        "R Squared": 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0,
        "Max Observed Flow (bbl/d)": float(q.max()),
        "Head at Fleet Max Flow (ft)": float(np.polyval(coeffs, q_eval)),
        "Fleet Median Flow (bbl/d)": fleet_median_flow,
    })

# ============================== STAGING: OUTPUTS =============================
PUMP_CURVES = pd.DataFrame(records, columns=CURVE_COLUMNS)
selected = PUMP_CURVES.loc[PUMP_CURVES["Pump ID"] == SelectedPumpId, "R Squared"]
OutCurveR2 = float(selected.iloc[0]) if len(selected) else 0.0
if not np.isfinite(OutCurveR2):
    OutCurveR2 = 0.0          # a scalar output must never be None/NaN (no type to export)

# ===================== OUTPUT DTYPE COERCION =====================
for c in INT_COLS:
    PUMP_CURVES[c] = pd.to_numeric(PUMP_CURVES[c], errors="coerce").fillna(0).astype("int64")
for c in REAL_COLS:
    PUMP_CURVES[c] = pd.to_numeric(PUMP_CURVES[c], errors="coerce").astype("float64")
PUMP_CURVES["Pump ID"] = PUMP_CURVES["Pump ID"].astype(str)
# =================================================================

if __name__ == "__main__":
    assert list(PUMP_CURVES.columns) == CURVE_COLUMNS
    assert str(PUMP_CURVES["Points"].dtype) == "int64"
    assert all(str(PUMP_CURVES[c].dtype) == "float64" for c in REAL_COLS)
    assert isinstance(OutCurveR2, float) and 0.0 <= OutCurveR2 <= 1.0
