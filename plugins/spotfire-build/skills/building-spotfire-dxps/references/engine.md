# Standard engine

The standard engine is what `scripts/dxpgen.py build` writes by default: one pasteable IronPython 3.4
builder made of three literals (`HOME`, `STYLE`, `APP`) and a small generic engine that builds the
analysis they describe. The engine is split into parts (`scripts/engine/`) so dxpgen can generate a
builder for any app whose spec it covers; `scripts/t3/` turns the resolved spec into the literals
and assembles the parts. The engine calls Spotfire's public API only. The worked example is
`assets/examples/well-tear-sheet`.

## Tiers

| tier | `--tier` | made of | styling |
|---|---|---|---|
| **standard** (default) | `standard` | core + used builders, all tier blocks | fonts, number formats, widths, red negatives, reference lines |
| quick | `quick` | core + used builders, `# @tier quick` blocks only | fonts and red negatives |
| compact (quickest) | `compact` | core + used builders, no tier blocks | none: data, visuals, colors given in APP, layout, save |
| report (exception) | `report` | standard + `report.py` | as standard, plus every step recorded, MANUAL-STEPS with the failed steps, snapshots |
| slim (exception) | `slim` | not this engine: `scripts/slim_builder.py` | the trimmed full library |
| full | `full` | not this engine: every `scripts/lib/*.py` (about 450 KB) | too big for the script editor; library development only |

Use report and slim only when a standard build has issues, or when the spec needs something the
standard engine does not build yet (dxpgen then stops with "<field>: ... is not in the standard
engine yet: use --tier slim").

## Files

Paths are relative to `scripts/`.

| file | what |
|---|---|
| `engine/core.py` | helpers (`ok`, `why`, colors, formats, `opt`, fonts), data loading with embedding and column formats, the default marking, pages, common visual helpers, the build loop, the layout tree, starter-table handling, the inline-first save; the build itself runs at the end (after `# @builders`) |
| `engine/builders/<kind>.py` | one per engine kind: `build_<kind>(v, vs)` plus its helpers, registered with `BUILDERS["<kind>"] = build_<kind>` and `TYPE_IDS["<kind>"] = "<VisualTypeIdentifiers member>"` |
| `engine/builders/_<name>.py` | shared parts (`_chart`: line, bar and scatter; `_tabular`: table and cross table; `_markers`: scatter and map marker layers), included once before the first builder that `# @uses` them |
| `engine/features/<name>.py` | feature parts, included only when the app uses the feature (table below), in this builder order: `guard`, `preflight`, `pathfree`, `properties`, `markings`, `datafunctions`, `scripts`, `controls`, `modload`, `textjs`, `links`, `settings`, `legend`, `coloring`, `filterpanel` |
| `engine/report.py` | the report add-on (report tier only); it replaces `ok`, `save_now`, `save`, `write_log` and `finish` |
| `t3/<kind>.py` | the converter of each kind: spec visual -> APP visual (`KIND`, `SPEC_TYPES`, `STYLE_KEYS`, `HANDLED`, `convert()`) |
| `t3/__init__.py` | registry, STYLE composition and trimming, APP, feature detection (`features_of`), the feature parts (`FEATURE_PARTS`, `FEATURE_NEEDS`), assembly (`t3.generate`) |
| `t3/_house.py` | the neutral default style (values the spec does not give) |
| `t3/_sections.py` | spec properties, markings, dataFunctions, scripts, vizMods and text-area control markers -> APP keys of the feature parts |
| `t3/_manual.py` | what the public API cannot build: the control marker texts, the APP `manual` entries and the `MANUAL-STEPS-<tier>.md` text |
| `t3/_coloring.py`, `t3/_filters.py` | the coloring object and the filter panel layout, shared with dxpgen and verify_dxp |
| `t3/_literal.py`, `t3/_assemble.py` | the HOME, STYLE and APP literals; directives, merged imports, the builder text |

The kinds: `text` (textArea), `kpi` (kpiChart), `table` (table), `line` (lineChart), `bar`
(barChart), `cross` (crossTable), `scatter` (scatterPlot), `map` (map) and `mod` (mod: a
visualization mod with layers, feature `vizMods`). **The generator includes only the builders (and
shared parts) the app uses**, in the order of first use; an app with only text areas gets core +
text.

### Features

A feature is something an app may or may not use. When it uses it, the generator includes the
feature's part (`engine/features/<name>.py`, when the feature has one) and keeps the
`# @feature <name>` blocks in core and the builders; otherwise both are left out. An app without
features gets the plain builder: no guard, preflight or pathfree either. An app whose only feature
is `manual` also keeps the plain builder, plus the TODO lines.

The engine has no feature that builds text-area controls (beyond their markers), property triggers,
action mods or the document theme: the public API cannot build them, so they are manual steps
(feature `manual`).

| feature (APP key) | part(s) | what it builds | spec source |
|---|---|---|---|
| `properties` (`properties`) | `properties` | document properties of every DataType, typed defaults, list-valued, description; created first | `properties` |
| `markings` (`markings`) | `markings` | the markings besides the default one, with colors | `markings` |
| `dataFunctions` (`dataFunctions`, `dfTables`) | `datafunctions` | Python data functions: register, bind inputs and outputs, run at build, refresh mode; output tables join `T`; column formats of `dataFunction` tables after the runs | `dataFunctions`, `tables[].source.type = "dataFunction"` |
| `markedInputs` (data-function bind `marking`) | - (blocks in `datafunctions`) | table and column inputs limited by a marking: `SetInput(param, expression, False, DataSelection[] {marking})` and a NOTE line (nothing is marked during the build) | `bind.limitByMarking` |
| `scripts` (`scripts`) | `scripts` | IronPython 3 scripts registered in the document (parameters, transaction) | `scripts` |
| `controls` (text visual `controls`) | `controls` | markers only: each `{{control:<id>}}` in the HTML becomes a visible marker such as `[Drop-down list: SelectedPumpId]` or `[Button: Reset Filters]` (an id the spec does not describe: `[control: <id>]`); the control itself is a manual step | textArea `controls` |
| `links` (visual `marking`, `limits`, `empty`; table and kpi `where`) | `links` | a visual's own marking (or none), markings that limit its data, empty-marking behavior, limit expressions on tables and KPI charts (and their tiles). In apps with features, KPI charts and cross tables without a marking get the default marking explicitly (`t3.mark_kpi_charts`): `VisualCollection.AddNew` leaves them unmarked (seen in live builds on Analyst 15.0) | `marking`, `limitByMarkings`, `emptyMarkingBehavior`, `limitExpression` |
| `settings` (visual `settings`) | `settings` | the escape hatch on visuals ([spec-format.md](spec-format.md) "Escape hatches"): dotted public property paths relative to the visual's content object, set after the builder and the data links, one `ok` per path (`<id>: setting <path>`); values converted to the property type (enum member name, `#RRGGBB` or `#AARRGGBB` color, numbers, booleans, strings, pseudo-enum static members); the report tier adds a manual fix per failed path | visual `settings` (dxpgen checks the paths against the API index) |
| `log` (line and bar `yLog`) | - (block in `_chart`) | log10 y axis | `yScale.log` |
| `barLayout` (bar `horizontal`, `sort`) | - (block in `bar`) | horizontal bars (`XAxis.Reversed`, as the UI does) and bars sorted by value | `orientation`, `sort` |
| `guard` (-) | `guard` | the refused-save re-check and the build session switch. `recheck()` names what to check after File > Save As (the markings in Edit > Document Properties > Markings, the description): the refused-save log line `CHECK after File > Save As: ...` and the report tier's fix. `switch_session()` runs only after a successful inline save: it adds a "Build Session" page with one text area and makes it active, saves the open analysis once more to `build\session\~build-session-<tier>.dxp` and logs `Session re-pointed to <scratch> - open the saved DXP to use the app`, so a later Ctrl+S never writes over the saved DXP. The guard does not detect a ticked "Execute in transaction" box: the header tells you to untick it | on in every builder of an app that uses any feature (besides `manual`) |
| `preflight` (APP `spec`, `release`, `files`) | `preflight` | right after the opened-from check, before the first document change, every file in APP `files` must exist under HOME (`File.Exists`, no `ok`); otherwise the build stops with "This builder does not match the files in <HOME>: missing <first four files> (and N more). Use the builder that belongs to this version (see versions\README.md). Nothing was changed." The log's first line starts with `[<release>, spec <12 hex>]` (`log_stamp`), so every build log names the spec that built the DXP next to it. dxpgen lists the files when it generates the builder (`t3.files_read`): sbdf tables, data-function code, IronPython scripts, each visualization mod's `mod-manifest.json` with the files it lists that exist then, text-area HTML and `.js` files; what the builder carries inline is not listed | on in every builder of an app that uses any feature (besides `manual`) |
| `pathFree` (-) | `pathfree` | sbdf tables loaded by bare file name with the current folder set to the file's folder (restored at once), so the DXP keeps `NAME.sbdf` instead of a local path with the user name; falls back to the full path with a NOTE line when that load fails or gives no columns; a NOTE line per table names the source path the DXP keeps (`DataTable.GenerateSourceView` read-back). Analyst's default out-of-process SBDF load starts without a working directory, inherits the current folder and finds the bare name too. **Not yet tested** | on in every builder of an app that has sbdf tables and uses any feature (besides `manual`) |
| `hiddenPages` (page `visible: false`) | - (blocks in core and report) | pages hidden from the page navigation with `Page.Visible = False`, one `hide page <title>` step each, after the active page is set so every page is built while shown; links, buttons and scripts can still go to a hidden page | page `visible` |
| `vizMods` (`vizMods`; visual kind `mod`) | `modload`; builder `builders/mod.py` | each visualization mod a visual uses must be listed by `ModManager.GetVisualizationModsIncludingPinned()` (public, 14.5): embedded in the analysis, installed or pinned. `modload.load_viz` takes the listed mod of the manifest's version, else a listed mod of another version with a NOTE; nothing listed: FAILED + `TODO viz mod <id>: <how>`. Mod visuals: `VisualCollection.AddNew(ModIdentifier)` (a placeholder text area `[mod: <id>]` + TODO when the mod is missing or refused; core then leaves data links, settings and legend items off it), the main view's table, limiting expression, filtering, axes (in the mod's own order, then `Color`; read back) and typed properties (`Property<T>` from the manifest type, through `MakeGenericMethod` on the public generic method when IronPython refuses the generic call; read back), legend only when APP gives it, then `Layers.Clear()` and `Layers.AddLayer(type, title)` per layer with table, limiting expression, filtering, marking (always set: `AddLayer` leaves a layer unmarked), limiting markings, empty behavior, axes and properties; a NOTE when Spotfire reports a view as not valid. Log: `OK viz mod <id> <version> (embedded or pinned)` | top-level `vizMods`, visual type `mod` ([spec-format.md](spec-format.md) "Visualization mods") |
| `textjs` (text visual `js`) | `textjs` | JavaScript on text areas: each name registered once (`ScriptDefinition.Create(..., ScriptLanguage.JavaScript, ..., True)`), attached with `HtmlTextArea.Scripts.Add(HtmlTextAreaScript(sd, {}))` after the single HtmlContent set; `.js` files read from HOME at build time | textArea `js` |
| `legendHide` (visual `legendHide`) | `legend` | legend items hidden by kind after the visual is built (runtime type of each `Legend.Items` entry: `LegendFilteringsItem`, `LegendMarkingItem`, `LegendGroupByItem` + `LegendLineConnectionItem`, `LegendColorItem`, `LegendReferenceLayerItem` + `LegendReferenceLayerTitleItem` + `LegendFittingModelCollectionItem`, `LegendTrellisItem`); on a map only `trellis` comes here (the map's own legend holds title, description and trellis items) | `legend.hide` |
| `layerLegends` (map `layerLegendHide`) | - (block in `builders/map.py`) | the map's `legend.hide` kinds hidden on every data layer's own `Legend` (`map_layer_legends`, last step of the map): `filtering`, `marking`, `markerBy` (`LegendGroupByItem`: Marker by or Geometry by), `lineBy` (`LegendLineConnectionItem`), `colorBy`, `shape` (`LegendMarkerShapeItem`), `size`, `rotation`, `limits` (`LegendFilterRuleItem`: Data limiting), `dataTable`, `layerTitle` (`Maps.LegendLayerTitleItem`) | map `legend.hide` |
| `coloring` (visual `coloring`, cross and table `cellColors`, KPI item coloring, map layer `coloring`) | `coloring` | the coloring object beyond the fixed and categorical chart colors (`scripts/lib/65_coloring.py` holds the same rules): gradient breakpoints (min, max, median, average, NN%, numbers, expressions), rules above the background in spec order (greaterThan, lessThan, between, equal: threshold or string rule, top, bottom, expression), one-color categorical palettes, the empty color, the default color, coloring `settings` (through `set_setting`; the `settings` part is then included). `configure(name, coloring, spec, cell)` runs the background in one step and each rule and setting in its own `ok`; cells without a default stay transparent | `coloring` on line, bar, scatter (when the fixed and categorical colors cannot express it), map layers, tables, cross tables, KPI charts |
| `cellColoring` (cross and table `cellColors`) | `coloring` | cell colorings of tables (keyed by column names) and cross tables (keyed by measure display names; no key = the default numeric coloring), after the red negatives | `table` and `crossTable` `coloring` |
| `kpiColoring` (fourth element of a `kpis` item) | `coloring` | KPI tile colorings on `THEN [Y.FinalValue]` | `kpis[].coloring`, KPI chart `coloring` |
| `range` (line, bar and scatter `yMax`, `xMin`, `xMax`) | - (block in `_chart`) | axis ranges besides the y minimum (`AxisRange`, None = automatic end) | `yScale.max`, `xScale.min`, `xScale.max` |
| `fitting` (line, bar and scatter `curves`) | - (blocks in `_chart`) | Lines & Curves: straight-line fits and curves (`AddCurve` of an expression in x, retried with the `${Name}` form), color, dash, width, label | `fittingModels` |
| `trellis` (line, bar and scatter `trellis`, `yEach`) | - (blocks in `_chart`) | small multiples (`Trellis.TrellisMode` Panels with `PanelAxis` and an optional fixed grid `ManualRowCount`, `ManualColumnCount`, `ManualLayout`, or RowsColumns with `RowAxis` and `ColumnAxis`) and an own y scale per trellis panel (`YAxis.IndividualScaling`, `IndividualScalingMode.Trellis`; `Color` without a trellis) | `trellis`, `yScale.individualScaling` |
| `scatter`, `map`, `markers` (kind flags) | - (blocks in `report.py`) | set when the app has a scatter plot or a map: the report tier's manual fixes of their steps | visual types `scatterPlot`, `map` |
| `filterLayout` (page `filters`, `filterTypes`) | `filterpanel` | each page's filter panel lists only the tables and columns a user needs (not styled). After the starter tables are removed: the filter types once per column on the default filtering scheme (`Filter.TypeId = FilterTypeIdentifiers.<type>`), then per page and listed table one `ok`: sub groups (`AddNewSubGroup`, `sub.Add(filter)` then the old group's `Remove(filter)`), listed columns shown and every other column hidden (`FilterHandle.Visible`; never removed: Spotfire re-adds a filter without a handle; a filter the builder makes gets its handle from Spotfire at once, so the handle is looked up again before one is added; a listed column the table does not have is left out with a NOTE line), items ordered (`Items.Move`), group expanded and moved to its place (`TableGroups.Move`); then every other table hidden (`TableGroup.Visible = False`); an `OK filters <page>: ...` line per page (NOTE when a step failed). `scripts/t3/_filters.py` holds the spec semantics shared with dxpgen and verify_dxp | top-level `filterPanelLayout`, page `filters` ([spec-format.md](spec-format.md) "Filter panel") |
| `manual` (APP `manual`) | - (block at the end of core's build) | everything the public API cannot build, as `[[what, how], ...]` from `scripts/t3/_manual.py`: text-area controls and visual action triggers page by page, property triggers, action mods, the theme. The builder logs each as a `TODO <what>: <how>` line after the page navigation; dxpgen writes the same items to `build/MANUAL-STEPS-<tier>.md`, and the report tier's `MANUAL-STEPS-report.md` lists them again under "Add by hand" | textArea `controls`, `triggers`, `actionMods`, control `actionMod`, visual `actionTriggers`, `app.theme` (only when the spec gives it) |

A builder of an app that uses any feature writes APP in the dense layout (`_literal.dense`: one
top-level key per line, values packed to 79 columns) and leaves function docstrings out (the engine
files keep them), which makes a large builder about 30 % smaller.

## How a builder is assembled

```
header (app, tier, run instructions incl. 'untick "Execute in transaction"',
        the build session note (guard), the number of manual items)
imports of every included part, merged; names nothing uses are dropped
HOME = r"<app folder>"
STYLE = {...}                      (house style + app.style, trimmed to the tier)
APP = {...}                        (from the resolved spec)
core.py up to "# @builders"        (definitions only)
feature parts                      (definitions; only the features the app uses)
shared parts and builders          (definitions + registration)
report.py                          (report tier)
core.py after "# @builders"        (the build)
```

Build order (each item its own `ok(...)`; feature steps only when used): the opened-from check (a
stop when the analysis was opened from a file), the preflight (a stop when a file is missing),
starter tables renamed when an app table has the same name, document properties, sbdf tables (by
file name with `pathFree`) and their column formats, the default marking, other markings, data
functions in spec order (register, bind with marking-limited inputs, run, refresh), column formats
of the data-function tables, scripts, visualization mods (`vizMods`), pages (per visual: add, title,
builder, data links, visual settings, legend items; text areas with their control markers and
JavaScript; mod visuals with their main view and layers; then the page layout), active page, hidden
pages, starter data removed (the default table set), filter types and filter panel layouts
(`filterLayout`), description, keywords, page navigation, the TODO lines (`manual`), a
`Built <n> of <m> visuals on <k> page(s).` line, then the log and the save.

In an app with mod visuals (`vizMods`) the starter pages are renamed `<title> (starter)` before the
pages are added and removed after every page is built: a mod visual you placed on the starter page
keeps the mod in the analysis until the app's own mod visuals exist. Other apps remove the starter
pages right after the new pages are added.

The save runs inside the script first (it works when "Execute in transaction" is unticked). When
Spotfire refuses it, the log says so and names what to check after File > Save As, and the save is
queued for after the script; no `Saved` line in the log means you save with File > Save As.

The log (`build\build-log-<tier>.txt`) starts with `No problems.` or `<n> problem(s), the build
went on:` (prefixed with `[<release>, spec <hash>]` by the preflight). It has an
`OK data function <name>: ran - <table> <n> rows, ...` line per function that ran (a
`FAILED data function <name>: ...` line when a binding or the run failed), a
`FAILED <visual>: setting <path>: ...` line per settings path that could not be set,
`OK viz mod <id> <version> (embedded or pinned)` (a NOTE when another version stands in) or FAILED +
`TODO viz mod <id>: ...` per visualization mod, a `TODO <visual>: placeholder for mod <id>; ...` per
mod visual built as a placeholder, a `FAILED <visual>: layer <title>...`, `<visual>: axis <name>` or
`... property <name>` line per mod item Spotfire refused, a `NOTE <page>: not in the layout tree,
added at the end: ...` line, one `TODO <what>: <how>` line per manual item, `Saved <path>` and, with
the guard, `Session re-pointed to <scratch> ...`.

Every line <= 79 characters, ASCII, IronPython 3.4 syntax. dxpgen checks each build: Python parse,
line length, ASCII and tabs, undefined names, `scripts/lint_ipy.py` (0 errors), Spotfire's own
IronPython 3.4 parser (`scripts/ipy_parse.ps1`, PARSE OK) and `scripts/sfapi.py has` for every member
the included parts declare (`--set` for setters). The member checks use the API index (`SFAPI_INDEX`,
else the newest `$DXP_WORKSPACE/api/spotfire-api-*.json`, written by `scripts/dump_api.ps1` from your
own Analyst); without an index they are skipped with a warning.

## Engine file conventions

- The leading comment block of a part documents it for maintainers and is not copied.
- Lines starting with `# @` are directives and never reach the builder:

| directive | meaning |
|---|---|
| `# @tier quick` ... `# @end` | kept for quick, standard and report |
| `# @tier standard` ... `# @end` | kept for standard and report only (compact keeps neither) |
| `# @uses _chart` | the shared part this builder needs |
| `# @api A.B; C.D(String)` | public members, checked with `sfapi.py has` |
| `# @set A.B` | assigned properties, checked with `sfapi.py has --set` |
| `# @note ...` | a maintainer note inside the code (stripped) |
| `# @feature name` ... `# @endfeature` | kept only when the app uses the feature (`!name`: only when it does not); may sit inside a tier block or hold one |
| `# @builders` | (core) where the builders and the report add-on go |

- Tier blocks are whole lines and do not nest; a block may sit inside a function body (indented
  markers are fine) as long as the code stays valid without it. A function used only inside a block
  must itself be inside a block of the same tier, or compact would keep dead code.
- A directive inside a tier block counts only for the tiers that keep it, so each tier checks
  exactly the members its code uses.
- Every build item runs in its own `ok(name, fn, *args)`: a failure becomes a log line, never a stop.
- Every Spotfire member a part uses is public and declared with `# @api` or `# @set`; a part that
  declares a non-public member is refused when the builder is assembled.

## HOME, STYLE and APP

`HOME` is the app folder: `data\<TABLE>.sbdf`, `html\*.html`, `datafunctions\*.py` and
`scripts\*.py` (read when the builder runs, so it stays small), `build\`. In a builder of `dxpgen
release`, `HOME` is the version folder `<app>\versions\vX.Y`, a frozen copy of those files, so the
builder reads only its own version and saves into `versions\vX.Y\build\`; the `preflight` feature
stops a builder whose files are not all in HOME before it changes anything (a builder pasted for the
wrong version or after the app folder changed).

`STYLE`:

| key | meaning |
|---|---|
| `palette` | colors by name; `"@name"` works wherever a color goes (STYLE and APP). A plain `"#RRGGBB"` works too |
| `font` | (quick and up) the font family every font the engine sets uses |
| `text`, `negative` | cell text color and (quick and up) the red of values below zero (red negatives) |
| `formats` | number formats by name; a name (or a literal format string) works wherever a format goes |
| `visual` | defaults per engine kind (and `ref` for reference lines). The same key on one visual in APP overrides the default for that visual only |

STYLE has no theme: the public API cannot set the document theme, so `app.theme` is a manual step
(see `manual`).

`APP`: `name`, `output` and `log` (relative to HOME), `description`, `keywords`, `defaultTable`,
`marking` `[name, color or None]`, `activePage`, optional `navigation` (page navigation when not
Tabs), `tables` `[[name, {format name: [columns]}], ...]` (a third element = data file relative to
HOME when it is not `data\<name>.sbdf`), `pages`; report tier: `tag` (file suffix) and `snapshots`
(`[width, height]` or None). Feature keys, present only when used:

| APP key | schema |
|---|---|
| `markings` | `[[name, color or None], ...]`: the markings besides the default one (`marking`), right after `marking` |
| `properties` | `[[name, DataType, default, listValued, description], ...]`; trailing `False` and `""` left out. Defaults are JSON values (DateTime `"2025-01-01T00:00:00"`, a list for list-valued) converted with `net()` |
| `dataFunctions` | `[{name, file (in HOME\datafunctions) or code, description, in, out, refresh, run}, ...]`, spec order. `in`: `[[name, "table"\|"column"\|"value", bind, dataTypes], ...]` with bind `{table, columns: [...]}`, `{table}` (the table's columns when it exists at bind time, else Spotfire's `$csearch` template), `{table, column}`, `{property}`, `{expression}` or `{value: "text"}` (non-string literals become `{expression}`: `20`, `0.5`, `True`, `DateTime(2025, 1, 1, 0, 0, 0, 0)`); dataTypes absent = the 11 types of the registration dialog. `out`: `[[name, "table", table] \| [name, "value", property], ...]`. `refresh: "manual"` (absent = automatic), `run: False` (absent = run at build) |
| `dfTables` | `[[table, {format: [columns]}], ...]`: column formats of `dataFunction` tables, applied after the runs |
| `scripts` | `[{name, file (in HOME\scripts) or code, description, params [[name, type, description], ...], transaction False}, ...]` |
| `vizMods` | `[[id, project folder relative to HOME, manifest version], ...]`: the visualization mods a mod visual uses, spec order (feature `vizMods`); the version is left out when the manifest has none. The preflight `files` list each one's `mod-manifest.json` and the files (and icon) it lists |
| `filterTypes` | `[[table, column, FilterTypeIdentifiers member], ...]`, each column once, right before `pages` (feature `filterLayout`) |
| `spec`, `release`, `files` | right after `log` (feature `preflight`): the first 12 hex digits of spec.json's sha256, the release version (`dxpgen release` only), and every file the builder reads, relative to HOME (`["data\\ROUTE.sbdf", "html\\opsKpiBand.html", ...]`) |
| `manual` | `[[what, how], ...]`, last: one entry per item the public API cannot build (feature `manual`), for example `["control kpiBand/mode", "Page 'Overview', text area 'kpiBand': Edit Text Area, delete the marker [Drop-down list: Mode] and, at that spot, Insert Property Control > Drop-down list bound to the document property Mode with fixed values ..."]` or `["trigger Mode -> ApplyMode", "Edit > Document Properties > Properties, select the document property 'Mode', click Script..., ..."]` |

A `dataFunctions` input bind may carry `"marking": <name>` (feature `markedInputs`): the input gets
only the rows marked in it. Any table works, including a table an earlier data function makes. A
typical use is an automatic, marking-limited function that writes a document property when you
mark rows.

Each page: `title`, optional `filterPanel` and `detailsOnDemand`, `visible` (feature
`hiddenPages`), `filters` (feature `filterLayout`: `[{table, columns ("*" or [names]), expanded
(only False), groups [[name, [columns]] or [name, [columns], False], ...]}, ...]` in display order),
`visuals`, `layout`:

```
{"column": [...]}  items top to bottom      {"row": [...]}  items side by side
{"visual": id}     one visual               "weight" sizes an item against its siblings (default 1)
```

Rows and columns alternate; a section nested in one of the same kind is merged into it, and a visual
missing from the tree is added at the end of the page.

Visual keys. All kinds: `id`, `type` (engine kind), `title`, `showTitle`, `legend`, plus any STYLE
`visual` default of the kind. All kinds but text (feature `links`): `marking` (a marking name, or
None = cannot be marked; absent = the default marking), `limits` (marking names that limit the
data), `empty` (`"ShowAll"`, `"ShowEmpty"` or `"ShowMessage"`, always written with `limits`: left to
the default, a live build showed an empty table). All kinds (feature `settings`): `settings`
`{dotted path: value}`, the spec's visual `settings` as written (paths relative to the content
object: `LineChart`, `BarChart`, `TablePlot`, `CrossTablePlot`, `KpiChart`, `HtmlTextArea`), for
example `{"BreakOnEmpty": True}` on a line chart (the shorthands `LimitingMarkingsEmptyBehavior` and
`LimitingMarkingsEmptyMessage` arrive as `Data.<name>`). All kinds but text (feature `legendHide`):
`legendHide` `[kind, ...]` (`filtering`, `marking`, `lineBy`, `colorBy`, `referenceLayers`,
`trellis`).

| kind | keys | style keys (tier) |
|---|---|---|
| text | `html` (file in HOME\html) or `htmlText` (inline); `controls` `{id: marker text}` (feature `controls`, below); `js` `[[name, file relative to HOME] or [name, None, code], ...]` (feature `textjs`) | - |
| kpi | `table`, `kpis` `[[title, expression, format or None(, coloring)], ...]` (the coloring: feature `kpiColoring`), `where` | `baseFont` (quick); `minTilesPerRow`, `minVisibleTiles`, `emptyText`, `tile` (standard) |
| table | `table`, `columns` `[name or [name, width px]]`, `where`, `cellColors` `[[columns, coloring], ...]` (feature `cellColoring`) | `negatives` [columns], `font`, `headerFont`, `headerBold` (quick) |
| line | `table`, `x`, `y` (expression or list), `where`, `color` or `colorBy` + `categories` {category: color}, `yMin`, `yLog`, `refs`; features: `coloring` (the APP coloring object), `yMax`, `xMin`, `xMax` (range), `curves` (fitting), `trellis` `{panel, rows, columns}` or `{rowsBy, columnsBy}` and `yEach` True (trellis; also on bar and scatter) | `axisFont`, `axisTitleFont`, `legendFont` (quick); `yFormat`, `lineWidth` (standard) |
| bar | as line, plus `stack` (true = stacked, `"percent"`, `"sideBySide"`), `horizontal` (true), `sort` (`"ascending"` or `"descending"`) | as line, without `lineWidth` |
| cross | `table`, `rows`, `columns` (categorical expressions), `measures` [...], `cellColors` `[[measure display names or None, coloring], ...]` (feature `cellColoring`; None = the default numeric coloring, which then sets `negatives` False) | `totals` (compact); `negatives` (true = every numeric measure), `font`, `headerFont`, `headerBold` (quick); `cellWidth`, `rowHeaderWidth` (standard) |
| scatter | as line (no `lineWidth`), plus `lineBy` (categorical), `sizeBy`, `shapeBy` (categorical), `shape` (MarkerType member), `labelBy`, `labels` (`"All"`, `"Marked"` or `"None"`), `markerSize` (% of the plot); `coloring`, `yMax`, `xMin`, `xMax`, `curves`, `trellis`, `yEach` as line | `axisFont`, `axisTitleFont`, `legendFont` (quick); `yFormat` (standard) |
| mod (feature `vizMods`) | `mod` (a `vizMods` id), `table` (main view), `where`, `filtering` (False only), `axes` `{name: expression or "" (clear)}` (written in manifest order, set in the mod's own order), `props` `[[name, "string" / "integer" / "double" / "boolean", value], ...]`, `legend` (written only when the spec gives `legend.visible`: absent keeps the manifest's default), `layers` `[{type, title, table, marking (name or None; the converter always writes it), where, filtering, limits, empty, axes, props}, ...]` (absent = the mod's own layers stay); `settings` paths are relative to the `ModVisualization` | - |
| map | `table` (the visual's: trellis layer and map data), `layers` [...], `autoZoom` (False only), `extent` [west, south, east, north] Web Mercator metres, `interactive` (a data layer title), `layerLegendHide` [kind, ...] (feature `layerLegends`); layer: `kind`, `title`, `settings`; data layers `table`, `colorBy`, `coloring`, `marking`, `limits`, `empty`, `where`; marker layers `x`, `y` and the scatter marker keys; feature layers `geometry` (geometry-by), `column` (WKB column) | - |
| ref (lines on line, bar and scatter) | `label`, `axis` `"X"` or `"Y"`, `value`, `color`, `dash` `"solid"`, `"dash"` or `"dot"`, `width` | `width` (compact), `labelFont` (quick) |
| curves (feature `fitting`, line, bar and scatter `curves`) | `kind` `"straightLine"` or `"curve"`, `expression` (in x), `alt` (the `${Name}` form), `color`, `dash` (`"dash"`, `"dot"`, `"double"`), `width`, `label` | - |

Text-area controls (`controls`, every tier): the marker text comes from
`scripts/t3/_manual.py` `control_marker`. A property control is `<UI kind>: <property>` with the UI
kinds Label, Input field, Input field (multiple lines), Drop-down list, List box, List box (multiple
select) and Slider (a spec `checkbox` becomes a Drop-down list with Yes = True and No = False; a
`radio` becomes a List box). An action control is `Button: <label>` or `Link: <label>`. The builder
writes the marker as a red dashed `[...]` span where `{{control:<id>}}` stands. The matching manual
step says, for example: "Edit Text Area, delete the marker [Drop-down list: Mode] and, at that
spot, Insert Property Control > Drop-down list bound to the document property Mode with fixed
values ...", or for a button "Insert Action Control > Button labeled 'Reset Filters' that runs the
IronPython script 'ResetFilters'". A button that names an action mod gets the IronPython script or
action as its step, with the action mod named as the alternative.

### The APP coloring object (feature `coloring`)

`scripts/t3/_coloring.py` turns a spec coloring object ([spec-format.md](spec-format.md)
"Coloring") into: one background of `categorical` `[[key, color], ...]` (keys typed like the
color-by column when it is a known SBDF column), `gradient` `[[value, color], ...]` or `fixed`
color; `rules` `[[type, color, value, ...], ...]` with types `greaterThan`, `lessThan`, `equal`
(threshold rule), `between` (low, high), `equalText` (text, is-expression: a string rule), `top` or
`bottom` (count), `expression` (Boolean expression); `default`; `empty` (the `"(Empty)"` category);
`settings` {path: value}. Values: `"min"`, `"max"`, `"median"`, `"average"`, `"NN%"`, a number
(float = Real, int = Integer: whole numbers on Real or unknown columns are written as floats),
True or False, any other text = an expression (`[$Name]` already translated). Colors keep an alpha
(`#AARRGGBB`). Line and bar charts whose coloring the plain `color` and `categories` keys express
(fixed, or categorical without `default` or `"(Empty)"`) keep those keys and do not need the
`coloring` part.

## Where STYLE and APP come from (scripts/t3)

- `STYLE` = the neutral default style (`scripts/t3/_house.py`: palette, Segoe UI, red negatives,
  number formats, per-kind sizes) merged with `app.style` ([spec-format.md](spec-format.md)
  "app.style": palette and formats entries are merged, each kind's defaults key by key). Each tier
  keeps only the keys its code reads, only for the kinds the app uses; default palette and format
  entries appear only when something uses them (standard keeps the spec's own palette and formats
  whole). `app.theme` is not part of STYLE: it becomes a manual step, and dxpgen writes its custom
  styles to `build/theme.json`. The `styling-spotfire-dxps` skill covers themes.
- `APP` comes from the resolved spec. Spec colors are `#RRGGBB` (the slim tier and the verifier read
  the same spec), so APP colors are hex. `showTitle` and `legend` follow the spec defaults on every
  tier; a visual key is written only when it differs from the STYLE default of its kind.
- Spec fields the engine leaves out on purpose are printed as a note (table, column and visual
  descriptions, data-function parameter descriptions). Fields it cannot build stop the build with
  the field path and "not in the standard engine yet: use --tier slim": relations, named filtering
  schemes, CSV tables, calculated columns, hierarchies, linked sbdf tables, `settings` on tables,
  columns, reference layers, KPIs and data functions (visual `settings` are built), `postScript`,
  fixed canvas, page filtering schemes, `useFiltering: false` (mod visuals and their layers take
  it), text-area CSS, TERR data functions, data-function inputs limited by filtering, marking limits
  on value binds, Binary property defaults, chart scale options other than min, max, Y log and Y
  individual scaling, reference bands and reference lines from another table, coloring rule
  settings, fitting-model settings, KPI comparative, time and tileBy, partial cross-table totals,
  bar `labels`, table `sort`, visual types without a builder. Items the public API cannot build at
  all (text-area controls, property triggers, action mods, the theme) never stop the build: they
  become manual steps.
- Data-function tables: their column types are only known after the run, so the generator knows
  only the column names their `tables[]` entry declares. A bare column of such a table on a chart's
  `colorBy` or a bar chart's `x` is taken for a category (`<[Col]>`), as a String column of an sbdf
  table is. Whole-table inputs (`columns: "*"`) pass an explicit column list: the declared one when
  no earlier function that runs at build produces the table, else the table's own columns at bind
  time (`$csearch` only when the table does not exist yet).

## Adding a builder (a new kind)

1. `scripts/engine/builders/<kind>.py`: a leading comment block (APP keys, style keys, `# @uses`,
   `# @api`, `# @set` directives), imports, `build_<kind>(v, vs)` and its helpers, styling inside
   tier blocks, then `BUILDERS["<kind>"] = build_<kind>` and `TYPE_IDS["<kind>"] =
   "<VisualTypeIdentifiers member>"`. Use the core helpers (`ok`, `opt`, `rgb`, `fmt`, `font`,
   `legend`, `T`, `MARK`) and, for charts, `@uses _chart`.
2. `scripts/t3/<kind>.py`: `KIND`, `SPEC_TYPES` (the spec visual types it converts), `STYLE_KEYS`
   (`(key, check, tier)`: the per-visual and `app.style.visual.<kind>` keys), `HANDLED` (spec fields
   it reads besides the common ones) and `convert(v, raw_v, path, ctx)` returning the APP keys in
   order. Report anything it cannot build with `ctx.unsupported(path, "...")`.
3. A test in `tests/test_tiers.py`. Nothing in dxpgen changes: both files are discovered, the
   validator accepts the new style keys, and the generator includes the builder only for apps that
   use it.

## Adding a feature

1. `scripts/engine/features/<name>.py`: a leading comment block (APP keys, `# @api` and `# @set`
   directives), imports, definitions only (no build steps). Public members only.
2. The build steps go into `scripts/engine/core.py` (or a builder) inside `# @feature <key>` ...
   `# @endfeature`, each in its own `ok(...)`, at its place in the build order.
3. `scripts/t3`: the APP keys (`_sections.py` or the kind's converter), the feature in
   `features_of()`, the part in `FEATURE_PARTS` (and `FEATURE_NEEDS` when the feature name differs
   from the part name or needs another part).
4. A test in `tests/test_features.py`. An app that does not use the feature must get the same
   builder as before.

Something the public API cannot build is not a feature: add it to `steps()` in
`scripts/t3/_manual.py` (and its marker, when it sits in text-area HTML), so it becomes a manual
step with one exact Analyst instruction.

## Live status

The current list of what is proven and what is not is in
[live-test-status.md](live-test-status.md). For the engine:

- Proven on Analyst 15.0: the standard tier's core with the text, kpi, table, line, bar and cross
  builders (the well tear sheet example built with no failed item); the inline save with "Execute in
  transaction" unticked (inside a transaction Spotfire refuses the save); the mod visual calls
  `AddNew(ModIdentifier)`, `Layers.Clear`, `AddLayer(type, title)` on several tables, where clauses
  with `${...}` and `DocumentProperty`, multi-measure values, `<[Axis.Default.Names]>`,
  `BinByDateTime`, a layer marking, typed `Property<T>` on the main view and the layers, and clearing
  an axis with `""` or `"<>"`; KPI charts and cross tables left unmarked by `AddNew` (hence the
  explicit default marking).
- A raw label, size, line order or rotation on a scatter plot or marker layer with aggregated
  markers blanks the whole map (seen in a live build on Analyst 15.0): dxpgen stops with an error
  for it and verify_dxp FAILs it ([api-maps.md](api-maps.md)).
- **Not yet tested** as generated builders, although every member passes `sfapi.py has` (public
  and `--set`), lint and Spotfire's IronPython parser in every tier, and the tests run the engine
  functions in CPython with stand-ins:
  - `properties`, `markings`, `dataFunctions`, `scripts`, `links`, `settings`, `log`, `barLayout`;
  - `guard` (the build session switch), `preflight` (it uses only `System.IO.File.Exists` and
    `Path.Combine` before any document change), `pathFree` (the by-name load), `hiddenPages`;
  - `markedInputs` (a marking-limited automatic function runs at build with no rows and re-runs on
    each mark), `textjs` (JavaScript attached by the builder runs after each render), `legendHide`
    (each legend kind hides the right items), `layerLegends`;
  - the `scatter` and `map` kinds, `coloring`, `cellColoring`, `kpiColoring`, `range`, `fitting`.
    Open questions: feature-layer geometry from SBDF metadata (the builder tags the column when the
    import did not keep `MapChart.ColumnTypeId`; NOTE line), `MarkerSize 0` hiding the route
    vertices while the line connection draws, `ViewExtent` as the first view with AutoZoom off, the
    layer settings routing (`Transparency` on the visualization of data layers), string rules on a
    `UniqueConcatenate` cross-table measure, a one-color categorical palette, rule precedence (first
    rule on top), the curve `x` on a scatter plot (y = x), `ReferenceCurve.LineStyle` and `Width`;
  - `filterLayout` and `trellis`. Open questions: the TableGroups of every table exist when the
    layout runs (after the starter tables are removed; a missing group is a FAILED line),
    `Items.Move` and `TableGroups.Move` give the listed order, a hidden table group stays hidden,
    filter types on the default scheme show on every page, the organization survives a data function
    re-run;
  - `vizMods` as a whole generated builder (`assets/examples/mod-layers-demo`): the version check
    and the fallback to another listed version, the placeholder path, `Property<Int32>` and the
    double read-back, layer `useFiltering` false, limiting markings and empty behavior, clearing a
    continuous axis, `legend.hide` on a mod's main view, the starter pages renamed and removed after
    the mod visuals, and adding a mod to the starter page as the route that makes it available;
  - `manual`: the TODO lines, and verify_dxp's WARN for a manual item not added yet and PASS or FAIL
    for an item added by hand.
