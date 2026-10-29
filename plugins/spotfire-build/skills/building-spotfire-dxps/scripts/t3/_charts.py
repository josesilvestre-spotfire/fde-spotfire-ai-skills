"""Shared spec -> APP conversion of line, bar and scatter charts (engine/builders/_chart.py on the engine
side).

Reads the spec like lib/60_charts.py and lib/65_coloring.py do (x, y, colorBy, coloring, xScale, yScale,
limitExpression, referenceLayers, fittingModels) and writes the base keys: x, y, where, color | colorBy +
categories, yMin, yLog, refs; with the features of engine/builders/_chart.py also coloring (a coloring
the base chart colors cannot express: gradient, rules, default, "(Empty)", settings; feature coloring),
yMax, xMin, xMax (feature range), curves (fittingModels; feature fitting), trellis (panel | rowsBy /
columnsBy, rows, columns) and yEach (yScale.individualScaling; feature trellis).
A chart whose spec has none of these gets exactly the APP keys it got before.
"""
import re

from . import _coloring
from ._common import NAMES_AXIS, PROP_RE, blank

CHART_HANDLED = ("x", "y", "colorBy", "coloring", "xScale", "yScale", "limitExpression", "referenceLayers",
                 "fittingModels", "trellis")
SCALE_DEFAULTS = {"min": None, "max": None, "log": False, "individualScaling": False, "title": None}
AXIS_X_RE = re.compile(r"\[Axis\.X\]", re.IGNORECASE)
DASHES = ("solid", "dash", "dot", "double")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def chart_body(v, path, ctx, extra=None, categorical_x=False):
    """Ordered APP keys of a line, bar or scatter chart. extra: kind-specific keys to insert after the
    colors (the bar chart's stack), as [(key, value)]. categorical_x: a bare column of a data-function
    table on x is a category (bar charts)."""
    table = ctx.table(v)
    out = {"table": table}
    if v.get("x") is None:
        ctx.unsupported(path, "a chart without 'x'")
    else:
        out["x"] = ctx.axis(v["x"], table, unknown_categorical=categorical_x)
    y = v.get("y")
    if blank(y):
        ctx.unsupported(path, "a chart without 'y'")
    else:
        out["y"] = ctx.measures(y, table)
    if v.get("limitExpression"):
        out["where"] = ctx.expr(v["limitExpression"])
    coloring = v.get("coloring") if isinstance(v.get("coloring"), dict) else {}
    if v.get("coloring") is not None and not isinstance(v.get("coloring"), dict):
        ctx.unsupported(path + ".coloring", "a list of colorings on a chart")
    full = coloring if coloring and not _coloring.simple(coloring) else None    # feature coloring
    color_by = v.get("colorBy")
    several = isinstance(y, (list, tuple)) and len([m for m in y if not blank(m)]) > 1
    if color_by is None and several:
        color_by = NAMES_AXIS                     # lib/60_charts: one color per measure
    if coloring.get("fixed") and full is None:
        out["color"] = ctx.color(coloring["fixed"], path + ".coloring.fixed")
    elif color_by is not None:
        # a gradient or rules color a continuous color-by: only a categorical coloring makes a bare
        # data-function column a category
        categories = full is None or bool(full.get("categorical"))
        out["colorBy"] = ctx.axis(color_by, table, unknown_categorical=categories)
    elif full is not None and full.get("fixed") is not None and not full.get("rules"):
        out["colorBy"] = "<>"                     # a fixed color is color by (None), as Analyst stores it
    for key, value in extra or []:
        out[key] = value
    cats = coloring.get("categorical")
    if cats and full is None:
        out["categories"] = dict((k, ctx.color(c, path + ".coloring.categorical." + k))
                                 for k, c in cats.items())
    xscale = v.get("xScale") if isinstance(v.get("xScale"), dict) else {}
    for key, value in xscale.items():
        if key == "gridlines" and value is False:
            continue                              # Spotfire's default for the X axis
        if key in ("min", "max") and _number(value):
            continue                              # feature range
        if value != SCALE_DEFAULTS.get(key, object()):
            ctx.unsupported(path + ".xScale." + key, "xScale '%s'" % key)
    scale = v.get("yScale") if isinstance(v.get("yScale"), dict) else {}
    for key, value in scale.items():
        if key == "min" or (key == "log" and isinstance(value, bool)):
            continue
        if key == "max" and _number(value):
            continue                              # feature range
        if key == "gridlines" and value is True:
            continue                              # Spotfire's default for the Y axis
        if key == "individualScaling" and isinstance(value, bool):
            continue                              # feature trellis (yEach)
        if value != SCALE_DEFAULTS.get(key, object()):
            ctx.unsupported(path + ".yScale." + key, "yScale '%s'" % key)
    low = scale.get("min")
    if low is not None:
        if _number(low):
            out["yMin"] = low
        else:
            ctx.unsupported(path + ".yScale.min", "an expression as the y-axis minimum")
    if scale.get("log") is True:
        out["yLog"] = True
    if _number(scale.get("max")):
        out["yMax"] = float(scale["max"])
    for key, name in (("min", "xMin"), ("max", "xMax")):
        if _number(xscale.get(key)):
            out[name] = float(xscale[key])
    t = trellis(v, table, path, ctx)
    if t:
        out["trellis"] = t                        # feature trellis
    if scale.get("individualScaling") is True:
        out["yEach"] = True                       # feature trellis: own y scale per panel
    if full is not None:
        type_name = _coloring.column_type(out.get("colorBy"), table, ctx)
        converted = _coloring.convert(full, path + ".coloring", ctx, type_name)
        if converted:
            out["coloring"] = converted
    return out


def trellis(v, table, path, ctx):
    """trellis -> APP {"panel": <cat>, "rows": n, "columns": n} (Panels; rows and columns fix the grid) or
    {"rowsBy": <cat>, "columnsBy": <cat>} (RowsColumns: the categories decide the grid, so rows and
    columns are left out; dxpgen validate warns). None when the spec has no trellis."""
    spec = v.get("trellis")
    if blank(spec):
        return None
    if not isinstance(spec, dict):
        ctx.unsupported(path + ".trellis", "a trellis that is not an object")
        return None
    if not blank(spec.get("panelBy")):
        out = {"panel": ctx.cat(spec["panelBy"], table)}
        for key in ("rows", "columns"):
            if isinstance(spec.get(key), int) and not isinstance(spec.get(key), bool) and spec[key] > 0:
                out[key] = spec[key]
        return out
    out = {}
    for key in ("rowsBy", "columnsBy"):
        if not blank(spec.get(key)):
            out[key] = ctx.cat(spec[key], table)
    if not out:
        ctx.unsupported(path + ".trellis", "a trellis without panelBy, rowsBy or columnsBy")
        return None
    return out


def refs(v, path, ctx):
    """referenceLayers -> APP refs [{label, axis, value, color, dash, width, labelFont}]."""
    out = []
    for k, layer in enumerate(v.get("referenceLayers") or []):
        lp = "%s.referenceLayers[%d]" % (path, k)
        kind = layer.get("kind")
        if kind not in ("horizontalLine", "verticalLine"):
            ctx.unsupported(lp, "a '%s' reference layer" % kind)
            continue
        if layer.get("table") is not None:
            ctx.unsupported(lp + ".table", "a reference line from another table")
        if not blank(layer.get("settings")):
            ctx.unsupported(lp + ".settings", "reference-layer settings")
        dash = layer.get("dash") or "solid"
        if dash not in ("solid", "dash", "dot"):
            ctx.unsupported(lp + ".dash", "dash '%s'" % dash)
        r = {"label": layer.get("label") or "", "axis": "Y" if kind == "horizontalLine" else "X",
             "value": ctx.expr(layer.get("value"))}
        if layer.get("color"):
            r["color"] = ctx.color(layer["color"], lp + ".color")
        if dash != "solid":
            r["dash"] = dash
        width = layer.get("width")
        if width is not None and width != ctx.default("ref", "width", 1):
            r["width"] = width
        font = layer.get("labelFont")
        if font is not None and ctx.has("quick") and font != ctx.default("ref", "labelFont"):
            r["labelFont"] = font
        out.append(r)
    return out


def curves(v, path, ctx):
    """fittingModels -> APP curves [{kind, expression, alt, color, dash, width, label}] (feature fitting).
    A curve's expression is in x: [Axis.X] -> x, [$Name] -> DocumentProperty("Name"); alt is the ${Name}
    form the engine tries when Spotfire rejects the first one (lib/65_coloring.py)."""
    out = []
    for k, m in enumerate(v.get("fittingModels") or []):
        mp = "%s.fittingModels[%d]" % (path, k)
        if not isinstance(m, dict):
            ctx.unsupported(mp, "a fitting model that is not an object")
            continue
        kind = m.get("kind")
        if kind not in ("straightLine", "curve"):
            ctx.unsupported(mp + ".kind", "fitting model '%s'" % kind)
            continue
        if not blank(m.get("settings")):
            ctx.unsupported(mp + ".settings", "fitting-model settings (use dash, width)")
        c = {"kind": kind}
        if kind == "curve":
            raw = str(m.get("expression") or "").strip()
            c["expression"] = AXIS_X_RE.sub("x", ctx.expr(raw))
            alt = AXIS_X_RE.sub("x", PROP_RE.sub(lambda mm: "${" + mm.group(1) + "}", raw))
            if alt != c["expression"]:
                c["alt"] = alt
        if m.get("color"):
            c["color"] = ctx.color(m["color"], mp + ".color")
        dash = m.get("dash") or "solid"
        if dash not in DASHES:
            ctx.unsupported(mp + ".dash", "dash '%s'" % dash)
        elif dash != "solid":
            c["dash"] = dash
        width = m.get("width")
        if width is not None:
            if _number(width) and 1 <= width <= 10:
                c["width"] = int(width)
            else:
                ctx.unsupported(mp + ".width", "a curve width outside 1..10")
        if m.get("label"):
            c["label"] = str(m["label"])
        out.append(c)
    return out
