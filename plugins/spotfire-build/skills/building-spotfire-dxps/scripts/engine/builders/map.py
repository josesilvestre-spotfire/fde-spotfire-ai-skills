# Standard engine, kind "map": map chart (lib/75_maps.py) with
# tile, marker and feature layers, back to front in APP order
# (AddNew*Layer appends front-most). Never calls AutoConfigure: on the
# map it clears every layer, on a layer it renames it and rewrites axes.
# APP keys: table (the visual's table: the trellis layer is the first
# enabled data layer on it, and the map's own data follows the trellis
# layer's table), layers [...], autoZoom (False; absent = on), extent
# [west, south, east, north] in Web Mercator metres (AutoZoom off, then
# ViewExtent), interactive (the title of the data layer that reacts to
# clicks; absent = the top-most enabled data layer). Layer keys: kind
# ("tile" | "marker" | "feature"), title,
# settings {path: value} (features/settings.py: relative to the layer
# visualization, or to the layer for Title, members only the layer has
# - Enabled, IncludeInAutoZoom, Projection, VisibleZoomLevelRange, ... -
# and every path of a tile layer: Transparency, Enabled). Data layers:
# table, colorBy ("<>" for a fixed color), coloring (features/
# coloring.py), marking (name or None; absent = the default marking),
# limits [marking names], empty, where. Marker layers: x (longitude),
# y (latitude) and the keys of _markers.py (sizeBy, shapeBy, shape,
# labelBy, labels, markerSize, lineBy), with Analyst's own line defaults
# first (UseMarkerColor, width 2, behind the markers). Feature layers:
# geometry (geometry-by expression, absent = one feature per row),
# column (the WKB column; absent = the column tagged Geometry, else the
# column named Geometry), tagged as map geometry (MapChart.ColumnTypeId
# Geometry, ContentType application/x-wkb, table MapChart.GeographicCrs
# EPSG:4326) when the SBDF import did not keep its metadata.
# layerLegendHide [kind, ...] (feature layerLegends, from the spec's
# legend.hide on a map): every data layer has its own Legend (the map's
# holds only title, description and trellis), so the kinds are hidden
# there, last (a color-axis change rebuilds the color items).
# Expressions are written as given. A marker layer whose marker-by has no
# baserowid() aggregates its markers: its label, size, line order and
# rotation must then be aggregated (First(...), Avg(...)), or Spotfire
# raises "Please specify an aggregation method." for the layer and draws
# nothing on the whole map (dxpgen rejects such a spec and verify_dxp
# FAILs such a DXP: references/api-maps.md).
# Converter: scripts/t3/map.py.
# @uses _markers
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.Layers
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.InteractiveLayerReference
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.TrellisLayerReference
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.AutoZoom
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.ViewExtent
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.Data
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChart.Legend
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartLayerCollection.AddNewStandardTileLayer
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartLayerCollection.AddNewMarkerLayer(DataTable, out MarkerLayerVisualization)
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartLayerCollection.AddNewFeatureLayer(DataTable, out FeatureLayerVisualization)
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartLayer.Title
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartLayer.Enabled
# @api Spotfire.Dxp.Application.Visuals.Maps.MapChartDataLayer.As
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.PositioningMethod
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.XAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.YAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.ColorAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.LineConnection
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.Data
# @api Spotfire.Dxp.Application.Visuals.Maps.FeatureLayerVisualization.GeometryByAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.FeatureLayerVisualization.ColorAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.FeatureLayerVisualization.Data
# @api Spotfire.Dxp.Application.Visuals.Maps.GeographicExtent.Create(Projection, Double, Double, Double, Double)
# @api Spotfire.Dxp.Application.Visuals.Maps.Projection.WebMercator
# @api PositioningMethod.LongitudeLatitude; ScaleAxis.Expression
# @api ColorAxis.Expression; GroupByAxis.Expression
# @api Spotfire.Dxp.Application.Visuals.LineConnection.UseMarkerColor
# @api Spotfire.Dxp.Application.Visuals.LineConnection.Width
# @api Spotfire.Dxp.Application.Visuals.LineConnection.IsBackground
# @api VisualizationData.MarkingReference; VisualizationData.Filterings
# @api VisualizationData.WhereClauseExpression
# @api VisualizationData.LimitingMarkingsEmptyBehavior
# @api VisualizationFilteringCollection.Add(DataSelection)
# @api VisualizationFilteringCollection.Contains(DataSelection)
# @api DataMarkingSelectionCollection.TryGetValue(String, out DataMarkingSelection)
# @api LimitingMarkingsEmptyBehavior.ShowEmpty; DataManager.Markings
# @api DataTable.Columns; DataTable.Name; DataTable.Properties
# @api DataColumnCollection.TryGetValue(String, out DataColumn)
# @api DataColumnCollection.GetEnumerator; DataColumn.Name; DataColumn.DataType
# @api DataColumn.Properties; DataColumnProperties.PropertyExists(String)
# @api DataColumnProperties.GetProperty(String)
# @api DataColumnProperties.SetProperty(String, Object)
# @api DataColumnProperties.ContentType; DataType.Name; DataType.Binary
# @api DataType.String; DataTableProperties.HasPropertyValue(String)
# @api DataTableProperties.GetProperty(String)
# @api DataTableProperties.SetProperty(String, Object); DataManager.Properties
# @api DataPropertyRegistry.ContainsProperty(DataPropertyClass, String)
# @api DataPropertyRegistry.AddProperty(DataPropertyClass, DataProperty)
# @api DataProperty.CreateCustomPrototype(String, DataType, DataPropertyAttributes)
# @api DataProperty.DefaultAttributes; DataPropertyAttributes.IsPropagated
# @api DataPropertyClass.Column; DataPropertyClass.Table
# @api VisualTypeIdentifiers.MapChart2
# @set Spotfire.Dxp.Application.Visuals.Maps.MapChart.InteractiveLayerReference
# @set Spotfire.Dxp.Application.Visuals.Maps.MapChart.TrellisLayerReference
# @set Spotfire.Dxp.Application.Visuals.Maps.MapChart.AutoZoom
# @set Spotfire.Dxp.Application.Visuals.Maps.MapChart.ViewExtent
# @set Spotfire.Dxp.Application.Visuals.Maps.MapChartLayer.Title
# @set Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.PositioningMethod
# @set Spotfire.Dxp.Application.Visuals.LineConnection.UseMarkerColor
# @set Spotfire.Dxp.Application.Visuals.LineConnection.Width
# @set Spotfire.Dxp.Application.Visuals.LineConnection.IsBackground
# @set ScaleAxis.Expression; ColorAxis.Expression; GroupByAxis.Expression
# @set VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference
# @set VisualizationData.WhereClauseExpression
# @set VisualizationData.LimitingMarkingsEmptyBehavior
# @set DataColumnProperties.ContentType
from System import Single
from Spotfire.Dxp.Application.Visuals import PositioningMethod
from Spotfire.Dxp.Application.Visuals.Maps import MapChart
from Spotfire.Dxp.Application.Visuals.Maps import MarkerLayerVisualization
from Spotfire.Dxp.Application.Visuals.Maps import FeatureLayerVisualization
from Spotfire.Dxp.Application.Visuals.Maps import GeographicExtent
from Spotfire.Dxp.Application.Visuals.Maps import Projection
from Spotfire.Dxp.Data import DataProperty, DataPropertyAttributes
from Spotfire.Dxp.Data import DataPropertyClass, DataType
from Spotfire.Dxp.Data import LimitingMarkingsEmptyBehavior

# ------------------------------------------------------------------ map
GEOMETRY_TAG = "MapChart.ColumnTypeId"
CRS_TAG = "MapChart.GeographicCrs"


def build_map(v, vs):
    vid = vs["id"]
    mc = v.As[MapChart]()
    built = []
    for ls in vs["layers"]:
        name = vid + ": layer " + ls["title"]
        if ls["kind"] == "feature":
            ok(name + " geometry column", map_geometry, name, ls)
        layer = ok(name, map_layer, mc, ls)
        if layer is not None:
            built.append(layer)
            map_configure(name, layer, ls)
    ok(vid + ": interactive layer", map_interactive, mc, built,
       vs.get("interactive"))
    table = ok(vid + ": trellis layer", map_trellis, mc, built, vs["table"])
    ok(vid + ": map data", map_data, mc, table or vs["table"])
    ok(vid + ": zoom", map_zoom, mc, vs)
    ok(vid + ": legend", legend, mc, vs)
    # @feature layerLegends
    if vs.get("layerLegendHide"):
        ok(vid + ": layer legends", map_layer_legends, built,
           vs["layerLegendHide"])
    # @endfeature


def map_layer(mc, ls):
    """[layer, layer visualization or None (tile), APP layer]."""
    kind = ls["kind"]
    if kind == "tile":
        layer, viz = mc.Layers.AddNewStandardTileLayer(), None
    elif kind == "marker":
        layer, viz = unpack(mc.Layers.AddNewMarkerLayer(T[ls["table"]]),
                            MarkerLayerVisualization)
    else:
        layer, viz = unpack(mc.Layers.AddNewFeatureLayer(T[ls["table"]]),
                            FeatureLayerVisualization)
    layer.Title = ls["title"]
    return [layer, viz, ls]


def unpack(result, viz_type):
    """(layer, typed visualization): IronPython returns the out
    parameter in a tuple; As[T]() works either way."""
    layer = result[0] if isinstance(result, tuple) else result
    return layer, layer.As[viz_type]()


def map_configure(name, built, ls):
    layer, viz = built[0], built[1]
    if viz is not None:
        if ls["kind"] == "marker":
            ok(name + " position", map_position, viz, ls)
            ok(name + " line defaults", map_lines, viz)
            marker_style(name, viz, ls)
        else:
            ok(name + " geometry by", map_geometry_by, viz, ls)
        if "colorBy" in ls:
            ok(name + " color by", map_color_by, viz, ls["colorBy"])
        # @feature coloring
        if ls.get("coloring"):
            ok(name + " coloring", axis_coloring, name + " coloring",
               viz.ColorAxis, ls["coloring"])
        # @endfeature
        ok(name + " data", map_layer_data, viz, ls)
    # @feature settings
    if ls.get("settings"):
        map_settings(name, layer, viz, ls["settings"])
    # @endfeature


def map_position(viz, ls):
    viz.PositioningMethod = PositioningMethod.LongitudeLatitude
    viz.XAxis.Expression = ls["x"]
    viz.YAxis.Expression = ls["y"]


def map_lines(viz):
    """What Analyst sets on every marker layer it makes (the API leaves
    width 1, black, in front of the markers)."""
    lc = viz.LineConnection
    lc.UseMarkerColor = True
    lc.Width = Single(2.0)
    lc.IsBackground = True


def map_geometry_by(viz, ls):
    viz.GeometryByAxis.Expression = ls.get("geometry", "<baserowid()>")


def map_color_by(viz, expression):
    """Before the coloring: the axis resets its rules when it changes."""
    viz.ColorAxis.Expression = expression


def map_marking(name):
    if name is None:
        return None
    found, m = Document.Data.Markings.TryGetValue(name)
    if not found:
        raise Exception("no marking " + name)
    return m


def map_layer_data(viz, ls):
    """Marking, marking limits, empty behavior and limit expression of
    one data layer (layer data is limited on the layer, not the map)."""
    data = viz.Data
    data.MarkingReference = (map_marking(ls["marking"]) if "marking" in ls
                             else MARK)
    for name in ls.get("limits", []):
        m = map_marking(name)
        if not data.Filterings.Contains(m):
            data.Filterings.Add(m)
    if "empty" in ls:
        data.LimitingMarkingsEmptyBehavior = getattr(
            LimitingMarkingsEmptyBehavior, ls["empty"])
    if ls.get("where"):
        data.WhereClauseExpression = ls["where"]


# @feature settings
def map_settings(name, layer, viz, settings):
    """Layer settings, one at a time: the visualization's own members
    there, Title and layer-only members (Enabled, ...) on the layer."""
    for path in sorted(settings):
        head = path.split(".")[0]
        target = layer
        if viz is not None and head != "Title" and hasattr(viz, head):
            target = viz
        ok(name + " setting " + path, set_setting, target, path,
           settings[path])
# @endfeature


def map_interactive(mc, built, title=None):
    """The data layer titled title, else the top-most enabled data layer
    reacts to marking and hover (it is drawn on top, so it is the one
    users click)."""
    chosen = None
    for layer, viz, ls in built:
        if viz is not None and layer.Enabled:
            chosen = layer
    for layer, viz, ls in built:
        if viz is not None and ls["title"] == title:
            chosen = layer
    if chosen is not None:
        mc.InteractiveLayerReference = chosen


def map_trellis(mc, built, table):
    """Trellis layer: the first enabled data layer on the visual's
    table (else the first on it, else the first data layer). Returns
    its table name: the map's own data follows it, as in every map
    made in Analyst."""
    data = [b for b in built if b[1] is not None]
    if not data:
        return None
    on_table = [b for b in data if b[2]["table"] == table]
    enabled = [b for b in on_table if b[0].Enabled]
    chosen = (enabled or on_table or data)[0]
    mc.TrellisLayerReference = chosen[0]
    return chosen[2]["table"]


def map_data(mc, table):
    mc.Data.DataTableReference = T[table]
    mc.Data.MarkingReference = MARK


def map_zoom(mc, vs):
    """extent: a fixed first view (AutoZoom off first: with AutoZoom on
    Spotfire clears ViewExtent whenever layers change)."""
    if vs.get("extent"):
        w, s, e, n = vs["extent"]
        mc.AutoZoom = False
        mc.ViewExtent = GeographicExtent.Create(
            Projection.WebMercator, float(w), float(s), float(e), float(n))
    else:
        mc.AutoZoom = bool(vs.get("autoZoom", True))


# @feature layerLegends
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.Legend
# @api Spotfire.Dxp.Application.Visuals.Maps.FeatureLayerVisualization.Legend
# @api Legend.Items; Legend.LegendItemCollection.GetEnumerator
# @api LegendItem.Visible; LegendFilteringsItem; LegendMarkingItem
# @api LegendGroupByItem; LegendLineConnectionItem; LegendColorItem
# @api LegendMarkerShapeItem; LegendSizeItem; LegendMarkerRotationItem
# @api LegendFilterRuleItem; LegendDataTableItem
# @api Spotfire.Dxp.Application.Visuals.Maps.LegendLayerTitleItem
# @set LegendItem.Visible
MAP_LEGEND = {
    "filtering": "LegendFilteringsItem",
    "marking": "LegendMarkingItem",
    "markerBy": "LegendGroupByItem",
    "lineBy": "LegendLineConnectionItem",
    "colorBy": "LegendColorItem",
    "shape": "LegendMarkerShapeItem",
    "size": "LegendSizeItem",
    "rotation": "LegendMarkerRotationItem",
    "limits": "LegendFilterRuleItem",
    "dataTable": "LegendDataTableItem",
    "layerTitle": "LegendLayerTitleItem"}


def map_layer_legends(built, kinds):
    """Every data layer has its own Legend (the map's holds only the
    title, description and trellis items): hide the kinds there."""
    names = [MAP_LEGEND[k] for k in kinds if k in MAP_LEGEND]
    for layer, viz, ls in built:
        if viz is None:
            continue
        for item in viz.Legend.Items:
            if item.GetType().Name in names:
                item.Visible = False
# @endfeature


# --------------------------------------------------- feature geometry
def type_id(column):
    """MapChart.ColumnTypeId of a column, lower case ("" when absent)."""
    props = column.Properties
    try:
        if not props.PropertyExists(GEOMETRY_TAG):
            return ""
        value = props.GetProperty(GEOMETRY_TAG)
    except Exception:
        return ""
    return "" if value is None else str(value).lower()


def geometry_column(t, name):
    if name:
        found, column = t.Columns.TryGetValue(name)
        if not found:
            raise Exception("no column " + name + " in " + t.Name)
        return column
    for column in t.Columns:
        if type_id(column) == "geometry":
            return column
    for column in t.Columns:
        if column.Name.lower() == "geometry":
            return column
    raise Exception(t.Name + " has no geometry column (Binary WKB)")


def register(kind, name):
    reg = Document.Data.Properties
    if not reg.ContainsProperty(kind, name):
        attrs = (DataProperty.DefaultAttributes
                 | DataPropertyAttributes.IsPropagated)
        reg.AddProperty(kind, DataProperty.CreateCustomPrototype(
            name, DataType.String, attrs))


def has_crs(t):
    try:
        return bool(t.Properties.HasPropertyValue(CRS_TAG)
                    and t.Properties.GetProperty(CRS_TAG))
    except Exception:
        return False


def map_geometry(name, ls):
    """The feature layer's WKB column as map geometry, as Spotfire's own
    geocoding settings tag it; a NOTE line says what the SBDF import
    did not keep (Not yet tested)."""
    t = T[ls["table"]]
    column = geometry_column(t, ls.get("column"))
    done = []
    if type_id(column) != "geometry":
        if column.DataType.Name != DataType.Binary.Name:
            raise Exception(column.Name + " is " + column.DataType.Name
                            + "; a feature layer needs Binary WKB")
        register(DataPropertyClass.Column, GEOMETRY_TAG)
        column.Properties.SetProperty(GEOMETRY_TAG, "Geometry")
        done.append(GEOMETRY_TAG)
    if not column.Properties.ContentType:
        column.Properties.ContentType = "application/x-wkb"
        done.append("ContentType")
    if not has_crs(t):
        register(DataPropertyClass.Table, CRS_TAG)
        t.Properties.SetProperty(CRS_TAG, "EPSG:4326")
        done.append(CRS_TAG)
    if done:
        LOG.append("NOTE " + name + ": set by the builder (the SBDF "
                   "import did not keep it): " + ", ".join(done))


BUILDERS["map"] = build_map
TYPE_IDS["map"] = "MapChart2"
