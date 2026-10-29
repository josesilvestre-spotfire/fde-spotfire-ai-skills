# Scripts

All scripts are in `scripts/`. Run them with Python 3.10 or later from any folder; they import
each other from their own folder. None of them starts Excel unless an option says so, none runs
macros, none updates links, and none writes into the workbook. They write only into the folder
given with `--out` (the app's `ingest/` folder).

| Script | Stage | What it does | Writes | Needs |
|---|---|---|---|---|
| `ingest_workbook.py` | 1 to 4 | Runs inventory, structure, issues and a draft dossier in one command | everything below | standard library |
| `inventory.py` | 1 | Reads the workbook XML: sheets, used ranges, formulas and stored values, names, Solver settings, tables, data validation, conditional formats, hidden sheets, rows and columns, comments, charts, pivots, external links, connections and Power Query, form controls, VBA presence, macro sheets, array formulas, what-if data tables, calculation settings | `inventory.json`, `snapshots/*.values.csv`, `snapshots/*.formulas.csv`, `vba/*.bas` with oletools | standard library; oletools optional (VBA code); openpyxl optional (`--crosscheck`); pywin32 and Excel for `--excel-snapshots` (**Not yet tested**) |
| `structure.py` | 2 | R1C1 blocks, block roles, labels and units, dependency graph, circular references, template copies | `structure.json`, `dependencies.mmd` | standard library |
| `issues.py` | 3 | Issue scan with severity and owner questions | `issues.json`, `issues.csv` | standard library |
| `dossier.py` | 4 | HTML dossier from the JSON files and `meaning.json` | `dossier.html` | standard library |
| `calc_model_scaffold.py` | 5 | Model scaffold with one section per block in calculation order, data CSVs, draft output map | `calc_model.py`, `excel_compat.py`, `data/*.csv`, `output-map.json` | standard library (the model needs pandas) |
| `excel_compat.py` | 5 | Excel behaviour helpers imported by the model | | standard library |
| `excel_cases.py` | 5 | Copies of the workbook with other inputs, marked for recalculation in Excel; reads them back after Excel has saved them. `recalc` runs the cases through Excel COM or the `formulas` package (**Not yet tested**) | `cases/*.xlsx`, `expected-cases.csv` | standard library; pywin32 and Excel, or formulas, for `recalc` |
| `reconcile.py` | 5 and 7 | `extract` reads the workbook's values for the outputs in `output-map.json`; `compare` checks a model output or a DXP export against them within the Logic Spec tolerances | `expected.csv`, `<out>.md`, `<out>.csv` | standard library (`extract` uses `xlsxlib.py`) |
| `export_data_function.py` | 6 | Writes the data function script: the excel_compat functions the model uses, the model code, and the parameter mapping | `datafunctions/<file>.py` | standard library |
| `check_handoff.py` | 6 | Checks `app-brief.md`, `logic-spec.md` and `spec.json` before the hand-off: formats, names, bindings, data files, fields the build's standard engine does not build; with `--build-skill <folder>` also runs the build skill's `dxpgen.py validate` | report on screen | standard library |
| `make_fixtures.py` | tests | Writes three synthetic workbooks with seeded defects | `assets/fixtures/*.xlsx` | standard library |
| `xlsxlib.py` | all | Workbook reader and formula tools used by the other scripts | | standard library |

Tests: `python scripts/tests/test_excel_scripts.py` (pandas needed for the model tests, openpyxl
optional).

## Commands

```bash
S=<this skill>/scripts
W=$DXP_WORKSPACE/apps/<AppSlug>

python $S/ingest_workbook.py book.xlsx --out $W/ingest --crosscheck        # stages 1 to 3 + draft dossier
python $S/dossier.py --ingest $W/ingest                             # after writing meaning.json
python $S/calc_model_scaffold.py book.xlsx --out $W/ingest          # stage 5 scaffold
python $S/reconcile.py extract --workbook book.xlsx --map $W/ingest/output-map.json \
    --out $W/ingest/expected.csv
(cd $W/ingest && python calc_model.py --out actual-model.csv)
python $S/reconcile.py compare --expected $W/ingest/expected.csv \
    --actual $W/ingest/actual-model.csv --map $W/ingest/output-map.json \
    --logic-spec $W/logic-spec.md --out $W/ingest/reconciliation-model
python $S/export_data_function.py --model $W/ingest/calc_model.py \
    --out $W/datafunctions/calculate_pressure_profile.py --name "Calculate Pressure Profile"
python $S/check_handoff.py $W --build-skill <folder of the building-spotfire-dxps skill>
```

## Excel through COM (optional, Not yet tested)

`inventory.py --excel-snapshots` and `excel_cases.py recalc --engine excel` start their own
hidden Excel instance (`DispatchEx`), so workbooks the user has open are not touched. Before the
file opens they set `AutomationSecurity = 3` (macros disabled); they open it with
`UpdateLinks=0` and `ReadOnly=True` and close it without saving. Ask the user before you use
them, and never use them while the user works in Excel on the same file.
