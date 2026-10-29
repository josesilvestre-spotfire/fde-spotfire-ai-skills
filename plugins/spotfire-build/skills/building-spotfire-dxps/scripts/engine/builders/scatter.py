# Standard engine, kind "scatter": scatter plot (lib/60_charts.py
# vis_scatter). APP keys: table, x, y (expression or list), where, color
# or colorBy + categories (or coloring: features/coloring.py), yMin,
# yLog, yMax / xMin / xMax (feature range), refs, curves (feature
# fitting: lines and curves such as y = x), and the marker keys of
# _markers.py: sizeBy, shapeBy, shape, labelBy, labels, markerSize,
# lineBy (markers joined per category). Style keys (STYLE visual
# "scatter" defaults): legendFont, axisFont, axisTitleFont, yFormat.
# Converter: scripts/t3/scatter.py.
# @uses _chart _markers
# @api ScatterPlot.Data; ScatterPlot.XAxis; ScatterPlot.YAxis
# @api ScatterPlot.ColorAxis; ScatterPlot.Legend; ScatterPlot.Layers
# @api ScaleAxis.Expression; VisualTypeIdentifiers.ScatterPlot
# @set VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference
# @set VisualizationData.WhereClauseExpression; ScaleAxis.Expression
from Spotfire.Dxp.Application.Visuals import ScatterPlot

# --------------------------------------------------------- scatter plot
def build_scatter(v, vs):
    sp = v.As[ScatterPlot]()
    sp.Data.DataTableReference = T[vs["table"]]
    sp.Data.MarkingReference = MARK
    sp.XAxis.Expression = vs["x"]
    sp.YAxis.Expression = measures(vs["y"])
    if vs.get("where"):
        sp.Data.WhereClauseExpression = vs["where"]
    chart_style(sp, vs)
    marker_style(vs["id"] + ":", sp, vs)


BUILDERS["scatter"] = build_scatter
TYPE_IDS["scatter"] = "ScatterPlot"
