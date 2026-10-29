---
type: llm
weight: 1
---

Grade the response and the file `calculate_pump_summary.py` it writes. Pass when all of these
hold; list every criterion that fails.

1. The explanation names the cause: Spotfire's Python puts the user site-packages folder ahead of
   its bundled packages, so pandas 3 now loads, and under pandas 3 the text columns (`Pump`,
   `status`) have the dtype `str`, which the SBDF writer refuses, so the output table is not
   created.
2. The fixed script converts every text output column to `object` dtype (`.astype(object)`) and
   every numeric output column through `pd.to_numeric(..., errors="coerce")` to a numeric dtype.
3. Missing values in numeric columns are `np.nan` (or `pd.NA` in a nullable dtype), not `None`.
4. The scalar output is cast to a native Python `int` (for example `int(float(x))`) on every path.
5. The file has a header docstring with two registration tables, `STAGING: INPUT PARAMETERS` and
   `STAGING: OUTPUT PARAMETERS`, one parameter per line with its type, data type and binding or
   destination.
6. A `STAGING: INPUTS` block defaults every input when it is missing (`NameError`) and when it is
   `None`, then coerces its type, so the file also runs standalone.
7. Every registered output is assigned on every code path.
8. Names follow the library naming standard: the output table is UPPER_SNAKE_CASE, a parameter
   bound to a document property has the property's exact name (PascalCase), output columns are
   Title Case with units where they have one.
9. The response tells the user how to check the fix with the skill's checker run by Spotfire's
   Python (for example `"$SPOTFIRE_PYTHON" scripts/check_sbdf_outputs.py ...`), ideally both with
   and without `-s`.
10. The script contains no `print` in the function body and no local file paths.
