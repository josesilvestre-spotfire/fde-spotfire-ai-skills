# Standard engine, kind "line": line chart.
# APP keys: table, x, y (expression or list), where, color (one color) or
# colorBy + categories {category: color}, yMin, refs [{label, axis
# "X"|"Y", value, color, dash "solid"|"dash"|"dot", width, labelFont}];
# style keys (STYLE visual "line" defaults): legendFont, axisFont,
# axisTitleFont, yFormat, lineWidth. Converter: scripts/t3/line.py.
# @uses _chart
# @api LineChart.Data; LineChart.XAxis; LineChart.YAxis; ScaleAxis.Expression
# @api VisualTypeIdentifiers.LineChart
# @set VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference
# @set VisualizationData.WhereClauseExpression; ScaleAxis.Expression
from System import Int32
from Spotfire.Dxp.Application.Visuals import LineChart

# ----------------------------------------------------------- line chart
def build_line(v, vs):
    lc = v.As[LineChart]()
    lc.Data.DataTableReference = T[vs["table"]]
    lc.Data.MarkingReference = MARK
    lc.XAxis.Expression = vs["x"]
    lc.YAxis.Expression = measures(vs["y"])
    if vs.get("where"):
        lc.Data.WhereClauseExpression = vs["where"]
    chart_style(lc, vs)
    # @tier standard
    if opt(vs, "lineWidth"):
        ok(vs["id"] + ": line width", line_width, lc,
           opt(vs, "lineWidth"))
    # @end


# @tier standard
# @api LineChart.LineWidth
# @set LineChart.LineWidth
def line_width(chart, width):
    chart.LineWidth = Int32(width)
# @end


BUILDERS["line"] = build_line
TYPE_IDS["line"] = "LineChart"
