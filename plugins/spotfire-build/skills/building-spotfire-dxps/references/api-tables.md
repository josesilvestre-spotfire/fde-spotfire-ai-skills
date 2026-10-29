# Tables, cross tables, summary tables, graphical tables, KPI charts

Owner: `scripts/lib/70_tables.py` (`vis_table`, `vis_crosstable`, `vis_summary`, `vis_graphical`, `vis_kpi`).
Spotfire Analyst 15.0, IronPython 3.4. Public API only. Newest member `[api 12.5]` (the `FontStyleFlags` rule
overloads), so everything runs on 14.6. Members: `scripts/lib/70_tables.members.txt`; setters:
`scripts/lib/70_tables.set.txt` (both pass `scripts/sfapi.py has`). Cell and KPI-tile colorings are built by
`scripts/lib/65_coloring.py` ([api-coloring.md](api-coloring.md)). Items not yet proven in a live build are
marked **Not yet tested** and listed in section 5.

## 1. Build sequence and report

Every builder: `B.table_or_default(table)` (a missing table fails the visual before it exists) ->
`page.Visuals.AddNew(VisualTypeIdentifiers.X)` -> `visual.As[T]()` -> `Data.DataTableReference = dt`
(columns and expressions resolve against it) -> one `B.step` per sub-item -> `vis_common` last, so
`settings` and `postScript` see the finished visual. A failed sub-item never loses the visual.
`vis_common` is called through `_tables_common`: looked up inside the step (a missing 60_charts fails
one step, not the visual) and given `coloring: None` (this module owns coloring for these types).

| visual | report steps (targets: id, `id/coloring[i]`, `id/columns[i] kind`, `id/kpis[i] title`) |
|---|---|
| table | `table.columns`, `table.sort`, `table.widths`, `table.coloring`, `table.common` |
| crossTable | `crossTable.axes`, `crossTable.totals`, `crossTable.coloring`, `crossTable.common` |
| summaryTable | `summaryTable.columns`, `summaryTable.statistics`, `summaryTable.common` |
| graphicalTable | `graphicalTable.rows`, `.reset`, `.column`, `.rule` (one per rule), `.range` (one per band), `.column.settings`, `.common` |
| kpiChart | `kpiChart.reset`, `.kpi`, `.coloring`, `.common` (postScript withheld), `.data`, `.kpi.settings`, `.postScript` |

KPI order matters: `vis_common` sets the chart-level data, `.data` mirrors it onto every KPI, then
per-KPI `settings`, then the chart's `postScript` (run here with `visual`, `content`, `Document`).

`B.created["tableVisuals"][id]` (JSON) = `type`, `table` plus:
- table: `columns` (display order), `autoAddNewColumns`, `sort` [{column, descending}],
  `widths` {column: px}, `colorings` (targets);
- crossTable: `rowAxis`, `columnAxis`, `measureAxis` (the exact strings set), `measureNames`,
  `totals`, `colorings`;
- summaryTable: `columns`, `autoAddNewColumns`, `statistics` (the accepted names);
- graphicalTable: `rowAxis`, `columns` [{kind, title, width, expression, x, comparative, rules,
  ranges}] (`{"kind", "built": false}` when a column failed);
- kpiChart: `kpis` [{title, value, tileAxis, xAxis, comparative, showSparkline, sortColumn,
  coloring (target), built}].

Warnings (not failures): `colorBy` / `referenceLayers` / `fittingModels` on these types; visual-level
`coloring` on summary or graphical tables; background keys, `rules` or `ranges` on a graphical column
kind without them; a sparkline without `x`; a column without `expression`; empty `kpis`, `columns`
or `measures`; a colored table column that is not shown; a cross-table coloring target that matches
no measure.

## 2. Spec fields as the library reads them (dxpgen should validate these)

**table**: `columns` = column names in display order (`"[Name]"` accepted). Absent = every column
of the table and `AutoAddNewColumns = True`; given = exactly those and `AutoAddNewColumns = False`
(set before `TableColumns.Clear()`). `sort` = `[{"column", "descending"}]`, first entry = primary.
`widths` = `{column: px}`; a column the table does not show fails that width (the others are set).
`coloring` = one coloring object or a list; each needs `columns` (one coloring may color several
columns; the first column's type types numeric literals and category keys).

**crossTable**: `rows`, `columns` = lists of levels (`["[Station]", "[Pump ID]"]`) or one expression;
built as `<[Station] NEST [Pump ID]>`, empty = `<>`; a bare column name is escaped. When `columns` is
empty or there is more than one measure, `[Axis.Default.Names]` (Column Names) ends the column axis
unless rows or columns already contain it (as saved analyses persist it: one measure ->
`<[Axis.Default.Names]>`; categories + two measures -> `<[Order Type] NEST [Axis.Default.Names]>`;
categories + one measure -> no Column Names). `rows: ["[Axis.Default.Names]"]` puts the measures on the
rows (statement layout, one row per measure; **Not yet tested**). The axis without Column Names is set
first, then both axes are read back; when Spotfire kept something else the other order is tried once and a
remaining difference is a warning (`created.tableVisuals[id].axesAsSet`).
`measures` = aggregations joined with `", "` and set before the category axes; **alias every
measure** (`Avg([Flow Rate (bbl/d)]) as [Avg Flow (bbl/d)]`). `totals` = `{"rows", "columns"}` ->
`ShowRowGrandTotal` / `ShowColumnGrandTotal` (the Analyst check boxes); subtotals stay at Spotfire's
default (change them with `postScript`: `content.ColumnSubtotals.HideAll()`). `coloring` = one object
or a list with optional `measures` = display names (aliases) or the measure expressions (resolved to
their display names). Without `measures` the coloring is `Colorings.DefaultNumericReference` (reused
when present, else a new coloring named "Numeric"): every numeric measure without its own coloring.

**summaryTable**: `columns` = column names (absent = every numeric column, `AutoAddNewColumns = True`);
`statistics` = aggregation method names (`Count`, `Avg`, `Min`, `Max`, `Sum`, `StdDev`, ...; the accepted
set is **Not yet tested**, T7); a rejected name fails the step, the accepted ones stay. No coloring.

**graphicalTable**: `rows` = category expression or levels (wrapped like cross-table axes).
`columns[]` share `kind`, `title`, `width`, `expression`, `settings` (relative to the miniature
visualization, for example `{"LineWidth": 2, "ShowStopValue": true}`, `{"IconSize": 14}`); per kind:

| kind | fields |
|---|---|
| `sparkline` | `expression` (Y, aggregated), `x` (time / category axis, verbatim), `color` (line), `individualScaling` |
| `calculatedValue` | `expression`, `coloring.rules` (font style Regular) |
| `icon` | `expression`, `coloring.rules`; a rule may add `shape` (MarkerType name, default `Circle`; dxpgen can check names with `scripts/sfapi.py enum MarkerType`) |
| `bulletGraph` | `expression`, `comparative`, `color`, `comparativeColor`, `ranges` [{`expression`, `color`, `label`}] (sets `ShowColorRanges`) |

`rules` directly on the column is accepted for `coloring.rules`. Miniatures have rules only (no
categorical / gradient / fixed / default). Rules are appended in spec order (first = highest
precedence, **Not yet tested** T11) and may carry `settings` (relative to the rule, for example
`ManualDisplayName`); a rule whose settings fail is removed. Rule values: numbers keep their JSON type,
`min` / `max` / `median` / `average`, `NN%`, any other string = expression with `[$Name]` ->
`DocumentProperty("Name")`. `equal`: a number or keyword -> threshold rule; a literal string -> string
rule; `[$Name]` -> string rule when the property is a String (spec type, else its current value),
threshold rule otherwise. Bullet range expressions get the same `[$Name]` translation; axis expressions
are passed verbatim.

**kpiChart**: `kpis[]` = {`title`, `value` (required), `comparative`, `time`, `tileBy`, `coloring`,
`settings` (relative to the KpiVisualization, for example `{"ShowSparklineScale": false, "EmptyTileText":
"-"}`)}. `tileBy` is wrapped like a categorical axis (`"[Station]"` -> `<[Station]>`, absent -> `<>`
= one tile). `time` is verbatim (absent -> `<>`); `ShowSparkline = bool(time)`. `SortColumn = THEN
[Y.FinalValue]` on every KPI (HighestFirst / LowestFirst need it on all). KPI `coloring` colors the
tiles on `THEN [Y.FinalValue]`; the visual-level `coloring` is the default for KPIs without their own.
Chart layout through visual `settings`: `MinTilesPerRow`, `MinVisibleTiles`, `NewRowPerKpi`,
`ShowTitlesForKpis`, `AdditionalSpacingBetweenKpis`, `PreferredRelativeTileWidth`, `SortMode`
(`[api 14.0]` / `[api 7.8]`; never the obsolete `PreferredTileWidth`).

**Coloring objects** (table / crossTable cells, KPI tiles) follow the "Coloring" section of
[spec-format.md](spec-format.md), implemented by 65_coloring: categorical | gradient | fixed are exclusive
backgrounds; rules sit above the background in spec order; cells no rule matches stay uncolored
(`DefaultColor #00000000`) unless `default` / `fixed` is given. Details and persisted shapes:
[api-coloring.md](api-coloring.md).

## 3. Verified recipes (condensed)

```python
visual = page.Visuals.AddNew(VisualTypeIdentifiers.Table)      # Visual; content via As[T]()
tbl = visual.As[TablePlot]()
tbl.Data.DataTableReference = dt                                # first
tbl.AutoAddNewColumns = False
tbl.TableColumns.Clear(); tbl.TableColumns.Add(col)             # display order = Add order; no Move/Insert
found, tc = tbl.TableColumns.TryGetTableColumn(col); tc.Width = 120   # width keyed by column
tbl.SortInfos.Clear(); tbl.SortInfos.Add(col, TablePlotColumnSortMode.Descending)
c = tbl.Colorings.AddNew("Status"); tbl.Colorings.AddMapping(CategoryKey("Status"), c)  # key = column name

ct = visual.As[CrossTablePlot]()
ct.MeasureAxis.Expression = "Avg([Flow]) as [Avg Flow], Count() as [Rows]"   # aliases first
ct.RowAxis.Expression = "<[Station] NEST [Pump ID]>"
ct.ColumnAxis.Expression = "<[Status] NEST [Axis.Default.Names]>"
ct.ShowRowGrandTotal = True
c = ct.Colorings.AddNew("Avg Flow"); ct.Colorings.AddMapping(CategoryKey("Avg Flow"), c)  # key = alias

st = visual.As[SummaryTable]()
st.AutoAddNewColumns = False
st.Columns.Clear(); st.Columns.AddNew("Flow Rate (bbl/d)")      # column NAME, not a DataColumn
st.Aggregations.Clear(); st.Aggregations.AddNew("Avg")

gt = visual.As[GraphicalTable]()                                # namespace ...Visuals.Miniatures
gt.RowAxis.Expression = "<[Pump ID]>"
gt.SortInfos.Clear(); gt.Columns.Clear()
column, spark = gt.Columns.AddNew[SparklineMiniatureVisualization]()   # out param -> tuple
spark.XAxis.Expression = '<BinByDateTime([Timestamp],"Year.Month.DayOfMonth",2)>'
spark.YAxis.Expression = "Avg([Flow Rate (bbl/d)])"; spark.LineColor = color("#333C66")
column, calc = gt.Columns.AddNew[CalculatedValueMiniatureVisualization]()
calc.ValueAxis.Rules.AddThresholdRule(op, cv, color, FontStyleFlags.Regular)   # 12.5 overload
column, icon = gt.Columns.AddNew[IconMiniatureVisualization]()
icon.IconAxis.Rules.AddThresholdRule(op, cv, color, MarkerShape(MarkerType.Circle))
column, bullet = gt.Columns.AddNew[BulletGraphMiniatureVisualization]()
bullet.ComparativeValueExpression = "..."; band = bullet.ColorRanges.AddNew(color, "Low"); band.Expression = "..."

kc = visual.As[KpiChart]()
kc.KpiCollection.Clear(); content = kc.KpiCollection.AddNew(); content.Title = "Average Flow"
kpi = content.Visualization                                      # KpiVisualization, own Data
kpi.YAxis.Expression = "Avg([Flow])"; kpi.TileAxis.Expression = "<[Station]>"
kpi.XAxis.Expression = "<>"; kpi.ShowSparkline = False; kpi.ComparativeAxis.Expression = "..."
kpi.SortColumn.Expression = "THEN [Y.FinalValue]"
kpi.ColorAxis.Expression = "THEN [Y.FinalValue]"; coloring = kpi.ColorAxis.Coloring
```

Facts the code relies on:
- A new visual is bare (`AddNew` does not call `AutoConfigure`): clear every collection that is
  filled and set every axis; never call `AutoConfigure()` after the axes.
- Marking: in live builds on Analyst 15.0, `AddNew` gave other charts and tables the default marking but
  left KPI charts and cross tables without one. `vis_common` therefore sets `Data.MarkingReference` on
  every visual (the default marking when the spec names none); in apps with features the standard engine
  sets the default marking on KPI charts and cross tables explicitly.
- `AddNew` always appends (`KpiCollection`, graphical `Columns`, `Aggregations`, `Colorings`).
- Out parameters return tuples: `found, tc = TryGetTableColumn(c)`, `column, mini =
  gt.Columns.AddNew[T]()` (`scripts/sfapi.py chain` resolves them); the code also accepts a bare column
  (`.Visualization`).
- Keys: table colorings by column name; cross-table colorings, formats and `SortRowsCategory` by the
  measure display name = its alias, else the expression without column brackets (`Sum([Flow])` ->
  `Sum(Flow)`). Renaming an alias orphans entries.
- `MeasureAxis` is typed `ColorAxis`, but cross-table cell colors live in `Colorings`.
- Each KPI owns a `VisualizationData`; chart and KPIs persist the same `DataTable`, `Marking`,
  `Filterings`, `UseActiveFiltering`, `MarkingCombinationMethod`, `LimitingMarkingsEmpty*`, hence the
  `.data` mirror step.
- `ShowSparkline` is independent of `XAxis` (saved analyses show a time axis with false and `<>` with
  true). `KpiXAxis` persists `supportsAxisModes: true` with both continuous and categorical sub-axes.
- `SummaryTable.Columns` (`SummaryTableVisibleColumnCollection`) is flagged DoNotUseOutsideAssembly
  but is the only public way to choose summary-table columns.

## 4. Pitfalls

1. Collections and axes are get-only (`TableColumns`, `SortInfos`, `Colorings`, `KpiCollection`,
   `Columns`, `Aggregations`, `Rules`, `ColorRanges`): call their methods, never assign them.
2. Bind the data table before columns and axes. `TryGetTableColumn` is `False` for a column the
   table does not show: add columns before widths and colorings.
3. `TableColumnCollection` has no `Move` / `Insert`: order = add order. The obsolete
   `TablePlot.Columns` (EditorBrowsable Never) must not be used.
4. Tables and graphical tables sort with `TablePlotColumnSortMode`; cross and summary tables with
   `Spotfire.Dxp.Data.SortOrder`.
5. `CreateLiteral(7000)` is an Integer literal; Real data wants `7000.0`. Spec numbers keep their
   JSON type in cross-table colorings, KPI tile colorings and graphical-table rules; only table
   cell colorings are typed like the (first) colored column. Write `180.0` for Real measures, `3`
   for `Count()`.
6. Use the `FontStyleFlags` / `MarkerShape` rule overloads; the `FontStyle` ones are obsolete.
7. `GraphicalTable` and the miniatures live in `Spotfire.Dxp.Application.Visuals.Miniatures`.
8. Not public, do not try: table header styles, cross-table per-column widths and header styles,
   KPI / graphical-table click actions (`PlotActions`), summary / graphical table colorings.
9. Number formats: tables use data-table-wide column formatters (`DataColumn.Properties.Formatter`,
   20_data `columns[name].format`); cross tables, KPI axes and calculated values own `Formatting`
   slots per result type (reach them with `settings` / `postScript`).

## 5. Not yet tested (each marked in the code)

| # | question | smallest check |
|---|---|---|
| T1 | `vis_common` re-assigning the same `DataTableReference` keeps columns, sort, widths, colorings | build the fragment; `TableColumns.Count` equals the spec |
| T2 | `TableColumn.Width` persists as `TableColumns.Widths[column Id]` | save, open the saved DXP with `verify_dxp.py dump`, look for the widths |
| T3 | `SortInfos` order = sort priority | ties in the first sort column ordered by the second |
| T4 | unaliased measure display name as coloring key | coloring on `Sum([Flow])` targeted as `Sum(Flow)` |
| T5 | which grand total each `totals` flag draws; subtotal default on nested rows | `totals.rows` true on two row levels |
| T6 | untargeted cross-table coloring (`DefaultNumericReference`) colors every numeric measure without its own | the fragment's `Readings` column gets the bottom-3 color |
| T7 | accepted summary-table method names | AddNew for Count, Sum, Avg, Min, Max, Median, StdDev, UniqueCount, Q1, Q3 |
| T8 | `gt.Columns.AddNew[T]()` returns `(column, miniature)` | the build succeeds (fallback reads `column.Visualization`) |
| T9 | sparkline X accepts continuous `[Timestamp]` as well as `<...>` | sparkline renders |
| T10 | miniature columns follow the graphical table's data (table, marking, limits) | mark rows; the sparklines react |
| T11 | graphical rule precedence = list order (first wins) | overlapping greaterThan rules: the first color shows |
| T12 | Integer literal vs Real values (and vice versa) in rules | `{"type": "greaterThan", "value": 180}` on a Real measure |
| T13 | expression condition values (`DocumentProperty("X")`), also inside a string rule | the fragment's `[$AlertThreshold]` and `[$SelectedPumpId]` rules color cells |
| T14 | what an expression rule may reference ([api-coloring.md](api-coloring.md) U10) | `[Status] = "Tripped"` rule renders |
| T15 | bullet `ColorRange.Expression` is the band's upper bound | two bands end at their expressions |
| T16 | a new KPI inherits the chart table | `kpi.Data.DataTableReference` right after AddNew |
| T17 | `KpiXAxis` takes a continuous time expression | `"time": "[Timestamp]"` renders a sparkline |
| T18 | KPI tiles follow the KPI-level marking / limits / filtering | the fragment's KPI chart empties to the marked pumps |

The fragment is `assets/examples/fragments/tables.json`. Coloring-side items (rule precedence above a
background U3, one-color palette, numeric / Boolean category keys U6) are listed in
[api-coloring.md](api-coloring.md).

## 6. Persisted fields for verify_dxp

Expected values: `created.tableVisuals[id]` (exact strings and names the builder set) and
`created.coloring[target]`. Colors persist as `Color(#AARRGGBB)` (spec `#RRGGBB` -> `#FFRRGGBB`);
expressions as set (compare after whitespace normalization). Type ids `Spotfire.Table`,
`Spotfire.CrossTable`, `Spotfire.KpiChart`, `Spotfire.KpiVisualization` are seen in saved analyses;
`Spotfire.SummaryTable`, `Spotfire.GraphicalTable` and the miniature ids `Spotfire.<Name>` are inferred
(**Not yet tested**: compare with the first saved build). `verify_dxp.py check` does not compare cell
colorings, KPI tile colorings, graphical-table columns or summary-table statistics yet.

| visual | check |
|---|---|
| table | `InternalContent: TablePlot` -> `TableColumns.Items` = `DataColumn "<name>"` in `columns` order; `AutoAddNewColumns`; `TableColumns.Widths` `KeyValuePair<Guid, Int32>` (key = the DataColumn node's `Id`; resolve to the name); `SortInfos.Items` (DataColumn order) + `SortModes` (`TablePlotColumnSortMode.*`) |
| table coloring | `Coloring: ColoringCollection` -> `Mappings` (`CategoryKey` `Parts[0]` = column name) -> `Items[Guid]` = `Coloring "<columns joined by ', '>"`; rules and background as in [api-coloring.md](api-coloring.md) |
| crossTable | `RowAxis` / `ColumnAxis` / `MeasureAxis` -> `ExpressionTexts.Expression` = `rowAxis` / `columnAxis` / `measureAxis`; `ShowRowGrandTotal`, `ShowColumnGrandTotal`; `Coloring.Mappings` keyed by `measureNames`; untargeted = `DefaultNumericReference -> Coloring` with the spec rules |
| summaryTable | the `columns` and `statistics` names under the `SummaryTable` node (field names unknown) |
| graphicalTable | `RowAxis` = `rowAxis`; one column per spec entry in order with `Title`, `Width` and the miniature: sparkline `XAxis` / `YAxis`, `LineColor`, `IndividualScaling`; calculated value `ValueAxis` + rules; icon `IconAxis` + rules (shape); bullet `ValueAxis`, `ComparativeValueExpression`, `ValueColor`, `ComparativeValueColor`, `ShowColorRanges`, `ColorRanges` (`DisplayName`, `Expression`, `Color`) |
| kpiChart | `KpiCollection.Items` in spec order -> `KpiContent.TitleExpression` = title (`${AutoTitle}` when absent) -> `MiniatureVisualization: KpiVisualization` -> `YAxis` = value, `TileAxis`, `XAxis`, `ComparativeAxis`, `SortColumn` (`THEN [Y.FinalValue]`), `ShowSparkline`, `ColorAxis` `THEN [Y.FinalValue]` + `Rules`; each KPI `Data` (`DataTable`, `Marking`, `Filterings`, `WhereClauseExpression`, `UseActiveFiltering`) equals the chart `Data`; chart `MinTilesPerRow` etc. from `settings` (`PreferredRelativeTileWidth` persists as `PreferredTileWidth`, a double; inferred, **Not yet tested**) |
