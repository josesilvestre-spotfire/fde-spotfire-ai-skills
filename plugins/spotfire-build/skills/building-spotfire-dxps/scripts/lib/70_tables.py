# ============================================================================
# 70_tables.py - table, cross table, summary table, graphical table, KPI chart.
# IronPython 3.4 inside Spotfire Analyst 15.0 (Python 3.4 syntax: no f-strings,
# no walrus, no annotations, no print). Public API only; no internal members.
# Reference: references/api-tables.md.
#
# Public builders (dispatched by 90_build.VISUAL_BUILDERS):
#   vis_table(page, vspec)       columns, sort, widths {column: px}, coloring
#   vis_crosstable(page, vspec)  rows, columns, measures, totals, coloring
#   vis_summary(page, vspec)     columns, statistics
#   vis_graphical(page, vspec)   rows + sparkline / calculatedValue / icon /
#                                bulletGraph columns
#   vis_kpi(page, vspec)         kpis: title, value, comparative, time, tileBy,
#                                coloring
# Each one resolves the data table first (a missing table fails the visual
# before it exists), AddNew()s the visual, binds Data.DataTableReference
# (columns and expressions resolve against it), builds every sub-item in its own
# B.step (a failed sub-item never loses the visual) and runs vis_common
# (60_charts.py) last, in its own step, so `settings` and `postScript` see the
# finished visual. vis_kpi mirrors the chart-level data settings onto every KPI
# after vis_common, then applies per-KPI settings and runs postScript itself.
# What was built goes to B.created["tableVisuals"][id] (the exact expressions
# set, for verify_dxp); colorings go to B.created["coloring"] (65_coloring.py).
#
# Coloring: 65_coloring.py builds table / cross-table cell colorings
# (coloring_add_cell_coloring) and KPI tile colorings (coloring_apply_kpi).
# Graphical-table calculated-value and icon rules use their own factories
# (FontStyleFlags / MarkerShape overloads), so they are built here, with
# coloring_expression for the spec's [$Property] shorthand.
#
# Spec interpretation owned by this module (references/api-tables.md, section 2):
# - table / crossTable `coloring`: one coloring object or a list of them, with
#   targets `columns` (table: column names, required) and `measures`
#   (crossTable: measure display names or the measure expressions; none =
#   every numeric measure, ColoringCollection.DefaultNumericReference).
# - Categorical axes (crossTable rows/columns, graphicalTable rows, KPI tileBy):
#   a list of levels or one expression; ["[Station]", "[Pump ID]"] ->
#   "<[Station] NEST [Pump ID]>", "[Station]" -> "<[Station]>", a bare column
#   name is escaped. Without crossTable `columns`, or with several measures,
#   "[Axis.Default.Names]" (Column Names) ends the column axis, unless rows or columns already
#   hold it; `rows: ["[Axis.Default.Names]"]` puts the measures on the rows (statement layout).
#   The axis without Column Names is set first and both axes are read back (one retry in the
#   other order; a remaining difference is a warning).
# - `settings` on a graphicalTable column is relative to its miniature
#   visualization; on a KPI it is relative to its KpiVisualization.
# - Every expression written ([$Name] shorthand -> DocumentProperty("Name"), as
#   60_charts and 75_maps read it): cross-table measures and levels, graphical
#   rows, column expressions, sparkline x, bullet comparative and ranges, KPI
#   value, time, comparative and tileBy, rule values. Measure display names
#   (coloring keys) come from the expression as set; `as[Name]` (no space) is an
#   alias too.
# - A graphical-table column or KPI that fails half-way is removed again: the
#   visual holds only finished items (the report marks the failed one built=false).
#
# Requires newer than 14.6: nothing (newest members used: the FontStyleFlags
# rule overloads of CalculatedValueRuleCollection, [api 12.5]).
# DoNotUseOutsideAssembly: SummaryTable.Columns (SummaryTableVisibleColumnCollection)
# is flagged but is the only public way to choose summary-table columns.
# ============================================================================
import re

from System import Int32
from Spotfire.Dxp.Application.Visuals import (VisualTypeIdentifiers, TablePlot, CrossTablePlot,
                                              SummaryTable, KpiChart, TablePlotColumnSortMode,
                                              MarkerShape, MarkerType)
from Spotfire.Dxp.Application.Visuals.ConditionalColoring import (ConditionValue,
                                                                  RuleComparisonOperator,
                                                                  StringComparisonOperator)
from Spotfire.Dxp.Application.Visuals.Miniatures import (GraphicalTable,
                                                         SparklineMiniatureVisualization,
                                                         CalculatedValueMiniatureVisualization,
                                                         IconMiniatureVisualization,
                                                         BulletGraphMiniatureVisualization)
from Spotfire.Dxp.Framework.Styles import FontStyleFlags

_tables_names_level = "[Axis.Default.Names]"     # (Column Names) on a cross-table axis
_tables_kpi_final = "THEN [Y.FinalValue]"        # KPI post-aggregation (GUI-built DXPs: 96 uses)
_tables_coloring_keys = ("categorical", "gradient", "fixed", "rules", "default")
_tables_background_keys = ("categorical", "gradient", "fixed", "default")   # none on miniatures
_tables_not_here = ("colorBy", "referenceLayers", "fittingModels")
_tables_prop_re = re.compile(r"^\[\$([A-Za-z0-9_.]+)\]$")
# A trailing alias: "... as [Name]" ("as[Name]" too: the space after `as` is optional) or
# "... as Name"; `as` follows a space, ")" or "]" (case-insensitive, like Spotfire).
_tables_alias_re = re.compile(r"(?:(?<=\s)|(?<=[\)\]]))as(?:\s*(\[(?:[^\]]|\]\])+\])|"
                              r"\s+([A-Za-z_][A-Za-z0-9_]*))\s*$", re.IGNORECASE)
_tables_miniatures = {
    "sparkline": SparklineMiniatureVisualization,
    "calculatedValue": CalculatedValueMiniatureVisualization,
    "icon": IconMiniatureVisualization,
    "bulletGraph": BulletGraphMiniatureVisualization,
}


# ---- small helpers -------------------------------------------------------------
def _tables_list(value):
    """None -> [], a single value -> [value], list/tuple -> list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _tables_column(dt, name):
    """DataColumn of dt by name; '[Name]' (expression form) is accepted too."""
    text = str(name)
    found, col = dt.Columns.TryGetValue(text)
    if not found and text.startswith("[") and text.endswith("]"):
        found, col = dt.Columns.TryGetValue(text[1:-1].replace("]]", "]"))
    if not found:
        raise Exception("column not found: " + dt.Name + "." + text)
    return col


def _tables_type_name(data_type):
    """DataType -> its name ('Real', 'Integer', ...), or None."""
    if data_type is None:
        return None
    try:
        return str(data_type.Name)
    except Exception:
        return None


def _tables_expr(value):
    """Spec expression -> Spotfire text: `[$Name]` -> DocumentProperty("Name") (65_coloring's
    coloring_expression), the reading 60_charts and 75_maps give every axis, so a spec expression
    means the same on every visual type. Other text passes through unchanged."""
    return coloring_expression(str(value).strip())


def _tables_levels(dt, value):
    """Category levels from a list or one expression; '<...>' wrappers removed, a bare column
    name escaped ('Pump ID' -> '[Pump ID]'), [$Name] translated."""
    out = []
    for item in _tables_list(value):
        text = str(item).strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1].strip()
        if not text:
            continue
        if not text.startswith("[") and dt is not None:
            found, col = dt.Columns.TryGetValue(text)
            if found:
                text = esc(col.Name)
        out.append(_tables_expr(text))
    return out


def _tables_categorical(levels):
    """['[A]', '[B]'] -> '<[A] NEST [B]>'; [] -> '<>' (None)."""
    if not levels:
        return "<>"
    return "<" + " NEST ".join(levels) + ">"


def _tables_measure_name(expression):
    """Display name of a measure: its alias, else the expression without column brackets
    (GUI-built DXPs: Sum([Directional Volume]) -> 'Sum(Directional Volume)')."""
    text = str(expression).strip()
    m = _tables_alias_re.search(text)
    if m:
        if m.group(1):
            return m.group(1)[1:-1].replace("]]", "]")
        return m.group(2)
    # Not yet tested: display name of an unaliased measure (always alias measures).
    return text.replace("]]", "\x00").replace("[", "").replace("]", "").replace("\x00", "]")


def _tables_record(vid, vtype, dt):
    """B.created["tableVisuals"][id]: what this module built (JSON-safe), for verify_dxp."""
    info = {"type": vtype, "table": dt.Name}
    B.created.setdefault("tableVisuals", {})[vid] = info
    return info


def _tables_unsupported(vid, vspec, label):
    for key in _tables_not_here:
        if vspec.get(key):
            B.warn(label + " " + vid + ": '" + key + "' does not apply to this visual type; ignored")


def _tables_common(visual, content, vspec, run_post=True):
    """vis_common (60_charts.py), looked up inside the step so a missing 60_charts fails this
    step, not the visual. `coloring` is built by this module, so vis_common gets None for it;
    with run_post=False the caller runs `postScript` itself afterwards (vis_kpi)."""
    common = dict(vspec)
    common["coloring"] = None
    if not run_post:
        common["postScript"] = None
    return vis_common(visual, content, common)


def _tables_post_script(visual, content, code):
    """postScript with the SPEC scope (visual, content, Document)."""
    run_post_script(code, {"visual": visual, "content": content})
    return True


def _tables_colorings(value):
    """Visual-level `coloring`: None, one coloring object, or a list of them."""
    return [item for item in _tables_list(value) if item]


def _tables_check_coloring(cspec):
    """A coloring object must say what to do (65_coloring treats an empty one as a no-op)."""
    if not isinstance(cspec, dict):
        raise Exception("a coloring must be an object, got " + type(cspec).__name__)
    for key in _tables_coloring_keys:
        if cspec.get(key) is not None:
            return cspec
    raise Exception("coloring needs one of " + ", ".join(_tables_coloring_keys) + ": " + str(cspec))


# ---- graphical-table rules (CalculatedValueRuleCollection / IconRuleCollection) ----
def _tables_is_keyword(text):
    low = str(text).strip().lower()
    if low in ("min", "max", "median", "average"):
        return True
    if low.endswith("%"):
        try:
            float(low[:-1])
            return True
        except ValueError:
            return False
    return False


def _tables_literal(number):
    """ConditionValue literal typed like the JSON value (100.0 Real, 3 Integer)."""
    if isinstance(number, float):
        type_name = "Real"
    elif -2147483648 <= number <= 2147483647:
        type_name = "Integer"
    else:
        type_name = "LongInteger"
    # Not yet tested: an Integer literal compared with Real values (and vice versa).
    return ConditionValue.CreateLiteral(net_value(type_name, number), data_type(type_name))


def _tables_cv(value):
    """Spec value -> ConditionValue: number, 'min'/'max'/'median'/'average', 'NN%' (percent of
    the range), or any other string as an expression ([$Name] -> DocumentProperty("Name"))."""
    if value is None:
        raise Exception("rule value missing")
    if isinstance(value, bool):
        return ConditionValue.CreateLiteral(value)
    if isinstance(value, (int, float)):
        return _tables_literal(value)
    text = str(value).strip()
    low = text.lower()
    if low == "min":
        return ConditionValue.MinValue
    if low == "max":
        return ConditionValue.MaxValue
    if low == "median":
        return ConditionValue.MedianValue
    if low == "average":
        return ConditionValue.AverageValue
    if low.endswith("%"):
        try:
            return ConditionValue.CreatePercentValue(float(low[:-1]))
        except ValueError:
            pass
    # Not yet tested: expression condition values (for example DocumentProperty("X")).
    return ConditionValue.CreateExpression(coloring_expression(text))


def _tables_need(spec, key):
    value = spec.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise Exception("'" + str(spec.get("type") or spec.get("kind") or "entry") + "' needs '"
                        + key + "'")
    return value


def _tables_prop_is_text(name):
    """True when document property `name` is a String (spec first, then its current value)."""
    wanted = str(name).lower()
    for p in B.spec.get("properties") or []:
        if str(p.get("name", "")).lower() == wanted:
            return p.get("type") == "String"
    try:
        return isinstance(B.prop(name).Value, str)
    except Exception:
        return True


def _tables_equal_rule(coll, value, rule_color, extra):
    """equal: numbers and keywords -> threshold rule; text -> string rule; [$Name] -> by the
    property's type (a String property -> string rule on the property value)."""
    if isinstance(value, str) and not _tables_is_keyword(value):
        m = _tables_prop_re.match(value.strip())
        if m is None and "[$" not in value:
            return coll.AddStringRule(StringComparisonOperator.Equal,
                                      ConditionValue.CreateLiteral(value), rule_color, extra)
        if m is not None and _tables_prop_is_text(m.group(1)):
            # Not yet tested: an expression condition value in a string rule.
            expression = ConditionValue.CreateExpression(coloring_expression(value))
            return coll.AddStringRule(StringComparisonOperator.Equal, expression, rule_color, extra)
    return coll.AddThresholdRule(RuleComparisonOperator.Equal, _tables_cv(value), rule_color, extra)


def _tables_add_rule(coll, rule, kind):
    """One spec rule on a calculated-value (kind 'calc': font style Regular) or icon (kind
    'icon': optional rule `shape` = MarkerType name, default Circle) rule collection, appended in
    spec order, then the rule's own `settings`. Returns the rule."""
    if not isinstance(rule, dict):
        raise Exception("a rule must be an object, got " + type(rule).__name__)
    rtype = rule.get("type")
    rule_color = color(_tables_need(rule, "color"))
    if kind == "calc":
        extra = FontStyleFlags.Regular
    else:
        extra = MarkerShape(enum_value(MarkerType, str(rule.get("shape") or "Circle")))
    # Not yet tested: precedence follows list order (first rule = top = wins).
    if rtype in ("greaterThan", "lessThan"):
        op = RuleComparisonOperator.Greater if rtype == "greaterThan" else RuleComparisonOperator.Less
        created = coll.AddThresholdRule(op, _tables_cv(_tables_need(rule, "value")), rule_color, extra)
    elif rtype == "equal":
        created = _tables_equal_rule(coll, _tables_need(rule, "value"), rule_color, extra)
    elif rtype == "between":
        low = _tables_cv(_tables_need(rule, "low"))
        high = _tables_cv(_tables_need(rule, "high"))
        created = coll.AddRangeRule(low, high, rule_color, extra)
    elif rtype in ("top", "bottom"):
        rank = Int32(int(_tables_need(rule, "count")))
        if rtype == "top":
            created = coll.AddTopNRule(rank, rule_color, extra)
        else:
            created = coll.AddBottomNRule(rank, rule_color, extra)
    elif rtype == "expression":
        # Not yet tested: what an expression rule may reference (coloring note U10).
        expression = coloring_expression(_tables_need(rule, "expression"))
        created = coll.AddExpressionRule(expression, rule_color, extra)
    else:
        raise Exception("unknown rule type: " + str(rtype))
    try:
        apply_settings(created, rule.get("settings"))
    except Exception:
        coll.Remove(created)                       # never leave a half-configured rule
        raise
    return created


def _tables_value_rules(cspec, where):
    """Rules of a graphical-table column: `coloring.rules` (or `rules`). Miniatures have no
    background coloring, so categorical / gradient / fixed / default are warned and ignored."""
    coloring = cspec.get("coloring") or {}
    if not isinstance(coloring, dict):
        B.warn(where + ": 'coloring' must be an object; ignored")
        coloring = {}
    ignored = [k for k in _tables_background_keys if coloring.get(k) is not None]
    if ignored:
        B.warn(where + ": " + ", ".join(ignored) + " ignored (graphical-table columns take rules only)")
    return _tables_list(coloring.get("rules") or cspec.get("rules"))


# ---- table ---------------------------------------------------------------------
def _tables_table_columns(tbl, dt, names, info):
    names = _tables_list(names)
    if not names:
        tbl.TableColumns.Clear()
        shown = []
        for col in dt.Columns:
            tbl.TableColumns.Add(col)
            shown.append(col.Name)
        tbl.AutoAddNewColumns = True
        info["columns"] = shown
        info["autoAddNewColumns"] = True
        return tbl.TableColumns.Count
    tbl.AutoAddNewColumns = False                  # before Clear
    tbl.TableColumns.Clear()                       # a new table's starting columns are unknown
    shown = []
    missing = []
    for name in names:
        try:
            col = _tables_column(dt, name)
            tbl.TableColumns.Add(col)              # display order = add order
            shown.append(col.Name)
        except Exception as e:
            missing.append(str(name) + " (" + exc_text(e) + ")")
    info["columns"] = shown
    info["autoAddNewColumns"] = False
    if missing:
        raise Exception("table columns not added: " + "; ".join(missing))
    return tbl.TableColumns.Count


def _tables_table_sort(tbl, dt, sorts, info):
    tbl.SortInfos.Clear()
    done = []
    missing = []
    for item in _tables_list(sorts):
        if isinstance(item, dict):
            name = item.get("column")
            descending = bool(item.get("descending", False))
        else:
            name = item
            descending = False
        try:
            col = _tables_column(dt, name)
            mode = TablePlotColumnSortMode.Descending if descending else TablePlotColumnSortMode.Ascending
            # Not yet tested: list order = sort priority.
            tbl.SortInfos.Add(col, mode)
            done.append({"column": col.Name, "descending": descending})
        except Exception as e:
            missing.append(str(name) + " (" + exc_text(e) + ")")
    info["sort"] = done
    if missing:
        raise Exception("sorts not added: " + "; ".join(missing))
    return tbl.SortInfos.Count


def _tables_table_widths(tbl, dt, widths, info):
    """Widths belong to columns, never to positions: TryGetTableColumn(column).Width."""
    done = {}
    missing = []
    for name in sorted(widths.keys()):
        try:
            col = _tables_column(dt, name)
        except Exception as e:
            missing.append(str(name) + " (" + exc_text(e) + ")")
            continue
        found, tcol = tbl.TableColumns.TryGetTableColumn(col)
        if not found:
            missing.append(str(name) + " (not shown in this table)")
            continue
        # Not yet tested: TableColumn.Width persists as TableColumns.Widths[column Id].
        tcol.Width = int(widths[name])
        done[col.Name] = int(widths[name])
    info["widths"] = done
    if missing:
        raise Exception("widths not set: " + "; ".join(missing))
    return len(done)


def _tables_table_coloring(tbl, dt, cspec, target):
    """Cell coloring of table columns: key = column name (GUI-built DXPs "Events" table). Several
    columns share one coloring."""
    _tables_check_coloring(cspec)
    names = _tables_list(cspec.get("columns"))
    if not names:
        raise Exception("a table coloring needs 'columns' (the table columns it colors)")
    cols = [_tables_column(dt, name) for name in names]
    keys = [c.Name for c in cols]
    for c in cols:
        found, unused = tbl.TableColumns.TryGetTableColumn(c)
        if not found:
            B.warn(target + ": column '" + c.Name + "' is colored but not shown in the table")
    # Never raises: background and each rule are their own steps under `target`.
    coloring_add_cell_coloring(tbl.Colorings, cspec, target, keys, None,
                               _tables_type_name(cols[0].DataType), True)
    return keys


def vis_table(page, vspec):
    """Table: columns (names, display order; absent = every column), sort [{column,
    descending}], widths {column: px}, coloring (objects with `columns`)."""
    dt = B.table_or_default(vspec.get("table"))
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.Table)
    tbl = visual.As[TablePlot]()
    tbl.Data.DataTableReference = dt               # bind first: the column list belongs to the table
    vid = vspec["id"]
    info = _tables_record(vid, "table", dt)
    _tables_unsupported(vid, vspec, "table")
    B.step("table.columns", vid, _tables_table_columns, (tbl, dt, vspec.get("columns"), info))
    if vspec.get("sort"):
        B.step("table.sort", vid, _tables_table_sort, (tbl, dt, vspec["sort"], info))
    if vspec.get("widths"):
        B.step("table.widths", vid, _tables_table_widths, (tbl, dt, vspec["widths"], info))
    info["colorings"] = []
    n = 0
    for cspec in _tables_colorings(vspec.get("coloring")):
        target = vid + "/coloring[" + str(n) + "]"
        n += 1
        if B.step("table.coloring", target, _tables_table_coloring, (tbl, dt, cspec, target)):
            info["colorings"].append(target)
    # vis_common assigns Data.DataTableReference only when the table differs (60_charts
    # _charts_set_table), so the columns, sort, widths and colorings above stay as built.
    B.step("table.common", vid, _tables_common, (visual, tbl, vspec))
    return visual


# ---- cross table ---------------------------------------------------------------
def _tables_cross_axes(ct, dt, vspec, measures, info):
    if measures:
        # Measures first: their aliases are the keys colorings, formats and sorts use.
        texts = [_tables_expr(m) for m in measures]
        measure_text = ", ".join(texts)
        ct.MeasureAxis.Expression = measure_text
        info["measureAxis"] = measure_text
        info["measureNames"] = [_tables_measure_name(t) for t in texts]
    rows = _tables_levels(dt, vspec.get("rows"))
    cols = _tables_levels(dt, vspec.get("columns"))
    has_names = False
    for level in rows + cols:
        if _tables_names_level in level:
            has_names = True
    if not has_names and (not cols or len(measures) > 1):
        # GUI-built DXPs: one measure, no column categories -> "<[Axis.Default.Names]>";
        # categories plus two measures -> "<[Order Type] NEST [Axis.Default.Names]>".
        cols = cols + [_tables_names_level]
    row_text = _tables_categorical(rows)
    col_text = _tables_categorical(cols)
    names_on_rows = False
    for level in rows:
        if _tables_names_level in level:
            names_on_rows = True
    info["rowAxis"] = row_text
    info["columnAxis"] = col_text
    info["axesAsSet"] = _tables_set_category_axes(ct, row_text, col_text, names_on_rows,
                                                  str(vspec.get("id") or "crossTable"))
    return True


def _tables_same_expression(actual, wanted):
    """Axis expressions compared as Spotfire may normalize them (spacing, keyword case)."""
    return " ".join(str(actual or "").split()).lower() == " ".join(str(wanted or "").split()).lower()


def _tables_set_category_axes(ct, row_text, col_text, names_on_rows, vid):
    """Row and column axes of a cross table, then a read-back of both.

    (Column Names) belongs on one axis only, so the axis that does not receive it is set first: with
    measures as rows (Names on the row axis) the column axis goes first, which takes Names off the
    columns before the rows get it. When that order raises, or Spotfire reads back something else
    (it moved a level), the other order is tried once. A difference that remains is a warning with
    what Spotfire kept; when both orders raise, the last error fails the step. Returns True when the
    axes read back as set."""
    # Not yet tested: Column Names on the row axis with several measures (measures as rows); no corpus
    # cross table has it (all 7 keep Names on the column axis), the Analyst UI allows it.
    if names_on_rows:
        first = [("ColumnAxis", col_text), ("RowAxis", row_text)]
    else:
        first = [("RowAxis", row_text), ("ColumnAxis", col_text)]
    error = None
    applied = False
    for order in (first, [first[1], first[0]]):
        try:
            for name, text in order:
                getattr(ct, name).Expression = text
        except Exception as e:
            error = e
            continue
        applied = True
        if (_tables_same_expression(ct.RowAxis.Expression, row_text)
                and _tables_same_expression(ct.ColumnAxis.Expression, col_text)):
            return True
    if not applied:
        raise error
    B.warn("cross table " + vid + ": Spotfire kept rows " + str(ct.RowAxis.Expression) + " and columns "
           + str(ct.ColumnAxis.Expression) + " instead of " + row_text + " and " + col_text)
    return False


def _tables_cross_totals(ct, totals, info):
    # Not yet tested: which grand total each flag draws, and whether subtotals of nested row
    # levels appear (ColumnSubtotals is left at Spotfire's default).
    done = {}
    if totals.get("rows") is not None:
        ct.ShowRowGrandTotal = bool(totals["rows"])
        done["rows"] = bool(totals["rows"])
    if totals.get("columns") is not None:
        ct.ShowColumnGrandTotal = bool(totals["columns"])
        done["columns"] = bool(totals["columns"])
    info["totals"] = done
    return True


def _tables_cross_coloring(ct, measures, cspec, target, vid):
    """Cell coloring of measures: key = measure display name (its alias, GUI-built DXPs); no
    `measures` = the default numeric coloring (every numeric measure without its own)."""
    _tables_check_coloring(cspec)
    by_expression = {}
    display = []
    for m in measures:
        text = _tables_expr(m)                  # the measure as _tables_cross_axes set it
        name = _tables_measure_name(text)
        by_expression[str(m).strip()] = name    # targets may repeat the spec text ...
        by_expression[text] = name              # ... or the translated one
        display.append(name)
    names = []
    for item in _tables_list(cspec.get("measures")):
        text = str(item).strip()
        name = by_expression.get(text, by_expression.get(_tables_expr(text), text))
        if display and name not in display:
            B.warn("cross table " + vid + ": coloring target '" + text
                   + "' matches no measure display name (" + ", ".join(display) + ")")
        names.append(name)
    # Not yet tested: the default numeric coloring colors every numeric measure without its own.
    coloring_add_cell_coloring(ct.Colorings, cspec, target, names if names else None,
                               None, None, True)
    return names if names else ["(default numeric)"]


def vis_crosstable(page, vspec):
    """Cross table: rows (levels), columns (levels), measures (aggregations, alias them),
    totals {rows, columns}, coloring (objects with optional `measures`)."""
    dt = B.table_or_default(vspec.get("table"))
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.CrossTable)
    ct = visual.As[CrossTablePlot]()
    ct.Data.DataTableReference = dt
    vid = vspec["id"]
    info = _tables_record(vid, "crossTable", dt)
    _tables_unsupported(vid, vspec, "cross table")
    measures = _tables_list(vspec.get("measures"))
    if not measures:
        B.warn("cross table " + vid + ": no measures; the measure axis keeps Spotfire's default")
    B.step("crossTable.axes", vid, _tables_cross_axes, (ct, dt, vspec, measures, info))
    if vspec.get("totals"):
        B.step("crossTable.totals", vid, _tables_cross_totals, (ct, vspec["totals"], info))
    info["colorings"] = []
    n = 0
    for cspec in _tables_colorings(vspec.get("coloring")):
        target = vid + "/coloring[" + str(n) + "]"
        n += 1
        if B.step("crossTable.coloring", target, _tables_cross_coloring,
                  (ct, measures, cspec, target, vid)):
            info["colorings"].append(target)
    B.step("crossTable.common", vid, _tables_common, (visual, ct, vspec))
    return visual


# ---- summary table -------------------------------------------------------------
def _tables_summary_columns(st, dt, names, info):
    names = _tables_list(names)
    if not names:
        st.Columns.Clear()
        shown = []
        for col in dt.Columns:
            if col.DataType.IsNumeric:
                st.Columns.AddNew(col.Name)
                shown.append(col.Name)
        st.AutoAddNewColumns = True
        info["columns"] = shown
        info["autoAddNewColumns"] = True
        return st.Columns.Count
    st.AutoAddNewColumns = False                   # before Clear
    st.Columns.Clear()
    shown = []
    missing = []
    for name in names:
        try:
            col = _tables_column(dt, name)
            st.Columns.AddNew(col.Name)            # takes the column NAME, not a DataColumn
            shown.append(col.Name)
        except Exception as e:
            missing.append(str(name) + " (" + exc_text(e) + ")")
    info["columns"] = shown
    info["autoAddNewColumns"] = False
    if missing:
        raise Exception("summary-table columns not added: " + "; ".join(missing))
    return st.Columns.Count


def _tables_summary_statistics(st, statistics, info):
    st.Aggregations.Clear()
    done = []
    rejected = []
    for method in _tables_list(statistics):
        try:
            # Not yet tested: accepted method names.
            st.Aggregations.AddNew(str(method))
            done.append(str(method))
        except Exception as e:
            rejected.append(str(method) + " (" + exc_text(e) + ")")
    info["statistics"] = done
    if rejected:
        raise Exception("statistics not accepted: " + "; ".join(rejected))
    return st.Aggregations.Count


def vis_summary(page, vspec):
    """Summary table: columns (column names; absent = every numeric column), statistics
    (aggregation method names)."""
    dt = B.table_or_default(vspec.get("table"))
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.SummaryTable)
    st = visual.As[SummaryTable]()
    st.Data.DataTableReference = dt
    vid = vspec["id"]
    info = _tables_record(vid, "summaryTable", dt)
    _tables_unsupported(vid, vspec, "summary table")
    B.step("summaryTable.columns", vid, _tables_summary_columns, (st, dt, vspec.get("columns"), info))
    if vspec.get("statistics"):
        B.step("summaryTable.statistics", vid, _tables_summary_statistics,
               (st, vspec["statistics"], info))
    if vspec.get("coloring"):
        B.warn("summary table " + vid + ": 'coloring' ignored (summary tables have no cell coloring)")
    B.step("summaryTable.common", vid, _tables_common, (visual, st, vspec))
    return visual


# ---- graphical table -----------------------------------------------------------
def _tables_graphical_rows(gt, dt, rows, info):
    text = _tables_categorical(_tables_levels(dt, rows))
    gt.RowAxis.Expression = text
    info["rowAxis"] = text
    return text


def _tables_graphical_reset(gt):
    gt.SortInfos.Clear()
    gt.Columns.Clear()
    return True


def _tables_graphical_column(gt, cspec, where):
    """One column: AddNew[T]() -> (column, miniature), then title, width and the kind's own fields;
    a column that fails half-way is removed again. Rules, bullet ranges and settings are separate
    steps. Returns (column, miniature, record)."""
    kind = cspec.get("kind")
    mini_type = _tables_miniatures.get(kind)
    if mini_type is None:
        raise Exception("unknown graphical-table column kind: " + str(kind))
    # Not yet tested: the out parameter comes back as (column, miniature).
    result = gt.Columns.AddNew[mini_type]()
    if isinstance(result, tuple):
        column = result[0]
        mini = result[1]
    else:
        column = result
        mini = result.Visualization
    try:
        return _tables_graphical_fill(column, mini, kind, cspec, where)
    except Exception:
        try:
            gt.Columns.Remove(column)              # never leave a half-built column behind
        except Exception:
            pass
        raise


def _tables_graphical_fill(column, mini, kind, cspec, where):
    """Title, width and the kind's own fields of a new graphical-table column."""
    expression = cspec.get("expression")
    if expression:
        expression = _tables_expr(expression)
    record = {"kind": kind, "title": cspec.get("title"), "width": cspec.get("width"),
              "expression": expression or None, "rules": 0}
    if cspec.get("title") is not None:
        column.Title = str(cspec["title"])
    if cspec.get("width") is not None:
        column.Width = int(cspec["width"])
    if not expression:
        B.warn(where + ": column without 'expression' keeps Spotfire's default value axis")
    if kind == "sparkline":
        if cspec.get("x"):
            # Not yet tested: a continuous X ("[Timestamp]") as well as a categorical one ("<...>").
            x_text = _tables_expr(cspec["x"])
            mini.XAxis.Expression = x_text
            record["x"] = x_text
        else:
            B.warn(where + ": sparkline without 'x' keeps Spotfire's default X axis")
        if expression:
            mini.YAxis.Expression = str(expression)
        if cspec.get("color"):
            mini.LineColor = color(cspec["color"])
        if cspec.get("individualScaling") is not None:
            mini.YAxis.IndividualScaling = bool(cspec["individualScaling"])
    elif kind == "calculatedValue":
        if expression:
            mini.ValueAxis.Expression = str(expression)
        mini.ValueAxis.Rules.Clear()
    elif kind == "icon":
        if expression:
            mini.IconAxis.Expression = str(expression)
        mini.IconAxis.Rules.Clear()
    else:
        if expression:
            mini.ValueAxis.Expression = str(expression)
        if cspec.get("comparative"):
            comparative = _tables_expr(cspec["comparative"])
            mini.ComparativeValueExpression = comparative
            record["comparative"] = comparative
        if cspec.get("color"):
            mini.ValueColor = color(cspec["color"])
        if cspec.get("comparativeColor"):
            mini.ComparativeValueColor = color(cspec["comparativeColor"])
        record["ranges"] = 0
        if cspec.get("ranges"):
            mini.ColorRanges.Clear()
            mini.ShowColorRanges = True
    return (column, mini, record)


def _tables_bullet_range(mini, band):
    if not isinstance(band, dict):
        raise Exception("a bullet-graph range must be an object, got " + type(band).__name__)
    expression = coloring_expression(_tables_need(band, "expression"))
    created = mini.ColorRanges.AddNew(color(_tables_need(band, "color")), str(band.get("label") or ""))
    # Not yet tested: the range expression is the band's upper bound.
    created.Expression = str(expression)
    return created


def _tables_graphical_extras(mini, cspec, record, target):
    """Rules (calculatedValue, icon), ranges (bulletGraph) and `settings` (relative to the
    miniature) of one column, each its own step."""
    kind = cspec.get("kind")
    rules = _tables_value_rules(cspec, target)
    if rules:
        coll = None
        rule_kind = None
        if kind == "calculatedValue":
            coll = mini.ValueAxis.Rules
            rule_kind = "calc"
        elif kind == "icon":
            coll = mini.IconAxis.Rules
            rule_kind = "icon"
        if coll is None:
            B.warn(target + ": rules ignored (only calculatedValue and icon columns have rules)")
        else:
            for i in range(len(rules)):
                if B.step("graphicalTable.rule", target + "/rules[" + str(i) + "]", _tables_add_rule,
                          (coll, rules[i], rule_kind)) is not None:
                    record["rules"] += 1
    if kind == "bulletGraph":
        ranges = _tables_list(cspec.get("ranges"))
        for i in range(len(ranges)):
            if B.step("graphicalTable.range", target + "/ranges[" + str(i) + "]", _tables_bullet_range,
                      (mini, ranges[i])) is not None:
                record["ranges"] += 1
    elif cspec.get("ranges"):
        B.warn(target + ": 'ranges' ignored (only bulletGraph columns have color ranges)")
    if cspec.get("settings"):
        B.step("graphicalTable.column.settings", target, apply_settings, (mini, cspec["settings"]))


def vis_graphical(page, vspec):
    """Graphical table: rows (category expression or levels), columns [{kind, title,
    expression, width, ...}] with kinds sparkline, calculatedValue, icon, bulletGraph."""
    dt = B.table_or_default(vspec.get("table"))
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.GraphicalTable)
    gt = visual.As[GraphicalTable]()
    gt.Data.DataTableReference = dt
    vid = vspec["id"]
    info = _tables_record(vid, "graphicalTable", dt)
    info["columns"] = []
    _tables_unsupported(vid, vspec, "graphical table")
    if vspec.get("coloring"):
        B.warn("graphical table " + vid + ": visual-level 'coloring' ignored; use columns[].coloring.rules")
    if vspec.get("rows"):
        B.step("graphicalTable.rows", vid, _tables_graphical_rows, (gt, dt, vspec["rows"], info))
    columns = _tables_list(vspec.get("columns"))
    if columns:
        B.step("graphicalTable.reset", vid, _tables_graphical_reset, (gt,))
    else:
        B.warn("graphical table " + vid + ": no columns in the spec")
    # Not yet tested: the miniature columns follow the graphical table's data (table, marking,
    # limits); unlike KPIs, none of them is given a VisualizationData of its own here.
    n = 0
    for cspec in columns:
        target = vid + "/columns[" + str(n) + "]"
        n += 1
        if not isinstance(cspec, dict):
            B.warn(target + ": a column must be an object; skipped")
            continue
        made = B.step("graphicalTable.column", target + " " + str(cspec.get("kind")),
                      _tables_graphical_column, (gt, cspec, target))
        if made is None:
            info["columns"].append({"kind": cspec.get("kind"), "built": False})
            continue
        record = made[2]
        info["columns"].append(record)
        _tables_graphical_extras(made[1], cspec, record, target)
    B.step("graphicalTable.common", vid, _tables_common, (visual, gt, vspec))
    return visual


# ---- KPI chart -----------------------------------------------------------------
def _tables_kpi_reset(kc):
    kc.KpiCollection.Clear()
    return True


def _tables_kpi_one(kc, dt, kspec, record):
    """One KPI: KpiCollection.AddNew() -> KpiContent (title) wrapping a KpiVisualization (axes).
    A KPI that fails half-way is removed again, so the chart holds only finished tiles."""
    if not kspec.get("value"):
        raise Exception("KPI without 'value': " + str(kspec))
    content = kc.KpiCollection.AddNew()
    try:
        return _tables_kpi_fill(content, dt, kspec, record)
    except Exception:
        try:
            kc.KpiCollection.Remove(content)       # never leave a half-built KPI behind
        except Exception:
            pass
        raise


def _tables_kpi_fill(content, dt, kspec, record):
    """Title, table and axes of a new KPI. Returns its KpiVisualization."""
    if kspec.get("title"):
        content.Title = str(kspec["title"])        # persisted as TitleExpression (default ${AutoTitle})
        record["title"] = str(kspec["title"])
    kpi = content.Visualization
    current = kpi.Data.DataTableReference
    if current is None or current.Name != dt.Name:
        # Not yet tested: whether a new KPI inherits the chart's table.
        kpi.Data.DataTableReference = dt
    value = _tables_expr(kspec["value"])
    tile = _tables_categorical(_tables_levels(dt, kspec.get("tileBy")))
    time_expression = kspec.get("time")
    x_text = _tables_expr(time_expression) if time_expression else "<>"
    kpi.YAxis.Expression = value
    kpi.TileAxis.Expression = tile
    # Not yet tested: KpiXAxis takes a continuous time expression ("[Timestamp]") as well as a
    # categorical one (it persists supportsAxisModes: true, GUI-built DXPs).
    kpi.XAxis.Expression = x_text
    kpi.ShowSparkline = bool(time_expression)      # independent flag (GUI-built DXPs): always set it
    comparative = kspec.get("comparative")
    if comparative:
        comparative = _tables_expr(comparative)
        kpi.ComparativeAxis.Expression = comparative
    kpi.SortColumn.Expression = _tables_kpi_final  # same on every KPI: HighestFirst/LowestFirst need it
    record.update({"value": value, "tileAxis": tile, "xAxis": x_text,
                   "comparative": comparative or None,
                   "showSparkline": bool(time_expression), "sortColumn": _tables_kpi_final})
    return kpi


def _tables_kpi_sync_data(kc, kpis):
    """Each KPI owns a VisualizationData (GUI-built DXPs: chart and KPI persist the
    same DataTable, Marking, Filterings and limits). Mirror the chart-level settings that
    vis_common applied onto every KPI."""
    # Not yet tested: KPI tiles follow the KPI-level marking / limits / filtering.
    src = kc.Data
    selections = [s for s in src.Filterings]
    table = src.DataTableReference
    for kpi in kpis:
        d = kpi.Data
        if table is not None and (d.DataTableReference is None or d.DataTableReference.Name != table.Name):
            d.DataTableReference = table
        d.MarkingReference = src.MarkingReference
        d.UseActiveFiltering = src.UseActiveFiltering
        d.WhereClauseExpression = src.WhereClauseExpression
        d.LimitingMarkingsEmptyBehavior = src.LimitingMarkingsEmptyBehavior
        d.LimitingMarkingsEmptyMessage = src.LimitingMarkingsEmptyMessage
        d.MarkingCombinationMethod = src.MarkingCombinationMethod
        while d.Filterings.Count > 0:
            d.Filterings.RemoveAt(0)
        for selection in selections:
            d.Filterings.Add(selection)
    return len(kpis)


def vis_kpi(page, vspec):
    """KPI chart: kpis [{title, value, comparative, time, tileBy, coloring, settings}]; the
    visual-level `coloring` is the default for KPIs without their own."""
    dt = B.table_or_default(vspec.get("table"))
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.KpiChart)
    kc = visual.As[KpiChart]()
    kc.Data.DataTableReference = dt
    vid = vspec["id"]
    info = _tables_record(vid, "kpiChart", dt)
    info["kpis"] = []
    _tables_unsupported(vid, vspec, "KPI chart")
    kpis = _tables_list(vspec.get("kpis"))
    if kpis:
        B.step("kpiChart.reset", vid, _tables_kpi_reset, (kc,))
    else:
        B.warn("KPI chart " + vid + ": no kpis in the spec; the chart stays empty")
    default_coloring = vspec.get("coloring")
    built = []
    n = 0
    for kspec in kpis:
        target = vid + "/kpis[" + str(n) + "]"
        n += 1
        if not isinstance(kspec, dict):
            B.warn(target + ": a KPI must be an object; skipped")
            continue
        record = {"title": None, "built": False, "coloring": None}
        info["kpis"].append(record)
        kpi = B.step("kpiChart.kpi", target + " " + str(kspec.get("title") or kspec.get("value")),
                     _tables_kpi_one, (kc, dt, kspec, record))
        if kpi is None:
            continue
        record["built"] = True
        built.append((kpi, kspec, target))
        cspec = kspec.get("coloring") or default_coloring
        if cspec:
            # Tile coloring on THEN [Y.FinalValue]; its background and rules are their own steps.
            B.step("kpiChart.coloring", target + "/coloring", coloring_apply_kpi,
                   (kpi, cspec, target + "/coloring"))
            record["coloring"] = target + "/coloring"
    B.step("kpiChart.common", vid, _tables_common, (visual, kc, vspec, False))
    if built:
        B.step("kpiChart.data", vid, _tables_kpi_sync_data, (kc, [b[0] for b in built]))
    for item in built:
        if item[1].get("settings"):
            B.step("kpiChart.kpi.settings", item[2], apply_settings, (item[0], item[1]["settings"]))
    if vspec.get("postScript"):
        B.step("kpiChart.postScript", vid, _tables_post_script, (visual, kc, vspec["postScript"]))
    return visual
