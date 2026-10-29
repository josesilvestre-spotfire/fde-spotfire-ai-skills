# ============================================================================
# 75_maps.py - map chart (TypeId "Spotfire.WebMapChart") and its layers.
#
#   vis_map(page, vspec)   references/spec-format.md visual type `map`; returns the Visual.
#
# Build order for one map (references/api-maps.md):
#   1. page.Visuals.AddNew(VisualTypeIdentifiers.MapChart2) -> Maps.MapChart. A map made through
#      the API is bare: no layers, no table, no marking, AutoZoom False.
#   2. Layers in spec order. The spec lists layers back to front, which is the order of
#      MapChart.Layers; AddNew*Layer() appends front-most, so no Move is needed.
#        tile    AddNewStandardTileLayer()   default service, title "Rich reference map"
#        marker  AddNewMarkerLayer(table)    X = longitude, Y = latitude (or the XCenter/YCenter
#                                            columns of a geometry table), sizeBy, lineBy
#        feature AddNewFeatureLayer(table)   tagged WKB geometry column, GeometryByAxis
#      then per data layer: colorBy + coloring, marking, data limits, layer settings.
#      Every layer and every aspect of it is its own B.step.
#   3. Map level: interactive layer = top-most enabled data layer (what users click); trellis
#      layer = first data layer on the visual's table; AutoZoom; then vis_common() (60_charts)
#      for title, table, marking, legend, settings and postScript. vis_common gets the trellis
#      layer's table as the map's own table (every GUI-built map keeps the two equal) and no data
#      limits (they are on the layers). postScript therefore runs last and can change the zoom.
# Never calls AutoConfigure on the map (it clears every layer), a layer or a layer visualization
# (it renames the layer and puts an arbitrary column on the size axis), nor AutoConfigureLayers.
#
# Expressions (as 60_charts and 70_tables read them): `[$Name]` -> DocumentProperty("Name") in
# latitude, longitude, colorBy, sizeBy, lineBy, a <...> geometry and limitExpression; lineBy is
# categorical-only, so "[Route ID]" is written "<[Route ID]>". A layer-level coloring needs the
# layer's colorBy (or fixed); otherwise it is warned and not applied.
#
# Report: B.created["maps"][<visual id>] = {layers, interactiveLayer, trellisLayer, table,
# autoZoom}, read back after vis_common.
# Requires newer than 14.6: none (newest member used: DataColumn.DataType [api 7.5]).
# Internal API: none. Reference: references/api-maps.md.
# IronPython 3.4: no f-strings, walrus, annotations, tabs or print.
# ============================================================================
from System import Single
from Spotfire.Dxp.Application.Visuals import VisualTypeIdentifiers, PositioningMethod
# Aliased on purpose: `from Spotfire.Dxp.Application.Visuals import *` in any module would rebind
# a bare `MapChart` to the obsolete Visuals.MapChart (all lib modules share one namespace).
from Spotfire.Dxp.Application.Visuals.Maps import MapChart as _maps_MapChart
from Spotfire.Dxp.Application.Visuals.Maps import MarkerLayerVisualization as _maps_MarkerViz
from Spotfire.Dxp.Application.Visuals.Maps import FeatureLayerVisualization as _maps_FeatureViz
from Spotfire.Dxp.Data import (DataProperty, DataPropertyAttributes, DataPropertyClass, DataType,
                               LimitingMarkingsEmptyBehavior)

# Column property that tags map columns ("Geometry", "XCenter", "YCenter", ...). This casing is
# the one in Spotfire's IL and in the spotfire Python package; lookups are case-insensitive.
_maps_TYPE_PROP = "MapChart.ColumnTypeId"
# Title Analyst 14.x/15.0 gives the default background layer (all GUI-built corpus maps).
_maps_TILE_TITLE = "Rich reference map"
# One feature per row: what FeatureLayerVisualization.AutoConfigure sets (IL; every corpus map).
_maps_ROW_FEATURES = "<baserowid()>"
_maps_LON_NAMES = ("longitude", "lon", "long", "lng")
_maps_LAT_NAMES = ("latitude", "lat")
_maps_AGGREGATES = ("avg(", "sum(", "min(", "max(", "first(", "last(", "median(", "count(",
                    "uniquecount(", "stddev(", "var(", "percentile(", "mode(")
# Visual-level data limits. On a map they belong on the data layers (the Layers page of the
# map properties); GUI-built maps keep the map-level Data at its defaults.
_maps_LAYER_LIMITS = {"limitByMarkings": [], "emptyMarkingBehavior": "ShowAll",
                      "limitExpression": None, "useFiltering": True}
# Visual-level fields that have no meaning on the map itself.
_maps_NOT_ON_MAP = {"colorBy": "set it on a layer", "sizeBy": "set it on a marker layer",
                    "lineBy": "set it on a marker layer", "referenceLayers": "maps have none",
                    "fittingModels": "maps have none"}


def vis_map(page, vspec):
    """Map chart with tile, marker and feature layers. Returns the Visual."""
    vid = vspec["id"]
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.MapChart2)
    content = visual.As[_maps_MapChart]()
    if content.Layers.Count > 0:
        # IL: a new map has no layers. Safety net only (Not yet tested: Layers.Count == 0 here).
        content.Layers.Clear()
    table_name = _maps_visual_table_name(vspec)
    layer_specs = vspec.get("layers")
    if layer_specs is None:
        layer_specs = []
    if not isinstance(layer_specs, list):
        B.warn(vid + ": 'layers' must be a list of layer objects; no layers built")
        layer_specs = []
    if not layer_specs:
        B.warn(vid + ": the map has no layers")
    built = []
    for index in range(len(layer_specs)):
        lspec = layer_specs[index]
        target = vid + "/layers[" + str(index) + "]"
        if not isinstance(lspec, dict):
            B.step("map.layer", target, _maps_fail, ("a map layer must be an object",))
            continue
        prepared = None
        if str(lspec.get("kind") or "").strip() == "feature":
            # Tag the geometry before the layer exists, so the layer meets a ready geometry table.
            prepared = B.step("map.geometryColumn", target, _maps_prepare_geometry,
                              (vspec, lspec))
        info = B.step("map.layer", target, _maps_add_layer, (content, vspec, lspec))
        if info is None:
            continue
        info["geometry"] = prepared
        built.append(info)
        _maps_configure_layer(info, vspec, lspec, table_name)
    _maps_check_layers(vspec, layer_specs, built, table_name)
    B.step("map.interactiveLayer", vid, _maps_set_interactive, (content, built))
    trellis = B.step("map.trellisLayer", vid, _maps_set_trellis, (content, built, table_name))
    map_table = table_name
    if trellis is not None and trellis["table"]:
        map_table = trellis["table"]
    B.step("map.autoZoom", vid, _maps_set_zoom, (content, vspec))
    B.step("map.common", vid, _maps_common, (visual, content, vspec, table_name, map_table))
    B.step("map.record", vid, _maps_record, (vid, content, built))
    return visual


# ---- layers ---------------------------------------------------------------------------------
def _maps_add_layer(content, vspec, lspec):
    """Create one layer (appended front-most) and set its title. Returns the layer record."""
    kind = str(lspec.get("kind") or "").strip()
    vid = vspec["id"]
    if kind == "tile":
        layer = content.Layers.AddNewStandardTileLayer()
        title = _maps_title(lspec, _maps_TILE_TITLE)
        layer.Title = title
        for key in ("table", "latitude", "longitude", "geometry", "colorBy", "sizeBy", "lineBy"):
            if lspec.get(key):
                B.warn(vid + "/" + title + ": '" + key + "' does not apply to a tile layer, ignored")
        return {"kind": kind, "layer": layer, "viz": None, "table": None, "tableName": "",
                "title": title, "target": vid + "/" + title}
    if kind not in ("marker", "feature"):
        raise Exception("unknown map layer kind " + repr(kind) + " (expected tile, marker or feature)")
    table = _maps_layer_table(vspec, lspec)
    # The DataTable overloads only: AddNewFeatureLayer(String, ...) would import a file.
    # Both methods have an out parameter (IronPython returns a tuple); _maps_unpack copes either way.
    if kind == "marker":
        layer, viz = _maps_unpack(content.Layers.AddNewMarkerLayer(table), _maps_MarkerViz)
    else:
        layer, viz = _maps_unpack(content.Layers.AddNewFeatureLayer(table), _maps_FeatureViz)
    # The default title is the layer type name ("Marker Layer"); the GUI uses the table name.
    # Always set it on the layer: VisualContent.Title of a layer visualization is not shown.
    title = _maps_title(lspec, table.Name)
    layer.Title = title
    return {"kind": kind, "layer": layer, "viz": viz, "table": table, "tableName": table.Name,
            "title": title, "target": vid + "/" + title}


def _maps_configure_layer(info, vspec, lspec, table_name):
    t = info["target"]
    kind = info["kind"]
    if kind == "tile":
        if lspec.get("settings"):
            B.step("map.layerSettings", t, _maps_layer_settings, (info, lspec["settings"]))
        return
    if kind == "marker":
        B.step("map.position", t, _maps_position_markers, (info, lspec))
        B.step("map.lineConnection", t, _maps_line_connection, (info, lspec.get("lineBy")))
        if lspec.get("sizeBy"):
            B.step("map.sizeBy", t, _maps_size_by, (info, lspec["sizeBy"]))
    else:
        B.step("map.geometryBy", t, _maps_geometry_by, (info, lspec))
        for key in ("latitude", "longitude", "sizeBy", "lineBy"):
            if lspec.get(key):
                B.warn(t + ": '" + key + "' does not apply to a feature layer, ignored")
    if lspec.get("colorBy"):
        B.step("map.colorBy", t, _maps_color_by, (info, lspec["colorBy"]))
    cspec = _maps_coloring_for(vspec, lspec)
    if cspec:
        B.step("map.coloring", t, _maps_apply_coloring, (info, lspec, cspec))
    B.step("map.marking", t, _maps_set_marking, (info, vspec))
    if (vspec.get("useFiltering") is False or vspec.get("limitByMarkings")
            or vspec.get("limitExpression")):
        B.step("map.dataLimits", t, _maps_set_limits, (info, vspec, table_name))
    if lspec.get("settings"):
        B.step("map.layerSettings", t, _maps_layer_settings, (info, lspec["settings"]))


def _maps_fail(message):
    raise Exception(message)


def _maps_title(lspec, default):
    title = lspec.get("title")
    if title is None or not str(title).strip():
        return default
    return str(title)


def _maps_unpack(result, viz_type):
    """(layer, typed visualization) from AddNewMarkerLayer / AddNewFeatureLayer."""
    layer = result
    if isinstance(result, tuple):
        layer = result[0]
    return layer, layer.As[viz_type]()


def _maps_layer_table(vspec, lspec):
    return B.table_or_default(lspec.get("table") or vspec.get("table"))


def _maps_visual_table_name(vspec):
    try:
        return B.table_or_default(vspec.get("table")).Name
    except Exception:
        return ""


def _maps_expr(value):
    """Spec expression -> Spotfire text: `[$Name]` -> DocumentProperty("Name") through 65_coloring's
    coloring_expression, the reading 60_charts and 70_tables give the shorthand (dxpgen accepts it
    in every expression). Looked up at call time; without 65_coloring the text passes through."""
    text = str(value).strip()
    convert = globals().get("coloring_expression")
    if convert is None:
        return text
    return convert(text)


def _maps_color_text(value):
    """colorBy text, built as 65_coloring._coloring_color_by builds it (one expression; a list of
    category levels nested "<[A] NEST [B]>"; [$Name] translated), so map.colorBy and
    apply_coloring set the same expression and the coloring rules are not reset."""
    if not isinstance(value, (list, tuple)):
        return _maps_expr(value)
    levels = []
    for item in value:
        text = str(item).strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1].strip()
        levels.append(text)
    if len(levels) == 1:
        return _maps_expr(value[0])
    return _maps_expr("<" + " NEST ".join(levels) + ">")


def _maps_categorical(value):
    """Expression for a categorical-only axis (line connection): <...> kept, anything else wrapped
    ("[Route ID]" -> "<[Route ID]>")."""
    text = _maps_color_text(value)
    if text.startswith("<") and text.endswith(">"):
        return text
    return "<" + text + ">"


def _maps_is_fixed(cspec):
    return isinstance(cspec, dict) and cspec.get("fixed") is not None


# ---- marker layers ----------------------------------------------------------------------------
def _maps_position_markers(info, lspec):
    viz = info["viz"]
    lon = lspec.get("longitude")
    lat = lspec.get("latitude")
    if bool(lon) != bool(lat):
        raise Exception("a marker layer needs both latitude and longitude")
    if not lon:
        lon, lat = _maps_find_position(info["table"], lspec.get("geometry"))
        if not lspec.get("geometry"):
            B.warn(info["target"] + ": no latitude/longitude in the spec, markers positioned by "
                   + lon + " / " + lat)
    else:
        lon = _maps_expr(lon)
        lat = _maps_expr(lat)
    viz.PositioningMethod = PositioningMethod.LongitudeLatitude   # also the constructor default
    viz.XAxis.Expression = lon     # continuous expressions: no angle brackets
    viz.YAxis.Expression = lat
    settings = lspec.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    if (_maps_is_aggregated(lon) or _maps_is_aggregated(lat)) and "MarkerByAxis.Expression" not in settings:
        B.warn(info["target"] + ": latitude/longitude are aggregated but no marker-by is set, so the "
               "layer draws one marker for all rows; add the layer setting "
               "\"MarkerByAxis.Expression\": \"<[Category]>\"")
    return lon + " / " + lat


def _maps_find_position(table, geometry):
    """Longitude/latitude expressions when the spec gives none.

    Spotfire's own order (IL MarkerLayerVisualization.AutoConfigureLayerVisualization): columns
    tagged XCenter/YCenter (shape-file style geometry tables), then longitude/latitude names.
    """
    x = _maps_tagged_column(table, "XCenter")
    y = _maps_tagged_column(table, "YCenter")
    if x is None or y is None:
        x = _maps_named_column(table, ("xcenter",), True)
        y = _maps_named_column(table, ("ycenter",), True)
    if x is not None and y is not None:
        return x.NameEscapedForExpression, y.NameEscapedForExpression
    if geometry:
        raise Exception("markers on a geometry table need XCenter/YCenter columns in "
                        + table.Name + "; give latitude/longitude, or use kind 'feature' to draw "
                        "the geometry itself")
    x = _maps_named_column(table, _maps_LON_NAMES, True)
    y = _maps_named_column(table, _maps_LAT_NAMES, True)
    if x is None or y is None:
        raise Exception("a marker layer needs latitude and longitude; table " + table.Name
                        + " has no numeric Longitude/Latitude columns")
    return x.NameEscapedForExpression, y.NameEscapedForExpression


def _maps_is_aggregated(expression):
    text = str(expression or "").strip().lower().replace(" ", "")
    for name in _maps_AGGREGATES:
        if text.startswith(name):
            return True
    return False


def _maps_line_connection(info, line_by):
    lc = info["viz"].LineConnection
    # GUI parity: Analyst runs LineConnection.AutoConfigure() on every marker layer it creates
    # (UseMarkerColor True, Width 2, IsBackground True); the API leaves Width 1, black, in front.
    lc.UseMarkerColor = True
    lc.Width = Single(2.0)
    lc.IsBackground = True
    if line_by:
        text = _maps_categorical(line_by)          # categorical: "<[Route ID]>", one line each
        lc.ConnectionAxis.Expression = text
        return text
    return "defaults"


def _maps_size_by(info, expression):
    if isinstance(expression, (list, tuple)):
        text = ", ".join([_maps_expr(v) for v in expression])
    else:
        text = _maps_expr(expression)
    info["viz"].SizeAxis.Expression = text
    return text


def _maps_color_by(info, expression):
    # Set the expression before any coloring: the axis resets its rules when it changes.
    text = _maps_color_text(expression)
    info["viz"].ColorAxis.Expression = text
    return text


# ---- feature layers ---------------------------------------------------------------------------
def _maps_prepare_geometry(vspec, lspec):
    """Find (and if needed tag) the geometry column of a feature layer's table.

    `geometry` is the geometry column name (`Geometry` or `[Geometry]`), or a geometry-by
    expression in angle brackets; absent = the column tagged Geometry, else a column named Geometry.
    """
    table = _maps_layer_table(vspec, lspec)
    text = str(lspec.get("geometry") or "").strip()
    name = None
    if text and not text.startswith("<"):
        name = _maps_unbracket(text)
    column = _maps_geometry_column(table, name)
    tagged = _maps_tag_geometry(column)
    return {"column": column.Name, "tagged": tagged}


def _maps_geometry_by_expression(lspec):
    text = str(lspec.get("geometry") or "").strip()
    if text.startswith("<"):
        return _maps_expr(text)
    return _maps_ROW_FEATURES


def _maps_geometry_column(table, name):
    if name:
        found, column = table.Columns.TryGetValue(name)
        if not found:
            raise Exception("geometry column '" + name + "' not found in table " + table.Name)
        return column
    column = _maps_tagged_column(table, "Geometry")
    if column is None:
        column = _maps_named_column(table, ("geometry",), False)
    if column is None:
        raise Exception("table " + table.Name + " has no geometry column: a feature layer needs a "
                        "Binary WKB column tagged MapChart.ColumnTypeId = Geometry (a GeoDataFrame "
                        "returned by a Python data function has one)")
    return column


def _maps_tag_geometry(column):
    """Tag a WKB column as map geometry, as Spotfire's own geocoding settings do.

    Mirrors the internal ColumnGeocodingSettings.RegisterAndSetMapColumnTypeIdProperty: register
    the column property (DefaultAttributes | IsPropagated) once, then set it. GeoDataFrame
    data-function outputs arrive tagged already. Returns True when this call tagged the column.
    Not yet tested: registering + SetProperty on a non-GeoDataFrame table makes the feature layer
    render (ActiveGeocodingTableReference = the table) without AutoConfigure.
    """
    if _maps_column_type_id(column).lower() == "geometry":
        return False
    if column.DataType.Name != DataType.Binary.Name:
        raise Exception("geometry column " + column.Name + " is " + column.DataType.Name
                        + "; a feature layer needs Binary WKB")
    registry = B.doc.Data.Properties
    if not registry.ContainsProperty(DataPropertyClass.Column, _maps_TYPE_PROP):
        attributes = DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated
        registry.AddProperty(DataPropertyClass.Column,
                             DataProperty.CreateCustomPrototype(_maps_TYPE_PROP, DataType.String,
                                                                attributes))
    column.Properties.SetProperty(_maps_TYPE_PROP, "Geometry")
    if not column.Properties.ContentType:
        column.Properties.ContentType = "application/x-wkb"
    return True


def _maps_geometry_by(info, lspec):
    # Set even when map.geometryColumn failed: the layer then works once the column is tagged.
    by = _maps_geometry_by_expression(lspec)
    info["viz"].GeometryByAxis.Expression = by
    return by


def _maps_unbracket(text):
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1].replace("]]", "]")
    return text


# ---- column lookups ---------------------------------------------------------------------------
def _maps_column_type_id(column):
    """Value of the MapChart.ColumnTypeId column property, or "" when absent."""
    props = column.Properties
    try:
        if not props.PropertyExists(_maps_TYPE_PROP):
            return ""
        value = props.GetProperty(_maps_TYPE_PROP)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value)


def _maps_tagged_column(table, type_id):
    wanted = type_id.lower()
    for column in table.Columns:
        if _maps_column_type_id(column).lower() == wanted:
            return column
    return None


def _maps_named_column(table, names, numeric):
    for column in table.Columns:
        if column.Name.lower() in names and (not numeric or column.DataType.IsNumeric):
            return column
    return None


# ---- coloring, marking, data limits, settings -------------------------------------------------
def _maps_coloring_for(vspec, lspec):
    """The coloring that applies to this data layer, or None.

    The visual-level `coloring` (or a layer-level `coloring`, when the spec gives one) applies to
    every data layer with a colorBy; a fixed color applies to every data layer.
    """
    cspec = lspec.get("coloring") or vspec.get("coloring")
    if not cspec:
        return None
    if lspec.get("colorBy") or _maps_is_fixed(cspec):
        return cspec
    return None


def _maps_apply_coloring(info, lspec, cspec):
    """apply_coloring (65_coloring.py) on the layer visualization, which has a ColorAxis and a
    Data.DataTableReference like a chart: category keys and literals get the layer table's types,
    and the report target is the layer. The colorBy expression is already set (map.colorBy);
    apply_coloring sets it again only when it differs, so the rules are not reset. A fixed color
    on a layer without colorBy colors by (None), "<>", as Analyst does."""
    fn = globals().get("apply_coloring")
    if fn is None:
        raise Exception("apply_coloring (65_coloring.py) is not part of this builder")
    # the exact text map.colorBy set, so apply_coloring finds it unchanged and keeps the rules
    color_by = _maps_color_text(lspec["colorBy"]) if lspec.get("colorBy") else None
    if color_by is None and _maps_is_fixed(cspec):
        color_by = "<>"
    fn(info["viz"], {"id": info["target"], "colorBy": color_by, "coloring": cspec})
    return "applied"


def _maps_set_marking(info, vspec):
    """The visual's marking on every data layer (GUI-built maps mark on each layer)."""
    data = info["viz"].Data
    if "marking" in vspec:
        name = vspec.get("marking")
        data.MarkingReference = B.marking(name) if name else None   # None = cannot be marked
        return name or "(cannot be marked)"
    data.MarkingReference = B.doc.Data.Markings.DefaultMarkingReference
    return "(default marking)"


def _maps_set_limits(info, vspec, table_name):
    """useFiltering on every data layer; limitByMarkings, emptyMarkingBehavior and limitExpression
    on the data layers of the visual's table only (they are written against that table)."""
    data = info["viz"].Data
    done = []
    if vspec.get("useFiltering") is False:
        data.UseActiveFiltering = False
        done.append("filtering off")
    limits = vspec.get("limitByMarkings") or []
    expression = vspec.get("limitExpression")
    if (limits or expression) and info["tableName"] != table_name:
        done.append("no limits (they are written against " + (table_name or "(none)") + ")")
        return ", ".join(done)
    for name in limits:
        marking = B.marking(name)
        if not data.Filterings.Contains(marking):
            data.Filterings.Add(marking)
    if limits:
        data.LimitingMarkingsEmptyBehavior = enum_value(
            LimitingMarkingsEmptyBehavior, vspec.get("emptyMarkingBehavior") or "ShowAll")
        done.append("limited by " + ", ".join([str(x) for x in limits]))
    if expression:
        # [$Name] translated exactly as vis_common translates limitExpression on other visuals
        data.WhereClauseExpression = _maps_expr(expression)
        done.append("limit expression")
    return ", ".join(done) or "defaults"


def _maps_layer_settings(info, settings):
    """Layer `settings`: paths relative to the layer visualization (data layers), except paths
    whose first member exists only on the layer (Enabled, IncludeInAutoZoom, Projection,
    VisibleZoomLevelRange, ...) and Title, which go to the MapChartLayer. Tile layers: the layer."""
    viz = info["viz"]
    if viz is None:
        apply_settings(info["layer"], settings)
        return "layer"
    on_viz = {}
    on_layer = {}
    for path in settings:
        head = path.split(".")[0]
        if head != "Title" and hasattr(viz, head):
            on_viz[path] = settings[path]
        else:
            on_layer[path] = settings[path]
    apply_settings(viz, on_viz)
    apply_settings(info["layer"], on_layer)
    return str(len(on_viz)) + " on the visualization, " + str(len(on_layer)) + " on the layer"


# ---- map level ----------------------------------------------------------------------------------
def _maps_set_interactive(content, built):
    """Top-most enabled data layer reacts to marking and hover: the layer drawn on top is the one
    users click, and it is Spotfire's own choice when the interactive layer goes away (IL
    MapChart.HandleInteractiveLayer: last enabled data layer). The API default is the first enabled
    data layer added."""
    chosen = None
    for info in built:
        if info["kind"] != "tile" and info["layer"].Enabled:
            chosen = info
    if chosen is None:
        return "none"
    content.InteractiveLayerReference = chosen["layer"]
    return str(chosen["layer"].Title)


def _maps_set_trellis(content, built, table_name):
    """Trellis layer = first enabled data layer on the visual's table (else the first data layer on
    it, else the first data layer: Spotfire's own add-time choice). It controls the map's trellis
    and every GUI-built map keeps the map's own Data on its table, so vis_common gets that table.
    Returns {"title", "table"} or None (no data layer)."""
    data = [info for info in built if info["kind"] != "tile"]
    if not data:
        return None
    on_table = [info for info in data if info["tableName"] == table_name]
    enabled = [info for info in on_table if info["layer"].Enabled]
    chosen = (enabled or on_table or data)[0]
    content.TrellisLayerReference = chosen["layer"]
    return {"title": str(chosen["layer"].Title), "table": chosen["tableName"]}


def _maps_set_zoom(content, vspec):
    """AutoZoom True clears any stored ViewExtent and follows the enabled layers whose
    IncludeInAutoZoom is True (data layers yes, tile layers no). Set before vis_common, so a
    postScript can still switch it off and store a fixed ViewExtent."""
    auto = vspec.get("autoZoom")
    if auto is None:
        auto = True
    # Not yet tested: the initial view of an AutoZoom False map with no ViewExtent.
    content.AutoZoom = bool(auto)
    return "on" if auto else "off"


def _maps_common(visual, content, vspec, table_name, map_table):
    """vis_common (60_charts.py) on the map, called through this wrapper so a missing vis_common
    fails this step, not the map. Data limits are reset to their defaults (they are on the
    layers), coloring and reference layers are per layer or not applicable, and the map's own
    table is the trellis layer's when no data layer uses the visual's table."""
    common = dict(vspec)
    for key in _maps_LAYER_LIMITS:
        value = _maps_LAYER_LIMITS[key]
        common[key] = list(value) if isinstance(value, list) else value
    common["coloring"] = None
    common["referenceLayers"] = []
    common["fittingModels"] = []
    if map_table and map_table != table_name:
        common["table"] = map_table
    return vis_common(visual, content, common)


def _maps_check_layers(vspec, layer_specs, built, table_name):
    vid = vspec["id"]
    seen_data = False
    has_tile = False
    colored = False
    on_table = False
    titles = []
    for info in built:
        if info["title"] in titles:
            B.warn(vid + ": several layers are titled '" + info["title"] + "'; give each layer "
                   "its own title")
        titles.append(info["title"])
        if info["kind"] == "tile":
            has_tile = True
            if seen_data:
                B.warn(vid + ": tile layer '" + info["title"] + "' comes after a data layer and "
                       "covers it (layers are listed back to front)")
        else:
            seen_data = True
            on_table = on_table or info["tableName"] == table_name
    for lspec in layer_specs:
        if not isinstance(lspec, dict) or str(lspec.get("kind") or "").strip() == "tile":
            continue
        if _maps_coloring_for(vspec, lspec):
            colored = True
        elif lspec.get("coloring"):
            B.warn(vid + ": layer '" + _maps_title(lspec, str(lspec.get("table") or table_name))
                   + "' has a coloring but no colorBy, so it is not applied (give the layer a "
                   "colorBy, or use fixed)")
    if seen_data and not has_tile:
        B.warn(vid + ": no tile layer, so the map has no background")
    if vspec.get("coloring") and not colored:
        B.warn(vid + ": coloring is set but no data layer has a colorBy")
    if seen_data and not on_table:
        text = (vid + ": no data layer uses the visual's table " + (table_name or "(none)")
                + "; the map's own data table follows the trellis layer instead")
        if vspec.get("limitByMarkings") or vspec.get("limitExpression"):
            text += ", and limitByMarkings/limitExpression are not applied"
        B.warn(text)
    for key in sorted(_maps_NOT_ON_MAP.keys()):
        if vspec.get(key):
            B.warn(vid + ": '" + key + "' does not apply to the map itself, ignored ("
                   + _maps_NOT_ON_MAP[key] + ")")


def _maps_record(vid, content, built):
    """B.created["maps"][vid]: what was built, read back after vis_common (JSON-safe).
    Layer position 0 = back."""
    layers = []
    for info in built:
        layer = info["layer"]
        row = {"kind": info["kind"], "title": str(layer.Title), "table": info["tableName"],
               "position": content.Layers.IndexOf(layer), "enabled": bool(layer.Enabled)}
        prepared = info.get("geometry")
        if prepared:
            row["geometry"] = prepared["column"]
            row["geometryTaggedByBuilder"] = prepared["tagged"]
        layers.append(row)
    table = content.Data.DataTableReference
    entry = {"layers": layers, "autoZoom": bool(content.AutoZoom),
             "interactiveLayer": _maps_layer_title(content.InteractiveLayerReference),
             "trellisLayer": _maps_layer_title(content.TrellisLayerReference),
             "table": None if table is None else str(table.Name)}
    B.created.setdefault("maps", {})[vid] = entry
    return str(len(layers)) + " layer(s)"


def _maps_layer_title(layer):
    if layer is None:
        return None
    return str(layer.Title)
