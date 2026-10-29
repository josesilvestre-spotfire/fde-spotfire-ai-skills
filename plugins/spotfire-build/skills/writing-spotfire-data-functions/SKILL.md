---
name: writing-spotfire-data-functions
description: Writes and reviews Python data functions for Spotfire Analyst. Covers the staging blocks that let one file run standalone and inside Spotfire, registration tables for the data function dialog, SBDF-safe output types (including text columns under pandas 3), shared outputs across sibling functions, customer staging functions and run chains, and ships a checker that runs a function and exports its outputs with Spotfire's own SBDF writer. Use when writing, fixing or reviewing any Python script that runs as a Spotfire data function, or when a data function output table is missing or has the wrong column types.
compatibility: Spotfire Analyst 15.0 with its bundled Python 3.14 (spotfire package 2.4.2). The checker needs Python 3.10+ with numpy and pandas.
metadata:
  maturity: Proven on one machine
  spotfire: "15.0"
---

# Writing Spotfire data functions

A Spotfire Python data function is a script that Spotfire runs in its own Python interpreter.
Spotfire passes each registered input as a global variable, runs the script, then writes each
registered output back with its SBDF writer. Most failures come from three places: an input that
is missing when the script runs on its own, an output that is not assigned on some path, and an
output whose type the SBDF writer refuses. The file layout below removes all three.

## Workflow

1. Read the App Brief and Logic Spec when the app folder has them
   (`$DXP_WORKSPACE/apps/<AppSlug>/`). The function implements the Logic Spec IDs it names. Do not
   change either document without telling the user.
2. Copy [assets/data-function-template.py](assets/data-function-template.py) to
   `datafunctions/<verb_object>.py` and fill it in. A complete example is
   [assets/examples/calculate_pump_efficiency.py](assets/examples/calculate_pump_efficiency.py).
3. Name everything by [references/naming-standard.md](references/naming-standard.md).
4. Run the file standalone, then run the checker with Spotfire's Python:
   `"$SPOTFIRE_PYTHON" scripts/check_sbdf_outputs.py datafunctions/<file>.py`.
5. Register it (by hand or through the API, see
   [references/registration-and-run-chains.md](references/registration-and-run-chains.md)), add it
   to the run chain and to the setup guide.

If `SPOTFIRE_PYTHON` is not set, ask the user for the `python.exe` Spotfire uses (under
`%LOCALAPPDATA%\Spotfire\<version>\Modules\Python Interpreter_<n>\python\` for a default Analyst
install), or run the checker with any Python that has pandas for the static checks only.

## File anatomy

Every data function file has these parts, in this order.

1. **Header docstring**: a banner with the Title Case name, version and purpose; the method and its
   constants; two registration tables; the visual each output table feeds; the registration
   type, refresh mode and every package the function needs.
2. **`STAGING: INPUTS`**: every input defaulted, then coerced to its type. The defaults make the
   file run unchanged in VS Code, Jupyter and Spotfire.
3. **Engine**: pure pandas and numpy, no Spotfire calls.
4. **`STAGING: OUTPUTS`**: every registered output assigned exactly once, on every path.
5. **`OUTPUT DTYPE COERCION`**: every output column forced to an SBDF-safe dtype.
6. **Smoke test** under `if __name__ == "__main__":`. Spotfire runs the script with `exec()` and
   globals that do not set `__name__`, so this block runs only standalone.

### Registration tables

The user registers parameters by hand from these tables, so every parameter has its own line with
name, type, data type, binding or destination and default. No shorthand such as `out* (12)` and
no "same as above".

```
------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name                 type    data type   binding                                default
  readings             Table   all         table PUMP_READINGS, all columns       required
  TargetEfficiencyPct  Value   Real        document property TargetEfficiencyPct  65.0
  specificGravity      Value   Real        constant                               1.0
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name                 type    destination
  PUMP_EFFICIENCY      Table   new data table PUMP_EFFICIENCY (replace on refresh)
  PumpsBelowTarget     Value   document property PumpsBelowTarget (LongInteger)
------------------------------------------------------------------------------
```

The checker reads output names from the `STAGING: OUTPUT PARAMETERS` table, so keep its shape:
a dashed line, a `name` header line, one line per parameter, a closing dashed line.

### Input staging

Spotfire 15.0 passes a registered input that is not bound as `None`, so default on both a missing
name and `None`:

```python
try:
    MinPoints
except NameError:
    MinPoints = None
if MinPoints is None:
    MinPoints = 24
MinPoints = int(MinPoints)
```

A Table input without a binding gets synthetic or sample data, so the standalone run exercises the
engine.

## Naming

The naming standard applies to every name in the file:

- A parameter bound to a document property has exactly the property's name, which is PascalCase
  (`TargetEfficiencyPct`). Other parameters are camelCase (`specificGravity`).
- Output tables are UPPER_SNAKE_CASE (`PUMP_EFFICIENCY`). Columns are Title Case with the unit in
  parentheses (`Flow Rate (bbl/d)`); the primary time column is `Timestamp (UTC)`.
- The data function itself is Title Case verb + object (`Calculate Pump Efficiency`). The file is
  the snake_case form (`calculate_pump_efficiency.py`).
- Result properties are named for what they hold (`PumpsBelowTarget`, `FleetEfficiencyText`), with
  no `out` or type prefix.

A one-character mismatch between a property, a parameter and a control raises no error: the
control does nothing or the KPI goes stale.

## Output types (Spotfire 15.0, spotfire 2.4.2)

Run under pandas 2.3.3 and 3.0.5 with Spotfire's SBDF writer. Details and the writer's messages
are in [references/sbdf-types.md](references/sbdf-types.md).

| Rule | Why |
|---|---|
| Text columns end as `object`: `df[c] = df[c].astype(object)` | under pandas 3 text columns have the dtype `str`, which the writer refuses, and the output table is not created |
| Numeric columns go through `pd.to_numeric(col, errors="coerce")` and get `float64`, `int64` or `Int64` | under pandas 3 an `object` column of numbers is refused |
| Missing numbers are `np.nan` or `pd.NA`, never `None` | `None` makes an `object` column |
| Integer columns with gaps use nullable `Int64` | it exports as LongInteger with `pd.NA` missing; `fillna(0)` invents zeros |
| An all-empty text column is `pd.StringDtype("python")` | an all-missing `object` column has no type |
| Scalar outputs are cast: `int(float(x))`, `float(x)`, `str(x)`, on every path | a `None` scalar fails; numpy scalars work but hide type changes |
| Integer output properties are LongInteger | a Python `int` exports as LongInteger, and a property keeps its first type |

Spotfire 15.0 bundles pandas 2.3.3, but Python puts the user site-packages folder
(`%APPDATA%\Python\Python314\site-packages`) ahead of it. On a machine where that folder holds
pandas 3, data functions run under pandas 3. Write for both.

## Shared outputs, staging functions, catalogs

- Sibling functions that share KPI properties map every shared property as both input and
  output and pass the values through when they are not the active method.
- An app that ships demo data also ships a customer staging function: required and optional
  tables, a `ColumnMapJson` property, documented defaults, and a validation table.
- An engine with many outputs documents them as a numbered catalog with row counts and target
  visuals.

Code and contracts: [references/patterns.md](references/patterns.md).

## Run chains and refresh

- One IronPython script (`Run All Data Functions`) runs the functions in dependency order with
  `ExecuteSynchronously()`; `Execute()` only queues the run until the script ends.
- Refresh automatic for functions driven by controls; manual, behind a button, for expensive runs.
- A function the user has not trusted does not run, and `ExecuteSynchronously` does nothing.

Code: [references/registration-and-run-chains.md](references/registration-and-run-chains.md).
For button and trigger scripts, use the `writing-spotfire-ironpython` skill.

## Check before you deliver

```bash
python scripts/check_sbdf_outputs.py --self-test
python datafunctions/calculate_pump_efficiency.py                  # smoke test
"$SPOTFIRE_PYTHON" scripts/check_sbdf_outputs.py datafunctions/calculate_pump_efficiency.py
"$SPOTFIRE_PYTHON" -s scripts/check_sbdf_outputs.py datafunctions/calculate_pump_efficiency.py
"$SPOTFIRE_PYTHON" scripts/check_sbdf_outputs.py datafunctions/calculate_pump_efficiency.py \
    --set MinPoints=500 --input readings=data/PUMP_READINGS.csv
```

The checker executes the file the way Spotfire does, lists each output, flags `str` dtypes,
numbers or mixed types in `object` columns, all-missing columns, `None` and unassigned outputs.
When the `spotfire` package is importable it also exports each output with Spotfire's own writer
and runs the whole function through `spotfire.data_function`, the runner Spotfire's Python
service uses, with every input you did not give arriving as `None` (as an unbound input does).
`-s` leaves out the user site-packages folder, so the second run uses the bundled pandas. Use
`--set` and `--input` to reach the other branches.

Before you hand the function over, also confirm:

- Every output is assigned on every path, pass-through branches included.
- The header lists every package the function imports, and the default path needs no network.
- The function and every parameter have a description; no credentials are constant inputs.
- No `print` in the function body (the smoke test block may print).
- The method is named and every constant is cited.
