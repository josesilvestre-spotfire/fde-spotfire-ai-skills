---
name: ingesting-prototypes
description: Reads an app prototype (Shiny for Python, Streamlit, Plotly or Dash, Quarto, plain HTML or a React mockup) and writes the hand-off files for a Spotfire build, which are the App Brief, the Logic Spec, a draft spec.json and a mapping table that gives every prototype element its Spotfire element, with a named substitute for anything Spotfire has no direct equivalent for. Ships a scanner that inventories the prototype's pages, inputs, outputs and reactivity, and a check for the hand-off files. Use it when a prototype, dashboard or mockup must become a Spotfire analysis, before any DXP is built. It only reads and documents; it never builds a DXP.
metadata:
  maturity: New, not yet tested
---

# Ingesting prototypes

This skill turns a working prototype into the three files a Spotfire build starts from:
`app-brief.md` (what the app is for), `logic-spec.md` (every calculation with its equation and
units) and a draft `spec.json` (pages, visuals, properties, data functions). It also writes a
mapping table that records, element by element, how the prototype becomes Spotfire and which
substitutes the owner approved.

The skill reads and documents. It does not build a DXP, generate an IronPython builder or start
Spotfire. The `building-spotfire-dxps` skill builds from its files.

## When to use it

| Starting point | Use |
|---|---|
| Shiny, Streamlit, Plotly, Dash, Quarto, HTML or React prototype | This skill |
| Excel calculation workbook | The `ingesting-excel-workbooks` skill |
| An existing DXP to rebuild | Inventory it first with the `auditing-and-comparing-dxps` skill, then use this skill with that inventory as the prototype (see "Rebuilding an existing DXP") |
| Only an idea or a conversation, no prototype | The `framing-spotfire-apps` skill writes the App Brief |

## Rules

- **No build.** Never write an IronPython builder, open Spotfire or save a DXP. Stop at the
  hand-off.
- **The prototype is the spec.** Map what the prototype does, not what you would design. A
  prototype that does not run is not a spec: get it running on a copy first.
- **Every element is mapped.** Every page, layout container, input, output, computation and piece
  of state gets one row in the mapping table, with a fidelity of EXACT, CLOSE, SUBSTITUTE or
  MANUAL.
- **The owner approves substitutes.** Every SUBSTITUTE and MANUAL row, every renamed input and
  every inferred calculation is confirmed by the owner before the hand-off.
- **Quirks stay until the owner decides.** A slider whose step never reaches its maximum, a
  selection that drives nothing, a label that disagrees with its value: keep the behaviour, note
  it in the mapping table and ask.
- **One name per binding.** An input id becomes one PascalCase name used for the document
  property, the data function parameter and the control binding (`fc_steps` becomes `FcSteps`).
- **Never edit the original prototype.** Work on a copy.
- **Text the user reads is written for the user**: titles, descriptions and labels carry no tool
  names, versions or developer notes.

## Files you write

All in the app folder `$DXP_WORKSPACE/apps/<AppSlug>/`:

| Path | Content |
|---|---|
| `app-brief.md` | Business problem, users, decisions, KPIs, inputs, outputs, data sources, refresh, open questions ([format](references/app-brief-format.md)) |
| `logic-spec.md` | Every computation the prototype performs ([format](references/logic-spec-format.md)) |
| `spec.json` | Draft build spec ([draft fields](references/spec-draft.md)) |
| `html/*.html` | Text-area HTML the spec refers to (control panels, KPI band) |
| `datafunctions/*.py` | Prototype engine code ported to data functions, only when you port it |
| `data/*.csv` | Datasets the prototype loads once or simulates with a fixed seed |
| `ingest/prototype-inventory.md`, `.json` | Scanner output |
| `ingest/mapping-table.md` | Every prototype element and its Spotfire element |

## Workflow

### 1. Locate the app folder

Read `DXP_WORKSPACE`. When it is not set, ask the user for the workspace folder. Pick a short
`AppSlug` without spaces and create `apps/<AppSlug>/`. When the folder already holds an App Brief
or Logic Spec from another skill, do not overwrite them: tell the user and merge.

### 2. Make the prototype runnable

1. Copy the prototype to a scratch folder. Pick the newest coherent version when there are
   several (mismatched modules between version folders are common).
2. Compile every file: `python -m py_compile <file>`. Fix nothing in the original; note what
   does not compile and ask.
3. Smoke-run the engine (the simulator, model or calculation module the UI imports) with the
   default inputs. You need its outputs later to check your port.
4. List the packages the engine imports. Spotfire Analyst 15.0's Python ships numpy, pandas and
   the spotfire package only; anything else is gap G12.

### 3. Scan the prototype

```bash
python scripts/scan_prototype.py <prototype file or folder> --out $DXP_WORKSPACE/apps/<AppSlug>/ingest
```

The scanner lists pages, layout containers, inputs (with ids, labels, defaults, ranges), outputs
(with trace kinds), reactivity, data loads and styling hints. It suggests a Spotfire element and
fidelity for mechanical cases, flags gap constructs (G1 to G13) and marks with "?" what it cannot
resolve. It reads code; it does not run it. Treat its list as a starting point.

### 4. Read the code

Read the prototype with [references/reading-prototypes.md](references/reading-prototypes.md).
Write down, per page: the layout tree with widths and heights, every input, every output, the
reactive graph (which inputs each output reads, what triggers each computation, what state is
kept), the data sources and the look. Add what the scanner cannot see: computations inside
functions, column names and units, colors, empty-state messages.

### 5. Map every element

Use [references/prototype-to-spotfire-mapping.md](references/prototype-to-spotfire-mapping.md):
section 1 for the direct mappings, section 2 for gaps with ranked substitutes. Take the first
ranked substitute unless the prototype gives a reason not to, and write the reason. Write
`ingest/mapping-table.md` (format below).

### 6. Write the Logic Spec

One entry per computation: engine functions, derived columns, the aggregate behind every KPI,
thresholds, smoothing, forecasts, filters that do arithmetic. Each entry has its equation, every
symbol with a unit, the output column or property, the grain, "Implemented as" (one of calculated
column, data function, document property, visual expression), the source file and function, edge
cases, and **Status: inferred**. In Conventions, state the tolerance used to compare the port
with the prototype engine.

Choose "Implemented as" by the reactive graph: a per-row formula with no Python is a calculated
column; anything that reacts to inputs and needs pandas or numpy is a data function; a single
aggregate shown in one visual can be a visual expression.

### 7. Write the App Brief

Start with the business problem: who has it, what it costs today, how it is handled now. Take it
from the owner, the prototype's README or About page. When nobody has stated it, write your best
reading and add a **Blocking** open question. Then users, decisions, KPIs (each with its Logic
Spec ID), one input row per prototype input, outputs with their page, data sources, refresh
cadence, out of scope (every element the mapping table drops), and open questions (every quirk
and every unclear behaviour).

### 8. Write the data and the code

- **Data the prototype loads once or simulates with a fixed seed**: run the prototype's own
  loader with its default inputs and write `data/<TABLE>.csv` with Title Case column names and
  units. Replace `datetime.now()` with a fixed start date so the data is reproducible.
- **Computation that reacts to inputs**: port it to `datafunctions/<verb_object>.py` when the
  engine code is small and clear; otherwise leave the Logic Spec entry and let the build step port
  it. A ported data function inlines sibling modules, uses numpy and pandas only, assigns every
  output on every path and returns typed empty outputs on empty input. The
  `writing-spotfire-data-functions` skill has the conventions.
- **Check the port** in CPython: run the prototype engine and the port on the same inputs and
  compare every output within the Logic Spec tolerance. The worked example's test does this.

### 9. Write the draft spec

Write `spec.json` with the fields in [references/spec-draft.md](references/spec-draft.md) and the
`html/` files it refers to. Names follow [references/naming-standard.md](references/naming-standard.md).
Every App Brief input is a property with a control; every value a data function writes is a
property; every visual id appears once in its page layout; every control is placed once in its
HTML with `{{control:<id>}}`. Use only what the build's standard engine builds (listed in
`spec-draft.md`): a filled band becomes its two edges as series, a calculated column becomes a
column the data function writes, and the mapping table records each such choice. Ship every data
file a table source names in `data/`.

### 10. Check the hand-off files

```bash
python scripts/check_handoff.py $DXP_WORKSPACE/apps/<AppSlug> --build-skill <folder of the building-spotfire-dxps skill>
```

It reports missing sections, KPIs that point at no calculation, names that break the naming
standard, bindings whose names differ, layout entries that point at no visual, controls not
placed exactly once, missing data files, fields the build's standard engine does not build, and
open questions that block the build. With `--build-skill` it also runs that skill's
`dxpgen.py validate` on the draft; leave the option out when the build skill is not installed.
Fix every error and every validator warning. Read every other warning: inferred calculations and
unanswered blocking questions are expected until step 11.

### 11. Owner checkpoint

Show the owner, in one message:

- every SUBSTITUTE and MANUAL row of the mapping table, with the gap and the chosen substitute
- every renamed input and every prototype quirk
- every Logic Spec entry with status inferred
- every blocking open question

Record each answer: the Owner decision column of the mapping table, `Status: confirmed` on each
Logic Spec entry, the Answer column of the open questions, and the App Brief status line
(`confirmed by <role> on <date>`). Do not hand off while a blocking question has no answer.

## Mapping table format

`ingest/mapping-table.md` holds one row per prototype element. Keep the scanner's element numbers
(E01, E02, ...) and continue the numbering for the rows you add.

```markdown
# Mapping table: <App name>

| # | Prototype element | Where | Spotfire element | Fidelity | Substitute and reason | Owner decision |
|---|---|---|---|---|---|---|
| E07 | `st.date_input` `window` "Date range" | app.py:22 | `input` controls on DateTime properties `WindowStart`, `WindowEnd` | SUBSTITUTE | G10: no date range control | Approved |
```

| Column | Content |
|---|---|
| Prototype element | Widget or construct, id, label |
| Where | File and line |
| Spotfire element | The spec element: page, visual id and type, property and control, data function, marking, reference layer, or "none" |
| Fidelity | EXACT, CLOSE, SUBSTITUTE or MANUAL |
| Substitute and reason | Gap ID and the ranked option chosen; renames and quirks |
| Owner decision | Filled at the checkpoint for every SUBSTITUTE, MANUAL, rename and quirk |

## Rebuilding an existing DXP

To rebuild an existing analysis, inventory it first with the `auditing-and-comparing-dxps`
skill. Its inventory (pages, visuals, data tables, data functions, scripts, document properties,
colors) takes the place of the scanner output: map each item as an element, treat the existing
data function code as the engine, and write the same three files. Behaviour the old DXP has but
the inventory cannot show (what a script does on a click) comes from reading the script.

## Worked example

[assets/samples/streamlit_pump_monitor/](assets/samples/streamlit_pump_monitor/app.py) is a
synthetic Streamlit prototype (sidebar inputs, a date range, tabs inside the page, a forecast with
a filled band and a dotted line, a file uploader). Its finished hand-off is in
[assets/examples/pump-vibration-monitor/](assets/examples/pump-vibration-monitor/app-brief.md):
App Brief, Logic Spec, draft spec, mapping table, text-area HTML and the ported data function.
Two more samples cover Shiny Core ([shiny_pressure_app](assets/samples/shiny_pressure_app/app.py))
and Dash ([dash_pump_fleet](assets/samples/dash_pump_fleet/app.py)).

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `scripts/scan_prototype.py <file or folder> --out <folder>` | Inventories a prototype; standard library only | `prototype-inventory.md`, `prototype-inventory.json` in `--out` |
| `scripts/check_handoff.py <app folder> [--build-skill <folder>]` | Checks `app-brief.md`, `logic-spec.md` and `spec.json` against the formats, each other and the build's standard engine; with `--build-skill` also runs the build skill's `dxpgen.py validate`; exit code 1 on errors | Nothing |
| `scripts/tests/test_prototype_scripts.py` | Runs both scripts on the samples and the worked example, and checks the example's data function against the sample engine (needs numpy and pandas) | Temporary files only |

Run the tests with `python scripts/tests/test_prototype_scripts.py`. The scanner and the check are
tested on the synthetic samples in this skill. They have not yet been run on a large real
prototype; the scanner reads code patterns and misses what a prototype builds dynamically
(widgets created in loops, figures assembled across functions).

## Next: the `building-spotfire-dxps` skill reads these files

When the check reports 0 errors and the owner has answered every blocking question, hand off:

1. Tell the user the app folder path and that the App Brief, Logic Spec, draft spec and mapping
   table are ready for the `building-spotfire-dxps` skill.
2. List what will need a manual step after the build (every MANUAL row) and the non-blocking open
   questions.
3. Stop. The `building-spotfire-dxps` skill validates and completes `spec.json`, builds the DXP
   and verifies it. It reads the App Brief and Logic Spec and does not change them without telling
   the user.
