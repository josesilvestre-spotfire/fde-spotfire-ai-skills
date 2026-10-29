# Standard engine, kind "kpi": KPI chart, one tile per KPI.
# APP keys: table, kpis [[title, expression, format or None(, coloring)],
# ...] (the coloring: feature kpiColoring, features/coloring.py);
# style keys (STYLE visual "kpi" defaults): baseFont, minTilesPerRow,
# minVisibleTiles, emptyText, tile. Converter: scripts/t3/kpi.py.
# @api KpiChart.Data; KpiChart.KpiCollection; KpiCollection.Clear
# @api KpiCollection.AddNew; KpiContent.Title; KpiContent.Visualization
# @api KpiVisualization.Data; KpiVisualization.YAxis; KpiVisualization.XAxis
# @api KpiVisualization.TileAxis; KpiVisualization.ShowSparkline
# @api KpiChart.Legend; VisualTypeIdentifiers.KpiChart
# @set VisualizationData.DataTableReference; KpiContent.Title
# @set KpiVisualization.ShowSparkline
from System import Int32
from Spotfire.Dxp.Application.Visuals import KpiChart

# ------------------------------------------------------------ KPI chart
def build_kpi(v, vs):
    vid = vs["id"]
    kc = v.As[KpiChart]()
    kc.Data.DataTableReference = T[vs["table"]]
    kc.KpiCollection.Clear()
    for item in vs["kpis"]:
        ok(vid + ": KPI " + item[0], add_kpi, kc, vs, item)
    ok(vid + ": legend", legend, kc, vs)
    # @tier quick
    if opt(vs, "baseFont"):
        ok(vid + ": base font", kpi_font, kc, opt(vs, "baseFont"))
    # @end
    # @tier standard
    if opt(vs, "minTilesPerRow"):
        ok(vid + ": tiles", kpi_tiles, kc, opt(vs, "minTilesPerRow"),
           opt(vs, "minVisibleTiles", opt(vs, "minTilesPerRow")))
    # @end


def add_kpi(kc, vs, item):
    # @feature !kpiColoring
    title, expression, fmt_name = item
    # @endfeature
    # @feature kpiColoring
    title, expression, fmt_name = item[0], item[1], item[2]
    # @endfeature
    content = kc.KpiCollection.AddNew()
    content.Title = title
    kpi = content.Visualization
    kpi.Data.DataTableReference = T[vs["table"]]
    kpi.YAxis.Expression = expression
    kpi.XAxis.Expression = "<>"
    kpi.TileAxis.Expression = "<>"
    kpi.ShowSparkline = False
    # @tier standard
    name = vs["id"] + ": KPI " + title
    if fmt_name:
        ok(name + " format", kpi_format, kpi, fmt_name)
    if opt(vs, "emptyText") is not None:
        ok(name + " empty text", kpi_empty, kpi, opt(vs, "emptyText"))
    if opt(vs, "tile"):
        ok(name + " tile color", kpi_tile, kpi, opt(vs, "tile"))
    # @end
    # @feature kpiColoring
    if len(item) > 3:
        label = vs["id"] + ": KPI " + title + " coloring"
        ok(label, kpi_coloring, label, kpi, item[3])
    # @endfeature


# @tier standard
# @api KpiYAxis.Formatting; Formatting.RealFormatter
# @api KpiVisualization.EmptyTileText; KpiVisualization.ColorAxis
# @api ColorAxis.Expression; ColorAxis.Coloring; Coloring.DefaultColor
# @set Formatting.RealFormatter; KpiVisualization.EmptyTileText
# @set ColorAxis.Expression; Coloring.DefaultColor
def kpi_format(kpi, fmt_name):
    kpi.YAxis.Formatting.RealFormatter = formatter(fmt_name)


def kpi_empty(kpi, text):
    kpi.EmptyTileText = text


def kpi_tile(kpi, color):
    kpi.ColorAxis.Expression = "THEN [Y.FinalValue]"
    kpi.ColorAxis.Coloring.Clear()
    kpi.ColorAxis.Coloring.DefaultColor = rgb(color)
# @end


# @tier quick
# @api KpiChart.BaseFontMetadata
# @set KpiChart.BaseFontMetadata
def kpi_font(kc, size):
    kc.BaseFontMetadata = font(size)
# @end


# @tier standard
# @api KpiChart.MinTilesPerRow; KpiChart.MinVisibleTiles
# @set KpiChart.MinTilesPerRow; KpiChart.MinVisibleTiles
def kpi_tiles(kc, per_row, visible):
    kc.MinTilesPerRow = Int32(per_row)
    kc.MinVisibleTiles = Int32(visible)
# @end


BUILDERS["kpi"] = build_kpi
TYPE_IDS["kpi"] = "KpiChart"
