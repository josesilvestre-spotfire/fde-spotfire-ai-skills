# ============================================================================
# 60_charts.py - chart visuals and their axes, plus vis_common (the common
# visual fields every visual builder applies last).
# IronPython 3.4 inside Spotfire Analyst 15.0 (Python 3.4 syntax: no f-strings,
# no walrus, no annotations, no print). Public API only; no internal members.
# Reference: references/api-charts.md. Members: lib/60_charts.members.txt
# (public), lib/60_charts.set.txt (assigned properties).
#
# Public functions (90_build.VISUAL_BUILDERS; each takes (page, vspec), returns the Visual):
#   vis_line, vis_bar, vis_combination, vis_scatter, vis_scatter3d, vis_pie, vis_box,
#   vis_heatmap, vis_treemap, vis_waterfall, vis_histogram
#   vis_common(visual, content, vspec)  title + showTitle, description, table, marking,
#       limitByMarkings + emptyMarkingBehavior, limitExpression, useFiltering, legend,
#       settings, postScript. Used by every visual module (70_tables, 75_maps, 80_textareas,
#       85_mods), so it skips what a content object does not have (text areas: Data, Legend,
#       Description) and never touches coloring, reference layers or fitting models.
#
# Build order of one chart:
#   1. B.table_or_default(table), the required fields and every expression: a missing table or
#      field fails the visual before it exists.
#   2. page.Visuals.AddNew(VisualTypeIdentifiers.X) -> Visual, .As[X]() -> content,
#      Data.DataTableReference = table (axis expressions resolve against it). AutoConfigure() is
#      never called: it picks columns and may overwrite axes. AddNew auto-places the visual;
#      50_pages applies the layout afterwards.
#   3. One B.step per axis, the trellis, each scale setting and each chart option.
#   4. colorBy + coloring (apply_coloring), then reference layers and fitting models where the
#      chart has them (line, bar, combination, scatter, box, waterfall, histogram) - 65_coloring.
#   5. vis_common last (settings and postScript see the finished chart), then a
#      IsConfigurationValid() check (warning only).
#   After AddNew nothing raises outside a B.step, so a failed part never loses the visual.
#   Report: B.created["charts"][id] (type, table, axes as set, options, scales, trellis, series,
#   valid) and B.created["visualSettings"][id] (what vis_common set), for verify_dxp.
#
# Spec interpretation owned by this module:
# - Expressions pass through as written. A bare column name of the visual's table becomes
#   [Name]; `[$Name]` becomes DocumentProperty("Name") (65_coloring's coloring_expression, so a
#   visual's axes, limit and reference layers read alike). A y list = several measures, ", ".
# - Categorical-only axes (lineBy, shapeBy, scatter lineBy, trellis, box x, heat-map x/y, pie
#   sector, waterfall category, treemap hierarchy) are wrapped in <...>; a list of levels is
#   nested outer first: ["[Station]", "[Pump ID]"] -> "<[Station] NEST [Pump ID]>". An x list
#   on the other charts is nested the same way.
# - A plain String or Boolean column, [Col] or a bare name, on an axis that takes both modes
#   (line/bar/combination/scatter x, colorBy) is written categorical, <[Col]>, with a warning:
#   those columns have no continuous scale (SPEC: the bar-chart x is a category). Numeric and
#   date/time columns keep the continuous form ([Timestamp]).
# - A categorical / gradient / rules coloring with no colorBy (and no Column Names default) is
#   warned: it has no values to color. fixed needs no colorBy.
# - Several measures and no colorBy -> colorBy "<[Axis.Default.Names]>" (Column Names, one
#   color per measure: the GUI and corpus pattern). The combination chart always defaults to it
#   (its color axis is the series axis).
# - A scale `title` becomes the axis expression's display name ("expr as [T]", "<expr as [T]>"):
#   Spotfire has no axis-title property. Impossible with several measures on one axis (warned).
# - individualScaling: mode Trellis on a trellised chart, else Color (one scale per color
#   category, or per measure under Column Names). secondaryScale: mode Dual, the matching series
#   on the Far (right) scale, every other series on the Near one.
# - Combination series without an alias get Spotfire's own name for an unaliased measure as
#   alias, the expression without identifier brackets (GUI-built DXPs: Sum([Baseline_HHP]) is keyed
#   "Sum(Baseline_HHP)"), so series-type and scale-dock keys are known exactly.
# - Bar sort: SortedBars (assumed largest first) and ascending through XAxis.Reversed;
#   horizontal bars get XAxis.Reversed = True like every GUI-built one (first category on top).
# - Treemap colorBy written as a category, <expr>, becomes UniqueConcatenate(expr): its color
#   axis is continuous-only (corpus pattern for categorical treemap colors).
# - 3D scatter: MarkerByAxis "<baserowid()>" (one marker per row; it aggregates otherwise).
#   The 2D scatter keeps Spotfire's marker-by: raw x/y give one marker per row (corpus);
#   "settings": {"MarkerByAxis.Expression": "<[Pump ID]>"} gives one marker per category.
# - histogram: a BarChart with X "BinByEvenIntervals(<column>, <bins>) as [<column>]" and
#   Y "Count()"; colorBy stacks it.
# - vis_common: a field present in vspec is applied (title "" is stored as "", not
#   ${AutoTitle}); absent fields take their SPEC defaults, except title (absent = untouched).
#
# Requires newer than 14.6: none (newest members: IndividualScalingMode.Dual [api 10.9],
# WaterfallChart [api 7.6]).
# Internal API: none.
# ============================================================================
from System import Object, Int32, Single, Double, DateTime
from Spotfire.Dxp.Application.Visuals import (VisualTypeIdentifiers, LineChart, BarChart,
                                              CombinationChart, ScatterPlot, ScatterPlot3D,
                                              PieChart, BoxPlot, HeatMap, Treemap, WaterfallChart,
                                              AxisRange, CategoryKey, AxisTransformType,
                                              IndividualScalingMode, ScaleDock, LabelVisibility,
                                              StackMode, BarChartOrientation,
                                              CombinationChartSeriesType, TrellisMode)
from Spotfire.Dxp.Data import LimitingMarkingsEmptyBehavior

_charts_names_axis = "<[Axis.Default.Names]>"      # (Column Names): one series per measure
_charts_row_axis = "<baserowid()>"                  # one marker per row, no aggregation
_charts_labels = {"all": "All", "marked": "Marked", "none": "None"}
_charts_stacks = {"stacked": "Stack", "sidebyside": "None", "percent": "Stack100Percent"}
_charts_sorts = ("none", "ascending", "descending")
_charts_empty_behaviors = ("ShowAll", "ShowEmpty", "ShowMessage")
_charts_layer_types = "line, bar, combination, scatter, box and waterfall charts and histograms"
_charts_category_types = ("String", "Boolean")      # DataType names without a continuous scale
_charts_value_colorings = ("categorical", "gradient", "rules")   # need a colorBy to color anything


# ---- spec values and expressions (pure Python, computed before AddNew) -------------------
def _charts_vid(vspec):
    return str(vspec.get("id") or "visual")


def _charts_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _charts_blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _charts_word(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _charts_text(value):
    """One spec expression value as text; numbers become culture-invariant literals."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return str(value).strip()


def _charts_props(text):
    """[$Name] -> DocumentProperty("Name"), through 65_coloring so a visual reads one way."""
    convert = globals().get("coloring_expression")
    if convert is None:
        return text
    return convert(text)


def _charts_column(text, table):
    """A bare column name of the visual's table -> [Name] (escaped); anything else unchanged."""
    if table is not None and text and text[0] not in "[<" and table.Columns.Contains(text):
        return esc(text)
    return text


def _charts_expr(value, table):
    """Axis expression: one expression, or a list of measures joined with ", "."""
    if isinstance(value, (list, tuple)):
        return ", ".join([_charts_expr(v, table) for v in value if not _charts_blank(v)])
    if value is None:
        return ""
    return _charts_props(_charts_column(_charts_text(value), table))


def _charts_unwrap(text):
    """The text inside an outer <...>, else the text."""
    t = text.strip()
    if len(t) >= 2 and t[0] == "<" and t[-1] == ">":
        return t[1:-1].strip()
    return t


def _charts_cat(value, table):
    """Categorical axis expression: <...> kept, a column or expression wrapped, a list of levels
    nested outer first; nothing -> "<>" (None)."""
    levels = []
    for item in _charts_list(value):
        if _charts_blank(item):
            continue
        inner = _charts_unwrap(_charts_text(item))
        if inner:
            levels.append(_charts_props(_charts_column(inner, table)))
    if not levels:
        return "<>"
    return "<" + " NEST ".join(levels) + ">"


def _charts_x(value, table, where):
    """X of line, bar, combination and scatter charts: an expression, or a list of levels. A plain
    String or Boolean column becomes the category axis (SPEC: the bar-chart x is a category)."""
    if isinstance(value, (list, tuple)):
        return _charts_cat(value, table)
    return _charts_category_column(_charts_expr(value, table), table, where)


def _charts_color_by(value, table, where):
    """colorBy: a list of levels -> <A NEST B>; one expression as written (<[Col]> colors by
    category, [Col] or an aggregation continuously), except that a plain String or Boolean column
    colors by category."""
    if isinstance(value, (list, tuple)):
        return _charts_cat(value, table)
    return _charts_category_column(_charts_expr(value, table), table, where)


def _charts_category_column(text, table, where):
    """A plain reference to a String or Boolean column, [Col] (also what a bare column name became),
    -> <[Col]>, warned. Such a column has no continuous scale, so the continuous form cannot draw on
    an axis that accepts both modes (bar/line/combination/scatter X, color). Anything else is
    returned unchanged."""
    if table is None or not text or text[0] != "[" or _charts_skip_ident(text, 0) != len(text):
        return text
    try:
        found, column = table.Columns.TryGetValue(text[1:-1].replace("]]", "]"))
        kind = str(column.DataType.Name) if found else ""
    except Exception:
        return text
    if kind not in _charts_category_types:
        return text
    B.warn(where + ": " + text + " is a " + kind + " column, so it is written as the category "
           "expression <" + text + ">; write <...> for categories in the spec")
    return "<" + text + ">"


def _charts_skip_ident(text, i):
    """Index after the [identifier] that starts at text[i] ("]]" inside is an escaped "]")."""
    n = len(text)
    j = i + 1
    while j < n:
        if text[j] == "]":
            if j + 1 < n and text[j + 1] == "]":
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _charts_skip_string(text, i):
    """Index after the string literal that starts at text[i] (doubled quote or backslash
    escapes inside)."""
    quote = text[i]
    n = len(text)
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            if j + 1 < n and text[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _charts_top_level(text):
    """[(index, char)] of the characters outside identifiers, string literals and parentheses."""
    out = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            i = _charts_skip_ident(text, i)
            continue
        if ch == '"' or ch == "'":
            i = _charts_skip_string(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            out.append((i, ch))
        i += 1
    return out


def _charts_split(text):
    """The measures of a multi-measure expression (top-level comma split)."""
    parts = []
    start = 0
    for i, ch in _charts_top_level(text):
        if ch == ",":
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _charts_count(expression):
    """Number of measures in an axis expression (0 for "" and "<>")."""
    return len(_charts_split(_charts_unwrap(expression or "")))


def _charts_alias(part):
    """(body, alias) of one measure: 'Sum([A]) as [Total A]' -> ('Sum([A])', 'Total A'); no
    alias -> (part, None). 'as' is case-insensitive; the alias is [bracketed] or one word."""
    n = len(part)
    found = None
    for i, ch in _charts_top_level(part):
        if ch not in "aA" or part[i:i + 2].lower() != "as":
            continue
        before = part[i - 1] if i > 0 else ""
        after = part[i + 2] if i + 2 < n else ""
        if before and (before.isspace() or before in ")]") and (after.isspace() or after == "["):
            found = i
    if found is None:
        return (part.strip(), None)
    rest = part[found + 2:].strip()
    if rest.startswith("[") and _charts_skip_ident(rest, 0) == len(rest):
        return (part[:found].strip(), rest[1:-1].replace("]]", "]"))
    if rest and (rest[0].isalpha() or rest[0] == "_") and all([c.isalnum() or c == "_" for c in rest]):
        return (part[:found].strip(), rest)
    return (part.strip(), None)


def _charts_display(body):
    """Spotfire's own display name of an unaliased measure: the expression without identifier
    brackets (GUI-built DXPs: Sum([Baseline_HHP]) is keyed "Sum(Baseline_HHP)")."""
    out = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "[":
            j = _charts_skip_ident(body, i)
            out.append(body[i + 1:max(i + 1, j - 1)].replace("]]", "]"))
            i = j
            continue
        if ch == '"' or ch == "'":
            j = _charts_skip_string(body, i)
            out.append(body[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _charts_titled(expression, title):
    """The axis expression with `title` as its display name (Spotfire shows the display name as
    the axis title and has no title property)."""
    text = expression.strip()
    wrapped = len(text) >= 2 and text[0] == "<" and text[-1] == ">"
    inner = text[1:-1].strip() if wrapped else text
    parts = _charts_split(inner)
    if not parts:
        raise Exception("the axis has no expression to title")
    if len(parts) > 1:
        raise Exception("the axis holds " + str(len(parts)) + " measures, whose names make up its "
                        "title; alias each measure instead")
    titled = _charts_alias(parts[0])[0] + " as " + esc(str(title))
    if wrapped:
        return "<" + titled + ">"
    return titled


def _charts_title(sspec):
    if isinstance(sspec, dict) and not _charts_blank(sspec.get("title")):
        return str(sspec.get("title"))
    return None


def _charts_norm(text):
    return " ".join(str(text).split())


def _charts_is_names(expression):
    """True for the (Column Names) axis expression."""
    return _charts_norm(_charts_unwrap(expression or "")) == "[Axis.Default.Names]"


def _charts_color_spec(vspec, table, default=None):
    """{id, colorBy, coloring} for apply_coloring: colorBy converted (bare names, [$Name], level
    lists, String/Boolean columns as categories), defaulting to `default` (Column Names for several
    measures). A categorical / gradient / rules coloring with nothing to color by is warned: it
    would color the color axis AddNew left (expected (None), one color for everything)."""
    vid = _charts_vid(vspec)
    coloring = vspec.get("coloring")
    spec = {"id": vid, "coloring": coloring}
    color_by = vspec.get("colorBy")
    if not _charts_blank(color_by):
        spec["colorBy"] = _charts_color_by(color_by, table, vid + "/colorBy")
    elif default is not None:
        spec["colorBy"] = default
    elif isinstance(coloring, dict):
        given = [k for k in _charts_value_colorings if not _charts_blank(coloring.get(k))]
        if given:
            B.warn(vid + ": coloring " + ", ".join(given) + " without colorBy has no values to color "
                   "(give colorBy, or use fixed for one color)")
    return spec


def _charts_multi_default(y):
    if _charts_count(y) > 1:
        return _charts_names_axis
    return None


def _charts_series(items, table, where):
    """Combination-chart series -> [{raw, expression (aliased), body, key, kind}]. Raises on a
    bad entry (before the visual exists)."""
    out = []
    keys = []
    for i in range(len(items)):
        item = items[i]
        label = where + "/series[" + str(i) + "]"
        if isinstance(item, dict):
            expression = item.get("expression")
            kind = item.get("kind") or "bar"
        else:
            expression = item
            kind = "bar"
        if _charts_blank(expression):
            raise Exception(label + " needs an expression")
        kind = _charts_word(kind)
        if kind not in ("bar", "line"):
            raise Exception(label + ': kind must be "bar" or "line", got ' + repr(kind))
        raw = _charts_expr(expression, table)
        parts = _charts_split(raw)
        if len(parts) != 1:
            raise Exception(label + " must hold one measure (give each measure its own series)")
        body, alias = _charts_alias(parts[0])
        if alias is None:
            alias = _charts_display(body)
            text = body + " as " + esc(alias)
        else:
            text = parts[0]
        if alias in keys:
            raise Exception(label + ": two series are named '" + alias + "'; alias them apart")
        keys.append(alias)
        out.append({"raw": raw, "expression": text, "body": body, "key": alias, "kind": kind})
    if not out:
        raise Exception(where + ": series is empty")
    return out


def _charts_match_secondary(entries, series, table, where):
    """Keys of the series named by secondaryScale entries (an entry is a series expression, with
    or without its alias, or the alias alone). Unmatched entries are warned."""
    right = []
    for entry in _charts_list(entries):
        if _charts_blank(entry):
            continue
        text = _charts_expr(entry, table)
        body, alias = _charts_alias(text)
        wanted = set([_charts_norm(text), _charts_norm(body)])
        if alias is not None:
            wanted.add(_charts_norm(alias))
        hit = None
        for s in series:
            names = set([_charts_norm(s["raw"]), _charts_norm(s["expression"]),
                         _charts_norm(s["body"]), _charts_norm(s["key"])])
            if wanted & names:
                hit = s
                break
        if hit is None:
            B.warn(where + ": secondaryScale entry " + text + " matches no series; it is not moved "
                   "to the right scale")
        elif hit["key"] not in right:
            right.append(hit["key"])
    return right


def _charts_bins_x(column, bins, table):
    """Histogram X: BinByEvenIntervals over the column, aliased with the column name."""
    text = _charts_text(column)
    name = None
    if table is not None and text and text[0] not in "[<" and table.Columns.Contains(text):
        name = text
    elif text.startswith("[") and _charts_skip_ident(text, 0) == len(text):
        name = text[1:-1].replace("]]", "]")
    expression = "BinByEvenIntervals(" + _charts_expr(column, table) + ", " + str(bins) + ")"
    if name:
        expression += " as " + esc(name)
    return expression


# ---- small step bodies (every conversion that can fail runs inside a B.step) -------------
def _charts_fail(message):
    raise Exception(message)


def _charts_read(getter):
    try:
        return getter()
    except Exception:
        return None


def _charts_has(obj, name):
    try:
        return hasattr(obj, name)
    except Exception:
        return False


def _charts_kind(content):
    try:
        return str(content.GetType().Name)
    except Exception:
        return "visual"


def _charts_call(name, args):
    """A function of another lib module, looked up when the step runs (a missing module fails
    this step, not the visual)."""
    fn = globals().get(name)
    if fn is None:
        raise Exception(name + " is not in the builder (lib module missing)")
    return fn(*args)


def _charts_number(value, low, high, what, where):
    """A spec number clamped to Spotfire's documented range (warned when it had to move)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Exception(what + " must be a number, got " + repr(value))
    clamped = max(low, min(high, value))
    if clamped != value:
        B.warn(where + ": " + what + " " + repr(value) + " is outside " + repr(low) + ".."
               + repr(high) + "; " + repr(clamped) + " is used")
    return clamped


def _charts_set_flag(obj, prop, value):
    flag = bool(value)
    setattr(obj, prop, flag)
    return flag


def _charts_set_line_width(content, value, where):
    width = int(_charts_number(value, 1, 10, "lineWidth", where))     # pixels, 1-10 (DOC)
    content.LineWidth = Int32(width)
    return width


def _charts_set_marker_size(content, value, where):
    size = float(_charts_number(value, 0, 100, "markerSize", where))  # % of the plot (DOC)
    content.MarkerSize = Single(size)
    return size


def _charts_set_labels(obj, value):
    if isinstance(value, bool):
        name = "All" if value else "None"
    else:
        name = _charts_labels.get(_charts_word(value))
        if name is None:
            raise Exception('labels must be true, false, "all", "marked" or "none", got ' + repr(value))
    # Not yet tested U8: enum_value's getattr(LabelVisibility, "None") (a Python 3 keyword member).
    obj.LabelVisibility = enum_value(LabelVisibility, name)
    return name


def _charts_set_orientation(content, value):
    key = _charts_word(value)
    if key not in ("vertical", "horizontal"):
        raise Exception('orientation must be "vertical" or "horizontal", got ' + repr(value))
    if key == "horizontal":
        content.Orientation = BarChartOrientation.Horizontal
    else:
        content.Orientation = BarChartOrientation.Vertical
    return key


def _charts_set_stack(content, value):
    name = _charts_stacks.get(_charts_word(value))
    if name is None:
        raise Exception('stack must be "stacked", "sideBySide" or "percent", got ' + repr(value))
    # StackMode.None = side by side; Not yet tested U8 (getattr of the member named None).
    content.StackMode = enum_value(StackMode, name)
    return str(value)


def _charts_set_sort(content, value):
    key = _charts_word(value)
    if key not in _charts_sorts:
        raise Exception('sort must be "none", "ascending" or "descending", got ' + repr(value))
    content.SortedBars = key != "none"                         # categorical X only (DOC)
    return key


def _charts_set_bar_order(content, horizontal, ascending):
    # Not yet tested U3: SortedBars puts the largest bar first, and Orientation = Horizontal does
    # not reverse the category axis by itself. Every GUI-built horizontal bar chart persists
    # X.Reversed true (first category on top, GUI-built DXPs 4/4); ascending = that order reversed.
    flag = bool(horizontal) != bool(ascending)
    content.XAxis.Reversed = flag
    return flag


def _charts_hide_dendrograms(content):
    # Not yet tested U13: a new heat map's dendrogram visibility (GUI heat maps persist hidden).
    content.RowDendrogram.Visible = False
    content.ColumnDendrogram.Visible = False
    return False


def _charts_series_type(kind):
    if kind == "line":
        return CombinationChartSeriesType.Line
    return CombinationChartSeriesType.Bar


def _charts_set_series_types(content, series, keyed):
    """SeriesType = the majority kind; with the Column Names series axis every series gets its
    own type, keyed by its display name."""
    kinds = [s["kind"] for s in series]
    default = "line" if kinds.count("line") > kinds.count("bar") else "bar"
    content.SeriesType = _charts_series_type(default)
    if not keyed:
        return {"*": default}
    indexed = content.IndexedSeriesType
    done = {}
    for s in series:
        # Not yet tested U21: indexer assignment with CategoryKey(<measure display name>).
        indexed[CategoryKey(s["key"])] = _charts_series_type(s["kind"])
        done[s["key"]] = s["kind"]
    return done


def _charts_set_secondary(axis, series, right):
    # Not yet tested U4: Dual mode plus Scale.IndexedDock[key] = Far gives exactly one left and
    # one right Y scale (no corpus chart uses dual scales).
    axis.IndividualScaling = True
    axis.IndividualScalingMode = IndividualScalingMode.Dual
    dock = axis.Scale.IndexedDock
    for s in series:
        if s["key"] in right:
            dock[CategoryKey(s["key"])] = ScaleDock.Far
        else:
            dock[CategoryKey(s["key"])] = ScaleDock.Near
    return list(right)


def _charts_bound(value, categorical):
    """AxisRange end: None = automatic; numbers stay numbers (indices on a categorical axis,
    Double on a continuous one); text = an ISO date/time."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise Exception("a scale min/max cannot be true or false")
    if isinstance(value, (int, float)):
        if categorical:
            return Int32(int(value))
        return Double(float(value))
    # Not yet tested U24: AxisRange with DateTime ends on a date/time axis.
    return DateTime.Parse(str(value), INVARIANT)


def _charts_set_range(axis, low, high):
    categorical = str(axis.Expression or "").strip().startswith("<")
    axis.Range = AxisRange(_charts_bound(low, categorical), _charts_bound(high, categorical))
    return True


def _charts_set_log(axis):
    axis.TransformType = AxisTransformType.Log10
    return True


def _charts_set_gridlines(axis, value):
    axis.Scale.ShowGridlines = bool(value)          # on the Scale, not the axis (pitfall 2)
    return True


def _charts_set_individual(axis, trellised):
    axis.IndividualScaling = True
    if trellised:
        axis.IndividualScalingMode = IndividualScalingMode.Trellis
        return "Trellis"
    axis.IndividualScalingMode = IndividualScalingMode.Color
    return "Color"


def _charts_set_axis(axis, expression, title, where):
    """Set one axis expression; a scale title is folded in as the display name."""
    final = expression
    if not _charts_blank(title):
        try:
            final = _charts_titled(expression, title)
        except Exception as e:
            B.warn(where + ": scale title '" + str(title) + "' not applied: " + exc_text(e))
            final = expression
    if final != expression:
        try:
            axis.Expression = final
            return final
        except Exception as e:
            # Not yet tested: an alias on a nested categorical axis (<[A] NEST [B] as [T]>), and
            # whether the Expression setter throws on an invalid expression at all.
            B.warn(where + ": Spotfire rejected the titled expression " + final + " ("
                   + exc_text(e) + "); the axis is set without the title")
    axis.Expression = expression
    return expression


def _charts_set_trellis(trellis, tspec, table, where):
    panel = tspec.get("panelBy")
    rows_by = tspec.get("rowsBy")
    columns_by = tspec.get("columnsBy")
    rows = tspec.get("rows")
    columns = tspec.get("columns")
    if not _charts_blank(panel):
        if not _charts_blank(rows_by) or not _charts_blank(columns_by):
            raise Exception("trellis: give panelBy, or rowsBy/columnsBy, not both")
        record = {"mode": "Panels", "panelBy": _charts_cat(panel, table)}
        trellis.TrellisMode = TrellisMode.Panels
        trellis.PanelAxis.Expression = record["panelBy"]
        if rows is not None:
            record["rows"] = int(_charts_number(rows, 1, 1000, "trellis rows", where))
            trellis.ManualRowCount = Int32(record["rows"])
        if columns is not None:
            record["columns"] = int(_charts_number(columns, 1, 1000, "trellis columns", where))
            trellis.ManualColumnCount = Int32(record["columns"])
        if rows is not None or columns is not None:
            trellis.ManualLayout = True             # a count also sets it (DOC); explicit anyway
        return record
    if _charts_blank(rows_by) and _charts_blank(columns_by):
        raise Exception("trellis needs panelBy, or rowsBy and/or columnsBy")
    record = {"mode": "RowsColumns"}
    trellis.TrellisMode = TrellisMode.RowsColumns
    if not _charts_blank(rows_by):
        record["rowsBy"] = _charts_cat(rows_by, table)
        trellis.RowAxis.Expression = record["rowsBy"]
    if not _charts_blank(columns_by):
        record["columnsBy"] = _charts_cat(columns_by, table)
        trellis.ColumnAxis.Expression = record["columnsBy"]
    if rows is not None or columns is not None:
        B.warn(where + ": trellis rows/columns apply to panelBy only (rows and columns of a "
               "rowsBy/columnsBy trellis come from its categories); ignored")
    return record


# ---- per-part steps -------------------------------------------------------------------------
def _charts_start(vspec, required):
    """Table and required fields, checked before the visual exists. Returns the DataTable."""
    missing = [key for key in required if _charts_blank(vspec.get(key))]
    if missing:
        raise Exception(str(vspec.get("type")) + " '" + _charts_vid(vspec) + "' needs "
                        + ", ".join(missing))
    return B.table_or_default(vspec.get("table"))


def _charts_new(page, vspec, table, type_id, content_class):
    """AddNew(type id) -> (Visual, content, report entry). The table is bound at once: axis
    expressions resolve against it. AutoConfigure is not called (U2)."""
    # Not yet tested U1: axes the spec leaves out keep what AddNew gives them (expected "<>" or
    # empty: color with one measure, line-by, 2D marker-by, size, shape, trellis).
    visual = page.Visuals.AddNew(type_id)
    content = visual.As[content_class]()
    if content is None:
        raise Exception("visual.As[" + content_class.__name__ + "]() returned nothing")
    content.Data.DataTableReference = table
    info = {"type": vspec.get("type"), "table": str(table.Name), "axes": {}, "options": {},
            "scales": {}, "trellis": None}
    B.created.setdefault("charts", {})[_charts_vid(vspec)] = info
    return (visual, content, info)


def _charts_axis(vid, info, name, axis, expression, title=None):
    """One axis expression in its own step, recorded in info["axes"][name]."""
    where = vid + "/" + name
    done = B.step("chart.axis", where, _charts_set_axis, (axis, expression, title, where))
    if done is not None:
        info["axes"][name] = done
    return done


def _charts_option(vid, info, label, fn, args):
    """One chart option in its own step, recorded in info["options"][label]."""
    done = B.step("chart.option", vid + "/" + label, fn, args)
    if done is not None:
        info["options"][label] = done
    return done


def _charts_trellis(vid, info, content, tspec, table):
    """Trellis in its own step. Returns True when the spec asks for one (individualScaling)."""
    if _charts_blank(tspec):
        return False
    if not isinstance(tspec, dict):
        B.step("chart.trellis", vid, _charts_fail, ("trellis must be an object",))
        return False
    record = B.step("chart.trellis", vid, _charts_set_trellis, (content.Trellis, tspec, table, vid))
    if record is not None:
        info["trellis"] = record
    return True


def _charts_scale(vid, info, name, axis, sspec, trellised):
    """min/max, log, gridlines and individualScaling of one axis, each in its own step. The
    scale title belongs to the axis expression (_charts_set_axis)."""
    if _charts_blank(sspec):
        return
    target = vid + "/" + name + "Scale"
    if not isinstance(sspec, dict):
        B.step("chart.scale", target, _charts_fail, ("a scale must be an object",))
        return
    record = info["scales"].setdefault(name, {})
    low = sspec.get("min")
    high = sspec.get("max")
    if low is not None or high is not None:
        if B.step("chart.scale.range", target, _charts_set_range, (axis, low, high)):
            record["min"] = low
            record["max"] = high
    if sspec.get("log"):
        if B.step("chart.scale.log", target, _charts_set_log, (axis,)):
            record["log"] = True
    if sspec.get("gridlines") is not None:
        if B.step("chart.scale.gridlines", target, _charts_set_gridlines, (axis, sspec["gridlines"])):
            record["gridlines"] = bool(sspec["gridlines"])
    if sspec.get("individualScaling"):
        mode = B.step("chart.scale.individualScaling", target, _charts_set_individual,
                      (axis, trellised))
        if mode:
            record["individualScaling"] = mode
    title = _charts_title(sspec)
    if title is not None and _charts_titled_ok(info["axes"].get(name), title):
        record["title"] = title


def _charts_titled_ok(expression, title):
    """True when the axis expression set carries `title` as its display name."""
    if not expression or _charts_count(expression) != 1:
        return False
    return _charts_alias(_charts_split(_charts_unwrap(expression))[0])[1] == title


def _charts_scales(vid, info, content, vspec, trellised, names):
    """The scales of `names` (X, Y, Z) that the spec gives as xScale / yScale / zScale."""
    for name in names:
        _charts_scale(vid, info, name, getattr(content, name + "Axis"),
                      vspec.get(name.lower() + "Scale"), trellised)


def _charts_coloring(vid, info, content, cspec):
    """colorBy + coloring through 65_coloring (its own steps), wrapped in one more step."""
    if cspec.get("colorBy") is None and not cspec.get("coloring"):
        return
    B.step("chart.coloring", vid, _charts_call, ("apply_coloring", (content, cspec)))
    if _charts_has(content, "ColorAxis"):
        shown = _charts_read(lambda: str(content.ColorAxis.Expression))
        if shown is not None:
            info["axes"]["Color"] = shown


def _charts_check(content, vid, info):
    # Not yet tested U14: what IsConfigurationValid() reports for a fresh, fully configured chart.
    valid = bool(content.IsConfigurationValid())
    info["valid"] = valid
    if not valid:
        B.warn("visual '" + vid + "': Spotfire reports the chart configuration as not valid; check "
               "its expressions against the columns of table " + str(info.get("table")))
    return valid


def _charts_complete(visual, content, vspec, info, layers):
    """Reference layers and fitting models (where the chart has them), vis_common, check."""
    vid = _charts_vid(vspec)
    refs = _charts_list(vspec.get("referenceLayers"))
    models = _charts_list(vspec.get("fittingModels"))
    if layers:
        if refs:
            B.step("chart.referenceLayers", vid, _charts_call,
                   ("apply_reference_layers", (content, refs, vid)))
        if models:
            B.step("chart.fittingModels", vid, _charts_call,
                   ("apply_fitting_models", (content, models, vid)))
    else:
        if refs:
            B.skip("chart.referenceLayers", vid, str(info.get("type")) + " has no reference layers ("
                   + _charts_layer_types + " do)")
        if models:
            B.skip("chart.fittingModels", vid, str(info.get("type")) + " has no lines and curves ("
                   + _charts_layer_types + " do)")
    B.step("chart.common", vid, vis_common, (visual, content, vspec))
    B.step("chart.check", vid, _charts_check, (content, vid, info))
    return visual


# ---- vis_common ---------------------------------------------------------------------------
def _charts_visual_of(obj):
    """The Visual for a Visual or a content object (content carries it in .Visual)."""
    inner = _charts_read(lambda: obj.Visual)
    if inner is None:
        return obj
    return inner


def _charts_set_title(visual, title, show):
    if title is not None:
        # A preprocessor expression: ${...} is live, \${ a literal.
        # Not yet tested: "" is persisted as an empty title (TitleExpression "").
        visual.Title = str(title)
    visual.ShowTitle = bool(show)
    return True


def _charts_set_description(content, text):
    content.Description = str(text)       # persisted as DescriptionExpression (preprocessor)
    # Not yet tested: how Analyst 15.0 shows the description with ShowDescription True.
    content.ShowDescription = True
    return True


def _charts_set_table(content, name):
    table = B.table_or_default(name)
    data = content.Data
    current = data.DataTableReference
    # Only when it differs: re-assigning the same table is never needed.
    if current is None or not Object.ReferenceEquals(current, table):
        data.DataTableReference = table
    return str(table.Name)


def _charts_set_marking(content, spec):
    if "marking" in spec:
        name = spec.get("marking")
        marking = None if name is None else B.marking(name)
    else:
        marking = B.doc.Data.Markings.DefaultMarkingReference
        name = None if marking is None else marking.Name
    content.Data.MarkingReference = marking     # None = the visual cannot be marked (DOC)
    return "" if name is None else str(name)


def _charts_add_limit(content, name):
    marking = B.marking(name)
    filterings = content.Data.Filterings
    if not filterings.Contains(marking):
        filterings.Add(marking)                 # limit the data by this marking
    return True


def _charts_set_empty(content, behavior):
    name = str(behavior).strip()
    if name not in _charts_empty_behaviors:
        raise Exception("emptyMarkingBehavior must be ShowAll, ShowEmpty or ShowMessage, got "
                        + repr(behavior))
    content.Data.LimitingMarkingsEmptyBehavior = enum_value(LimitingMarkingsEmptyBehavior, name)
    return name


def _charts_set_where(content, expression):
    text = _charts_props(_charts_text(expression))
    content.Data.WhereClauseExpression = text   # a boolean expression; "" would clear it (DOC)
    return text


def _charts_legend_visible(legend):
    if isinstance(legend, dict):
        return bool(legend.get("visible", True))
    if legend is None:
        return True
    return bool(legend)


def _charts_set_legend(content, visible):
    content.Legend.Visible = bool(visible)
    return bool(visible)


def _charts_settings(content, settings):
    apply_settings(content, settings)
    return True


def _charts_post(visual, content, code):
    run_post_script(code, {"visual": visual, "content": content})
    return True


def _charts_common_data(vid, content, spec, record):
    """table, marking, limitByMarkings + emptyMarkingBehavior, limitExpression, useFiltering."""
    done = B.step("visual.table", vid, _charts_set_table, (content, spec.get("table")))
    if done is not None:
        record["table"] = done
    done = B.step("visual.marking", vid, _charts_set_marking, (content, spec))
    if done is not None:
        record["marking"] = done or None
    names = [n for n in _charts_list(spec.get("limitByMarkings")) if not _charts_blank(n)]
    if names:
        limited = []
        for name in names:
            if B.step("visual.limitByMarking", vid + "/" + str(name), _charts_add_limit,
                      (content, name)):
                limited.append(str(name))
        record["limitByMarkings"] = limited
        behavior = spec.get("emptyMarkingBehavior") or "ShowAll"
        done = B.step("visual.emptyMarkingBehavior", vid, _charts_set_empty, (content, behavior))
        if done is not None:
            record["emptyMarkingBehavior"] = done
        if record.get("marking") and record.get("marking") in limited:
            B.warn("visual '" + vid + "' is limited by its own marking '" + record["marking"]
                   + "', so it cannot be marked; give detail visuals another marking")
    expression = spec.get("limitExpression")
    if not _charts_blank(expression):
        done = B.step("visual.limitExpression", vid, _charts_set_where, (content, expression))
        if done is not None:
            record["limitExpression"] = done
    use = spec.get("useFiltering", True)
    if use is not None and not bool(use):
        if B.step("visual.useFiltering", vid, _charts_set_flag,
                  (content.Data, "UseActiveFiltering", False)) is not None:
            record["useFiltering"] = False
    else:
        record["useFiltering"] = True     # the default; the page's filtering scheme is 50_pages'


def vis_common(visual, content, vspec):
    """The SPEC common visual fields, each in its own B.step, in this order: title + showTitle,
    description, table, marking, limitByMarkings + emptyMarkingBehavior, limitExpression,
    useFiltering, legend, settings, postScript (last, so they see the finished visual).

    Fields present in vspec are applied (title "" is stored as ""); absent fields take their SPEC
    defaults, except title (absent = left as is) and marking (absent = the document's default
    marking; present and None = cannot be marked). What the content lacks (a text area has no
    Data, Legend or Description) is skipped. Coloring, reference layers and fitting models are
    the visual builders' job. Records B.created["visualSettings"][id]. Returns the Visual.
    """
    spec = vspec or {}
    vid = _charts_vid(spec)
    visual = _charts_visual_of(visual)
    record = {}
    B.created.setdefault("visualSettings", {})[vid] = record

    title = spec.get("title")
    show = spec.get("showTitle", True)
    if B.step("visual.title", vid, _charts_set_title, (visual, title, show)):
        record["showTitle"] = bool(show)
        if title is not None:
            record["title"] = str(title)

    description = spec.get("description")
    if not _charts_blank(description):
        if _charts_has(content, "Description"):
            if B.step("visual.description", vid, _charts_set_description, (content, description)):
                record["description"] = str(description)
        else:
            B.warn("visual '" + vid + "': a " + _charts_kind(content) + " has no description; "
                   "'description' was not stored")

    if _charts_has(content, "Data"):
        _charts_common_data(vid, content, spec, record)

    if _charts_has(content, "Legend"):
        visible = _charts_legend_visible(spec.get("legend", {"visible": True}))
        if B.step("visual.legend", vid, _charts_set_legend, (content, visible)) is not None:
            record["legend"] = {"visible": visible}

    settings = spec.get("settings")
    if settings:
        if B.step("visual.settings", vid, _charts_settings, (content, settings)):
            record["settings"] = sorted(settings.keys())

    code = spec.get("postScript")
    if code:
        if B.step("visual.postScript", vid, _charts_post, (visual, content, code)):
            record["postScript"] = True
    return visual


# ---- chart builders -------------------------------------------------------------------------
def vis_line(page, vspec):
    """Line chart: x, y (one or several measures), colorBy, lineBy, trellis, xScale, yScale,
    showMarkers, lineWidth, steps; coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("x", "y"))
    vid = _charts_vid(vspec)
    x = _charts_x(vspec.get("x"), table, vid + "/x")
    y = _charts_expr(vspec.get("y"), table)
    line_by = None
    if not _charts_blank(vspec.get("lineBy")):
        line_by = _charts_cat(vspec.get("lineBy"), table)
    cspec = _charts_color_spec(vspec, table, _charts_multi_default(y))
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.LineChart, LineChart)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    if line_by is not None:
        _charts_axis(vid, info, "Line", content.LineByAxis, line_by)
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    if vspec.get("showMarkers") is not None:
        _charts_option(vid, info, "showMarkers", _charts_set_flag,
                       (content, "ShowMarkers", vspec.get("showMarkers")))
    if vspec.get("lineWidth") is not None:
        _charts_option(vid, info, "lineWidth", _charts_set_line_width,
                       (content, vspec.get("lineWidth"), vid))
    if vspec.get("steps") is not None:
        _charts_option(vid, info, "steps", _charts_set_flag,
                       (content, "SteppedLines", vspec.get("steps")))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)


def _charts_bar_layout(vid, info, content, vspec):
    """orientation, stack, sort and the category-axis direction they imply."""
    orientation = vspec.get("orientation")
    sort = vspec.get("sort")
    if not _charts_blank(orientation):
        _charts_option(vid, info, "orientation", _charts_set_orientation, (content, orientation))
    if not _charts_blank(vspec.get("stack")):
        _charts_option(vid, info, "stack", _charts_set_stack, (content, vspec.get("stack")))
    if not _charts_blank(sort):
        _charts_option(vid, info, "sort", _charts_set_sort, (content, sort))
    if not _charts_blank(orientation) or _charts_word(sort) in ("ascending", "descending"):
        _charts_option(vid, info, "xReversed", _charts_set_bar_order,
                       (content, _charts_word(orientation) == "horizontal",
                        _charts_word(sort) == "ascending"))


def vis_bar(page, vspec):
    """Bar chart: x (category), y (one or several measures), colorBy, orientation, stack, sort,
    labels, trellis, yScale (xScale too); coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("x", "y"))
    vid = _charts_vid(vspec)
    x = _charts_x(vspec.get("x"), table, vid + "/x")
    y = _charts_expr(vspec.get("y"), table)
    cspec = _charts_color_spec(vspec, table, _charts_multi_default(y))
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.BarChart, BarChart)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    _charts_bar_layout(vid, info, content, vspec)
    if vspec.get("labels") is not None:
        _charts_option(vid, info, "labels", _charts_set_labels, (content, vspec.get("labels")))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)


def vis_histogram(page, vspec):
    """Histogram: a bar chart on BinByEvenIntervals(column, bins) (default 20 bins) counting
    rows; colorBy stacks it. Also: trellis, xScale, yScale, labels; reference layers, fits."""
    table = _charts_start(vspec, ("column",))
    vid = _charts_vid(vspec)
    bins = vspec.get("bins")
    if bins is None:
        bins = 20
    if isinstance(bins, bool) or not isinstance(bins, (int, float)) or int(bins) < 1:
        raise Exception("histogram '" + vid + "': bins must be a whole number >= 1, got " + repr(bins))
    # Not yet tested U11: one bar per bin, filling it, for BinByEvenIntervals without <>.
    x = _charts_bins_x(vspec.get("column"), int(bins), table)
    cspec = _charts_color_spec(vspec, table)
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.BarChart, BarChart)
    info["bins"] = int(bins)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, "Count()", _charts_title(vspec.get("yScale")))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    if vspec.get("labels") is not None:
        _charts_option(vid, info, "labels", _charts_set_labels, (content, vspec.get("labels")))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)


def vis_combination(page, vspec):
    """Combination chart: x, series [{expression, kind: bar|line}], colorBy (the series axis,
    default Column Names), secondaryScale (series on the right scale), trellis, xScale, yScale;
    coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("x", "series"))
    vid = _charts_vid(vspec)
    x = _charts_x(vspec.get("x"), table, vid + "/x")
    series = _charts_series(_charts_list(vspec.get("series")), table, vid)
    y = ", ".join([s["expression"] for s in series])
    cspec = _charts_color_spec(vspec, table, _charts_names_axis)
    keyed = _charts_is_names(cspec.get("colorBy"))
    right = []
    if not _charts_blank(vspec.get("secondaryScale")):
        if keyed:
            right = _charts_match_secondary(vspec.get("secondaryScale"), series, table, vid)
        else:
            B.warn(vid + ": secondaryScale needs the Column Names series axis; with colorBy "
                   + cspec.get("colorBy") + " the series are its categories, so every series "
                   "stays on one scale")
    if not keyed and len(set([s["kind"] for s in series])) > 1:
        B.warn(vid + ": bar/line per series needs the Column Names series axis; with colorBy "
               + cspec.get("colorBy") + " every series gets the majority kind")
    y_scale = vspec.get("yScale")
    if _charts_title(y_scale) is not None:
        # the series aliases are the series-type and scale-dock keys: never replace them
        B.warn(vid + ": a combination chart's Y axis is titled by its series names; yScale.title '"
               + _charts_title(y_scale) + "' is not applied")
        y_scale = dict(y_scale)
        y_scale.pop("title", None)
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.CombinationChart,
                                        CombinationChart)
    info["series"] = [{"expression": s["expression"], "key": s["key"], "kind": s["kind"]}
                      for s in series]
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y)
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scale(vid, info, "X", content.XAxis, vspec.get("xScale"), trellised)
    _charts_scale(vid, info, "Y", content.YAxis, y_scale, trellised)
    # the series axis first: series types and scale docks are keyed by its categories
    _charts_coloring(vid, info, content, cspec)
    _charts_option(vid, info, "seriesTypes", _charts_set_series_types, (content, series, keyed))
    if right:
        _charts_option(vid, info, "secondaryScale", _charts_set_secondary,
                       (content.YAxis, series, right))
    return _charts_complete(visual, content, vspec, info, True)


def vis_scatter(page, vspec):
    """Scatter plot: x, y, colorBy, sizeBy, shapeBy, labelBy (+ labels), markerSize, lineBy
    (connect markers), trellis, xScale, yScale; coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("x", "y"))
    vid = _charts_vid(vspec)
    x = _charts_x(vspec.get("x"), table, vid + "/x")
    y = _charts_expr(vspec.get("y"), table)
    size = None
    if not _charts_blank(vspec.get("sizeBy")):
        size = _charts_expr(vspec.get("sizeBy"), table)
    shape = None
    if not _charts_blank(vspec.get("shapeBy")):
        shape = _charts_cat(vspec.get("shapeBy"), table)
    label = None
    if not _charts_blank(vspec.get("labelBy")):
        label = _charts_expr(vspec.get("labelBy"), table)
    line = None
    if not _charts_blank(vspec.get("lineBy")):
        line = _charts_cat(vspec.get("lineBy"), table)
    cspec = _charts_color_spec(vspec, table, _charts_multi_default(y))
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.ScatterPlot,
                                        ScatterPlot)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    if size is not None:
        _charts_axis(vid, info, "Size", content.SizeAxis, size)
    if shape is not None:
        _charts_axis(vid, info, "Shape", content.ShapeAxis, shape)
    if label is not None:
        _charts_axis(vid, info, "Label", content.LabelColumn, label)
    labels = vspec.get("labels")
    if labels is not None or label is not None:
        # labelBy shows labels on every marker unless `labels` says otherwise
        _charts_option(vid, info, "labels", _charts_set_labels,
                       (content, True if labels is None else labels))
    if line is not None:
        # Not yet tested: lines follow the X order with OrderAxis left empty, as in the corpus.
        _charts_axis(vid, info, "LineConnection", content.LineConnection.ConnectionAxis, line)
    if vspec.get("markerSize") is not None:
        _charts_option(vid, info, "markerSize", _charts_set_marker_size,
                       (content, vspec.get("markerSize"), vid))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)


def vis_scatter3d(page, vspec):
    """3D scatter plot: x, y, z, colorBy, sizeBy (also trellis, xScale, yScale, zScale), one
    marker per row."""
    table = _charts_start(vspec, ("x", "y", "z"))
    vid = _charts_vid(vspec)
    x = _charts_expr(vspec.get("x"), table)
    y = _charts_expr(vspec.get("y"), table)
    z = _charts_expr(vspec.get("z"), table)
    size = None
    if not _charts_blank(vspec.get("sizeBy")):
        size = _charts_expr(vspec.get("sizeBy"), table)
    cspec = _charts_color_spec(vspec, table)
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.ScatterPlot3D,
                                        ScatterPlot3D)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    _charts_axis(vid, info, "Z", content.ZAxis, z, _charts_title(vspec.get("zScale")))
    # one marker per row: the 3D plot aggregates markers otherwise (DOC, GUI-built DXPs 2/2)
    _charts_axis(vid, info, "Marker", content.MarkerByAxis, _charts_row_axis)
    if size is not None:
        _charts_axis(vid, info, "Size", content.SizeAxis, size)
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y", "Z"))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, False)


def vis_pie(page, vspec):
    """Pie chart: sector (category, on the color axis), size (sector size), labels, trellis;
    coloring colors the sectors."""
    table = _charts_start(vspec, ("sector", "size"))
    vid = _charts_vid(vspec)
    sector = _charts_cat(vspec.get("sector"), table)
    size = _charts_expr(vspec.get("size"), table)
    if not _charts_blank(vspec.get("colorBy")):
        B.warn(vid + ": a pie chart's colors are its sectors (" + sector + "); colorBy is ignored")
    cspec = {"id": vid, "coloring": vspec.get("coloring")}
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.PieChart, PieChart)
    _charts_axis(vid, info, "Sector", content.ColorAxis, sector)
    _charts_axis(vid, info, "SectorSize", content.SectorSizeAxis, size)
    if vspec.get("labels") is not None:
        # Not yet tested: which label parts (category, percentage, value) a new pie shows.
        _charts_option(vid, info, "labels", _charts_set_labels,
                       (content.VisualAttributes, vspec.get("labels")))
    _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, False)


def vis_box(page, vspec):
    """Box plot: x (category), y (a raw value column: the box-plot Y axis does not aggregate),
    colorBy, trellis, yScale (xScale too); coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("x", "y"))
    vid = _charts_vid(vspec)
    x = _charts_cat(vspec.get("x"), table)
    y = _charts_expr(vspec.get("y"), table)
    cspec = _charts_color_spec(vspec, table, _charts_multi_default(y))
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.BoxPlot, BoxPlot)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)


def vis_heatmap(page, vspec):
    """Heat map: x, y (categories), value (cell expression), coloring (cell colors; default a
    gradient chosen by Spotfire). Also trellis, xScale, yScale."""
    table = _charts_start(vspec, ("x", "y", "value"))
    vid = _charts_vid(vspec)
    x = _charts_cat(vspec.get("x"), table)
    y = _charts_cat(vspec.get("y"), table)
    value = _charts_expr(vspec.get("value"), table)
    if not _charts_blank(vspec.get("colorBy")):
        B.warn(vid + ": heat-map cells are colored by their value; colorBy is ignored")
    cspec = {"id": vid, "coloring": vspec.get("coloring")}
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.HeatMap, HeatMap)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    _charts_axis(vid, info, "Measures", content.MeasureAxis, value)
    _charts_option(vid, info, "dendrograms", _charts_hide_dendrograms, (content,))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, False)


def vis_treemap(page, vspec):
    """Treemap: hierarchy (levels, outer first), size (numeric aggregation), colorBy (continuous;
    a category is colored through UniqueConcatenate). Also trellis."""
    table = _charts_start(vspec, ("hierarchy", "size"))
    vid = _charts_vid(vspec)
    hierarchy = _charts_cat(vspec.get("hierarchy"), table)
    size = _charts_expr(vspec.get("size"), table)
    cspec = _charts_color_spec(vspec, table)
    color_by = cspec.get("colorBy")
    if color_by is not None and color_by.strip().startswith("<"):
        inner = _charts_unwrap(color_by)
        if inner and " nest " not in (" " + inner.lower() + " "):
            # the treemap color axis is continuous-only (GUI-built DXPs AxisConfiguration; 5 of 11 corpus
            # treemaps color categories this way).
            # Not yet tested: categorical colors keyed by the category values apply to it.
            cspec["colorBy"] = "UniqueConcatenate(" + inner + ")"
        else:
            B.warn(vid + ": a treemap colors by a continuous expression; colorBy " + color_by
                   + " is set as written")
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.Treemap, Treemap)
    _charts_axis(vid, info, "Hierarchy", content.HierarchyAxis, hierarchy)
    _charts_axis(vid, info, "Size", content.SizeAxis, size)
    _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, False)


def vis_waterfall(page, vspec):
    """Waterfall chart: category (blocks), value, colorBy (also labels, trellis, xScale, yScale);
    coloring, reference layers, fitting models."""
    table = _charts_start(vspec, ("category", "value"))
    vid = _charts_vid(vspec)
    x = _charts_cat(vspec.get("category"), table)
    y = _charts_expr(vspec.get("value"), table)
    cspec = _charts_color_spec(vspec, table)
    visual, content, info = _charts_new(page, vspec, table, VisualTypeIdentifiers.WaterfallChart,
                                        WaterfallChart)
    _charts_axis(vid, info, "X", content.XAxis, x, _charts_title(vspec.get("xScale")))
    _charts_axis(vid, info, "Y", content.YAxis, y, _charts_title(vspec.get("yScale")))
    if vspec.get("labels") is not None:
        _charts_option(vid, info, "labels", _charts_set_labels, (content, vspec.get("labels")))
    trellised = _charts_trellis(vid, info, content, vspec.get("trellis"), table)
    _charts_scales(vid, info, content, vspec, trellised, ("X", "Y"))
    _charts_coloring(vid, info, content, cspec)
    return _charts_complete(visual, content, vspec, info, True)
