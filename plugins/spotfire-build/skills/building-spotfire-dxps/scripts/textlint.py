"""textlint - the customer-ready text check of `dxpgen validate`.

Customers can read everything a DXP carries: page and visual titles, descriptions, text areas,
table, column, property, data-function and script names and descriptions, control labels and value
lists, the messages scripts and data functions write, and the code itself (data-function scripts,
IronPython scripts, text-area JavaScript and action-mod bundles open in Spotfire's editors). None of
it may carry internal language: release tags (R1.0, r53), development notes (TODO, FIXME,
NEEDS-LIVE-TEST), design history ("verbatim", "legacy", "prototype"), tool and assistant names,
internal property names in prose (ReqOpsDays), person names.

Scopes and levels (spec `app.textLint`, references/spec-format.md "app"):
  visible  titles, descriptions, labels, HTML text, property defaults, value lists, object names,
           action-mod and visualization-mod manifest texts, mod text properties; default "error"
  code     comments, docstrings and string literals of embedded code, HTML comments; default
           "warning" (a string literal may be a message users see: reword it too)
  allow    ids of DEFAULT_RULES this app accepts (e.g. ["builder"] for an app about a query builder)
`app.bannedTerms`: extra terms for the app (person names, codenames): plain text matches as a whole
word, case-insensitive; "re:<regex>" is a regular expression (case-sensitive unless it says (?i)).

No Spotfire, no I/O of its own: check_app(spec, read) gets the files through `read`.
"""
import html.parser
import io
import re
import tokenize

LEVELS = ("error", "warning", "off")
VISIBLE, NAME, CODE = "visible", "name", "code"     # NAME: object names (prose-only rules skip them)

_B = r"(?<![A-Za-z0-9])"                            # letter/digit boundaries: GIS_PUMPS_LEGACY
_E = r"(?![A-Za-z0-9])"                             # matches, useLegacy does not


class Rule(object):
    def __init__(self, rid, label, pattern, scopes, flags=0):
        self.id, self.label, self.scopes = rid, label, scopes
        self.regex = re.compile(_B + "(?:" + pattern + ")" + _E, flags)


_ALL = (VISIBLE, NAME, CODE)
DEFAULT_RULES = (
    Rule("release-tag", "internal release tag", r"R\d+\.(?:\d+|[xX])|r\d{2,}", _ALL),
    Rule("version-tag", "version tag", r"[vV]\d+\.\d+(?:\.\d+)*", (VISIBLE,)),
    Rule("verbatim", "design-history word", r"verbatim", _ALL, re.I),
    Rule("legacy", "design-history word", r"legacy", _ALL, re.I),
    Rule("prototype", "design-history word", r"prototypes?", _ALL, re.I),
    Rule("dev-note", "development note", r"TODO|FIXME|(?i:needs[-_ ]live[-_ ]test)", _ALL),
    Rule("assistant", "assistant name", r"claude|anthropic", _ALL, re.I),
    Rule("skill", "internal skill reference", r"skill[\s_-]*\d{1,2}", _ALL, re.I),
    Rule("tool-name", "internal tool name",
         r"dxpgen|sfapi|verify_dxp|slim_builder|lint_ipy|sf_sanitize|ipy_parse", _ALL, re.I),
    Rule("builder", "internal tool word", r"builders?", _ALL, re.I),
    Rule("property-name", "internal property name in prose", r"Req[A-Z][A-Za-z0-9]*", (VISIBLE,)),
)
RULE_IDS = tuple(r.id for r in DEFAULT_RULES)

# keys whose string values are visible prose wherever they sit in a visual (reference-layer and
# fitting-model labels, scale titles, KPI titles, control labels, value-list texts ...)
VISIBLE_KEYS = ("title", "description", "label", "subtitle", "caption", "emptyText", "text", "header",
                "tooltip", "message", "emptyMessage", "displayName")
_SETTING_TEXT_RE = re.compile(r"(?:Title|Description|Message|Text|Label)$")
# mod visual and layer properties whose string values the mod shows (a heading, a label ...)
_MOD_TEXT_PROP_RE = re.compile(r"(?i)(?:title|heading|label|text|caption|description|message)$")
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*control\s*:[^{}]*\}\}")
_HTML_TEXT_ATTRS = ("title", "alt", "placeholder", "aria-label")


def config_problems(app):
    """[(path, message)] for app.textLint and app.bannedTerms (dxpgen v_app reports them as errors)."""
    out = []
    cfg = app.get("textLint")
    if cfg is not None:
        if not isinstance(cfg, dict):
            return [("app.textLint", "must be {\"visible\": ..., \"code\": ..., \"allow\": [...]}")]
        for k in cfg:
            if k not in ("visible", "code", "allow"):
                out.append(("app.textLint." + k, "unknown field (visible, code, allow)"))
        for k in ("visible", "code"):
            if k in cfg and cfg[k] not in LEVELS:
                out.append(("app.textLint." + k, "must be one of %s" % ", ".join(LEVELS)))
        allow = cfg.get("allow")
        if allow is not None:
            if not isinstance(allow, list):
                out.append(("app.textLint.allow", "must be a list of rule ids (%s)" % ", ".join(RULE_IDS)))
            else:
                for i, rid in enumerate(allow):
                    if rid not in RULE_IDS:
                        out.append(("app.textLint.allow[%d]" % i, "unknown rule %r (%s)"
                                    % (rid, ", ".join(RULE_IDS))))
    terms = app.get("bannedTerms")
    if terms is not None:
        if not isinstance(terms, list):
            return out + [("app.bannedTerms", "must be a list of terms")]
        for i, t in enumerate(terms):
            if not isinstance(t, str) or not t.strip() or t.strip() == "re:":
                out.append(("app.bannedTerms[%d]" % i, "must be a non-empty string"))
            elif t.startswith("re:"):
                try:
                    re.compile(t[3:])
                except re.error as e:
                    out.append(("app.bannedTerms[%d]" % i, "is not a valid regular expression: %s" % e))
    return out


def app_rules(app):
    """The rules of an app: DEFAULT_RULES minus textLint.allow, plus one rule per bannedTerms entry."""
    cfg = app.get("textLint") if isinstance(app.get("textLint"), dict) else {}
    allow = set(cfg.get("allow") or []) if isinstance(cfg.get("allow"), list) else set()
    rules = [r for r in DEFAULT_RULES if r.id not in allow]
    for t in app.get("bannedTerms") or []:
        if not isinstance(t, str) or not t.strip():
            continue
        try:
            if t.startswith("re:"):
                rules.append(Rule("banned-term", "banned term of this app", t[3:], _ALL))
            else:
                rules.append(Rule("banned-term", "banned term of this app", re.escape(t.strip()), _ALL, re.I))
        except re.error:
            continue                                   # config_problems reports it
    return rules


def app_levels(app):
    cfg = app.get("textLint") if isinstance(app.get("textLint"), dict) else {}
    vis = cfg.get("visible") if cfg.get("visible") in LEVELS else "error"
    code = cfg.get("code") if cfg.get("code") in LEVELS else "warning"
    return {VISIBLE: vis, NAME: vis, CODE: code}


def snippet(text, m, width=36):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("..." if a > 0 else "") + s + ("..." if b < len(text) else "")


# ---- code segments: (line, kind, text) with kind comment | docstring | string ------------------
def python_segments(code):
    """Comments, docstrings and string literals of Python / IronPython code (tokenize; on a
    tokenize error the simple line scanner of hash_segments)."""
    out = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return hash_segments(code)
    skip = (tokenize.NL, tokenize.COMMENT)
    sig = [t for t in toks if t.type not in skip]
    pos = dict((id(t), i) for i, t in enumerate(sig))
    fmid = getattr(tokenize, "FSTRING_MIDDLE", None)
    for t in toks:
        if t.type == tokenize.COMMENT:
            out.append((t.start[0], "comment", t.string))
        elif t.type == tokenize.STRING:
            i = pos[id(t)]
            prev = sig[i - 1].type if i > 0 else tokenize.NEWLINE
            nxt = sig[i + 1].type if i + 1 < len(sig) else tokenize.NEWLINE
            alone = prev in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING) \
                and nxt in (tokenize.NEWLINE, tokenize.ENDMARKER)
            out.append((t.start[0], "docstring" if alone else "string", t.string))
        elif fmid is not None and t.type == fmid:
            out.append((t.start[0], "string", t.string))
    return out


_QUOTED_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


def hash_segments(code):
    """Line scanner for '#' comments and quoted strings (R, or Python tokenize cannot read)."""
    out = []
    for n, line in enumerate(code.split("\n"), 1):
        quote, cut = None, None
        k = 0
        while k < len(line):
            ch = line[k]
            if quote:
                if ch == "\\":
                    k += 1
                elif ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = k
                break
            k += 1
        body = line if cut is None else line[:cut]
        if cut is not None:
            out.append((n, "comment", line[cut:]))
        for m in _QUOTED_RE.finditer(body):
            out.append((n, "string", m.group(0)))
    return out


def js_segments(code):
    """Comments and string literals (quotes and template literals) of JavaScript."""
    out = []
    i, n, line = 0, len(code), 1
    while i < n:
        ch = code[i]
        two = code[i:i + 2]
        if two == "//":
            j = code.find("\n", i)
            j = n if j < 0 else j
            out.append((line, "comment", code[i:j]))
            i = j
        elif two == "/*":
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((line, "comment", code[i:j]))
            line += code.count("\n", i, j)
            i = j
        elif ch in "\"'`":
            j = i + 1
            while j < n and code[j] != ch:
                if code[j] == "\\":
                    j += 1
                elif code[j] == "\n" and ch != "`":
                    break
                j += 1
            j = min(j + 1, n)
            out.append((line, "string", code[i:j]))
            line += code.count("\n", i, j)
            i = j
        else:
            if ch == "\n":
                line += 1
            i += 1
    return out


class _HtmlText(html.parser.HTMLParser):
    """(line, scope, kind, text): text and title/alt attributes are visible, comments and
    <style>/<script> bodies are code."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.items, self.raw = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.raw += 1
        for k, v in attrs:
            if k in _HTML_TEXT_ATTRS and v:
                self.items.append((self.getpos()[0], VISIBLE, "attribute", v))

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.raw:
            self.raw -= 1

    def handle_data(self, data):
        if data.strip():
            text = _PLACEHOLDER_RE.sub(" ", data)
            self.items.append((self.getpos()[0], CODE if self.raw else VISIBLE,
                               "string" if self.raw else "text", text))

    def handle_comment(self, data):
        self.items.append((self.getpos()[0], CODE, "comment", data))


def html_segments(text):
    p = _HtmlText()
    try:
        p.feed(text)
        p.close()
    except Exception:                                  # noqa: BLE001 - malformed HTML: scan it whole
        return [(1, VISIBLE, "text", _PLACEHOLDER_RE.sub(" ", text))]
    return p.items


# ---- the check -----------------------------------------------------------------------------------
class TextLint(object):
    def __init__(self, spec, read):
        """read(rel_path) -> (text or None, key): the file's text and a key that names it uniquely."""
        self.spec = spec
        self.read = read
        app = spec.get("app") if isinstance(spec.get("app"), dict) else {}
        self.rules = app_rules(app)
        self.levels = app_levels(app)
        self.found = []                                # (level, path, message)
        self.seen_files = {}

    # visible strings of the spec: one finding per (path, rule)
    def text(self, path, value, scope=VISIBLE):
        if not isinstance(value, str) or not value.strip() or self.levels[scope] == "off":
            return
        for rule, matches in self.matches(value, scope):
            terms = sorted(set(m.group(0) for m in matches))
            what = "this name" if scope == NAME else "this text"
            self.found.append((self.levels[scope], path, "%s contains %s (%s): \"%s\" - customers see it; "
                               "write it in customer language%s"
                               % (what, ", ".join("'%s'" % t for t in terms), rule.label,
                                  snippet(value, matches[0]), self.allow_hint(rule))))

    def matches(self, text, scope):
        out = []
        for rule in self.rules:
            if scope not in rule.scopes:
                continue
            ms = list(rule.regex.finditer(text))
            if ms:
                out.append((rule, ms))
        return out

    def allow_hint(self, rule):
        if rule.id == "banned-term":
            return ""
        return " (app.textLint.allow: [\"%s\"] accepts it for this app)" % rule.id

    # files and code: one finding per (path, rule, scope) with the line numbers
    def segments(self, path, segs, label):
        """segs: [(line, scope, kind, text)]."""
        groups = {}
        order = []
        for line, scope, kind, text in segs:
            if self.levels[scope] == "off" or not text:
                continue
            for rule, ms in self.matches(text, scope):
                for m in ms:
                    key = (rule.id, scope)
                    if key not in groups:
                        groups[key] = {"rule": rule, "scope": scope, "lines": [], "kinds": [], "terms": set(),
                                       "snippet": snippet(text, m)}
                        order.append(key)
                    g = groups[key]
                    ln = line + text.count("\n", 0, m.start())
                    if ln not in g["lines"]:
                        g["lines"].append(ln)
                    if kind not in g["kinds"]:
                        g["kinds"].append(kind)
                    g["terms"].add(m.group(0))
        for key in order:
            g = groups[key]
            rule, scope = g["rule"], g["scope"]
            lines = sorted(g["lines"])
            where = "line%s %s%s" % ("s" if len(lines) > 1 else "", ", ".join(str(x) for x in lines[:8]),
                                     " and %d more" % (len(lines) - 8) if len(lines) > 8 else "")
            terms = ", ".join("'%s'" % t for t in sorted(g["terms"])[:6])
            if scope == CODE:
                msg = ("%s: %s (%s) in %s of the embedded code, %s: \"%s\" - data-function, script, "
                       "JavaScript and action-mod code is readable inside the DXP; reword or remove it%s"
                       % (label, terms, rule.label, "/".join(k + "s" for k in g["kinds"]), where,
                          g["snippet"], self.allow_hint(rule)))
            else:
                msg = ("%s: visible text contains %s (%s) on %s: \"%s\" - customers see it; write it in "
                       "customer language%s" % (label, terms, rule.label, where, g["snippet"],
                                                self.allow_hint(rule)))
            self.found.append((self.levels[scope], path, msg))

    def code_text(self, path, code, lang, label):
        if not isinstance(code, str) or not code.strip() or self.levels[CODE] == "off":
            return
        if lang == "js":
            segs = js_segments(code)
        elif lang == "r":
            segs = hash_segments(code)
        else:
            segs = python_segments(code)
        self.segments(path, [(line, CODE, kind, text) for line, kind, text in segs], label)

    def code_file(self, path, rel, lang):
        text, key = self.read(rel)
        if text is None or key in self.seen_files:
            return
        self.seen_files[key] = path
        self.code_text(path, text, lang, rel)

    def html_value(self, path, value):
        if not isinstance(value, str) or not value.strip():
            return
        if value.lstrip().startswith("<"):
            text, label = value, "inline HTML"
        else:
            text, key = self.read(value.strip())
            if text is None or key in self.seen_files:
                return
            self.seen_files[key] = path
            label = value.strip()
        self.segments(path, html_segments(text), label)

    # ---- spec walk ---------------------------------------------------------------------------
    def run(self):
        s = self.spec
        app = s.get("app") if isinstance(s.get("app"), dict) else {}
        self.text("app.name", app.get("name"), NAME)
        self.text("app.description", app.get("description"))
        for i, k in enumerate(_list(app.get("keywords"))):
            self.text("app.keywords[%d]" % i, k)
        for i, t in enumerate(_list(s.get("tables"))):
            if not isinstance(t, dict):
                continue
            p = "tables[%d]" % i
            self.text(p + ".name", t.get("name"), NAME)
            self.text(p + ".description", t.get("description"))
            cols = t.get("columns") if isinstance(t.get("columns"), dict) else {}
            for c, meta in cols.items():
                if isinstance(meta, dict):
                    self.text("%s.columns[%r].description" % (p, c), meta.get("description"))
            for key in ("calculatedColumns", "hierarchies"):
                for k, c in enumerate(_list(t.get(key))):
                    if isinstance(c, dict):
                        self.text("%s.%s[%d].name" % (p, key, k), c.get("name"), NAME)
                        self.text("%s.%s[%d].description" % (p, key, k), c.get("description"))
        for key in ("markings", "filteringSchemes"):
            for i, m in enumerate(_list(s.get(key))):
                if isinstance(m, dict):
                    self.text("%s[%d].name" % (key, i), m.get("name"), NAME)
        for i, prop in enumerate(_list(s.get("properties"))):
            if not isinstance(prop, dict):
                continue
            p = "properties[%d]" % i
            self.text(p + ".name", prop.get("name"), NAME)
            self.text(p + ".description", prop.get("description"))
            for d in (prop.get("default") if isinstance(prop.get("default"), list) else [prop.get("default")]):
                self.text(p + ".default", d)
        for i, d in enumerate(_list(s.get("dataFunctions"))):
            if not isinstance(d, dict):
                continue
            p = "dataFunctions[%d]" % i
            self.text(p + ".name", d.get("name"), NAME)
            self.text(p + ".description", d.get("description"))
            for key in ("inputs", "outputs"):
                for j, io_ in enumerate(_list(d.get(key))):
                    if isinstance(io_, dict):
                        self.text("%s.%s[%d].description" % (p, key, j), io_.get("description"))
            lang = "r" if d.get("engine") == "terr" else "python"
            if isinstance(d.get("script"), str) and d["script"].strip():
                self.code_file(p + ".script", d["script"].strip(), lang)
            elif isinstance(d.get("scriptCode"), str):
                self.code_text(p + ".scriptCode", d["scriptCode"], lang, "scriptCode")
        for i, sc in enumerate(_list(s.get("scripts"))):
            if not isinstance(sc, dict):
                continue
            p = "scripts[%d]" % i
            self.text(p + ".name", sc.get("name"), NAME)
            self.text(p + ".description", sc.get("description"))
            for j, prm in enumerate(_list(sc.get("parameters"))):
                if isinstance(prm, dict):
                    self.text("%s.parameters[%d].description" % (p, j), prm.get("description"))
            if isinstance(sc.get("file"), str) and sc["file"].strip():
                self.code_file(p + ".file", sc["file"].strip(), "python")
            elif isinstance(sc.get("code"), str):
                self.code_text(p + ".code", sc["code"], "python", "script '%s'" % sc.get("name"))
        for i, m in enumerate(_list(s.get("actionMods"))):
            if isinstance(m, dict) and isinstance(m.get("project"), str) and m["project"].strip():
                self.action_mod("actionMods[%d].project" % i, m["project"].strip())
        for i, m in enumerate(_list(s.get("vizMods"))):
            if isinstance(m, dict) and isinstance(m.get("project"), str) and m["project"].strip():
                self.viz_mod("vizMods[%d].project" % i, m["project"].strip())
        self.filter_groups("filterPanelLayout", s.get("filterPanelLayout"))
        for pi, pg in enumerate(_list(s.get("pages"))):
            if not isinstance(pg, dict):
                continue
            self.text("pages[%d].title" % pi, pg.get("title"))
            self.filter_groups("pages[%d].filters" % pi, pg.get("filters"))
            for vi, v in enumerate(_list(pg.get("visuals"))):
                if isinstance(v, dict):
                    self.visual("pages[%d].visuals[%d]" % (pi, vi), v)
        return self.found

    def filter_groups(self, path, layout):
        """Sub group names of a filter panel layout: labels a user reads in the Filters panel."""
        if not isinstance(layout, dict):
            return
        for k, t in enumerate(_list(layout.get("tables"))):
            if isinstance(t, dict):
                for g, group in enumerate(_list(t.get("subGroups"))):
                    if isinstance(group, dict):
                        self.text("%s.tables[%d].subGroups[%d].name" % (path, k, g), group.get("name"))

    def visual(self, path, v):
        for key, value in v.items():
            p = path + "." + key
            if v.get("type") == "mod" and key in ("properties", "layers", "axes"):
                self.mod_view_text(p, key, value)
            elif key == "html":
                self.html_value(p, value)
            elif key == "js":
                for k, item in enumerate(_list(value)):
                    if isinstance(item, str):
                        self.code_file("%s[%d]" % (p, k), item, "js")
                    elif isinstance(item, dict):
                        self.text("%s[%d].name" % (p, k), item.get("name"), NAME)
                        self.code_text("%s[%d].code" % (p, k), item.get("code"), "js", "JavaScript")
            elif key == "postScript":
                self.code_text(p, value, "python", "postScript")
            elif key == "settings" and isinstance(value, dict):
                for sk, sv in value.items():
                    if isinstance(sv, str) and _SETTING_TEXT_RE.search(sk):
                        self.text("%s[%r]" % (p, sk), sv)
            elif key in ("css", "style"):
                continue
            else:
                self.walk(p, key, value)

    def walk(self, path, key, value):
        if isinstance(value, str):
            if key in VISIBLE_KEYS:
                self.text(path, value)
        elif isinstance(value, dict):
            for k, v in value.items():
                if key == "fixed" or k in VISIBLE_KEYS or isinstance(v, (dict, list)):
                    self.walk(path + "." + str(k), k, v)
        elif isinstance(value, list):
            for k, v in enumerate(value):
                if key == "fixed" and isinstance(v, dict):
                    self.text("%s[%d].text" % (path, k), v.get("text"))
                    if isinstance(v.get("value"), str) and v.get("value") != v.get("text"):
                        self.text("%s[%d].value" % (path, k), v.get("value"))
                elif isinstance(v, (dict, list)):
                    self.walk("%s[%d]" % (path, k), key, v)
                elif isinstance(v, str) and key in VISIBLE_KEYS:
                    self.text("%s[%d]" % (path, k), v)

    def mod_properties(self, path, props):
        """String values of mod properties whose name says they are text (heading, label, ...)."""
        if not isinstance(props, dict):
            return
        for name, value in props.items():
            if isinstance(value, str) and _MOD_TEXT_PROP_RE.search(str(name)):
                self.text("%s.%s" % (path, name), value)

    def mod_view_text(self, path, key, value):
        """A mod visual's properties and layers (titles, text properties); axes are expressions."""
        if key == "properties":
            self.mod_properties(path, value)
        elif key == "layers":
            for k, layer in enumerate(_list(value)):
                if isinstance(layer, dict):
                    lp = "%s[%d]" % (path, k)
                    self.text(lp + ".title", layer.get("title"))
                    self.mod_properties(lp + ".properties", layer.get("properties"))

    def viz_mod(self, path, project):
        """A visualization mod's manifest texts (name, description, axis titles: visible; layer types, axis
        and property names: names) and the files it lists (JavaScript, CSS and HTML comments: code)."""
        import json
        base = project.rstrip("/\\")
        text, _ = self.read(base + "/mod-manifest.json")
        if text is None:
            return
        try:
            man = json.loads(text)
        except ValueError:
            return
        if not isinstance(man, dict):
            return
        self.text(path + " (manifest name)", man.get("name"))
        self.text(path + " (manifest description)", man.get("description"))
        views = [("", man)] + [(" layers[%d]" % k, x) for k, x in enumerate(_list(man.get("layers")))
                               if isinstance(x, dict)]
        for label, view in views:
            vp = "%s (manifest%s)" % (path, label)
            if label:
                self.text(vp + ".type", view.get("type"), NAME)
            for k, prop in enumerate(_list(view.get("properties"))):
                if isinstance(prop, dict):
                    self.text("%s.properties[%d].name" % (vp, k), prop.get("name"), NAME)
            dvd = view.get("dataViewDefinition") if isinstance(view.get("dataViewDefinition"), dict) else {}
            for k, axis in enumerate(_list(dvd.get("axes"))):
                if not isinstance(axis, dict):
                    continue
                ap = "%s.axes[%d]" % (vp, k)
                self.text(ap + ".name", axis.get("name"), NAME)
                control = axis.get("propertyControl") if isinstance(axis.get("propertyControl"), dict) else {}
                self.text(ap + ".propertyControl.title", control.get("title"))
        for k, name in enumerate(_list(man.get("files"))):
            if not isinstance(name, str) or not name.strip():
                continue
            fp = "%s (manifest files[%d])" % (path, k)
            rel = base + "/" + name.strip()
            low = name.strip().lower()
            if low.endswith(".js"):
                self.code_file(fp, rel, "js")
            elif low.endswith(".css"):
                self.css_file(fp, rel)
            elif low.endswith((".html", ".htm")):
                body, key = self.read(rel)
                if body is not None and key not in self.seen_files:
                    self.seen_files[key] = fp
                    self.segments(fp, html_segments(body), rel)

    def css_file(self, path, rel):
        """The /* comments */ of a style sheet (code)."""
        text, key = self.read(rel)
        if text is None or key in self.seen_files or self.levels[CODE] == "off":
            return
        self.seen_files[key] = path
        segs = [(1 + text.count("\n", 0, m.start()), CODE, "comment", m.group(0))
                for m in _CSS_COMMENT_RE.finditer(text)]
        self.segments(path, segs, rel)

    def action_mod(self, path, project):
        import json
        text, _ = self.read(project.rstrip("/\\") + "/mod-manifest.json")
        if text is None:
            return
        try:
            man = json.loads(text)
        except ValueError:
            return
        if not isinstance(man, dict):
            return
        self.text(path + " (manifest name)", man.get("name"))
        self.text(path + " (manifest description)", man.get("description"))
        for k, sc in enumerate(_list(man.get("scripts"))):
            if not isinstance(sc, dict):
                continue
            sp = "%s (manifest scripts[%d])" % (path, k)
            self.text(sp + ".name", sc.get("name"))
            self.text(sp + ".description", sc.get("description"))
            for j, prm in enumerate(_list(sc.get("parameters"))):
                if isinstance(prm, dict):
                    self.text("%s.parameters[%d].displayName" % (sp, j), prm.get("displayName"))
                    self.text("%s.parameters[%d].description" % (sp, j), prm.get("description"))
            if isinstance(sc.get("file"), str) and sc["file"].strip():
                self.code_file(sp + ".file", project.rstrip("/\\") + "/" + sc["file"].strip(), "js")


def _list(v):
    return v if isinstance(v, list) else []


def check_app(spec, read):
    """[(level, path, message)] of the customer-ready text check (levels error | warning)."""
    return [f for f in TextLint(spec, read).run() if f[0] in ("error", "warning")]
