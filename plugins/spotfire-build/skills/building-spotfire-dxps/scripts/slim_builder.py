#!/usr/bin/env python3
"""slim_builder - an IronPython builder that holds only the library code one app's spec needs.

Part of the building-spotfire-dxps skill. CPython 3.10 or newer, standard library only.

    python scripts/slim_builder.py <app> [--tag TAG] [--out FILE] [--indent {2,4}] [--clipboard]
                                 [--no-lint] [--no-sanitize] [--tools-dir DIR]

`dxpgen.py build` concatenates every lib/[0-9][0-9]_*.py module, so every builder carries every
feature (about 450,000 characters): too big to paste and compile in Analyst's script editor. This
tool validates and resolves the spec exactly like dxpgen.py (it imports dxpgen and calls
validate_app, resolve_spec, library_files, render_builder, ...) and writes a builder with only
what this spec reaches:

  1. Call-graph reachability. Roots: run_build, BuildContext and the VISUAL_BUILDERS functions of
     the visual types the spec uses (VISUAL_BUILDERS itself is cut down to them). Names are
     followed, and so are string constants that name a library function (the globals().get(...)
     lookups of 60_charts). Top-level functions, constants and imported names nothing reaches are
     dropped, and with them whole modules (maps, mods, data functions, ...).
  2. Feature gates (GATES). Some functions only run for a spec feature: data functions, scripts,
     triggers, text-area controls, CSV tables, trellis, fitting models, ... When the spec does not
     use the feature, the gate stops the walk there. Kept code that still names such a function
     gets a one-line stub, name = _slim_stub('name'), that raises if it is ever reached with work
     to do (called with nothing but empty arguments it returns None, like the list-level steps).
  3. Docstrings and comments go (ast.unparse); "# noqa" directives stay. Blocks are indented two
     spaces (--indent 4 for four, about 7% larger). Every line is re-wrapped to at most 79
     characters and each wrapped statement must parse to the same AST as before.
  4. The resolved spec follows as a literal with short lines (it must literal_eval back to the
     resolved spec), then APP_DIR, the BuildContext line and run_build(), as in the full builder.

--tag TAG saves the analysis as '<app.output stem> TAG.dxp' (this build only; spec.json is not
touched); build-report.json, MANUAL-STEPS.md and snapshots/ still go next to it.
Default output: build/build_<AppSlug>_slim[_<tag>].py. Exit codes as dxpgen.py: 0 ok, 1 validation
errors or a failed check of the generated builder, 2 usage. Nothing runs in Spotfire: the user
pastes the builder into Analyst's script editor and clicks Run Script.
"""
import argparse
import ast
import builtins
import datetime
import io
import json
import os
import re
import sys
import tokenize
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
import dxpgen  # noqa: E402  (the one place that resolves specs and lists the library)

LIMIT = 79                    # longest line of the generated builder
INDENT = "  "                 # block indentation (--indent 4 for ast.unparse's four spaces)
SPEC_STEP = " "               # indentation step of the spec literal
SCRIPT_GLOBALS = {"Document", "Application"}
ROOTS = ("run_build", "BuildContext")
STUB_HELPER = "_slim_stub"


# ---------------------------------------------------------------------------------------------
# feature gates: (feature, used(resolved spec) -> bool, library functions that only run for it)
# A predicate must be True whenever the library could call one of its functions for this spec
# (when in doubt it says True: that only costs size).
# ---------------------------------------------------------------------------------------------
def _dicts(obj):
    """Every dict inside obj (obj included), depth first."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)


def _has(obj, key, test=bool):
    return any(test(d[key]) for d in _dicts(obj) if key in d)


def _visuals(spec, vtype=None):
    for page in spec.get("pages") or []:
        for v in (page.get("visuals") or []) if isinstance(page, dict) else []:
            if isinstance(v, dict) and (vtype is None or v.get("type") == vtype):
                yield v


def _not_none(value):
    return value is not None


def _pages(spec):
    return spec.get("pages") or []


def _tables(spec):
    return [t for t in spec.get("tables") or [] if isinstance(t, dict)]


def _column_specs(spec):
    for t in _tables(spec):
        columns = t.get("columns")
        for c in (columns.values() if isinstance(columns, dict) else []):
            if isinstance(c, dict):
                yield c


def _scale_titles(spec):
    return any(isinstance(v.get(k), dict) and v[k].get("title") is not None
               for v in _visuals(spec) for k in ("xScale", "yScale", "zScale"))


def _duplicate_titles(spec):
    titles = [p.get("title") for p in _pages(spec) if isinstance(p, dict)]
    return len(titles) != len(set(titles))


def _text_areas(spec, key):
    return any(v.get(key) for v in _visuals(spec, "textArea"))


GATES = (
    ("document properties", lambda s: bool(s.get("properties")), ("data_add_properties",)),
    ("relations", lambda s: bool(s.get("relations")), ("data_relations",)),
    ("filtering schemes", lambda s: bool(s.get("filteringSchemes")), ("data_filtering_schemes",)),
    ("data functions", lambda s: bool(s.get("dataFunctions")), ("df_build_all",)),
    ("IronPython scripts", lambda s: bool(s.get("scripts")), ("scripts_add_all",)),
    ("property triggers", lambda s: bool(s.get("triggers")), ("scripts_add_triggers",)),
    ("the built-in marking (spec without markings)", lambda s: not s.get("markings"),
     ("_data_builtin_marking",)),
    ("CSV tables", lambda s: any((t.get("source") or {}).get("type") == "csv" for t in _tables(s)),
     ("_data_csv_settings", "_data_code_page", "_data_check_column_types")),
    ("calculated columns", lambda s: _has(_tables(s), "calculatedColumns"), ("_data_calculated_column",)),
    ("hierarchies", lambda s: _has(_tables(s), "hierarchies"), ("_data_hierarchy",)),
    ("column descriptions", lambda s: any(c.get("description") for c in _column_specs(s)),
     ("_data_column_description",)),
    ("column settings", lambda s: any(c.get("settings") for c in _column_specs(s)), ("_data_column_settings",)),
    ("clearing theme styles (spec without customStyles)",
     lambda s: not ((s.get("app") or {}).get("theme") or {}).get("customStyles"), ("_document_clear_styles",)),
    ("duplicate page titles", _duplicate_titles, ("_pages_duplicate",)),
    ("trellis", lambda s: _has(_pages(s), "trellis"), ("_charts_set_trellis",)),
    ("log scales", lambda s: _has(_pages(s), "log"), ("_charts_set_log",)),
    ("scale gridlines", lambda s: _has(_pages(s), "gridlines", _not_none), ("_charts_set_gridlines",)),
    ("individual scaling", lambda s: _has(_pages(s), "individualScaling"), ("_charts_set_individual",)),
    ("scale titles", _scale_titles, ("_charts_titled", "_charts_titled_ok")),
    ("line widths", lambda s: _has(_pages(s), "lineWidth", _not_none), ("_charts_set_line_width",)),
    ("labels", lambda s: _has(_pages(s), "labels", _not_none) or _has(_pages(s), "labelBy"),
     ("_charts_set_labels",)),
    ("bar orientation and sorting", lambda s: _has(_pages(s), "orientation") or _has(_pages(s), "sort"),
     ("_charts_set_orientation", "_charts_set_sort", "_charts_set_bar_order")),
    ("bar stacking", lambda s: _has(_pages(s), "stack"), ("_charts_set_stack",)),
    ("visual descriptions", lambda s: any(v.get("description") for v in _visuals(s)),
     ("_charts_set_description",)),
    ("limit by markings", lambda s: _has(_pages(s), "limitByMarkings"), ("_charts_add_limit", "_charts_set_empty")),
    ("postScript", lambda s: _has(_pages(s), "postScript"), ("_charts_post", "_tables_post_script")),
    ("reference layers", lambda s: _has(_pages(s), "referenceLayers"), ("apply_reference_layers",)),
    ("fitting models", lambda s: _has(_pages(s), "fittingModels"), ("apply_fitting_models",)),
    ("'equal' coloring rules", lambda s: _has(_pages(s), "type", lambda v: v == "equal"),
     ("_coloring_equal_rule",)),
    ("KPI coloring", lambda s: any(_has(v, "coloring") for v in _visuals(s, "kpiChart")),
     ("coloring_apply_kpi",)),
    ("table sorting", lambda s: any(v.get("sort") for v in _visuals(s, "table")), ("_tables_table_sort",)),
    ("table column widths", lambda s: any(v.get("widths") for v in _visuals(s, "table")),
     ("_tables_table_widths",)),
    ("table coloring", lambda s: any(v.get("coloring") for v in _visuals(s, "table")),
     ("_tables_table_coloring",)),
    ("cross-table totals", lambda s: any(v.get("totals") for v in _visuals(s, "crossTable")),
     ("_tables_cross_totals",)),
    ("cross-table coloring", lambda s: any(v.get("coloring") for v in _visuals(s, "crossTable")),
     ("_tables_cross_coloring",)),
    ("text-area controls", lambda s: _text_areas(s, "controls"),
     ("_textareas_make_control", "_textareas_manual")),
    ("text-area CSS", lambda s: _text_areas(s, "css"),
     ("_textareas_style_class", "_textareas_css_name", "_textareas_css_js")),
    ("text-area CSS and JavaScript", lambda s: _text_areas(s, "css") or _text_areas(s, "js"),
     ("_textareas_attach", "_textareas_js_manual")),
)


def gated_off(spec):
    """{function name: feature} for every gate whose feature this spec does not use."""
    off = {}
    for feature, used, names in GATES:
        if not used(spec):
            for name in names:
                off[name] = feature
    return off


# ---------------------------------------------------------------------------------------------
# library units and reachability
# ---------------------------------------------------------------------------------------------
class Unit(object):
    """One top-level statement of one lib module."""

    def __init__(self, module, node):
        self.module = module
        self.node = node
        self.refs = set()        # names loaded anywhere inside
        self.strs = set()        # string constants inside
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            self.kind = "def"
            self.names = [node.name]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.kind = "import"
            self.names = [(a.asname or a.name).split(".")[0] for a in node.names]
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            self.kind = "assign"
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            self.names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
        else:
            self.kind = "other"   # module-level side effects such as clr.AddReference(...)
            self.names = []
        if self.kind != "import":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and not isinstance(sub.ctx, ast.Store):
                    self.refs.add(sub.id)
                elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    self.strs.add(sub.value)
            if isinstance(node, ast.AugAssign):
                self.refs.update(self.names)


def library_units(parts):
    units = []
    for module, text in parts:
        tree = ast.parse(text, filename="lib/" + module)
        for node in tree.body:
            units.append(Unit(module, node))
    return units


def used_visual_types(spec):
    return [t for t in dict.fromkeys(v.get("type") for v in _visuals(spec)) if isinstance(t, str)]


def visual_builders(units):
    for u in units:
        if u.kind == "assign" and u.names == ["VISUAL_BUILDERS"]:
            return u, ast.literal_eval(u.node.value)
    raise ValueError("lib/90_build.py defines no VISUAL_BUILDERS")


def shake(units, spec, off):
    """Walk the call graph from the roots. Returns (needed names, stub names, VISUAL_BUILDERS)."""
    vb_unit, builders = visual_builders(units)
    used = dict((t, builders[t]) for t in used_visual_types(spec) if t in builders)
    vb_unit.strs = set()                        # its strings are the dispatch table, cut down below
    vb_unit.node = ast.Assign(targets=[ast.Name("VISUAL_BUILDERS", ast.Store())],
                              value=ast.Dict([ast.Constant(k) for k in used],
                                             [ast.Constant(v) for v in used.values()]))
    by_name = {}
    for u in units:
        for n in u.names:
            by_name.setdefault(n, []).append(u)
    functions = set(n for u in units if u.kind == "def" for n in u.names)
    queue = list(ROOTS) + list(used.values())
    for u in units:
        if u.kind == "other":
            queue.extend(u.refs)
    needed = set()
    while queue:
        name = queue.pop()
        if name in needed or name in off or name not in by_name:
            continue
        needed.add(name)
        for u in by_name[name]:
            queue.extend(u.refs)
            queue.extend(s for s in u.strs if s in functions)
    kept = [u for u in units if u.kind == "other" or (u.kind != "import" and set(u.names) & needed)]
    stubs = set()
    for u in kept:
        stubs.update(r for r in u.refs if r in off and r in functions)
    return needed, stubs, used


# ---------------------------------------------------------------------------------------------
# docstrings, comments, noqa directives
# ---------------------------------------------------------------------------------------------
class _StripDocstrings(ast.NodeTransformer):
    """Remove bare string statements (docstrings, string 'comments'); empty bodies get `pass`."""

    def generic_visit(self, node):
        super().generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list) or not stmts or not isinstance(stmts[0], ast.stmt):
                continue
            kept = [s for s in stmts if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                            and isinstance(s.value.value, str))]
            setattr(node, field, kept or [ast.Pass()])
        return node


_NOQA_RE = re.compile(r"#\s*noqa(?::\s*([A-Za-z0-9_,\- ]+?))?\s*(?:\(|$)")


def noqa_comments(module_text):
    """{one-line unparsed statement: '# noqa[: rules]'} for statements carrying a noqa comment."""
    lines = {}
    for tok in tokenize.generate_tokens(io.StringIO(module_text).readline):
        if tok.type == tokenize.COMMENT:
            m = _NOQA_RE.search(tok.string)
            if m:
                rules = (m.group(1) or "").strip()
                lines[tok.start[0]] = "# noqa: " + rules if rules else "# noqa"
    found = {}
    if lines:
        for node in ast.walk(ast.parse(module_text)):
            if isinstance(node, ast.stmt) and node.lineno in lines:
                found.setdefault(ast.unparse(node).split("\n")[0].strip(), lines[node.lineno])
    return found


def unparse_unit(node, indent):
    """Source of one top-level statement: no docstrings or comments, `indent` per block level."""
    text = ast.unparse(ast.fix_missing_locations(_StripDocstrings().visit(node)))
    if indent == "    ":
        return text
    out = []
    for line in text.split("\n"):
        body = line.lstrip(" ")
        out.append(indent * ((len(line) - len(body)) // 4) + body)
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# re-wrapping: one logical line (as ast.unparse writes it) -> physical lines <= LIMIT
# ---------------------------------------------------------------------------------------------
class _NoBreak(Exception):
    pass


_OPENERS = ("(", "[", "{")
_CLOSERS = (")", "]", "}")
_NO_BREAK_BEFORE = {")", "]", "}", ",", ":", ".", "(", "[", "=", ";"}
_OPERATORS = {"+", "-", "*", "/", "//", "%", "**", "==", "!=", "<", ">", "<=", ">=", "|", "&", "^",
              "<<", ">>", "and", "or", "if", "else", "for", "in", "is", "not"}
_STATEMENT_KEYWORDS = {"assert", "break", "continue", "del", "from", "global", "import", "nonlocal",
                       "pass", "raise", "return", "yield", "if", "elif", "else", "while", "for", "try",
                       "except", "finally", "with", "def", "class", "lambda"}


class _Atom(object):
    __slots__ = ("sep", "text", "kind", "depth", "span")

    def __init__(self, sep, text, kind, depth, span=0):
        self.sep = sep          # whitespace before the token in the one-line form
        self.text = text
        self.kind = kind        # tokenize token type
        self.depth = depth      # bracket depth before the token
        self.span = span        # opening bracket: width of its content up to the closing one


def _set_spans(atoms):
    stack = []
    width = 0
    for a in atoms:
        if a.kind == tokenize.OP and a.text in _CLOSERS and stack:
            opener, start = stack.pop()
            opener.span = width - start
        width += len(a.sep) + len(a.text)
        if a.kind == tokenize.OP and a.text in _OPENERS:
            stack.append((a, width))
    return atoms


def _atoms(code):
    out = []
    depth = 0
    prev = 0
    for tok in tokenize.generate_tokens(io.StringIO(code + "\n").readline):
        if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.INDENT,
                        tokenize.DEDENT, tokenize.COMMENT):
            continue
        if tok.start[0] != 1 or tok.end[0] != 1:
            raise ValueError("not a one-line statement: " + code[:70])
        out.append(_Atom(code[prev:tok.start[1]], tok.string, tok.type, depth))
        prev = tok.end[1]
        if tok.type == tokenize.OP and tok.string in _OPENERS:
            depth += 1
        elif tok.type == tokenize.OP and tok.string in _CLOSERS:
            depth -= 1
    return _set_spans(out)


def _render(atoms, lead):
    return lead + atoms[0].text + "".join(a.sep + a.text for a in atoms[1:])


def _quality(prev, atom, backslash):
    """How good a line break between prev and atom is (higher is better), None = not allowed.
    Inside brackets any break is legal Python; at depth 0 only with a backslash."""
    if atom.depth == 0 and not backslash:
        return None
    if atom.kind == tokenize.OP and atom.text in _NO_BREAK_BEFORE:
        return None
    if prev.text == "." or (prev.text, atom.text) in (("not", "in"), ("is", "not")):
        return None
    if prev.kind == tokenize.STRING and atom.kind == tokenize.STRING:
        return 4
    if prev.text == ",":
        return 4
    if prev.kind == tokenize.OP and prev.text in _OPENERS:
        return 3 if prev.span > 30 else 0       # never str(<newline>n) for a short bracket
    if atom.text in _OPERATORS:
        return 2
    if prev.text in _OPERATORS or prev.text == "=":
        return 0
    return 1


def _choose(cur, lead, room, backslash):
    """(k, backslash) = break before cur[k] whose first part fits, or None."""
    candidates = []
    width = len(lead) + len(cur[0].text)
    for k in range(1, len(cur)):
        q = _quality(cur[k - 1], cur[k], backslash)
        bs = cur[k].depth == 0
        if q is not None and width + (2 if bs else 0) <= room:
            candidates.append((k, q, width, bs))
        width += len(cur[k].sep) + len(cur[k].text)
    if not candidates:
        return None
    right = max(c[2] for c in candidates)
    k, q, w, bs = max((c for c in candidates if c[2] >= right - 25), key=lambda c: (c[1], c[0]))
    return k, bs


def _attached(queue, i, backslash):
    """Width of the atoms from queue[i] on that cannot start a line (closing brackets, commas)."""
    width = 0
    while i < len(queue):
        q = _quality(queue[i - 1], queue[i], backslash)
        if q is not None:
            return width + (2 if queue[i].depth == 0 else 0)
        width += len(queue[i].sep) + len(queue[i].text)
        i += 1
    return width


def _encode(value):
    return ascii(value)


def split_string(value, first_room, rest_room, tail=0):
    """Adjacent ASCII literals for a str value: the first at most first_room characters wide, the
    others rest_room; the last leaves `tail` characters free. Cuts after a space when one is near."""
    if len(_encode(value)) + tail <= first_room:
        return [_encode(value)]
    out = []
    pos = 0
    room = first_room
    n = len(value)
    while pos < n:
        end = pos
        while end < n and len(_encode(value[pos:end + 1])) + (tail if end + 1 == n else 0) <= room:
            end += 1
        if end == pos:
            if room == rest_room:
                raise _NoBreak()
            out.append(None)                  # nothing fits after the prefix: start on a new line
            room = rest_room
            continue
        if end < n:
            cut = value.rfind(" ", pos, end)
            if cut >= pos + (end - pos) // 2:
                end = cut + 1
        out.append(_encode(value[pos:end]))
        pos = end
        room = rest_room
    return out


def _string_value(text):
    prefix = re.match(r"[A-Za-z]*", text).group(0).lower()
    if "b" in prefix or "f" in prefix or "t" in prefix:
        raise _NoBreak()
    return ast.literal_eval(text)


def _fill(atoms, indent, cont, limit, extra, backslash):
    """Greedy line filling. A string atom is checked together with the closing brackets and commas
    glued to it; one too long for a fresh continuation line is split into adjacent literals (the
    first one using the rest of the current line)."""
    lines = []
    cur = []
    lead = indent
    room = limit - extra
    queue = list(atoms)
    i = 0
    while i < len(queue):
        cur.append(queue[i])
        i += 1
        while True:
            last = cur[-1]
            is_str = last.kind == tokenize.STRING
            tail = _attached(queue, i, backslash) if is_str else 0
            if len(_render(cur, lead)) + tail <= room:
                break
            prefix = _render(cur[:-1], lead) if len(cur) > 1 else None
            before = len(prefix + last.sep) if prefix is not None else len(lead)
            can_break = prefix is not None and _quality(cur[-2], last, backslash) is not None
            bs = last.depth == 0
            if is_str and len(cont) + len(last.text) + tail > limit:
                # too long even alone on a continuation line: split it here
                if can_break and room - before < 16 and len(prefix) + (2 if bs else 0) <= room:
                    lines.append(prefix + (" \\" if bs else ""))
                    cur, lead, room = [last], cont, limit
                    continue
                pick = None
            else:
                pick = _choose(cur, lead, room, backslash)
            if pick is not None:
                k, k_bs = pick
                lines.append(_render(cur[:k], lead) + (" \\" if k_bs else ""))
                cur, lead, room = cur[k:], cont, limit
                continue
            if not (is_str and (last.depth > 0 or backslash)):
                raise _NoBreak()
            chunks = split_string(_string_value(last.text), room - before, limit - len(cont), tail)
            if chunks[0] is None or len(chunks) == 1:
                raise _NoBreak()
            pieces = [_Atom(" ", c, tokenize.STRING, last.depth) for c in chunks]
            pieces[0].sep = last.sep
            cur[-1] = queue[i - 1] = pieces[0]
            queue[i:i] = pieces[1:]
    lines.append(_render(cur, lead))
    return lines


def _parenthesize(atoms):
    """The atoms with ( ) around the expression of a simple statement or compound header, so that
    the wrapper may break inside it; None when there is no such expression."""
    header = atoms[-1].text == ":" and atoms[-1].depth == 0
    end = len(atoms) - 1 if header else len(atoms)
    first = atoms[0]
    start = None
    if first.kind == tokenize.NAME and first.text in ("return", "if", "elif", "while"):
        start = 1
    elif first.kind == tokenize.NAME and first.text in ("for", "from"):
        word = "in" if first.text == "for" else "import"     # for <target> in <expr>: / from x import a, b
        for j, a in enumerate(atoms):
            if a.depth == 0 and a.kind == tokenize.NAME and a.text == word:
                start = j + 1
                break
    elif not header:
        for j, a in enumerate(atoms):
            if a.depth == 0 and a.kind == tokenize.OP and a.text.endswith("=") \
                    and a.text not in ("==", "!=", "<=", ">="):
                start = j + 1
        if start is None and not (first.kind == tokenize.NAME and first.text in _STATEMENT_KEYWORDS):
            start = 0
    if start is None or start >= end:
        return None
    inner = [_Atom(a.sep, a.text, a.kind, a.depth + 1) for a in atoms[start:end]]
    opening = _Atom(inner[0].sep, "(", tokenize.OP, 0)
    inner[0].sep = ""
    return _set_spans(atoms[:start] + [opening] + inner + [_Atom("", ")", tokenize.OP, 1)] + atoms[end:])


def wrap_line(line, limit=LIMIT, comment=None):
    """One logical line -> physical lines of at most `limit` characters (comment on the first)."""
    body = line.lstrip(" ")
    indent = line[:len(line) - len(body)]
    tail = ("  " + comment) if comment else ""
    if len(line) + len(tail) <= limit:
        return [line + tail]
    atoms = _atoms(body)
    header = atoms[-1].text == ":" and atoms[-1].depth == 0
    # continuation lines: 4 deeper; a compound header's must also clear its body's indentation
    cont = indent + (" " * max(4, 2 * len(INDENT)) if header else "    ")
    for mode in ("brackets", "parentheses", "backslash"):
        seq = _parenthesize(atoms) if mode == "parentheses" else atoms
        if seq is None:
            continue
        try:
            lines = _fill(seq, indent, cont, limit, len(tail), mode == "backslash")
        except _NoBreak:
            continue
        if tail:
            if lines[0].endswith("\\"):
                raise ValueError("cannot keep '%s' on a continued line: %s" % (comment, line.strip()))
            lines[0] += tail
        return lines
    raise ValueError("cannot wrap to %d characters: %s" % (limit, line.strip()))


def wrap_source(text, noqa=None, limit=LIMIT):
    """Re-wrap source made of one-line logical lines; the result must parse to the same AST."""
    out = []
    for line in text.split("\n"):
        comment = (noqa or {}).get(line.strip())
        out.extend(wrap_line(line, limit, comment))
    wrapped = "\n".join(out)
    if ast.dump(ast.parse(wrapped)) != ast.dump(ast.parse(text)):
        raise ValueError("re-wrapping changed the code:\n" + text[:300])
    return wrapped


# ---------------------------------------------------------------------------------------------
# the resolved spec as a literal with short lines
# ---------------------------------------------------------------------------------------------
def _flat(obj):
    if isinstance(obj, str):
        return _encode(obj)
    if obj is None or isinstance(obj, (bool, int, float)):
        return repr(obj)
    if isinstance(obj, dict):
        return "{" + ", ".join(_flat(k) + ": " + _flat(v) for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ", ".join(_flat(v) for v in obj) + "]"
    raise TypeError("not a JSON value in the resolved spec: %r" % (obj,))


def _literal(obj, lead, prefix, suffix, limit, step):
    """Lines of `lead + prefix + <literal of obj> + suffix`, none longer than limit. Containers are
    packed: items share a line while they fit (the first one on the bracket's line), an item too
    long for a line of its own is laid out the same way one level deeper."""
    one = lead + prefix + _flat(obj) + suffix
    if len(one) <= limit:
        return [one]
    inner = lead + step
    if isinstance(obj, (dict, list)) and obj:
        if isinstance(obj, dict):
            opener, closer = "{", "}"
            items = [(_flat(k) + ": ", v) for k, v in obj.items()]
        else:
            opener, closer = "[", "]"
            items = [("", v) for v in obj]
        lines = [lead + prefix + opener]
        fresh = True                                  # the last line ends with the opener
        for n, (item_prefix, value) in enumerate(items):
            end = (closer + suffix) if n == len(items) - 1 else ","
            flat = item_prefix + _flat(value) + end
            gap = "" if fresh else " "
            if len(lines[-1]) + len(gap) + len(flat) <= limit:
                lines[-1] += gap + flat
            elif len(inner) + len(flat) <= limit:
                lines.append(inner + flat)
            else:
                lines.extend(_literal(value, inner, item_prefix, end, limit, step))
            fresh = False
        return lines
    if isinstance(obj, str):
        head = lead + prefix + "("
        chunks = split_string(obj, max(limit - len(head), 0), limit - len(inner), len(")" + suffix))
        if chunks[0] is None:
            lines, chunks = [head], chunks[1:]
        else:
            lines, chunks = [head + chunks[0]], chunks[1:]
        lines += [inner + c for c in chunks]
        lines[-1] += ")" + suffix
        return lines
    raise ValueError("cannot fit %s in %d characters" % (one.strip()[:60], limit))


def spec_literal(resolved, limit=LIMIT, step=SPEC_STEP):
    """'SPEC = {...}' lines; literal_eval of the literal must give the resolved spec back."""
    lines = _literal(resolved, "", "SPEC = ", "", limit, step)
    text = "\n".join(lines)
    if ast.literal_eval(text[len("SPEC = "):]) != resolved:
        raise ValueError("the spec literal does not round-trip")
    return text


# ---------------------------------------------------------------------------------------------
# checks of the generated builder
# ---------------------------------------------------------------------------------------------
def _scope_names(node):
    """Names bound inside a function or class (parameters, assignments, imports, nested defs)."""
    bound = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and sub is not node:
            bound.add(sub.name)
        elif isinstance(sub, ast.arg):
            bound.add(sub.arg)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in sub.names)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
    return bound


def undefined_names(text):
    """{name: count} of names the builder loads (calls included) that nothing defines: not a
    top-level name, not bound in the enclosing function, not a builtin or a script global."""
    tree = ast.parse(text)
    top = set(SCRIPT_GLOBALS) | set(dir(builtins))
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
            top.add(stmt.name)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            top.update((a.asname or a.name).split(".")[0] for a in stmt.names)
        else:
            top.update(n.id for n in ast.walk(stmt) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
    missing = {}
    for stmt in tree.body:
        bound = _scope_names(stmt) if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)) else set()
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in top \
                    and sub.id not in bound:
                missing[sub.id] = missing.get(sub.id, 0) + 1
    return missing


def text_problems(text, limit=LIMIT):
    problems = []
    for n, line in enumerate(text.split("\n"), 1):
        if len(line) > limit:
            problems.append("line %d is %d characters long" % (n, len(line)))
        if not line.isascii():
            problems.append("line %d is not ASCII" % n)
        if "\t" in line:
            problems.append("line %d has a tab" % n)
    return problems


# ---------------------------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------------------------
def tagged_output(output, tag):
    """'build/Well Tear Sheet.dxp' + 'v2' -> 'build/Well Tear Sheet v2.dxp'."""
    stem, ext = os.path.splitext(output)
    return stem + " " + tag + (ext or ".dxp")


def slim_library(parts, resolved):
    """(code, info): the library code this spec reaches, unparsed and re-wrapped."""
    units = library_units(parts)
    off = gated_off(resolved)
    needed, stubs, builders = shake(units, resolved, off)
    noqa = {}
    for module, text in parts:
        noqa.update(noqa_comments(text))
    sections = []
    module_stats = {}
    imported = {}                          # local name -> import key bound most recently
    seen_other = set()
    for module, text in parts:
        chunk = []
        kept_defs, dropped_defs = [], []
        for u in (x for x in units if x.module == module):
            if u.kind == "import":
                aliases = []
                for a in u.node.names:
                    local = (a.asname or a.name).split(".")[0]
                    key = (getattr(u.node, "module", None), a.name, a.asname, getattr(u.node, "level", 0))
                    if local in needed and imported.get(local) != key:
                        aliases.append(a)
                        imported[local] = key
                if not aliases:
                    continue
                node = (ast.ImportFrom(u.node.module, aliases, u.node.level)
                        if isinstance(u.node, ast.ImportFrom) else ast.Import(aliases))
                chunk.append(("simple", wrap_source(ast.unparse(node), noqa)))
                continue
            if u.kind == "other":
                source = ast.unparse(u.node)
                if source not in seen_other:
                    seen_other.add(source)
                    chunk.append(("simple", wrap_source(source, noqa)))
                continue
            name = u.names[0] if u.names else ""
            if not set(u.names) & needed:
                if u.kind == "def":
                    dropped_defs.append(name)
                continue
            for local in u.names:
                imported.pop(local, None)
            source = unparse_unit(u.node, INDENT)
            chunk.append(("def" if u.kind == "def" else "simple", wrap_source(source, noqa)))
            if u.kind == "def":
                kept_defs.append(name)
        module_stats[module] = (kept_defs, dropped_defs)
        if chunk:
            sections.append((module, chunk))
    # stubs for gated functions that kept code still names, in library order
    stub_nodes = []
    for u in units:
        if u.kind == "def" and u.names[0] in stubs:
            stub_nodes.append(_stub(u.node))
    lines = []
    for module, chunk in sections:
        lines.append("# " + "-" * 20 + " lib/" + module)
        prev = None
        for kind, source in chunk:
            if kind == "def" or prev == "def":
                lines.append("")
            lines.append(source)
            prev = kind
        lines.append("")
    if stub_nodes:
        features = sorted(set(off[n] for n in stubs), key=lambda f: f.strip("'").lower())
        lines.append("# " + "-" * 20 + " not in this slim builder (stubs raise if reached)")
        for feature_line in _wrap_words("# features: " + ", ".join(features), "#   "):
            lines.append(feature_line)
        lines.append(wrap_source(unparse_unit(_stub_factory(), INDENT)))
        for node in stub_nodes:
            lines.append(wrap_source(unparse_unit(node, INDENT)))
        lines.append("")
    info = {"modules": module_stats, "stubs": sorted(stubs), "gatedOff": off, "builders": builders,
            "needed": needed}
    return "\n".join(lines).rstrip("\n") + "\n", info


def _wrap_words(text, cont, limit=LIMIT):
    out = []
    line = ""
    for word in text.split(" "):
        candidate = (line + " " + word) if line else word
        if len(candidate) > limit and line:
            out.append(line)
            candidate = cont + word
        line = candidate
    out.append(line)
    return out


def _stub_factory():
    """The stub maker: a stub returns None when called with nothing to do (only empty arguments,
    as the list-level steps of 90_build are for a spec without that feature), else raises."""
    return ast.parse(
        "def %s(name):\n"
        "    def stub(*args, **kwargs):\n"
        "        if args and not [a for a in args if a]:\n"
        "            return None\n"
        "        raise Exception(name + '() is not in this slim builder: the spec did not use it when '\n"
        "                        'the builder was generated (rebuild with scripts/slim_builder.py)')\n"
        "    return stub\n" % STUB_HELPER).body[0]


def _stub(node):
    """name = _slim_stub('name') for a gated library function that kept code still names."""
    call = ast.Call(ast.Name(STUB_HELPER, ast.Load()), [ast.Constant(node.name)], [])
    return ast.fix_missing_locations(ast.Assign([ast.Name(node.name, ast.Store())], call))


def render_slim(resolved, app_dir, slug, spec_sha, lib_sha, code, info, tag, generated):
    app = resolved.get("app", {})
    out_rel = str(app.get("output", "")).replace("/", "\\")
    modules = [m[:-3] for m, (kept, _) in info["modules"].items() if kept]
    header = []
    for text in ("# %s - slim Spotfire DXP builder%s, IronPython 3."
                 % (app.get("name", ""), (" (tag " + tag + ")") if tag else ""),
                 "# Generated by scripts/slim_builder.py on %s from spec.json %s and "
                 "the parts of lib/ it needs: %s." % (generated[:10], spec_sha[:16], ", ".join(modules)),
                 "# Saves %s with build-report.json, MANUAL-STEPS.md and snapshots\\ next to it."
                 % out_rel):
        header += _wrap_words(text, "#   ")
    header += [
        "#",
        "# Run it (you start it; nothing runs automatically):",
        "#   1. File > New and add any starter data (Analyst opens the script",
        "#      editor only when the analysis has data; the builder removes it).",
        "#   2. Edit > Document Properties > Scripts > New, IronPython 3; untick",
        "#      \"Execute in transaction\" (inside a transaction Spotfire refuses",
        "#      the save), paste this whole file and click Run Script.",
        "#   3. Close the dialog with Cancel (OK would store the builder inside",
        "#      the analysis). The analysis saves itself.",
        "# Do not edit: change spec.json and run scripts/slim_builder.py again.",
        "",
    ]
    trailer = [
        spec_literal(resolved),
        "\n".join(wrap_line("APP_DIR = " + dxpgen.path_literal(app_dir))),
        "B = BuildContext(",
        "    SPEC, APP_DIR, Document, Application,",
        "    %s," % json.dumps(spec_sha),
        "    %s)" % json.dumps(lib_sha),
        "run_build()",
    ]
    return "\n".join(header) + "\n" + code + "\n" + "\n".join(trailer) + "\n"


def check_builder(text, resolved):
    """[(level, message)] for the generated builder (all must hold before it is written)."""
    issues = []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [("error", "the slim builder does not parse: %s (line %s)" % (e.msg, e.lineno))]
    issues += [("error", p) for p in text_problems(text)[:20]]
    for name, count in sorted(undefined_names(text).items()):
        issues.append(("error", "%s is used %d time(s) but never defined (removed by the shaking?)" % (name, count)))
    for level, message in dxpgen.library_check([("slim", text)], resolved):
        issues.append((level, message))
    spec_node = next((s for s in tree.body if isinstance(s, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "SPEC" for t in s.targets)), None)
    if spec_node is None or ast.literal_eval(spec_node.value) != resolved:
        issues.append(("error", "SPEC in the builder is not the resolved spec"))
    return issues


def mod_layer_paths(spec):
    """Paths of mod visuals that give "layers": lib/85_mods.py builds no layers, so a slim builder would
    silently drop them (the standard engine builds them: vizMods)."""
    out = []
    for i, page in enumerate(spec.get("pages") or []):
        for j, v in enumerate((page.get("visuals") or []) if isinstance(page, dict) else []):
            if isinstance(v, dict) and v.get("type") == "mod" and v.get("layers") is not None:
                out.append("pages[%d].visuals[%d].layers" % (i, j))
    return out


def slim_app(app_dir, spec_path, options, tag=None, out_path=None, clipboard=False, out=None):
    """validate -> resolve (dxpgen) -> shake -> write the slim builder -> checks. Exit code."""
    out = out or sys.stdout
    report, spec, raw = dxpgen.validate_app(app_dir, spec_path, options)
    out.write(report.render("Validating %s" % spec_path) + "\n")
    if report.errors or spec is None:
        out.write("\nAborted: fix the errors above, then run slim_builder.py again.\n")
        return dxpgen.EXIT_INVALID
    layered = mod_layer_paths(spec)
    if layered:
        out.write("\nAborted: %s: mod layers are built by the standard engine only; build without --tier slim.\n"
                  % ", ".join(layered))
        return dxpgen.EXIT_INVALID
    files = dxpgen.library_files()
    if not files:
        out.write("\nAborted: no lib/[0-9][0-9]_*.py files in %s\n" % dxpgen.LIB_DIR)
        return dxpgen.EXIT_INVALID
    app_dir = Path(app_dir).resolve()
    slug = dxpgen.app_slug(app_dir)
    resolved = dxpgen.library_spec(dxpgen.resolve_spec(spec, app_dir))
    parts = []
    lib_bytes = b""
    for f in files:
        data = f.read_bytes()
        lib_bytes += data
        parts.append((f.name, data.decode("utf-8-sig").replace("\r\n", "\n")))
    lib_sha = dxpgen.sha256_bytes(lib_bytes)
    spec_sha = dxpgen.sha256_bytes(raw)
    generated = datetime.datetime.now().replace(microsecond=0).isoformat()
    full = dxpgen.render_builder(resolved, app_dir, slug, spec_sha, parts, lib_sha, generated)
    if tag:
        resolved["app"]["output"] = tagged_output(resolved["app"]["output"], tag)
    try:
        code, info = slim_library(parts, resolved)
        text = render_slim(resolved, app_dir, slug, spec_sha, lib_sha, code, info, tag, generated)
    except ValueError as e:
        out.write("\nAborted: %s\n" % e)
        return dxpgen.EXIT_INVALID
    issues = check_builder(text, resolved)
    errors = [m for level, m in issues if level == "error"]
    if out_path is None:
        out_path = app_dir / "build" / ("build_%s_slim%s.py" % (slug, ("_" + tag) if tag else ""))
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")     # ASCII when the checks pass

    out.write("\nSlim builder written: %s\n" % target)
    out.write("  full builder (dxpgen.py build): %9d characters, %6d lines\n"
              % (len(full), full.count("\n")))
    out.write("  slim builder:                   %9d characters, %6d lines (%.0f%% of the full one)\n"
              % (len(text), text.count("\n"), 100.0 * len(text) / len(full)))
    out.write("  longest line %d characters, ASCII only: %s\n"
              % (max(len(x) for x in text.split("\n")), "yes" if text.isascii() else "NO"))
    out.write("  visual builders: %s\n" % ", ".join("%s -> %s" % kv for kv in info["builders"].items()))
    if dxpgen.t3._filters.uses_layouts(spec):
        out.write("  note: the filter panel layouts (filterPanelLayout, page filters) are built by the standard "
                  "engine only; this builder leaves every page's filter panel as Spotfire makes it\n")
    out.write("\nLibrary kept / removed (top-level functions):\n")
    for module, (kept, dropped) in info["modules"].items():
        if not kept:
            out.write("  lib/%-20s removed entirely (%d functions)\n" % (module, len(dropped)))
        else:
            out.write("  lib/%-20s kept %3d, removed %3d\n" % (module, len(kept), len(dropped)))
    features = sorted(set(info["gatedOff"].values()))
    out.write("\nFeatures this spec does not use (gated off):\n")
    for line in _wrap_words("  " + ", ".join(features), "  ", 100):
        out.write(line + "\n")
    if info["stubs"]:
        out.write("Stubs (named by kept code, raise if reached): %s\n" % ", ".join(info["stubs"]))
    lint_line = "not run (--no-lint)"
    if options.lint:
        min_version = resolved["app"].get("minimumSpotfireVersion") or "14.6"
        lint = dxpgen.lint_builder(target, options.tools_dir, min_version)
        if lint is None:
            lint_line = "not run (scripts/lint_ipy.py not found)"
        else:
            code_, findings, output = lint
            lint_errors = [f for f in findings if f["level"] == "error"]
            lint_line = "%d error(s), %d warning(s)" % (len(lint_errors), len(findings) - len(lint_errors))
            for f in lint_errors[:15]:
                errors.append("lint line %s, col %s: %s" % (f["line"], f["col"], f["msg"]))
            if code_ not in (0, 1):
                lint_line += " (lint_ipy.py exit %s: %s)" % (code_, dxpgen.tail(output))
    out.write("\nLint of the slim builder: %s\n" % lint_line)
    if options.lint:
        # the same external checks as the standard-engine tiers (dxpgen.engine_checks)
        parsed = dxpgen.ipy_parse(target, options.tools_dir)
        if parsed is None:
            out.write("IronPython parse: not run (needs Windows PowerShell and Spotfire Analyst 15.0)\n")
        elif parsed[0]:
            out.write("IronPython parse: %s\n" % parsed[1])
        else:
            errors.append("Spotfire's IronPython 3.4 parser: %s" % parsed[1])
        kept = [m for m, (names, _) in info["modules"].items() if names]
        counts = []
        for suffix, setter in ((".members.txt", False), (".set.txt", True)):
            specs = []
            for module in kept:
                listing = dxpgen.LIB_DIR / (module[:-3] + suffix)
                if listing.is_file():
                    specs += [x.strip() for x in listing.read_text(encoding="utf-8").splitlines()
                              if x.strip() and not x.lstrip().startswith("#")]
            found = dxpgen.sfapi_has(specs, options.tools_dir, setter=setter, api_dir=options.api_dir)
            if found is None:
                continue
            missing, okay = found
            errors.extend("sfapi.py has%s: %s is not in the 15.0 index" % (" --set" if setter else "", m)
                          for m in missing)
            counts.append("%d %s" % (okay, {".members.txt": "members", ".set.txt": "setters"}[suffix]))
        if counts:
            out.write("sfapi.py has (lib member lists of the kept modules): %s OK\n" % ", ".join(counts))
    for level, message in issues:
        if level != "error":
            out.write("  warning: %s\n" % message)
    if errors:
        out.write("\nChecks FAILED:\n" + "".join("  - %s\n" % m for m in errors))
    if clipboard:
        copied, problem = dxpgen.copy_to_clipboard(target)
        out.write("\nThe builder is on the clipboard.\n" if copied
                  else "\nCould not copy to the clipboard (%s).\n" % problem)
    output_path = Path(dxpgen._abs_path(app_dir, resolved["app"]["output"]))
    out.write("\nTo build the analysis (you start it; nothing runs automatically):\n"
              "  1. In Spotfire Analyst: File > New, then add any starter data.\n"
              "  2. Edit > Document Properties > Scripts > New, IronPython 3, untick \"Execute in "
              "transaction\"\n     (inside a transaction Spotfire refuses to save), paste the whole of\n"
              "     %s and click Run Script.\n"
              "  3. Close the dialog with Cancel. The analysis saves itself to\n"
              "     %s\n" % (target.name, output_path))
    out.write("Then verify it: python \"%s\" check \"%s\" --dxp \"%s\"\n"
              % (TOOL_DIR / "verify_dxp.py", app_dir, output_path))
    return dxpgen.EXIT_INVALID if errors else dxpgen.EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="slim_builder.py",
        description="Write an IronPython builder with only the library code an app's spec needs "
                    "Exit codes: 0 ok, 1 validation errors or failed checks, 2 usage.")
    parser.add_argument("app", help="app folder, spec.json, or app slug")
    parser.add_argument("--tag", help="saves the analysis as '<app.output stem> <TAG>.dxp' (letters, digits, "
                                      "'-', '_')")
    parser.add_argument("--out", help="builder file to write (default build/build_<AppSlug>_slim[_<TAG>].py)")
    parser.add_argument("--indent", type=int, choices=(2, 4), default=2,
                        help="spaces per block level (default 2: about 7%% smaller than 4)")
    parser.add_argument("--clipboard", action="store_true", help="copy the builder to the Windows clipboard")
    parser.add_argument("--no-lint", action="store_true", help="do not run scripts/lint_ipy.py")
    parser.add_argument("--no-sanitize", action="store_true",
                        help="do not check text-area HTML against Spotfire's sanitizer")
    parser.add_argument("--tools-dir", help="folder with lint_ipy.py / sf_sanitize.ps1 (default: this folder)")
    return parser


def main(argv=None):
    global INDENT
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else dxpgen.EXIT_USAGE
    if args.tag is not None and not re.match(r"^[A-Za-z0-9_-]+$", args.tag):
        sys.stderr.write("--tag may only use letters, digits, '-' and '_'\n")
        return dxpgen.EXIT_USAGE
    found = dxpgen.resolve_app(args.app)
    if found is None or not found[1].is_file():
        sys.stderr.write("app or spec.json not found: %s\n" % args.app)
        return dxpgen.EXIT_USAGE
    options = dxpgen.Options(lint=not args.no_lint, sanitize=not args.no_sanitize, tools_dir=args.tools_dir)
    INDENT = " " * args.indent
    return slim_app(found[0], found[1], options, tag=args.tag, out_path=args.out, clipboard=args.clipboard)


if __name__ == "__main__":
    sys.exit(main())
