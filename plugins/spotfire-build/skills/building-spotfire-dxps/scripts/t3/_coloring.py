"""Spec coloring objects -> the APP coloring object of the standard engine (engine/features/coloring.py).

    convert(cspec, path, ctx, type_name=None)   one references/spec-format.md coloring object -> APP dict (None when empty)
    simple(cspec)                               True when the base chart colors (fixed, or categorical
                                                without default / "(Empty)") express it: line and bar
                                                charts keep those APP keys, so their builders do not change
    measure_name(expression)                    a cross-table measure's display name (its coloring key)

Reads the spec like lib/65_coloring.py: one background (categorical | gradient | fixed), rules above it
in spec order (the first rule wins), default, the "(Empty)" category, settings (paths relative to the
Coloring, checked by dxpgen against the API index). Values (gradient "at", rule value / low / high):
min, max, median, average, "NN%", a number (typed like the colored values when they are known: a whole
number on a Real column becomes 1.0; unknown types keep the JSON type), or an expression ([$Name] ->
DocumentProperty("Name")). An equal rule on text is a string rule (literal, or DocumentProperty of a
String property), anything else a threshold rule, as lib/65_coloring.py decides it.
"""
import re

from ._common import COLOR_RE, PROP_RE, blank

KEYWORDS = ("min", "max", "median", "average")
NUMERIC = ("Integer", "LongInteger", "Real", "SingleReal", "Currency")
WHOLE = ("Integer", "LongInteger")
ORDERED = NUMERIC + ("Date", "DateTime", "Time", "TimeSpan")
KEYS = ("categorical", "gradient", "fixed", "rules", "default", "settings")
RULE_KEYS = ("type", "value", "low", "high", "count", "expression", "color")
_ALIAS_RE = re.compile(r"(?:(?<=\s)|(?<=[\)\]]))as(?:\s*(\[(?:[^\]]|\]\])+\])|\s+([A-Za-z_][A-Za-z0-9_]*))\s*$",
                       re.IGNORECASE)


def simple(cspec):
    """The base chart colors (APP color / categories) cover it."""
    if not isinstance(cspec, dict):
        return False
    extra = [k for k in cspec if k not in ("fixed", "categorical") and not blank(cspec[k])]
    if extra:
        return False
    cats = cspec.get("categorical") or {}
    return "(Empty)" not in cats


def is_keyword(text):
    word = str(text).strip().lower()
    if word in KEYWORDS:
        return True
    if word.endswith("%"):
        try:
            float(word[:-1])
            return True
        except ValueError:
            return False
    return False


def color(value, path, ctx):
    """'#RRGGBB' / '#AARRGGBB' (alpha kept: the engine reads it) or '@name'."""
    if isinstance(value, str) and (COLOR_RE.match(value) or value.startswith("@")):
        return value
    ctx.unsupported(path, "a color %r that is not '#RRGGBB' or '#AARRGGBB'" % (value,))
    return "#000000"


def value(v, path, ctx, type_name=None):
    """Spec value -> APP value (engine cond())."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if type_name in WHOLE and float(v).is_integer():
            return int(v)
        if isinstance(v, int) and type_name in (None, "Real", "SingleReal", "Currency"):
            return float(v)
        return v
    if v is None or isinstance(v, (list, dict)):
        ctx.unsupported(path, "a coloring value %r" % (v,))
        return "min"
    text = str(v).strip()
    if is_keyword(text):
        return text.lower()
    return ctx.expr(text)


def prop_is_text(name, ctx):
    for p in ctx.resolved.get("properties") or []:
        if isinstance(p, dict) and str(p.get("name", "")).lower() == str(name).lower():
            return p.get("type", "String") == "String"
    return True


def rule(r, path, ctx, type_name=None):
    """One spec rule -> [type, color, value, ...] or None."""
    if not isinstance(r, dict):
        ctx.unsupported(path, "a coloring rule that is not an object")
        return None
    if not blank(r.get("settings")):
        ctx.unsupported(path + ".settings", "coloring rule settings")
    if r.get("shape") is not None:
        ctx.unsupported(path + ".shape", "a rule shape (graphical-table icons)")
    kind = r.get("type")
    c = color(r.get("color"), path + ".color", ctx)
    if kind in ("greaterThan", "lessThan"):
        return [kind, c, value(r.get("value"), path + ".value", ctx, type_name)]
    if kind == "between":
        return [kind, c, value(r.get("low"), path + ".low", ctx, type_name),
                value(r.get("high"), path + ".high", ctx, type_name)]
    if kind == "equal":
        v = r.get("value")
        if isinstance(v, str) and not is_keyword(v) and type_name not in ORDERED:
            m = PROP_RE.fullmatch(v.strip())
            if m is None and "[$" not in v:
                return ["equalText", c, v, False]
            if m is not None and prop_is_text(m.group(1), ctx):
                return ["equalText", c, ctx.expr(v), True]
            return ["equal", c, ctx.expr(v)]
        return ["equal", c, value(v, path + ".value", ctx, type_name)]
    if kind in ("top", "bottom"):
        count = r.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            ctx.unsupported(path + ".count", "a top/bottom count %r" % (count,))
            count = 1
        return [kind, c, count]
    if kind == "expression":
        return [kind, c, ctx.expr(r.get("expression") or "")]
    ctx.unsupported(path + ".type", "coloring rule type '%s'" % kind)
    return None


def convert(cspec, path, ctx, type_name=None, extra_keys=()):
    """references/spec-format.md coloring object -> APP coloring dict, or None when it says nothing. extra_keys: target
    keys the caller reads itself (table columns, cross-table measures)."""
    if not isinstance(cspec, dict):
        ctx.unsupported(path, "a coloring that is not an object")
        return None
    for key in cspec:
        if key not in KEYS and key not in extra_keys:
            ctx.unsupported(path + "." + key, "coloring field '%s'" % key)
    out = {}
    cats = cspec.get("categorical")
    if cats:
        pairs = []
        for key, c in cats.items():
            if key == "(Empty)":
                out["empty"] = color(c, path + ".categorical.(Empty)", ctx)
                continue
            pairs.append([category(key, type_name), color(c, path + ".categorical." + key, ctx)])
        out["categorical"] = pairs
    elif cspec.get("gradient"):
        points = []
        for k, point in enumerate(cspec["gradient"]):
            pp = "%s.gradient[%d]" % (path, k)
            if not isinstance(point, dict):
                ctx.unsupported(pp, "a gradient point that is not {at, color}")
                continue
            points.append([value(point.get("at"), pp + ".at", ctx, type_name),
                           color(point.get("color"), pp + ".color", ctx)])
        if len(points) < 2:
            ctx.unsupported(path + ".gradient", "a gradient with fewer than two points")
        out["gradient"] = points
    elif cspec.get("fixed") is not None:
        out["fixed"] = color(cspec["fixed"], path + ".fixed", ctx)
    rules = []
    for k, r in enumerate(cspec.get("rules") or []):
        converted = rule(r, "%s.rules[%d]" % (path, k), ctx, type_name)
        if converted is not None:
            rules.append(converted)
    if rules:
        out["rules"] = rules
    if cspec.get("default") is not None and cspec.get("fixed") is None:
        out["default"] = color(cspec["default"], path + ".default", ctx)
    if isinstance(cspec.get("settings"), dict) and cspec["settings"]:
        out["settings"] = dict(cspec["settings"])
    return out or None


def category(key, type_name):
    """A categorical key typed like the color-by column (JSON keys are text)."""
    try:
        if type_name in WHOLE:
            return int(key)
        if type_name in ("Real", "SingleReal"):
            return float(key)
        if type_name == "Boolean":
            return str(key).strip().lower() == "true"
    except ValueError:
        pass
    return key


def measure_name(expression):
    """Display name of a cross-table measure: its alias, else the expression without identifier
    brackets (Spotfire's own name: Sum([A]) -> 'Sum(A)')."""
    text = str(expression).strip()
    m = _ALIAS_RE.search(text)
    if m:
        if m.group(1):
            return m.group(1)[1:-1].replace("]]", "]")
        return m.group(2)
    return text.replace("]]", "\x00").replace("[", "").replace("]", "").replace("\x00", "]")


def column_type(expression, table, ctx):
    """DataType name of a color-by that is one plain column ([Col] or <[Col]>), else None."""
    if not isinstance(expression, str):
        return None
    m = re.match(r"^<?\s*\[((?:[^\]]|\]\])+)\]\s*>?$", expression.strip())
    if not m:
        return None
    return ctx.column_type(table, m.group(1).replace("]]", "]"))
