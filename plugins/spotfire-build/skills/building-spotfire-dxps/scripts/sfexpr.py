"""sfexpr - small readers of Spotfire expressions shared by dxpgen.py and verify_dxp.py.

No Spotfire, no I/O. The regexes below were dxpgen's own (expression_columns); dxpgen imports them from
here so both tools read expressions the same way.

raw_column_refs(text)
    The column names of an expression that sit outside every aggregation call. An empty list means the
    expression is aggregated, constant or post-aggregated (THEN). Used for the marker rule
    (references/api-maps.md, "How a working map is configured"): a scatter plot or map marker
    layer whose marker-by is not row level (it has no baserowid()) aggregates its markers, and then a
    raw label, size, line order or rotation makes Spotfire show "Please specify an aggregation
    method." and draw nothing; on a map one bad layer blanks the whole map, tile layer included.
unaggregated(text)
    raw_column_refs, plus a bare spec column name ("Station ID", no brackets) read as raw.
row_level(marker_by)
    True when a marker-by expression contains baserowid() (aggregation off: raw values are fine).

value_kind(text, prop_type, column_kind=None)
    ('date' | 'number' | 'string' | 'boolean' | 'time' | None, why) of an expression's value, read
    lexically: a document property (its declared type), a literal, a date or number function, an
    aggregation of one column, arithmetic. None = cannot tell. Used for reference lines (a date-axis
    reference line must evaluate to a date).
date_call_properties(text)
    [(function, property)] for every DateAdd / AddDays / ... call whose arguments name a document
    property (DocumentProperty("X") or [$X]).

Known limit: the one-argument Concatenate([A]) aggregation reads as raw (write UniqueConcatenate([A])).
"""
import re

# string literals, aliases ('as [Name]'), ${...} preprocessor text, Spotfire's own identifiers
# ([Axis.X], [Axis.Default.Names], [Axis.Color] ..., the KPI [Y.FinalValue]) and THEN
_EXPR_STRING_RE = re.compile(r'"(?:[^"\\]|\\.|"")*"|\'(?:[^\'\\]|\\.|\'\')*\'')
_EXPR_ALIAS_RE = re.compile(r"(?i)(?:(?<=\s)|(?<=[\)\]>]))as\s*\[(?:[^\]]|\]\])*\]")
_EXPR_IDENT_RE = re.compile(r"\[((?:[^\]]|\]\])*)\]")
_EXPR_PREPROCESSOR_RE = re.compile(r"(?<!\\)\$\{[^}]*\}")
_EXPR_SPECIAL_RE = re.compile(r"^(?:Axis\..+|(?:X|Y|Color|Size|Value)\.[A-Za-z]+)$")
_EXPR_THEN_RE = re.compile(r"(?i)\bTHEN\b")
# a spec column written without brackets ("Station ID", "Flow (bbl/d)"): same as scripts/t3/_common.py
PLAIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*?(?: \([^()\[\]<>\"']*\))?$")

# Spotfire aggregation methods (OVER keeps its node navigation inside the aggregated part)
AGGREGATES = frozenset(n.lower() for n in (
    "Sum", "Avg", "Count", "UniqueCount", "CountBig", "Min", "Max", "Median", "First", "Last",
    "UniqueConcatenate", "MostCommon", "StdDev", "StdErr", "Var", "Range", "Percentile", "P10", "P90",
    "Q1", "Q3", "IQR", "LAV", "UAV", "LIF", "UIF", "LOF", "UOF", "Outliers", "PctOutliers", "L95", "U95",
    "Product", "GeometricMean", "MeanDeviation", "MedianAbsoluteDeviation", "TrimmedMean",
    "WeightedAverage", "ValueForMax", "ValueForMin", "Covariance", "Correlation", "OVER"))
_AGG_TOKEN_RE = re.compile(r"\[(?:[^\]]|\]\])*\]|([A-Za-z_][A-Za-z0-9_]*)\s*\(|\(|\)")


def raw_column_refs(text):
    """Column names of a Spotfire expression outside every aggregation call ([] = aggregated, constant,
    post-aggregated with THEN, or a categorical "<...>" expression)."""
    if not isinstance(text, str) or not text.strip() or text.strip().startswith("<"):
        return []
    s = _EXPR_PREPROCESSOR_RE.sub(" ", text)
    s = _EXPR_STRING_RE.sub('""', s)
    s = _EXPR_ALIAS_RE.sub(" ", s)
    if _EXPR_THEN_RE.search(s):
        return []
    stack, raw = [], []
    for m in _AGG_TOKEN_RE.finditer(s):
        tok = m.group(0)
        if tok.startswith("["):
            name = tok[1:-1].replace("]]", "]")
            if s[m.end():m.end() + 2] == ".[" or name.startswith("$") or _EXPR_SPECIAL_RE.match(name):
                continue                                    # [Table].[Column] prefix, [$Prop], [Axis.X]
            if not any(stack):
                raw.append(name)
        elif m.group(1):
            stack.append(m.group(1).lower() in AGGREGATES)
        elif tok == "(":
            stack.append(False)
        elif stack:
            stack.pop()
    return raw


def unaggregated(text):
    """raw_column_refs, plus a bare spec column name (no brackets) taken as one raw column."""
    if not isinstance(text, str) or not text.strip():
        return []
    t = text.strip()
    return raw_column_refs(t) or ([t] if PLAIN_NAME_RE.match(t) else [])


def row_level(marker_by):
    """True when a marker-by expression contains baserowid(): one marker per row, no aggregation."""
    return isinstance(marker_by, str) and "baserowid()" in marker_by.replace(" ", "").lower()


# ---- value kinds (reference lines) -----------------------------------------------------------------
TYPE_KIND = {"Date": "date", "DateTime": "date", "Time": "time", "TimeSpan": "time", "String": "string",
             "Boolean": "boolean", "Integer": "number", "LongInteger": "number", "Real": "number",
             "SingleReal": "number", "Currency": "number"}
# functions that shift a date by a count: Spotfire wants an Integer count and a date
DATE_SHIFT_FUNCS = frozenset(n.lower() for n in (
    "DateAdd", "AddDays", "AddHours", "AddMinutes", "AddMonths", "AddQuarters", "AddSeconds", "AddWeeks",
    "AddYears", "AddMilliseconds"))
DATE_FUNCS = DATE_SHIFT_FUNCS | frozenset(n.lower() for n in (
    "Date", "DateTime", "Today", "DateTimeNow", "ParseDateTime", "DateTimeTicks"))
NUMBER_FUNCS = frozenset(n.lower() for n in (
    "DateDiff", "Year", "Quarter", "Month", "Week", "Day", "DayOfMonth", "DayOfYear", "Hour", "Minute",
    "Second", "Millisecond", "Count", "UniqueCount", "CountBig", "Sum", "StdDev", "StdErr", "Var", "Abs",
    "Round", "Integer", "LongInteger", "Real", "SingleReal", "Sqrt", "Ln", "Log", "Log10", "Exp", "Power",
    "Ceiling", "Floor", "Len", "Mod", "Rank", "Percentile", "P10", "P90", "Q1", "Q3", "IQR"))
COLUMN_KIND_AGGS = frozenset(("min", "max", "first", "last", "avg", "median", "mostcommon"))
_PROP_REF_RE = re.compile(r"""DocumentProperty\(\s*(['"])([^'"]+)\1\s*\)|\[\$([A-Za-z0-9.]+)\]""")
_WHOLE_PROP_RE = re.compile(r"""^(?:DocumentProperty\(\s*(['"])([^'"]+)\1\s*\)|\[\$([A-Za-z0-9.]+)\])$""")
_NUMBER_RE = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def mask(text):
    """Same length, string-literal and [identifier] contents replaced by '_' (structure only)."""
    out = list(text)
    for rx in (_EXPR_STRING_RE, _EXPR_IDENT_RE):
        for m in rx.finditer("".join(out)):
            for k in range(m.start() + 1, m.end() - 1):
                out[k] = "_"
    return "".join(out)


def _close(masked, open_at):
    """Index of the parenthesis closing the one at open_at, or -1."""
    depth = 0
    for k in range(open_at, len(masked)):
        if masked[k] == "(":
            depth += 1
        elif masked[k] == ")":
            depth -= 1
            if depth == 0:
                return k
    return -1


def _strip(text):
    s = _EXPR_ALIAS_RE.sub(" ", " " + text).strip()
    while s.startswith("(") and _close(mask(s), 0) == len(s) - 1:
        s = s[1:-1].strip()
    return s


def _split_arith(s):
    """Operands of top-level + - * / (unary signs stay with their operand)."""
    m = mask(s)
    parts, depth, start, prev = [], 0, 0, -1
    for k, ch in enumerate(m):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif (depth == 0 and ch in "+-*/" and prev >= 0 and m[prev] not in "+-*/(,"
              and not (m[prev] in "eE" and prev > 0 and m[prev - 1].isdigit()) and m[start:k].strip()):
            parts.append(s[start:k])
            start = k + 1
        if not ch.isspace():
            prev = k
    parts.append(s[start:])
    return [p.strip() for p in parts]


def value_kind(text, prop_type, column_kind=None):
    """(kind, why): kind 'date', 'number', 'string', 'boolean', 'time' or None (cannot tell).
    prop_type(name) -> the document property's DataType name or None; column_kind(name) -> kind or None."""
    if not isinstance(text, str) or not text.strip():
        return None, ""
    s = _strip(text)
    m = _WHOLE_PROP_RE.match(s)
    if m:
        name = m.group(2) or m.group(3)
        t = prop_type(name)
        return TYPE_KIND.get(t), ('DocumentProperty("%s"), a %s property' % (name, t)) if t else ""
    if _NUMBER_RE.match(s):
        return "number", "the number %s" % s
    if _EXPR_STRING_RE.fullmatch(s):
        return "string", "a text literal"
    if s.lower() in ("true", "false"):
        return "boolean", s
    parts = _split_arith(s)
    if len(parts) > 1:
        kinds = [value_kind(p, prop_type, column_kind) for p in parts if p]
        if kinds and all(k == "number" for k, _ in kinds):
            props = [why for k, why in kinds if why.startswith("DocumentProperty")]
            return "number", "arithmetic on " + (props[0] if props else "numbers")
        return None, ""
    c = _CALL_RE.match(s)
    if c and _close(mask(s), c.end() - 1) == len(s) - 1:
        fn = c.group(1).lower()
        if fn in DATE_FUNCS:
            return "date", "%s(...)" % c.group(1)
        if fn in NUMBER_FUNCS:
            return "number", "%s(...)" % c.group(1)
        inner = s[c.end():-1].strip()
        if fn in COLUMN_KIND_AGGS and column_kind is not None:
            col = _EXPR_IDENT_RE.fullmatch(inner)
            if col:
                kind = column_kind(col.group(1).replace("]]", "]"))
                return kind, ("%s([%s])" % (c.group(1), col.group(1))) if kind else ""
        return None, ""
    col = _EXPR_IDENT_RE.fullmatch(s)
    if col and column_kind is not None:
        kind = column_kind(col.group(1).replace("]]", "]"))
        return kind, ("[%s]" % col.group(1)) if kind else ""
    return None, ""


def date_call_properties(text):
    """[(function, property)]: document properties inside the arguments of DateAdd / AddDays / ..."""
    if not isinstance(text, str):
        return []
    m = mask(text)
    out = []
    for c in _CALL_RE.finditer(m):
        if c.group(1).lower() not in DATE_SHIFT_FUNCS:
            continue
        end = _close(m, c.end() - 1)
        args = text[c.end():end if end >= 0 else len(text)]
        for p in _PROP_REF_RE.finditer(args):
            pair = (c.group(1), p.group(2) or p.group(3))
            if pair not in out:
                out.append(pair)
    return out
