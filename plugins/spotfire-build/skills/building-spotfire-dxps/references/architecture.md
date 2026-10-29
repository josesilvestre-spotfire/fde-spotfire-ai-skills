# Architecture (contract for the building-spotfire-dxps skill)

## Pipeline

```
prototype or brief (the ingesting-prototypes skill turns a prototype into a spec)
   |
   v
$DXP_WORKSPACE/apps/<AppSlug>/spec.json + data/*.sbdf + html/ + scripts/ + datafunctions/
   |  python scripts/dxpgen.py validate <app>     (schema, references, data-file columns, naming,
   |                                               HTML sanitizer, lint, customer-ready text,
   |                                               reference-line types)
   |  python scripts/dxpgen.py build <app> [--tier standard|quick|compact|report|slim] [--clipboard]
   v
build/build_<AppSlug>_<tier>.py   one IronPython 3 file (standard, quick, compact, report: the
   |                              standard engine, scripts/engine/ + scripts/t3/; slim: only the
   |                              scripts/lib/ code the spec reaches, scripts/slim_builder.py)
build/MANUAL-STEPS-<tier>.md      one Analyst instruction per item the public API cannot build
build/theme.json                  app.theme custom styles, for the manual theme step
   |  you run the builder in Spotfire Analyst: new analysis with starter data > Edit > Document
   |  Properties > Scripts > New > untick "Execute in transaction" > paste > Run Script > Cancel
   |  (or unattended, with the running-spotfire-unattended skill)
   v
build/<name> <tier>.dxp   build/build-log-<tier>.txt   (TODO lines = the manual steps)
   |  report tier also: build-report-report.json, MANUAL-STEPS-report.md (with "Add by hand"),
   |  snapshots-report/; slim tier: build-report.json, MANUAL-STEPS.md, snapshots/
   |  you do the manual steps in Analyst and save
   |  python scripts/verify_dxp.py check <app> --dxp "build/<name> <tier>.dxp"
   v
build/verify-report.md (+ .json)   PASS / FAIL / WARN per spec item + hygiene checks
```

Never hand-write `AnalysisDocument.xml`. Spotfire itself serializes everything the builder creates.

## Builder tiers and the standard engine

`dxpgen.py build` writes the **standard** tier by default. The standard engine is
`scripts/engine/` (IronPython: `core.py`, `builders/<kind>.py`, `features/<name>.py`,
`report.py`) plus `scripts/t3/` (CPython: one spec-to-APP converter per kind, the house style,
STYLE composition and assembly). A builder is `HOME`, `STYLE` (house style + `app.style`) and
`APP` (converted from the resolved spec, with the manual steps in `APP["manual"]`), followed by the
core and only the builders and feature parts the app uses.

| tier | builds |
|---|---|
| `standard` (default) | the standard engine with full styling: fonts, number formats, widths, red negatives, reference lines |
| `quick` | fonts and red negatives |
| `compact` | data, visuals, colors and layout, no font styling (the quickest) |
| `report` | the standard tier plus `scripts/engine/report.py`: a step report, MANUAL-STEPS with a fix per failed step, snapshots |
| `slim` | `scripts/slim_builder.py`: only the `scripts/lib/` code the spec reaches. Use it when the standard engine stops with the field paths and "not in the standard engine yet: use --tier slim" |
| `full` | every `scripts/lib/` module concatenated (about 450 KB, too big for the script editor): library development only |

Tier blocks in the engine files (`# @tier quick` / `# @tier standard` ... `# @end`) decide what
each tier keeps. Feature parts (`scripts/engine/features/`: document properties, markings, data
functions, scripts, text-area control markers, mod lookup, text-area JavaScript, links, settings,
legends, coloring, filter panels, the preflight and the build session switch) and `# @feature`
blocks are included only for apps that use them. Details, schema and how to add a builder:
[engine.md](engine.md); the style layer: [spec-format.md](spec-format.md) "app.style".

Rules every generated builder follows (all tiers): IronPython 3.4 syntax (no f-strings, walrus,
annotations, print), lines <= 79 characters, ASCII only; the opened-from-file guard; starter tables
renamed on a name clash and removed at the end; each item in its own guarded step; the save inside
the script first, the queued save as the fallback, and a log line asking for File > Save As when no
"Saved" line appears; one `TODO <what>: <how>` log line per manual step. dxpgen checks every
builder: Python parse, `scripts/lint_ipy.py` (0 errors), `scripts/ipy_parse.ps1` (Spotfire's own
IronPython 3.4 compiler: PARSE OK) and `scripts/sfapi.py has` for every Spotfire member the
included engine parts declare (`# @api`, `# @set`). Without an API index the member check is
skipped with a note.

## Workspace

The tools take an app folder, its `spec.json`, or an app slug under `$DXP_WORKSPACE/apps/`. Set
`DXP_WORKSPACE` (the older name `DXP_BUILDER_HOME` is also read); there is no default location.

```
$DXP_WORKSPACE/
  api/               spotfire-api-<build>.json, spotfire-property-docs.json (scripts/dump_api.ps1)
  apps/<AppSlug>/
    spec.json
    data/            SBDF (preferred) or CSV inputs
    html/            text-area HTML, CSS, JS
    scripts/         IronPython action and trigger scripts
    datafunctions/   Python (or TERR) data-function code
    build/           generated: builders, MANUAL-STEPS, theme.json, DXPs, logs, reports,
                     snapshots, session/ (the build session scratch file)
    versions/vX.Y/   releases written by dxpgen release
```

Other variables: `SFAPI_INDEX` (the API index file), `SPOTFIRE_HOME` (the Analyst install folder,
for `ipy_parse.ps1`, `sf_sanitize.ps1` and `dump_api.ps1`), `SPOTFIRE_PYTHON` (Spotfire's
`python.exe`, for `sbdf_export.py`). `scripts/sfenv.py` resolves all four.

## Version policy

- Ground truth for what exists and its exact signature: the API index you generate on your own
  machine with `scripts/dump_api.ps1` from your installed Analyst (public members only). The tools
  read the file `SFAPI_INDEX` names, else the newest `$DXP_WORKSPACE/api/spotfire-api-*.json`, and
  query it with `scripts/sfapi.py`. Without an index the member checks are skipped with a warning.
- Descriptions and behavior: the online Spotfire Analyst API reference for your version (one page
  per type and member), plus `spotfire-property-docs.json`, the property documentation embedded in
  Analyst that `dump_api.ps1` writes next to the index.
- How Spotfire persists an object: [dxp-anatomy.md](dxp-anatomy.md).
- Builders target `app.minimumSpotfireVersion` (default 14.6): prefer API members whose
  `[api x.y]` version is <= 14.6. dxpgen and the linter warn on newer members; use them only when
  the feature needs them (and say so in the report). Analyst 15.0 also saves 14.8 and 14.6 copies
  of the document, so a DXP built on 15.0 opens in 14.6.

## Public API only

The builder calls only public members of the Spotfire API, the ones the index lists. The
`settings` escape hatch also sets public properties only. Spotfire 15.0 has no public API for the
items below, so the builder does not create them. Each one becomes a manual step: `dxpgen.py
build` writes it to `build/MANUAL-STEPS-<tier>.md` as one exact Analyst instruction, and the
builder logs it as a `TODO <what>: <how>` line in `build/build-log-<tier>.txt`.

| spec item | what the builder does | what you do in Analyst |
|---|---|---|
| text-area controls (`controls`, `{{control:<id>}}` in the HTML) | puts a visible marker where the control goes: `[Drop-down list: SelectedPumpId]`, `[Button: Reset Filters]` (the slim tier writes `[control: <id>]`) | Edit Text Area, delete the marker and, at that spot, Insert Property Control or Insert Action Control as the step describes (binding, fixed values, script, arguments) |
| property triggers (`triggers`) | adds the script, checks that the property exists | Edit > Document Properties > Properties, select the property, click Script..., select the script |
| action mods (`actionMods`, control `actionMod`, visual `actionTriggers`) | adds the IronPython scripts the spec lists; the buttons are text-area controls (row above), and a button's step names its `script` when the spec gives one | add the action mod (pin or install it, or Tools > Development > Mods development > Connect to file), then wire the buttons and the visual action triggers to it; the `building-action-mods` skill covers action mods |
| document theme (`app.theme`) | writes the custom styles to `build/theme.json` | apply the theme and the custom styles; the `styling-spotfire-dxps` skill covers themes |
| text-area background | leaves Spotfire's default | set it in Analyst when you need it |

The spec format keeps `controls`, `triggers`, `actionMods`, `actionTriggers`, control `actionMod`
and `app.theme`: dxpgen validates them and turns them into manual steps. `verify_dxp.py check`
reports a manual item you have not added yet as WARN and an item you added by hand as PASS or FAIL.
The report tier's `MANUAL-STEPS-report.md` lists the same items under "Add by hand".

Visualization mods are built when `ModManager.GetVisualizationModsIncludingPinned()` (public,
14.5) lists the mod: embedded in the analysis, installed or pinned. Otherwise the builder puts a
placeholder text area `[mod: <id>]` where the visual goes and logs a TODO line. To make a mod
available, pin or install it, or add it once to the starter page of the new analysis before you
run the builder (Tools > Development > Mods development > Connect to file, or drag the `.mod`
file onto the page; this second route is **Not yet tested**).

## Execution model inside Spotfire

- You run the builder as an ordinary script from the script editor with "Execute in transaction"
  unticked. Inside a transaction Spotfire refuses `SaveAs` ("document is not idle").
- `finish()` writes the log, then saves inside the script. When Spotfire refuses that save, the
  builder queues it with `ApplicationThread.InvokeAsynchronously` (retried while Spotfire is not
  idle), and the log says to use File > Save As and names what to re-check afterwards (the markings
  and the description: closing the Document Properties dialog can reset them). Queued calls from
  the script editor did not run in live tests on Analyst 15.0, so the inline save comes first.
- Build session switch (apps with features, after a successful inline save only): the builder adds
  a "Build Session" page and saves the open analysis once more to
  `build/session/~build-session-<tier>.dxp`. The open analysis is then linked to that scratch file,
  not to the saved DXP, so a later Ctrl+S cannot overwrite the good file with the copy whose
  markings the dialog reset. Close it without saving and open the saved DXP.
- Analyst opens the script editor only once the analysis has data, so the builder runs in a new
  analysis with starter data. It refuses a document opened from a file. Starter tables are renamed
  `<name> (starter)` when a spec table has their name and are removed at the end. Apps with mod
  visuals rename the starter pages `<title> (starter)` and remove them only after every page is
  built, so a mod you added on the starter page stays in the analysis.
- Build order of the standard engine (each item its own `ok(...)` step):
  1. checks before any change: the opened-from-file guard and the preflight (every file the
     builder reads exists)
  2. starter tables renamed on a name clash
  3. document properties
  4. tables (embedded), column formats
  5. the default marking, other markings
  6. data functions: register, bind, run; then the formats of their output tables
  7. IronPython scripts
  8. visualization mods: find each one the visuals use
  9. pages, starter pages removed; per page: panels and filtering scheme, visuals (data, axes,
     coloring, reference layers; text areas with markers in place of controls; a placeholder for a
     missing mod), then the layout
  10. active page, hidden pages, starter tables removed and the default table set, filter panel
      layouts, description, keywords, page navigation
  11. one TODO line per manual step, "Built N of M visuals", then `finish()` (log, save)
- The slim and full tiers (`scripts/lib/90_build.py`) run doc.prepare (existing pages, starter
  tables, the theme as a manual step), properties, tables, markings, filtering schemes, data
  functions, table metadata, relations, scripts, pages, triggers (manual steps), doc.finish, then
  `B.finish()` (report, MANUAL-STEPS.md, save, queued snapshots).

## Resolved spec (what the library receives)

dxpgen embeds the spec as a Python literal after resolving it (the standard engine receives
`HOME`, `STYLE` and `APP` instead: [engine.md](engine.md)). Library code may rely on:

| spec field | in the builder |
|---|---|
| `tables[].source.path` | absolute Windows path (file checked to exist at generation time) |
| text area `html` | the final HTML string (file content or inline), placeholders `{{control:<id>}}` intact |
| text area `css` | CSS text or `""` |
| text area `js` | list of `{"name": "<file stem>", "code": "<javascript>"}` |
| `scripts[].code` | IronPython source (from `file` when given); `file` kept for reporting |
| `dataFunctions[].scriptCode` | data-function source (from `script`) |
| `app.theme.customStyles` | dict (from the JSON file when a path was given) or absent; written to `build/theme.json` |
| defaults | every default from [spec-format.md](spec-format.md) filled in explicitly (`showTitle`, `legend`, `marking`, `embed`, ...) |
| `marking` on visuals | the marking name, or `None` when the spec said `null` |

The generated library builder ends with:

```python
SPEC = {...}                      # resolved spec, Python literal
APP_DIR = r"<absolute path of the app folder>"
B = BuildContext(SPEC, APP_DIR, Document, Application, "<sha256 spec.json>", "<sha256 lib>")
run_build()
```

## Library (`scripts/lib/`, IronPython 3.4, concatenated in file-name order)

| file | owns | key functions |
|---|---|---|
| `00_core.py` | BuildContext `B`, steps and report, value conversion, the settings escape hatch (public properties only), the finish (inline save, else queued) | `B.step`, `B.fallback`, `B.warn`, `color`, `enum_value`, `esc`, `apply_settings`, `B.finish` |
| `10_document.py` | page cleanup, theme (writes `build/theme.json`, records the manual step), navigation, canvas, description | `doc_prepare`, `doc_apply_theme`, `doc_finish` |
| `20_data.py` | tables, embedding, columns, relations, markings, filtering schemes, document properties | `data_add_properties`, `data_load_tables`, `data_table_metadata`, `data_relations`, `data_markings`, `data_filtering_schemes` |
| `30_datafunctions.py` | data-function registration, bindings, execution | `df_build_all` |
| `40_scripts.py` | IronPython scripts, JavaScript, property triggers (manual steps) | `scripts_add_all`, `scripts_add_triggers`, `script_def` |
| `50_pages.py` | pages, panels, layout tree | `pages_create`, `page_apply_layout` |
| `60_charts.py` | chart visuals and axes | `vis_line`, `vis_bar`, `vis_combination`, `vis_scatter`, `vis_scatter3d`, `vis_pie`, `vis_box`, `vis_heatmap`, `vis_treemap`, `vis_waterfall`, `vis_histogram` |
| `65_coloring.py` | coloring, reference layers, fitting models | `apply_coloring`, `apply_reference_layers`, `apply_fitting_models` |
| `70_tables.py` | table, cross table, summary table, graphical table, KPI chart | `vis_table`, `vis_crosstable`, `vis_summary`, `vis_graphical`, `vis_kpi` |
| `75_maps.py` | map chart and layers | `vis_map` |
| `80_textareas.py` | HTML text areas, CSS injection, JavaScript; a `[control: <id>]` marker and a manual step per control | `vis_textarea` |
| `85_mods.py` | visualization mods (embedded, installed or pinned; else a placeholder) | `vis_mod` |
| `90_build.py` | dispatcher and build order | `VISUAL_BUILDERS`, `run_build(spec)` |

Each module lists the Spotfire members it uses in `<module>.members.txt` (and the assigned ones in
`<module>.set.txt`); `sfapi.py has` checks them against the index.

Module rules:
- Top-level names are unique across all modules (they share one file). Private helpers start
  with `_<module>_`, for example `_data_find_table`.
- Imports at the top of each module are allowed (duplicates are harmless).
- Every public builder function takes the spec dict for its object and returns the created
  object; it records what it made in `B.created` (see Build outputs).
- Visual builders have the signature `vis_xxx(page, vspec)` and return the `Visual` (wrapper),
  after the common settings (`title`, `showTitle`, `description`, `table`, `marking`,
  `limitByMarkings`, `limitExpression`, `useFiltering`, `legend`, `settings`, `postScript`) were
  applied by `vis_common(visual, content, vspec)` from `60_charts.py`.
- No `print`. Diagnostics go into the report. No f-strings, walrus, annotations or tabs.
- Look names up through `B` (`B.table(name)`, `B.prop(name)`, `B.script(name)`,
  `B.marking(name)`, `B.page(title)`, `B.visual(id)`), never by iterating ad hoc.

## Build outputs

- `build/MANUAL-STEPS-<tier>.md` (written by `dxpgen.py build`): one numbered instruction per item
  the public API cannot build, in build order (controls page by page, action triggers, property
  triggers, action mods, theme). "Nothing to add by hand" when there are none.
- `build/theme.json`: the `app.theme` custom styles with `general.baseTheme` and
  `general.baseThemeSfx` set to `app.theme.base`.
- `build/build-log-<tier>.txt` (standard engine): the first line is "No problems." or "N
  problem(s), the build went on:" (apps with features prefix the spec hash and release), then
  `FAILED <step>: <why>`, `TODO <what>: <how>`, `NOTE ...`, `Saved <path>`, the refused-save line
  with what to re-check after File > Save As, and "Built N of M visuals on P page(s)."
- Report tier: `build-report-report.json` (`app`, `tier`, `spotfire`, `status`, `counts`, `saved`,
  `output`, `files`, `pages`, `visuals`, `snapshots`, `log`, `steps`), `MANUAL-STEPS-report.md`
  ("Fix in Analyst": each failed step with its fix and error; "Add by hand": every TODO item;
  "Optional: snapshots") and `snapshots-report/`.
- Slim and full tiers: `build-report.json`, `MANUAL-STEPS.md` (every fallback) and `snapshots/`:

```json
{
  "app": "Pump Station Monitor", "spec": "<sha256 of spec.json>", "builder": "<sha256>",
  "spotfire": "71.0.22206.3863", "started": "...", "finished": "...",
  "status": "ok | ok-with-fallbacks | errors",
  "steps": [{"group": "tables", "name": "load", "target": "PUMP_DATA", "status": "ok|failed|fallback|skipped",
             "seconds": 0.4, "message": "", "traceback": ""}],
  "fallbacks": [{"feature": "pages.textArea.control", "target": "controlPanel/pumpSelect",
                 "reason": "Spotfire 15.0 has no public API for text-area controls",
                 "manual": "In text area ...: Edit Text Area, delete the [control: pumpSelect] marker and, at that spot, ..."}],
  "warnings": ["..."],
  "created": {"pages": {}, "visuals": {}, "controls": {}, "tables": {}, "properties": {},
              "scripts": {}, "dataFunctions": {}, "document": {}, "theme": {}, "layouts": {}, "mods": {}},
  "output": "<app folder>/build/Pump Station Monitor.dxp", "saved": true,
  "snapshots": ["p01-page-Fleet Overview.png", "..."]
}
```

JavaScript definitions are recorded under `created.scripts` with language `JavaScript` (key
`<name> [JavaScript]` when an IronPython script has the same name). Mod visuals that could not be
added are recorded in `created.mods[id]` with `placeholder: true`. `verify_dxp.py` maps spec ids
to saved objects through `created` when the file exists, else by title and type.

## Rules the tools enforce

| rule | contract | checked by |
|---|---|---|
| Customer-ready text | visible text = error, embedded code = warning (`app.textLint`, `app.bannedTerms`) | `scripts/textlint.py` via `validate` |
| Date reference lines | value = a DateTime property or a date expression; no DateAdd / AddDays over a non-date property | `Validator.v_reference_types` |
| Marker aggregation | label, size, line order, rotation aggregated unless marker-by has `baserowid()` | `Validator.v_marker_aggregation`, `verify_dxp.py` |
| Filter panel per page | every page shows the tables and columns a user needs there: the page's own `filters` or the top-level `filterPanelLayout` ([spec-format.md](spec-format.md) "Filter panel"); ids, keys, coordinates, geometry and calculation-only columns hidden; `"filters": "all"` only on purpose | `Validator.v_filter_layouts` (unknown tables, columns, types = errors; a page without a layout in an app with 2+ tables = warning), `verify_dxp.py` area "Filter panels" |
| No styling of the filter panel or the data canvas | no CSS, theme rule or custom style targets the Filters panel or the data canvas; both keep Spotfire's own look | review |

The app design rules (page structure, scenarios, KPI bands as HTML, controls next to the visuals
they drive) are in the `spotfire-app-design-rules` skill.

## Tools (`scripts/`; CPython 3.10 or newer unless noted)

| tool | does |
|---|---|
| `scripts/sfapi.py` | query the API index (`type`, `search`, `has`, `chain`, `enum`, `ns`) |
| `scripts/dump_api.ps1` | write the index (public members) and the property docs from your installed Analyst (PowerShell) |
| `scripts/sfenv.py` | resolve `DXP_WORKSPACE`, `SFAPI_INDEX`, `SPOTFIRE_HOME`, `SPOTFIRE_PYTHON` |
| `scripts/dxpgen.py` | `new <AppSlug>` (scaffold), `validate`, `build [--tier standard\|quick\|compact\|report\|slim\|full] [--clipboard]` (also writes MANUAL-STEPS and theme.json), `release --version vX.Y`, `verify` |
| `scripts/textlint.py` | the customer-ready text check `validate` runs: default banned-term rules, scopes (visible, name, code), Python / JavaScript / HTML segmenters |
| `scripts/sfexpr.py` | expression readers shared by dxpgen and verify_dxp: raw column refs, marker aggregation, value kinds of reference lines |
| `scripts/t3/` | the standard engine's generator: per-kind converters (`<kind>.py`), house style, STYLE/APP, manual steps (`_manual.py`), assembly and tier stripping (`t3.generate`) |
| `scripts/engine/` | the standard engine's IronPython parts (core, builders, features, report add-on) |
| `scripts/ipy_parse.ps1` | compile a builder with Spotfire's own IronPython 3.4 (PowerShell, needs `SPOTFIRE_HOME`; prints PARSE OK) |
| `scripts/slim_builder.py` | `<app> [--tag T] [--out F]`: builder with only the library code the spec reaches (call graph + feature gates, stubs for gated names), no docstrings or comments, lines <= 79, ASCII |
| `scripts/lint_ipy.py` | IronPython 3.4 lint: syntax subset, no print or tabs, API members against the index, version level |
| `scripts/verify_dxp.py` | `check`: read the saved DXP and compare it with the spec, hygiene checks; `dump`: JSON model of a DXP (needs `lxml`) |
| `scripts/sfgraph.py` | reader of the `AnalysisDocument.xml` object graph, used by verify_dxp (needs `lxml`) |
| `scripts/sbdf_export.py` | run with Spotfire's Python (`SPOTFIRE_PYTHON`): CSV / Parquet / pickle to SBDF with exact types |
| `scripts/sf_sanitize.ps1` | run Spotfire's own text-area HTML sanitizer on an HTML file (PowerShell, needs `SPOTFIRE_HOME`) |

## Naming (`app.namingPolicy`, default `program`)

| object | `program` policy | `camelCase` policy |
|---|---|---|
| document properties | PascalCase, no spaces, no type prefix (`SelectedPumpId`) | camelCase (`selectedPumpId`) |
| data functions, scripts | Title Case "Verb + Object" (`Calculate Pump Curves`) | camelCase |
| tables | `UPPER_SNAKE_CASE` | lower or camelCase |
| columns | Title Case with units in parentheses (`Flow Rate (bbl/d)`) | as data arrives |
| pages, markings, filtering schemes | Title Case, no numbering, never `Marking (2)` | same |

Always: one name per binding across layers (property = data-function parameter = control
binding = script lookup); no auto-generated names (`(2)`, `Untitled`); built-in properties
(`MaxMissingTimeParts`, `FiscalYearOffset`, ...) are exempt.

## HTML policy

`htmlMode: "safe"` (default): HTML must survive Spotfire 15.0's default sanitizer. No `<style>`,
`<script>`, `<details>`, `<button>`, `<input>`, `<select>`, `<svg>`, `<section>`; inline styles
only with plain values (no `var()`, `calc()`, `url()`, gradients); CSS that needs selectors is
injected by JavaScript into `#style-container`. `dxpgen.py validate` checks every text area with
its emulation of Spotfire's default sanitizer (allowlist and rules) and fails validation when the
sanitizer would remove content (`--no-sanitize` skips the check). `scripts/sf_sanitize.ps1` runs
Spotfire's own sanitizer on an HTML file when you need its exact output. `rich` skips the check.
