"""Engine parts -> one builder text (standard engine). No Spotfire, no I/O besides reading
engine/*.py.

An engine part is engine/core.py, engine/report.py or engine/builders/<name>.py. Its leading comment
block documents it for maintainers and is not copied; "# @..." lines are directives and never reach
the builder:
  # @kind <kind>          (builders) the engine kind it registers
  # @uses <part> ...      shared parts it needs (engine/builders/_<name>.py), included once before it
  # @api A.B; C.D         public members, checked with scripts/sfapi.py has
  # @set A.B; C.D         assigned properties, checked with scripts/sfapi.py has --set
  # @tier quick|standard  ...  # @end   styling kept from that tier up (compact keeps neither);
                          a directive inside a tier block counts only for the tiers that keep it
  # @feature name  ...  # @endfeature   kept only when the app uses the feature ("!name": only
                          when it does not); feature and tier blocks may sit inside each other
  # @builders             (core) where the builders and the report add-on go
Imports of all parts are merged at the top of the builder; names nothing uses are dropped. The
engine uses Spotfire's public API only: a "# @internal" directive is an error.
"""
import ast
import re

LEVELS = {"compact": 0, "quick": 1, "standard": 2, "report": 2}
LIMIT = 79
_TIER_RE = re.compile(r"^#\s*@tier\s+(\w+)\s*$")
_END_RE = re.compile(r"^#\s*@end\s*$")
_DIRECTIVE_RE = re.compile(r"^#\s*@(\w+)\b\s*(.*)$")
_FEATURE_RE = re.compile(r"^#\s*@feature\s+(!?)(\w+)\s*$")
_ENDFEATURE_RE = re.compile(r"^#\s*@endfeature\s*$")


class Part(object):
    """One engine file, parsed for one tier."""

    def __init__(self, name, path, text, tier, features=None):
        self.name = name
        self.path = path
        self.kind = None
        self.uses = []
        self.api = []
        self.set = []
        lines = text.replace("\r\n", "\n").split("\n")
        lines = strip_features(lines, features, str(path))
        kept = strip_tiers(lines, LEVELS[tier], str(path))
        self._directives(kept)          # a directive inside a tier block counts for that tier only
        body = _drop_leading_comments(kept)
        body = [line for line in body if not _is_directive(line) or line.strip() == "# @builders"]
        self.imports, self.code = split_imports(body, str(path))

    def _directives(self, lines):
        for line in lines:
            m = _DIRECTIVE_RE.match(line.strip())
            if not m:
                continue
            word, rest = m.group(1), m.group(2).strip()
            items = [x.strip() for x in rest.split(";") if x.strip()]
            if word == "kind":
                self.kind = rest
            elif word == "uses":
                self.uses.extend(rest.split())
            elif word == "api":
                self.api.extend(items)
            elif word == "set":
                self.set.extend(items)
            elif word == "internal":
                raise ValueError("%s: '# @internal %s': the engine uses Spotfire's public API only"
                                 % (self.path, rest))


def _is_directive(line):
    return bool(_DIRECTIVE_RE.match(line.strip()))


def strip_tiers(lines, level, where="engine"):
    """Lines without the tier blocks above `level` (0 compact, 1 quick, 2 standard); the markers go."""
    out = []
    block = None
    for n, line in enumerate(lines, 1):
        s = line.strip()
        m = _TIER_RE.match(s)
        if m:
            if block is not None:
                raise ValueError("%s:%d: '# @tier' inside another tier block" % (where, n))
            if m.group(1) not in ("quick", "standard"):
                raise ValueError("%s:%d: unknown tier '%s' (quick or standard)" % (where, n, m.group(1)))
            block = m.group(1)
            continue
        if _END_RE.match(s):
            if block is None:
                raise ValueError("%s:%d: '# @end' without '# @tier'" % (where, n))
            block = None
            continue
        if block is not None and LEVELS[block] > level:
            continue
        out.append(line)
    if block is not None:
        raise ValueError("%s: '# @tier %s' has no '# @end'" % (where, block))
    return out


def strip_features(lines, features, where="engine"):
    """Lines without the feature blocks the app does not use; the markers go. features None = every
    feature on (positive blocks kept, "!name" blocks dropped)."""
    out = []
    block = None
    for n, line in enumerate(lines, 1):
        s = line.strip()
        m = _FEATURE_RE.match(s)
        if m:
            if block is not None:
                raise ValueError("%s:%d: '# @feature' inside another feature block" % (where, n))
            on = features is None or m.group(2) in features
            block = on != bool(m.group(1))
            continue
        if _ENDFEATURE_RE.match(s):
            if block is None:
                raise ValueError("%s:%d: '# @endfeature' without '# @feature'" % (where, n))
            block = None
            continue
        if block is False:
            continue
        out.append(line)
    if block is not None:
        raise ValueError("%s: a '# @feature' block has no '# @endfeature'" % where)
    return out


def _drop_leading_comments(lines):
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    return lines[i:]


def _is_import_stmt(node):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "AddReference")


def split_imports(lines, where="engine"):
    """(leading import statements as [(ast node, source text)], the remaining code lines)."""
    text = "\n".join(lines)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise ValueError("%s does not parse after the tier stripping: %s (line %s)" % (where, e.msg, e.lineno))
    imports = []
    end = 0
    for node in tree.body:
        if not _is_import_stmt(node):
            break
        imports.append((node, "\n".join(lines[node.lineno - 1:node.end_lineno])))
        end = node.end_lineno
    rest = lines[end:]
    while rest and not rest[0].strip():
        rest = rest[1:]
    return imports, rest


class Imports(object):
    """Merged import statements of several parts, in first-seen order."""

    def __init__(self):
        self.items = []                    # ("raw", text) | ("import", name) | ("from", module, [names])

    def add(self, node, source):
        if isinstance(node, ast.Import):
            for alias in node.names:
                key = ("import", alias.name if not alias.asname else alias.name + " as " + alias.asname)
                if key not in self.items:
                    self.items.append(key)
        elif isinstance(node, ast.ImportFrom):
            names = [a.name if not a.asname else a.name + " as " + a.asname for a in node.names]
            for item in self.items:
                if item[0] == "from" and item[1] == node.module:
                    for n in names:
                        if n not in item[2]:
                            item[2].append(n)
                    return
            self.items.append(("from", node.module, list(names)))
        else:
            key = ("raw", source.strip())
            if key not in self.items:
                self.items.append(key)

    def render(self, used):
        """Import lines, keeping only names in `used` (clr and its AddReference calls always stay)."""
        lines = []
        for item in self.items:
            if item[0] == "raw":
                lines.append(item[1])
            elif item[0] == "import":
                bound = item[1].split(" as ")[-1].split(".")[0]
                if bound in used or bound == "clr":
                    lines.append("import " + item[1])
            else:
                names = [n for n in item[2] if n.split(" as ")[-1] in used]
                if names:
                    lines.extend(render_from(item[1], names))
        return lines


def render_from(module, names):
    one = "from %s import %s" % (module, ", ".join(names))
    if len(one) <= LIMIT:
        return [one]
    lines = ["from %s import (" % module]
    cur = "   "
    for i, n in enumerate(names):
        piece = n + ("," if i < len(names) - 1 else ")")
        if len(cur) + 1 + len(piece) > LIMIT:
            lines.append(cur)
            cur = "    " + piece
        else:
            cur = cur + " " + piece
    lines.append(cur)
    return lines


def used_names(text):
    names = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def drop_docstrings(lines):
    """Code lines without function docstrings (dense builders: the engine files keep them)."""
    tree = ast.parse("\n".join(lines))
    gone = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef) and len(node.body) > 1 and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)):
            gone.update(range(node.body[0].lineno - 1, node.body[0].end_lineno))
    return [line for n, line in enumerate(lines) if n not in gone]


def collapse_blank_lines(text):
    return re.sub(r"\n{4,}", "\n\n\n", text)


def wrap_comment(text, prefix="# ", indent="#   ", limit=LIMIT):
    """Comment lines of at most `limit` characters (continuation lines start with `indent`)."""
    lines = []
    cur = prefix
    for w in text.split():
        fresh = cur in (prefix, indent)
        candidate = cur + w if fresh else cur + " " + w
        if len(candidate) > limit and not fresh:
            lines.append(cur)
            cur = indent + w
        else:
            cur = candidate
    lines.append(cur)
    return lines
