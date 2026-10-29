---
name: building-spotfire-dxps
description: Builds a finished Spotfire Analyst DXP from an app spec through Spotfire's public API. Reads the App Brief, Logic Spec and draft spec.json that the ingest skills write (or writes spec.json from a request), exports the data to SBDF with Spotfire's own Python, validates the spec, generates one pasteable IronPython builder, has it run in Analyst 15.0 (by hand or unattended), verifies the saved DXP against the spec, lists what must be added by hand, and keeps every handover as a versioned release. Use when an app, a prototype hand-off or a workbook hand-off must become a DXP, when a DXP must be rebuilt from its spec, or when a saved DXP must be checked against its spec.
compatibility: Windows, Spotfire Analyst 15.0 (documents readable by 14.6). Python 3.10+ for the tools (standard library; verify_dxp.py also needs lxml). Spotfire's bundled Python for SBDF export.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Building Spotfire DXPs

This skill turns an app spec into a Spotfire analysis without hand-editing any file inside the DXP.
Spotfire builds every page, visual, table, property, data function and script through its own API
and saves the file itself; the verifier then reads the saved DXP back and compares it with the spec.

```
app-brief.md + logic-spec.md + spec.json (draft)      or a request
        |  you complete spec.json, html/, scripts/, datafunctions/, data/*.sbdf
        v
dxpgen.py validate  ->  dxpgen.py build  ->  build/build_<AppSlug>_<tier>.py  (+ MANUAL-STEPS-<tier>.md)
        |  run it in Analyst (unattended, or pasted into the script editor)
        v
build/<App name> <tier>.dxp  ->  verify_dxp.py check  ->  build/verify-report.md
        |  every handover
        v
dxpgen.py release --version vX.Y  ->  <app>/versions/vX.Y/
```

Read only what the task needs. The spec format is in [references/spec-format.md](references/spec-format.md)
(open the section for the field you write); API recipes per area are in `references/api-*.md`.

## Before you start

| Variable | Used for |
|---|---|
| `DXP_WORKSPACE` | folder that holds `apps/<AppSlug>/` (the older name `DXP_BUILDER_HOME` also works) |
| `SPOTFIRE_HOME` | the Analyst install folder (holds `Spotfire.Dxp.exe`); used by `ipy_parse.ps1` and `dump_api.ps1` |
| `SPOTFIRE_PYTHON` | Spotfire's `python.exe` (under `SPOTFIRE_HOME/Modules/Python Interpreter_*/python/`) for `sbdf_export.py` |
| `SFAPI_INDEX` | the API index file; default: the newest `$DXP_WORKSPACE/api/spotfire-api-*.json` |

Generate the API index once per Spotfire version on your own machine (it is not shipped):

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dump_api.ps1
```

It loads the installed assemblies read-only, lists public members only and writes
`$DXP_WORKSPACE/api/spotfire-api-<build>.json`. Without an index every tool still runs; the member
checks are skipped with a warning.

All commands below run from this skill's folder; `<app>` is an app folder, its `spec.json`, or an
app slug under `$DXP_WORKSPACE/apps/`.

## Workflow

1. **Read the inputs.** With ingest outputs, follow "Building from ingest outputs" below. With a
   request only, write down the pages, the visuals per page (type, table, axes), the inputs (they
   become document properties), the calculations that must react to inputs (they become Python
   data functions) and the data sources, and ask about anything that changes the design.
2. **Scaffold** a new app: `python scripts/dxpgen.py new <AppSlug> --name "<App Name>"` creates
   `$DXP_WORKSPACE/apps/<AppSlug>/` with `spec.json`, `data/`, `html/`, `scripts/`,
   `datafunctions/` and `build/`.
3. **Data to SBDF** with Spotfire's own Python, so column types are exact:
   `"%SPOTFIRE_PYTHON%" scripts/sbdf_export.py data.csv <app>/data/PUMP_DATA.sbdf --types "Timestamp (UTC)=DateTime"`.
   The standard engine loads SBDF tables only. Data that must react to inputs is computed by a data
   function (the `writing-spotfire-data-functions` skill), not precomputed.
4. **Write spec.json** plus the files it names: text-area HTML in `html/`, IronPython in `scripts/`
   (the `writing-spotfire-ironpython` skill), data function code in `datafunctions/`. Follow
   [references/naming-standard.md](references/naming-standard.md): PascalCase properties, Title Case
   "Verb Object" scripts and data functions, UPPER_SNAKE_CASE tables, Title Case columns with units.
   Write text-area HTML that survives Spotfire's default sanitizer (inline styles with plain values;
   no `<style>`, `<script>`, `<button>`, `<input>`, `<select>`, `<svg>`, `<details>`).
5. **Validate**: `python scripts/dxpgen.py validate <app>`. Fix every error and read every warning.
   Validation checks the schema, references, the columns of the data files, naming, the sanitizer
   rules, IronPython lint, customer-ready text, reference-line types and marker aggregation.
6. **Build**: `python scripts/dxpgen.py build <app> --clipboard` writes the standard builder
   `build/build_<AppSlug>_standard.py`, checks it (Python parse, lines of at most 79 characters,
   ASCII, undefined names, `lint_ipy.py`, Spotfire's own IronPython parser, `sfapi.py has` for every
   member) and writes `build/MANUAL-STEPS-standard.md`. Other tiers with `--tier` (below).
7. **Run the builder.** With the `running-spotfire-unattended` skill installed, run it unattended
   through that skill. Otherwise you or the user runs it in Analyst:
   - open a new analysis and add any starter data (the script editor needs data; the builder
     renames clashing starter tables and removes them at the end);
   - Edit > Document Properties > Scripts > New, language IronPython 3, **untick "Execute in
     transaction"**, paste, Run Script;
   - close the dialog with **Cancel** (OK stores the builder inside the analysis);
   - File > Open the saved `build/<App name> <tier>.dxp`. Never save the open build session (answer
     No): closing the Document Properties dialog resets its markings, and it is linked to a scratch
     file in `build/session/`.
   The builder writes `build/build-log-<tier>.txt`: `OK`, `NOTE`, `FAILED` and `TODO` lines.
8. **Add the manual steps** in the saved DXP: every item of `build/MANUAL-STEPS-<tier>.md` (also the
   `TODO` lines of the log), then save. See "Public API only" below.
9. **Verify**: `python scripts/verify_dxp.py check <app> --dxp "<app>/build/<App name> standard.dxp"`
   writes `build/verify-report.md` and `.json`. Report every FAIL with the report path. A manual step
   not done yet is a WARN, never a PASS.
10. **Release every handover**: `python scripts/dxpgen.py release <app> --version vX.Y --notes "..."`
    copies the runtime files to `<app>/versions/vX.Y/`, generates the builder from that copy (it
    saves its DXP there) and adds a row to `<app>/versions/README.md`. Hand over the versioned builder
    path dxpgen prints. A version folder is never regenerated once it holds a saved DXP, so the
    previous good version is always the backup. After the user checks the DXP, write Good or Broken
    in the README's Status column.

For small changes to a built app, change the spec or the files and build again: HTML, scripts and
data function code are read from the app folder when the builder runs.

## Building from ingest outputs

The `ingesting-prototypes` and `ingesting-excel-workbooks` skills read existing work and leave an
app folder with `app-brief.md`, `logic-spec.md`, a draft `spec.json`, `data/` and, for a workbook,
`datafunctions/` and `ingest/`. They never build. You do, as follows.

1. Read [references/app-brief-format.md](references/app-brief-format.md) and
   [references/logic-spec-format.md](references/logic-spec-format.md), then the two documents.
   An open question marked **Blocking** stops the build until the owner answers it. Every input of
   the App Brief is a document property; every KPI and output names the page that shows it; every
   Logic Spec entry is implemented exactly as its "Implemented as" line says.
2. Validate the draft unchanged: `python scripts/dxpgen.py validate <app>`. The draft uses spec
   version 1 field names, so it validates without edits.
3. Complete the spec: convert `data/*.csv` to SBDF with `sbdf_export.py` and switch those table
   sources to `sbdf` (the standard engine loads SBDF only; `--tier slim` also reads CSV), add the
   page filter layouts, `app.style`, visual `settings`, and the visualization mods the design names.
   Draft text-area controls stay in the spec: they become markers and manual steps.
4. **Workbook source:** the data function file in `datafunctions/` is the calculation model the
   ingest skill reconciled against the workbook (`ingest/calc_model.py`, exported unchanged). Use it
   as the data function code unchanged. When the build needs a change to it, stop, tell the user, and
   send the change back through the ingest skill (change list, new reconciliation).
5. Build, run, add the manual steps and verify as in the workflow.
6. **Workbook source, reconciliation:** export the DXP's output tables to CSV, then run the
   reconciliation step of the `ingesting-excel-workbooks` skill against the Excel values, with the
   stored inputs and each case it lists. To export unattended, run `scripts/export_tables_job.py`
   through the `running-spotfire-unattended` skill (`--set source=<saved DXP> --set tables=A,B`;
   **Not yet tested**); by hand, use File > Export > Data to File in Analyst for each table. Report
   every output that does not match within the Logic Spec's tolerance.
7. Never change `app-brief.md` or `logic-spec.md` without telling the user.

## Builder tiers

Every builder is one IronPython 3.4 file with lines of at most 79 characters, ASCII only.

| Tier | Flag | What it is | When |
|---|---|---|---|
| standard | `--tier standard` (default) | the standard engine (`scripts/engine` + `scripts/t3`): data, visuals, colors, layout, fonts, number formats, widths, red negatives, reference lines | every normal build |
| quick | `--tier quick` | standard engine with fonts and red negatives only | a faster build when styling is secondary |
| compact | `--tier compact` | data, visuals, colors and layout; no font styling | the quickest check |
| report | `--tier report` | standard plus a step report, `MANUAL-STEPS-report.md` and PNG snapshots | a standard build misbehaves and the cause is unclear |
| slim | `--tier slim` | the build library (`scripts/lib`) trimmed to what the spec uses | the spec needs something the standard engine does not build |
| full | `--tier full` | the whole library (about 450 KB, too big for the script editor) | library development only |

The standard engine builds line, bar, scatter, table, cross table, KPI chart, map, text area and
visualization mod visuals. When the spec uses something it does not build (CSV sources, calculated
columns, relations, hierarchies, named filtering schemes, a fixed canvas, pie, box plot, heat map,
treemap, waterfall, histogram, combination chart, 3D scatter, summary or graphical table), dxpgen
stops with "not in the standard engine yet: use --tier slim" and the field paths. Use the slim tier,
or a substitute from [references/spec-format.md](references/spec-format.md). The slim tier writes
its own `build-report.json`, `MANUAL-STEPS.md` and snapshots at run time. How the engine is
assembled: [references/engine.md](references/engine.md).

## Public API only: what is added by hand

The builder uses Spotfire's public API only. Spotfire 15.0 has no public API for these items, so the
builder does not create them; it lists each with exact Analyst instructions in
`build/MANUAL-STEPS-<tier>.md` and as a `TODO` line in the build log:

| Spec item | What the builder does | What you do |
|---|---|---|
| text-area `controls` (`{{control:<id>}}`) | puts a visible marker such as `[Drop-down list: SelectedPumpId]` or `[Button: Reset Filters]` | Edit Text Area, replace the marker with Insert Property Control or Insert Action Control as described |
| `triggers` (property change runs a script) | registers the script | Edit > Document Properties > Properties > the property > Script... > the script |
| `actionMods`, a button's `actionMod`, visual `actionTriggers` | buttons get no action mod; no visual action triggers | add the action mod and wire the buttons and triggers (the `building-action-mods` skill) |
| `app.theme` | writes the custom styles to `build/theme.json` | apply the theme (the `styling-spotfire-dxps` skill) |
| a visualization mod that is not embedded, installed or pinned | a placeholder text area `[mod: <id>]` | pin the mod, or add it once to the starter page before you run the builder (**Not yet tested**) |

`verify_dxp.py` reports such an item as WARN until it is in the saved DXP, then checks it like any
other item. The text-area styling (CSS injected through text-area JavaScript, theme, palette) is the
`styling-spotfire-dxps` skill's work; this skill keeps a neutral default style.

## Rules that prevent known live bugs

- Never hand-write or patch `AnalysisDocument.xml`. Every object is created by Spotfire through the
  builder.
- Every Spotfire member in generated code and in scripts exists in the index of your installed
  version: check it with `python scripts/sfapi.py has Type.Member` (or `chain "<expr>"`) before you
  write it. `lint_ipy.py` enforces this and rejects `BindingFlags.NonPublic`.
- Untick "Execute in transaction". Inside a transaction Spotfire refuses `SaveAs`, a save queued from
  the script editor never runs, and closing the dialog then resets the markings. When the log has no
  `Saved` line, use File > Save As and re-check the markings and the description.
- Open the saved DXP after the run; never keep working in or save the build session.
- IronPython 3.4 only: no f-strings, walrus, annotations, tabs or `print`; `getattr(Enum, "None")`
  for enum members named None; generics as `AddNew[T]()`; out parameters return tuples.
- Exact property value types: a Real default is `72.0`, not `72`. Property names use letters and
  digits only.
- One name per binding: document property = data function parameter = control binding = script
  lookup key. A mismatch raises no error; the control does nothing or the value goes stale.
- Scatter plots and map marker layers aggregate their markers unless the marker-by contains
  `baserowid()`. A raw label, size, line order or rotation then blanks the visual ("Please specify
  an aggregation method."); on a map one bad layer blanks the whole map. dxpgen stops on it.
- A date reference line binds to a DateTime property or a date expression; no `DateAdd` over a
  number property.
- Data functions: output tables exist only after the first run, so visuals on them are built after
  the run. Text columns go out as `object` dtype under pandas 3 (`sbdf_export.py` handles it).
- Embedded data only, no local paths or credentials in the DXP (`verify_dxp.py` scans the archive).
  sbdf tables are loaded by file name so the DXP keeps no local folder.
- Bump a mod's version in every release that changes it: the builder takes the listed mod with the
  manifest's version first.
- Every handover is a release; never change or delete a version folder that holds a saved DXP.

## Design rules dxpgen checks

dxpgen warns or stops on these; the full set is the `spotfire-app-design-rules` skill.

- Every page organizes its filter panel (page `filters` or top-level `filterPanelLayout`): only the
  tables and columns a user needs; ids, keys, coordinates and calculation-only columns hidden.
  Never style the filter panel or the data canvas.
- KPIs as an HTML band (caption and value per figure), not KPI charts for single values.
- Customer-ready text everywhere, embedded code included: no release tags, version tags, TODOs,
  tool or assistant names, person names (`app.bannedTerms`) in titles, descriptions, HTML,
  messages, comments or strings.
- Markings that reach nothing, span tables or split one table are listed as notes (interaction
  audit): every marking must drive every relevant visual on its page.

## Scripts that run inside the DXP

Measured on Analyst 15.0, for trigger and button scripts the app ships:

- Spotfire spends 0.65 to 1.3 s preparing a large stored IronPython script on every run. Store a
  large script as a compile-once stub (code as a string, compiled once per session and cached in
  `AppDomain.CurrentDomain`, then `exec`): a trigger run fell from 650 ms to about 50 ms.
- Set reference-layer and coloring properties only when they change; each assignment re-evaluates
  the chart. Never remove and re-add a column of a shared table on a click.
- One trellised chart (RowsColumns, rows = lane) shows and hides lanes in under a second; many short
  charts are slow to add, remove and lay out.
- Filter visuals with `DocumentProperty(...)` where clauses instead of rebuilding tables.

The `writing-spotfire-ironpython` skill has the stub pattern.

## Files

| Path | What |
|---|---|
| `scripts/dxpgen.py` | `new`, `validate`, `build`, `release`, `verify` |
| `scripts/verify_dxp.py` | `check` a saved DXP against the spec; `dump` its model as JSON |
| `scripts/engine/` | the standard engine: `core.py`, `builders/`, `features/`, `report.py` |
| `scripts/t3/` | spec to HOME, STYLE and APP converters, the neutral house style, manual steps, assembly |
| `scripts/lib/`, `scripts/slim_builder.py` | the build library and the slim tier |
| `scripts/lint_ipy.py`, `scripts/textlint.py`, `scripts/sfexpr.py` | IronPython lint, customer-ready text check, expression readers |
| `scripts/sfapi.py`, `scripts/dump_api.ps1`, `scripts/sfenv.py` | API index queries, the index generator, environment lookup |
| `scripts/sbdf_export.py` | CSV, Parquet, JSON or pickle to SBDF with exact types (run with Spotfire's Python) |
| `scripts/ipy_parse.ps1` | compile a builder with Spotfire's IronPython 3.4 without running it |
| `scripts/sfgraph.py` | reader of the saved document's object graph (used by `verify_dxp.py`) |
| `scripts/export_tables_job.py` | job for the unattended runner: data tables to CSV |
| `references/` | [spec-format.md](references/spec-format.md), [architecture.md](references/architecture.md), [engine.md](references/engine.md), [analyst-facts.md](references/analyst-facts.md), [dxp-anatomy.md](references/dxp-anatomy.md), `api-*.md` recipes, [live-test-status.md](references/live-test-status.md), the shared formats |
| `assets/examples/` | `well-tear-sheet/` (synthetic economics, every engine tier), `mod-layers-demo/` (a visualization mod with three layers), `fragments/` (spec fragments per area) |
| `tests/` | unit tests of the tools and the engine (no Spotfire needed) |

## Tests

```
python -m unittest discover -s tests
```

The tests need no Spotfire. With `SFAPI_INDEX` (or `$DXP_WORKSPACE/api`) set they also check members
against your index; with Spotfire installed they also run its IronPython parser and the SBDF export
round trips. Tests that need what is missing are skipped.

## Status

Assembled from proven parts, not run as a whole: the engine tiers, data functions, scripts,
properties, markings and the run procedure were proven in live builds on Analyst 15.0 on one
machine; the public-only manual-step route of this release has not run in Analyst yet. What is
proven and what is **Not yet tested**: [references/live-test-status.md](references/live-test-status.md).
