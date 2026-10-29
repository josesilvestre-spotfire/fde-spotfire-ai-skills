---
name: ingesting-excel-workbooks
description: Breaks down an engineering calculation workbook (.xlsx or .xlsm) without running it, documents its structure, calculations, issues and purpose, reproduces its numbers in a Python model reconciled against the workbook's values, and writes the App Brief, Logic Spec, draft build spec, change list and data function code for a Spotfire DXP. Ships the inventory, R1C1 block, dependency, issue scan, dossier, model scaffold and reconciliation scripts, with owner checkpoints after the meaning, the model and the redesign. Use it when a spreadsheet tool must become a Spotfire analysis, when a workbook needs an audit of its formulas before anyone relies on it, or when the build step needs the reconciliation script. It never builds the DXP; the building-spotfire-dxps skill reads its files.
metadata:
  maturity: New, not yet tested
---

# Ingesting Excel workbooks

Engineers keep calculations in large, loosely organised workbooks. This skill reads such a
workbook as data (macros never run, links never update), documents it for its owner, reproduces
its numbers in Python, and writes the files the build skill needs. The Python model becomes the
data function code, so the DXP ships the code that passed the comparison with Excel.

The skill covers stages 1 to 6. Stage 7 (build the DXP and check it against Excel) belongs to
the `building-spotfire-dxps` skill, which runs the reconciliation script this skill ships.

## Rules

1. **Reproduce the workbook's numbers first; fixes only after the owner approves them.** Typed
   values, odd cells, unit mistakes and hidden errors stay in the model, each with a comment
   naming its issue, until the owner approves the change in the change list.
2. Never change the workbook. Work on a copy; the scripts only read it.
3. Never start Excel without asking. The scripts read the file's XML; the optional COM paths
   (`--excel-snapshots`, `excel_cases.py recalc --engine excel`) are **Not yet tested** and start
   their own hidden instance with macros disabled and links not updated.
4. Never build a DXP, generate a builder or start Spotfire. This skill ends with files.
5. Never invent meaning. A goal, a user, a unit or a correlation comes from the workbook or the
   owner; anything else is a question in the dossier.
6. Stop at each checkpoint (after stages 4, 5 and 6) and wait for the owner's answer.
7. Every number in the App Brief and Logic Spec traces to a workbook cell or an owner answer.

## Before you start

- The workbook must be `.xlsx` or `.xlsm`. Ask the owner to save `.xls` and `.xlsb` files as
  `.xlsx` (macros disabled) first.
- The app folder is `$DXP_WORKSPACE/apps/<AppSlug>/`. When `DXP_WORKSPACE` is not set, ask the
  user where it is. Working files go in `ingest/`; the hand-off files in the app folder itself.
- Python 3.10 or later. The scripts use the standard library; pandas runs the model; openpyxl
  (cross-check) and oletools (VBA code) are optional. Check with `python -c "import pandas"`.
- Read [the scripts reference](references/scripts.md) once for the commands and outputs.

## Stage 1: inventory

```bash
python <skill>/scripts/ingest_workbook.py book.xlsx --out $DXP_WORKSPACE/apps/<AppSlug>/ingest --crosscheck
```

`ingest_workbook.py` runs stages 1 to 3 and writes a draft dossier. Read `inventory.json` first:

- `calculation.mode` manual: the stored values may be stale. Ask for a copy that was
  recalculated (F9) and saved before you reconcile anything.
- `externalLinks`, `powerQuery`, `connections`: where data comes from. Stored values are used.
- `vbaPresent`: with oletools the module code is in `ingest/vba/`; without it, ask the owner for
  the code. Macros are never run.
- `dataTables`, `solver`, `arrayFormulas`, hidden sheets: calculations Excel does outside cells.
- `crosscheck`: every sheet should match. A mismatch means the reader missed formulas; report it.
- `snapshots/*.values.csv` and `*.formulas.csv`: the sheets as grids, for reading and quoting.

## Stage 2: structure

`structure.json` lists blocks: ranges whose cells hold the same formula in R1C1 form, so a
filled-down column of 5000 cells is one block. Each block has a role:

| Role | Meaning |
|---|---|
| input | A value a user sets (on an input sheet, named, or with a drop-down) |
| parameter | Another value formulas read (coefficients, per-asset constants) |
| override | A value typed inside a formula block |
| lookup | A range read by `VLOOKUP`, `MATCH`, `INDEX` |
| raw data | A large block of values |
| calculation | A formula block other blocks read |
| output | A formula block on a summary sheet, in a chart, or a single result nothing else reads |
| terminal | A formula block nothing reads (candidate unused calculation) |
| label, unreferenced value | Text, and values no formula reads |

Also read `cycles` (circular references), `templateFamilies` (sheets copied from one template and
where the copies differ), `sheetFlow` and `dependencies.mmd` (a Mermaid diagram of the blocks).

## Stage 3: issues

`issues.json` lists each finding with a severity, a location and a question for the owner. The
types, what each means and how the model treats it are in
[the issue catalog](references/issue-catalog.md). Check the high-severity findings against the
formula snapshots before you report them; the scan can be wrong where units are unlabelled or
`OFFSET` hides a dependency.

## Stage 4: meaning, then checkpoint 1

1. Interview the owner with the questions in
   [meaning and dossier](references/meaning-and-dossier.md).
2. Write `ingest/meaning.json`: goal, users, decisions, manual steps, and for each block that
   feeds an output its name, equation, unit, meaning and reference.
3. Write a draft `logic-spec.md` (format in [logic-spec-format.md](references/logic-spec-format.md)):
   one entry per calculation the outputs need, every entry `Status: inferred`, the workbook
   range and issue IDs under "Source in the original work". Put the reconciliation tolerance in
   the Conventions line (`default abs=1e-6 rel=1e-9; L05 abs=0.001`).
4. Rebuild the dossier: `python <skill>/scripts/dossier.py --ingest <ingest folder>`.

**Checkpoint 1.** Send `ingest/dossier.html` to the owner. The owner confirms the goal, the
users, the meaning of each block, and answers the blocking questions. Do not continue until the
owner has answered. Set the confirmed Logic Spec entries to `Status: confirmed`.

## Stage 5: calculation model, then checkpoint 2

1. Scaffold: `python <skill>/scripts/calc_model_scaffold.py book.xlsx --out <ingest folder>`.
   It writes `calc_model.py` (one commented section per block in calculation order),
   `excel_compat.py`, `data/*.csv` and a draft `output-map.json`.
2. Edit `output-map.json`: the outputs the App Brief needs, with Logic Spec IDs and the key
   range of each vector output.
3. Port each block following the Logic Spec and
   [the model rules](references/calc-model-and-reconciliation.md). Use `excel_compat.py` for
   Excel behaviour (rounding, serial dates, empty cells, range lookups, 15 digits, errors) and
   [the Excel function map](references/excel-function-map.md) for each function.
4. Reconcile the stored values:

   ```bash
   python <skill>/scripts/reconcile.py extract --workbook book.xlsx --map ingest/output-map.json --out ingest/expected.csv
   (cd ingest && python calc_model.py --out actual-model.csv)
   python <skill>/scripts/reconcile.py compare --expected ingest/expected.csv --actual ingest/actual-model.csv \
       --map ingest/output-map.json --logic-spec logic-spec.md --out ingest/reconciliation-model
   ```

5. Add input cases that exercise every branch, lookup band and boundary
   (`excel_cases.py make`, the owner recalculates and saves each copy in Excel,
   `excel_cases.py extract`), run the model on them and compare again.
6. A difference you cannot remove without changing the logic is not fixed: record it as a
   question and, when the owner accepts it, in `ingest/explanations.csv`.

**Checkpoint 2.** Every output matches or is explained in the reconciliation reports. Show the
reports and the hidden errors the model recorded to the owner.

## Stage 6: redesign, then checkpoint 3

1. Map every workbook element to a Spotfire element with the tables in
   [the Excel function map](references/excel-function-map.md) and write
   `ingest/mapping-table.md` (workbook element, where, Spotfire element, fidelity EXACT, CLOSE,
   SUBSTITUTE or MANUAL, note). One sheet per asset becomes one long table; what-if tables
   become a sweep in the data function; VBA steps become scripts only after the code is read.
2. Write `ingest/change-list.md`: every difference between the workbook and the DXP. Fixes to
   workbook errors are **proposed**; changes of form only (ranges to tables, inputs to
   properties) are listed but change no number.
3. Write `app-brief.md` ([format](references/app-brief-format.md)) starting with the business
   problem; every KPI names a Logic Spec ID; every input becomes a property.
4. Finish `logic-spec.md`: "Implemented as" names one Spotfire element per entry.
5. Fill in the model's data function interface (`PARAMETERS`, `TABLE_PARAMETERS`,
   `SPOTFIRE_OUTPUTS`, `spotfire_outputs`), reconcile once more, then export it:
   `python <skill>/scripts/export_data_function.py --model ingest/calc_model.py --out datafunctions/<file>.py --name "<Verb Object>"`.
6. Write the draft `spec.json` following [the draft spec reference](references/spec-draft.md)
   and the [naming standard](references/naming-standard.md); data tables from `data/*.csv`,
   which ship with the draft. Use only what the build's standard engine builds (listed in the
   draft spec reference): calculated columns and relations become columns the data function
   writes; a feature that needs the build's slim tier goes into the mapping table.
7. Copy `<skill>/scripts/reconcile.py` to `ingest/reconcile.py` for the build step.
8. Run `python <skill>/scripts/check_handoff.py $DXP_WORKSPACE/apps/<AppSlug> --build-skill
   <folder of the building-spotfire-dxps skill>` and fix every error and warning. Without the
   build skill installed, leave out `--build-skill`; the static checks still run.

**Checkpoint 3.** The owner approves or rejects each proposed change. Approved changes go into
the model, followed by a new reconciliation with the accepted differences in
`ingest/explanations.csv`, and the Logic Spec and change list are updated. Rejected changes stay
reproduced.

## Files this skill writes

| File | Content |
|---|---|
| `app-brief.md`, `logic-spec.md`, `spec.json` | The hand-off |
| `datafunctions/<file>.py` | The exported, reconciled model |
| `data/*.csv` | Input tables taken from the workbook |
| `html/*.html` | Text-area HTML referenced by the spec, when the draft has input panels |
| `ingest/inventory.json`, `structure.json`, `issues.json`, `issues.csv`, `dependencies.mmd`, `snapshots/` | Stages 1 to 3 |
| `ingest/meaning.json`, `ingest/dossier.html` | Stage 4 |
| `ingest/calc_model.py`, `excel_compat.py`, `output-map.json`, `expected.csv`, `cases/`, `reconciliation-model.md`, `explanations.csv` | Stage 5 |
| `ingest/mapping-table.md`, `ingest/change-list.md`, `ingest/reconcile.py` | Stage 6 |

## Worked example and fixtures

- `assets/examples/line-pressure-profile/` is a complete hand-off for the synthetic pipe
  pressure-drop workbook: App Brief, Logic Spec, draft spec, mapping table, change list,
  meaning, the reconciled model (it reproduces the seeded defects) and the exported data
  function. It passes `check_handoff.py` and its model reconciles with 0 differences.
- `assets/fixtures/` holds three synthetic workbooks with seeded defects (pipe pressure drop,
  production decline with template copies and a what-if table, project economics with a
  circular interest calculation and an external link). `scripts/make_fixtures.py` rebuilds them
  and lists every seeded defect; `scripts/tests/test_excel_scripts.py` checks that the scripts
  find each one.

## Limits

- Tested on the synthetic fixtures only. Real workbooks (two or three, one hydraulics or
  production calculation and one economics model) are still to be run.
- Opening the fixtures in Excel, the COM paths and the `formulas` engine are **Not yet tested**.
- `.xls`, `.xlsb` and password-protected files are not read.
- Pivot tables are listed from their parts; their layout is not rebuilt.
- Speed: stages 1 to 3 took about 12 seconds for a synthetic sheet of 60,000 formula cells.

## Next: the `building-spotfire-dxps` skill reads these files

Hand over the app folder. The `building-spotfire-dxps` skill reads `app-brief.md`,
`logic-spec.md`, `spec.json`, `datafunctions/` and `data/`, builds the DXP, runs it with the
stored inputs and each case, exports the output tables to CSV and runs `ingest/reconcile.py
compare` against `ingest/expected.csv` (stage 7, checkpoint 4). It does not change the App Brief
or the Logic Spec without telling the user.
