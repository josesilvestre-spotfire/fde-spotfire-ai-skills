# Standard engine, shared part "_chart": what the line, bar and
# scatter builders share (data binding helpers, colors, y axis, fonts,
# legend and reference lines; with features: a full coloring on the color
# axis, x and y axis ranges, lines and curves, the trellis and an own y
# scale per panel: APP "trellis", "yEach"). Included
# once when an app has a line, bar or scatter chart.
# @api LineChart.ColorAxis; BarChart.ColorAxis; ColorAxis.Expression
# @api ColorAxis.Coloring; Coloring.Clear; Coloring.DefaultColor
# @api Coloring.SetColorForCategory(CategoryKey, Color); CategoryKey.ctor(Object[])
# @api LineChart.XAxis; LineChart.YAxis; BarChart.XAxis; BarChart.YAxis
# @api ScaleAxis.Range; AxisRange.ctor(Object, Object); ScaleAxis.Scale
# @api LineChart.Legend; BarChart.Legend; LineChart.Layers; BarChart.Layers
# @api LayerCollection.AddNewReferenceLayer; ReferenceLayer.Name
# @api ReferenceLayer.ValueAxis; ReferenceLayer.Expression; ReferenceLayer.Line
# @api ReferenceLayer.Label; Line.Enabled; Line.Stroke; Stroke.WithColor
# @api Stroke.WithStyle; Stroke.WithWidth; ColorInfo.ctor(Int32)
# @api Label.Enabled; Label.Style
# @api LabelStyle.WithShowDisplayName; LabelStyle.WithShowValue
# @api ValueAxis.X; ValueAxis.Y; LineStyle.Single; LineStyle.Dash; LineStyle.Dot
# @set ColorAxis.Expression; Coloring.DefaultColor; ScaleAxis.Range
# @set ReferenceLayer.Name
# @set ReferenceLayer.ValueAxis; ReferenceLayer.Expression; Line.Enabled
# @set Line.Stroke; Label.Enabled; Label.Style
from System import Single
from System.Drawing import Color
from Spotfire.Dxp.Application.Visuals import CategoryKey
from Spotfire.Dxp.Application.Visuals import AxisRange, LineStyle
from Spotfire.Dxp.Application.Visuals import AxisTransformType
from Spotfire.Dxp.Application.Visuals import TrellisMode
from Spotfire.Dxp.Application.Visuals import IndividualScalingMode
from Spotfire.Dxp.Application.Visuals.ReferenceElements import ValueAxis
from Spotfire.Dxp.Framework.Styles import ColorInfo

# ----------------------------------------------------------- line, bar
def measures(y):
    if isinstance(y, (list, tuple)):
        return ", ".join(y)
    return y


def chart_style(chart, vs):
    vid = vs["id"]
    if vs.get("color") or vs.get("colorBy"):
        ok(vid + ": colors", colors, chart, vs)
    # @feature coloring
    if vs.get("coloring"):
        ok(vid + ": coloring", axis_coloring, vid + ": coloring",
           chart.ColorAxis, vs["coloring"])
    # @endfeature
    if vs.get("yMin") is not None:
        ok(vid + ": y range", y_range, chart, vs["yMin"])
    # @feature range
    if [k for k in ("yMax", "xMin", "xMax") if k in vs]:
        ok(vid + ": axis ranges", axis_ranges, chart, vs)
    # @endfeature
    # @feature log
    if vs.get("yLog"):
        ok(vid + ": log scale", y_log, chart)
    # @endfeature
    # @feature trellis
    if vs.get("trellis"):
        ok(vid + ": trellis", trellis, chart, vs["trellis"])
    if vs.get("yEach"):
        ok(vid + ": y scale per panel", y_each, chart,
           bool(vs.get("trellis")))
    # @endfeature
    # @tier standard
    if opt(vs, "yFormat"):
        ok(vid + ": y format", y_format, chart, opt(vs, "yFormat"))
    # @end
    # @tier quick
    ok(vid + ": axis fonts", axis_fonts, chart, vs)
    # @end
    ok(vid + ": legend", legend, chart, vs)
    # @tier quick
    ok(vid + ": legend font", legend_font, chart, vs)
    # @end
    for r in vs.get("refs", []):
        ok(vid + ": line " + r["label"], ref_line, chart, r)
    # @feature fitting
    for c in vs.get("curves", []):
        ok(vid + ": curve " + (c.get("label") or c["kind"]), add_curve,
           chart, c)
    # @endfeature


def colors(chart, vs):
    if vs.get("color"):
        chart.ColorAxis.Expression = "<>"
        chart.ColorAxis.Coloring.Clear()
        chart.ColorAxis.Coloring.DefaultColor = rgb(vs["color"])
        return
    chart.ColorAxis.Expression = vs["colorBy"]
    coloring = chart.ColorAxis.Coloring
    cats = vs.get("categories", {})
    for key in sorted(cats):
        coloring.SetColorForCategory(CategoryKey(key), rgb(cats[key]))


def y_range(chart, low):
    chart.YAxis.Range = AxisRange(float(low), None)


# @feature range
def bound(value):
    return None if value is None else float(value)


def axis_ranges(chart, vs):
    """yMax (with yMin), xMin and xMax; None keeps that end automatic."""
    if "yMax" in vs:
        chart.YAxis.Range = AxisRange(bound(vs.get("yMin")),
                                      bound(vs["yMax"]))
    if "xMin" in vs or "xMax" in vs:
        chart.XAxis.Range = AxisRange(bound(vs.get("xMin")),
                                      bound(vs.get("xMax")))
# @endfeature


# @feature log
# @api ScaleAxis.TransformType; AxisTransformType.Log10
# @set ScaleAxis.TransformType
def y_log(chart):
    chart.YAxis.TransformType = AxisTransformType.Log10
# @endfeature


# @feature trellis
# @note lib/60_charts.py _charts_set_trellis / _charts_set_individual;
# @note ManualRowCount / ManualColumnCount count only in Panels mode.
# @api LineChart.Trellis; BarChart.Trellis; ScatterPlot.Trellis
# @api Trellis.TrellisMode; Trellis.PanelAxis; Trellis.RowAxis
# @api Trellis.ColumnAxis; TrellisAxis.Expression; Trellis.ManualLayout
# @api Trellis.ManualRowCount; Trellis.ManualColumnCount
# @api TrellisMode.Panels; TrellisMode.RowsColumns
# @api ScaleAxis.IndividualScaling; ScaleAxis.IndividualScalingMode
# @api IndividualScalingMode.Trellis; IndividualScalingMode.Color
# @set Trellis.TrellisMode; TrellisAxis.Expression; Trellis.ManualLayout
# @set Trellis.ManualRowCount; Trellis.ManualColumnCount
# @set ScaleAxis.IndividualScaling; ScaleAxis.IndividualScalingMode
def trellis(chart, t):
    """Small multiples: panels by one categorical expression (with an
    optional fixed grid), or rows and columns by categories."""
    tr = chart.Trellis
    if t.get("panel"):
        tr.TrellisMode = TrellisMode.Panels
        tr.PanelAxis.Expression = t["panel"]
        if t.get("rows"):
            tr.ManualRowCount = int(t["rows"])
        if t.get("columns"):
            tr.ManualColumnCount = int(t["columns"])
        if t.get("rows") or t.get("columns"):
            tr.ManualLayout = True
        return
    tr.TrellisMode = TrellisMode.RowsColumns
    if t.get("rowsBy"):
        tr.RowAxis.Expression = t["rowsBy"]
    if t.get("columnsBy"):
        tr.ColumnAxis.Expression = t["columnsBy"]


def y_each(chart, trellised):
    """Own y scale per trellis panel (per color without a trellis)."""
    chart.YAxis.IndividualScaling = True
    chart.YAxis.IndividualScalingMode = (
        IndividualScalingMode.Trellis if trellised
        else IndividualScalingMode.Color)
# @endfeature


# @tier standard
# @api ScaleAxis.Scale; Scale.Formatting; Formatting.RealFormatter
# @set Formatting.RealFormatter
def y_format(chart, name):
    chart.YAxis.Scale.Formatting.RealFormatter = formatter(name)
# @end


# @tier quick
# @api Scale.FontMetadata; ScaleAxis.TitleFontMetadata; Legend.FontMetadata
# @set Scale.FontMetadata; ScaleAxis.TitleFontMetadata; Legend.FontMetadata
def axis_fonts(chart, vs):
    for axis in (chart.XAxis, chart.YAxis):
        axis.Scale.FontMetadata = font(opt(vs, "axisFont"))
        axis.TitleFontMetadata = font(opt(vs, "axisTitleFont"))


def legend_font(content, vs):
    content.Legend.FontMetadata = font(opt(vs, "legendFont"))
# @end


def ref_line(chart, r):
    defaults = STYLE["visual"]["ref"]
    dashes = {"solid": LineStyle.Single, "dash": LineStyle.Dash,
              "dot": LineStyle.Dot}
    layer = chart.Layers.AddNewReferenceLayer()
    layer.Name = r["label"]
    layer.ValueAxis = ValueAxis.X if r["axis"] == "X" else ValueAxis.Y
    layer.Expression = r["value"]
    layer.Line.Enabled = True
    c = rgb(r.get("color", STYLE["text"]))
    argb = Color.FromArgb(255, c.R, c.G, c.B).ToArgb()
    stroke = layer.Line.Stroke.WithColor(ColorInfo(argb))
    stroke = stroke.WithStyle(dashes[r.get("dash", "solid")])
    stroke = stroke.WithWidth(Single(r.get("width", defaults["width"])))
    layer.Line.Stroke = stroke
    layer.Label.Enabled = True
    style_ = layer.Label.Style.WithShowDisplayName(True)
    layer.Label.Style = style_.WithShowValue(False)
    # @tier quick
    ok("line " + r["label"] + ": label font", label_font, layer,
       r.get("labelFont", defaults["labelFont"]))
    # @end


# @tier quick
# @api Label.LabelFont
# @set Label.LabelFont
def label_font(layer, size):
    layer.Label.LabelFont = font(size)
# @end


# @feature fitting
# @api LineChart.FittingModels; BarChart.FittingModels
# @api ScatterPlot.FittingModels; FittingModelCollection.AddStraightLineFit
# @api FittingModelCollection.AddCurve(String); StraightLineFittingModel.Line
# @api ReferenceCurveFittingModel.Curve; ReferenceCurve.Visible
# @api ReferenceCurve.Color; ReferenceCurve.CustomDisplayName
# @api ReferenceCurve.LineStyle; ReferenceCurve.Width; ReferenceCurve.Details
# @api ReferenceDetailItemCollection.GetEnumerator; ReferenceDetailItem.Name
# @api ReferenceDetailItem.ShowInLabel; LineStyle.Double
# @set ReferenceCurve.Visible; ReferenceCurve.Color
# @set ReferenceCurve.CustomDisplayName; ReferenceCurve.LineStyle
# @set ReferenceCurve.Width; ReferenceDetailItem.ShowInLabel
def add_curve(chart, c):
    """Lines & Curves: a straight-line fit or a curve whose expression
    is in x (y = x: "x"); alt is the ${Name} form of a curve with a
    document property, tried when Spotfire rejects the first one."""
    models = chart.FittingModels
    if c["kind"] == "straightLine":
        curve = models.AddStraightLineFit().Line
    else:
        try:
            model = models.AddCurve(c["expression"])
        except Exception:
            if not c.get("alt"):
                raise
            model = models.AddCurve(c["alt"])
        curve = model.Curve
    curve.Visible = True
    if c.get("color"):
        curve.Color = rgb(c["color"])
    if c.get("dash"):
        dashes = {"solid": LineStyle.Single, "dash": LineStyle.Dash,
                  "dot": LineStyle.Dot, "double": LineStyle.Double}
        curve.LineStyle = dashes[c["dash"]]
    if c.get("width"):
        curve.Width = int(c["width"])
    if c.get("label"):
        curve.CustomDisplayName = c["label"]
        for detail in curve.Details:
            if detail.Name == "Name":
                detail.ShowInLabel = True
# @endfeature
