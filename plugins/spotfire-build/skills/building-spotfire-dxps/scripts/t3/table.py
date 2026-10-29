"""spec table -> engine kind "table" (engine/builders/table.py).

columns + widths {column: px} -> columns [name or [name, width]]. Red negatives come from the
per-visual style key "negatives" (column list) or from a coloring that is exactly the red-negatives
rule (lessThan 0 in STYLE "negative", default STYLE "text", SetColorOnText true), which the slim
tier builds as written; every other coloring (with its "columns") becomes APP "cellColors" [[columns,
coloring], ...] (engine feature cellColoring, scripts/t3/_coloring.py). sort needs the slim tier for now.
limitExpression -> "where" (engine/features/links.py).
"""
from . import _coloring
from ._common import blank

KIND = "table"
SPEC_TYPES = ("table",)
STYLE_KEYS = (("negatives", "columns", "quick"), ("font", "size", "quick"),
              ("headerFont", "size", "quick"), ("headerBold", "bool", "quick"))
HANDLED = ("columns", "widths", "coloring", "limitExpression")


def _name(column):
    c = str(column).strip()
    if c.startswith("[") and c.endswith("]"):
        return c[1:-1].replace("]]", "]")
    return c


def negatives_from_coloring(coloring, path, ctx, cells=None, table=None):
    """Columns of a red-negatives coloring, or None; every other coloring goes to cells (a list:
    [[columns, APP coloring], ...]; None = reported unsupported)."""
    if blank(coloring):
        return None
    items = coloring if isinstance(coloring, list) else [coloring]
    columns = []
    for n, c in enumerate(items):
        cp = "%s.coloring[%d]" % (path, n) if isinstance(coloring, list) else path + ".coloring"
        rules = c.get("rules") or []
        settings = c.get("settings") or {}
        rule = rules[0] if len(rules) == 1 else {}
        value = rule.get("value")
        matches = (all(blank(c.get(k)) for k in ("categorical", "gradient", "fixed"))
                   and rule.get("type") == "lessThan"
                   and (value in (0, 0.0) or (isinstance(value, str) and value.strip() in ("0", "0.0")))
                   and not isinstance(value, bool)
                   and ctx.same_color(rule.get("color"), ctx.style.get("negative"))
                   and (c.get("default") is None or ctx.same_color(c.get("default"), ctx.style.get("text")))
                   and settings == {"SetColorOnText": True} and c.get("columns"))
        if not matches:
            if cells is None:
                ctx.unsupported(cp, "a table coloring other than red negatives (rule lessThan 0 in "
                                "app.style negative, default app.style text, SetColorOnText true)")
                continue
            names = [_name(x) for x in c.get("columns") or []]
            if not names:
                ctx.unsupported(cp + ".columns", "a table coloring without columns")
                continue
            converted = _coloring.convert(c, cp, ctx, ctx.column_type(table, names[0]),
                                          extra_keys=("columns",))
            if converted:
                cells.append([names, converted])
            continue
        columns.extend(_name(x) for x in c["columns"] if _name(x) not in columns)
    return columns


def convert(v, rv, path, ctx):
    table = ctx.table(v)
    names = v.get("columns")
    if not names:
        cols = ctx.columns_of(table)
        if not cols:
            ctx.unsupported(path, "a table without 'columns' (its data file could not be read)")
            names = []
        else:
            names = [c for c, _ in cols]
    widths = v.get("widths") or {}
    columns = []
    for c in names:
        name = _name(c)
        width = widths.get(c, widths.get(name))
        columns.append([name, width] if width and ctx.has("standard") else name)
    out = {"table": table, "columns": columns}
    if v.get("limitExpression"):
        out["where"] = ctx.expr(v["limitExpression"])
    cells = []
    negatives = negatives_from_coloring(v.get("coloring"), path, ctx, cells, table)
    explicit = rv.get("negatives")
    if explicit:
        negatives = list(negatives or []) + [_name(x) for x in explicit if _name(x) not in (negatives or [])]
    if negatives and ctx.has("quick"):
        out["negatives"] = negatives
    if cells:
        out["cellColors"] = cells                # engine feature cellColoring
    return out
