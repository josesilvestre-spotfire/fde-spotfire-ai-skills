"""spec lineChart -> engine kind "line" (engine/builders/line.py)."""
from ._charts import CHART_HANDLED, chart_body, curves, refs

KIND = "line"
SPEC_TYPES = ("lineChart",)
# (key, check, tier): app.style.visual.line defaults, and per-visual keys of a lineChart.
STYLE_KEYS = (("yFormat", "format", "standard"), ("lineWidth", "size", "standard"),
              ("axisFont", "size", "quick"), ("axisTitleFont", "size", "quick"),
              ("legendFont", "size", "quick"))
HANDLED = CHART_HANDLED          # lineWidth is a style key (written by scripts/t3/__init__.py)


def convert(v, rv, path, ctx):
    out = chart_body(v, path, ctx)
    fits = curves(v, path, ctx)
    if fits:
        out["curves"] = fits                     # engine feature fitting
    lines = refs(v, path, ctx)
    if lines:
        out["refs"] = lines
    return out
