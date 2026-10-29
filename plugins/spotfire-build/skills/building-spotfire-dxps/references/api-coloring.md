# API reference: coloring, reference layers, fitting models

Owner: `scripts/lib/65_coloring.py`. Spotfire Analyst 15.0, IronPython 3.4. Public API only: every
member is verified with `scripts/sfapi.py has` (`scripts/lib/65_coloring.members.txt`; setters in
`scripts/lib/65_coloring.set.txt`). Newer than 14.6: `ReferenceLayer.Data` and
`ReferenceLayerData.DataTableReference` [api 15.0], used only for a reference layer with `table`.

Evidence: [API] signature in the public API index; [CORPUS] seen in the saved XML of DXPs built in
Analyst. Untagged statements describe the behavior the module relies on; the ones not yet proven on
a live Spotfire are listed under **Not yet tested**.

## Functions

| function | does | report |
|---|---|---|
| `apply_coloring(content, vspec)` | `colorBy`, then `coloring`, on `content.ColorAxis` (charts, KPI and map layer visualizations) or on `content.Colorings` (heat map, table, cross table) as the default numeric coloring. Also accepts `(ColorAxis or Coloring, bare coloring object)` | steps `colorBy`, `coloring` (background), `coloring.rule` per rule, `coloring.settings`; target `<vid>/coloring` |
| `apply_reference_layers(content, layers, vid=None)` | one reference layer per entry | step `referenceLayer` `<vid>/referenceLayers[i]`; a failed layer is removed; `skipped` when the visual has no reference layers |
| `apply_fitting_models(content, models, vid=None)` | one fitting model per entry | step `fittingModel` `<vid>/fittingModels[i]`; a failed model is removed |
| `coloring_configure(coloring, cspec, target, type_name=None, cell=False, record=None)` | any `Coloring` object | as `coloring*` above |
| `coloring_apply_axis(color_axis, cspec, target, expression=None, type_name=None)` | color-by expression (set only when it differs), then the coloring | a failed `colorBy` skips the coloring |
| `coloring_apply_kpi(kpi_visualization, cspec, target)` | KPI tiles: color-by `THEN [Y.FinalValue]`, then the coloring | |
| `coloring_add_cell_coloring(colorings, cspec, target, key=None, name=None, type_name=None, cell=True)` | table / cross-table / heat-map cells. `key` = table column name or cross-table measure display name (alias), or a list sharing one coloring (named after the keys); `None` = `DefaultNumericReference` (reused, else created as "Numeric"). A coloring already mapped to a key is reused | |
| `coloring_expression(text)` | `[$Name]` -> `DocumentProperty("Name")`; numbers -> literal text (`repr`, culture-invariant) | |

70_tables.py uses `coloring_add_cell_coloring` (table columns, cross-table measures) and
`coloring_apply_kpi`; 75_maps.py calls `apply_coloring(layer_viz, {"id", "colorBy", "coloring"})`.
Nothing raises: every item is its own `B.step`; public-API failures are `failed` (no fallback).
`vid` defaults to the target of the enclosing `B.step("visual", <id>)` from 90_build.

Records: `B.created["coloring"][target]` = `{on: colorAxis|cells, expression|key, mode, default,
rules, built, rulesBuilt}` (mode `categorical|gradient|fixed|rules|none|spotfire-default|invalid`);
`B.created["referenceLayers"][vid]` = list of `{index, kind, name, expression,
secondaryExpression, valueAxis, table, color, dash, width, label}`;
`B.created["fittingModels"][vid]` = list of `{index, kind, expression, color, label}`.

## Spec interpretation (owned here)

- **Expressions.** `[$Name]` is spec shorthand, not Spotfire syntax. Every expression this module
  writes (rule values and expressions, gradient `at` text, layer `value` / `low` / `high`, curve
  `expression`) gets `DocumentProperty("Name")`. `colorBy` is written as given; a list of category
  levels becomes `"<[A] NEST [B]>"` (a color axis takes one expression). Curves also map
  `[Axis.X]` -> `x` (the Curve Draw variable [CORPUS: `"x"`]); a curve whose
  `DocumentProperty(...)` form is rejected is retried with `${Name}` and a warning is recorded.
- **Order.** `colorBy` is set first (only when it differs), then the coloring is read and built:
  the axis resets its rules when the expression changes.
- **Background.** `categorical` | `gradient` | `fixed`, exclusive (two = failed step). `rules` or
  `default` without a background = fixed mode: `Clear()`, values no rule matches get `default`.
  Only `settings` = background untouched. The spec is validated and converted before the document
  is touched, so a bad entry leaves the coloring as it was.
- **fixed without colorBy** (and without rules) on a chart sets the color-by to `"<>"` (None), how
  Analyst stores a fixed color [CORPUS: every `"<>"` axis has `ColorRule[0]` + `DefaultColor`].
  Not on pie charts: their color axis holds the sectors, so a pie coloring never needs `colorBy`.
- **categorical.** Reuse the first `CategoricalColorRule` (keeps Spotfire's palette), remove the
  others. `default` -> `SetColors([default])` first (a one-color palette for every unlisted
  category; `SetColors` clears explicit colors), then `SetColorForCategory(CategoryKey(key),
  c)`. Key `"(Empty)"` -> `Coloring.EmptyColor`. Keys are typed like the color-by column when the
  color-by is one plain column (`[Col]` or `<[Col]>`): Integer, LongInteger, Real, SingleReal,
  Boolean; otherwise strings.
- **gradient** (at least 2 points). Reuse the first `ContinuousColorRule`, `IntervalMode.Gradient`,
  breakpoints cleared and added in spec order. `at`: `min` `max` `median` `average` ->
  `ConditionValue` statics; `"NN%"` -> `CreatePercentValue(NN)` (percent of the min..max range
  [CORPUS 25/50/75]); number -> literal; other text -> `CreateExpression`.
- **default** -> `Coloring.DefaultColor` (ignored with `fixed`). Table and cross-table cells with no
  `default` get `#00000000`, so unmatched cells stay uncolored [CORPUS cross-table "Numeric"];
  heat maps keep Spotfire's opaque default [CORPUS heat map `DefaultColor #FFFAA264`].
- **Literals** keep their JSON type (100.0 Real, 3 Integer, beyond Int32 LongInteger) unless the
  target type is known (plain-column color-by, or `type_name`): `CreateLiteral(value, DataType)`.
- **Rules** go above the background rule, as in Analyst (its rule dialog inserts every new rule at
  index 0). Spec order = list order top-down: rule i is added (`Add*` appends) and moved to index
  i, so the first spec rule is the top rule.

| `type` | fields | factory |
|---|---|---|
| `greaterThan` / `lessThan` | `value` | `AddThresholdColorRule(RuleComparisonOperator.Greater / Less, cv, c)` |
| `between` | `low`, `high` | `AddRangeRule(cv_low, cv_high, c)` |
| `equal` | `value` | number, keyword, or a numeric/date color-by -> `AddThresholdColorRule(Equal, ...)`; text -> `AddStringColorRule(StringComparisonOperator.Equal, CreateLiteral(text), c)`; `[$Name]` -> string rule when the property is String (spec `properties`, else its value), else threshold |
| `top` / `bottom` | `count` | `AddTopNRule(Int32, c)` / `AddBottomNRule(Int32, c)` (Int32 overload) |
| `expression` | `expression` | `AddExpressionRule(text, c)` |

Rule values (`value`, `low`, `high`) use the `at` grammar. Optional `settings` on a rule or on the
coloring object go through `apply_settings`, e.g. `{"ManualDisplayName": "Top 3"}`,
`{"EmptyColor": "#FFCCCCCC"}`, `{"SetColorOnText": true}`.

## Reference layers (14.6 reference elements, `content.Layers.AddNewReferenceLayer()`)

| kind | build |
|---|---|
| `horizontalLine` | `ValueAxis.Y`, `Expression = value`, `Line.Enabled`, `Line.Stroke` = default stroke + `WithColor` / `WithStyle` / `WithWidth` |
| `verticalLine` | the same with `ValueAxis.X` |
| `band` | `ValueAxis.Y`, `Expression = high`, `SecondaryExpression = low` [CORPUS 95% CI], `Band.FillEnabled`, `Band.Fill = Fill().WithColor(ci)`, `Line.Enabled = False`, `IsBackground = True`; `dash` / `width` given -> `Band.StrokeEnabled` + `Band.Stroke` (outline) |

- Order: `Name`, then `table` (`Data.DataTableReference`, before the expressions), `ValueAxis`,
  expressions, styles, label, `settings` last.
- `dash`: `solid` `dot` `dash` `double` -> `LineStyle.Single/Dot/Dash/Double`. `width` clamped to
  1..10. A color alpha < 255 becomes `Transparency = 1 - A/255` with an opaque stroke/fill color.
- `label` -> `Name = label`, `Label.Enabled`, style `ShowDisplayName` on, `ShowValue` off; lines
  also `TextAlign.Right` + `VerticalTextAlign.Top`. No label -> name `Horizontal line` /
  `Vertical line` / `Band` (+ ` 2`, ...).
- Vertical bands and one element per row go through layer `settings` (applied last), e.g. event
  windows from another table: `{"ValueAxis": "X", "ElementByAxis.Expression": "<baserowid()>",
  "EvaluationModes": "Color, Trellis"}` with `low` `Min([Start])`, `high` `Min([End])` [CORPUS]. `ElementByAxis` is [api 15.0].
- Supported on BarChart, LineChart, ScatterPlot, CombinationChart, BoxPlot, WaterfallChart (and
  ProbitPlot); other visuals get a `skipped` step.

## Fitting models (Lines & Curves)

`straightLine` -> `FittingModels.AddStraightLineFit()`, curve `.Line`; `curve` ->
`AddCurve(expression)` (validated by the setter, throws on invalid text), curve `.Curve`.
Then `Visible = True`, `Color`, `label` -> `CustomDisplayName` + `ShowInLabel` on the detail named
`"Name"` [CORPUS]. Line style and width via `settings` relative to the model:
`{"Line.LineStyle": "Dash", "Line.Width": 2}` (`Curve.*` for curves; `Width` is Int32 1..10 and
throws outside). In 15.0 each model gets an automatic `FittingModelLayer` in `content.Layers`
[CORPUS]; never create those.

## Facts the code relies on

1. Two color types: rules, `DefaultColor`, `EmptyColor`, `ReferenceCurve.Color` take
   `System.Drawing.Color`; `Stroke` / `Fill` take `ColorInfo(color.ToArgb())` [API].
2. A coloring's mode is its first background rule: Categorical, Continuous (Gradient/Segments),
   none = fixed (`DefaultColor`).
3. A new `ContinuousColorRule` has no breakpoints; Spotfire's chart default gradient is
   MinValue `#CFDBFF` -> MaxValue `#23419F` [CORPUS].
4. `SetColorForCategory` = find-or-add the categorical rule, then set the key; an unknown key is
   stored as a user-added category, not an error.
5. `ConditionValue.CreateLiteral(x)` infers the DataType from the CLR type (`int` Integer, `float`
   Real, `str` String); `CreateExpression` values are DataType String [CORPUS].
6. Cell colorings: `Colorings.AddNew(name)` + `AddMapping(CategoryKey(key), coloring)` (overwrites;
   throws for a coloring of another collection) or `DefaultNumericReference` [API]. Table key =
   column name; cross-table key = measure display name (alias) [CORPUS]. Heat maps and 11 of 12
   corpus cross tables carry a "Numeric" coloring as `DefaultNumericReference`, no mappings [CORPUS].
7. KPI tile color-by is `THEN [Y.FinalValue]` in every corpus KPI [CORPUS].
8. Reference-layer defaults: `ValueAxis.Y`, `EvaluationModes` None, Line / Band fill / Band stroke /
   Label disabled, line stroke width 2 in a theme color [CORPUS]. `Stroke`, `Fill`,
   `LabelStyle` are immutable: assign the `With*` result [API]. `Stroke.WithColor` sets
   `ColorType.Specific`, lightness 0; `Stroke.WithWidth` clamps 1..10.
9. Plain reference lines (`FittingModels.AddHorizontalLine`) accept only the axis itself as a column
   (`Sum([X])` throws); reference layers take aggregations of any column [CORPUS], so the
   module uses layers for lines and bands.
10. `DocumentProperty("name")` is a real calculation method; `[$p]` is not Spotfire syntax.

## Pitfalls

- Spec colors are `#RRGGBB` or `#AARRGGBB` (alpha FIRST, `00_core.color`). Navy at 20 % opacity is
  `#33333C66`; `#333C6633` is alpha 0x33 on `#3C6633` (dark green).
- Never assign get-only objects (`Coloring`, `Colorings`, `Layers`, `FittingModels`, `Breakpoints`,
  `Details`, `Line`, `Band`, `Label`, `Data`, `ElementByAxis`); mutate them.
- `CreateLiteral(7000)` is Integer: write `7000.0` for Real data (or pass `type_name`).
- Callers set the visual's table and every other axis before `apply_coloring` and must not change
  `ColorAxis.Expression` afterwards (it wipes the rules).
- CombinationChart colors by category only (a gradient logs a warning).
- Reference-layer and curve expressions are validated against the visual's axes: build them after
  the axes. Date values: prefer `DateTime(2025,5,31,0,0,0,0)` (no string parsing, culture-safe).
- `ColorTranslator.FromHtml("#FF0000") != Color.Red` (named-ness); compare `ToArgb()`.
- Enum members named `None` need `getattr(X, "None")` (not used by this module).

## Not yet tested

| item | where |
|---|---|
| U3 rule precedence = list order, top first, above the background rule | `_coloring_add_rule` |
| U6 numeric / Boolean category keys (typed from the color-by column) | `_coloring_category_part` |
| One-color palette (`SetColors([default])`) colors every unlisted category | `_coloring_background` |
| Fixed / rules-only mode keeps zero rules on a categorical or continuous color-by (invariant keeper) | `_coloring_background` |
| Integer literal vs Real values (and vice versa) when the type is unknown | `_coloring_literal` |
| Expression condition values (`DocumentProperty("X")`, `Avg([Axis.Color])`), also inside a string rule | `_coloring_condition`, `_coloring_equal_rule` |
| U10 what an expression rule may reference (`[Axis.Color]`, columns) | `_coloring_add_rule` |
| U2 `DocumentProperty("X")` as a reference-layer value; the line follows the property | `_coloring_configure_layer` |
| U8 ColorInfo alpha vs `Transparency`; `Transparency` fades the whole layer | `_coloring_colorinfo`, layers |
| Band outline (`Band.StrokeEnabled`) draws both band edges | `_coloring_configure_layer` |
| Label placement (`Right` + `Top`) and label text = layer name | `_coloring_configure_layer` |
| U11 curve property form: `DocumentProperty("X")` or `${X}` (both tried) | `_coloring_build_model` |
| Band from another table with `ElementByAxis <baserowid()>`: one band per row | layer `settings` |
| U13 date literal forms on a date axis (`DateTime(2025,5,31,0,0,0,0)`, `Date("2025-05-31")`) | spec values |

## Persisted fields for verify_dxp

Paths in the saved document XML of a DXP ([dxp-anatomy.md](dxp-anatomy.md) sections 6.2 and 6.3).

| spec | look for |
|---|---|
| `colorBy` | `Color: ColorAxis "Color"` -> `ExpressionTexts` -> `Expression` (exact string; `"<>"` for a fixed color) |
| coloring | `Rules: Coloring` -> `DefaultColor: Color(#AARRGGBB)`, `EmptyColor`, `Items: ColorRule[k]` in spec order: conditional rules first, background last. Ignore `DefaultCategoricalRules`, `DefaultContinuousRules`, `DefaultDefaultColor` |
| categorical | `CategoricalColorRule` -> `UserSetColors: KeyValuePair<CategoryKey, Color>[k]` (`Parts: [0]: "<key>"`), `Palette` = `[default]` when given |
| gradient | `ContinuousColorRule` -> `Breakpoints` -> `ColorBreakpoint` {`ValueKeeper.InnerValue` {`Value`, `ValueType: ConditionValueType.MinValue/MaxValue/AverageValue/MedianValue/Literal/Percent/Expression`, `DataType`}, `Color`}, `IntervalMode.Gradient` |
| fixed | `Items: ColorRule[0]`, `DefaultColor` |
| rules | class names `ThresholdColorRule`, `RangeColorRule`, `StringColorRule`, `TopBottomColorRule`, `ExpressionColorRule` in spec order (field names not in the corpus: check class and order; colors and values **Not yet tested**) |
| cell coloring | `Coloring: ColoringCollection` -> `Mappings: KeyValuePair<CategoryKey, Guid>[k]`, `Items`, `DefaultNumericReference: -> Coloring "Numeric"` |
| KPI coloring | `KpiContent` -> `MiniatureVisualization: KpiVisualization` -> `ColorAxis` expression `THEN [Y.FinalValue]` + `Rules` |
| reference layer | `InternalLayers` -> `ReferenceLayer "<Name>"`: `Value` / `SecondaryValue` (`ReferenceValueColumn`) -> `Expression` (after `[$p]` -> `DocumentProperty("p")`), `Line` {`Enabled`, `Stroke` {`style: LineStyle.X`, `color.color.argb`, `type: ColorType.Specific`, `width`}}, `Band` {`FillEnabled`, `Fill.attributes.color.argb`, `StrokeEnabled`, `Stroke`}, `Label` {`Enabled`, `Style.showDisplayName`, `showValue`, `textAlign`, `verticalTextAlign`}, `IsBackground`, `Transparency`; 15.0: `Data: ReferenceLayerData` {`ValueAxis`, `EvaluationModes`, `Width`, table (null = the visual's)} (14.6 copy: `ValueAxis` on the layer, the table only in the `QualifiedNameMapper`) |
| fitting model | `FittingModels` -> `Items` -> `StraightLineFittingModel` / `ReferenceCurveFittingModel` {`Enabled`, `Curves: ReferenceCurve "line"/"curve"` {`Expression`, `Color: ColorInfo argb`, `LineStyle`, `Width`, `Visible`, `CustomDisplayName`, `Details` -> `CurveNameReferenceItemDetail "Name"` `ShowInLabel: true`}}; 15.0 also `InternalLayers` -> `FittingModelLayer` |

ARGB check: `"%08X" % (argb & 0xFFFFFFFF)`; `#333C66` = -13419418, `#E94165` = -1490587,
`#3050EF` = -13610769.

## Standard engine (scripts/engine/features/coloring.py)

The library's coloring rules ported to the standard engine (feature `coloring`; **Not yet tested**
as a generated builder). `scripts/t3/_coloring.py` converts each spec coloring object
([spec-format.md](spec-format.md) "Coloring") at generation time (values typed, `[$Name]`
translated, equal rules decided as string or threshold rules), so the engine only calls the API.
[engine.md](engine.md) describes the APP coloring object.

| engine function | does | lib equivalent |
|---|---|---|
| `argb(value)` | `#AARRGGBB` -> `Color.FromArgb(a, r, g, b)`, `#RRGGBB` / `@name` -> `rgb()` | `color()` |
| `cond(value)` | `min`/`max`/`median`/`average` -> `ConditionValue` statics, `NN%` -> `CreatePercentValue`, float -> `CreateLiteral(Double, DataType.Real)`, int -> Integer (LongInteger beyond Int32), bool -> `CreateLiteral(bool)`, other text -> `CreateExpression` | `_coloring_condition` |
| `keep_one(coloring, categorical)` | reuse the first categorical / continuous rule, remove every other rule | `_coloring_keep_one` |
| `background(coloring, spec, cell)` | categorical (`SetColors([default])` first, `SetColorForCategory`), gradient (`IntervalMode.Gradient`, breakpoints cleared and added), fixed / rules only (`Clear()`), then `DefaultColor` (fixed, default, or transparent for cells), `EmptyColor` | `_coloring_background` |
| `add_rule(coloring, r, position)` | `AddThresholdColorRule`, `AddRangeRule`, `AddStringColorRule`, `AddTopNRule`, `AddBottomNRule`, `AddExpressionRule`, then `Move(IndexOf(rule), position)`: the first spec rule is the top one | `_coloring_add_rule` |
| `configure(name, coloring, spec, cell)` | background (skipped when the spec has settings only), each rule in its own `ok`, each setting through `set_setting` | `_coloring_configure` |
| `axis_coloring(name, axis, spec)` | a color axis whose expression is already set (charts: core's `colors`; map layers: `map_color_by`) | `coloring_apply_axis` |
| `cell_colorings(content, vs)` / `cell_coloring(...)` | `Colorings.AddNew(", ".join(keys))` + `AddMapping(CategoryKey(key), coloring)` per key (table column names, cross-table measure display names), or `DefaultNumericReference` (created as "Numeric" when absent) | `coloring_add_cell_coloring` |
| `kpi_coloring(name, kpi, spec)` | `ColorAxis.Expression = "THEN [Y.FinalValue]"`, then `configure` | `coloring_apply_kpi` |

Line and bar charts keep the plain `color` / `categories` path for fixed colors and plain categorical
colorings (no `coloring` part needed); the scatter plot uses the same path. Rule `settings` and the
categorical default on a pie chart are library-only. Fitting models (Lines & Curves) are built by
`add_curve` in `scripts/engine/builders/_chart.py` (feature `fitting`): `AddStraightLineFit().Line` or
`AddCurve(expression).Curve` (retried with the `${Name}` form), `Visible`, `Color`, `LineStyle`
(`dash`), `Width`, `CustomDisplayName` and the `Name` detail shown in the label.
