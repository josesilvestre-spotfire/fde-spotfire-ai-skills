# Standard engine, kind "table": table plot.
# APP keys: table, columns [name or [name, width px]], negatives
# [columns drawn in red text below zero], cellColors [[columns,
# coloring], ...] (feature cellColoring, features/coloring.py); style
# keys (STYLE visual
# "table" defaults): font, headerFont, headerBold.
# Converter: scripts/t3/table.py.
# @uses _tabular
# @api TablePlot.Data; TablePlot.AutoAddNewColumns; TablePlot.TableColumns
# @api TableColumnCollection.Clear; TableColumnCollection.Add(DataColumn)
# @api TablePlot.Legend; VisualTypeIdentifiers.Table
# @set VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference; TablePlot.AutoAddNewColumns
from System import Int32
from Spotfire.Dxp.Application.Visuals import TablePlot

# ---------------------------------------------------------------- table
def build_table(v, vs):
    vid = vs["id"]
    t = T[vs["table"]]
    tp = v.As[TablePlot]()
    tp.Data.DataTableReference = t
    tp.Data.MarkingReference = MARK
    tp.AutoAddNewColumns = False
    tp.TableColumns.Clear()
    columns = []
    for item in vs["columns"]:
        if isinstance(item, str):
            item = [item, None]
        columns.append(item)
        ok(vid + ": column " + item[0], add_column, tp, t, item[0])
    # @tier standard
    for cname, width in columns:
        if width:
            ok(vid + ": width " + cname, column_width, tp, t, cname,
               width)
    # @end
    ok(vid + ": legend", legend, tp, vs)
    # @tier quick
    ok(vid + ": fonts", table_fonts, tp, vs)
    if opt(vs, "negatives"):
        ok(vid + ": negatives", negatives, tp, opt(vs, "negatives"))
    # @end
    # @feature cellColoring
    if vs.get("cellColors"):
        cell_colorings(tp, vs)
    # @endfeature


def add_column(tp, t, cname):
    tp.TableColumns.Add(t.Columns[cname])


# @tier standard
# @api TableColumnCollection.TryGetTableColumn; TableColumn.Width
# @set TableColumn.Width
def column_width(tp, t, cname, width):
    found, tc = tp.TableColumns.TryGetTableColumn(t.Columns[cname])
    if not found:
        raise Exception("the column is not shown in the table")
    tc.Width = Int32(width)
# @end


BUILDERS["table"] = build_table
TYPE_IDS["table"] = "Table"
