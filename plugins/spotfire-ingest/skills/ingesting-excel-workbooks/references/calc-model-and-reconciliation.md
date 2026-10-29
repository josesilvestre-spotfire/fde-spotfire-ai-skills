# Calculation model and reconciliation

## The model

`calc_model_scaffold.py` writes `ingest/calc_model.py` with:

- `INPUTS`: every input, parameter and override cell with its stored value, keyed by the cell
  (`"Inputs!B3"`). Values typed over formulas are inputs too, so the model can reproduce them.
- `TABLES`: raw data and lookup ranges, written as CSV next to the model.
- `OUTPUTS`: the outputs to reconcile.
- `run(inputs=None, tables=None)`: returns `{output name: value}`; a vector output is a dict
  `{key: value}` (segment, month, well) or a list (positions 1, 2, ...).
- One commented section per workbook block, in calculation order, with the Excel formula, its
  R1C1 form, the blocks it reads, its exceptions and whether it is part of a circular group.
- The data function interface, filled in at stage 6: `PARAMETERS`, `TABLE_PARAMETERS`,
  `SPOTFIRE_OUTPUTS` and `spotfire_outputs(result)`.

Rules:

- Port from the Logic Spec, block by block. Keep the workbook's order of operations; it keeps
  the floating-point results within tolerance.
- Reproduce first. Typed values, odd cells, unit mistakes and hidden errors stay as they are,
  each with a comment that names the issue or change ID. A fix goes in only after the owner
  approves it in the change list; then reconcile again and add the accepted difference to the
  explanations file.
- Use `excel_compat.py` wherever Excel and Python differ (rounding, dates, empty cells,
  lookups, errors, powers). Use the standard library, numpy and pandas only: the model becomes
  the data function, and Spotfire's Python (checked on Analyst 15.0) ships numpy, pandas and the
  spotfire package.
- Name the columns of `data/*.csv` with the names the DXP tables will have (Title Case with
  units, naming standard), and use the same names in the model, so the exported data function
  reads Spotfire's tables unchanged.
- A circular group becomes a loop that stops when the change is below the Logic Spec tolerance;
  the reconciliation tolerance of those outputs is at least the workbook's `iterateDelta`.

## Test cases

1. **Stored values.** `reconcile.py extract` reads Excel's stored results for every output in
   `output-map.json`.
2. **Extra input sets.** Choose cases so every branch (`IF`), every lookup band and every
   boundary (zero length, empty input, maximum) is exercised. Write `cases.csv` (a `case`
   column, then one column per input cell), run `excel_cases.py make`, ask the owner to open each
   copy in Excel, let it recalculate and save it, then run `excel_cases.py extract`. The model
   runs the same cases with `python calc_model.py --cases cases.csv`.

## output-map.json

```json
{"workbook": "pipe_pressure_drop.xlsx",
 "outputs": [
  {"name": "Outlet Pressure (psi)", "id": "L08", "range": "Calc!J5:J24", "key": "Calc!A5:A24",
   "column": "Outlet Pressure (psi)", "abs": 1e-6, "rel": 1e-9},
  {"name": "Total Pressure Drop (psi)", "id": "L10", "range": "Summary!B4"}]}
```

`name` is the output name the model returns; `id` the Logic Spec entry; `range` the workbook
cells; `key` the cells that identify the rows of a vector output; `column` the column name in a
DXP export when it differs from `name`; `abs` and `rel` an override of the tolerance.

## Tolerances

State them in the Logic Spec's Conventions line, so the model check and the DXP check use the
same numbers:

```
- Rounding and tolerance for reconciliation: default abs=1e-6 rel=1e-9; L05 abs=0.001 rel=0
```

A value passes when `|actual - expected| <= abs + rel * |expected|`. An Excel error value
matches an empty value or the same error. Without a stated tolerance the script uses
`abs=1e-9 rel=1e-9`.

## Explanations

A difference the owner accepts (an approved fix, an approximate lookup that cannot be
reproduced) goes into `ingest/explanations.csv`:

```
output,index,explanation
Friction Loss (psi),10,C4 approved: formula restored for segment 10
Outlet Pressure (psi),*,C3 approved: elevation loss converted to psi
```

It is reported as EXPLAINED, and the report passes when every other value matches.

## Checkpoint 2

Every output matches or is explained in `ingest/reconciliation-model.md` for the stored values
and every extra case. Show the report to the owner.

## Stage 7 (run by building-spotfire-dxps)

The build skill builds the DXP from `spec.json`, runs it with the stored inputs (and each case),
exports each output table to CSV and runs the same comparison:

```bash
python ingest/reconcile.py compare --expected ingest/expected.csv \
    --actual <export>/SEGMENT_RESULTS.csv --key "Segment" --map ingest/output-map.json \
    --logic-spec logic-spec.md --out ingest/reconciliation-dxp
```

Stage 6 copies `reconcile.py` into the app's `ingest/` folder, so the build step runs the same
script without knowing where this skill is installed. `compare` needs only the standard
library. Value outputs (document properties) are exported as a one-row CSV with one column per
property, or written by the build skill as a long CSV (case, output, index, value).
