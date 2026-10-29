"""
==============================================================================
 <Verb Object>                                              version 1.0.0
 <One sentence: what the function calculates and for which page or visual.>
==============================================================================

Spotfire Python data function. The same file runs unchanged in Spotfire, in
VS Code and in Jupyter: Spotfire passes every registered input as a global
variable, and the STAGING: INPUTS block below gives each input a default
when it is missing.

------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name             type    data type   binding                        default
  sourceTable      Table   all         table SOURCE_DATA, all columns  required
  SelectedAssetId  Value   String      document property SelectedAssetId  ""
  minRows          Value   Integer     constant                       10
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name             type    destination
  RESULT_TABLE     Table   new data table RESULT_TABLE (replace on refresh)
  ResultCount      Value   document property ResultCount (LongInteger)
  StatusMessage    Value   document property StatusMessage (String)
------------------------------------------------------------------------------
REGISTRATION
  Type: Python script. Refresh: automatic.
  Packages the Spotfire Python environment needs: numpy, pandas (bundled).
  Output tables: RESULT_TABLE feeds the <visual title> visual.
------------------------------------------------------------------------------
"""
import numpy as np
import pandas as pd

# ============================== STAGING: INPUTS ==============================
# Spotfire passes an input that is registered but not bound as None, so each
# default covers both a missing name and None.
try:
    sourceTable
except NameError:
    sourceTable = None
if sourceTable is None:
    rng = np.random.default_rng(42)
    sourceTable = pd.DataFrame({
        "Asset": np.repeat(["Unit A", "Unit B"], 48),
        "Value (unit)": rng.normal(100.0, 5.0, 96),
    })

try:
    SelectedAssetId
except NameError:
    SelectedAssetId = None
if SelectedAssetId is None:
    SelectedAssetId = ""
SelectedAssetId = str(SelectedAssetId)

try:
    minRows
except NameError:
    minRows = None
if minRows is None:
    minRows = 10
minRows = int(minRows)
# =============================================================================


# ================================== ENGINE ===================================
def run(table, asset_id, min_rows):
    """Pure pandas and numpy. Name the method and cite every constant."""
    data = table.copy()
    if asset_id:
        data = data[data["Asset"] == asset_id]
    summary = (data.groupby("Asset", as_index=False)
               .agg(Rows=("Value (unit)", "size"),
                    Mean=("Value (unit)", "mean")))
    summary = summary[summary["Rows"] >= min_rows]
    summary = summary.rename(columns={"Mean": "Mean Value (unit)"})
    message = "%d assets, %d rows" % (len(summary), len(data))
    return summary, message
# =============================================================================


# ============================== STAGING: OUTPUTS =============================
# Every registered output is assigned exactly once, on every code path.
RESULT_TABLE, StatusMessage = run(sourceTable, SelectedAssetId, minRows)
ResultCount = int(len(RESULT_TABLE))
StatusMessage = str(StatusMessage)

# ========================== OUTPUT DTYPE COERCION ============================
# Numeric columns get a numeric dtype, text columns object dtype. Under
# pandas 3 a text column has the dtype "str", which the SBDF writer refuses:
# the output table is then not created and no error is shown in the visual.
INT_COLS = ["Rows"]
REAL_COLS = ["Mean Value (unit)"]
TEXT_COLS = ["Asset"]
for c in INT_COLS:
    RESULT_TABLE[c] = pd.to_numeric(RESULT_TABLE[c], errors="coerce").astype("Int64")
for c in REAL_COLS:
    RESULT_TABLE[c] = pd.to_numeric(RESULT_TABLE[c], errors="coerce").astype("float64")
for c in TEXT_COLS:
    RESULT_TABLE[c] = RESULT_TABLE[c].astype(object)
# =============================================================================


if __name__ == "__main__":
    # Standalone smoke test. Spotfire never runs this block.
    assert isinstance(RESULT_TABLE, pd.DataFrame) and len(RESULT_TABLE) > 0
    for c in RESULT_TABLE.columns:
        assert str(RESULT_TABLE[c].dtype) != "str", c
    assert type(ResultCount) is int and type(StatusMessage) is str
