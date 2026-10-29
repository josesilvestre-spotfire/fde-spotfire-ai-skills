# ============================================================================
# 65_coloring.py - coloring (chart color axes and cell colorings), reference
# layers and fitting models. IronPython 3.4 inside Spotfire Analyst 15.0
# (Python 3.4 syntax: no f-strings, no walrus, no annotations, no print).
# Public API only; no internal members. Reference: references/api-coloring.md.
#
# Contract functions (references/architecture.md), called by the visual builders after the
# visual's table and every other axis expression are set:
#   apply_coloring(content, vspec)                 colorBy + coloring: the ColorAxis of a chart or
#                                                  map layer visualization, or the Colorings of a
#                                                  heat map / table / cross table (default numeric
#                                                  coloring). Also accepts (ColorAxis or Coloring,
#                                                  bare coloring object).
#   apply_reference_layers(content, layers, vid=None)   horizontalLine, verticalLine, band
#   apply_fitting_models(content, models, vid=None)     straightLine, curve
# Helpers for other modules (70_tables, 75_maps, ...):
#   coloring_configure(coloring, cspec, target, type_name=None, cell=False, record=None)
#   coloring_apply_axis(color_axis, cspec, target, expression=None, type_name=None)
#   coloring_apply_kpi(kpi_visualization, cspec, target)
#   coloring_add_cell_coloring(colorings, cspec, target, key=None, name=None, type_name=None,
#                              cell=True)
#   coloring_expression(text)
# Every item (color-by, background, each rule, settings, each layer, each model)
# is its own B.step: a failure is reported and the build goes on.
#
# Spec interpretation owned by this module:
# - `[$Name]` is the spec's shorthand for a document property; Spotfire has no
#   such syntax, so every expression written here gets DocumentProperty("Name").
#   Curve expressions also map [Axis.X] to x (the Curve Draw variable).
# - colorBy is written as given ([$Name] translated as everywhere); a list of category levels
#   becomes "<[A] NEST [B]>".
# - Background: categorical | gradient | fixed (exclusive). Rules without a
#   background = fixed mode: values that match no rule get `default`. A chart
#   with `fixed`, no rules and no colorBy colors by (None), "<>" (not pie charts).
# - `default` with categorical = a one-color palette (every category without
#   its own color); key "(Empty)" sets the empty-value color.
# - Rules go above the background rule, as in Analyst (its rule dialog inserts
#   every new rule at the top). Spec order = list order top-down: the first spec
#   rule is the top rule (highest precedence).
# - Numeric literals keep their JSON type (100.0 Real, 3 Integer) unless the
#   target type is known (plain-column color-by, or type_name from the caller).
# - Reference layers: dash / width style a line; on a band they draw its outline.
#
# Requires newer than 14.6: ReferenceLayer.Data and
# ReferenceLayerData.DataTableReference [api 15.0], only for a layer `table`.
# ============================================================================
import clr
clr.AddReference("System.Drawing")
import re

from System import Array, Object, Int32, Int64, Single
from System.Drawing import Color
from Spotfire.Dxp.Framework.Styles import ColorInfo, TextAlign, VerticalTextAlign
from Spotfire.Dxp.Application.Visuals import CategoryKey, LineStyle
from Spotfire.Dxp.Application.Visuals.ConditionalColoring import (CategoricalColorRule,
                                                                  ContinuousColorRule,
                                                                  ConditionValue, IntervalMode,
                                                                  RuleComparisonOperator,
                                                                  StringComparisonOperator)
from Spotfire.Dxp.Application.Visuals.ReferenceElements import ValueAxis
from Spotfire.Dxp.Application.Visuals.Styles import Fill

_coloring_prop_re = re.compile(r"\[\$([A-Za-z0-9_.]+)\]")
_coloring_axis_x_re = re.compile(r"\[Axis\.X\]", re.IGNORECASE)
_coloring_column_re = re.compile(r"^<?\s*\[((?:[^\]]|\]\])+)\]\s*>?$")
_coloring_kpi_expression = "THEN [Y.FinalValue]"     # KPI tile color-by (GUI-built DXPs: every KPI)
_coloring_backgrounds = ("categorical", "gradient", "fixed")
_coloring_cspec_keys = ("categorical", "gradient", "fixed", "rules", "default")
_coloring_numeric_types = ("Integer", "LongInteger", "Real", "SingleReal", "Currency")
_coloring_ordered_types = _coloring_numeric_types + ("Date", "DateTime", "Time", "TimeSpan")
_coloring_layer_names = {"horizontalLine": "Horizontal line", "verticalLine": "Vertical line",
                         "band": "Band"}
_coloring_dashes = {"solid": "Single", "dot": "Dot", "dash": "Dash", "double": "Double"}


# ---- expressions ------------------------------------------------------------------------
def coloring_expression(text):
    """Spec expression -> Spotfire expression text.

    Numbers become literals (repr is culture-invariant). `[$Name]` becomes
    DocumentProperty("Name"), the property function (preferred over ${Name} text
    substitution: coloring note, pitfall 15).
    """
    if text is None:
        return None
    if isinstance(text, bool):
        return "true" if text else "false"
    if isinstance(text, (int, float)):
        return repr(text)
    return _coloring_prop_re.sub(_coloring_prop_call, str(text))


def _coloring_prop_call(match):
    return 'DocumentProperty("' + match.group(1) + '")'


def _coloring_prop_name(text):
    """'[$Name]' (the whole text) -> 'Name', else None."""
    s = str(text).strip()
    m = _coloring_prop_re.match(s)
    if m is not None and m.end() == len(s):
        return m.group(1)
    return None


def _coloring_curve_expression(text):
    """Curve Draw expressions use x for the X value (GUI-built DXPs: "x"); the spec may write
    [Axis.X]."""
    return _coloring_axis_x_re.sub("x", coloring_expression(text))


def _coloring_preprocessor_call(match):
    return "${" + match.group(1) + "}"


def _coloring_curve_fallback(text):
    """The same curve with ${Name} text substitution instead of DocumentProperty("Name")."""
    return _coloring_axis_x_re.sub("x", _coloring_prop_re.sub(_coloring_preprocessor_call, str(text)))


def _coloring_color_by(value):
    """colorBy: one expression, or a list of category levels -> "<[A] NEST [B]>" (a color axis
    takes one expression; nested levels as 70_tables.py builds categorical axes). `[$Name]` is
    translated like every other spec expression; already translated text (60_charts, 75_maps)
    passes through unchanged, so the expression set by the caller is not reset."""
    if not isinstance(value, (list, tuple)):
        return coloring_expression(str(value))
    levels = []
    for item in value:
        text = str(item).strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1].strip()
        levels.append(text)
    if len(levels) == 1:
        return coloring_expression(str(value[0]).strip())
    return coloring_expression("<" + " NEST ".join(levels) + ">")


def _coloring_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ---- small helpers ----------------------------------------------------------------------
def _coloring_need(spec, key, what):
    value = spec.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise Exception(str(what) + " needs '" + key + "'")
    return value


def _coloring_color(value, what):
    if value is None or not str(value).strip():
        raise Exception(str(what) + " needs a color")
    return color(value)


def _coloring_colorinfo(c):
    """System.Drawing.Color -> opaque ColorInfo for Stroke / Fill (the alpha becomes the layer's
    Transparency instead; whether Spotfire draws ColorInfo alpha is Not yet tested U8)."""
    return ColorInfo(Color.FromArgb(255, c.R, c.G, c.B).ToArgb())


def _coloring_clamp(value, low, high):
    return max(low, min(high, float(value)))


def _coloring_vid(content, vid):
    """Visual id for report targets: the given id, else the target of the enclosing
    B.step("visual", <id>, ...) that 90_build.build_visual opened, else the content title."""
    if vid:
        return str(vid)
    steps = B.report["steps"]
    for i in range(len(steps) - 1, -1, -1):
        if steps[i].get("name") == "visual":
            return str(steps[i].get("target"))
    try:
        return str(content.Title) or "visual"
    except Exception:
        return "visual"


def _coloring_record(target, entry):
    """B.created["coloring"][target] = what was built (for verify_dxp)."""
    store = B.created.setdefault("coloring", {})
    key = target
    n = 2
    while key in store:          # several colorings under one target (map layers)
        key = target + " #" + str(n)
        n += 1
    store[key] = entry


def _coloring_is_cspec(spec):
    """True for a coloring object (categorical/gradient/fixed/rules/default), False for a visual
    spec (has id / colorBy / coloring)."""
    if "id" in spec or "colorBy" in spec or "coloring" in spec:
        return False
    for key in _coloring_cspec_keys:
        if key in spec:
            return True
    return False


def _coloring_axis_type(content, expression):
    """DataType name of a color-by that is one plain column ([Col] or <[Col]>), else None."""
    try:
        text = expression if expression is not None else content.ColorAxis.Expression
        m = _coloring_column_re.match(str(text or "").strip())
        if m is None:
            return None
        table = content.Data.DataTableReference
        if table is None:
            return None
        found, column = table.Columns.TryGetValue(m.group(1).replace("]]", "]"))
        if not found:
            return None
        return str(column.DataType.Name)
    except Exception:
        return None


# ---- condition values ---------------------------------------------------------------------
def _coloring_literal(number, type_name):
    """Numeric ConditionValue literal, typed like the target when known, else like the JSON value."""
    if type_name not in _coloring_numeric_types:
        if isinstance(number, float):
            type_name = "Real"
        elif -2147483648 <= number <= 2147483647:
            type_name = "Integer"
        else:
            type_name = "LongInteger"
    # Not yet tested: an Integer literal compared with Real values (and vice versa).
    return ConditionValue.CreateLiteral(net_value(type_name, number), data_type(type_name))


def _coloring_is_keyword(text):
    word = str(text).strip().lower()
    if word in ("min", "max", "median", "average"):
        return True
    if word.endswith("%"):
        try:
            float(word[:-1])
            return True
        except ValueError:
            return False
    return False


def _coloring_condition(value, type_name=None):
    """Spec value -> ConditionValue: a number, 'min' | 'max' | 'median' | 'average', 'NN%'
    (percent of the min..max range), or any other string as an expression."""
    if value is None:
        raise Exception("coloring value missing")
    if isinstance(value, bool):
        return ConditionValue.CreateLiteral(value)
    if isinstance(value, (int, float)):
        return _coloring_literal(value, type_name)
    text = str(value).strip()
    word = text.lower()
    if word == "min":
        return ConditionValue.MinValue
    if word == "max":
        return ConditionValue.MaxValue
    if word == "median":
        return ConditionValue.MedianValue
    if word == "average":
        return ConditionValue.AverageValue
    if word.endswith("%"):
        try:
            return ConditionValue.CreatePercentValue(float(word[:-1]))
        except ValueError:
            pass
    # Not yet tested: expression values such as DocumentProperty("X") or Avg([Axis.Color]).
    return ConditionValue.CreateExpression(coloring_expression(text))


def _coloring_category_part(key, type_name):
    """Categorical key typed like the color-by column (JSON keys are strings)."""
    # Not yet tested: numeric and Boolean category keys (coloring note U6).
    try:
        if type_name == "Integer":
            return Int32(int(key))
        if type_name == "LongInteger":
            return Int64(int(key))
        if type_name == "Real":
            return float(key)
        if type_name == "SingleReal":
            return Single(float(key))
        if type_name == "Boolean":
            return str(key).strip().lower() == "true"
    except ValueError:
        pass
    return key


def _coloring_prop_is_text(name):
    """True when document property `name` is a String (spec first, then its current value)."""
    for p in B.spec.get("properties") or []:
        if str(p.get("name", "")).lower() == str(name).lower():
            return p.get("type") == "String"
    try:
        return isinstance(B.prop(name).Value, str)
    except Exception:
        return True


# ---- coloring: background and rules -----------------------------------------------------------
def _coloring_mode(cspec):
    given = [k for k in _coloring_backgrounds if cspec.get(k) is not None]
    if len(given) > 1:
        raise Exception("coloring: " + " and ".join(given) + " are exclusive, give one")
    if given:
        return given[0]
    if cspec.get("rules") or cspec.get("default") is not None:
        return "rules"
    return "none"


def _coloring_mode_name(cspec):
    try:
        return _coloring_mode(cspec)
    except Exception:
        return "invalid"


def _coloring_keep_one(coloring, rule_type):
    """Keep the first rule of rule_type (add one when missing) and remove every other rule.
    Reusing the rule Spotfire made for the color-by keeps its palette (theme colors)."""
    keep = None
    for i in range(coloring.Count):
        if isinstance(coloring[i], rule_type):
            keep = coloring[i]
            break
    for i in range(coloring.Count - 1, -1, -1):
        rule = coloring[i]
        if keep is None or not Object.ReferenceEquals(rule, keep):
            coloring.Remove(rule)
    if keep is None:
        if rule_type is CategoricalColorRule:
            keep = coloring.AddCategoricalColorRule()
        else:
            keep = coloring.AddContinuousColorRule()
    return keep


def _coloring_background(get_coloring, cspec, type_name, cell):
    """Background mode + default color. Returns the Coloring (the rules come after).
    The spec is validated and converted first: a bad entry leaves the document untouched."""
    mode = _coloring_mode(cspec)
    default = cspec.get("default")
    default_color = None if default is None else _coloring_color(default, "default")
    fixed_color = None
    pairs = []
    if mode == "categorical":
        given = cspec.get("categorical")
        if not isinstance(given, dict):
            raise Exception("categorical must be an object {category: color}")
        for key in given:
            pairs.append((key, _coloring_color(given[key], "category '" + str(key) + "'")))
    elif mode == "gradient":
        given = cspec.get("gradient")
        if not isinstance(given, (list, tuple)) or len(given) < 2:
            raise Exception("a gradient needs at least two points")    # a new rule has none (IL)
        for point in given:
            if not isinstance(point, dict):
                raise Exception("a gradient point must be an object {at, color}")
            pairs.append((_coloring_condition(_coloring_need(point, "at", "gradient point"), type_name),
                          _coloring_color(point.get("color"), "gradient point")))
    elif mode == "fixed":
        fixed_color = _coloring_color(cspec.get("fixed"), "fixed")
    coloring = get_coloring()
    if coloring is None:
        raise Exception("no Coloring to configure")
    if mode == "categorical":
        rule = _coloring_keep_one(coloring, CategoricalColorRule)
        if default_color is not None:
            # One-color palette: every category without its own color gets `default`.
            # SetColors clears explicit colors (IL), so it runs before them.
            # Not yet tested: a one-color palette is accepted and applied to unlisted categories.
            rule.SetColors(Array[Color]([default_color]))
        for key, c in pairs:
            if key == "(Empty)":
                coloring.EmptyColor = c          # Spotfire's label for empty values
            else:
                # Not yet tested: under (Column Names) the category of an aliased measure is its alias
                # ("Sum([A]) as [Inlet]" -> "Inlet"); proven for cross tables, INFERRED for charts (R1b).
                coloring.SetColorForCategory(CategoryKey(_coloring_category_part(key, type_name)), c)
    elif mode == "gradient":
        rule = _coloring_keep_one(coloring, ContinuousColorRule)
        rule.IntervalMode = IntervalMode.Gradient
        rule.Breakpoints.Clear()
        for value, c in pairs:
            rule.Breakpoints.Add(value, c)
    elif mode in ("fixed", "rules"):
        # No background rule = fixed color mode (GUI-built DXPs: every "<>" color axis, ColorRule[0]).
        # Not yet tested: with a categorical or continuous color-by the axis keeps zero rules
        # (ColorAxis.get_Coloring runs an invariant keeper that might re-add a background rule).
        coloring.Clear()
        if mode == "fixed":
            coloring.DefaultColor = fixed_color
    if mode not in ("fixed", "none"):
        if default_color is not None:
            coloring.DefaultColor = default_color
        elif cell:
            # Table / cross-table cells no rule matches stay uncolored (GUI-built DXPs: the cross-table
            # "Numeric" coloring persists DefaultColor #00000000; same rule as 70_tables.py).
            coloring.DefaultColor = color("#00000000")
    return coloring


def _coloring_equal_rule(coloring, value, c, type_name):
    """equal: numbers and keywords -> threshold rule; plain text -> string rule (literal); exactly
    [$Name] -> by the property's type (String: string rule on its value, else threshold); [$Name]
    inside a longer expression -> threshold rule on the expression (the same choices as
    70_tables._tables_equal_rule, so one spec form gives one result everywhere)."""
    text_value = (isinstance(value, str) and not _coloring_is_keyword(value)
                  and type_name not in _coloring_ordered_types)
    if text_value:
        prop = _coloring_prop_name(value)
        if prop is None and "[$" not in value:
            return coloring.AddStringColorRule(StringComparisonOperator.Equal,
                                               ConditionValue.CreateLiteral(value), c)
        expression = ConditionValue.CreateExpression(coloring_expression(value))
        if prop is not None and _coloring_prop_is_text(prop):
            # Not yet tested: an expression condition value in a string rule.
            return coloring.AddStringColorRule(StringComparisonOperator.Equal, expression, c)
        return coloring.AddThresholdColorRule(RuleComparisonOperator.Equal, expression, c)
    return coloring.AddThresholdColorRule(RuleComparisonOperator.Equal,
                                          _coloring_condition(value, type_name), c)


def _coloring_add_rule(coloring, rspec, position, type_name):
    """Add one spec rule and move it to `position` (above the background rule). Returns it."""
    rtype = rspec.get("type")
    c = _coloring_color(rspec.get("color"), "rule '" + str(rtype) + "'")
    if rtype in ("greaterThan", "lessThan"):
        op = RuleComparisonOperator.Greater if rtype == "greaterThan" else RuleComparisonOperator.Less
        value = _coloring_condition(_coloring_need(rspec, "value", rtype), type_name)
        rule = coloring.AddThresholdColorRule(op, value, c)
    elif rtype == "between":
        low = _coloring_condition(_coloring_need(rspec, "low", rtype), type_name)
        high = _coloring_condition(_coloring_need(rspec, "high", rtype), type_name)
        rule = coloring.AddRangeRule(low, high, c)
    elif rtype == "equal":
        rule = _coloring_equal_rule(coloring, _coloring_need(rspec, "value", rtype), c, type_name)
    elif rtype in ("top", "bottom"):
        count = Int32(int(_coloring_need(rspec, "count", rtype)))
        if rtype == "top":
            rule = coloring.AddTopNRule(count, c)
        else:
            rule = coloring.AddBottomNRule(count, c)
    elif rtype == "expression":
        # Not yet tested: what an expression rule may reference ([Axis.Color], columns; U10).
        rule = coloring.AddExpressionRule(
            coloring_expression(_coloring_need(rspec, "expression", rtype)), c)
    else:
        raise Exception("unknown coloring rule type: " + str(rtype))
    try:
        # Add*Rule appends after the background rule; Analyst moves every new rule to the top.
        # Not yet tested: precedence follows list order, top first (coloring note U3).
        index = coloring.IndexOf(rule)
        if index != position:
            coloring.Move(index, position)
        apply_settings(rule, rspec.get("settings"))
    except Exception:
        coloring.Remove(rule)
        raise
    return rule


def _coloring_fail(message):
    raise Exception(message)


def _coloring_configure(get_coloring, cspec, target, type_name, cell, record):
    if not isinstance(cspec, dict):
        B.step("coloring", target, _coloring_fail,
               ("a coloring must be one object, got " + type(cspec).__name__,))
        return None
    coloring = B.step("coloring", target, _coloring_background,
                      (get_coloring, cspec, type_name, cell))
    rules = _coloring_list(cspec.get("rules"))
    entry = dict(record or {})
    entry["mode"] = _coloring_mode_name(cspec)
    entry["default"] = cspec.get("default")
    entry["rules"] = [str(r.get("type")) if isinstance(r, dict) else "?" for r in rules]
    if coloring is None:
        entry["built"] = False
        _coloring_record(target, entry)
        return None
    placed = 0
    for i in range(len(rules)):
        rule = B.step("coloring.rule", target + "/rules[" + str(i) + "]", _coloring_add_rule,
                      (coloring, rules[i], placed, type_name))
        if rule is not None:
            placed += 1
    if cspec.get("settings"):
        B.step("coloring.settings", target, apply_settings, (coloring, cspec.get("settings")))
    entry["built"] = True
    entry["rulesBuilt"] = placed
    _coloring_record(target, entry)
    return coloring


def _coloring_set_expression(axis, expression):
    if axis.Expression != expression:
        axis.Expression = expression     # a change resets the rules: always before them
    return expression


def _coloring_cell_target(colorings, key, name):
    """The Coloring for cells: mapped to key(s) (table column names or cross-table measure
    display names), or the default numeric coloring when key is None."""
    keys = [str(k) for k in _coloring_list(key)]
    if not keys:
        coloring = colorings.DefaultNumericReference
        if coloring is None:
            coloring = colorings.AddNew(name or "Numeric")     # Analyst's own name for it
            colorings.DefaultNumericReference = coloring
        return coloring
    coloring = None
    mapped = [k for k in colorings.GetCategories()]
    for text in keys:
        wanted = CategoryKey(text)
        for k in mapped:
            if wanted.Equals(k):
                coloring = colorings.GetColoringForCategory(k)
                break
        if coloring is not None:
            break
    if coloring is None:
        coloring = colorings.AddNew(name or ", ".join(keys))
    for text in keys:
        colorings.AddMapping(CategoryKey(text), coloring)      # overwrites: idempotent (IL)
    return coloring


# ---- coloring: public ---------------------------------------------------------------------------
def coloring_configure(coloring, cspec, target, type_name=None, cell=False, record=None):
    """Configure any Coloring object from a spec coloring object (categorical, gradient, fixed,
    rules, default, settings). type_name: DataType name of the colored values when known (types
    literals and category keys). cell=True: values no rule matches stay uncolored. Never raises;
    returns the Coloring, or None when its background step failed."""
    if not cspec:
        return None
    return _coloring_configure(lambda: coloring, cspec, target, type_name, cell, record)


def coloring_apply_axis(color_axis, cspec, target, expression=None, type_name=None):
    """Color-by expression first (set only when it differs: a change resets the rules), then the
    spec coloring on color_axis.Coloring, read afterwards. Returns the Coloring or None."""
    if expression is not None:
        done = B.step("colorBy", target, _coloring_set_expression, (color_axis, expression))
        if done is None:
            if cspec:
                B.skip("coloring", target, "colorBy failed; coloring not applied")
            return None
    if not cspec:
        if expression is not None:
            _coloring_record(target, {"on": "colorAxis", "expression": expression,
                                      "mode": "spotfire-default", "built": True})
        return None
    shown = expression
    if shown is None:
        try:
            shown = str(color_axis.Expression)
        except Exception:
            shown = None
    record = {"on": "colorAxis", "expression": shown}
    return _coloring_configure(lambda: color_axis.Coloring, cspec, target, type_name, False, record)


def coloring_apply_kpi(kpi_visualization, cspec, target):
    """KPI tile coloring: color by the tile's final value (THEN [Y.FinalValue], the only KPI color
    expression in the corpus), then the spec coloring. Returns the Coloring or None."""
    if not cspec:
        return None
    return coloring_apply_axis(kpi_visualization.ColorAxis, cspec, target, _coloring_kpi_expression)


def coloring_add_cell_coloring(colorings, cspec, target, key=None, name=None, type_name=None,
                               cell=True):
    """Cell coloring in a ColoringCollection (TablePlot / CrossTablePlot / HeatMap .Colorings).
    key: a table column name or cross-table measure display name (its alias), or a list of them
    sharing one coloring; None = the default numeric coloring (DefaultNumericReference).
    Returns the Coloring or None."""
    if not cspec:
        return None
    record = {"on": "cells", "key": key}
    return _coloring_configure(lambda: _coloring_cell_target(colorings, key, name), cspec, target,
                               type_name, cell, record)


def apply_coloring(content, vspec):
    """colorBy + coloring of one visual (vspec["colorBy"], vspec["coloring"]).

    Charts and map layer visualizations (75_maps.py passes {"id", "colorBy", "coloring"}):
    content.ColorAxis. Heat maps, tables, cross tables: content.Colorings, default numeric
    coloring. Also accepts a ColorAxis or a Coloring as `content` with a bare coloring object as
    `vspec`. A `fixed` coloring without colorBy and rules colors by (None), "<>" (not on pie
    charts, whose color axis holds the sectors). Returns the Coloring.
    """
    spec = vspec if vspec is not None else {}
    if not isinstance(spec, dict) or _coloring_is_cspec(spec):
        cspec = spec
        color_by = None
        vid = _coloring_vid(content, None)
    else:
        cspec = spec.get("coloring")
        color_by = spec.get("colorBy")
        vid = str(spec.get("id") or _coloring_vid(content, None))
    if color_by is None and not cspec:
        return None
    target = vid + "/coloring"
    expression = None
    if color_by is not None:
        expression = _coloring_color_by(color_by)
    if hasattr(content, "ColorAxis"):
        kind = content.GetType().Name
        if (expression is None and isinstance(cspec, dict) and _coloring_mode_name(cspec) == "fixed"
                and not cspec.get("rules") and kind != "PieChart"):
            # A fixed color is color by (None), "<>", as Analyst stores it (GUI-built DXPs: every "<>"
            # axis has ColorRule[0] + DefaultColor). A pie chart's color axis holds its sectors.
            expression = "<>"
        if kind == "CombinationChart" and isinstance(cspec, dict) and cspec.get("gradient") is not None:
            B.warn(target + ": combination charts color by category only (gradient may not show)")
        type_name = _coloring_axis_type(content, expression)
        return coloring_apply_axis(content.ColorAxis, cspec, target, expression, type_name)
    if hasattr(content, "Colorings"):
        if expression is not None:
            B.warn(target + ": colorBy ignored; " + content.GetType().Name
                   + " cells are colored by their own values")
        if not cspec:
            return None
        heat = content.GetType().Name == "HeatMap"     # heat-map cells always get a color
        return coloring_add_cell_coloring(content.Colorings, cspec, target, cell=not heat)
    if hasattr(content, "Coloring") and hasattr(content, "Expression"):
        return coloring_apply_axis(content, cspec, target, expression)     # a ColorAxis
    if hasattr(content, "AddCategoricalColorRule"):
        return coloring_configure(content, cspec, target)                  # a Coloring
    B.skip("coloring", target, content.GetType().Name + " has no color axis or cell colorings")
    return None


# ---- reference layers ---------------------------------------------------------------------------
def _coloring_unique(base, used):
    name = base
    n = 2
    while name in used:
        name = base + " " + str(n)
        n += 1
    used.append(name)
    return name


def _coloring_line_style(dash):
    key = str(dash).strip().lower()
    if key not in _coloring_dashes:
        raise Exception("dash must be one of solid, dot, dash, double: " + str(dash))
    return enum_value(LineStyle, _coloring_dashes[key])


def _coloring_stroke(stroke, c, lspec):
    """The spec's color / dash / width on a Stroke. Stroke is immutable: With* returns a copy."""
    if c is not None:
        stroke = stroke.WithColor(_coloring_colorinfo(c))     # ColorType.Specific (IL)
    if lspec.get("dash"):
        stroke = stroke.WithStyle(_coloring_line_style(lspec["dash"]))
    if lspec.get("width") is not None:
        stroke = stroke.WithWidth(Single(_coloring_clamp(lspec["width"], 1.0, 10.0)))
    return stroke


def _coloring_configure_layer(layer, kind, lspec, used):
    label = lspec.get("label")
    if label:
        label = str(label)
        layer.Name = label
        used.append(label)                       # later automatic names avoid it
    else:
        layer.Name = _coloring_unique(_coloring_layer_names[kind], used)
    table = lspec.get("table")
    if table:
        try:
            data = layer.Data                    # [api 15.0]
        except AttributeError:
            raise Exception("'table' on a reference layer needs Spotfire 15.0 (ReferenceLayer.Data)")
        data.DataTableReference = B.table(table)    # before the expressions: they bind to it
    layer.ValueAxis = ValueAxis.X if kind == "verticalLine" else ValueAxis.Y
    if kind == "band":
        expression = coloring_expression(lspec.get("high"))
        secondary = coloring_expression(lspec.get("low"))
        layer.Expression = expression            # Value = upper edge (GUI-built DXPs 95% CI band)
        layer.SecondaryExpression = secondary
    else:
        expression = coloring_expression(lspec.get("value"))
        secondary = None
        # Not yet tested: DocumentProperty("X") values, and the line following the property (U2).
        layer.Expression = expression
    c = None
    if lspec.get("color"):
        c = color(lspec["color"])
    if kind == "band":
        layer.Line.Enabled = False
        layer.Band.FillEnabled = True            # every element starts switched off
        if c is not None:
            layer.Band.Fill = Fill().WithColor(_coloring_colorinfo(c))
        if lspec.get("dash") or lspec.get("width") is not None:
            # dash / width on a band draw its outline (the Area stroke, off by default).
            # Not yet tested: the outline follows both band edges.
            layer.Band.StrokeEnabled = True
            layer.Band.Stroke = _coloring_stroke(layer.Band.Stroke, c, lspec)
        layer.IsBackground = True                # draw the band behind the data
    else:
        layer.Line.Enabled = True
        layer.Line.Stroke = _coloring_stroke(layer.Line.Stroke, c, lspec)   # default: width 2
    if c is not None and c.A < 255:
        # Not yet tested: Transparency fades the whole layer (GUI-built DXPs event bands: 0.72).
        layer.Transparency = Single(round(1.0 - c.A / 255.0, 3))
    if label:
        layer.Label.Enabled = True
        style = layer.Label.Style.WithShowDisplayName(True).WithShowValue(False)
        if kind != "band":
            # Not yet tested: label placement (right end, above the line) and that the label
            # text is the layer name.
            style = style.WithTextAlign(TextAlign.Right).WithVerticalTextAlign(VerticalTextAlign.Top)
        layer.Label.Style = style
    apply_settings(layer, lspec.get("settings"))
    return {"kind": kind, "name": str(layer.Name), "expression": expression,
            "secondaryExpression": secondary, "valueAxis": str(layer.ValueAxis),
            "table": table or None, "color": lspec.get("color"), "dash": lspec.get("dash"),
            "width": lspec.get("width"), "label": label or None}


def _coloring_build_layer(content, lspec, used):
    kind = lspec.get("kind")
    if kind not in _coloring_layer_names:
        raise Exception("unknown reference layer kind: " + str(kind))
    if kind == "band":
        _coloring_need(lspec, "low", "band")
        _coloring_need(lspec, "high", "band")
    else:
        _coloring_need(lspec, "value", kind)
    layers = content.Layers
    layer = layers.AddNewReferenceLayer()
    try:
        info = _coloring_configure_layer(layer, kind, lspec, used)
    except Exception:
        try:
            layers.Remove(layer)                 # never leave a half-built layer behind
        except Exception:
            pass
        raise
    return (layer, info)


def apply_reference_layers(content, layers, vid=None):
    """One reference layer (14.6 reference elements) per spec entry, each its own B.step:
    horizontalLine / verticalLine (value) and band (low, high), with color, dash, width, label,
    table, settings. Returns the created ReferenceLayers."""
    built = []
    layers = _coloring_list(layers)
    if not layers:
        return built
    vid = _coloring_vid(content, vid)
    if not hasattr(content, "Layers") or not hasattr(content.Layers, "AddNewReferenceLayer"):
        B.skip("referenceLayers", vid, content.GetType().Name + " has no reference layers"
               + " (bar, line, scatter, combination, box and waterfall charts do)")
        return built
    used = []
    for i in range(len(layers)):
        target = vid + "/referenceLayers[" + str(i) + "]"
        result = B.step("referenceLayer", target, _coloring_build_layer, (content, layers[i], used))
        if result is not None:
            built.append(result[0])
            info = result[1]
            info["index"] = i
            B.created.setdefault("referenceLayers", {}).setdefault(vid, []).append(info)
    return built


# ---- fitting models (Lines & Curves) ------------------------------------------------------------
def _coloring_build_model(content, mspec):
    kind = mspec.get("kind")
    models = content.FittingModels
    expression = None
    if kind == "straightLine":
        model = models.AddStraightLineFit()
        curve = model.Line
    elif kind == "curve":
        raw = _coloring_need(mspec, "expression", "curve")
        expression = _coloring_curve_expression(raw)
        try:
            model = models.AddCurve(expression)  # the setter validates; invalid text throws
        except Exception as first:
            # Not yet tested: which property form a curve accepts, DocumentProperty("X") or
            # ${X} (its validator maps property references by name; coloring note U11).
            alternative = _coloring_curve_fallback(raw)
            if alternative == expression:
                raise
            try:
                model = models.AddCurve(alternative)
            except Exception:
                raise first
            B.warn("curve '" + expression + "' was rejected; built as '" + alternative + "'")
            expression = alternative
        curve = model.Curve
    else:
        raise Exception("unknown fitting model kind: " + str(kind))
    label = mspec.get("label")
    if label:
        label = str(label)
    try:
        curve.Visible = True
        if mspec.get("color"):
            curve.Color = color(mspec["color"])
        if label:
            curve.CustomDisplayName = label
            for detail in curve.Details:
                if detail.Name == "Name":        # the line-name detail (GUI-built DXPs)
                    detail.ShowInLabel = True
        apply_settings(model, mspec.get("settings"))
    except Exception:
        try:
            models.Remove(model)
        except Exception:
            pass
        raise
    return (model, {"kind": kind, "expression": expression, "color": mspec.get("color"),
                    "label": label or None})


def apply_fitting_models(content, models, vid=None):
    """One fitting model per spec entry, each its own B.step: straightLine and curve (expression
    in x; [Axis.X] and [$Name] are translated), with color, label, settings. In 15.0 Spotfire adds
    a FittingModelLayer to content.Layers for each model by itself. Returns the created models."""
    built = []
    models = _coloring_list(models)
    if not models:
        return built
    vid = _coloring_vid(content, vid)
    if not hasattr(content, "FittingModels"):
        B.skip("fittingModels", vid, content.GetType().Name + " has no lines and curves")
        return built
    for i in range(len(models)):
        target = vid + "/fittingModels[" + str(i) + "]"
        result = B.step("fittingModel", target, _coloring_build_model, (content, models[i]))
        if result is not None:
            built.append(result[0])
            info = result[1]
            info["index"] = i
            B.created.setdefault("fittingModels", {}).setdefault(vid, []).append(info)
    return built
