# Standard engine, kind "bar": bar chart.
# APP keys: table, x, y, where, color or colorBy + categories, stack
# (true = stacked, "percent", "sideBySide"), horizontal (true), sort
# ("ascending" | "descending" by value), yMin, yLog, refs; style keys
# (STYLE visual "bar" defaults): legendFont, axisFont, axisTitleFont,
# yFormat. Converter: scripts/t3/bar.py.
# @uses _chart
# @api BarChart.Data; BarChart.XAxis; BarChart.YAxis; ScaleAxis.Expression
# @api BarChart.StackMode; StackMode.Stack; StackMode.Stack100Percent
# @api StackMode.None; VisualTypeIdentifiers.BarChart
# @set VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference
# @set VisualizationData.WhereClauseExpression; ScaleAxis.Expression
# @set BarChart.StackMode
from Spotfire.Dxp.Application.Visuals import BarChart, StackMode
from Spotfire.Dxp.Application.Visuals import BarChartOrientation

# ------------------------------------------------------------ bar chart
def build_bar(v, vs):
    bc = v.As[BarChart]()
    bc.Data.DataTableReference = T[vs["table"]]
    bc.Data.MarkingReference = MARK
    bc.XAxis.Expression = vs["x"]
    bc.YAxis.Expression = measures(vs["y"])
    if vs.get("where"):
        bc.Data.WhereClauseExpression = vs["where"]
    chart_style(bc, vs)
    if vs.get("stack"):
        ok(vs["id"] + ": stack", stack, bc, vs["stack"])
    # @feature barLayout
    if vs.get("horizontal") or vs.get("sort"):
        ok(vs["id"] + ": orientation and sort", bar_layout, bc, vs)
    # @endfeature


def stack(chart, mode):
    """true = stacked bars, "percent" = 100% stacked, "sideBySide"
    = bars next to each other (StackMode member None)."""
    names = {"percent": "Stack100Percent", "sideBySide": "None"}
    chart.StackMode = getattr(StackMode, names.get(mode, "Stack"))


# @feature barLayout
# @api BarChart.Orientation; BarChartOrientation.Horizontal
# @api BarChart.SortedBars; ScaleAxis.Reversed
# @set BarChart.Orientation; BarChart.SortedBars; ScaleAxis.Reversed
def bar_layout(chart, vs):
    """Horizontal bars get XAxis.Reversed like every GUI-built one (first
    category on top); sorted bars put the largest first, so ascending
    reverses that order (lib/60_charts.py _charts_set_bar_order)."""
    if vs.get("horizontal"):
        chart.Orientation = BarChartOrientation.Horizontal
    if vs.get("sort"):
        chart.SortedBars = True
    chart.XAxis.Reversed = (bool(vs.get("horizontal"))
                            != (vs.get("sort") == "ascending"))
# @endfeature


BUILDERS["bar"] = build_bar
TYPE_IDS["bar"] = "BarChart"
