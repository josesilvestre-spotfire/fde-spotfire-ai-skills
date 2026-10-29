# Running the engine inside a Spotfire data function

**Not yet tested** on a live Spotfire. The wrapper below was run offline against the example
with the inputs simulated as Python variables (pandas 3.0, numpy 2.5, Python 3.14). Use the
`writing-spotfire-data-functions` skill for the staging block, the registration table and
SBDF-safe output types.

## Packages

| Package | Needed for | In the Python bundled with Spotfire Analyst 15.0 |
|---|---|---|
| numpy, pandas | everything | Yes (observed: numpy 2.4, pandas 2.3) |
| pyyaml | reading cards, packs, profiles and tag maps | Not observed in the bundled set. Check with `import yaml` and install it through Spotfire's Python package management if it fails |
| scipy | nothing; optional | No (observed). `tssme.robust` uses scipy when present and an exact NumPy path otherwise; `test_engine_runs_end_to_end_without_scipy` covers this |

Two observations from Spotfire Analyst 15.0 that affect this engine:

- The bundled Python had no scipy and no torch.
- A user-level site-packages folder can load before the bundled packages (a newer numpy and
  pandas 3 from the user site were imported first). Code must run on pandas 2.x and 3.x. The
  engine's tests have been run on pandas 3.0 only; pandas 2.3 is **Not yet tested**.

## Where the engine lives

The data function imports `tssme` from a folder on disk. Pass that folder in as a string
input (for example a document property) rather than hard coding it, and pass the pack folder
the same way. A copy of the `scripts/` folder on a shared drive works for every user of the
analysis, provided their Python can read it.

## Wrapper

Inputs: `historian` (table, one DateTime column plus the sensor columns), `unitId`,
`tagmapPath`, `packPath`, `enginePath`, `calibrationPath` (strings; the last may be empty).
Outputs: `findings` (table), `reportMarkdown` and `checksSkipped` (strings).

```python
import json
import os
import sys

import numpy as np
import pandas as pd

if enginePath and enginePath not in sys.path:
    sys.path.insert(0, enginePath)          # the folder that holds the tssme package
if packPath:
    os.environ["TSSME_PACK_PATH"] = packPath

from tssme import analyse, report_md
from tssme import packs as tssme_packs

# The Python process can outlive one run, so rediscover packs and register their checks
# on every run instead of relying on what was found at first import.
tssme_packs.registry(refresh=True)
_, pack_errors = tssme_packs.load_pack_checks()

ctx, result = analyse(historian, unit=unitId, tagmap=tagmapPath,
                      calibration=calibrationPath or None)


def _ts(value):
    return pd.Timestamp(value) if value else pd.NaT


rows = result.findings
findings = pd.DataFrame({
    "Check": pd.Series([f.check_id for f in rows], dtype=object),
    "Kind": pd.Series([f.kind for f in rows], dtype=object),
    "Severity": pd.Series([f.severity for f in rows], dtype=object),
    "Confidence": pd.Series([f.confidence for f in rows], dtype=object),
    "Roles": pd.Series(["|".join(f.roles) for f in rows], dtype=object),
    "Window Start": pd.to_datetime(pd.Series(
        [_ts(f.window[0] if f.window else None) for f in rows], dtype=object)
    ).astype("datetime64[ns]"),
    "Window End": pd.to_datetime(pd.Series(
        [_ts(f.window[1] if f.window else None) for f in rows], dtype=object)
    ).astype("datetime64[ns]"),
    "Summary": pd.Series([f.summary for f in rows], dtype=object),
    "Interpretation": pd.Series([f.interpretation for f in rows], dtype=object),
    "Next Step": pd.Series([f.next_step for f in rows], dtype=object),
    "Source": pd.Series([f.source for f in rows], dtype=object),
    "Statistic": pd.Series([json.dumps(f.statistic, default=str) for f in rows],
                           dtype=object),
})
reportMarkdown = report_md(ctx, result)
checksSkipped = "; ".join(f"{k}: {v}" for k, v in result.skipped.items())
if pack_errors:
    checksSkipped += " | pack errors: " + "; ".join(
        f"{k}: {v}" for k, v in pack_errors.items())
```

Notes:

- `analyse` accepts the input table directly. It uses the tag map's `time_column` when that
  column is present, otherwise the frame's DatetimeIndex.
- `statistic` is a nested dict, so it is written as JSON text. Nested structures are not
  SBDF-safe.
- Route the findings table on `Kind`, not on `Severity`: `candidate` rows are hypotheses and
  `not_evaluated` rows are coverage gaps, whatever their severity.
- A run with high or critical findings is a normal result, not an error. Only the CLI turns
  it into a non-zero exit code.
