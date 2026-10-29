"""spec barChart -> engine kind "bar" (engine/builders/bar.py)."""
from ._charts import CHART_HANDLED, chart_body, curves, refs

KIND = "bar"
SPEC_TYPES = ("barChart",)
STYLE_KEYS = (("yFormat", "format", "standard"), ("axisFont", "size", "quick"),
              ("axisTitleFont", "size", "quick"), ("legendFont", "size", "quick"))
HANDLED = CHART_HANDLED + ("stack", "orientation", "sort")
STACKS = {"stacked": True, "percent": "percent", "sidebyside": "sideBySide"}


def convert(v, rv, path, ctx):
    extra = []
    stack = v.get("stack")
    if stack is not None:
        mode = STACKS.get(str(stack).strip().lower())
        if mode is None:
            ctx.unsupported(path + ".stack", "stack '%s'" % stack)
        else:
            extra.append(("stack", mode))
    orientation = str(v.get("orientation") or "vertical").strip().lower()
    if orientation == "horizontal":
        extra.append(("horizontal", True))
    elif orientation != "vertical":
        ctx.unsupported(path + ".orientation", "orientation '%s'" % v.get("orientation"))
    sort = str(v.get("sort") or "none").strip().lower()
    if sort in ("ascending", "descending"):
        extra.append(("sort", sort))
    elif sort != "none":
        ctx.unsupported(path + ".sort", "sort '%s'" % v.get("sort"))
    out = chart_body(v, path, ctx, extra, categorical_x=True)
    fits = curves(v, path, ctx)
    if fits:
        out["curves"] = fits                     # engine feature fitting
    lines = refs(v, path, ctx)
    if lines:
        out["refs"] = lines
    return out
