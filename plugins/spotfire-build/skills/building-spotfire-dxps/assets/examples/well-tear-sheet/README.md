# Well Tear Sheet: example app

A single-well acquisition tear sheet built with the standard engine. The economics are synthetic
(case `DEMO-WELL-001`, a drilled but uncompleted well); no real well, operator or deal is behind
them. Use this app to try the whole workflow once before you build your own.

## Data

`data/source_tear_sheet.json` holds the annual economics: case metadata, headline KPIs, the PV table,
maximum bids, breakevens, reserves and 11 annual cash-flow rows (Yr 1 to Yr 10 plus Remaining).
`data/make_source_economics.py` writes it from a monthly model (Arps decline, price deck, operating
cost, taxes, capex); the assumptions are constants at the top of that script. Run it with any
Python 3.10+ when you change an assumption.

`data/generate_toy_data.py` (run it with Spotfire's Python, `SPOTFIRE_PYTHON`) writes one SBDF per
table and the two text-area HTML files:

| table | rows | content |
|---|---|---|
| WELL_SUMMARY | 1 | metadata and headline economics |
| CASH_FLOW_ANNUAL | 11 | annual economics plus $K copies of the money columns for the statements |
| PRODUCTION_MONTHLY | 602 | monthly profile, reconstructed so it sums to every annual total |
| PV_PROFILE | 5 | PV and NPV at 0, 10, 15, 20 and 30% |
| BREAKEVENS | 7 | oil breakevens, maximum bids, capex headroom |
| RESERVES | 2 | remaining gross and net |
| LOE_PER_BOE | 40 | lifting cost per net BOE by year and component |
| SENSITIVITIES | 10 | scenarios with an economic limit (model deltas applied to the base case) |
| DILIGENCE_FLAGS | 6 | flags derived from the economics |

`html/header.html` and `html/diligence.html` use inline styles only and pass Spotfire's default
HTML sanitizer.

## Design

Page "Tear Sheet": header text area, KPI chart (PV10, acquisition price, NPV10 after price, IRR,
MOIC, payback, oil breakeven), tables for present value, breakevens and reserves, line charts for oil
and gas rate and cumulative cash flow (zero line and payback line), and a stacked bar chart of
lifting cost per BOE.

Page "Cash Flow and LOE": cross tables with line items as rows and calendar periods as columns (cash
flow summary and lease operating expense statement), a sensitivities table with red negative values,
and the diligence flags text area.

`app.style` in `spec.json` holds the look the standard engine applies: palette, Segoe UI, named
number formats, per-kind defaults (KPI and table fonts, cross-table widths, red negatives). The
document theme is not part of the spec: apply one with the `styling-spotfire-dxps` skill if you want
it. The spec has no text-area controls, triggers or action mods, so the build has no manual steps.

## Build and verify

```
"%SPOTFIRE_PYTHON%" data\generate_toy_data.py
python <skill>\scripts\dxpgen.py validate .
python <skill>\scripts\dxpgen.py build . --clipboard
```

Copy the folder to `$DXP_WORKSPACE/apps/well-tear-sheet` first if you want to address it by slug.
`build` writes `build/build_well-tear-sheet_standard.py` (about 40 KB). `--tier quick`,
`--tier compact`, `--tier report` and `--tier slim` write the other tiers next to it.

Run the builder unattended with the `running-spotfire-unattended` skill, or in Spotfire Analyst:
File > New and add any data, Edit > Document Properties > Scripts > New, language IronPython 3,
untick "Execute in transaction", paste, Run Script, close the dialog with Cancel. The analysis saves
itself to `build/Well Tear Sheet standard.dxp` and writes `build/build-log-standard.txt`. Close the
open analysis without saving and open the saved DXP. Then:

```
python <skill>\scripts\verify_dxp.py check . --dxp "build\Well Tear Sheet standard.dxp"
```
