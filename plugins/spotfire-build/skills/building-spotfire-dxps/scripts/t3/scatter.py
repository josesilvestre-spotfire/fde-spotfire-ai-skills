"""spec scatterPlot -> engine kind "scatter" (engine/builders/scatter.py, _chart.py, _markers.py).

x, y, colorBy, coloring, xScale / yScale (min, max, log y), limitExpression, referenceLayers and
fittingModels read like line and bar charts (scripts/t3/_charts.py), plus the marker keys: lineBy and
shapeBy are categorical (a list nests, a plain column becomes <[Col]>), sizeBy and labelBy are
expressions (a bare column name of the table is escaped), labels (true / false / "all" / "marked" /
"none" -> All / None / Marked), markerSize (% of the plot, 0-100) and shape (a MarkerType member name,
standard engine only). trellis and yScale.individualScaling read like line and bar charts (feature
trellis).
"""
from ._charts import CHART_HANDLED, chart_body, curves, refs
from ._common import blank

KIND = "scatter"
SPEC_TYPES = ("scatterPlot",)
STYLE_KEYS = (("yFormat", "format", "standard"), ("axisFont", "size", "quick"),
              ("axisTitleFont", "size", "quick"), ("legendFont", "size", "quick"))
HANDLED = CHART_HANDLED + ("sizeBy", "shapeBy", "shape", "labelBy", "labels", "markerSize", "lineBy")
LABELS = {"all": "All", "marked": "Marked", "none": "None"}


def labels_value(value, path, ctx):
    if isinstance(value, bool):
        return "All" if value else "None"
    name = LABELS.get(str(value).strip().lower())
    if name is None:
        ctx.unsupported(path, "labels %r" % (value,))
    return name


def marker_keys(spec, table, path, ctx, out):
    """The keys of engine/builders/_markers.py (scatter visuals and map marker layers)."""
    if not blank(spec.get("sizeBy")):
        size = ctx.measures(spec["sizeBy"], table)
        out["sizeBy"] = ", ".join(size) if isinstance(size, list) else size
    if not blank(spec.get("shapeBy")):
        out["shapeBy"] = ctx.cat(spec["shapeBy"], table)
    if spec.get("shape"):
        out["shape"] = str(spec["shape"])
    if not blank(spec.get("labelBy")):
        out["labelBy"] = ctx.measures(spec["labelBy"], table)
    if spec.get("labels") is not None:
        name = labels_value(spec["labels"], path + ".labels", ctx)
        if name and not (name == "All" and "labelBy" in out):
            out["labels"] = name
    if spec.get("markerSize") is not None:
        out["markerSize"] = float(spec["markerSize"])
    if not blank(spec.get("lineBy")):
        out["lineBy"] = ctx.cat(spec["lineBy"], table)
    return out


def convert(v, rv, path, ctx):
    out = chart_body(v, path, ctx)
    marker_keys(v, out["table"], path, ctx, out)
    fits = curves(v, path, ctx)
    if fits:
        out["curves"] = fits
    lines = refs(v, path, ctx)
    if lines:
        out["refs"] = lines
    return out
