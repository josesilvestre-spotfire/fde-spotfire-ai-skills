"""Shared pieces of the spec -> HOME/STYLE/APP conversion (standard engine).

Context carries the resolved spec, the raw spec (to tell what the author wrote from what dxpgen
filled in), the tier, the STYLE being built and the problems found. Converters (scripts/t3/<kind>.py)
call its helpers for colors, number formats, expressions and "not in the standard engine yet".
"""
import re

NOT_YET = "not in the standard engine yet: use --tier slim"
LEVELS = {"compact": 0, "quick": 1, "standard": 2, "report": 2}
COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
PROP_RE = re.compile(r"\[\$([A-Za-z0-9_.]+)\]")
IDENT_RE = re.compile(r"^\[(?:[^\]]|\]\])*\]$")
# "Calendar Period", "Flow Rate (bbl/d)": a column name, never an expression ("Count()" and
# "Sum(x)" have no space before the parenthesis)
PLAIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*?(?: \([^()\[\]<>\"']*\))?$")
NAMES_LEVEL = "[Axis.Default.Names]"
NAMES_AXIS = "<[Axis.Default.Names]>"
CATEGORY_TYPES = ("String", "Boolean")

# Style keys every kind accepts in app.style.visual.<kind> (they are also SPEC visual fields).
COMMON_STYLE_KEYS = (("showTitle", "bool", "compact"), ("legend", "bool", "compact"))
# app.style.visual.ref: chart reference lines (line and bar charts); labelFont also per layer.
REF_STYLE_KEYS = (("width", "size", "compact"), ("labelFont", "size", "quick"))


def blank(value):
    return value is None or value == "" or value == [] or value == {}


def esc(name):
    return "[" + str(name).replace("]", "]]") + "]"


def unwrap(text):
    t = text.strip()
    if len(t) >= 2 and t[0] == "<" and t[-1] == ">":
        return t[1:-1].strip()
    return t


def check_style_value(check, value, palette=None):
    """Problem text for a style value of the given check kind, or None."""
    if check == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if check == "size":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        return None if ok else "must be a positive number"
    if check in ("count", "width"):
        ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
        return None if ok else "must be a positive whole number"
    if check == "text":
        return None if isinstance(value, str) else "must be a string"
    if check == "format":
        return None if isinstance(value, str) and value.strip() else "must be a format name or format string"
    if check == "color":
        if value is None:
            return None
        if isinstance(value, str) and (COLOR_RE.match(value) or (
                value.startswith("@") and (palette is None or value[1:] in palette))):
            return None
        return "must be '#RRGGBB' or '@name' of app.style.palette (or null)"
    if check == "columns":
        ok = isinstance(value, list) and all(isinstance(x, str) and x for x in value)
        return None if ok else "must be a list of column names"
    if check == "negatives":
        if isinstance(value, bool):
            return None
        return check_style_value("columns", value)
    return None


def default_table_name(resolved):
    """spec defaultTable, else the first file table, else the first table (as verify_dxp reads it)."""
    if resolved.get("defaultTable"):
        return resolved["defaultTable"]
    tables = [t for t in resolved.get("tables") or [] if isinstance(t, dict) and t.get("name")]
    files = [t for t in tables if isinstance(t.get("source"), dict) and t["source"].get("type") in ("sbdf", "csv")]
    return (files or tables)[0]["name"] if (files or tables) else None


class Context(object):
    def __init__(self, resolved, raw, app_dir, tier, style, columns_of=None):
        self.resolved = resolved
        self.raw = raw if isinstance(raw, dict) else {}
        self.app_dir = app_dir
        self.tier = tier
        self.level = LEVELS[tier]
        self.style = style
        self.df_tables = {}           # dataFunction table -> declared column names (types unknown)
        for t in resolved.get("tables") or []:
            src = t.get("source") if isinstance(t, dict) and isinstance(t.get("source"), dict) else {}
            if src.get("type") == "dataFunction" and t.get("name"):
                cols = t.get("columns") if isinstance(t.get("columns"), dict) else {}
                self.df_tables[t["name"]] = list(cols)
        base = columns_of or (lambda table: None)

        def columns(table):
            found = base(table)
            if found is None and self.df_tables.get(table):
                return [(c, None) for c in self.df_tables[table]]
            return found
        self.columns_of = columns
        self.problems = []            # (path, message): blocks the build
        self.notes = []               # what the standard engine leaves out on purpose
        self.viz_manifests = {}       # visualization mod id -> parsed mod-manifest.json (vizMods)
        self.default_table = default_table_name(resolved)
        self.marking_name = "Marking"  # the default marking's name (build_app sets it before the pages)

    # ---- tiers and problems ---------------------------------------------------------------
    def has(self, tier):
        return self.level >= LEVELS[tier]

    def unsupported(self, path, what):
        self.problems.append((path, "%s is %s" % (what, NOT_YET)))

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def table(self, v):
        """The visual's table, else the default table (lib: B.table_or_default)."""
        return v.get("table") or self.default_table

    # ---- STYLE lookups ----------------------------------------------------------------------
    def default(self, kind, key, fallback=None):
        return self.style.get("visual", {}).get(kind, {}).get(key, fallback)

    def hexcode(self, value):
        if isinstance(value, str) and value.startswith("@"):
            return self.style["palette"].get(value[1:], value)
        return value

    def color(self, value, path):
        """A spec color for APP: '#RRGGBB' (or '@name'); '#FFRRGGBB' loses its opaque alpha."""
        if value is None:
            return None
        if isinstance(value, str) and value.startswith("@"):
            return value
        text = str(value)
        if len(text) == 9:
            if text[1:3].upper() != "FF":
                self.unsupported(path, "a color with transparency (%s)" % text)
                return "#" + text[3:]
            return "#" + text[3:]
        return text

    def same_color(self, a, b):
        ha, hb = self.hexcode(a), self.hexcode(b)
        if not (isinstance(ha, str) and isinstance(hb, str)):
            return ha == hb
        ha = ha.upper()
        hb = hb.upper()
        if len(ha) == 9 and ha[1:3] == "FF":
            ha = "#" + ha[3:]
        if len(hb) == 9 and hb[1:3] == "FF":
            hb = "#" + hb[3:]
        return ha == hb

    def format_name(self, fmt):
        """A format name of STYLE['formats'] for a format string (or a name), else the string."""
        if not isinstance(fmt, str) or not fmt:
            return fmt
        formats = self.style.get("formats", {})
        if fmt in formats:
            return fmt
        for name, text in formats.items():
            if text == fmt:
                return name
        return fmt

    # ---- expressions --------------------------------------------------------------------------
    def expr(self, value):
        """[$Name] -> DocumentProperty("Name"), numbers -> literals (lib/65_coloring reading)."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        return PROP_RE.sub(lambda m: 'DocumentProperty("%s")' % m.group(1), str(value).strip())

    def column_type(self, table, name):
        cols = self.columns_of(table)
        if not cols:
            return None
        for cname, ctype in cols:
            if cname == name:
                return ctype
        return None

    def column(self, text, table):
        """A bare column name of the table -> [Name] (lib/60_charts reading). When the data file
        cannot be read, a plain name (no brackets, parentheses, operators or quotes: it cannot be
        an expression) is taken for a column too, as the library does against the loaded table."""
        if text and text[0] not in "[<":
            cols = self.columns_of(table)
            if cols:
                if any(c == text for c, _ in cols):
                    return esc(text)
            elif PLAIN_NAME_RE.match(text):
                return esc(text)
        return text

    def axis(self, value, table, categorical_strings=True, unknown_categorical=False):
        """Line/bar x and colorBy: an expression, or a list of levels -> <A NEST B>; a plain String or
        Boolean column becomes the category <[Col]> (lib/60_charts.py _charts_category_column).
        unknown_categorical: a bare column of a data-function table (its type is only known after
        the run) is taken for a category too (colorBy, bar x)."""
        if isinstance(value, (list, tuple)):
            return self.cat(value, table)
        text = self.expr(self.column(str(value).strip(), table))
        if categorical_strings and IDENT_RE.match(text):
            ctype = self.column_type(table, text[1:-1].replace("]]", "]"))
            if ctype in CATEGORY_TYPES or (unknown_categorical and ctype is None
                                           and table in self.df_tables):
                return "<" + text + ">"
        return text

    def measures(self, value, table):
        """y: one expression or a list (several measures, joined by the engine)."""
        if isinstance(value, (list, tuple)):
            return [self.expr(self.column(str(v).strip(), table)) for v in value if not blank(v)]
        return self.expr(self.column(str(value).strip(), table))

    def cat(self, value, table):
        """Categorical axis: a list of levels or one expression -> <A NEST B> ('<>' when empty)."""
        levels = []
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if blank(item):
                continue
            inner = unwrap(str(item))
            if inner:
                levels.append(self.expr(self.column(inner, table)))
        return "<" + " NEST ".join(levels) + ">" if levels else "<>"

    def levels(self, value, table):
        """Cross-table levels (lib/70_tables.py _tables_levels)."""
        out = []
        items = value if isinstance(value, (list, tuple)) else ([] if value is None else [value])
        for item in items:
            text = unwrap(str(item))
            if not text:
                continue
            out.append(self.expr(self.column(text, table)))
        return out
