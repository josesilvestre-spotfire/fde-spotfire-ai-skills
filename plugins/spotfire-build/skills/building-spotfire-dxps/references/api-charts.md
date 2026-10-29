# Chart visuals and vis_common

Owner: `scripts/lib/60_charts.py` (`vis_line`, `vis_bar`, `vis_combination`, `vis_scatter`,
`vis_scatter3d`, `vis_pie`, `vis_box`, `vis_heatmap`, `vis_treemap`, `vis_waterfall`,
`vis_histogram`, and `vis_common`, which every visual module calls last). Public API only. Newest
member `IndividualScalingMode.Dual` [api 10.9], so everything runs on 14.6. Members:
`scripts/lib/60_charts.members.txt`, setters: `scripts/lib/60_charts.set.txt` (both pass
`scripts/sfapi.py has`). Coloring, reference layers and fitting models are built by
`scripts/lib/65_coloring.py` ([api-coloring.md](api-coloring.md)).
Tags: CORPUS = seen in the saved XML of DXPs built in Analyst; DOC = Spotfire's property
documentation; U<n> and T<n> = **Not yet tested** items (section 5).

## 1. Build sequence and report

Every chart builder:
1. `B.table_or_default(table)`, the required fields and every expression string. A missing table or
   field raises before the visual exists.
2. `page.Visuals.AddNew(VisualTypeIdentifiers.X)` (returns the `Visual`), then `visual.As[X]()` (the
   content), then `content.Data.DataTableReference = table` (axis expressions resolve against it).
   `AutoConfigure()` is never called: it picks columns and may overwrite axes. `AddNew` auto-places
   the visual; `50_pages` applies the layout afterwards.
3. One `B.step` per axis, trellis, scale setting and option.
4. `apply_coloring`, then `apply_reference_layers` and `apply_fitting_models` on line, bar,
   combination, scatter, box and waterfall charts and histograms. Other types record a skip.
5. `vis_common` (so `settings` and `postScript` see the finished chart), then
   `IsConfigurationValid()`. False gives a warning, not a failure.

After `AddNew`, nothing raises outside a step, so a failed part never loses the visual. The 65_coloring
functions are looked up when their step runs, so a missing module fails one step.

| step name | target | what |
|---|---|---|
| `chart.axis` | `id/X`, `id/Y`, `id/Z`, `id/Line`, `id/Size`, `id/Shape`, `id/Label`, `id/LineConnection`, `id/Marker`, `id/Sector`, `id/SectorSize`, `id/Measures`, `id/Hierarchy` | one axis expression (a scale title is folded in) |
| `chart.trellis` | `id` | trellis mode, axes, grid |
| `chart.scale.range` / `.log` / `.gridlines` / `.individualScaling` | `id/XScale`, `id/YScale`, `id/ZScale` | one scale setting each |
| `chart.option` | `id/showMarkers`, `lineWidth`, `steps`, `orientation`, `stack`, `sort`, `xReversed`, `labels`, `markerSize`, `dendrograms`, `seriesTypes`, `secondaryScale` | one option each |
| `chart.coloring`, `chart.referenceLayers`, `chart.fittingModels` | `id` | wrappers around 65_coloring (its own steps follow) |
| `chart.common`, `chart.check` | `id` | `vis_common`; `IsConfigurationValid()` |
| `visual.title`, `.description`, `.table`, `.marking`, `.limitByMarking` (`id/<marking>`), `.emptyMarkingBehavior`, `.limitExpression`, `.useFiltering`, `.legend`, `.settings`, `.postScript` | `id` | `vis_common`, in this order |

`B.created["charts"][id]` (JSON): `type`, `table`, `axes` {name: the exact expression set; `Color`
is read back from `ColorAxis.Expression`}, `options` {label: value set}, `scales` {X/Y/Z: {min, max,
log, gridlines, individualScaling: "Trellis"|"Color", title (only when applied)}}, `trellis` {mode
`Panels`|`RowsColumns`, panelBy, rowsBy, columnsBy, rows, columns}, `series` (combination: the
aliased expression, key, kind), `bins` (histogram), `valid`.
`B.created["visualSettings"][id]` (every visual that ran `vis_common`): `title`, `showTitle`,
`description`, `table`, `marking` (null = cannot be marked), `limitByMarkings`,
`emptyMarkingBehavior`, `limitExpression` (as set), `useFiltering`, `legend`, `settings` (paths),
`postScript`.

Warnings (not failures): a scale title on an axis with several measures, or on a combination
chart's Y axis; a value clamped to its documented range; trellis `rows`/`columns` with
rowsBy/columnsBy; `colorBy` on a pie or heat map; secondaryScale or mixed series kinds with a
colorBy other than Column Names; an unmatched secondaryScale entry; a visual limited by its own
marking; a description on a content without one; `IsConfigurationValid()` False.

## 2. Spec fields as the library reads them (dxpgen should validate these)

| type | field -> API |
|---|---|
| lineChart | `x` -> `XAxis`; `y` (one or a list) -> `YAxis`; `lineBy` -> `LineByAxis`; `showMarkers` -> `ShowMarkers`; `lineWidth` (1-10 px) -> `LineWidth`; `steps` -> `SteppedLines` |
| barChart | `x` -> `XAxis`; `y` -> `YAxis`; `orientation` -> `Orientation` (+ `XAxis.Reversed`); `stack` `stacked`/`sideBySide`/`percent` -> `StackMode.Stack`/`None`/`Stack100Percent`; `sort` -> `SortedBars` (+ `XAxis.Reversed`); `labels` -> `LabelVisibility` |
| combinationChart | `x` -> `XAxis`; `series` -> `YAxis` (one measure each), `SeriesType` and `IndexedSeriesType[key]`; `colorBy` -> `ColorAxis` (the series axis, default `<[Axis.Default.Names]>`); `secondaryScale` -> `YAxis.IndividualScalingMode.Dual` + `Scale.IndexedDock[key] = Far` |
| scatterPlot | `x`, `y` (one or a list); `sizeBy` -> `SizeAxis`; `shapeBy` -> `ShapeAxis`; `labelBy` -> `LabelColumn` + `LabelVisibility.All`; `markerSize` (0-100, % of the plot, default 3.5) -> `MarkerSize`; `lineBy` -> `LineConnection.ConnectionAxis`. Unless `MarkerByAxis` contains `baserowid()` the markers aggregate (`ScatterLayer.AggregationEnabled`), so `SizeAxis`, `LabelColumn`, `LineConnection.OrderAxis` and `RotationAxis` must be aggregated (`Avg([X])`, `First([ID])`); a raw one shows "Please specify an aggregation method." and draws nothing (seen in a live build on Analyst 15.0). x, y and color may stay raw (they split). dxpgen rejects it, verify_dxp FAILs it ([api-maps.md](api-maps.md)) |
| scatterPlot3D | `x`, `y`, `z` -> `XAxis`/`YAxis`/`ZAxis`; `MarkerByAxis = "<baserowid()>"`; `sizeBy` -> `SizeAxis` |
| pieChart | `sector` -> `ColorAxis` (categorical); `size` -> `SectorSizeAxis`; `labels` -> `VisualAttributes.LabelVisibility` |
| boxPlot | `x` -> `XAxis` (categorical); `y` -> `YAxis` (a raw column: the box-plot Y axis does not aggregate) |
| heatMap | `x`, `y` -> `XAxis`/`YAxis` (categorical); `value` -> `MeasureAxis`; dendrograms hidden; `coloring` -> `Colorings` (65_coloring) |
| treemap | `hierarchy` (levels, outer first) -> `HierarchyAxis` `<A NEST B>`; `size` -> `SizeAxis` (numeric aggregation); `colorBy` -> `ColorAxis` (continuous only) |
| waterfallChart | `category` -> `XAxis` (categorical); `value` -> `YAxis` |
| histogram | BarChart: `XAxis = "BinByEvenIntervals(<column>, <bins>) as [<column>]"`, `YAxis = "Count()"`; `bins` default 20 |

Every chart: `colorBy` and `coloring` (65_coloring), `trellis`. Line, bar, combination, scatter,
box, waterfall and histogram: `referenceLayers`, `fittingModels`. The builder also accepts
`xScale`/`yScale` on every chart with those axes, `zScale` on the 3D plot, `labels` on waterfalls
and scatter plots, and `labels` as `"all"`, `"marked"` or `"none"` ([spec-format.md](spec-format.md)
lists fewer; dxpgen decides what it allows).

- **Expressions** pass through as written. A bare column name of the visual's table becomes
  `[Name]`. `[$Name]` becomes `DocumentProperty("Name")`, the same rule 65_coloring uses for
  reference layers, applied to axes, `colorBy` and `limitExpression`. Live column choice is plain
  Spotfire syntax and passes through: `Avg([${SelectedMeasure}])`.
- **Categorical-only axes** (lineBy, shapeBy, scatter lineBy, trellis axes, box x, heat-map x/y,
  pie sector, waterfall category, treemap hierarchy) are wrapped in `<...>`. A list of levels is
  nested outer first: `["[Station]", "Pump ID"]` -> `<[Station] NEST [Pump ID]>`. Nothing -> `<>`.
  An `x` list on line, bar, combination and scatter charts is nested the same way. Other axes are
  never wrapped: `<[Station]>` is categorical, `[Timestamp]` continuous (bar `x` included).
- **Several measures** (a `y` list, or commas at the top level of one string): `colorBy` defaults to
  `<[Axis.Default.Names]>` (Column Names). This is the corpus pattern on every multi-measure line
  chart, scatter plot and bar chart. A `categorical` coloring is then keyed by the measure aliases.
  For per-category colors with several measures, write `colorBy: "<[Axis.Default.Names] NEST [Station]>"`.
- **Scale object** `{min, max, log, gridlines, individualScaling, title}`:
  - min/max -> `axis.Range = AxisRange(low, high)`. None keeps that end automatic. Numbers become
    Double on a continuous axis and Int32 indices on a categorical one; ISO text becomes DateTime.
  - log -> `TransformType = Log10`; gridlines -> `axis.Scale.ShowGridlines`.
  - individualScaling -> `IndividualScaling = True`, mode `Trellis` on a trellised chart, else
    `Color` (one scale per color category, or per measure under Column Names).
  - title -> the axis expression's display name (`Sum([F]) as [Flow]`, `<[S] as [Station]>`).
    Spotfire has no axis-title property. Not applied (warned) when the axis holds several measures.
- **Trellis** `{panelBy}` -> `TrellisMode.Panels` + `PanelAxis`; `rows`/`columns` ->
  `ManualRowCount`/`ManualColumnCount` + `ManualLayout`. `{rowsBy, columnsBy}` ->
  `TrellisMode.RowsColumns` + `RowAxis`/`ColumnAxis`; there `rows`/`columns` are ignored (DOC).
  `panelBy: "<[Axis.Default.Names]>"` gives one panel per measure (like Plotly subplots; CORPUS).
- **Combination series** without an alias get Spotfire's own name for an unaliased measure as their
  alias: the expression with the identifier brackets removed. The corpus keys `Sum([Baseline_HHP])`
  as `Sum(Baseline_HHP)`. So `Avg([Motor Current (A)])` becomes
  `Avg([Motor Current (A)]) as [Avg(Motor Current (A))]`, and its coloring key is
  `Avg(Motor Current (A))`. `SeriesType` = the majority kind, and every series also gets
  `IndexedSeriesType[CategoryKey(alias)]`. A `secondaryScale` entry may be the series expression
  (with or without its alias) or the alias alone. With a `colorBy` other than Column Names the
  series are its categories, so per-series kinds and the secondary scale cannot apply (warned).
- **Bar order**: `sort` `descending` -> `SortedBars = True` (largest first, U3); `ascending`
  reverses that through `XAxis.Reversed`. Horizontal bars get `XAxis.Reversed = True`, so the first
  category is on top (every GUI-built horizontal bar chart, CORPUS 4/4).
  Rule: `Reversed = horizontal XOR ascending`, set whenever `orientation` is given or sort is
  ascending/descending.
- **Treemap color** given as a category `<expr>` becomes `UniqueConcatenate(expr)`, because the
  treemap color axis is continuous-only (CORPUS 5 of 11 treemaps). Give `size` and continuous
  colors as aggregations (`Sum(...)`, `Count()`).
- **2D scatter marker-by** is left as Spotfire creates it: GUI scatter plots on raw columns keep
  `<>` and still draw one marker per row (CORPUS). For one marker per category use
  `"settings": {"MarkerByAxis.Expression": "<[Pump ID]>"}` with aggregated x/y.
- **Histogram**: the alias names the X axis after the column; `xScale.title` replaces it.

**vis_common** (`vis_common(visual, content, vspec)`; `visual` may also be the content):

| field | API | rule |
|---|---|---|
| `title` | `Visual.Title` | set exactly as given, `""` included (no `${AutoTitle}`); absent = untouched. A preprocessor expression: `${Prop}` is live, `\${` is a literal |
| `showTitle` | `Visual.ShowTitle` | default true |
| `description` | `Visualization.Description` + `ShowDescription = True` | only when non-empty; warned on contents without it |
| `table` | `Data.DataTableReference` | assigned only when it differs (reference check) |
| `marking` | `Data.MarkingReference` | name -> `B.marking`; present and null = cannot be marked; absent = `DefaultMarkingReference` |
| `limitByMarkings` | `Data.Filterings.Add(marking)` | one step per marking, skipped when already there |
| `emptyMarkingBehavior` | `Data.LimitingMarkingsEmptyBehavior` | only with limitByMarkings; message via `settings` `Data.LimitingMarkingsEmptyMessage` |
| `limitExpression` | `Data.WhereClauseExpression` | `[$Name]` translated |
| `useFiltering` | `Data.UseActiveFiltering` | set only when false (true is the default; 50_pages gives the page its scheme) |
| `legend` | `Legend.Visible` | `{"visible": b}` or a bare boolean |
| `settings` | `apply_settings(content, ...)` | paths relative to the content |
| `postScript` | `run_post_script(code, {visual, content})` | last |

A content without `Data`, `Legend` or `Description` (a text area) skips those fields. Coloring,
reference layers and fitting models are not part of `vis_common`.

## 3. Verified recipes (condensed)

```python
vis = page.Visuals.AddNew(VisualTypeIdentifiers.LineChart)       # Visual (layouts need it)
lc = vis.As[LineChart]()                                           # content: axes, data
lc.Data.DataTableReference = table                                # before any axis
lc.XAxis.Expression = "[Timestamp]"
lc.YAxis.Expression = "Avg([Flow]) as [Flow], Avg([P]) as [P]"   # several measures
lc.ColorAxis.Expression = "<[Axis.Default.Names]>"               # one color per measure
lc.LineByAxis.Expression = "<[Station]>"
lc.Trellis.TrellisMode = TrellisMode.Panels
lc.Trellis.PanelAxis.Expression = "<[Axis.Default.Names]>"       # one panel per measure
lc.YAxis.IndividualScaling = True
lc.YAxis.IndividualScalingMode = IndividualScalingMode.Trellis   # own scale per panel
lc.YAxis.Range = AxisRange(0.0, None)                             # None = automatic end
lc.YAxis.TransformType = AxisTransformType.Log10
lc.YAxis.Scale.ShowGridlines = True                               # on .Scale, not the axis
lc.LineWidth = Int32(2); lc.ShowMarkers = False; lc.SteppedLines = True

cc = page.Visuals.AddNew(VisualTypeIdentifiers.CombinationChart).As[CombinationChart]()
cc.YAxis.Expression = "Sum([V]) as [Volume], Avg([Price]) as [Price]"
cc.ColorAxis.Expression = "<[Axis.Default.Names]>"               # series axis (always categorical)
cc.SeriesType = CombinationChartSeriesType.Bar
cc.IndexedSeriesType[CategoryKey("Price")] = CombinationChartSeriesType.Line   # key = alias
cc.YAxis.IndividualScaling = True
cc.YAxis.IndividualScalingMode = IndividualScalingMode.Dual
cc.YAxis.Scale.IndexedDock[CategoryKey("Price")] = ScaleDock.Far              # right scale

bc.Orientation = BarChartOrientation.Horizontal; bc.XAxis.Reversed = True
bc.StackMode = getattr(StackMode, "None")                        # side by side (keyword member)
bc.SortedBars = True; bc.LabelVisibility = LabelVisibility.All
sp.LineConnection.ConnectionAxis.Expression = "<[Pump ID]>"      # connect markers per pump
s3.MarkerByAxis.Expression = "<baserowid()>"                     # 3D: one marker per row
hm.MeasureAxis.Expression = "Count([Event ID]) as [Events]"; hm.RowDendrogram.Visible = False
tm.HierarchyAxis.Expression = "<[Station] NEST [Pump ID]>"; tm.ColorAxis.Expression = "UniqueConcatenate([Status])"
d = chart.Data
d.Filterings.Add(Document.Data.Markings["Selected Pump"])        # limit by marking
d.LimitingMarkingsEmptyBehavior = LimitingMarkingsEmptyBehavior.ShowMessage
d.WhereClauseExpression = '[Station] = DocumentProperty("SelectedStation")'
d.MarkingReference = None                                        # cannot be marked
```

## 4. Pitfalls

1. `AddNew(VisualTypeIdentifiers.X)` returns the Visual and `AddNew[X]()` the content.
   `LayoutDefinition`, `Remove` and `GetVisualBounds` need the Visual. `As[X]()` returns None on a
   class mismatch.
2. A new chart is bare: no table and no marking. Never call `AutoConfigure()` after the axes are set.
3. Scale appearance is on `axis.Scale` (`ShowGridlines`, `ShowLabels`, `LabelOrientation`). Range,
   log, reversal and individual scaling are on the axis. `ScaleAxis.ShowLabels` does not exist; a
   corpus script lost that setting to a blanket `except`.
4. `AxisMode` is read-only and follows the expression: `<...>` categorical, otherwise continuous.
   Bar/line Y, the box Y and the treemap size are continuous-only; trellis, line-by, marker-by,
   shape, box X, heat-map X/Y and the treemap hierarchy are categorical-only; the treemap color is
   continuous-only. The box-plot Y does not aggregate (give a raw column).
5. No axis-title property: alias the expression. A measure's display name is its series key for
   `IndexedSeriesType`, `IndexedDock`, Column Names colors and per-measure ranges, so alias
   measures and key with the same text.
6. `YAxis.IndividualScaling` (scales per panel, color or dual) is not `LineChart.ShowIndividualScaling`
   (which normalises lines to percent).
7. Enum members named `None` (`LabelVisibility`, `StackMode`, `AxisTransformType`) need
   `getattr(Enum, "None")` (`enum_value`).
8. `Single` properties (`MarkerSize`, `BarWidth`, widths) are wrapped in `Single(...)`; `Int32` ones
   (`LineWidth`, trellis counts) in `Int32(...)`.
9. Units differ (DOC): `LineChart.MarkerSize` px; `ScatterPlot.MarkerSize` percent of the plot
   (default 3.5; a Plotly marker of 6-10 px is roughly 2-4); `ScatterPlot3D.MarkerSize` percent of
   the box; `LineWidth` 1-10 px.
10. `CombinationChart.ColorAxis` is always categorical and defines the series. There is no
    `SecondaryYAxis` member; dual scales are `IndividualScalingMode.Dual` + `Scale.IndexedDock`.
11. A heat map has no `ColorAxis` (cells use `Colorings`); a pie chart has no X/Y (sectors =
    `ColorAxis`, `SizeAxis` scales whole pies only with trellis).
12. `Trellis.ManualRowCount` and `ManualColumnCount` work in Panels mode only; setting either sets
    `ManualLayout` (DOC).
13. A visual whose own marking is in its `Filterings` cannot be marked (DOC); detail visuals need a
    second marking.
14. Visuals on an API-made page ignore the filter panel until the page has a filtering scheme
    (50_pages assigns it).
15. Titles and descriptions are preprocessor expressions: escape a literal `${` as `\${`.

## 5. Not yet tested (each marked in the code)

Each item needs a run in Analyst 15.0.

| # | question | where |
|---|---|---|
| U1 | Axes the spec leaves out keep what `AddNew` gives them (expected `<>`/empty: color with one measure, line-by, 2D marker-by, size, shape) | `_charts_new` |
| U3 | `SortedBars` puts the largest bar first, and `Orientation = Horizontal` does not reverse X by itself | `_charts_set_bar_order` |
| U4 | Dual mode plus `IndexedDock[key] = Far` gives exactly one left and one right Y scale | `_charts_set_secondary` |
| U8 | `getattr(LabelVisibility, "None")` / `getattr(StackMode, "None")` | `_charts_set_labels`, `_charts_set_stack` |
| U11 | `BinByEvenIntervals([c], n)` without `<>` draws one bar per bin, filling it | `vis_histogram` |
| U13 | Dendrogram visibility of a new heat map (GUI ones persist hidden) | `_charts_hide_dendrograms` |
| U14 | What `IsConfigurationValid()` reports on a fully configured chart | `_charts_check` |
| U21 | Indexer assignment `IndexedSeriesType[CategoryKey(alias)] = ...` / `IndexedDock[...]` from IronPython | `_charts_set_series_types` |
| U24 | `AxisRange` with `DateTime` ends on a date axis | `_charts_bound` |
| T1 | `Visual.Title = ""` persists an empty `TitleExpression` (no `${AutoTitle}`) | `_charts_set_title` |
| T2 | How 15.0 shows a description with `ShowDescription = True` | `_charts_set_description` |
| T3 | An alias on a nested categorical axis (`<[A] NEST [B] as [T]>`), and whether the `Expression` setter throws on invalid text (the builder falls back to the untitled expression) | `_charts_set_axis` |
| T4 | Scatter line connections follow the X order with `OrderAxis` left empty (as in the corpus) | `vis_scatter` |
| T5 | Which label parts (category, percentage, value) a new pie shows with `LabelVisibility.All` | `vis_pie` |
| T6 | Categorical colors keyed by category values apply on the `UniqueConcatenate` treemap color axis | `vis_treemap` |
| U22 | A 15.0 pie is still persisted under `ScatterLayer.PieMarker` (verifier) | section 6 |

## 6. Persisted fields for verify_dxp

All are under `Visual` (`TitleExpression.Expression`, `ShowTitle`) and its `InternalContent: <Class>`
(`TypeId.Name` `Spotfire.LineChart`, `Spotfire.BarChart`, `Spotfire.CombinationChart`,
`Spotfire.ScatterPlot`, `Spotfire.ScatterPlot3D`, `Spotfire.PieChart`, `Spotfire.BoxPlot`,
`Spotfire.HeatMap`, `Spotfire.Treemap`, `Spotfire.WaterfallChart`; histogram = `Spotfire.BarChart`).
Axis expressions are at `<axis>.ExpressionTexts.Expression`.

| built | outline path |
|---|---|
| description | `DescriptionExpression.Expression`, `ShowDescription` |
| table, marking | `Data.DataTable -> DataTable "<name>"`, `Data.Marking -> DataMarkingSelection "<name>"` (or `null`) |
| limitByMarkings | `Data.Filterings.Items[i].Reference -> DataMarkingSelection "<name>"`; `Data.LimitingMarkingsEmptyBehavior`, `Data.LimitingMarkingsEmptyMessage` |
| limitExpression, useFiltering | `Data.WhereClauseExpression` (`ManagedExpression.Expression` or `null`), `Data.UseActiveFiltering`; page scheme `Data.ActiveFiltering` |
| legend | `Legend.Visible` |
| line/bar/combination/box/waterfall/heat-map axes | `X: ScaleAxis "X"`, `Y: ScaleAxis "Y"`, `Color: ColorAxis "Color"`, line `Line: GroupByAxis "Line"`, heat map `Measures: HeatMapMeasureAxis` |
| scatter axes | under `ScatterLayer`: `X`, `Y`, `Color`, `Size: SizeAxis`, `Shape: ShapeAxis`, `Marker: GroupByAxis`, `LabelColumn`, `LabelVisibility`, `MarkerSize`, `LineConnection` (`Line` = connection axis, `Order`) |
| 3D axes | `X`/`Y`/`Z: ScaleAxis3D`, `Color`, `Size`, `Marker: GroupByAxis` (`<baserowid()>`) |
| pie | `ScatterLayer.PieMarker.Color` (sectors), `.SectorSize`, `.VisualAttributes.LabelVisibility` (11.3 corpus only, U22) |
| treemap | `Hierarchy: TreemapHierarchyAxis`, `Size: TreemapSizeAxis`, `Color` |
| scales | `<axis>.Range`, `.TransformType`, `.Reversed`, `.IncludeZeroInAutoZoom`: `KeyValuePair<CategoryKey, ...>[n]`, `[0].key` = root `CategoryKey` (`Parts: Object[0]`); `Range.value.low/high` = `null` or `Double`/`Int32`/`DateTime`; `<axis>.IndividualScaling`, `.IndividualScalingMode`; `<axis>.Scale.ShowGridlines` (KeyValuePair array); docks `<axis>.Scale.UserSetScaleDock` (key `Parts: ["<alias>"]`, `ScaleDock.Far`) |
| trellis | `Trellis.TrellisMode`, `.Panels`/`.Rows`/`.Columns` (`TrellisAxis` expressions), `.ManualLayout`, `.ManualRowCount`, `.ManualColumnCount` |
| line options | `LineWidth`, `ShowMarkers`, `SteppedLines` |
| bar options | `Orientation: BarChartOrientation.*`, `StackMode: StackMode.*`, `SortedBars`, `SortBy`, `SortSegementsBySize` (sic), `LabelVisibility`, `X.Reversed` |
| combination | `SeriesType`, series types per key, `Y.IndividualScalingMode: Dual` and the docks. No corpus instance: confirm the field names on the first saved build |
| heat map | `RowDendrogram.Visible`, `ColumnDendrogram.Visible` |

Compare expressions after collapsing whitespace. Spotfire may normalise spacing and the case of
`as`, so use `B.created["charts"][id]["axes"]` as the reference for what the builder set.

## Standard engine scatter plot (scripts/engine/builders/scatter.py)

`build_scatter(v, vs)` (**Not yet tested** as a generated builder): `Data.DataTableReference`, the
default marking, `XAxis` / `YAxis` expressions, `WhereClauseExpression`, then `_chart.chart_style`
(colors or the full coloring, y min / log / format, x and y ranges, trellis, fonts, legend, reference
lines, lines and curves) and `_markers.marker_style` (`SizeAxis`, `ShapeAxis` expression and
`DefaultShape`, `LabelColumn` + `LabelVisibility`, `MarkerSize`, `LineConnection.ConnectionAxis`).
Converter `scripts/t3/scatter.py` reads x, y, colorBy, coloring, xScale / yScale (min, max; log y;
individualScaling), limitExpression, referenceLayers, fittingModels, trellis and the marker fields
like `vis_scatter`. Line connections follow the X order unless `settings`
`{"LineConnection.OrderAxis.Expression": "[X]"}` says otherwise; `{"LineConnection.Width": 2}` sets
their width. x and y ranges on line, bar and scatter charts: `axis_ranges` (feature `range`) sets
`AxisRange(min, max)` with None for an automatic end. [engine.md](engine.md) lists the APP keys.

## Standard engine trellis and individual y scaling (scripts/engine/builders/_chart.py, feature trellis)

APP `trellis`: `{"panel": "<[Well Name]>", "rows": 2, "columns": 4}` -> `Trellis.TrellisMode = Panels`,
`PanelAxis.Expression`, `ManualRowCount`, `ManualColumnCount`, `ManualLayout = True` (the counts are used
only in Panels mode with ManualLayout, per the property docs); `{"rowsBy": ..., "columnsBy": ...}` ->
`TrellisMode = RowsColumns`, `RowAxis.Expression`, `ColumnAxis.Expression`. APP `yEach` ->
`YAxis.IndividualScaling = True`, `IndividualScalingMode.Trellis` (trellised) or `Color`. Persisted:
`Trellis {TrellisMode, ManualLayout, ManualRowCount, ManualColumnCount, Panels, Rows, Columns, Pages}`;
the y axis is `Y` on line and bar charts and `ScatterLayer > Y` on scatter plots (`IndividualScaling`,
`IndividualScalingMode`). The same paths work through the visual `settings` escape hatch
(`Trellis.TrellisMode`, `Trellis.PanelAxis.Expression`, `Trellis.ManualRowCount`, ...), set in sorted path
order.
