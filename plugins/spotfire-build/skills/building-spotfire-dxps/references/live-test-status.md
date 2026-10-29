# Live-test status

What has run in Spotfire Analyst 15.0 and what has not. When a build uses an item marked
**Not yet tested**, tell the user which item to look at in the result, and report what happened.
Everything here was proven on one Windows machine; nothing has run on a second machine yet.

## Proven in live builds on Analyst 15.0

- The run procedure: a new analysis with starter data, the New Script dialog with "Execute in
  transaction" unticked, Run Script, Cancel. With the box unticked the builder saves inside the
  script; with the box ticked Spotfire refuses `SaveAs` ("document is not idle"), and a save queued
  with `ApplicationThread.InvokeAsynchronously` from the script editor never ran.
- Closing the Document Properties dialog resets the markings of the open analysis, never of the
  saved file: the user opens the saved DXP, never saves the build session.
- Builders of every engine tier (standard, quick, compact, report) and the slim tier for an app with
  sbdf tables, KPI charts, tables, line and bar charts, cross tables and text areas (the well tear
  sheet example).
- Document properties, several markings, Python data functions registered, bound and run at build,
  and IronPython scripts, in builders of apps with features.
- The map configuration in [api-maps.md](api-maps.md) ("How a working map is configured"): a map built
  any other way can draw nothing.
- Visualization mod visuals with layers through the public API (`AddNew(ModIdentifier)`,
  `Layers.Clear`, `AddLayer`, typed properties, axes, where clauses, layer markings), in a
  hand-written builder.

## Not yet tested

Builder features:

- The engine-generated builder of an app with mod visuals as a whole; the starter pages renamed
  `<title> (starter)` and removed after the mod visuals exist; `Property<Int32>` set by a builder and
  read back; layer `useFiltering: false`; a layer marking set to none; layer `limitByMarkings` and
  `emptyMarkingBehavior`; clearing a continuous axis (`""` then `"<>"`); `legend.hide` on a mod's
  main view; the placeholder text area when the mod is not listed; the listed-mod route with the
  version check and the NOTE when another version stands in.
- Making a mod available by adding it to the starter page before the build (Tools > Development >
  Mods development > Connect to file, or dragging the `.mod` file), then running the builder there.
- A marking-limited automatic data function: it runs at build with no rows and re-runs on every drag.
- Text-area JavaScript attached by the builder, and its look under Web Player and the default
  sanitizer.
- `legend.hide`: the item kinds map to the right legend items (lineBy, referenceLayers); on maps,
  the kinds hidden on every data layer's own legend.
- Maps: a feature layer on an embedded SBDF renders (the builder tags the WKB column as geometry and
  sets the CRS when the import did not keep them, with a NOTE line); `MarkerSize 0` hides route
  vertices while the line connection draws; `extent` gives the first view; layer `settings` land on
  the visualization or the layer as intended; the star marker shape.
- Colorings: rule precedence (first rule on top), string rules on a `UniqueConcatenate` cross-table
  measure, gradients with numeric breakpoints on cross-table cells, one-color categorical palettes,
  KPI tile colorings.
- Scatter plots: a curve `x` draws y = x; dash and width on curves.
- sbdf tables loaded by file name so the DXP keeps no local folder (feature `pathFree`); the default
  marking set on cross tables of featured apps.
- Filter panel layouts: every listed table has its table group when the layout runs, hidden columns
  and tables stay hidden after save and reopen, the listed order holds, sub groups take their
  columns, filter types show on every page, and the organization survives a data function re-run
  that replaces its output table.
- `trellis` (Panels with a fixed grid, RowsColumns) and `yScale.individualScaling` on line, bar and
  scatter charts.

Manual steps and tools of this release:

- The control markers (`[Drop-down list: <property>]`, `[Button: <label>]`) render as plain HTML,
  and the MANUAL-STEPS instructions match Analyst 15.0's menus (Edit Text Area > Insert Property
  Control / Insert Action Control; Edit > Document Properties > Properties > Script...).
- The Analyst menu path for applying theme-editor JSON (`build/theme.json`) by hand.
- The slim tier after the removal of its non-public code paths (controls, triggers and the theme
  now go straight to their manual steps).
- `scripts/export_tables_job.py` (CSV export of data tables for the workbook reconciliation).
- `scripts/dump_api.ps1` after its non-public dump mode was removed: the public index it writes is
  expected to be the same as before; re-run it once and compare.
- Builders run unattended through the `running-spotfire-unattended` skill.
