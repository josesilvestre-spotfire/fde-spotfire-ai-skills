# Analyst facts: why the builder works this way

The facts below come from the public API of Spotfire Analyst 15.0 (build 71.0.22206.3863), from
DXPs saved by Spotfire 6.5 to 15.0 and read with `scripts/verify_dxp.py dump`, and from live builds
on Analyst 15.0. Items not confirmed in a live build are marked **Not yet tested**.

## 1. Why a generated builder, not generated XML

A `.dxp` is a ZIP. `AnalysisDocument.xml` is one line of serialized .NET objects: every object,
string and array has a document-wide Id, repeats are `<ObjectRef>`s, strings are interned and
shared between fields, types are declared once and referenced, column-bound expressions carry
column-name maps, scripts and data functions carry per-user approval stamps, and Spotfire writes
14.8 and 14.6 downgraded copies of the whole document next to the 15.0 one. One text-area control
alone is about 60 lines of interlinked graph. Hand-writing this is fragile and unverifiable.

Spotfire's API builds the same objects with all invariants intact, and Spotfire serializes them.
The builder therefore only ever calls the public API, and correctness is checked twice: statically
(every member exists in the API index) and after saving (the saved DXP matches the spec).
`scripts/sfgraph.py` reads the object graph for `verify_dxp.py`, including `<MultiDimensionalArray>`
(map transforms). Neither tool adds objects to a DXP.

## 2. Sources of truth and the version policy

| question | source |
|---|---|
| Does `X.Y` exist, with which signature, since which version? | `python scripts/sfapi.py has X.Y` / `type X --inherited` on the index you write with `scripts/dump_api.ps1` from your own Analyst (public members only; `[api a.b]` = the version that introduced the member). Without an index the member checks are skipped with a warning |
| What does it do? | the online Spotfire Analyst API reference for your version (one page per type and member); `spotfire-property-docs.json` (the property documentation embedded in Analyst, written next to the index by `dump_api.ps1`) |
| How does Spotfire persist and behave in practice? | DXPs saved by Analyst, read with `verify_dxp.py dump`, and [dxp-anatomy.md](dxp-anatomy.md) |

Builders target `minimumSpotfireVersion` 14.6 by default: members with `[api]` above 14.6 are used
only when a feature needs them, and the linter flags them.

Text-area controls, property triggers, action mods, the document theme and the text-area
background have no public API. The builder leaves them as manual steps
([architecture.md](architecture.md), "Public API only").

## 3. Execution facts inside Analyst

- `Application.SaveAs(path, DocumentSaveSettings())` throws "document is not idle" inside a
  transaction. A script run from the script editor with "Execute in transaction" ticked runs
  inside one; with the box unticked the builder saves inside the script. So the run instruction
  always says: untick "Execute in transaction".
- Callbacks queued with `ApplicationThread.InvokeAsynchronously` from the script editor did not
  run in live tests on Analyst 15.0. The builder saves inline first; the queued save is only the
  fallback, and when no "Saved" line appears the log says to use File > Save As.
- After a manual File > Save As, check the markings and the description. In DXPs saved by hand
  after a refused inline save, the default marking kept its default name and color and the
  description and keywords were empty, although every build log reported those steps as done
  (theme, pages, visuals and formats were all there). Likely cause: the Document Properties dialog
  the script editor lives in restores its own General and Markings tabs when it closes. With
  "Execute in transaction" unticked the builder saves inside the script, before the dialog closes,
  so the file keeps them (**Not yet tested**). The refused-save log line names what to re-check.
- After the inline save the open analysis is linked to the saved path, and closing the dialog
  resets the markings of that open copy. Never save it (no Ctrl+S, answer No when asked), or the
  reset copy overwrites the good file; File > Open the saved DXP instead. Builders of apps with
  features re-link the open analysis to a scratch file in `build/session` (a "Build Session" page
  says so), so this cannot happen by accident.
- `DataFunction.ExecuteSynchronously()` also returns False when the function's inputs did not
  change since its last run (nothing is re-run or written). Treat a run as failed only when it
  returns False and `NeedsRefresh` is still True (the engine's `run_function` check).
- `Save(String)` is obsolete; `SaveAs(String, DocumentSaveSettings)` is the current API.
  `DocumentSaveSettings()` writes the 14.x compatibility copies by default.
- `ScriptManager.ExecuteScript(code, language, args, stream, inTransaction)` swallows errors into
  the stream; running a stored `ScriptDefinition` raises them. The builder never relies on
  swallowed errors: every step records its own exception and traceback.
- `ScriptDefinition.Create(...)` and `DataFunctionDefinitionBuilder.Build()` stamp the object with
  an approval for the current Windows user, so a DXP you build reopens trusted for you. Other
  users get Spotfire's normal trust prompt.
- Data functions: only `ExecuteSynchronously()` completes inside the builder; output tables exist
  only after the first run, so visuals on them are built afterwards (build order).
- `VisualCollection.AddNew` auto-places visuals; the layout is applied once per page at the end,
  with every visual exactly once and alternating section orientation.
- Pages created through the API have no filtering scheme and hidden panels; the builder sets them.
- Persisted strings escape control characters as `_xHH` (tab = `_x09`); the verifier decodes them.
- Unattended builder runs (no paste into the script editor) are covered by the
  `running-spotfire-unattended` skill.

## 4. Data facts

- File-based tables are not embedded by default (a user preference decides): the builder forces
  embedding per table through `Document.Data.SaveSettings`, updating the existing entry.
- `TextDataReaderSettings()` defaults to separator ";", no header, guessed culture, ANSI: always set
  all four. Prefer SBDF.
- SBDF from pandas 3: string columns have dtype `str`, which `spotfire.sbdf.export_data` rejects
  ("unknown dtype 'str'"); convert to `object` first. `scripts/sbdf_export.py` handles this.
  Nullable `Int64` exports in spotfire 2.4.2.
- Document property names: letters and digits, dot-separated segments; case-insensitive; no
  underscores. Values must have the exact .NET type (`72.0` for Real).
- Property attributes as Analyst's UI sets them: `DefaultAttributes | IsPropagated` (78), as every
  custom property in saved DXPs has.
- New markings default to black; set the default table and marking before creating visuals.
- Excel has no public data source type; convert to SBDF.

## 5. Visual facts that bite

- Chart type ids match class names (`HeatMap`, capital M). Histogram = bar chart on
  `BinByEvenIntervals([x], n)` with `Count()`.
- `<...>` makes an expression categorical; several measures are comma-separated. Alias measures
  (`as [Name]`): the alias is the key for per-series settings, cross-table formats and KPI colors.
- Gridlines, tick labels and formats live on `axis.Scale`; range, log, reversal live on the axis.
  There is no axis title property (the display name is the title). `YAxis.ShowLabels` does not
  exist (a script that sets it fails silently inside a blanket `except`).
- Own Y scale per trellis panel: `YAxis.IndividualScaling = True` + `IndividualScalingMode.Trellis`.
- Horizontal bar charts built in the UI also set `XAxis.Reversed = True`.
- Coloring: set the color expression first (it resets the rules), then add rules and move each new
  rule to the top as Analyst does. `Apply(name)` finds document color schemes only.
- Reference layers start with line, fill and label switched off; turn on what you need.
- Maps: use `VisualTypeIdentifiers.MapChart2` (`Maps.MapChart`); a new map has no layers, no
  background, no marking. `AutoConfigure()` deletes all layers.
- Table column order is Add order (no Move); widths are keyed by column; number formats are set on
  the data column's formatter and apply to every visual using that column.
- Enum members named `None` need `getattr(Enum, "None")` in IronPython 3.
- Proven in live builds on Analyst 15.0:
  - Trellis Panels mode is capped at about three panels per screen. RowsColumns mode with the row
    axis on a lane column shows every lane.
  - Time axes of stacked visuals line up when each sets the same `YAxis.Scale.Span` (58 px).
  - A dashed or dotted series is one reference layer with `EvaluationModes = Category`,
    `ElementByAxis = "<>"`, `Avg([Value])`, and a dashed `LineConnection`. Set its stroke color
    explicitly (it does not inherit; black by default).
  - A layer label shows the expression's display name, so alias it. A layer expression needs
    `DateTime("yyyy-MM-dd HH:mm:ss")`; `DateTime(y,m,d,...)` is invalid there.
  - Scatter label layout Auto scatters labels far from their markers once crowded, and a newline in
    a label is clipped. Use `MarkerLabelLayout.Center` and staggered rows.
  - A scatter line connection cannot be clicked. To make a long capsule clickable, give it a table
    of points along it (unpivot) plus a relation by key.
  - A click on a graphical-table row header does not mark; a click on a cell does.
  - Action mods you add by hand: each visual button shows its script's manifest icon, so two
    buttons with different icons need two scripts; an empty optional argument stops the action,
    so leave the argument out.
  - No `Replace()` in expressions (use `Substitute()`); `DetailItemCollection` has no `Clear()`.

## 6. Text-area HTML facts

- The sanitizer is on by default in 15.0 (preference
  `TextArea/TextAreaPreferences/PerformHtmlSanitation`); an administrator can turn it off for a
  group. Allowlisted: 47 elements; removed with their subtree: `style`, `script`,
  `details`/`summary`, `button`, `input`, `select`, `svg`, `section` and others; one bad inline
  style value drops the whole `style` attribute.
- `${prop}` is not substituted in text-area HTML; show property values with Label controls.
- Spotfire renders controls with its own widgets: buttons are `input[type=button].sfc-action-button`,
  drop-downs are `div.sf-element-dropdown` (never `<select>`), list boxes `div.sf-element-list-box`.
- A drop-down inside a `display:none` element renders zero wide. Hide sections off screen instead.
- Text-area JavaScript (public `HtmlTextArea.Scripts`) runs after each full render with Spotfire's
  jQuery in scope; it is how CSS with selectors gets in under the sanitizer (`#style-container`).

## 7. Verification

`verify_dxp.py check` reads the saved DXP and compares it page by page and object by object with
the spec, then runs hygiene checks: embedded data, no absolute paths or user names anywhere in the
archive, no credential-like strings, no auto names, naming policy, layout proportions, control
tokens resolving, data-function parameter = property name. A manual step you have not done yet
(a control marker, a missing trigger, the theme, an action trigger) is a WARN; once you add the
item by hand it is checked like any other (PASS or FAIL). A placeholder text area where a mod
visual should be is a FAIL. Snapshots (`Visual.Render`) and your own view of the analysis are the
visual check against the prototype. The build log's TODO lines and `MANUAL-STEPS-<tier>.md` list
what is left to do by hand.

## 8. Known limitations

- Live test status per feature: [live-test-status.md](live-test-status.md).
- Visualization mods must be embedded, installed or pinned before the build (or added once to the
  starter page, **Not yet tested**); Excel sources must be converted to SBDF.
- No public API, so manual: text-area controls, property triggers, action mods and their visual
  action triggers, the document theme, the text-area background, KPI and graphical-table click
  actions, map annotations and custom marker shapes from files.
