# Prototype to Spotfire mapping

How each prototype construct becomes a Spotfire element in the draft `spec.json`
(`spec-draft.md`). Section 1 maps pages and layout, inputs, outputs, figure details, reactivity,
data, value boxes and text. Section 2 lists the constructs with no direct Spotfire equivalent
(gaps G1 to G13) with ranked substitutes. Section 3 is a worked example. Section 4 is the
extraction checklist.

Fidelity, written into the mapping table for every element:

| Fidelity | Meaning |
|---|---|
| EXACT | Same behaviour |
| CLOSE | Same purpose, small visual difference |
| SUBSTITUTE | Different mechanism, same user outcome. The owner approves it before the build |
| MANUAL | Not buildable: a manual step after the build, or dropped. The owner approves it |

Spotfire behaviour below was seen on Spotfire Analyst 15.0. Items marked **Not yet tested** have
not been confirmed in a live Analyst session.

The draft uses only what the standard engine of the `building-spotfire-dxps` skill builds
(`spec-draft.md`, "What the standard engine builds"). Mappings marked *slim tier* below need that
skill's slim tier: the draft uses the next substitute instead, and the mapping table names both,
so the owner can ask for the slim tier.

## 1. Mapping tables

### 1.1 Pages and layout

| Prototype construct | Draft spec | Fidelity |
|---|---|---|
| Top-level tabs (`page_navbar`, `st.navigation` or `pages/`, Dash pages, Quarto `#` pages, a React tab bar) | One `pages[]` entry per tab, `app.pageNavigation: "Tabs"`; Title Case, no numbering ("1. Data" becomes "Data") | EXACT |
| Tabs inside a page (`navset_*`, `st.tabs`, `dcc.Tabs`, `{.tabset}`, `.panel-tabset`) | No in-page tab container exists. Independent analyses become separate pages; views of the same selection are stacked on one page | SUBSTITUTE |
| Sidebar (`ui.sidebar(width=300)`, `st.sidebar`, `{.sidebar}`, a left `dbc.Col`) | A `textArea` holding the controls, first item of a `row`, `showTitle: false`; weight = sidebar width / canvas width (300 of 1600 gives 18) | SUBSTITUTE |
| Sidebar plus a second input rail | One merged control column | SUBSTITUTE |
| `layout_columns(col_widths=[4, 8])`, `st.columns([0.3, 0.7])`, `dbc.Col(width=4)`, `.column width="40%"` | A `row` with the same weights | EXACT |
| Vertically stacked cards, Quarto rows | A `column`; pixel or percent heights become weights | CLOSE |
| Card with a header (`ui.card_header`, `#| title:`, `dbc.CardHeader`) | One visual per card: the header becomes `title` (`showTitle: true`), a footnote becomes `description` | CLOSE (no per-card border or shadow; the theme styles every visual alike) |
| Columns that only arrange inputs inside the sidebar | Flex rows inside the text-area HTML, not layout | EXACT |
| App title, navbar | A thin header text area at the top of each page (weight 6 to 8 in a root `column`), or nothing (the page tabs carry the names) | SUBSTITUTE |
| Accordion, expander | Always-open sections in the panel (`<details>` does not survive the text-area sanitizer) | SUBSTITUTE |
| Popover, modal, offcanvas | A section of the panel, or its own page | SUBSTITUTE |

Layout tree recipe:

1. Root `column` when a header band or KPI band spans the top, otherwise a root `row`.
2. Sidebar: `row` [sidebar text area, main area].
3. Main area: stacked cards become a `column`, side-by-side cards a `row`. Nested containers
   alternate orientation: a `row` inside a `row` is flattened.
4. Every visual of the page appears exactly once; weights are relative to their siblings.

A full-width trend card above `layout_columns(col_widths=[4, 8])`, under a header band:

```json
"layout": {"column": [
  {"visual": "pageHeader", "weight": 7},
  {"visual": "vibrationTrend", "weight": 55},
  {"row": [{"visual": "alarmSummary", "weight": 4}, {"visual": "pumpTable", "weight": 8}],
   "weight": 38}
]}
```

### 1.2 Inputs to document properties and controls

Each input becomes one document property and one control in a text area. The property name comes
from the input id in PascalCase (`pump_id` becomes `PumpId`, `fc_steps` becomes `FcSteps`); its
type is exact; its default is the prototype default in that type (`72.0` for Real); its
description is the input label. The same name is used for the data function parameter and the
control binding.

| Prototype input | Shiny, Streamlit, Dash, OJS | Control `kind` and values | Property type | Fidelity |
|---|---|---|---|---|
| Select, fixed choices | `input_select`, `st.selectbox`, `dcc.Dropdown`, `Inputs.select` | `dropdown` with `{"fixed": [{"text": label, "value": key}]}` (Shiny dicts, `format_func`, Dash `options` give the pairs) | String or the value type | EXACT |
| Select with choices from data (`ui.update_select`, options built from a column) | same | `dropdown` with `{"column": {"table", "column"}}`: unique values, follows the data, no script | the column type | EXACT |
| Select over DataFrame column names | same | `dropdown` with the names as a fixed list, or a catalog table written by a data function as the `column` source | String | SUBSTITUTE |
| Cascading selects | chained `update_select` | The first property feeds an automatic data function whose output table is the second control's `column` source; that function has `executeAtBuild: true` so the table exists when the control is built. List refresh **Not yet tested** | String | SUBSTITUTE |
| Multi-select | `input_selectize(multiple=True)`, `input_checkbox_group`, `st.multiselect`, `dcc.Dropdown(multi=True)`, `dcc.Checklist` | `multiSelectListbox` on a `listValued: true` property (default a JSON array). A script joins the values into a String property for data functions; a direct data function binding is **Not yet tested**. If it only subsets categories, use a filter or a marking instead | String list | CLOSE |
| Numeric slider | `input_slider`, `st.slider`, `dcc.Slider`, `Inputs.range` | `slider` with `min`, `max`, `step`; at most 1000 positions, otherwise `input` | Integer, Real | EXACT |
| Range slider | `input_slider(value=(a, b))`, `st.slider((a, b))`, `dcc.RangeSlider` | Two properties (`...Min`, `...Max`) with two controls, or a page filter on the column | two numeric | SUBSTITUTE (G10) |
| Date or datetime slider, date range | `input_slider` with datetimes, `input_date_range`, `dcc.DatePickerRange` | No date slider exists: `input` controls on Date or DateTime properties, marking by dragging on the time axis, or a range filter on the time column when it only frames the view | Date, DateTime | SUBSTITUTE (G10) |
| Numeric input | `input_numeric`, `st.number_input`, `dcc.Input(type="number")` | `input` (Spotfire rejects values of the wrong type) | Integer, Real | EXACT |
| Text input, text area | `input_text`, `input_text_area`, `st.text_input`, `st.text_area` | `input`, `multilineInput` | String | EXACT |
| Radio buttons | `input_radio_buttons`, `st.radio`, `dcc.RadioItems` | `radio` (a single-select list box: Spotfire has no radio property control) or `dropdown` | String | SUBSTITUTE |
| Checkbox, switch, toggle | `input_checkbox`, `input_switch`, `st.checkbox`, `st.toggle` | `checkbox` (a Yes/No drop-down on a Boolean property), or a `button` whose script flips a mode | Boolean | SUBSTITUTE |
| Action button | `input_action_button`, `st.button`, `html.Button`, `st.form_submit_button` | `button` with `script` (and `args`) or `action: {"refreshDataFunction": "<name>"}` | | EXACT |
| Navigation link | `input_action_link`, `dcc.Link`, a React route | `link` or `button` with `action: {"gotoPage": "<title>"}` | | EXACT |
| File upload | `input_file`, `st.file_uploader`, `dcc.Upload` | None: data enters at build time (`tables[]`); users replace data through Spotfire's own data menus | | MANUAL (G11) |
| Download | `st.download_button`, `dcc.Download` | Spotfire's own export (File > Export); no control | | SUBSTITUTE |
| Dark-mode switch | `input_dark_mode`, theme toggles | `app.theme.base`, document-wide; drop the control | | SUBSTITUTE |
| Hidden JavaScript bridge inputs | `Shiny.setInputValue`, `selectedData`, `relayoutData`, `on_select` | Marking (1.5) | | SUBSTITUTE |

```json
"properties": [
  {"name": "PumpId", "type": "String", "default": "P-101", "description": "Pump shown on the detail page"},
  {"name": "ForecastHours", "type": "Integer", "default": 72, "description": "Forecast horizon (h)"},
  {"name": "AlarmLevel", "type": "Real", "default": 7.1, "description": "Vibration alarm level (mm/s)"}
]
```

and in the panel text area:

```json
"controls": {
  "pumpId":        {"kind": "dropdown", "property": "PumpId",
                    "values": {"column": {"table": "PUMP_READINGS", "column": "Pump ID"}}},
  "forecastHours": {"kind": "slider", "property": "ForecastHours", "min": 24, "max": 336, "step": 1},
  "alarmLevel":    {"kind": "input", "property": "AlarmLevel"}
}
```

### 1.3 Outputs to visuals

The draft uses the visual types listed in `spec-draft.md`. Other chart kinds are written as the
substitute in the third column and recorded in the mapping table.

| Prototype output | Draft visual and fields | Fidelity |
|---|---|---|
| Line traces over x (`go.Scatter(mode="lines")`, `Scattergl`, `px.line`, `st.line_chart`, Recharts `Line`) | `lineChart`: `x: "[Timestamp (UTC)]"`; `y` one expression or a list (`"Avg([Flow Rate (bbl/d)])"`); `px.line(color=...)` becomes `colorBy: "<[Station]>"`; several measures become a `y` list with `colorBy: "<[Axis.Default.Names]>"`. `lines+markers` (`showMarkers`) and `line_shape="hv"` (`steps`) are *slim tier*: the draft draws the plain line and the mapping table records the difference (CLOSE) | EXACT |
| Markers (`mode="markers"`, `px.scatter`, Recharts `Scatter`) | `scatterPlot`: `x`, `y`, `colorBy`, `sizeBy`, `labelBy`, `markerSize`; a connected path becomes `lineBy`. Unless the markers are one per row, `labelBy` and `sizeBy` are aggregated (`First([Pump ID])`, `Avg([Flow])`) | EXACT |
| `trendline="ols"` | `fittingModels: [{"kind": "straightLine"}]`; LOWESS and other trendlines become a data function output drawn as a series | EXACT or SUBSTITUTE |
| Bars (`go.Bar`, `px.bar`, Recharts `Bar`) | `barChart`: `x` (category), `y`; `orientation="h"` becomes `"horizontal"`; `barmode="stack"` becomes `stack: "stacked"`, `"group"` becomes `"sideBySide"`, `barnorm="percent"` becomes `"percent"`; sorted bars use `sort`; text uses `labels` | EXACT |
| Bars and lines together, `secondary_y=True`, Recharts `ComposedChart` | `lineChart` with several `y` measures, or a `barChart` and a `lineChart` stacked with the same x | SUBSTITUTE |
| Histogram (`go.Histogram`, `px.histogram(nbins=)`) | `barChart` on a binned x (`BinByEvenIntervals`), or a data function that writes the bins | SUBSTITUTE |
| Box or violin | A data function that writes the quartiles, drawn as a `barChart` or `table` | SUBSTITUTE |
| Heatmap, `px.imshow`, correlation matrix | `crossTable` with a gradient cell coloring (rows and columns are the two categories), or a `scatterPlot` with square markers and a gradient color-by. Unpivot a matrix to a long table first | SUBSTITUTE |
| Treemap, sunburst, icicle | Horizontal sorted `barChart` (one level) or `crossTable` with a gradient (two levels) | SUBSTITUTE |
| Pie or donut | Horizontal `barChart` with `sort: "descending"`, or `stack: "percent"` for shares | SUBSTITUTE |
| Waterfall, funnel | Horizontal `barChart` with `sort: "descending"` (funnel); a data function that writes the running steps (waterfall) | SUBSTITUTE |
| Area (`px.area`, `fill="tozeroy"`, Recharts `Area`) | Gap G2 | SUBSTITUTE |
| 3D scatter, surface | `scatterPlot` of two dimensions colored by the third, or a gridded `crossTable` | SUBSTITUTE |
| Contour | A data function that writes contour lines, drawn as a map feature layer or a `scatterPlot` with `lineBy` | SUBSTITUTE |
| Point map (`scatter_mapbox`, `scatter_geo`, `st.map`, pydeck) | `map`: a `tile` layer plus a `marker` layer (`latitude`, `longitude`, `colorBy`, `sizeBy`) | EXACT |
| Choropleth | `map` `feature` layer on a table with a WKB geometry column | CLOSE |
| Density map | A `marker` layer colored or sized by value, or a gridded `feature` layer from a data function (no heat-map layer type exists) | SUBSTITUTE |
| Indicator, gauge, value box, metric | HTML KPI band (1.7) | CLOSE |
| Data table (`render.DataGrid`, `st.dataframe`, `DataTable`, `go.Table`) | `table`: `columns`, `sort`, `widths`, `coloring`; row selection is the table's own marking (1.5) | EXACT |
| Pivot or grouped summary | `crossTable` (`rows`, `columns`, `measures`, `totals`) | EXACT |
| Sparkline, icon or bullet columns | `table` or `crossTable` with cell colorings; sparklines as a trellised `lineChart` | SUBSTITUTE |
| Gantt (`px.timeline`) | X bands from an event table (G1), or swim lanes in a `scatterPlot` | SUBSTITUTE |
| Sankey, parallel coordinates, candlestick, polar, radar | Gap G13 | SUBSTITUTE |
| matplotlib or seaborn picture | Rebuilt natively from the same data | SUBSTITUTE |

### 1.4 Plotly figure details

| Plotly | Draft spec |
|---|---|
| `add_hline(y=v)`, `add_vline(x=t)` | `referenceLayers`: `{"kind": "horizontalLine", "value": "12.3"}`, `{"kind": "verticalLine", "value": "[$ViewDate]"}`; `line_dash` becomes `dash` (`solid`, `dot`, `dash`, `double`), `line_color` becomes `color`, `line_width` becomes `width`, `annotation_text` becomes `label`; a property value is `"[$AlarmLevel]"`. A line on a date axis binds to a DateTime property |
| `add_hrect(y0, y1)` | Two `horizontalLine` reference layers at y0 and y1 with one color. A filled `band` layer (`{"kind": "band", "low": "<y0>", "high": "<y1>"}`) is *slim tier* |
| `add_vrect(x0, x1)` per event | Gap G1 |
| `fill="tonexty"` between an upper and a lower trace | Gap G2 |
| `yaxis_type="log"`, `xaxis_type="log"` | `yScale` or `xScale` `{"log": true}` |
| Axis `range=[a, b]` | Scale `min`, `max` |
| Axis titles | The measure's display name: alias it (`"Avg([Vibration (mm/s)]) as [Vibration]"`). Aliases are also the keys of per-series colors |
| Figure title | Visual `title`; live values with `${Property}` (`"${PumpId} vibration trend"`) |
| `make_subplots(rows=n, shared_xaxes=True)`, one measure per row | One `lineChart` with a `y` list, `trellis: {"panelBy": "<[Axis.Default.Names]>"}`, `yScale.individualScaling: true` |
| `facet_row`, `facet_col`, `facet_col_wrap` | `trellis`: `rowsBy`, `columnsBy`, `panelBy` (and `rows`, `columns` for a fixed grid) |
| Subplots of unrelated charts | Separate visuals in a `column` or `row` |
| `secondary_y` | Two visuals stacked with the same x, or one `lineChart` with both measures when the scales are close |
| Rangeslider, zoom | Spotfire zooms natively (gap G4 for zoom events) |
| `dragmode="select"` | Marking (1.5) |
| `hovermode="x unified"`, hover templates | Spotfire's per-marker tooltip (cosmetic loss) |
| Legend position | `legend.visible`; Spotfire docks legends left or right only |
| `add_annotation(text=...)` | No free-text annotation: a reference-layer `label`, the visual `title` or `description`, or a note in the panel |
| Empty-state annotation ("Run the model first") | `emptyMarkingBehavior: "ShowMessage"` on marking-limited visuals, otherwise a hint in the panel |
| `template="plotly_dark"`, `paper_bgcolor` | `app.theme.base`, document-wide (G7) |
| One `marker_color` or `line.color` | `coloring: {"fixed": "#2DD4BF"}` |
| `color_discrete_map`, per-trace colors | `coloring.categorical`, keyed by category value, or by the measure alias when the series are measures |
| `colorway` | `coloring.categorical` on each visual (Spotfire ignores prototype palettes) |
| `color_continuous_scale` | `coloring.gradient` with `min`, `50%`, `max` breakpoints |
| `opacity` | Band colors as `#AARRGGBB`; series colors are opaque (blend them over the background color yourself) |
| Dashed or dotted data series | Gap G3 |

### 1.5 Reactivity

| Prototype mechanism | Draft spec | Notes |
|---|---|---|
| Input used directly by a view (filter rows, pick a column, title) | The property inside expressions: `limitExpression: "[Pump ID] = DocumentProperty(\"PumpId\")"`, column choice `"Avg([${ViewTag}])"`, `title: "${PumpId}"`. Spotfire re-renders by itself: no script | `"${PumpId}"` inside a quoted limit expression: **Not yet tested** |
| Reactive calc, `@st.cache_data`, a callback that builds a frame from inputs | Data function with `refresh: "automatic"`, `value` inputs bound to the properties (same names), table outputs; `executeAtBuild: true` when visuals use its tables | Re-runs whenever an input changes |
| Button-gated compute (`@reactive.event(input.run)`, `st.form`, `n_clicks`) | Data function with `refresh: "manual"` plus a `button` with `action: {"refreshDataFunction": "<name>"}` | No script |
| A button with several effects (reset state, set properties, run functions in order, notify) | `scripts[]` on a `button`; the script runs the functions in order | Scripts only for side effects |
| State in `reactive.value`, `st.session_state`, `dcc.Store` (label registry, recipe steps) | A String property holding JSON, edited by scripts and parsed by an automatic data function into a table | Saved with the DXP |
| An in-memory fitted model | None (G5): a stateless pipeline | |
| `ui.update_select` with choices from data | `column` value source | Automatic |
| Per-row derived column | A column computed by the data function that writes the table. `calculatedColumns` are *slim tier* | |
| Chart selection (`plotly_selected`, `selectedData`, `on_select`, Recharts `onClick`) | `markings[]` plus the visual's `marking`; detail visuals use `limitByMarkings`; across tables a data function input with `bind.limitByMarking` (`relations[]` are *slim tier*) | EXACT pattern |
| Computation on the selection | Data function table input with `bind.limitByMarking` and `refresh: "automatic"` | Nothing is marked at build time, so the function returns typed empty outputs on an empty table |
| A button that reads the selection | A script that reads the marked rows | |
| Table row selection (`selection_mode="row"`, `row_selectable`) | `table` with its own marking (`"Selected Pump"`) | |
| Click to drill to another page | Marking plus `limitByMarkings` on the target page plus a `link` with `gotoPage` | |
| Zoom and relayout events | None (G4) | |
| Hover events | None: tooltips only | |
| Side effect on a property change | A property trigger. The draft does not write triggers: list it in the mapping table; property triggers have no public API in Spotfire 15.0, so the build skill decides | |
| `dcc.Interval`, auto refresh, streaming | None: the analysis holds stored data | MANUAL (G11) |
| `req()`, validation messages | The data function writes a status value property shown by a `label` control | |

Data function outputs: never predict output names in a script; let the function write a small
manifest table when a script needs to know what it produced. Emit typed empty frames, so a first
run with no rows does not fix String column types.

### 1.6 Data: precomputed or data function

| Prototype data | Draft spec |
|---|---|
| Loaded once, or simulated with a fixed seed and no input dependency | A file in `data/` (SBDF or CSV), `tables[]` with `embed: true` |
| Recomputed when inputs change | Data function (1.5), inputs bound by property name |
| `import simulator` between prototype files | Inline the module into the data function script: a data function cannot import sibling files |
| Excel | Convert to CSV or SBDF; for a calculation workbook use the `ingesting-excel-workbooks` skill |
| `datetime.now()` in a generator | A fixed start date, so builds are reproducible |
| Imports beyond numpy and pandas | Analyst 15.0's Python ships numpy, pandas and the spotfire package only. Install the packages into Spotfire's Python environment, or port the code to numpy (a behaviour change: the owner decides, G12). Guard optional imports |
| Names | Columns Title Case with units (`FeedGas_MMscfd` becomes `Feed Gas (MMscfd)`), tables UPPER_SNAKE_CASE, functions Title Case verb + object (`simulate` becomes `Simulate Pump Fleet`) |

### 1.7 Value boxes and KPI tiles

| Prototype | Draft spec |
|---|---|
| Boxes over table aggregates (`ui.value_box`, `st.metric`, Quarto valuebox, React KPI tile, `go.Indicator`) | An HTML KPI band in a text area: caption plus a `label` control per value, bound to a property a data function writes. Use `kpiChart` (`title`, `value`, `comparative`, `coloring`) only when the owner asks for native KPI tiles |
| A scalar computed in Python (R squared, threshold, counts) | Data function `value` output, written to a property, shown by a `label` control. Never `${}` inside HTML |
| `st.metric(delta=...)` | A second label (the delta), or `kpiChart` `comparative` |
| Showcase icon | Dropped, or a Unicode glyph in the band HTML |
| Value colored by state | A text-area JavaScript that watches the label, or `kpiChart` coloring rules |

### 1.8 Text and styling

| Prototype | Draft spec |
|---|---|
| Static markdown, headings, lists, tables | Text-area HTML with tags the sanitizer allows |
| Markdown with live values (`f"**{rows:,}** rows"`) | `label` controls bound to value properties; labels show plain text, no bold inside a value |
| Green or red status headline | A label in the KPI band plus JavaScript coloring (1.7) |
| LaTeX, superscripts | Unicode or entities (`R&sup2;`): `<sup>` is removed by the sanitizer |
| App CSS, Bootstrap or Streamlit themes | `app.theme.base`; the text-area look is handled by the `styling-spotfire-dxps` skill |
| Fonts | Document-wide; text-area font stacks with fallbacks |

## 2. Gaps and ranked substitutes

The first substitute is preferred. Write the chosen one into the mapping table with its fidelity
and ask the owner to approve it.

| # | Gap | Ranked substitutes | Fidelity |
|---|---|---|---|
| G1 | Shaded X bands: `add_vrect`, Recharts `ReferenceArea x1/x2`, Gantt overlays | 1. X-band reference layer from an event table, one band per row (`table`, `low: "Min([Start])"`, `high: "Min([End])"`, value axis X); one layer per event class with a where clause. Band reference layers from another table need Analyst 15.0 (*slim tier*). 2. A 0/1 bar series on a secondary axis with a translucent color, so contiguous bars read as a band (**Not yet tested**; *slim tier*: combination chart). 3. Color the line by state (`colorBy`): the first option for a draft. 4. A pending or selected window shown as marked rows | 1 EXACT look, 2 CLOSE, 3 CLOSE |
| G2 | Filled ribbons and areas: `fill="tonexty"`, `fill="tozeroy"`, `px.area`, Recharts `Area` | 1. Y band reference layer evaluated per x (`low: "Sum([Lower])"`, `high: "Sum([Upper])"`, evaluation mode Category); several stacked opaque bands blended in drawing order for several ribbons (*slim tier*). 2. Both edges as same-color series without fill: the first option for a draft. 3. A fitting model with confidence curves (a different model: the owner approves). 4. Stacked areas as a stacked `barChart` on a binned x with full bar width (**Not yet tested** look) | 1 CLOSE |
| G3 | Dashed or dotted data series (forecasts) | 1. A distinct solid color plus a clear legend name. 2. A build-time script that draws the series as a column-values line with a dotted line style (written by the build skill). Constant lines (thresholds) are reference lines with `dash`: EXACT | 1 CLOSE, 2 EXACT |
| G4 | Zoom events (`relayoutData`, `plotly_relayout`), rangeslider, "sync to zoom" | 1. Drop the event; users zoom with Spotfire's own zoom sliders (**Not yet tested** as a spec setting). 2. A "Use zoomed range" button whose script reads the axis zoom range (whether it reflects the user's zoom: **Not yet tested**) | Partial |
| G5 | In-memory models and objects (`reactive.value` holding a fitted model) | 1. Stateless pipeline: the training data function writes every downstream output (scores, losses, attributions as tables; threshold and status as value properties). 2. A pickled model in a Binary property (**Not yet tested** for size and trust) | Equivalent outputs |
| G6 | Markdown rendering, text with inline values | 1. Static HTML plus `label` controls for the values. 2. A button script that rewrites the text area's HTML after the run | CLOSE |
| G7 | Light page with dark plots, or the reverse | 1. One document theme: dark (closest to dark plots) or light (closest to the page); ask the owner. 2. A light theme with custom style rules that darken visuals (text areas turn dark too; **Not yet tested** look) | Approximate |
| G8 | Progress bars, spinners, per-step progress (`ui.Progress`, `st.progress`, `dcc.Loading`) | 1. Spotfire's own busy indicator while a data function runs. 2. A script that wraps the run in Spotfire's progress dialog (generic, no per-step messages). 3. Write the per-step history (epoch losses) to an output table shown after the run | Partial |
| G9 | Horizontal-only box select (`selectdirection="h"`) | 1. Mark on the 0/1 band bars of G1 option 2, so a drag marks time bins whatever the line's y (**Not yet tested**). 2. Typed start and end properties plus a script that sets the marking | CLOSE |
| G10 | Date sliders and range sliders | Section 1.2, rows "Range slider" and "Date or datetime slider" | SUBSTITUTE |
| G11 | File upload, in-page tabs, popovers, hover cards, timers | Sections 1.1 and 1.2: build-time data, pages or stacking, panel sections; hover cards and timers are dropped | MANUAL |
| G12 | Python packages missing from Spotfire's Python (torch, scipy, statsmodels, scikit-learn) | 1. Install them into Spotfire's Python environment (Analyst and the server's Python service). 2. Port to numpy (changes the model: the owner approves and the acceptance metrics are checked again) | 1 EXACT |
| G13 | Charts with no native type (sankey, parallel coordinates, candlestick, polar, radar) | 1. A visualization mod that is already installed or in the library (the `building-visualization-mods` skill). 2. A native approximation the owner agrees to | Varies |

## 3. Worked example: a forecast tab

Prototype (condensed): `layout_sidebar(sidebar(fc_steps 24 to 336 default 72, fc_span 12 to 168
default 48, width=280), card("Vibration trend and forecast", forecast_plot))`. The plot has raw
and smoothed vibration lines, a dotted forecast, a `fill="tonexty"` band of plus and minus two
standard deviations, and an `add_hline` alarm level. It re-renders live when a slider moves.

Mapping: two Integer properties `FcSteps` and `FcSpan`; an automatic data function
`Forecast Vibration Trend` (inputs: the readings table, `AlarmLevel`, the two properties;
output: table `VIBRATION_FORECAST` holding history, forecast and the band edges in one table,
so every series comes from the chart's own table). The page:

```json
{
  "title": "Forecast",
  "visuals": [
    {"id": "forecastPanel", "type": "textArea", "title": "Forecast Settings", "showTitle": false,
     "html": "html/forecast_panel.html",
     "controls": {
       "fcSteps": {"kind": "slider", "property": "FcSteps", "min": 24, "max": 336, "step": 1},
       "fcSpan":  {"kind": "slider", "property": "FcSpan", "min": 12, "max": 168, "step": 1}}},
    {"id": "forecastTrend", "type": "lineChart", "table": "VIBRATION_FORECAST",
     "title": "${PumpId} vibration trend and ${FcSteps} h forecast (mm/s)",
     "x": "[Timestamp (UTC)]",
     "y": ["Avg([Vibration (mm/s)]) as [Raw]", "Avg([Vibration Smoothed (mm/s)]) as [Smoothed]",
           "Avg([Vibration Forecast (mm/s)]) as [Forecast]",
           "Avg([Forecast Lower (mm/s)]) as [Lower]", "Avg([Forecast Upper (mm/s)]) as [Upper]"],
     "colorBy": "<[Axis.Default.Names]>",
     "coloring": {"categorical": {"Raw": "#1E293B", "Smoothed": "#2DD4BF", "Forecast": "#A78BFA",
                                  "Lower": "#D8CCFD", "Upper": "#D8CCFD"}},
     "referenceLayers": [
       {"kind": "horizontalLine", "value": "[$AlarmLevel]", "color": "#FBBF24", "dash": "dash",
        "label": "Alarm"}]}
  ],
  "layout": {"row": [{"visual": "forecastPanel", "weight": 18}, {"visual": "forecastTrend", "weight": 82}]}
}
```

Substitutes recorded in the mapping table for the owner: the dotted forecast is a solid violet
series (G3 option 1), the ribbon is its two edges in one light color (G2 option 2; a filled
per-x band, G2 option 1, needs the slim tier).

## 4. Extraction checklist

1. **Runnable source.** Compile every file, resolve names, smoke-run the engine on copies with the
   default inputs. Pick the newest coherent version folder.
2. **Inventory.** Run `scripts/scan_prototype.py` and read its element list. It is a starting
   point: read the code for everything it marks as unresolved.
3. **Pages.** Tabs, nav panels and Quarto pages become page titles (Title Case, no numbering).
4. **Layout.** Per page, write the tree (sidebar, rows, columns, cards) with widths and heights
   as weights (1.1).
5. **Inputs.** Per input: id, widget, label, choices, default, min, max, step, multiple. Each
   becomes a property (PascalCase name, exact type and default, description) plus a control kind
   and value source (1.2).
6. **Outputs.** Per figure, table, text and value box: the visual type and fields (1.3, 1.4, 1.7).
7. **Reactive graph.** For every output, the inputs it reads; for every computation, its trigger;
   every piece of state becomes an expression, an automatic data function, a manual data
   function with a button, a script, a marking or a trigger (1.5).
8. **Computations.** Every calculation the prototype performs (engine functions, derived
   columns, aggregates behind KPIs, thresholds) becomes a Logic Spec entry with its equation and
   units, status inferred.
9. **Data.** Sources; precomputed or input-driven; column, table and function names; the package
   check against Spotfire's Python; fixed seeds and start dates (1.6).
10. **Look.** Theme base, per-visual colors, fonts.
11. **Gaps.** Every construct without a direct equivalent gets a substitute from section 2,
    written into the mapping table for the owner to approve.
