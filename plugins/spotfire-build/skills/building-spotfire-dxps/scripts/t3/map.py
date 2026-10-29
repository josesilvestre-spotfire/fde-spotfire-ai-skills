"""spec map -> engine kind "map" (engine/builders/map.py, _markers.py; colorings: _coloring.py).

Reads the spec like lib/75_maps.py: layers back to front; a tile layer (title "Rich reference map" by
default) takes only title and settings; data layers (title = their table by default) get the visual's
marking (a layer "marking" overrides it), and the visual's limitByMarkings / emptyMarkingBehavior /
limitExpression when the layer is on the visual's table (a layer's own limitByMarkings,
emptyMarkingBehavior, limitExpression override them: standard engine); a layer coloring (or the
visual's, when the layer has a colorBy, or always for a fixed color) becomes the layer's APP coloring.
Marker layers: latitude / longitude (absent: the table's XCenter / YCenter or Latitude / Longitude
columns, when its columns are known), sizeBy, lineBy (categorical), labelBy, labels, markerSize,
shape, shapeBy (standard engine: the scatter vocabulary). Feature layers: geometry (a column name ->
APP column; "<...>" -> the geometry-by expression). extent {west, south, east, north} in degrees ->
Web Mercator metres (APP extent; AutoZoom off); interactiveLayer (a data layer title) -> APP
interactive. Layer settings pass through (engine/features/
settings.py routes them to the layer visualization or the layer).
"""
import math

from . import _coloring
from .scatter import marker_keys
from ._common import blank

KIND = "map"
SPEC_TYPES = ("map",)
STYLE_KEYS = ()
HANDLED = ("layers", "autoZoom", "extent", "interactiveLayer", "coloring", "limitExpression")
TILE_TITLE = "Rich reference map"
LON_NAMES = ("longitude", "lon", "long", "lng")
LAT_NAMES = ("latitude", "lat")
R = 20037508.342789244                   # Web Mercator half circumference (m)


def mercator(lon, lat):
    x = lon * R / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * R / math.pi
    return x, y


def find_position(table, ctx):
    """(longitude, latitude) expressions from the table's known columns, or None (lib/75_maps.py
    _maps_find_position, at generation time)."""
    cols = ctx.columns_of(table) or []
    names = dict((c.lower(), c) for c, _ in cols)
    for xs, ys in ((("xcenter",), ("ycenter",)), (LON_NAMES, LAT_NAMES)):
        x = [names[n] for n in xs if n in names]
        y = [names[n] for n in ys if n in names]
        if x and y:
            return "[" + x[0].replace("]", "]]") + "]", "[" + y[0].replace("]", "]]") + "]"
    return None


def convert(v, rv, path, ctx):
    table = ctx.table(v)
    default_marking = ctx.marking_name
    visual_marking = v.get("marking", default_marking)
    visual_coloring = v.get("coloring") if isinstance(v.get("coloring"), dict) else None
    layers = []
    for k, layer in enumerate(v.get("layers") or []):
        lp = "%s.layers[%d]" % (path, k)
        if not isinstance(layer, dict):
            ctx.unsupported(lp, "a map layer that is not an object")
            continue
        kind = layer.get("kind")
        if kind == "tile":
            entry = {"kind": "tile", "title": layer.get("title") or TILE_TITLE}
        elif kind in ("marker", "feature"):
            entry = data_layer(layer, kind, lp, path, ctx, table, visual_marking, default_marking,
                               visual_coloring, v)
        else:
            ctx.unsupported(lp + ".kind", "map layer kind '%s'" % kind)
            continue
        if isinstance(layer.get("settings"), dict) and layer["settings"]:
            entry["settings"] = dict(layer["settings"])
        layers.append(entry)
    out = {"table": table, "layers": layers}
    extent = v.get("extent")
    if isinstance(extent, dict) and extent:
        w, s = mercator(float(extent["west"]), float(extent["south"]))
        e, n = mercator(float(extent["east"]), float(extent["north"]))
        out["extent"] = [round(w, 3), round(s, 3), round(e, 3), round(n, 3)]
    elif v.get("autoZoom") is False:
        out["autoZoom"] = False
    if v.get("interactiveLayer"):
        out["interactive"] = v["interactiveLayer"]           # dxpgen checks that it names a data layer
    return out


def data_layer(layer, kind, lp, path, ctx, table, visual_marking, default_marking, visual_coloring, v):
    ltable = layer.get("table") or table
    entry = {"kind": kind, "title": layer.get("title") or ltable, "table": ltable}
    if kind == "marker":
        lat, lon = layer.get("latitude"), layer.get("longitude")
        if not blank(lat) and not blank(lon):
            entry["x"] = ctx.expr(ctx.column(str(lon).strip(), ltable))
            entry["y"] = ctx.expr(ctx.column(str(lat).strip(), ltable))
        else:
            found = find_position(ltable, ctx)
            if found is None:
                ctx.unsupported(lp, "a marker layer without latitude and longitude (the columns of %s are "
                                "not known before the build)" % ltable)
            else:
                entry["x"], entry["y"] = found
        marker_keys(layer, ltable, lp, ctx, entry)
    else:
        for key in ("sizeBy", "lineBy", "labelBy", "labels", "markerSize", "shape", "shapeBy"):
            if not blank(layer.get(key)):
                ctx.unsupported(lp + "." + key, "'%s' on a feature layer" % key)
        geometry = str(layer.get("geometry") or "").strip()
        if geometry.startswith("<"):
            entry["geometry"] = ctx.expr(geometry)
        elif geometry:
            entry["column"] = geometry[1:-1].replace("]]", "]") if geometry.startswith("[") else geometry
    own = isinstance(layer.get("coloring"), dict)
    cspec = layer["coloring"] if own else visual_coloring
    fixed = isinstance(cspec, dict) and cspec.get("fixed") is not None
    color_by = layer.get("colorBy")
    if not blank(color_by):
        entry["colorBy"] = ctx.cat(color_by, ltable) if isinstance(color_by, (list, tuple)) else             ctx.axis(color_by, ltable)
    elif fixed and not cspec.get("rules"):
        entry["colorBy"] = "<>"                       # a fixed color is color by (None), as Analyst stores it
    if cspec and ("colorBy" in entry or fixed):
        converted = _coloring.convert(cspec, lp + ".coloring" if own else path + ".coloring", ctx,
                                      _coloring.column_type(entry.get("colorBy"), ltable, ctx))
        if converted:
            entry["coloring"] = converted
    marking = layer["marking"] if "marking" in layer else visual_marking
    if marking != default_marking:
        entry["marking"] = marking
    inherit = ltable == table                         # the visual's limits are written against its table
    limits = layer["limitByMarkings"] if "limitByMarkings" in layer else (
        v.get("limitByMarkings") if inherit else None)
    empty = layer["emptyMarkingBehavior"] if "emptyMarkingBehavior" in layer else (
        v.get("emptyMarkingBehavior") if inherit and limits else None)
    if limits:
        entry["limits"] = list(limits)
        entry["empty"] = empty or "ShowAll"           # always with limits (references/engine.md, links)
    elif empty:
        entry["empty"] = empty
    where = layer["limitExpression"] if "limitExpression" in layer else (
        v.get("limitExpression") if inherit else None)
    if where:
        entry["where"] = ctx.expr(where)
    return entry
