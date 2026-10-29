"""spec crossTable -> engine kind "cross" (engine/builders/cross.py).

rows / columns (levels) -> categorical expressions read like lib/70_tables.py: a bare column name
is escaped, several levels nest, and (Column Names) ends the column axis when neither axis holds it
and there is no column level or several measures. totals {rows, columns} must agree (the engine sets
both).
coloring (one object or a list, references/spec-format.md) -> APP "cellColors" [[measure display names or None, coloring],
...] (engine feature cellColoring): "measures" names the measures a coloring colors (their alias, or the
measure expression), none = the default numeric coloring, which then replaces the red negatives of
the style key "negatives".
"""
from . import _coloring
from ._common import NAMES_LEVEL

KIND = "cross"
SPEC_TYPES = ("crossTable",)
STYLE_KEYS = (("totals", "bool", "compact"), ("negatives", "bool", "quick"), ("font", "size", "quick"),
              ("headerFont", "size", "quick"), ("headerBold", "bool", "quick"),
              ("cellWidth", "width", "standard"), ("rowHeaderWidth", "width", "standard"))
HANDLED = ("rows", "columns", "measures", "totals", "coloring")


def _cat(levels):
    return "<" + " NEST ".join(levels) + ">" if levels else "<>"


def convert(v, rv, path, ctx):
    table = ctx.table(v)
    measures = [ctx.expr(m) for m in v.get("measures") or []]
    if not measures:
        ctx.unsupported(path + ".measures", "a cross table without measures")
    rows = ctx.levels(v.get("rows"), table)
    cols = ctx.levels(v.get("columns"), table)
    if not any(NAMES_LEVEL in level for level in rows + cols) and (not cols or len(measures) > 1):
        cols.append(NAMES_LEVEL)
    out = {"table": table, "rows": _cat(rows), "columns": _cat(cols), "measures": measures}
    totals = v.get("totals")
    if isinstance(totals, dict) and (totals.get("rows") is not None or totals.get("columns") is not None):
        r, c = totals.get("rows"), totals.get("columns")
        if r is None or c is None or bool(r) != bool(c):
            ctx.unsupported(path + ".totals", "grand totals on rows or columns only")
        elif bool(r) != ctx.default("cross", "totals", False):
            out["totals"] = bool(r)
    cells = cell_colorings(v, rv, measures, path, ctx)
    if cells:
        out["cellColors"] = cells
        negatives = rv.get("negatives", ctx.default("cross", "negatives", False))
        if [keys for keys, _ in cells if keys is None] and negatives is True and ctx.has("quick"):
            out["negatives"] = False             # the default numeric coloring is the spec's own
    return out


def cell_colorings(v, rv, measures, path, ctx):
    """coloring -> [[display names or None, APP coloring], ...] (lib/70_tables.py _tables_cross_coloring)."""
    value = v.get("coloring")
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    names = {}
    for raw, text in zip(v.get("measures") or [], measures):
        names[str(raw).strip()] = names[text] = _coloring.measure_name(text)
    out = []
    for n, c in enumerate(items):
        cp = "%s.coloring[%d]" % (path, n) if isinstance(value, list) else path + ".coloring"
        if not isinstance(c, dict):
            ctx.unsupported(cp, "a cross-table coloring that is not an object")
            continue
        keys = None
        if c.get("measures"):
            keys = []
            for m in c["measures"]:
                text = str(m).strip()
                keys.append(names.get(text, names.get(ctx.expr(text), text)))
        converted = _coloring.convert(c, cp, ctx, None, extra_keys=("measures",))
        if converted:
            out.append([keys, converted])
    return out
