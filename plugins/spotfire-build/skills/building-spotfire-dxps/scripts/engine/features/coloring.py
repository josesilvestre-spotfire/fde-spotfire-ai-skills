# Standard engine, feature part "coloring": the references/spec-format.md coloring
# object beyond the fixed and categorical chart colors of core
# (lib/65_coloring.py): gradients (breakpoints min, max, median, average,
# NN% of the range, numbers, expressions), rules (greaterThan, lessThan,
# between, equal, top, bottom, expression) above the background as
# Analyst inserts them, categorical colors with a one-color default
# palette and the empty color, a fixed color, the default color and the
# coloring's own settings. Used on chart color axes (line, bar, scatter:
# APP visual "coloring"), map layers (layer "coloring", builders/map.py),
# table and cross-table cells (APP "cellColors") and KPI tiles (the
# fourth element of a "kpis" item).
# APP coloring object (scripts/t3/_coloring.py): one background of
# "categorical" [[key, color], ...] (keys typed like the color-by column),
# "gradient" [[value, color], ...] or "fixed" color; "rules" [[type,
# color, value, ...], ...]; "default" color; "empty" color; "settings"
# {path: value} (features/settings.py, relative to the Coloring). Values:
# "min", "max", "median", "average", "NN%", a number (float = Real, int
# = Integer), True/False, any other text = an expression. Rule types:
# greaterThan / lessThan / equal (value), between (low, high), equalText
# (text, is-expression: a string rule), top / bottom (count), expression
# (Boolean expression). Colors '#RRGGBB', '#AARRGGBB' or '@name'.
# @api ColorAxis.Coloring; Coloring.Clear; Coloring.DefaultColor
# @api Coloring.EmptyColor; Coloring.Count; Coloring.Item; Coloring.Remove
# @api Coloring.AddCategoricalColorRule; Coloring.AddContinuousColorRule
# @api Coloring.SetColorForCategory(CategoryKey, Color)
# @api CategoricalColorRule.SetColors; ContinuousColorRule.IntervalMode
# @api ContinuousColorRule.Breakpoints; IntervalMode.Gradient
# @api ColorBreakpointCollection.Clear
# @api ColorBreakpointCollection.Add(ConditionValue, Color)
# @api ConditionValue.MinValue; ConditionValue.MaxValue
# @api ConditionValue.MedianValue; ConditionValue.AverageValue
# @api ConditionValue.CreatePercentValue(Double)
# @api ConditionValue.CreateLiteral(Object, DataType)
# @api ConditionValue.CreateLiteral(Object)
# @api ConditionValue.CreateExpression(String)
# @api Coloring.AddThresholdColorRule(RuleComparisonOperator, ConditionValue, Color)
# @api Coloring.AddRangeRule(ConditionValue, ConditionValue, Color)
# @api Coloring.AddStringColorRule(StringComparisonOperator, ConditionValue, Color)
# @api Coloring.AddTopNRule(Int32, Color); Coloring.AddBottomNRule(Int32, Color)
# @api Coloring.AddExpressionRule(String, Color); Coloring.IndexOf
# @api Coloring.Move; RuleComparisonOperator.Greater
# @api RuleComparisonOperator.Less; RuleComparisonOperator.Equal
# @api StringComparisonOperator.Equal; CategoryKey.ctor(Object[])
# @api DataType.Real; DataType.Integer; DataType.LongInteger
# @api Object.ReferenceEquals; CategoricalColorRule; ContinuousColorRule
# @set Coloring.DefaultColor; Coloring.EmptyColor
# @set ContinuousColorRule.IntervalMode
from System import Array, Object, Double, Int32, Int64
from System.Drawing import Color
from Spotfire.Dxp.Application.Visuals import CategoryKey
from Spotfire.Dxp.Application.Visuals.ConditionalColoring import (
    CategoricalColorRule, ContinuousColorRule, ConditionValue, IntervalMode,
    RuleComparisonOperator, StringComparisonOperator)
from Spotfire.Dxp.Data import DataType

# ------------------------------------------------------------ coloring
THRESHOLDS = {"greaterThan": "Greater", "lessThan": "Less",
              "equal": "Equal"}
BACKGROUND = ("categorical", "gradient", "fixed", "rules", "default")
STATICS = {"min": "MinValue", "max": "MaxValue", "median": "MedianValue",
           "average": "AverageValue"}


def argb(value):
    """'#RRGGBB', '#AARRGGBB' or '@name' -> System.Drawing.Color."""
    h = hexcode(value)
    if len(h) == 9:
        return Color.FromArgb(int(h[1:3], 16), int(h[3:5], 16),
                              int(h[5:7], 16), int(h[7:9], 16))
    return rgb(h)


def cond(value):
    """APP value -> ConditionValue (lib/65_coloring.py reading)."""
    if isinstance(value, bool):
        return ConditionValue.CreateLiteral(value)
    if isinstance(value, float):
        return ConditionValue.CreateLiteral(Double(value), DataType.Real)
    if isinstance(value, int):
        if -2147483648 <= value <= 2147483647:
            return ConditionValue.CreateLiteral(Int32(value),
                                                DataType.Integer)
        return ConditionValue.CreateLiteral(Int64(value),
                                            DataType.LongInteger)
    word = value.strip().lower()
    if word in STATICS:
        return getattr(ConditionValue, STATICS[word])
    if word.endswith("%"):
        try:
            return ConditionValue.CreatePercentValue(float(word[:-1]))
        except ValueError:
            pass
    return ConditionValue.CreateExpression(value)


def keep_one(coloring, categorical):
    """The first categorical (or continuous) rule, every other rule
    removed; reusing Spotfire's own rule keeps its palette."""
    kind = CategoricalColorRule if categorical else ContinuousColorRule
    keep = None
    for i in range(coloring.Count):
        if isinstance(coloring[i], kind):
            keep = coloring[i]
            break
    for i in range(coloring.Count - 1, -1, -1):
        rule = coloring[i]
        if keep is None or not Object.ReferenceEquals(rule, keep):
            coloring.Remove(rule)
    if keep is None:
        if categorical:
            keep = coloring.AddCategoricalColorRule()
        else:
            keep = coloring.AddContinuousColorRule()
    return keep


def background(coloring, spec, cell):
    """Background rule, default and empty colors. Table and cross-table
    cells without a default stay uncolored (transparent default)."""
    default = spec.get("default")
    if "categorical" in spec:
        rule = keep_one(coloring, True)
        if default:
            rule.SetColors(Array[Color]([argb(default)]))
        for key, c in spec["categorical"]:
            coloring.SetColorForCategory(CategoryKey(key), argb(c))
    elif "gradient" in spec:
        rule = keep_one(coloring, False)
        rule.IntervalMode = IntervalMode.Gradient
        rule.Breakpoints.Clear()
        for value, c in spec["gradient"]:
            rule.Breakpoints.Add(cond(value), argb(c))
    else:
        coloring.Clear()
    if "fixed" in spec:
        coloring.DefaultColor = argb(spec["fixed"])
    elif default:
        coloring.DefaultColor = argb(default)
    elif cell:
        coloring.DefaultColor = Color.FromArgb(0, 0, 0, 0)
    if spec.get("empty"):
        coloring.EmptyColor = argb(spec["empty"])


def add_rule(coloring, r, position):
    """One rule, moved to position (the first rule is the top one)."""
    kind, c = r[0], argb(r[1])
    if kind in THRESHOLDS:
        op = getattr(RuleComparisonOperator, THRESHOLDS[kind])
        rule = coloring.AddThresholdColorRule(op, cond(r[2]), c)
    elif kind == "between":
        rule = coloring.AddRangeRule(cond(r[2]), cond(r[3]), c)
    elif kind == "equalText":
        if r[3]:
            value = ConditionValue.CreateExpression(r[2])
        else:
            value = ConditionValue.CreateLiteral(r[2])
        rule = coloring.AddStringColorRule(StringComparisonOperator.Equal,
                                           value, c)
    elif kind == "top":
        rule = coloring.AddTopNRule(Int32(r[2]), c)
    elif kind == "bottom":
        rule = coloring.AddBottomNRule(Int32(r[2]), c)
    else:
        rule = coloring.AddExpressionRule(r[2], c)
    index = coloring.IndexOf(rule)
    if index != position:
        coloring.Move(index, position)
    return rule


def configure(name, coloring, spec, cell=False):
    """Background first, then each rule and each setting on its own (a
    coloring with settings only keeps its background)."""
    if [k for k in BACKGROUND if k in spec]:
        background(coloring, spec, cell)
    placed = 0
    for r in spec.get("rules", []):
        rule = ok(name + " rule " + r[0], add_rule, coloring, r, placed)
        if rule is not None:
            placed += 1
    # @feature settings
    for path in sorted(spec.get("settings", {})):
        ok(name + " setting " + path, set_setting, coloring, path,
           spec["settings"][path])
    # @endfeature


def axis_coloring(name, axis, spec):
    """A color axis whose expression is already set (it resets the
    rules when it changes)."""
    configure(name, axis.Coloring, spec)


# @feature cellColoring
# @api TablePlot.Colorings; CrossTablePlot.Colorings
# @api ColoringCollection.AddNew; ColoringCollection.AddMapping(CategoryKey, Coloring)
# @api ColoringCollection.DefaultNumericReference
# @set ColoringCollection.DefaultNumericReference
def cell_colorings(content, vs):
    for keys, spec in vs["cellColors"]:
        name = vs["id"] + ": cells " + (", ".join(keys) if keys
                                         else "(numeric)")
        ok(name, cell_coloring, name, content, keys, spec)


def cell_coloring(name, content, keys, spec):
    """keys: table column names or cross-table measure display names
    sharing one coloring; None = the default numeric coloring."""
    colorings = content.Colorings
    if keys:
        coloring = colorings.AddNew(", ".join(keys))
        for key in keys:
            colorings.AddMapping(CategoryKey(key), coloring)
    else:
        coloring = colorings.DefaultNumericReference
        if coloring is None:
            coloring = colorings.AddNew("Numeric")
            colorings.DefaultNumericReference = coloring
    configure(name, coloring, spec, True)
# @endfeature


# @feature kpiColoring
# @api KpiVisualization.ColorAxis; ColorAxis.Expression
# @set ColorAxis.Expression
def kpi_coloring(name, kpi, spec):
    """KPI tiles color by their final value (every corpus KPI)."""
    kpi.ColorAxis.Expression = "THEN [Y.FinalValue]"
    configure(name, kpi.ColorAxis.Coloring, spec)
# @endfeature
