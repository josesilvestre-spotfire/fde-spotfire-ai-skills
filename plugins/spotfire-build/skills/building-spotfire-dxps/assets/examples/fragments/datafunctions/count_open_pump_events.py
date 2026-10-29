"""
==============================================================================
 Count Open Pump Events  (v1.0)
 Number of events of the selected pump that have no End time yet. Feeds the
 "Open events" label of the Pump Control Panel text area
 (assets/examples/fragments/textareas.json); its "Refresh Open Events" button
 refreshes this function (refresh behaviour: manual).
 Runtime packages: numpy, pandas.
------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name               type     document property     notes
  PUMP_EVENTS        Table    (table PUMP_EVENTS)   uses Pump ID, End
  SelectedPumpId     Value    SelectedPumpId        String
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name               type     destination
  OpenEventCount     Value    document property OpenEventCount (Integer)
------------------------------------------------------------------------------
==============================================================================
"""
import numpy as np
import pandas as pd

# ============================== STAGING: INPUTS ==============================
try:
    PUMP_EVENTS
except NameError:
    PUMP_EVENTS = pd.DataFrame({
        "Event ID": ["E-1", "E-2", "E-3"],
        "Pump ID": ["P-101", "P-101", "P-102"],
        "End": [pd.Timestamp("2026-01-02 08:00"), pd.NaT, pd.NaT],
    })
try:
    SelectedPumpId
except NameError:
    SelectedPumpId = "P-101"
SelectedPumpId = "" if SelectedPumpId is None else str(SelectedPumpId)
# ============================================================================

events = PUMP_EVENTS
if "Pump ID" in events.columns and "End" in events.columns:
    is_pump = events["Pump ID"].astype(str) == SelectedPumpId
    is_open = pd.to_datetime(events["End"], errors="coerce").isna()
    open_count = int(np.count_nonzero(is_pump & is_open))
else:
    open_count = 0

# ============================== STAGING: OUTPUTS =============================
OpenEventCount = int(open_count)          # Integer property: plain int, never a numpy scalar
# ============================================================================
