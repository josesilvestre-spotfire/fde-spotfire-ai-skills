# App spec v1 (normative)

The app spec is the single source of truth for one Spotfire analysis. You write it from the
prototype or brief (Shiny, Plotly, Streamlit, Quarto, HTML), `scripts/dxpgen.py` validates it and
turns it into a builder script, you run the builder in Spotfire Analyst, and
`scripts/verify_dxp.py` checks the saved DXP against it.

- Format: JSON, file `spec.json` in the app folder (`$DXP_WORKSPACE/apps/<AppSlug>/`). Comments are
  not allowed.
- Paths are relative to the app folder. dxpgen inlines file contents (HTML, CSS, JS, scripts,
  data-function code) into the builder or has the builder read them from the app folder, and
  resolves data paths.
- Expressions are Spotfire expressions, written exactly as Spotfire stores them
  (`Avg([Discharge Pressure (psig)])`, `<[Station]>`, `[Axis.X]`).
- Names are exact. dxpgen checks them against `app.namingPolicy` ([architecture.md](architecture.md),
  Naming).
- Colors are `#RRGGBB` or `#AARRGGBB`.
- Fields marked (required) must be present; everything else has the default shown.
- `settings` is an escape hatch on any object that maps to a Spotfire node: a dict of
  dotted public-API property paths to values (see "Escape hatches").
- Some items have no public API: text-area controls, property triggers, action mods (their buttons
  and visual action triggers) and `app.theme`. The spec keeps them, dxpgen validates them, and
  `dxpgen.py build` turns each into one manual step (see "Manual steps").

## Top level

```json
{
  "specVersion": 1,
  "app": {},
  "tables": [],
  "defaultTable": null,
  "relations": [],
  "markings": [],
  "filteringSchemes": [],
  "properties": [],
  "dataFunctions": [],
  "scripts": [],
  "triggers": [],
  "actionMods": [],
  "vizMods": [],
  "filterPanelLayout": null,
  "pages": [],
  "activePage": null
}
```

`filterPanelLayout`: the filter panel organization of every page that has no `filters` of its own
(see "Filter panel").

`vizMods`: the visualization mods that `mod` visuals use in the standard engine, each with its
project folder (see "Visualization mods").

`triggers` and `actionMods`: validated, then manual steps (see "triggers" and "Action mods").

## app

| field | default | meaning |
|---|---|---|
| `name` (required) | | Analysis name; default output file name |
| `description` | `""` | `Document.Properties.Description` |
| `keywords` | `[]` | `Document.Properties.Keywords` |
| `output` | `"build/<name>.dxp"` | Where the builder saves the analysis. The tier is added to the file name: `build/<name> <tier>.dxp` |
| `namingPolicy` | `"program"` | `"program"` (the default naming standard) or `"camelCase"` |
| `htmlMode` | `"safe"` | `"safe"`: text-area HTML must survive Spotfire's default sanitizer. `"rich"`: allow `<style>` and other non-allowlisted markup; it renders as written only where the sanitizer is off (servers sanitize text-area HTML by default; dxpgen warns) |
| `theme` | absent | `base`: `LightSfx`, `DarkSfx`, `Light`, `Dark`. Optional `customStyles`: theme-editor JSON object or a path to a `.json` file; `base` overrides `customStyles.general.baseTheme` (dxpgen warns when they differ). **Manual step**: no public API sets the document theme. dxpgen validates the field, writes the custom styles to `build/theme.json` and adds the theme to MANUAL-STEPS; the `styling-spotfire-dxps` skill covers themes |
| `pageNavigation` | `"Tabs"` | `Tabs`, `Links`, `None`, `Off` |
| `canvas` | `null` | `{"width": 1920, "height": 1080, "fitToWindow": true}` for a fixed visualization area |
| `snapshots` | `{"enabled": true, "width": 1600, "height": 900}` | PNG renders of every page and visual after the build |
| `minimumSpotfireVersion` | `"14.6"` | Oldest Analyst the builder must run on. dxpgen warns about API members newer than this |
| `style` | `null` | Style layer of the standard engine (palette, font, number formats, per-kind visual defaults); see "app.style". The library tiers (slim, full) ignore it |
| `textLint` | `{"visible": "error", "code": "warning", "allow": []}` | Levels of the customer-ready text check of `dxpgen validate` (`scripts/textlint.py`): `visible` = titles, descriptions, labels, HTML text, property defaults, value lists, object names, action-mod and visualization-mod manifest texts; `code` = comments, docstrings and strings of embedded code and HTML comments; each `error`, `warning` or `off`. `allow`: rule ids this app accepts (`release-tag`, `version-tag`, `verbatim`, `legacy`, `prototype`, `dev-note`, `assistant`, `skill`, `tool-name`, `builder`, `property-name`). Validate-only: never reaches the builder |
| `bannedTerms` | `[]` | Extra terms this app must not show, usually person names and codenames: plain text matches a whole word, case-insensitive; `"re:<regex>"` is a regular expression. Checked like the default rules; validate-only |

## tables

```json
{
  "name": "PUMP_DATA",
  "source": {"type": "sbdf", "path": "data/PUMP_DATA.sbdf"},
  "description": "One row per pump per hour.",
  "columns": {"Flow Rate (bbl/d)": {"description": "Metered flow", "format": "#,##0.0"}},
  "calculatedColumns": [
    {"name": "Head (ft)", "expression": "[Discharge Pressure (psig)] * 2.31 / [Specific Gravity]",
     "description": "Pump head from discharge pressure"}
  ],
  "hierarchies": [{"name": "Asset", "levels": ["Region", "Station", "Pump ID"]}],
  "embed": true
}
```

Source types:

| `type` | fields | notes |
|---|---|---|
| `sbdf` | `path` | Preferred. Write SBDF with `scripts/sbdf_export.py` (Spotfire's own Python, `SPOTFIRE_PYTHON`, exact column types) |
| `csv` | `path`, `separator` (`","`), `culture` (`"en-US"`), `encoding` (`"utf-8"`), `header` (`true`), `columns` ({name: DataType}) | Every column type should be listed; unlisted columns are typed by Spotfire |
| `dataFunction` | `function`, `output` | The table is created by that data function's output; this entry only carries metadata (description, columns, calculated columns) applied after the function runs |

`embed: true` stores the data inside the DXP (no link to the local file). Linked tables are not
allowed in a published app. `settings` on a table (relative to the `DataTable`) and on a column
entry (`columns[name].settings`, relative to the `DataColumn`) use the escape hatch below.

An embedded file table still keeps its source's `FilePath` in the DXP (a local path that can
contain the user name), and a stream source keeps the temp file it spools to instead. The standard
engine loads the `sbdf` tables of every app that uses any feature by file name, with the current
folder set to the file's folder for the load (`scripts/engine/features/pathfree.py`), so the DXP
keeps only `NAME.sbdf`. The build log has one `NOTE <table>: the DXP keeps the source path '...'`
line per table, and a NOTE with the reason when it had to fall back to the full path
(**Not yet tested**). Apps without features (the well tear sheet example) keep the full path.

DataType names: `String`, `Integer`, `LongInteger`, `Real`, `SingleReal`, `Currency`, `Date`,
`DateTime`, `Time`, `TimeSpan`, `Boolean`, `Binary`.

## relations, markings, filteringSchemes

```json
"relations": [
  {"left": "PUMP_DATA", "right": "PUMP_CURVES", "on": [["Pump ID", "Pump ID"]]}
],
"markings": [
  {"name": "Selected Pump", "color": "#E94165", "default": true}
],
"filteringSchemes": [
  {"name": "Fleet Filters", "default": false}
]
```

- `on` lists `[leftColumn, rightColumn]` pairs joined with `and`.
- At most one marking may be `default`; with several and none marked, the first is the default
  (warning). The default marking becomes `Markings.DefaultMarkingReference` and the marking every
  visual uses unless the visual says otherwise. With no markings, the document's built-in marking
  is renamed `Marking` and kept as default.
- The default filtering scheme always exists; `filteringSchemes` adds named ones. `default: true`
  (at most one) renames the built-in default scheme to that name.

## properties (document properties)

```json
{"name": "SelectedPumpId", "type": "String", "default": "P-101",
 "description": "Pump shown on the detail page", "listValued": false}
```

- Names: letters and digits only, dot-separated segments allowed (Spotfire rule). Case-insensitive
  in Spotfire, so two names that differ only in case are an error.
- `default` must match the type exactly: Real `72.0`, Integer `5`, Boolean `true`,
  Date/DateTime ISO `"2025-01-31"` / `"2025-01-31T08:00:00"`, TimeSpan `"01:30:00"`.
- `listValued: true` makes a list property (`default` is a JSON array), needed by multi-select
  list boxes.

## dataFunctions

```json
{
  "name": "Calculate Pump Curves",
  "description": "Fits head-flow curves per pump.",
  "engine": "python",
  "script": "datafunctions/calculate_pump_curves.py",
  "inputs": [
    {"name": "PUMP_DATA", "type": "table", "bind": {"table": "PUMP_DATA", "columns": "*",
      "limitByFiltering": null, "limitByMarking": null}},
    {"name": "flowRate", "type": "column", "bind": {"table": "PUMP_DATA", "column": "Flow Rate (bbl/d)"}},
    {"name": "SelectedPumpId", "type": "value", "dataTypes": ["String"], "bind": {"property": "SelectedPumpId"}},
    {"name": "minPoints", "type": "value", "dataTypes": ["Integer"], "bind": {"value": 20}},
    {"name": "maxFlow", "type": "value", "dataTypes": ["Real"], "bind": {"expression": "Max([PUMP_DATA].[Flow Rate (bbl/d)])"}}
  ],
  "outputs": [
    {"name": "PUMP_CURVES", "type": "table", "target": {"table": "PUMP_CURVES"}},
    {"name": "OutR2", "type": "value", "target": {"property": "OutR2"}}
  ],
  "refresh": "automatic",
  "executeAtBuild": true
}
```

- `engine`: `python` (Spotfire Python data function) or `terr`.
- Input `type`: `table`, `column`, `value`. Output `type`: `table`, `value`
  (`columns` outputs are not in v1).
- A `value` input/output bound to a property must have the same name as the property
  (the one-name-per-binding rule; dxpgen enforces it).
- `executeAtBuild: true` runs the function synchronously during the build so its output tables
  exist before visuals are bound to them. Visuals may only reference data-function output tables
  whose function has `executeAtBuild: true`.
- Every registered output must be assigned by the script (dxpgen checks the script text).
- `limitByMarking` (a marking name) on a `table` or `column` input: the function gets only the rows
  marked in that marking (`DataFunctionInputCollection.SetInput(param, expression, False,
  [marking])`), and an `automatic` function re-runs on every marking change. Nothing is marked
  during the build, so a function with `executeAtBuild: true` runs on an empty table then and must
  still return typed outputs. Spotfire has no "when nothing is marked" option on inputs. An
  automatic function must never read a property it writes (directly or through another function):
  Spotfire then reports cyclic dependencies and switches it to manual. To copy a marked window into
  properties the user can also type, write one String property from the function and copy it on
  with a property trigger (pattern below; the trigger is a manual step). The standard engine builds
  `limitByMarking` on table and column binds (not on property, expression or literal binds);
  `limitByFiltering` needs the slim tier.

```json
{"name": "Track Marked Window", "script": "datafunctions/track_marked_window.py",
 "inputs": [{"name": "MarkedRows", "type": "table",
             "bind": {"table": "PUMP_READINGS", "columns": ["Timestamp", "Pump ID"],
                      "limitByMarking": "Label Window"}},
            {"name": "LabelPump", "type": "value", "dataTypes": ["String"],
             "bind": {"property": "LabelPump"}}],
 "outputs": [{"name": "MarkedWindow", "type": "value", "target": {"property": "MarkedWindow"}}],
 "refresh": "automatic", "executeAtBuild": true}
```

## scripts (IronPython)

```json
{"name": "Reset All Filters", "description": "Clears every filter on the page.",
 "file": "scripts/reset_all_filters.py",
 "parameters": [{"name": "page", "type": "Page", "description": "Page to reset"}],
 "transaction": true}
```

- `file` or `code` (inline string). Language is IronPython 3 (Python 3.4 syntax: no f-strings,
  no walrus, no annotations; no `print`, see the `writing-spotfire-ironpython` skill).
- Parameter types: `String`, `Integer`, `LongInteger`, `Real`, `SingleReal`, `Boolean`, `Date`,
  `DateTime`, `Time`, `TimeSpan`, `Currency`, `Page`, `Visualization`, `DataTable`.
- `transaction` defaults to `true` (as scripts made in Analyst).
- dxpgen lints every API member the script uses against your API index (`SFAPI_INDEX`, else the
  newest `$DXP_WORKSPACE/api/spotfire-api-*.json`); without an index the member check is skipped
  with a warning.

## triggers

```json
"triggers": [{"property": "MarkedWindow", "script": "Apply Marked Window"}]
```

A property trigger runs the script whenever the document property changes, whatever changed it (a
control, a script, a data-function output). One script per property; a trigger passes no
arguments.

**Manual step.** Spotfire 15.0 has no public API that adds a property trigger, so the builder does
not create it. dxpgen validates each entry: the property and the script exist (errors), one trigger
per property (error), a script that declares parameters (warning). The builder still adds the
script itself; the standard engine logs `TODO trigger <property> -> <script>: ...`, and
`build/MANUAL-STEPS-<tier>.md` says: "Edit > Document Properties > Properties, select the document
property, click Script..., choose to run a script when the value changes, select the script and
click OK". `verify_dxp.py check` reports a trigger not added yet as WARN, and checks a trigger added
by hand (property, script) as PASS or FAIL. Spotfire runs property triggers only where the license
feature "Spotfire Enterprise Player" is on; Analyst has it (**Not yet tested** for consumer and Web
Player groups). [api-scripts.md](api-scripts.md) R4 has the trigger behaviour.

## pages

```json
{
  "title": "Fleet Overview",
  "visible": true,
  "filterPanel": false,
  "detailsOnDemand": false,
  "filteringScheme": null,
  "filters": null,
  "visuals": [],
  "layout": {}
}
```

- `filterPanel` (boolean): whether the Filters panel is shown when the page opens. `filters`: which
  tables and columns that panel lists, `{"tables": [...]}` or `"all"`; absent = the top-level
  `filterPanelLayout` (see "Filter panel"). The two are independent: a hidden panel still gets its
  organization, for the user who opens it.
- `title` is a preprocessor expression like visual titles: `${...}` is live, write `\${` for a
  literal. Page titles are unique case-insensitively.
- `filteringScheme`: name from `filteringSchemes`; null = the default scheme.
- `layout` (required when there is more than one visual) is a tree:
  `{"row": [items]}` places items left to right, `{"column": [items]}` top to bottom.
  An item is `{"visual": "<id>", "weight": 20}` or a nested `row`/`column` with its own `weight`.
  Weights are relative within their parent (default 1). Nested containers must alternate
  orientation. Every visual on the page appears exactly once.

```json
"layout": {"row": [
  {"visual": "controls", "weight": 18},
  {"column": [
    {"visual": "trend", "weight": 60},
    {"row": [{"visual": "byPump"}, {"visual": "events"}], "weight": 40}
  ], "weight": 82}
]}
```

## Filter panel (standard engine)

Every page organizes its filter panel so a user sees only the tables and columns that matter on that
page (a rule of the `spotfire-app-design-rules` skill). The panel is not styled: it keeps Spotfire's
own look (no CSS, no theme rules for it), and neither is the data canvas.

```json
"filterPanelLayout": {"tables": [
  {"table": "WELL_HEADER", "columns": ["Well Name", "Region", "Rig", "Spud Date"],
   "filterTypes": {"Well Name": "ListBoxFilter", "Spud Date": "RangeFilter"}},
  {"table": "WELL_DAILY", "expanded": false, "columns": ["Well Name", "Report Date"],
   "subGroups": [{"name": "Rig parameters", "expanded": false,
                  "columns": ["ROP (ft/h)", "WOB (klbf)", "RPM", "Torque (kft-lbf)"]},
                 {"name": "Circulation", "columns": ["SPP (psi)", "Flow Rate (gpm)"]}]}
]},

"pages": [
  {"title": "Fleet Overview", "visuals": [], "layout": {}},
  {"title": "Well Detail", "filters": {"tables": [
     {"table": "WELL_DAILY", "columns": ["Report Date", "Depth (ft)"],
      "filterTypes": {"Report Date": "RangeFilter"}}]}, "visuals": [], "layout": {}},
  {"title": "Data Generation", "filters": {"tables": []}, "visuals": [], "layout": {}},
  {"title": "Data Audit", "filters": "all", "visuals": [], "layout": {}}
]
```

| field | default | meaning |
|---|---|---|
| top-level `filterPanelLayout` | `null` | the layout of every page without its own `filters` (null = none) |
| page `filters` | `null` | the page's own layout; `"all"` keeps Spotfire's default panel (every table and column) on purpose; absent or null = `filterPanelLayout`; `{"tables": []}` hides every table (a page with nothing to filter) |
| `tables` (required) | | the tables the panel lists, top to bottom. **Every table not listed is hidden** (`TableGroup.Visible = False`) |
| `tables[].table` (required) | | a table of the spec: an sbdf table, or a data-function output table whose function has `executeAtBuild: true` |
| `tables[].columns` | `[]` | the filters shown at the top level of the table, in this order, or `"*"` (every column not in a sub group, in Spotfire's order). **Every column not listed is hidden** (`FilterHandle.Visible = False`; never removed, so it cannot come back on its own) |
| `tables[].expanded` | `true` | whether the table's group starts expanded |
| `tables[].subGroups` | `[]` | named groups shown after the top-level columns, in this order: `{"name", "columns" (required, in order), "expanded" (default true)}`. Names are unique per table (Spotfire refuses a second one) |
| `tables[].filterTypes` | `{}` | `{column: type}` with type `CheckBoxFilter`, `ListBoxFilter`, `RadioButtonFilter`, `RangeFilter` (number, date and time columns only), `TextFilter` or `ItemFilter`. Unlisted columns keep Spotfire's choice (range for numbers and dates, check boxes or a list box for text) |

Rules `dxpgen validate` enforces (errors): known tables built before the pages; columns spelled
exactly as the table has them (the builder finds filters by exact name): for an sbdf table its
file's columns, for a data-function table **the columns declared in the `columns` of its top-level
`tables[]` entry** (declare every column a layout names there; a description is enough; its filter
types are not type-checked); no Binary columns (Spotfire has no filter for them); a column in one
place only (the top level or one sub group); a table entry that shows at least one filter; a known
filter type, `RangeFilter` not on a String or Boolean column; and **one type per column in the whole
app**: a filter type belongs to the filtering scheme, which every page shares, so two pages cannot
give a column different types. Design rule (warning): in an app with two or more tables, a page with
no layout (neither its own `filters` nor `filterPanelLayout`) is warned; `"filters": "all"` turns
that into a note. A top-level `filterPanelLayout` that no page uses (every page has its own
`filters` or `"all"`) is warned too: the builder ignores it, its `filterTypes` included.

What the builder does (`scripts/engine/features/filterpanel.py`, after the starter tables are
removed so every data-function table has its group): per page and listed table, in its own step:
the sub groups are made and their columns moved into them, the listed columns are shown and every
other column hidden, the items are put in the listed order (columns, then sub groups) and the group
moved to its place; then every table not listed is hidden; one `OK filters <page>: ...` log line per
page (NOTE when a step failed or a column was left out). A listed column the table does not have
when the builder runs (a data function that did not return it) is left out with a
`NOTE filters <table>: no column ...` line and the rest of the table is still organized (verify_dxp
then FAILs that table's filter list). Filter types are set once per column on the default filtering
scheme. Spotfire keeps one `TableGroup` per table per page, and a filter with no handle anywhere in
its table group is added back at the top level when the table's filters change
(`TableGroup.AutoSynchronizeFilters`), which is why columns are hidden and never removed;
`FilterGroup.Add` appends a new handle, `Remove` drops that group's handle. The slim and full tiers
do not build layouts (dxpgen leaves them out of their builders and says so). `verify_dxp` reads every
page's `TableGroup` / `FilterHandle` / `FilterSubGroup` visibility, order, expanded state and filter
type from the saved DXP and reports a PASS or FAIL line per item (area "Filter panels").

Choosing what to show: the columns a user would slice the page by (asset, region, status, date, a
few key measures), never ids, technical keys, coordinates, geometry, sort helpers or columns that
only feed calculations; the page's main table first; the tables of a data-generation page hidden on
the operator pages. **Not yet tested**: the filter panel layouts in a live build
([live-test-status.md](live-test-status.md)), including that the organization survives a data
function re-run that replaces its output table (Spotfire keeps column identity on a replace with the
same column names; a renamed column would come back visible at the top level).

## Visuals: common fields

| field | default | meaning |
|---|---|---|
| `id` (required) | | Unique across the app; used by layout, controls and the verifier |
| `type` (required) | | One of the types below |
| `title` | `""` | Visual title. `${...}` is live Spotfire syntax; write `\${` for a literal |
| `showTitle` | `true` | |
| `description` | `""` | |
| `table` | `defaultTable` | Data table |
| `marking` | default marking | Marking name, or `null` for "cannot be marked". Spotfire leaves new KPI charts and cross tables unmarked; the standard engine gives them the default marking explicitly in apps with features (an explicit default marking works too) |
| `limitByMarkings` | `[]` | Markings that limit the data shown |
| `emptyMarkingBehavior` | `"ShowAll"` | `ShowAll`, `ShowEmpty`, `ShowMessage` when `limitByMarkings` is set |
| `limitExpression` | `null` | Boolean expression limiting the rows (Limit data using expression) |
| `useFiltering` | `true` | Follow the page's filtering scheme |
| `legend` | `{"visible": true}` | Legend visibility; `"hide"`: legend items to hide, among `filtering`, `marking`, `lineBy`, `colorBy`, `referenceLayers` (also lines and curves), `trellis` (standard engine). On a map `hide` applies to every data layer's own legend and also accepts `markerBy`, `shape`, `size`, `rotation`, `limits` (Data limiting), `dataTable`, `layerTitle` (not `referenceLayers`); see Maps |
| `coloring` | `null` | See Coloring |
| `referenceLayers` | `[]` | See Reference layers (line, bar, scatter, combination charts) |
| `fittingModels` | `[]` | See Fitting models |
| `settings` | `{}` | Escape hatch: public property paths to values |
| `postScript` | `null` | Escape hatch: IronPython run after the visual is built, with `visual`, `content`, `Document` in scope |
| `actionTriggers` | `[]` | Buttons and menu items on the visual that run an action-mod script, `[{display, actionMod, label}]` (see "Action mods"). Validated, then a manual step |

## Visual types

Each axis value is an expression string. Lists mean several columns on one axis.

| `type` | fields |
|---|---|
| `lineChart` | `x`, `y` (string or list), `colorBy`, `lineBy`, `trellis`, `xScale`, `yScale`, `showMarkers`, `lineWidth`, `steps` |
| `barChart` | `x` (category), `y` (value, string or list), `colorBy`, `orientation` (`vertical`/`horizontal`), `stack` (`stacked`/`sideBySide`/`percent`), `sort` (`none`/`ascending`/`descending`), `labels`, `trellis`, `yScale` |
| `combinationChart` | `x`, `series` [{`expression`, `kind`: `bar`/`line`}], `colorBy`, `secondaryScale` (list of expressions on the right axis), `trellis` |
| `scatterPlot` | `x`, `y`, `colorBy`, `sizeBy`, `shapeBy`, `labelBy`, `labels`, `markerSize`, `lineBy` (connect markers), `shape` (default marker: a `MarkerType` member such as `Circle`, `Diamond`, `StarFive`; standard engine), `trellis`, `xScale`, `yScale`. Unless `settings` `MarkerByAxis.Expression` contains `baserowid()` the markers aggregate, so `labelBy`, `sizeBy` and the settings `LabelColumn.Expression`, `SizeAxis.Expression`, `LineConnection.OrderAxis.Expression`, `RotationAxis.Expression` must be aggregated (`First([ID])`, `Avg([Flow])`): a raw one makes the plot show "Please specify an aggregation method." and draw nothing (dxpgen error; x, y and colorBy may stay raw) |
| `scatterPlot3D` | `x`, `y`, `z`, `colorBy`, `sizeBy` |
| `pieChart` | `sector` (category), `size` (value), `labels`, `trellis` |
| `boxPlot` | `x` (category), `y` (value), `colorBy`, `trellis` |
| `heatMap` | `x`, `y`, `value` (cell expression), `coloring` |
| `treemap` | `hierarchy` (list of columns, outer first), `size`, `colorBy` |
| `waterfallChart` | `category`, `value`, `colorBy` |
| `histogram` | `column`, `bins` (default 20), `colorBy`: built as a bar chart on `BinByEvenIntervals` |
| `table` | `columns` (list), `sort` [{`column`, `descending`}], `widths` {column: px}, `coloring` |
| `crossTable` | `rows` (list), `columns` (list), `measures` (list of aggregated expressions), `totals` {`rows`, `columns`: bool}, `coloring` |
| `summaryTable` | `columns` (list), `statistics` (list, e.g. `Avg`, `Min`, `Max`, `Count`) |
| `graphicalTable` | `rows` (category expression), `columns` [{`kind`: `sparkline`/`calculatedValue`/`icon`/`bulletGraph`, `title`, `expression`, ...}] |
| `kpiChart` | `kpis` [{`title`, `value`, `comparative`, `time`, `tileBy`, `coloring`, `format`}] (`format`: standard engine) |
| `map` | `layers` [{`kind`: `tile`/`marker`/`feature`, `table`, `latitude`, `longitude`, `geometry`, `colorBy`, `coloring`, `sizeBy`, `lineBy`, `labelBy`, `labels`, `markerSize`, `shape`, `shapeBy`, `marking`, `limitByMarkings`, `emptyMarkingBehavior`, `limitExpression`, `title`, `settings`}], `autoZoom` (true), `extent`, `interactiveLayer` (see Maps) |
| `textArea` | `html`, `css`, `js`, `controls` (see Text areas) |
| `mod` | `modId`, `axes` {name: expression; `Color` = the mod's color axis; a list = several measures}, `properties` {name: value}, `layers` [{`type`, `title`, `table`, `axes`, `properties`, `marking`, `limitExpression`, `useFiltering`, `limitByMarkings`, `emptyMarkingBehavior`}]. Standard engine: the mod is listed in `vizMods` (see "Visualization mods"). Slim tier: the mod must already be available in Analyst (embedded, installed, pinned or in the library), and `layers` is refused |

Scales: `{"min": null, "max": null, "log": false, "gridlines": true, "individualScaling": false, "title": null}`.
The standard engine builds `min` and `max` (numbers) on both axes of line, bar and scatter charts,
`log` on the y axis and `yScale.individualScaling`: each trellis panel gets its own y scale (each
color without a trellis).
Trellis: `{"panelBy": "<[Station]>"}` or `{"rowsBy": "...", "columnsBy": "..."}`, optional
`"rows"`, `"columns"` for a fixed grid (panelBy only: with rowsBy / columnsBy the categories decide
the grid; dxpgen warns; give both: with only one, Spotfire keeps its own value for the other, dxpgen
warns).

### Trellis (small multiples) in the standard engine

Line, bar and scatter charts take `trellis` (feature `trellis`; the slim tier reads the same field):

```json
{"id": "ropByWell", "type": "lineChart", "title": "ROP by well", "table": "WELL_DAILY",
 "x": "[Depth (ft)]", "y": "Avg([ROP (ft/h)])",
 "trellis": {"panelBy": "<[Well Name]>", "rows": 2, "columns": 4},
 "yScale": {"individualScaling": true},
 "legend": {"visible": true, "hide": ["trellis"]}}

{"id": "nptByPhase", "type": "barChart", "x": "<[NPT Category]>", "y": "Sum([NPT (h)])",
 "trellis": {"columnsBy": "<[Well Name]>", "rowsBy": "<[Phase]>"}}
```

- `panelBy` (one categorical expression; a bare column becomes `<[Col]>`): Panels mode, Spotfire
  wraps the panels; `rows` and `columns` together fix the grid per trellis page (`ManualRowCount`,
  `ManualColumnCount`, `ManualLayout`). `rowsBy` / `columnsBy`: RowsColumns mode, one row / column
  per category.
- `yScale.individualScaling: true`: `YAxis.IndividualScaling` with `IndividualScalingMode.Trellis`
  on a trellised chart (`Color` otherwise), so a low-rate well is not flattened by a high-rate one.
- dxpgen checks the expressions against the table's columns; verify_dxp checks the trellis axes, the
  mode, the fixed grid and the individual scaling.
- Equivalent `settings` recipe (works too, every path is a public 15.0 member; the builder sets the
  paths in sorted order): `{"Trellis.TrellisMode": "Panels", "Trellis.PanelAxis.Expression": "<[Well
  Name]>", "Trellis.ManualRowCount": 2, "Trellis.ManualColumnCount": 4, "Trellis.ManualLayout": true,
  "YAxis.IndividualScaling": true, "YAxis.IndividualScalingMode": "Trellis"}` (RowsColumns:
  `Trellis.RowAxis.Expression`, `Trellis.ColumnAxis.Expression`). Prefer the `trellis` field: its
  columns are validated and verify_dxp checks it.

### Which visual types the standard engine builds

The standard engine builds `textArea`, `kpiChart`, `table`, `crossTable`, `lineChart`, `barChart`,
`scatterPlot`, `map` and `mod` (with its mod listed in `vizMods`). Every other type stops
`dxpgen build` with "visual type '...' is not in the standard engine yet: use --tier slim"; the slim
tier (the library) has builders for them, but it is the exception tier (no filter layouts, about
three times the size, less live evidence). Use these instead:

| wanted | standard engine | how |
|---|---|---|
| heat map (`heatMap`) | no | `crossTable` with a gradient cell coloring (`coloring: {"gradient": [...]}` without `measures`), rows and columns = the two categories; or a `scatterPlot` with `shape: "Square"`, `markerSize` and a gradient color-by |
| pie / donut (`pieChart`) | no | horizontal `barChart` with `sort: "descending"`, or `stack: "percent"` for shares; a share in the KPI band |
| treemap (`treemap`) | no | horizontal sorted `barChart` (one level), or a `crossTable` with a gradient (two levels) |
| combination chart (`combinationChart`) | no | `lineChart` with several `y` measures (one color each), a `barChart` with reference lines, or a bar and a line chart stacked with the same x |
| graphical table (`graphicalTable`) | no | `table` or `crossTable` with cell colorings (status rules, gradients); sparklines as a trellised `lineChart` |
| calculated value miniatures | no | the HTML KPI band of the `spotfire-app-design-rules` skill, or `crossTable` measures with rule colorings |
| box plot, histogram, waterfall, 3D scatter | no | `barChart` on a binned x (`BinByEvenIntervals`), `scatterPlot`, a data function that computes the summary |
| small multiples | yes | `trellis` on line, bar and scatter charts (above) |

## Coloring

```json
{"categorical": {"Running": "#2E8540", "Tripped": "#E94165"}, "default": "#999999"}
{"gradient": [{"at": "min", "color": "#3050EF"}, {"at": "50%", "color": "#FFFFFF"}, {"at": "max", "color": "#E94165"}]}
{"fixed": "#333C66"}
{"rules": [{"type": "greaterThan", "value": 100.0, "color": "#E94165"}]}
```

`colorBy` sets the color expression first; coloring rules are applied after it (Spotfire resets
the rules when the expression changes). Rule types: `greaterThan`, `lessThan`, `between`
(`low`, `high`), `equal`, `top` (`count`), `bottom` (`count`), `expression` (`expression`).
`at` accepts `min`, `max`, `median`, `average`, `NN%` (percent of range) or a number.

Where colorings apply (the standard engine builds all of them):

| visual | coloring |
|---|---|
| line, bar, scatter charts | on the color axis (`colorBy`; a `fixed` color alone colors by (None)). Fixed and plain categorical colorings are set by the chart builder; gradients, rules, `default`, `"(Empty)"` and `settings` go through `scripts/engine/features/coloring.py` |
| map layers | per data layer (see Maps) |
| `table` | cell colorings, one object or a list, each with `columns` (the table columns it colors, sharing one coloring). A coloring that is exactly red negatives becomes the `negatives` style |
| `crossTable` | cell colorings, one object or a list; `measures` names the measures a coloring colors (their alias or the measure expression; an unaliased measure is keyed by its expression without brackets: `Avg([R])` -> `Avg(R)`); without `measures` it is the default numeric coloring (it then replaces the red negatives of the house style) |
| `kpiChart` | `kpis[].coloring`, or the visual-level `coloring` as the default of every KPI; tiles are colored by their final value (`THEN [Y.FinalValue]`) |

- One background (`categorical`, `gradient` or `fixed`); `rules` go above it in spec order (the
  first rule is the top one and wins); `default` colors what no rule or category matches (cells
  without a `default` stay uncolored); `categorical` `default` is a one-color palette for unlisted
  categories; the key `"(Empty)"` is the empty-value color.
- Numbers are typed like the colored values when the color-by is one column of an SBDF table (`5` on
  a Real column is `5.0`); otherwise a whole number is Real (`0` -> `0.0`) for gradients and
  thresholds. `equal` on text is a string rule (`"Critical"`, or `[$Name]` of a String property);
  categorical keys are text unless the column is a known Integer, Real or Boolean column
  (data-function tables: their types are only known after the run, so color categories of a
  data-function table should be String columns).
- `settings` on the coloring object go through the escape hatch (`{"SetColorOnText": true}`,
  `{"EmptyColor": "#FFCCCCCC"}`); `settings` on a rule need the slim tier.
- Colors may carry alpha: `#AARRGGBB` (`"default": "#00000000"` = transparent).

## Reference layers and fitting models

```json
"referenceLayers": [
  {"kind": "horizontalLine", "value": "[$SelectedThreshold]", "color": "#E94165", "dash": "dash", "width": 2, "label": "Alarm"},
  {"kind": "verticalLine", "value": "Date(\"2025-05-31\")", "color": "#666666", "dash": "dot"},
  {"kind": "band", "low": "[P10]", "high": "[P90]", "color": "#333C6633", "table": null}
],
"fittingModels": [
  {"kind": "straightLine", "color": "#3050EF"},
  {"kind": "curve", "expression": "2.31 * [Axis.X]", "color": "#E94165", "label": "Design curve"}
]
```

`value`, `low`, `high` are expressions (constants, `[$Property]` references, aggregations allowed
where Spotfire allows them). `table` draws a band or line from another data table.

A line must evaluate to the type of its axis. On a date axis bind it to a DateTime property that
the script or data function setting the day writes (`[$ViewDate]`, `DocumentProperty("ViewDate")`);
`DateAdd("day", DocumentProperty("ViewDay") - 1, Min([Date]))` over a number property fails in
Spotfire ("Invalid type for function call 'DateAdd'"). `dxpgen validate` stops on DateAdd / AddDays
over a non-date property and on a line whose type differs from its axis (axis type from the data
file, a column `format`, or an aggregation; a column name such as Date or Timestamp gives a
warning).

Fitting models (Lines & Curves) on line, bar and scatter charts: `straightLine` (a least-squares
fit) and `curve` (`expression` in x: `[Axis.X]` is the x value, so `"[Axis.X]"` draws y = x;
`[$Name]` becomes `DocumentProperty("Name")`, retried as `${Name}` when Spotfire rejects it), each
with `color`, `label` and (standard engine) `dash` (`solid`, `dash`, `dot`, `double`) and `width`
(1-10 px). Fitting-model `settings` need the slim tier.

## Maps

```json
{"id": "pipelineMap", "type": "map", "title": "PIPELINE MAP", "table": "PIPELINE_SEGMENTS",
 "marking": "Marking", "extent": {"west": -104.2, "south": 28.0, "east": -94.1, "north": 33.5},
 "layers": [
   {"kind": "tile", "settings": {"Transparency": 0.45}},
   {"kind": "feature", "title": "Solar Radiation", "table": "SOLAR_LAYER",
    "colorBy": "Sum([Solar Radiation (MJ/m2)])", "marking": null,
    "coloring": {"gradient": [{"at": "min", "color": "#9EB6FF"}, {"at": "max", "color": "#FF4E33"}]},
    "settings": {"Enabled": false, "Transparency": 0.71}},
   {"kind": "marker", "title": "Pipeline", "latitude": "[Latitude]", "longitude": "[Longitude]",
    "lineBy": "<[Segment ID]>", "markerSize": 0, "colorBy": "[Map Value]",
    "coloring": {"gradient": [{"at": "min", "color": "#FFF9CF"}, {"at": "median", "color": "#FFDE5C"},
                              {"at": "max", "color": "#DB4D37"}]},
    "settings": {"LineConnection.Width": 4.0, "DrawingOrderAxis.Expression": "[Draw Order]"}},
   {"kind": "marker", "title": "Station Status", "table": "PUMP_STATIONS",
    "latitude": "[Latitude]", "longitude": "[Longitude]", "shape": "StarFive", "markerSize": 3.8,
    "colorBy": "<[Station Status]>", "coloring": {"categorical": {"Running": "#258750", "Stopped": "#C9C9C9"}},
    "labelBy": "Concatenate(First([Station ID]), \" - \", First([Station Status]))",
    "limitExpression": "[In Service] = \"Yes\""}
 ],
 "legend": {"visible": true, "hide": ["filtering", "marking", "markerBy", "lineBy", "shape", "size", "limits"]}}
```

Layers are listed back to front (a tile layer first, or it covers the data). Fields per layer:

| field | layers | meaning |
|---|---|---|
| `kind` (required) | all | `tile` (the reference map), `marker`, `feature` (WKB geometry) |
| `title` | all | layer title; default `Rich reference map` (tile), the table name (data layers) |
| `table` | marker, feature | default: the visual's `table` |
| `latitude`, `longitude` | marker | position expressions (`[Latitude]`, `Avg([Latitude])` with a `MarkerByAxis.Expression` setting); absent: the table's XCenter/YCenter or Latitude/Longitude columns |
| `geometry` | feature | the WKB column (`Geometry`); absent: the column tagged `MapChart.ColumnTypeId = Geometry`, else the column named Geometry. `<...>` = a geometry-by expression (one feature per row by default) |
| `colorBy`, `coloring` | marker, feature | color-by expression and its coloring (see Coloring; a `fixed` color needs no colorBy). The visual-level `coloring` applies to every data layer with a colorBy (a fixed one to every data layer); a layer `coloring` overrides it |
| `sizeBy`, `lineBy` | marker | size expression (aggregated, see below); categorical expression whose markers are joined by one line each (route lines from vertex tables) |
| `labelBy`, `labels`, `markerSize`, `shape`, `shapeBy` | marker | as on scatter plots: label expression (aggregated, see below), `true`/`false`/`all`/`marked`/`none`, marker size in % of the plot (0 hides the vertex markers of a route), default marker shape (a `MarkerType` member: `Circle`, `StarFive`, `Diamond`, ...), categorical shape expression (standard engine) |
| `marking` | marker, feature | a marking name or `null` (cannot be marked); default: the visual's `marking` (standard engine) |
| `limitByMarkings`, `emptyMarkingBehavior`, `limitExpression` | marker, feature | the layer's own data limits (standard engine). The visual-level fields apply to the data layers on the visual's `table` that do not give their own |
| `settings` | all | escape hatch, paths relative to the layer visualization; `Title` and members only the layer has (`Enabled`, `IncludeInAutoZoom`, `Projection`, `VisibleZoomLevelRange`) go to the layer, and every path of a tile layer does. `Enabled: false` = the layer starts switched off; `Transparency` 0..1 (tile: the layer; data layers: the visualization); `LineConnection.Width`, `LineConnection.OrderAxis.Expression`, `DrawingOrderAxis.Expression`, `MarkerByAxis.Expression`, `MaxNumberOfLabels`, `LineFeatureVisualAttributes.LineWidth`, ... |

Map-level fields: `autoZoom` (default true: follow the data), `extent` `{west, south, east, north}`
in degrees (standard engine: the first view, stored as the Web Mercator `ViewExtent`; it switches
AutoZoom off), `interactiveLayer` (standard engine: the title of the data layer that reacts to
clicks and hover; default the top-most enabled data layer), `table` (the visual's table: the trellis
layer is the first enabled data layer on it, and the map's own data follows that layer's table),
`marking`, `legend`, `settings` (relative to the MapChart, e.g. `{"InteractionMode": "Panning",
"MarkingMode": "Lasso"}`).

- **Aggregation rule (proven on Analyst 15.0):** a marker layer whose `MarkerByAxis.Expression` has
  no `baserowid()` (an empty marker-by included) aggregates its markers. Its `labelBy`, `sizeBy` and
  the settings `LabelColumn.Expression`, `SizeAxis.Expression`,
  `LineConnection.OrderAxis.Expression`, `RotationAxis.Expression` must then be aggregated
  (`First([Station Label])`, `UniqueConcatenate(...)`, `Avg([Seq])`); position, color and
  `DrawingOrderAxis.Expression` may stay raw. A raw one raises "Please specify an aggregation
  method." for that layer, and Spotfire then draws nothing on the whole map, tile layer included
  (the issue icon says "Invalid configuration (<layer>)"). dxpgen rejects such a spec (error with
  the fix), verify_dxp FAILs such a DXP. Feature layers are not affected.
- `legend.hide` on a map applies to every data layer's own legend (each layer has one; the map's
  own legend holds only title, description and trellis items, so only `trellis` goes there). Kinds:
  `filtering`, `marking`, `markerBy` (Marker by / Geometry by), `lineBy` (line connection),
  `colorBy`, `shape`, `size`, `rotation`, `limits` (Data limiting), `dataTable`, `layerTitle`,
  `trellis`. Layer titles and color items only: `["filtering", "marking", "markerBy", "lineBy",
  "shape", "size", "limits"]`; `"legend": {"visible": false}` hides the whole legend (standard
  engine; **Not yet tested** for layer legends).
- Every marker layer gets Analyst's own line-connection defaults first (marker color, width 2,
  behind the markers); settings and `lineBy` come after.
- Feature tables: an SBDF written by a GeoDataFrame data function or by `scripts/sbdf_export.py`
  keeps its geometry column metadata (`MapChart.ColumnTypeId = Geometry`, `ContentType
  application/x-wkb`, table `MapChart.GeographicCrs`); when the import did not keep them, the
  standard engine sets them (Binary column required, CRS `EPSG:4326`) and logs a NOTE line
  (**Not yet tested**).
- The library tiers (slim, full) ignore the standard-engine-only fields; there the same layers need
  `settings` (`MarkerSize`, `LabelColumn.Expression`, `LabelVisibility`,
  `Data.WhereClauseExpression`).

## Text areas

```json
{
  "id": "controls", "type": "textArea", "title": "Controls", "showTitle": false,
  "html": "html/controls.html",
  "css": "html/controls.css",
  "js": [],
  "controls": {
    "pumpSelect": {"kind": "dropdown", "property": "SelectedPumpId",
                   "values": {"column": {"table": "PUMP_DATA", "column": "Pump ID"}}},
    "mode":       {"kind": "dropdown", "property": "ViewMode",
                   "values": {"fixed": [{"text": "Hourly", "value": "H"}, {"text": "Daily", "value": "D"}]}},
    "window":     {"kind": "slider", "property": "TrendWindowDays", "min": 7, "max": 365, "step": 1},
    "threshold":  {"kind": "input", "property": "AlertThreshold"},
    "runModel":   {"kind": "button", "label": "Run Model", "script": "Run Pump Model", "args": {}},
    "toDetail":   {"kind": "link", "label": "Pump detail", "action": {"gotoPage": "Pump Detail"}},
    "r2":         {"kind": "label", "property": "OutR2"}
  }
}
```

- `html`: a file path or an inline string starting with `<`. Controls are placed with
  `{{control:<id>}}` placeholders. Every control must be placed exactly once.
- `css` (optional, slim tier): in `safe` mode it is injected by a small JavaScript into a
  `<div id="style-container">` that dxpgen adds; inline `style=""` attributes are also fine. In
  `rich` mode it becomes a `<style>` block. The standard engine stops on `css` ("inject it with a
  text-area JavaScript"): put the CSS in a `js` entry instead (template pattern below).
- `js`: extra JavaScript files attached through the public `HtmlTextArea.Scripts` API. The script
  name is the file stem, so name files Title Case "Verb Object" (`Show Render Time.js`); an entry may
  also be `{"name", "code"}`. The standard engine (feature `textjs`) registers each name once
  (`ScriptDefinition.Create(name, "", code, ScriptLanguage.JavaScript, no parameters, True)`) and
  attaches it after the text area's single HtmlContent set; the builder reads a `.js` file from the
  app folder when it runs (not carried in the builder). A JavaScript name must differ from every
  IronPython script name, and two text areas that list one name must list the same code.
- Template pattern (the stylesheet injector of the `styling-spotfire-dxps` skill): one host text
  area per page carries the injector, e.g. `"js": ["html/Apply Template Styles.js"]`, and its HTML
  starts with `<div id="style-container"></div><div id="styleDivSF"></div>`; no other text area on
  the page has those divs or the script. The CSS lives inside the JavaScript, never in `<style>`
  (safe mode).
- Control kinds: `label`, `input`, `multilineInput`, `dropdown`, `listbox`, `multiSelectListbox`
  (list-valued property), `slider`, `checkbox` (Boolean property), `radio`, `button`, `link`.
- Value sources for `dropdown`, `listbox`, `multiSelectListbox`, `radio`:
  `{"fixed": [{"text", "value"}]}` or `{"column": {"table", "column"}}`.
- `button`/`link` actions: `script` (+ `args`, values for the script's parameters: JSON values for
  String and numeric types, a page title for `Page`, a visual id for `Visualization`, a table name
  for `DataTable`), or `action: {"gotoPage": "<title>"}`, `{"applyBookmark": "<name>"}`,
  `{"refreshDataFunction": "<name>"}`. A button may add `actionMod` next to its `script` (see
  "Action mods").

**Controls are manual steps.** Spotfire 15.0 has no public API that adds a property control or an
action control to a text area, so the builder does not create controls. dxpgen validates every
control (kind, property and its type, value source, script and arguments, page, bookmark name, data
function). The builder replaces each `{{control:<id>}}` with a visible marker such as
`[Drop-down list: SelectedPumpId]` or `[Button: Reset Filters]` (a placeholder whose id the spec does
not describe gets `[control: <id>]`; the slim tier's library writes `[control: <id>]` for every
control). `build/MANUAL-STEPS-<tier>.md` has one instruction per control, for example: "Page
'Overview', text area 'Controls' (controls): Edit Text Area, delete the marker [Drop-down list:
ViewMode] and, at that spot, Insert Property Control > Drop-down list bound to the document property
ViewMode with fixed values Hourly = H, Daily = D." Spotfire has no check-box or radio-button
property control: a `checkbox` becomes a Yes/No drop-down list on the Boolean property and a `radio`
a single-select list box. `verify_dxp.py check` reports a control still shown as its marker as WARN,
and checks a control added by hand (kind, binding, values, label, script) as PASS or FAIL.

## Action mods

Buttons and visual action triggers can run the scripts of an action mod (Spotfire 15.0; the
`building-action-mods` skill writes one, [api-mods.md](api-mods.md) has the API). The public API
cannot add an action mod to an analysis or wire a button or a visual action trigger to it, so all of
them are **manual steps**. dxpgen validates every action-mod key, so the instructions in
MANUAL-STEPS name real script ids and arguments.

```json
"actionMods": [{"id": "pump-actions", "project": "actionmod"}],

"markNormal": {"kind": "button", "label": "Mark Normal", "script": "Add Label Window",
               "args": {"LabelKind": "Normal"},
               "actionMod": {"mod": "pump-actions", "script": "add-label-window",
                             "args": {"labelKind": "Normal"}, "label": "Mark the window as normal"}},

"actionTriggers": [{"display": "FloatingButton",
                    "actionMod": {"mod": "pump-actions",
                                  "script": "clear-marked-window", "args": {}}},
                   {"display": "ContextMenuItem", "label": "Clear the marked window",
                    "actionMod": {"mod": "pump-actions",
                                  "script": "clear-marked-window", "args": {}}}]
```

| field | meaning |
|---|---|
| `actionMods[].id` (required) | the mod id (`mod-manifest.json` `id`); one id names one mod (not also in `vizMods`) |
| `actionMods[].project` | the mod project folder, relative to the app (`mod-manifest.json` with the built bundles; or a packed `<id>.mod`). Without it the mod must already be embedded, installed or pinned in Analyst (warning: script ids are not checked) |
| `actionMod.mod` / `.script` | a listed mod id and one of its script ids (`mod-manifest.json` `scripts[].id`) |
| `actionMod.args` | values for the script's parameters by manifest name (literals; a page title for `Page`, a visual id for `Visualization`, a table name for `DataTable`) |
| `actionMod.label` (buttons and links) | optional: the name of the button's action. The control's own `label` stays the button text |
| `actionTriggers[].display` | `FloatingButton` (default), `TitleBarButton` or `ContextMenuItem` |
| `actionTriggers[].label` | optional: the name of the trigger's action, which Spotfire shows as the menu item text (`ContextMenuItem`) and the button tooltip. It sits on the trigger, not inside `actionMod` |

- dxpgen reads the project's `mod-manifest.json` when it exists: script ids, parameter names, `enum`
  values and types are checked (errors), missing values of required parameters and unbuilt bundles
  are warned; without a manifest the references are warned as unchecked (a `<id>.mod` file gets a
  note).
- Labels: a non-empty, one-line string (errors); spaces at either end and two triggers of one
  display with the same label on one visual (warnings); a `label` inside a trigger's `actionMod` is
  an error (it belongs on the trigger). Labels are visible text, so the customer-ready text check
  reads them.
- MANUAL-STEPS, per action mod: "Action mod '<id>': add it to the analysis (pin or install it in
  your library, or Tools > Development > Mods development > Connect to file > <project>/
  mod-manifest.json), then wire the buttons and action triggers listed here to it." Per visual
  trigger: "Page '<title>', visual '<title>': Visualization properties > Action triggers > add a
  <display> that runs the action '<script>' of the action mod '<mod>' with arguments ..., named
  '<label>'."
- A button with `script` (or `action`) and `actionMod` is a control step like every button: insert
  it with its IronPython script or action; the step names the action-mod action to use instead when
  the mod is in the analysis. A button with `actionMod` alone is warned at validate: it does nothing
  until you wire it by hand.
- `verify_dxp.py check` reports a visual action trigger not added yet as WARN, and checks one added
  by hand (display, mod, script, arguments) as PASS or FAIL; for a button added by hand that runs an
  action-mod script it checks the script and its arguments.

## Visualization mods (standard engine)

A `mod` visual shows a visualization mod (the `building-visualization-mods` skill writes one). The
standard engine reads the mod's project folder at validate and build time: the folder's
`mod-manifest.json` gives the layer types, the axes of each view, the property types and the
version. A mod visual can hold layers: each layer is a data view of its own, with its own table,
limiting expression, marking, axes and properties. `actionTriggers` on a mod visual are manual
steps, as on every visual.

```json
"vizMods": [{"id": "demo-layers", "project": "mods/demo-layers"}],

{"id": "demoLayers", "type": "mod", "modId": "demo-layers", "title": "Readings and events",
 "table": "READINGS", "marking": null, "legend": {"visible": false},
 "properties": {"heading": "Pump readings", "showGrid": true, "lineWidth": 1.5, "maxRows": 5000},
 "layers": [
   {"type": "Series", "title": "Readings", "table": "READINGS", "marking": null,
    "limitExpression": "[Asset] = \"${ViewAsset}\"",
    "axes": {"X": "Timestamp", "Values": ["Pressure (psig)", "Flow (bbl/d)"],
             "Series": "<[Axis.Default.Names]>"},
    "properties": {"role": "raw", "lineWidth": 1}},
   {"type": "Series", "title": "Daily range", "table": "READINGS", "marking": null,
    "limitExpression": "[Asset] = \"${ViewAsset}\"", "useFiltering": false,
    "axes": {"X": "Min([Timestamp])",
             "Values": ["Min([Pressure (psig)]) as [Pressure min]", "Max([Pressure (psig)]) as [Pressure max]"],
             "Series": "<[Axis.Default.Names]>",
             "Bin": "<BinByDateTime([Timestamp],\"Year.Quarter.Month.Day.Hour\",${BinLevel})>"},
    "properties": {"role": "binned", "visible": true}},
   {"type": "Records", "title": "Events", "table": "EVENTS", "marking": "Event Pick",
    "limitExpression": "[Asset] = \"${ViewAsset}\"",
    "axes": {"Key": "<[Event ID]>", "Attributes": ["Asset", "Start", "End"], "Values": "Max([Severity])"},
    "properties": {"role": "events"}}],
 "actionTriggers": [{"display": "FloatingButton",
                     "actionMod": {"mod": "demo-layers-actions", "script": "next-asset",
                                   "args": {"Assets": "Pump A,Pump B"}}}]}
```

The example app is `assets/examples/mod-layers-demo`.

| field | meaning |
|---|---|
| `vizMods[].id` (required) | the mod id (`mod-manifest.json` `id`); one id names one mod (not also in `actionMods`) |
| `vizMods[].project` (required) | the mod project folder, relative to the app: `mod-manifest.json` with the files it lists (build the mod first) |
| `modId` (required) | a `vizMods` id |
| `table` | the main view's table (default `defaultTable`) |
| `axes` | the main view's axes {name: value} (manifest `dataViewDefinition.axes`; `Color` = the color axis when the manifest declares `colorAxis`) |
| `properties` | the mod's properties {name: value} (manifest `properties`), typed by the manifest |
| `limitExpression`, `useFiltering`, `marking`, `limitByMarkings`, `emptyMarkingBehavior` | the main view's data, as on every visual |
| `legend` | absent: the manifest's `legend.defaultVisibility` stays (not the spec default `visible: true`); `visible` sets it; `hide` takes `filtering`, `marking`, `colorBy` |
| `settings` | escape hatch, paths relative to the ModVisualization (`UseSeparateColorForMarkedItems`, `Transparency`, `Description`, `ShowDescription`, ...) |
| `layers` | absent: the mod's own layers stay as Spotfire makes them; given: exactly these layers in this order (`[]` removes every layer) |
| `layers[].type` (required) | a manifest `layers[].type` |
| `layers[].title` | default: the type. Unique within the visual: the mod and `verify_dxp` find layers by title |
| `layers[].table` | default: the visual's table |
| `layers[].axes`, `layers[].properties` | the layer type's axes and properties (manifest `layers[].dataViewDefinition.axes`, `layers[].properties`) |
| `layers[].marking` | a marking name, or `null` (cannot be marked); absent: the visual's marking (the builder always sets it: a new layer has no marking) |
| `layers[].limitExpression`, `useFiltering`, `limitByMarkings`, `emptyMarkingBehavior` | the layer's data (`emptyMarkingBehavior` default `ShowAll` when `limitByMarkings` is given). A layer does not take the visual's limits |

Axis values: an expression string, a list, `""` (clears the axis) or `null` (leaves the axis as the
mod configures it). How a value is written depends on the axis mode in the manifest:

- categorical: `"<...>"` as written; a column name (`Asset` or `[Asset]`) becomes `<[Asset]>`; a list
  of levels becomes `<[A] NEST [B]>`. Any other expression must be wrapped in `<...>` (dxpgen error).
- continuous: the expression as written; a bare column name becomes `[Name]`; a list becomes several
  measures joined with `, ` (the manifest axis needs `allowMultipleMeasures`; dxpgen error
  otherwise). `<...>` is refused (dxpgen error).
- dual (or no mode): as continuous.
- `[$P]` becomes `DocumentProperty("P")`; `${P}` stays live. An unknown `${P}` in a mod axis or
  limiting expression is a dxpgen error (the view cannot be evaluated), not the usual warning.

Property values by manifest type: `string` (a JSON object or list is written as compact JSON text;
at most 102400 characters), `integer` (32-bit; a whole number written as `3.0` is accepted),
`double` (any number), `boolean`. A name the manifest does not list, or a value of another type, is
a dxpgen error.

dxpgen validate also checks: the manifest is valid JSON with the listed id and type
`visualization`; every file the manifest lists is in the project folder (error) and so is its icon
(warning); layer types and axis names exist; layer titles are unique; layer tables and markings
exist; column references in mod axes and limiting expressions are columns of the view's table (file
tables; warnings); a required axis that gets no expression while the manifest configures none
(`expressionHeuristics: "none"`) is warned. A `vizMods` entry that no visual uses is warned and left
out of the builder. Customer-ready text covers the manifest's name, description, layer types, axis
and property names, axis titles, the comments of the files it lists (JavaScript, CSS, HTML), layer
titles and string properties whose name ends in title, heading, label, text, caption, description
or message.

How the builder finds the mod: the public API cannot add a mod from a project folder or a `.mod`
file, so the builder uses a mod that `ModManager.GetVisualizationModsIncludingPinned()` (public,
14.5) lists: a mod embedded in the analysis the builder runs in, or one installed or pinned in your
library. It takes the listed mod with the manifest's version, else a listed mod of another version
(a NOTE line). When none is listed, the log gets a FAILED and a `TODO viz mod <id>: ...` line, each
visual of the mod becomes a placeholder text area `[mod: <id>]`, and the build goes on. To make a
mod available before you run the builder, pin or install it in your library, or add it once to the
starter page of the new analysis (Tools > Development > Mods development > Connect to file > its
`mod-manifest.json`, or drag its `.mod` file onto the page) and run the builder there; that second
route is **Not yet tested**. In an app with mod visuals the starter pages get the title
"<title> (starter)" and are removed only after every page is built, so a mod you placed on the
starter page stays in use until the new visuals have it. The preflight lists the manifest and the
files it lists, so a builder whose mod files are missing stops before it changes anything.
`dxpgen release` copies the project folder (without `node_modules`).

- Running the builder needs Spotfire 14.8 or newer (`ModVisualization.Axis` api 14.7,
  `Property<T>` api 14.8).
- A mod added from its project folder or a `.mod` file stores that path in the DXP (ModOrigin
  ManifestFile or File; `verify_dxp` warns). That is fine for a development build; a customer
  package needs the mod from the library.
- The slim tier builds no layers: `--tier slim` stops on a mod visual with `layers`.
- **Not yet tested**: see [live-test-status.md](live-test-status.md) (the generated builder as a
  whole, the starter pages removed after the mod visuals, the listed-mod route with the version
  check, the placeholder path, integer properties, layer `useFiltering: false` and limiting
  markings, `legend.hide` on a mod).

## app.style (standard engine style layer)

`dxpgen.py build` writes the standard engine by default (tiers: [architecture.md](architecture.md),
[engine.md](engine.md)). Its builder carries a `STYLE` dictionary; `app.style` is that dictionary in
the spec, without the theme (`app.theme` is a manual step). Everything is optional: what the spec
leaves out comes from the house style (`scripts/t3/_house.py`, from the tear-sheet style guide:
Segoe UI, ink `#111110`, negatives `#BA2C48`, LightSfx with an off-white canvas and ruled visual
titles).

```json
"style": {
  "palette": {"ink": "#111110", "neg": "#BA2C48", "oil": "#71AB3C"},
  "font": "Segoe UI",
  "text": "@ink",
  "negative": "@neg",
  "formats": {"money": "$#,##0;-$#,##0", "pct1": "0.0%", "musd": "$#,##0,,.0M;-$#,##0,,.0M"},
  "visual": {
    "kpi": {"baseFont": 8, "minTilesPerRow": 7, "minVisibleTiles": 7, "emptyText": "-"},
    "cross": {"negatives": true, "cellWidth": 84, "rowHeaderWidth": 200},
    "ref": {"labelFont": 8}
  }
}
```

| field | meaning |
|---|---|
| `palette` | color names -> `#RRGGBB`. `"@name"` refers to them inside `app.style` (`text`, `negative`, `visual.kpi.tile`); colors elsewhere in the spec stay `#RRGGBB` (the library tiers and the verifier read the same spec) |
| `font` | font family of every font the engine sets (axis, legend, table, KPI, reference-line labels) |
| `text` | cell text color of the red-negatives coloring (values zero and above) |
| `negative` | red of values below zero |
| `formats` | number formats by name. A name works wherever the spec takes a format for the standard engine (`kpis[].format`, `yFormat`); column `format` strings that equal a named format are written by name |
| `visual` | defaults per engine kind: `text`, `kpi`, `table`, `cross`, `line`, `bar` (the spec types textArea, kpiChart, table, crossTable, lineChart, barChart) and `ref` (reference lines). A visual's own key wins |

Style keys per kind (the tier that first applies them in brackets; `showTitle` and `legend` are
accepted for every kind, but a visual always keeps its spec default `true` when it does not say):

| kind | keys |
|---|---|
| `kpi` | `baseFont` pt (quick); `minTilesPerRow`, `minVisibleTiles`, `emptyText`, `tile` color or null (standard) |
| `table` | `negatives` [columns in red below zero], `font`, `headerFont` pt, `headerBold` (quick) |
| `cross` | `totals` bool (compact); `negatives` (true = every numeric measure), `font`, `headerFont`, `headerBold` (quick); `cellWidth`, `rowHeaderWidth` px (standard) |
| `line` | `axisFont`, `axisTitleFont`, `legendFont` pt (quick); `yFormat`, `lineWidth` (standard) |
| `bar` | `axisFont`, `axisTitleFont`, `legendFont` pt (quick); `yFormat` (standard) |
| `ref` | `width` px (compact), `labelFont` pt (quick) |

### Per-visual style keys

A visual may carry the style keys of its kind; they apply to that visual only (unknown keys are
warned, wrong values are errors):

```json
{"id": "cumCash", "type": "lineChart", "x": "[Month]", "y": ["Sum([A]) as [A]", "Sum([B]) as [B]"],
 "yFormat": "musd", "lineWidth": 2,
 "referenceLayers": [{"kind": "horizontalLine", "value": "0", "label": "Breakeven", "labelFont": 8}]}
```

Also for the standard engine: `kpiChart` `kpis[].format` (a format name or string per KPI), table
`negatives` (columns that must be in `columns`). It reads `lineWidth` (lineChart), `widths` (table)
and `totals` (crossTable; `rows` and `columns` must agree) as this spec defines them. A table
`coloring` that is exactly red negatives (one `lessThan` 0 rule in `app.style.negative`, default
`app.style.text`, `settings` `{"SetColorOnText": true}`) is read as `negatives`, so the slim tier
builds the same rule from the same spec.

### What the standard engine builds

sbdf tables (embedded; loaded by file name in apps with features, so the DXP keeps no local folder)
with column formats, document properties (every DataType, typed and list-valued defaults,
descriptions), markings (the default one and named ones with colors), Python data functions
(inputs: table with `columns` `"*"` or a list, column, value bound to `property`, `value` or
`expression`, `dataTypes`, table and column inputs limited by a marking; outputs: table or property;
`refresh`; `executeAtBuild`) run at build in spec order, `dataFunction` tables (column formats
applied after the runs; usable as `defaultTable` and by visuals and controls), IronPython scripts
(`file` or `code`, typed `parameters`, `transaction`), pages (filter panel, details on demand), page
navigation, text areas (HTML file or inline, JavaScript files, a visible marker for each control),
KPI charts, tables, line charts, bar charts (also `orientation: "horizontal"` and `sort`), cross
tables, scatter plots and maps with the fields above (maps with tile, marker and feature layers,
colorings of every mode on chart color axes, map layers, table and cross-table cells and KPI tiles,
x and y axis ranges, lines and curves), per-visual `marking` (a name or null) with `limitByMarkings`
and `emptyMarkingBehavior`, `limitExpression` on charts, tables and KPI charts, `yScale.min` and
`yScale.log`, reference lines, `trellis` and `yScale.individualScaling` on line, bar and scatter
charts, the filter panel layouts (`filterPanelLayout`, page `filters`), fixed and categorical
colors, `legend.hide` (on maps: every data layer's legend), mod visuals with layers (`vizMods`, see
"Visualization mods"), the default marking on KPI charts and cross tables (apps with features),
`settings` on visuals (the escape hatch below, applied after the visual is built, one path at a
time, so one bad path does not block the others) and layout trees. The items not yet run live are
listed in [live-test-status.md](live-test-status.md).

Not built, manual steps instead (see "Manual steps"): text-area controls, property triggers, action
mods with their buttons and visual action triggers, and `app.theme`.

Run the builder with "Execute in transaction" unticked: inside a transaction Spotfire refuses the
inline save, and the log then says to use File > Save As and names what to re-check afterwards (the
markings in Edit > Document Properties > Markings, the description). After a successful inline
save, an app that uses any feature turns the open analysis into a build session: a "Build Session"
page, and the analysis linked to a scratch file in `build/session`. Close it without saving and open
the saved DXP.

dxpgen stops with "<field>: ... is not in the standard engine yet: use --tier slim" for anything
else (relations, named filtering schemes, CSV tables, calculated columns, hierarchies, `settings` on
tables, columns, reference layers, KPIs and data functions, `postScript`, text-area CSS, TERR data
functions, data-function inputs limited by filtering, marking limits on value binds,
`useFiltering: false`, reference bands, rule settings, fitting-model settings, other visual types,
...). Table, column, visual and data-function parameter descriptions are not stored (a note says
so); slim stores them. Data-function code and script files are read by the builder when it runs
(from `datafunctions\` and `scripts\` in the app folder), like the HTML files.

`dxpgen validate` also prints an interaction audit as notes (never errors): per page, a marking used
by only one visual or map layer that nothing is limited by and no data function reads ("nothing else
on the page highlights or reacts"), a marking that spans several tables (only visuals on the same
table highlight each other: the standard engine builds no relations), and a table shown with
different markings on one page (they do not highlight each other). Use it to check that every
marking reaches every relevant visual of its page.

## Escape hatches

`settings` maps public property paths, relative to the visual's content object (or the table,
layer or axis it sits on), to values:

```json
"settings": {"XAxis.Scale.ShowGridlines": false, "Legend.Visible": false, "YAxis.Scale.LabelOrientation": "Vertical"}
"settings": {"Description": "Drag across the chart to mark a window.", "ShowDescription": true,
             "UseSeparateColorForMarkedItems": true, "YAxis.ShowAxisSelector": false,
             "LimitingMarkingsEmptyBehavior": "ShowMessage",
             "LimitingMarkingsEmptyMessage": "Mark rows in the chart above"}
```

`Description`, `ShowDescription` and `UseSeparateColorForMarkedItems` are `Visualization`
properties (every chart, table and KPI chart); `YAxis.ShowAxisSelector` hides the axis selector of
a chart's y axis. `LimitingMarkingsEmptyBehavior` and `LimitingMarkingsEmptyMessage` are shorthands
for `Data.LimitingMarkingsEmptyBehavior` / `Data.LimitingMarkingsEmptyMessage` (they live on the
visual's data; dxpgen rewrites them), what a visual with `limitByMarkings` shows when nothing is
marked. Settings run after `emptyMarkingBehavior`, so they win.

The builder walks the path with getattr, converts the value to the target property's type
(enum by member name, `System.Drawing.Color` from `#hex`, numbers, booleans, strings) and sets it.
dxpgen checks every path against the API index and rejects unknown members (without an index the
check is skipped with a warning).

`postScript` is a last resort for configuration the spec cannot express. It is linted like any
other IronPython.

## Manual steps

Spotfire 15.0 has no public API for these spec items, so the builder does not create them:

| spec item | what you get |
|---|---|
| text-area `controls` | a visible marker per `{{control:<id>}}` (`[Drop-down list: SelectedPumpId]`, `[Button: Reset Filters]`; slim tier `[control: <id>]`) and one Edit Text Area > Insert Property Control or Insert Action Control step per control |
| `triggers` | one Edit > Document Properties > Properties > Script... step per trigger; the script itself is built |
| `actionMods`, button `actionMod`, visual `actionTriggers` | one step per action mod (add it to the analysis) and per visual trigger (Visualization properties > Action triggers) |
| `app.theme` | one step to apply the theme; custom styles saved as `build/theme.json` |

`dxpgen.py build` writes them, in build order, to `build/MANUAL-STEPS-<tier>.md`, and the builder
logs each as a `TODO <what>: <how>` line in `build/build-log-<tier>.txt`. The slim tier's library
records them as fallbacks and writes them after the run to `MANUAL-STEPS.md` and
`build-report.json` next to the saved DXP. The report tier's
builder rewrites `MANUAL-STEPS-report.md` after the run: its failed steps under "Fix in Analyst"
and these items under "Add by hand". After the build, open the saved DXP, do each step and save.
`verify_dxp.py check` reports a manual item that is not added yet as WARN, and an item added by hand
as PASS or FAIL. A FAILED line in the log is a separate problem to fix.
