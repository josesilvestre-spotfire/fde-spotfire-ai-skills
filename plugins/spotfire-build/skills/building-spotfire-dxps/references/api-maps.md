# API reference: map charts and layers

Owners: `scripts/lib/75_maps.py` (`vis_map(page, vspec)`, slim tier) and `scripts/engine/builders/map.py`
(standard engine, with the marker helpers of `scripts/engine/builders/_markers.py` and the colorings of
`scripts/engine/features/coloring.py`; converter `scripts/t3/map.py`). Spotfire Analyst 15.0,
IronPython 3.4. Public API only. The library's members are checked with `scripts/sfapi.py has`
(`scripts/lib/75_maps.members.txt`, setters in `scripts/lib/75_maps.set.txt`); the engine part declares
its members in `# @api` and `# @set` lines (Maps types by their full names: `MapChart` and
`MapChartLayer` exist twice in the index). Newest member used: `DataColumn.DataType` [api 7.5], nothing
newer than 14.6 (except the optional `CopyrightInfoItems`, [api 14.8]).
Example: `assets/examples/fragments/maps.json` with
`assets/examples/fragments/datafunctions/build_pipeline_route.py`.

Evidence tags: [API] in the public API index; [DXP] seen in maps built in Analyst and saved; **Not yet
tested** marks what has not run in a live Spotfire.

## What makes a map draw nothing

A map with one misconfigured data layer draws nothing at all, tile layer and healthy layers included,
and shows only "Please specify an aggregation method." Proven on Analyst 15.0: the canvas text is the
message, and the red issue icon next to the map title has the tooltip "Invalid configuration (<layer
title>)". When a map is blank, hover that icon first: it names the failing layer. The build log and the
spec comparison cannot see it (every step is OK).

These settings do not break a map: layer kinds and order (tile at the back, feature layers, then
marker layers), one table per layer, `PositioningMethod LongitudeLatitude` with raw `[Longitude]` and
`[Latitude]`, layer projections (tile EPSG:3857, data EPSG:4326), a route as a marker layer with
`MarkerSize 0` and a line connection, a continuous gradient on a raw column, categorical colors
`<[Status]>`, marker shapes, feature layers with `GeometryBy <baserowid()>`. Fields that differ between
a builder map and an Analyst map but do not matter: `ActiveDataReference`, `AutomaticGeocodingHierarchies`,
`InitialExtent` (no API), a map-level `Data.LimitingMarkingsEmptyBehavior ShowEmpty` with no limiting
marking.

### The cause: a raw expression in a slot that must aggregate

- A marker layer (and a scatter plot) aggregates its markers unless its marker-by contains `baserowid()`
  (`<baserowid()>`, `<[Axis.Default.Names] NEST baserowid()>`). Marker by `<>` (empty, what the API
  leaves and what Analyst writes by default) means aggregation ON. Pie markers always aggregate.
- With aggregation on, every slot that cannot split the markers must hold an aggregating or constant
  expression. A raw column there raises "Please specify an aggregation method." for the layer, and the
  map then draws nothing.
- Slots that split the markers (one marker per distinct value), so a raw column is fine: X, Y, Color and
  DrawingOrder. Slots that must aggregate: Size, rotation, `LineConnection.Order`, the label
  (`LabelColumn`) and tooltip `Details` expressions. The Labels card shows the error on "Label by".
- In live builds on Analyst 15.0 a layer label `[Station ID]` blanked a whole map, and a scatter plot with
  `LineConnection.OrderAxis.Expression = "[Flow (bbl/d)]"` went blank the same way.

### Rules

| slot (marker layer or scatter plot) | marker by `<>` (default) | marker by contains `baserowid()` |
|---|---|---|
| X / Y (longitude / latitude) | raw `[Longitude]` | raw |
| color | raw `[Map Value]` (continuous gradient) or categorical `<[Status]>` | raw |
| `DrawingOrderAxis` | raw `[Draw Order]` | raw |
| `lineBy` (`LineConnection.ConnectionAxis`) | categorical `<[Segment ID]>` | categorical |
| `LineConnection.OrderAxis` | aggregated (`Avg([Seq])`) or empty (vertices connect in row order) | raw |
| `sizeBy` (`SizeAxis`) | aggregated (`Avg([Flow (bbl/d)])`) | raw |
| `RotationAxis` | aggregated | raw |
| `labelBy` (`LabelColumn`) | aggregated: `First([Station Label])`, `UniqueConcatenate([Station ID])`, `Concatenate(First([A]), " - ", First([B]))` | raw |
| tooltip `Details` expressions | aggregated (same rule as labels; inferred, **Not yet tested**) | raw |
| feature layer color | aggregated (`Avg(...)`, `Sum(...)`), as in every Analyst map [DXP] | n/a |

- "Aggregated" means every column reference sits inside an aggregation call (`Sum`, `Avg`, `Min`, `Max`,
  `Count`, `UniqueCount`, `Median`, `First`, `Last`, `UniqueConcatenate`, `StdDev`, `Percentile`, ...),
  or the expression is a constant, or a `THEN` post-aggregation. `Concatenate(...)` with several
  arguments is the string function: aggregate inside it.
- Prefer the aggregated form over a `baserowid()` marker-by on maps: it is what Analyst writes, and a
  row-level marker-by changes hover, marking and label counting for every slot of the layer.
- An empty marker-by is the aggregating case: never accept a raw label, size or order because "the
  marker-by is empty so it is per row".

### A working route map (proven on Analyst 15.0)

| part | setting |
|---|---|
| tile | `StandardTileLayer` "Rich reference map", `Transparency 0.45`, `IncludeInAutoZoom false`, EPSG:3857 |
| overlays | feature layers on WKB tables: color `Sum([<value>])` with a min/max gradient and visualization `Transparency 0.71`; contour lines in fixed grey, `Transparency 0.56`, `LineWidth 2` |
| route | marker layer on the vertex table (several points per segment): X/Y raw, marker by `<>`, `MarkerSize 0`, `LineConnection` Line `<[Segment ID]>`, `Width 4`, `UseMarkerColor`, `IsBackground`, `DrawingOrder [Draw Order]`, color raw with a min / median / max gradient |
| stations | marker layer, `StarFive`, `MarkerSize 3.84`, categorical color with an alias (`<[Operating_Mode] as [Station Status]>`), label aggregated ("STN-01 - Boosting"), `MaxNumberOfLabels 21`, `LabelVisibility All` |
| pumps | marker layer, `Circle`, `MarkerSize 1.72`, categorical color On/Off, `LabelVisibility None`, `UseSeparateColorForMarkedItems true` |
| map level | trellis layer = the route layer (map `Data` table = the route table), interactive layer = the stations layer, `AutoZoom false` with a fixed `ViewExtent` in EPSG:3857, `InteractionMode Panning` |
| marking | every data layer marks with "Marking" |
| legend | map `Legend.Visible` false; marker layer legends show only the `Color` item; feature layer legends hide Marking |
| filtering | every layer and the map on one filtering scheme, `UseActiveFiltering` true |

Marking rule: never limit the base geometry of a map (route, stations) by a marking that can be empty
with `ShowEmpty`. Use `ShowAll`, or limit only the detail layers. A layer limited by an empty marking
under `ShowEmpty` draws nothing, silently (no issue is raised).

### Legends: every data layer has its own legend [API]

The legend panel of a map is built from one `Legend` per data layer (`LayerVisualization.Legend`,
inherited from `Visualization`). Its items are `LegendLayerTitleItem` (Maps namespace),
`LegendFilteringsItem`, `LegendDataTableItem`, `LegendMarkingItem`, `LegendGroupByItem` (Marker by /
Geometry by), `LegendColorItem`, `LegendMarkerShapeItem`, `LegendSizeItem`, `LegendMarkerRotationItem`,
`LegendLineConnectionItem` and `LegendFilterRuleItem` ("Data limiting"). The map's own `MapChart.Legend`
holds only Title, Description and Trellis, so hiding items there hides nothing on the layers.

Rule: hide legend items on each data layer's `Legend.Items` (`item.GetType().Name`,
`item.Visible = False`) after the layer's color axis and coloring are set (a color-axis change rebuilds
the color items). Layers made through the API show every item, while Analyst users normally keep only
Color. The standard engine's feature `layerLegends` does this: the converter sends a map's `legend.hide`
kinds to the builder as `layerLegendHide` (only `trellis` goes to the map's own legend), and
`map_layer_legends` hides them on every data layer as the map's last step. Kinds: `filtering`,
`marking`, `markerBy` (`LegendGroupByItem`), `lineBy` (`LegendLineConnectionItem`), `colorBy`, `shape`,
`size`, `rotation`, `limits` (`LegendFilterRuleItem`), `dataTable`, `layerTitle`. To keep only Color and
the layer titles: `["filtering", "marking", "markerBy", "lineBy", "shape", "size", "limits"]`;
`"legend": {"visible": false}` hides the whole map legend. Analyst maps persist the per-layer `Visible`
flags [DXP]; `layerLegends` itself is **Not yet tested**.

### Checks that catch it before you run a builder

- dxpgen validate (`Validator.v_marker_aggregation`, detector `scripts/sfexpr.py` `raw_column_refs` and
  `unaggregated`): a raw `labelBy` or `sizeBy` on a scatter plot or marker layer (a bare column name
  counts as raw), or a raw `LabelColumn.Expression`, `SizeAxis.Expression`,
  `LineConnection.OrderAxis.Expression` or `RotationAxis.Expression` setting, is an error unless the
  same object's `MarkerByAxis.Expression` setting contains `baserowid()`. The message names the fix
  (`First(...)` for labels, `Avg(...)` for the others).
- verify_dxp (`check_marker_aggregation`, on the saved DXP): the same rule on every scatter plot and map
  marker layer is a FAIL ("Spotfire shows 'Please specify an aggregation method.' and draws nothing").
- Known detector limit: the one-argument `Concatenate([A])` aggregation reads as raw; write
  `UniqueConcatenate([A])`.
- After a build, open `Preview.png` from the saved DXP: a blank visual with one centred line of text is a
  configuration error.

## Function (slim tier)

`vis_map(page, vspec)` builds one map and returns the `Visual`. Each layer, and each aspect of a layer,
is its own `B.step`, so a bad expression loses one item, never the map. Step names:
`map.geometryColumn`, `map.layer`, `map.position`, `map.lineConnection`, `map.sizeBy`, `map.geometryBy`,
`map.colorBy`, `map.coloring`, `map.marking`, `map.dataLimits`, `map.layerSettings`, then
`map.interactiveLayer`, `map.trellisLayer`, `map.autoZoom`, `map.common`, `map.record`. Targets:
`<vid>/layers[i]` until the layer exists, then `<vid>/<layer title>`. Public API failures are `failed`
steps (a spec or library defect to fix), never fallbacks.

| spec | built as |
|---|---|
| `type: "map"` | `page.Visuals.AddNew(VisualTypeIdentifiers.MapChart2)`, `visual.As[Maps.MapChart]()` |
| `layers` order | back to front, the order of `MapChart.Layers`; `AddNew*Layer()` appends front-most, so spec order needs no `Move` |
| `kind: "tile"` | `Layers.AddNewStandardTileLayer()`, default service (`ServiceName ""` = Automatic) |
| `kind: "marker"` | `Layers.AddNewMarkerLayer(table)`; `PositioningMethod.LongitudeLatitude`; `XAxis.Expression = longitude`, `YAxis.Expression = latitude` |
| marker, `geometry`, no lat/lon | X/Y = the table's `XCenter`/`YCenter` columns (tagged, else by name); none = failed step. A GeoDataFrame export adds only `Geometry`: the data must carry its own centroid columns |
| marker, no lat/lon, no geometry | numeric `Longitude`/`Lon`/`Long`/`Lng` and `Latitude`/`Lat` columns (case-insensitive), with a warning. Write lat/lon explicitly in specs |
| `kind: "feature"` | geometry column tagged first (step `map.geometryColumn`), then `Layers.AddNewFeatureLayer(table)`; `GeometryByAxis.Expression = "<baserowid()>"` |
| `geometry` (feature) | the geometry column (`Geometry` or `[Geometry]`); absent = the column tagged `Geometry`, else a column named `Geometry`; a value in angle brackets (`<[Segment ID]>`) is the geometry-by expression |
| `colorBy` | `ColorAxis.Expression` (marker and feature); a list is joined with `", "` as the coloring module does |
| `coloring` (visual level) | `apply_coloring(layer_viz, {"id": "<vid>/<layer>", "colorBy", "coloring"})` (`scripts/lib/65_coloring.py`) on every data layer with a colorBy; a `fixed` color also on layers without one (color by `<>`). A layer-level `coloring` overrides it |
| `sizeBy` (marker) | `SizeAxis.Expression` |
| `lineBy` (marker) | `LineConnection.ConnectionAxis.Expression`. Every marker layer also gets Analyst's own line defaults: `UseMarkerColor True`, `Width 2`, `IsBackground True` |
| `title` | `MapChartLayer.Title`; default: the table name (data layers), `"Rich reference map"` (tile) |
| `marking` | `Data.MarkingReference` of every data layer (`null` = cannot be marked) |
| `limitByMarkings`, `emptyMarkingBehavior`, `limitExpression` | data layers on the visual's `table` only: `Data.Filterings.Add(marking)`, `Data.LimitingMarkingsEmptyBehavior`, `Data.WhereClauseExpression`. Layers on other tables (route geometry) keep all rows |
| `useFiltering: false` | `Data.UseActiveFiltering = False` on every data layer |
| layer `settings` | relative to the layer visualization for data layers, except `Title` and members only the layer has (`Enabled`, `IncludeInAutoZoom`, `IncludeInResetViewExtent`, `Projection`, `VisibleZoomLevelRange`), which go to the `MapChartLayer`; tile layers: the layer |
| interactive layer | `MapChart.InteractiveLayerReference` = top-most enabled data layer (recipe R6) |
| trellis layer | `MapChart.TrellisLayerReference` = first enabled data layer on the visual's table, else the first data layer on it, else the first data layer (recipe R6) |
| `autoZoom` (default true) | `MapChart.AutoZoom`, after the layers, before `vis_common` |
| `title`, `showTitle`, `description`, `table`, `marking`, `legend`, `settings`, `postScript` | `vis_common` (`scripts/lib/60_charts.py`) on the MapChart, last, with: data limits reset to defaults (they are on the layers; Analyst maps keep the map-level `Data` unlimited), `coloring`/`referenceLayers`/`fittingModels` emptied, and `table` = the trellis layer's table (differs from the spec only when no data layer uses the visual's table, with a warning). `postScript` runs after the zoom, so it can store a fixed view |

Report: `B.created["maps"][<vid>]`, read back after `vis_common`:
`{"layers": [{"kind", "title", "table", "position" (0 = back), "enabled", "geometry"?,
"geometryTaggedByBuilder"?}], "interactiveLayer": <title>, "trellisLayer": <title>, "table":
<map-level table>, "autoZoom": bool}`. Colorings: `B.created["coloring"]["<vid>/<layer title>/coloring"]`.

Warnings: no layers; `layers` not a list; tile layer after a data layer (covers it); no tile layer;
duplicate layer titles; `coloring` but no data layer with a colorBy; no data layer on the visual's table
(the map table follows the trellis layer, limits not applied); fields that do not apply (tile: `table`,
`latitude`, `longitude`, `geometry`, `colorBy`, `sizeBy`, `lineBy`; feature: `latitude`, `longitude`,
`sizeBy`, `lineBy`; map level: `colorBy`, `sizeBy`, `lineBy`, `referenceLayers`, `fittingModels`);
aggregated lat/lon without a marker-by; positions found by column name.

## Recipes

### R1 Create the map [API]
```python
visual = page.Visuals.AddNew(VisualTypeIdentifiers.MapChart2)    # TypeId "Spotfire.WebMapChart"
mc = visual.As[Maps.MapChart]()
```
A map made through the API is bare: 0 layers, no background, `Projection` WebMercator (EPSG:3857),
`AutoZoom False`, `ViewExtent null`, `Data.DataTableReference null`, `Data.MarkingReference null`, title
`"Map chart"`. `VisualTypeIdentifiers.MapChart` and `Visuals.MapChart` are the obsolete map. Import the
map types from `Spotfire.Dxp.Application.Visuals.Maps` under aliases: all library modules share one
namespace, and `from Spotfire.Dxp.Application.Visuals import *` would rebind `MapChart`.

### R2 Background [API][DXP]
```python
tile = mc.Layers.AddNewStandardTileLayer()      # default title "Map Layer"
tile.Title = "Rich reference map"                # what Analyst 14.x and 15.0 name it
```
`ServiceName` `""` = Automatic, as in every Analyst map [DXP]. Tile layers default to
`IncludeInAutoZoom False` and honor layer-level `Transparency` (0..1, 1 = invisible). Keep
`mc.Projection` WebMercator while a tile layer is enabled. Other services through the layer setting
`{"ServiceName": "..."}` (valid names: **Not yet tested**, M3).

### R3 Marker layer [API][DXP]
```python
layer, mv = unpack(mc.Layers.AddNewMarkerLayer(table), MarkerLayerVisualization)
layer.Title = "Pump Stations"
mv.PositioningMethod = PositioningMethod.LongitudeLatitude
mv.XAxis.Expression = "[Longitude]"           # continuous: no angle brackets
mv.YAxis.Expression = "[Latitude]"
mv.ColorAxis.Expression = "Avg([Discharge Pressure (psig)])"   # then coloring (rules reset when it changes)
mv.SizeAxis.Expression = "Avg([Flow Rate (bbl/d)])"
mv.Data.MarkingReference = marking
```
- `AddNewMarkerLayer(DataTable, out MarkerLayerVisualization)` returns `(layer, viz)` in IronPython;
  `unpack` takes `result[0]` and calls `layer.As[MarkerLayerVisualization]()`, which works whether or not
  the tuple comes back.
- It only creates the layer and sets its table: no axes, no marking, title `"Marker Layer"`.
- Several rows per site: aggregate the position and set a marker-by: latitude `Avg([Latitude])`,
  longitude `Avg([Longitude])`, layer setting `{"MarkerByAxis.Expression": "<[Station]>"}`. Aggregated
  positions without a marker-by draw one marker for all rows (the builder warns).
- Useful layer settings: `MarkerSize` (Single, % of the plot, default 3.5), `LabelColumn.Expression`
  (`First([Station])`), `LabelVisibility` (`None`/`Marked`/`All`), `MaxNumberOfLabels`, `Transparency`
  (on the visualization for data layers), `MarkerByAxis.Expression`, `DrawingOrderAxis.Expression`,
  `Enabled`.

### R4 Feature layer from a GeoDataFrame [API][DXP]
```python
flayer, fv = unpack(mc.Layers.AddNewFeatureLayer(table), FeatureLayerVisualization)  # DataTable overload
flayer.Title = "Pipeline Segments"
fv.GeometryByAxis.Expression = "<baserowid()>"   # one feature per row (what AutoConfigure sets)
fv.ColorAxis.Expression = "Sum([Length (km)])"
```
- The table needs a Binary WKB column whose column property `MapChart.ColumnTypeId` is `Geometry`. A
  Python data function that returns a geopandas `GeoDataFrame` produces exactly that (the `spotfire`
  Python package's SBDF export): one Binary column named `Geometry` (whatever the frame calls it) with
  `{"MapChart.ColumnTypeId": "Geometry", "ContentType": "application/x-wkb"}`, plus the table property
  `MapChart.GeographicCrs = crs.to_string()`. Nothing else (no XCenter/YCenter). Keep one geometry column
  per GeoDataFrame.
- geopandas and shapely come from the "Spotfire Geospatial Library" Python package, which Analyst and the
  server both need. Write string columns as pandas `"string"` dtype so empty outputs stay typed (see the
  example function).
- `AddNewFeatureLayer(String, ...)` loads a file: always pass the `DataTable`.
- Other sources: the builder tags the column through the public column-property API before it adds the
  layer (**Not yet tested**, M5):
```python
reg = Document.Data.Properties
if not reg.ContainsProperty(DataPropertyClass.Column, "MapChart.ColumnTypeId"):
    reg.AddProperty(DataPropertyClass.Column, DataProperty.CreateCustomPrototype(
        "MapChart.ColumnTypeId", DataType.String, DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated))
col.Properties.SetProperty("MapChart.ColumnTypeId", "Geometry")
col.Properties.ContentType = "application/x-wkb"
```
  The CRS defaults to the layer projection (EPSG:4326). Non-WGS84 data needs the table property
  `MapChart.GeographicCrs` or the layer setting `{"Projection": "WebMercator"}` (only the static
  `None`/`WebMercator`/`Wgs84` convert from JSON; any EPSG code through a postScript with
  `Projection("EPSG:...")`).
- Feature layer settings: `LineFeatureVisualAttributes.LineWidth`, `PointFeatureVisualAttributes.PointSize`,
  `PolygonFeatureVisualAttributes.BorderWidth`, `LabelVisibility` (default `All`), `Transparency`.

### R5 Route lines: markers joined by a line connection [API][DXP]
```python
lc = mv.LineConnection
lc.ConnectionAxis.Expression = "<[Route ID]>"   # one polyline per category
lc.OrderAxis.Expression = "Avg([Seq])"          # aggregated: marker by <> aggregates (rules above)
lc.Width = Single(4.0); lc.UseMarkerColor = True; lc.IsBackground = True
mv.MarkerSize = Single(0.0)                     # hide the vertex markers
```
Without an order the vertices connect in row order (a working route map leaves it empty and sets
`DrawingOrderAxis [Draw Order]`). A raw `[Seq]` order blanks the whole map ("Please specify an aggregation
method.", see the rules above). The other route pattern is R4 over WKB LineStrings: use R5 for vertex
tables with lat/lon and a sequence, R4 when the source has geometries or polygons.

### R6 Map level: interactive layer, trellis layer, map table, zoom [API][DXP]
```python
mc.InteractiveLayerReference = top_most_enabled_data_layer
mc.TrellisLayerReference = first_data_layer_on_the_visual_table
mc.AutoZoom = True
vis_common(visual, mc, common)   # map Data.DataTableReference = the trellis layer's table
```
- Interactive layer (the layer that reacts to marking and hover): the builder sets the top-most enabled
  data layer explicitly. It is drawn on top, so it is the one users click.
- Trellis layer: the property documentation calls it "the data layer that will control trellising"
  (`LayerVisualization.TrellisingFollowsMainLayer`, default false, makes another layer follow it).
  Analyst maps keep the map-level `Data.DataTable` equal to the trellis layer's table, even when that
  layer is not the first [DXP]. The builder sets the trellis layer on the visual's table and gives
  `vis_common` that layer's table, so the pair stays consistent.
- `mc.AutoZoom = True` clears any stored `ViewExtent` and follows the union of the enabled layers with
  `IncludeInAutoZoom` (data layers yes, tile layers no). While AutoZoom is on, Spotfire resets
  `ViewExtent` whenever the layers change: a fixed view needs `AutoZoom = False` first. AutoZoom off keeps
  the user's view when filters change (overview maps); on follows the data (maps limited by a marking).
- Fixed view (postScript, `content` = the MapChart; Analyst maps persist EPSG:3857 metres):
```python
import math
from Spotfire.Dxp.Application.Visuals.Maps import GeographicExtent, Projection
R = 20037508.342789244
def mx(lon):
    return lon * R / 180.0
def my(lat):
    return math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * R / math.pi
content.AutoZoom = False
content.ViewExtent = GeographicExtent.Create(Projection.WebMercator, mx(-103.3), my(31.2), mx(-101.3), my(32.4))
```
  (`GeographicExtent.Create(Projection, west, south, east, north)`.)
- `Layers.Move(Layers.IndexOf(layer), 0)` sends a layer to the back; `layer.Enabled = False` hides it
  (the layer's check box); `layer.VisibleZoomLevelRange = ZoomLevelRange(6, None)` shows it from zoom
  level 6 inwards.

### R7 Beyond the spec format (postScript, `content` = the MapChart) [API]
- TMS background: `t = content.Layers.AddNewTmsLayer(); t.Title = "OpenStreetMap";
  t.UrlTemplate = Uri("https://tile.openstreetmap.org/{z}/{x}/{y}.png");
  content.Layers.Move(content.Layers.IndexOf(t), 0)`. `{x}`, `{y}`, `{z}` are required.
  `t.CopyrightInfoItems.Add(CopyrightInfo(text, link))`: `CopyrightInfo` and `CopyrightInfoItems` are
  [api 14.8] (newer than 14.6).
- Shapes: `mv = content.Layers[4].As[MarkerLayerVisualization](); mv.ShapeAxis.Expression = "<[Status]>";
  mv.ShapeAxis.ShapeMap[CategoryKey("Tripped")] = MarkerShape(MarkerType.TriangleUp)` (not
  `ShapeAxis.Scheme`, which is obsolete).
- Tooltip lines: `mv.Details.Items.AddExpression("Avg([Flow Rate (bbl/d)]) as [Flow]")`.
- Pies per site: set `mv.MarkerClass = MarkerClass.Chart` first (only then `ColorAxis` is the pie color
  axis), then `mv.PieMarker.SectorSizeAxis.Expression`.
- Plant diagram: `content.Projection = Projection.None`, `img = content.Layers.AddNewImageLayer(path)`,
  `img.SetExtent(GeographicExtent.Create(Projection.None, 0.0, 0.0, 30.0, 30.0))`, marker layers with
  `Projection = Projection.None`, no tile layer.

## Pitfalls

1. Never call `MapChart.AutoConfigure()`: it clears every layer. Layer and visualization
   `AutoConfigure()` rename the layer to the table name, overwrite X/Y and put the first numeric column on
   the size axis. `AutoConfigureLayers()` depends on the machine's preferences. `AutoConfigureGeocoding`
   loads library geocoding tables. The builder calls none of them.
2. `AddNew*Layer` appends front-most: a background added after data layers covers them (the builder warns
   when a tile layer follows a data layer). Labels or roads tile overlays on top are fine.
3. Set titles on the `MapChartLayer`; `VisualContent.Title` of a layer visualization is not shown.
4. Transparency: tile and WMS layers on the layer; data layers on the visualization (layer-level
   `Transparency` is not supported there: `MapChartLayer.SupportsTransparency` is false).
5. Write expressions as Spotfire stores them: X/Y continuous (`[Longitude]`), color-by categorical
   `<[Status]>` or continuous `Avg([P])`, connection and geometry-by categorical (`<[Route ID]>`,
   `<baserowid()>`); size, labels, line order, rotation and tooltip expressions aggregated unless the
   marker-by contains `baserowid()` (one raw label blanks the whole map).
6. Set the colorBy expression before the coloring: the color axis resets its rules when the expression
   changes. For pies set `MarkerClass` before `ColorAxis`.
7. `MarkerSize`, `LineWidth`, `Width`, `PointSize`, `BorderWidth` are Single (saved as float32: compare
   with a tolerance); `Transparency` and extents are Double.
8. `Projection("")` throws (use `Projection.None`); unsupported EPSG codes throw `ArgumentException`.
9. Do not rely on `TileLayer.IncludeInResetViewExtent`: setting it has no effect (**Not yet tested** live).
10. Data must exist first: `AddNew*Layer` needs the `DataTable`, so map tables made by data functions need
    `executeAtBuild: true`.
11. Column property name casing: write `MapChart.ColumnTypeId` (the `spotfire` Python package writes it
    so; one saved DXP persists it lower-case; lookups are case-insensitive, inferred).
12. Obsolete: `ScaleFont`/`LabelFont` (use `...FontMetadata`), `ShapeAxis.Scheme` (use `ShapeMap`),
    `TmsLayer.CopyrightText`/`CopyrightLink` (use `CopyrightInfoItems`). `MarkerLabelLayout` is
    `DoNotUseOutsideAssembly` (leave `LabelLayout` at Auto).
13. The map-level `Data` is not where layer data is limited: limits, marking and filtering live on each
    layer's visualization `Data`. A visual-level `table` that no layer uses means nothing on a map; the
    builder warns and uses the trellis layer's table.

## Not yet tested

| # | check |
|---|---|
| M1 | A new map has `Layers.Count == 0`, no table, no marking (the builder clears as a safety net) |
| M2 | `AddNewMarkerLayer(table)` / `AddNewFeatureLayer(table)` return a `(layer, viz)` tuple in IronPython (the builder works either way) |
| M3 | `ServiceName ""` renders the rich reference map; valid names from `StandardTileLayer.AvailableServiceNames()` |
| M4 | A feature layer on a GeoDataFrame table renders without AutoConfigure; `fv.ActiveGeocodingTableReference` is the table and `Projection` EPSG:4326 after save |
| M5 | Tagging an untagged WKB column (registry `AddProperty` + `SetProperty`) makes the feature layer render; `GetProperty` on a never-registered name returns null rather than throwing (the builder catches either) |
| M6 | Initial view of a map with `AutoZoom False` and no `ViewExtent` (expected: the reset extent of the data layers, stored as `InitialExtent` on first render as Analyst maps do; else the world view) |
| M7 | `MarkerSize 0` hides vertex markers while the line connection still draws |
| M8 | `ZoomLevelRange(6, None)` accepts Python None for `Int32?` |
| M9 | The builder's `TrellisLayerReference` and the map-level `Data.DataTableReference` (set by vis_common to the trellis layer's table) are kept after save; whether Spotfire syncs the map `Data` to the trellis layer by itself |
| M10 | `MapChartLayer.Transparency` on a data layer is saved but has no visual effect |
| M11 | TMS `UrlTemplate` keeps `{x}{y}{z}` unescaped (`Uri.ToString()`) |
| M12 | `Data.LimitingMarkingsEmptyBehavior` and `WhereClauseExpression` on a layer limit what the layer draws |
| M13 | The data function's GeoDataFrame output keeps the `Geometry` tag through the data-function import (DXPs saved by Analyst 15.0 show it does) |
| M14 | Per-layer legend items hidden by `layerLegends` stay hidden after save and reopen |

## Saved structure (what verify_dxp checks)

```
Visual  Title, ShowTitle
  InternalContent: MapChart   TypeId "Spotfire.WebMapChart"
    AutoZoom, ViewExtent, InteractionMode, MarkingMode, Projection.Identifier "EPSG:3857",
    InteractiveLayerReference -> MapChartDataLayer, TrellisLayerReference -> MapChartDataLayer,
    Data (DataTable = the trellis layer's table, Marking, no Filterings), Legend.Visible
    Layers: MapChartLayerCollection -> Items: MapChartLayer[n]        index 0 = back
      [i] StandardTileLayer "<title>"  Title, Enabled, Transparency, ServiceName, IncludeInAutoZoom false
      [i] MapChartDataLayer "<title>"  Title, Enabled, Projection "EPSG:4326", IncludeInAutoZoom true
            Visualization: MarkerLayerVisualization  TypeId "Spotfire.WebMarkerLayerVisualization"
              PositioningMethod LongitudeLatitude
              ScatterLayer.X / .Y / .Color / .Size / .Marker (ExpressionTexts.Expression)
              ScatterLayer.LineConnection.Line (lineBy) / .Order, Width, UseMarkerColor, IsBackground
              ScatterLayer.MarkerSize, .LabelVisibility, .LabelColumn
              Data: DataTable, Marking, UseActiveFiltering, Filterings.Items[].Reference,
                    LimitingMarkingsEmptyBehavior, WhereClauseExpression
            Visualization: FeatureLayerVisualization TypeId "Spotfire.WebFeatureLayerVisualization"
              GeometryByAxis.Expression, ColorAxis.Expression, LabelVisibility, Transparency,
              ActiveGeocodingTableReference = the layer table, Data: (as above)
```

Per spec item: layer count, order and kind (`StandardTileLayer` / marker / feature viz TypeId) against
`layers` (and `created.maps[vid].layers`); each `title`; data-layer table = `table` (or the visual's);
X = `longitude`, Y = `latitude` (or the XCenter/YCenter columns); Color = `colorBy` (`<>` for a fixed
coloring without colorBy); Size = `sizeBy`; LineConnection.Line = `lineBy` (`""` or `<>` = none);
GeometryByAxis = `<baserowid()>` or the `<...>` geometry; every data layer's Marking = `marking` (none
when null); limits on the data layers of the visual's table only; `UseActiveFiltering` = `useFiltering`
on every data layer; map-level `Data` without filterings; `InteractiveLayerReference` /
`TrellisLayerReference` = `created.maps[vid].interactiveLayer` / `.trellisLayer`, and the map
`Data.DataTable` = the trellis layer's table; `AutoZoom` = `autoZoom` (a postScript may override it);
feature tables have a Binary column with `MapChart.ColumnTypeId = Geometry`; the marker-aggregation rule
above. Expressions are byte-exact; Single values with a tolerance.

## Standard engine (scripts/engine/builders/map.py)

The standard engine's map builder follows `vis_map`. Every member is declared in the part's `# @api` /
`# @set` lines and checked with `sfapi.py has` at each build. It ran in a live build on Analyst 15.0 (the
build behind "What makes a map draw nothing"). Still **Not yet tested** in the engine: a feature layer on
an embedded SBDF renders after the builder tags the WKB column, `MarkerSize 0` with a line connection,
`extent` as the first view, layer `settings` landing on the visualization or the layer as intended, the
star marker shape, and `layerLegends`.

| item (`ok` name) | what | library equivalent |
|---|---|---|
| `<vid>: layer <title> geometry column` | feature layers, before the layer: find the WKB column (`column`, else tagged, else named Geometry); when `MapChart.ColumnTypeId` is missing: Binary check, register the column property (`DefaultAttributes \| IsPropagated`) and set `Geometry`; `ContentType = application/x-wkb` when empty; table property `MapChart.GeographicCrs = EPSG:4326` when missing (registered the same way); a NOTE line lists what the builder had to set | `_maps_prepare_geometry` (+ CRS) |
| `<vid>: layer <title>` | `AddNewStandardTileLayer()` / `AddNewMarkerLayer(table)` / `AddNewFeatureLayer(table)` (DataTable overloads; the out parameter comes back in a tuple, `As[T]()` either way), `Title` | `_maps_add_layer` |
| `... position` | `PositioningMethod.LongitudeLatitude`, X = longitude, Y = latitude | `_maps_position_markers` |
| `... line defaults` | `LineConnection.UseMarkerColor = True`, `Width = 2`, `IsBackground = True` (Analyst's own defaults) | `_maps_line_connection` |
| `... size by`, `shapes`, `labels`, `marker size`, `line by` | `SizeAxis`, `ShapeAxis.Expression` / `DefaultShape = MarkerShape(MarkerType.X)`, `LabelColumn.Expression` + `LabelVisibility`, `MarkerSize` (Single), `LineConnection.ConnectionAxis` | `_maps_size_by`, settings |
| `... geometry by` | `GeometryByAxis.Expression` (`<baserowid()>` by default) | `_maps_geometry_by` |
| `... color by`, `... coloring` | `ColorAxis.Expression` first (`<>` for a fixed color), then `configure` on `ColorAxis.Coloring` | `_maps_color_by`, `_maps_apply_coloring` |
| `... data` | `Data.MarkingReference` (layer `marking`, else the default marking), `Data.Filterings.Add` per limiting marking, `LimitingMarkingsEmptyBehavior`, `WhereClauseExpression` | `_maps_set_marking`, `_maps_set_limits` |
| `... setting <path>` | `set_setting` on the visualization, or on the layer for `Title` and members the visualization lacks (`Enabled`, `IncludeInAutoZoom`, `Projection`, `VisibleZoomLevelRange`) and for tile layers | `_maps_layer_settings` |
| `<vid>: interactive layer` | the data layer titled `interactiveLayer`, else the top-most enabled data layer | `_maps_set_interactive` |
| `<vid>: trellis layer`, `<vid>: map data` | first enabled data layer on the visual's table (else on it, else the first data layer); map `Data.DataTableReference` = that layer's table, `MarkingReference` = the default marking (`data_links` sets a named one) | `_maps_set_trellis`, `vis_common` |
| `<vid>: zoom` | `extent`: `AutoZoom = False`, then `ViewExtent = GeographicExtent.Create(Projection.WebMercator, w, s, e, n)` (metres, converted from the spec's degrees by the converter); else `AutoZoom` | `_maps_set_zoom` + the R6 postScript recipe |
| `<vid>: layer legends` | feature `layerLegends`: `item.Visible = False` on every data layer's `Legend.Items` whose runtime type matches a `layerLegendHide` kind (**Not yet tested**) | none (the library has no layer legend step) |

Spec fields only the standard engine reads: the layer fields `labelBy`, `labels`, `markerSize`, `shape`,
`shapeBy`, `marking`, `limitByMarkings`, `emptyMarkingBehavior`, `limitExpression` and the map fields
`extent` and `interactiveLayer` ([spec-format.md](spec-format.md) "Maps"); the library ignores them.
Marker layers without latitude and longitude are positioned from the table's columns known at generation
time (SBDF header or the declared columns of a data-function table: XCenter/YCenter, else
Longitude/Latitude names); otherwise the spec needs them.

The route map of "A working route map" in spec terms: tile `settings.Transparency 0.45`; overlay feature
layers with gradients and `settings {"Enabled": false, "Transparency": 0.71}` (switched off at start);
the route as a marker layer with `lineBy "<[Segment ID]>"`, `settings {"MarkerSize": 0,
"LineConnection.Width": 4, "DrawingOrderAxis.Expression": "[Draw Order]"}` and a min / median / max
gradient; the stations with `shape "StarFive"`, a categorical coloring, `labelBy` and a layer
`limitExpression`; the pumps with a categorical coloring; `interactiveLayer` = the stations layer.
`InitialExtent` (stored by Analyst after the first render) has no API; `extent` stores `ViewExtent`,
which Analyst also persists.
