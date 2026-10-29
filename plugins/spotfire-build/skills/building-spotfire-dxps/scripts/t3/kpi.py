"""spec kpiChart -> engine kind "kpi" (engine/builders/kpi.py).

kpis[] {title, value, format, coloring} -> [title, expression, format name(, coloring)]; format is a
name of app.style.formats (or a format string, mapped back to its name when one matches). A KPI's
coloring (or the visual-level coloring, the default of every KPI) becomes the APP coloring object of
scripts/t3/_coloring.py, colored by the tile's final value (engine feature kpiColoring). Comparative,
time, tileBy and settings need the slim tier for now. limitExpression -> "where"
(engine/features/links.py: the chart and every tile).
"""
from . import _coloring
from ._common import blank

KIND = "kpi"
SPEC_TYPES = ("kpiChart",)
STYLE_KEYS = (("baseFont", "size", "quick"), ("minTilesPerRow", "count", "standard"),
              ("minVisibleTiles", "count", "standard"), ("emptyText", "text", "standard"),
              ("tile", "color", "standard"))
HANDLED = ("kpis", "limitExpression", "coloring")


def convert(v, rv, path, ctx):
    items = []
    default = v.get("coloring") if isinstance(v.get("coloring"), dict) else None
    if v.get("coloring") is not None and default is None:
        ctx.unsupported(path + ".coloring", "a KPI chart coloring that is not one object")
    for k, item in enumerate(v.get("kpis") or []):
        ip = "%s.kpis[%d]" % (path, k)
        for key in ("comparative", "time", "tileBy", "settings"):
            if not blank(item.get(key)):
                ctx.unsupported(ip + "." + key, "KPI '%s'" % key)
        fmt = item.get("format") if ctx.has("standard") else None
        entry = [item.get("title") or "", ctx.expr(item.get("value")),
                 ctx.format_name(fmt) if fmt else None]
        own = item.get("coloring") if isinstance(item.get("coloring"), dict) else None
        if own or default:
            converted = _coloring.convert(own or default, ip + ".coloring" if own else path + ".coloring",
                                          ctx)
            if converted:
                entry.append(converted)            # engine feature kpiColoring
        items.append(entry)
    out = {"table": ctx.table(v), "kpis": items}
    if v.get("limitExpression"):
        out["where"] = ctx.expr(v["limitExpression"])
    return out
