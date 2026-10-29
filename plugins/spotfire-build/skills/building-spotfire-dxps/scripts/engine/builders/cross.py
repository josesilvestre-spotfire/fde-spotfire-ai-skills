# Standard engine, kind "cross": cross table.
# APP keys: table, rows, columns (categorical expressions), measures
# [...], cellColors [[measure display names or None, coloring], ...]
# (feature cellColoring, features/coloring.py: after the red negatives,
# so a default numeric coloring of the spec wins); style keys (STYLE
# visual "cross" defaults): totals, negatives
# (true = every numeric measure), font, headerFont, headerBold,
# cellWidth, rowHeaderWidth. Converter: scripts/t3/cross.py.
# @uses _tabular
# @api CrossTablePlot.Data; CrossTablePlot.MeasureAxis
# @api CrossTablePlot.ColumnAxis; CrossTablePlot.RowAxis
# @api CrossTablePlot.ShowRowGrandTotal; CrossTablePlot.ShowColumnGrandTotal
# @api CrossTablePlot.Legend; VisualTypeIdentifiers.CrossTable
# @set VisualizationData.DataTableReference
# @set CrossTablePlot.ShowRowGrandTotal; CrossTablePlot.ShowColumnGrandTotal
from System import Int32
from Spotfire.Dxp.Application.Visuals import CrossTablePlot

# ---------------------------------------------------------- cross table
def build_cross(v, vs):
    vid = vs["id"]
    ct = v.As[CrossTablePlot]()
    ct.Data.DataTableReference = T[vs["table"]]
    ct.MeasureAxis.Expression = ", ".join(vs["measures"])
    ct.ColumnAxis.Expression = vs["columns"]
    ct.RowAxis.Expression = vs["rows"]
    ct.ShowRowGrandTotal = bool(opt(vs, "totals", False))
    ct.ShowColumnGrandTotal = bool(opt(vs, "totals", False))
    ok(vid + ": legend", legend, ct, vs)
    # @tier quick
    ok(vid + ": fonts", table_fonts, ct, vs)
    # @end
    # @tier standard
    if opt(vs, "cellWidth"):
        ok(vid + ": cell width", cell_width, ct, opt(vs, "cellWidth"))
    if opt(vs, "rowHeaderWidth"):
        ok(vid + ": row header width", row_header_width, ct,
           opt(vs, "rowHeaderWidth"))
    # @end
    # @tier quick
    if opt(vs, "negatives"):
        ok(vid + ": negatives", negatives, ct, None)
    # @end
    # @feature cellColoring
    if vs.get("cellColors"):
        cell_colorings(ct, vs)
    # @endfeature


# @tier standard
# @api CrossTablePlot.CellWidth; CrossTablePlot.RowHeaderWidths
# @set CrossTablePlot.CellWidth
def cell_width(ct, width):
    ct.CellWidth = Int32(width)


def row_header_width(ct, width):
    ct.RowHeaderWidths[0] = Int32(width)
# @end


BUILDERS["cross"] = build_cross
TYPE_IDS["cross"] = "CrossTable"
