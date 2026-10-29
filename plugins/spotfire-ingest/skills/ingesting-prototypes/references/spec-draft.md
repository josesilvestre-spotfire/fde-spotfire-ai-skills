# Draft build spec (`spec.json`)

The ingest skills write a draft `spec.json` next to `app-brief.md` and `logic-spec.md` in the app
folder (`$DXP_WORKSPACE/apps/<AppSlug>/`). The `building-spotfire-dxps` skill owns the full spec
format (app spec v1), validates the draft and adds what the draft leaves out (style, `settings`,
`postScript`, action mods, visualization mods). The draft uses only the fields below, with the
field names of spec v1, so the build skill can validate it without edits.

## Rules

- JSON without comments. Paths are relative to the app folder.
- Names follow `naming-standard.md`: properties PascalCase, tables UPPER_SNAKE_CASE, columns Title
  Case with the unit in parentheses, data functions and scripts Title Case verb + object, visual
  ids camelCase.
- Every input in the App Brief becomes one entry in `properties` and one control in a text area.
  The property name, the data function parameter and the control binding are the same name.
- Every Logic Spec entry appears where its "Implemented as" line says: a data function in
  `dataFunctions`, a document property in `properties`, or a visual expression inside the visual.
- Every output in the App Brief names a page; that page has the visual.
- Visual titles keep the prototype's card header or the workbook's own header, with units.
- Unknowns go into the App Brief's open questions, never into the spec as placeholders.
- Data enters at build time. Every `csv` or `sbdf` source names a file that ships in `data/`
  (synthetic or extracted data; a script in `ingest/` may write it). The build skill converts
  CSV to SBDF before it builds. Excel files are converted to CSV first.
- A data function table output that a filter layout, a control or a visual names declares those
  columns in its `tables[]` entry (`"columns": {"Pump ID": {"description": "Pump"}}`).
- A filter layout lists at least one column of each table it names.
- A data function value output that is a Python `int` goes to a `LongInteger` property (Python
  integers export as LongInteger); a Python `float` goes to a `Real` property.
- The draft uses only what the standard engine of the `building-spotfire-dxps` skill builds
  (next section). A prototype or workbook feature that needs more goes into the mapping table
  with the substitute the draft uses, so the owner can ask for the build's slim tier instead.
- Before the hand-off, the build skill's `dxpgen.py validate` reports 0 errors and 0 warnings
  for the draft (`check_handoff.py --build-skill <folder>` runs it).

## What the standard engine builds

Checked against the standard engine of the `building-spotfire-dxps` skill. Anything else stops
its build with "not in the standard engine yet: use --tier slim".

| Part | Built | Not built (slim tier only) |
|---|---|---|
| Top level | `tables`, `markings`, `properties`, `dataFunctions`, `scripts`, `pages`, `filterPanelLayout` | `relations`, `filteringSchemes` |
| Tables | `sbdf` and `dataFunction` sources (`csv` in a draft, converted by the build), `columns` with `description` and `format`, `embed: true` | `calculatedColumns`, `hierarchies`, table or column `settings`, linked tables |
| Data functions | `engine: "python"`, table, column and property binds, `limitByMarking` on table and column binds | `limitByFiltering`, literal `bind.value` lists or objects |
| Pages | `title`, `visuals`, `layout`, `filters`, `filterPanel`, `visible` | `filteringScheme` |
| `lineChart` | `x`, `y`, `colorBy`, `coloring`, `trellis`, `xScale`, `yScale`, `referenceLayers`, `fittingModels`, `limitExpression` | `showMarkers`, `steps`, `lineBy` |
| `barChart` | `x`, `y`, `colorBy`, `coloring`, `orientation`, `stack`, `sort`, `trellis`, `xScale`, `yScale`, `referenceLayers`, `fittingModels`, `limitExpression` | `labels` |
| `scatterPlot` | `x`, `y`, `colorBy`, `sizeBy`, `shapeBy`, `labelBy`, `labels`, `markerSize`, `shape`, `lineBy`, `trellis`, scales, `referenceLayers`, `fittingModels`, `limitExpression` | |
| `table`, `crossTable` | `columns`, `widths`, `coloring`; `rows`, `columns`, `measures`, `totals` | |
| `kpiChart`, `map`, `textArea` | `kpis`, `coloring`; `layers`, `extent`, `autoZoom`; `html`, `controls`, `js` | text-area `css` |
| Reference layers | `horizontalLine`, `verticalLine` with `value`, `color`, `dash` (`solid`, `dash`, `dot`), `label` | `band`, lines from another table, layer `settings` |
| Every visual | `id`, `type`, `title`, `showTitle`, `table`, `marking`, `limitByMarkings`, `emptyMarkingBehavior`, `legend`, `settings` | `useFiltering: false`, `postScript` |

Use instead in a draft:

| Wanted | Draft |
|---|---|
| Calculated column, lookup through a relation | A column computed by the data function that writes the table |
| Filled band or ribbon (`fill="tonexty"`, `add_hrect`) | Both edges as series of the same color, or two horizontal reference lines |
| Markers on a line, step lines | The plain line; the mapping table records the difference |
| Pie, heat map, treemap, combination, box plot, histogram, waterfall | The substitute in the mapping reference (bar chart, cross table, line chart with several `y`) |

## Top level used by the draft

```json
{
  "specVersion": 1,
  "app": {"name": "Line Pressure Profile", "description": "...", "namingPolicy": "program",
          "htmlMode": "safe", "theme": {"base": "LightSfx"}, "pageNavigation": "Tabs"},
  "tables": [],
  "defaultTable": "SEGMENTS",
  "markings": [],
  "properties": [],
  "dataFunctions": [],
  "scripts": [],
  "pages": [],
  "activePage": "Overview"
}
```

## Fields

| Field | What the draft writes |
|---|---|
| `tables[]` | `name`, `source` (`{"type": "csv", "path": "data/X.csv", "columns": {name: DataType}}`, `{"type": "sbdf", "path": "data/X.sbdf"}` or `{"type": "dataFunction", "function": ..., "output": ...}`), `description`, `columns` (`{name: {"description": ...}}`, required for the columns of a data function table that a page names), `embed: true` |
| `markings[]` | `name`, `color`, `default` (one marking per selection the prototype or workbook supports) |
| `properties[]` | `name`, `type` (`String`, `Integer`, `LongInteger`, `Real`, `Boolean`, `Date`, `DateTime`), `default` in the exact type (`72.0` for Real), `description` (the input label), `listValued` for multi-select |
| `dataFunctions[]` | `name`, `description`, `engine: "python"`, `script` (`datafunctions/<file>.py`), `inputs` [`name`, `type` (`table`, `column`, `value`), `dataTypes` for value inputs (`["Real"]`), `bind` (`table`, `columns`, `property`)], `outputs` [`name`, `type` (`table`, `value`), `target` (`table` or `property`)], `refresh` (`automatic` or `manual`), `executeAtBuild` |
| `scripts[]` | `name`, `description`, `file` (`scripts/<file>.py`), `parameters`; only for side effects (reset, several steps in order) |
| `pages[]` | `title`, `visuals`, `layout` (`row` / `column` tree with `weight`), `filters` (`{"tables": [{"table": ..., "columns": [...]}]}`, or `{"tables": []}` for a page with nothing to filter) |
| visuals | `id`, `type`, `title`, `table`, the fields of the type (table above), `marking`, `limitByMarkings`, `limitExpression`, `coloring`, `referenceLayers` |
| text areas | `type: "textArea"`, `html` (`html/<file>.html`), `controls` {id: {`kind`, `property`, `values`, `min`, `max`, `step`, `label`, `script`, `action`}} placed in the HTML with `{{control:<id>}}` |

Control kinds: `label`, `input`, `multilineInput`, `dropdown`, `listbox`, `multiSelectListbox`,
`slider`, `checkbox`, `radio`, `button`, `link`. Value sources: `{"fixed": [{"text", "value"}]}`
or `{"column": {"table", "column"}}`. Whether a control is created automatically or listed as a
manual step is decided by the `building-spotfire-dxps` skill.

## Example

A pressure profile app with one input table, one input property, one data function and one page:

```json
{
  "specVersion": 1,
  "app": {"name": "Line Pressure Profile", "namingPolicy": "program", "htmlMode": "safe",
          "theme": {"base": "LightSfx"}, "pageNavigation": "Tabs"},
  "tables": [
    {"name": "SEGMENTS", "source": {"type": "csv", "path": "data/SEGMENTS.csv",
      "columns": {"Segment": "Integer", "Length (ft)": "Real", "Inner Diameter (in)": "Real",
                  "Elevation Change (ft)": "Real"}},
     "description": "One row per pipe segment.", "embed": true},
    {"name": "SEGMENT_RESULTS", "source": {"type": "dataFunction",
      "function": "Calculate Pressure Profile", "output": "SEGMENT_RESULTS"},
     "description": "Pressure drop and outlet pressure per segment."}
  ],
  "defaultTable": "SEGMENT_RESULTS",
  "markings": [{"name": "Selected Segment", "color": "#E94165", "default": true}],
  "properties": [
    {"name": "FlowRate", "type": "Real", "default": 12000.0, "description": "Flow rate (bbl/d)"},
    {"name": "OutletPressure", "type": "Real", "default": 0.0,
     "description": "Outlet pressure of the last segment (psi), written by the data function"}
  ],
  "dataFunctions": [
    {"name": "Calculate Pressure Profile", "engine": "python",
     "script": "datafunctions/calculate_pressure_profile.py",
     "inputs": [
       {"name": "SEGMENTS", "type": "table", "bind": {"table": "SEGMENTS", "columns": "*"}},
       {"name": "FlowRate", "type": "value", "dataTypes": ["Real"], "bind": {"property": "FlowRate"}}
     ],
     "outputs": [
       {"name": "SEGMENT_RESULTS", "type": "table", "target": {"table": "SEGMENT_RESULTS"}},
       {"name": "OutletPressure", "type": "value", "target": {"property": "OutletPressure"}}
     ],
     "refresh": "automatic", "executeAtBuild": true}
  ],
  "pages": [
    {"title": "Overview",
     "visuals": [
       {"id": "inputsPanel", "type": "textArea", "title": "Inputs", "showTitle": false,
        "html": "html/inputs_panel.html",
        "controls": {"flowRate": {"kind": "input", "property": "FlowRate"},
                     "outletPressure": {"kind": "label", "property": "OutletPressure"}}},
       {"id": "pressureProfile", "type": "lineChart", "title": "Outlet Pressure (psi)",
        "x": "[Segment]", "y": "Sum([Outlet Pressure (psi)])"}
     ],
     "layout": {"row": [{"visual": "inputsPanel", "weight": 18},
                        {"visual": "pressureProfile", "weight": 82}]}}
  ],
  "activePage": "Overview"
}
```

A value output of a data function (`OutletPressure`) also has its own entry in `properties`.
