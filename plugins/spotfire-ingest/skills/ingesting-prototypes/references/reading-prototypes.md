# Reading a prototype

Where each prototype kind keeps its pages, layout, inputs, outputs, reactivity, data and styling.
Read the prototype with this file, then map what you found with
`prototype-to-spotfire-mapping.md`.

Shiny for Python, Streamlit, Plotly figures and HTML or React mockups have been read for real
apps. No Dash or Quarto prototype has been studied yet: those sections are framework knowledge.

## Ground rules

- The prototype is the spec. Build guides and older DXPs are only pattern evidence.
- A prototype that does not run is not a spec. Compile every file (`python -m py_compile`),
  resolve names, and smoke-run its engine on a copy with the default inputs before you map it.
- Pick the newest coherent version when a folder holds several. Version folders often carry
  mismatched modules (a newer `simulator.py` that breaks an older `app.py`).
- Layout grammar shared by most prototypes made for Spotfire: KPI band on top, filter or
  parameter rail on the left, primary visual in the centre, detail table below. An approved
  mockup maps element for element.
- Prototype quirks (a slider whose top value its step never reaches, a label that disagrees with
  its value) are kept or fixed only by the owner's decision. Record each one in the mapping table.

## Shiny for Python

| Aspect | Where it lives |
|---|---|
| Syntax | Core: `app_ui = ui.page_*(...)` plus `def server(input, output, session)`. Express: `from shiny.express import input, render, ui`, `with ui.sidebar():` and `with ui.card():` blocks, render functions inline. Larger apps split pages into modules (`@module.ui`, `@module.server`) |
| Pages | `ui.page_navbar(ui.nav_panel("Data", ...))`; each `nav_panel` is a page |
| Layout | `ui.page_sidebar`, `ui.layout_sidebar(ui.sidebar(..., width=300), ...)`; `ui.layout_columns(..., col_widths=[4, 8])` (12-column grid); `ui.layout_column_wrap`; `ui.card(ui.card_header("..."), ...)`; `ui.navset_*` (tabs inside a page); `ui.accordion`; `ui.value_box` |
| Inputs | `ui.input_*("id", "label", ...)`: choices as a list or a `{value: label}` dict, `selected`, `multiple=True`; slider `min`, `max`, `step`, `value` (a tuple is a range slider, datetimes make a date slider); `input_switch`, `input_checkbox`, `input_action_button`, `input_action_link`, `input_file` |
| Outputs | `ui.output_plot/ui/text/data_frame("id")`, `output_widget("id")`, each paired with the server function of the same name: `@render.plot`, `@render.ui`, `@render.text`, `@render.data_frame`, `@render_widget` or `@render_plotly` (shinywidgets). Map the Plotly code inside the render function |
| Reactivity | `@reactive.calc` (derived value), `@reactive.effect` plus `@reactive.event(input.run)` (button-gated work), `reactive.value(...)` (state), `ui.update_select` and `ui.update_slider` (dynamic choices), `req()`, `ui.notification_show`, `ui.Progress`. JavaScript bridges (`Shiny.setInputValue("plot_select", ...)`) carry chart selection and zoom |
| Data | Module-level loads and simulator calls; the engine or model module the app imports |
| Styling | `theme=`, `ui.navbar_options(bg=...)`, `ui.tags.style`, `ui.include_css`, the Plotly layout (`paper_bgcolor`, `template`, colors) |
| Watch for | State that must persist across interactions (label registries, recipe steps); a render function's name is its output id |

## Streamlit

| Aspect | Where it lives |
|---|---|
| Model | The script reruns top to bottom on every interaction; widget values are plain variables |
| Pages | Multipage `pages/` folder, or `st.navigation([st.Page(...)])` |
| Layout | `st.set_page_config(layout="wide")`; `st.sidebar`; `st.columns([0.3, 0.7])`; `st.tabs([...])`; `st.expander`, `st.container`, `st.popover` |
| Inputs | `st.selectbox` (`format_func` shows a label and stores the key), `st.multiselect`, `st.slider` (a tuple is a range, datetimes make a date slider), `st.select_slider`, `st.number_input`, `st.text_input`, `st.text_area`, `st.radio`, `st.checkbox`, `st.toggle`, `st.date_input`, `st.button`, `st.form` plus `st.form_submit_button`, `st.file_uploader`, `st.download_button` |
| Outputs | `st.plotly_chart(fig)`, `st.altair_chart`, `st.line_chart`, `st.bar_chart`, `st.area_chart`, `st.scatter_chart`, `st.map`, `st.dataframe`, `st.table`, `st.metric(label, value, delta)`, `st.markdown`, `st.caption`, `st.info` |
| Reactivity | `st.session_state` (state), `@st.cache_data` (memoized compute: a data function candidate), `on_change` callbacks, `st.rerun()`, selection events `st.plotly_chart(..., on_select="rerun")` and `st.dataframe(..., on_select="rerun")` |
| Data | The engine module (`engine.py`, `model.py`) is the data function candidate. Computation written inside tab bodies (event tables, autocorrelation, spectra, forecasts, resampling) moves into data function outputs: Spotfire visuals do not compute frames |
| Styling | `.streamlit/config.toml` `[theme]` (`primaryColor`, `backgroundColor`, `secondaryBackgroundColor`, `textColor`, `font`); palette constants in the code; injected `<style>` over `data-testid` selectors (ignore these: Spotfire has no such page structure) |
| Watch for | Files that do not import (a `from __future__` line after other imports in a concatenated file, an import alias that the code never uses): run `python -m py_compile` and a name check first |

## Plotly figures and Dash

| Aspect | Where it lives |
|---|---|
| Figure code | `px.*(...)` or `go.Figure(...)`; `fig.update_layout`, `update_traces`, `update_xaxes`; `fig.add_vrect`, `add_hrect`, `add_hline`, `add_vline`, `add_shape`, `add_annotation`; `make_subplots(rows, cols, shared_xaxes=True, specs=[[{"secondary_y": True}]])` |
| Exported HTML | The figure is the JSON passed to `Plotly.newPlot(div, data, layout, config)`: `data` holds the traces (`type`, `mode`, `x`, `y`, `marker`, `line`, `fill`, `name`, `xaxis: "x2"`), `layout` holds `title`, `xaxis`, `yaxis2`, `shapes`, `annotations`, `template`, `colorway`. A vrect is a `shapes` entry with `type: "rect"` spanning the y domain 0 to 1; an hline is a `type: "line"` spanning the x domain. Recent Plotly versions encode arrays as `{"dtype": "f8", "bdata": "<base64>"}`: decode with `numpy.frombuffer(base64.b64decode(bdata), dtype)` |
| Dash pages | Multipage `Dash(use_pages=True)` plus `dash.register_page`; `dcc.Tabs` at the top of `app.layout` |
| Dash layout | The `app.layout` tree: `html.Div`, `dcc.Tabs`, `dbc.Row` and `dbc.Col(width=4)` (12-column grid), `dbc.Card` |
| Dash inputs | `dcc.Dropdown(options, value, multi=True)`, `dcc.Slider`, `dcc.RangeSlider`, `dcc.RadioItems`, `dcc.Checklist`, `dcc.Input(type="number")`, `dcc.DatePickerSingle`, `dcc.DatePickerRange`, `html.Button` (`n_clicks`) |
| Dash outputs | `dcc.Graph(id, figure)`, `dash_table.DataTable` (`row_selectable`, `selected_rows`), `html.Div(children)` |
| Dash reactivity | Each `@callback(Output(...), Input(...), State(...))` is one dependency edge: `Input` is a live trigger, `State` is read on trigger, `n_clicks` is a button event. `dcc.Store` holds state, `dcc.Interval` is a timer; graph events are Inputs on `selectedData`, `clickData`, `hoverData`, `relayoutData` (zoom) |
| Styling | `assets/*.css` (loaded automatically), `style={...}` dicts, `className`, `external_stylesheets`, figure templates |

## Quarto

| Aspect | Where it lives |
|---|---|
| File | `.qmd`: YAML front matter (`format: html` or `format: dashboard`, `theme`, `css`, `server: shiny`), Markdown, Python cells with `#|` options (`label`, `echo`, `title`, `fig-cap`, `layout-ncol`, `content`, `context`) |
| Dashboard layout | A `#` heading is a page; a `##` heading is a row (default) or a column (`orientation: columns`), sized `{height=60%}` or `{width=40%}`; nested `###`; each cell output is one card (`#| title:`); `::: {.card}`; `{.tabset}` makes tabs inside a row or column; `{.sidebar}`, `{.toolbar}` |
| Value boxes | A cell with `#| content: valuebox` returning `dict(icon=..., color=..., value=...)` |
| Document layout | `::: {.panel-tabset}`, `:::: {.columns}` with `::: {.column width="40%"}`, `#| layout-ncol: 2`, callouts |
| Reactivity | None in a plain Quarto document: everything is computed when it renders. `server: shiny` adds Shiny inputs (usually in `{.sidebar}`) and `@render.*` functions in `#| context: server` cells: read those as Shiny. OJS cells (`viewof x = Inputs.range(...)`, `Inputs.select`) are inputs too |
| Data | Computed when the document renders: precomputed data unless a Shiny or OJS input drives it |
| Styling | `theme:` (a Bootswatch name or an `.scss` file), `css:` |
| Text and figures | Prose becomes text-area HTML; inline values (`` `{python} x` ``) become label controls or `${}` titles; matplotlib and seaborn pictures are rebuilt as native visuals, never embedded as images |

## HTML and React mockups

| Aspect | Where it lives |
|---|---|
| HTML concept panels | `<style>` plus classes, `<details>` accordions, and control placeholders in several conventions: `<SpotfireControl id="..." />` with a comment naming the control type, property and values; bracket notes such as `[SPOTFIRE ACTION: ...]`, `[SPOTFIRE INPUT: ...]`, `[INSERT BUTTON: ...]`; `label="..."` attributes. Each placeholder becomes a control in the draft spec. The panel markup itself is rewritten: Spotfire's text-area sanitizer removes `<style>`, `<details>`, `<sup>` and script tags |
| React layout | The JSX component tree (rows, grids, cards); Tailwind classes or inline style objects |
| React state | `useState` (each piece of UI state becomes a document property or a marking), `useMemo` (expressions or data functions), handlers (`onClick` becomes a button, link or marking) |
| React charts | Recharts `LineChart`, `BarChart` (`stackId`), `AreaChart`, `ComposedChart`, `ScatterChart` (`ZAxis` is size), `PieChart` (`innerRadius` makes a donut), `Treemap`, `RadarChart`, `ReferenceLine`, `ReferenceArea`, `Brush`, `Tooltip`, `Legend` |
| Data | Hard-coded arrays or JavaScript generators: replace them with the real extract or simulator output |
| Annotations | Mockups made for Spotfire often annotate each element with its counterpart (KPI tile, filter or marking, script action): follow them |

## What to write down per prototype

| Item | Record |
|---|---|
| Pages | Title of every tab, nav panel or Quarto page, in order |
| Layout | Per page: sidebar, rows, columns and cards, with widths and heights |
| Inputs | Id, widget, label, choices (value and label), default, min, max, step, multiple |
| Outputs | Per figure: trace kinds, x, y, color, size, facets, secondary axis, shapes, annotations, log axes, ranges, title. Per table: columns, sort, selection. Per text: static or live. Per value box: the aggregate |
| Reactive graph | For every output, the inputs it reads; for every computation, its trigger (live input, button, selection, timer); every piece of state |
| Data | Sources, whether each dataset is loaded once or recomputed from inputs, fixed seeds and start dates, packages the engine imports |
| Look | Theme base (light or dark), per-series colors, fonts |
