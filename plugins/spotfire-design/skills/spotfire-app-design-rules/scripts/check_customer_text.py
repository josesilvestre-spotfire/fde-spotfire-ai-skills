#!/usr/bin/env python3
"""Check that the text a Spotfire analysis ships is written for customers.

Customers can read everything a DXP carries: page and visual titles, text-area HTML, descriptions,
control labels, and the code itself (data functions, IronPython scripts, text-area JavaScript, mod
files), which opens in Spotfire's editors. This script scans the source files of an app and reports
internal language: release and version tags, development notes, design-history words, assistant
and tool names, placeholders, em and en dashes in visible text, and any term from your own list.

Scopes and levels:
  visible  HTML text and title/alt/placeholder attributes; JSON values under keys such as
           title, description, label, caption, text, tooltip, message, name     -> ERROR
  code     comments, docstrings and string literals of Python, R, JavaScript and CSS files,
           HTML comments and <script>/<style> bodies                              -> WARNING
A string literal in code may be a message users see: reword it too.

Usage:
  python check_customer_text.py <file or folder> [...] [--terms FILE] [--allow RULE ...]
                                [--strict] [--json]

  --terms FILE   one term per line (names, project code names); '#' starts a comment;
                 plain terms match as whole words without regard to case; 're:<regex>' is a
                 regular expression
  --allow RULE   accept a default rule for this app (repeatable), e.g. --allow builder for an
                 app about a query builder
  --strict       exit 1 on warnings as well as errors
  --json         print the findings as JSON

Folders are scanned recursively for .html, .htm, .css, .js, .py, .r and .json files. The folders
ingest, versions, data, node_modules, .git and __pycache__ are skipped.

Exit code: 0 clean, 1 findings at the failing level, 2 usage error. Standard library only; the
script reads files and prints, it writes nothing.
"""
import argparse
import html.parser
import io
import json
import re
import sys
import tokenize
from pathlib import Path

VISIBLE, CODE = "visible", "code"
LEVEL = {VISIBLE: "ERROR", CODE: "WARNING"}
SUFFIXES = {".html", ".htm", ".css", ".js", ".py", ".r", ".json"}
SKIP_DIRS = {"ingest", "versions", "data", "node_modules", ".git", "__pycache__"}
VISIBLE_KEYS = {"title", "subtitle", "description", "label", "caption", "text", "header",
                "tooltip", "message", "emptytext", "emptymessage", "displayname", "name"}
TEXT_ATTRS = ("title", "alt", "placeholder", "aria-label")
PLACEHOLDER_RE = re.compile(r"\{\{\s*control\s*:[^{}]*\}\}")
BOUND_START = r"(?<![A-Za-z0-9])"
BOUND_END = r"(?![A-Za-z0-9])"


class Rule(object):
    def __init__(self, rid, label, pattern, scopes, flags=0, bounded=True):
        self.id, self.label, self.scopes = rid, label, scopes
        if bounded:
            pattern = BOUND_START + "(?:" + pattern + ")" + BOUND_END
        self.regex = re.compile(pattern, flags)


BOTH = (VISIBLE, CODE)
DEFAULT_RULES = (
    Rule("release-tag", "internal release tag", r"R\d+\.(?:\d+|[xX])|r\d{2,}", BOTH),
    Rule("version-tag", "version tag in visible text", r"[vV]\d+\.\d+(?:\.\d+)*", (VISIBLE,)),
    Rule("design-history", "design-history word", r"verbatim|legacy|prototypes?", BOTH, re.I),
    Rule("dev-note", "development note",
         r"TODO|FIXME|XXX|HACK|(?i:needs[-_ ]live[-_ ]test)|(?i:not yet tested)", BOTH),
    Rule("assistant", "assistant or model name", r"claude|anthropic|chatgpt|openai", BOTH, re.I),
    Rule("skill", "reference to an authoring skill", r"skill[\s_-]*\d{1,2}", BOTH, re.I),
    Rule("builder", "build tool word", r"builders?", BOTH, re.I),
    Rule("placeholder", "placeholder text", r"TBD|lorem ipsum|placeholder text", (VISIBLE,), re.I),
    Rule("dash", "em or en dash in visible text", "[\u2013\u2014]", (VISIBLE,), bounded=False),
)
RULE_IDS = [r.id for r in DEFAULT_RULES]


def load_terms(path):
    """Rules for the terms in a private list (one per line)."""
    rules = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        if term.startswith("re:"):
            rules.append(Rule("term", "term from your list", term[3:], BOTH))
        else:
            rules.append(Rule("term", "term from your list", re.escape(term), BOTH, re.I))
    return rules


# ---- segments: (line, scope, text) ---------------------------------------------------------------
def python_segments(code):
    """Comments, docstrings and string literals of Python code."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                out.append((tok.start[0], CODE, tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return hash_segments(code)
    return out


QUOTED_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


def hash_segments(code):
    """'#' comments and quoted strings, line by line (R, or Python that does not tokenize)."""
    out = []
    for n, line in enumerate(code.split("\n"), 1):
        quote, cut, k = None, None, 0
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
            out.append((n, CODE, line[cut:]))
        for m in QUOTED_RE.finditer(body):
            out.append((n, CODE, m.group(0)))
    return out


def js_segments(code):
    """Comments and string literals (quotes and template literals) of JavaScript or CSS."""
    out = []
    i, n, line = 0, len(code), 1
    while i < n:
        two = code[i:i + 2]
        ch = code[i]
        if two == "//" and not code[max(0, i - 1):i] == ":":
            j = code.find("\n", i)
            j = n if j < 0 else j
            out.append((line, CODE, code[i:j]))
            i = j
        elif two == "/*":
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((line, CODE, code[i:j]))
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
            out.append((line, CODE, code[i:j]))
            line += code.count("\n", i, j)
            i = j
        else:
            if ch == "\n":
                line += 1
            i += 1
    return out


class _HtmlText(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.items, self.raw = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.raw += 1
        for key, value in attrs:
            if key in TEXT_ATTRS and value:
                self.items.append((self.getpos()[0], VISIBLE, value))

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.raw:
            self.raw -= 1

    def handle_data(self, data):
        if data.strip():
            text = PLACEHOLDER_RE.sub(" ", data)
            self.items.append((self.getpos()[0], CODE if self.raw else VISIBLE, text))

    def handle_comment(self, data):
        self.items.append((self.getpos()[0], CODE, data))


def html_segments(text):
    parser = _HtmlText()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # malformed HTML: scan the whole text as visible
        return [(1, VISIBLE, PLACEHOLDER_RE.sub(" ", text))]
    return parser.items


def json_segments(text):
    """String values under visible keys, with the line where each value first appears."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []

    def line_of(value):
        idx = text.find(json.dumps(value)[1:-1])
        return text.count("\n", 0, idx) + 1 if idx >= 0 else 1

    def walk(node, key):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key and key.lower() in VISIBLE_KEYS and node.strip():
            out.append((line_of(node), VISIBLE, node))

    walk(data, None)
    return out


def segments_for(path, text):
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        return html_segments(text)
    if suffix == ".py":
        return python_segments(text)
    if suffix == ".r":
        return hash_segments(text)
    if suffix in (".js", ".css"):
        return js_segments(text)
    if suffix == ".json":
        return json_segments(text)
    return []


# ---- the check -----------------------------------------------------------------------------------
def snippet(text, match, width=40):
    a, b = max(0, match.start() - width), min(len(text), match.end() + width)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("..." if a > 0 else "") + s + ("..." if b < len(text) else "")


def check_file(path, rules):
    text = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for line, scope, seg in segments_for(path, text):
        for rule in rules:
            if scope not in rule.scopes:
                continue
            for m in rule.regex.finditer(seg):
                found.append({"file": str(path), "line": line + seg.count("\n", 0, m.start()),
                              "level": LEVEL[scope], "scope": scope, "rule": rule.id,
                              "label": rule.label, "match": m.group(0),
                              "context": snippet(seg, m)})
    return found


def iter_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUFFIXES and \
                        not any(part in SKIP_DIRS for part in f.relative_to(p).parts[:-1]):
                    yield f
        else:
            raise FileNotFoundError(str(p))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="files or app folders to scan")
    ap.add_argument("--terms", help="file with your own terms, one per line")
    ap.add_argument("--allow", action="append", default=[], choices=RULE_IDS,
                    help="accept a default rule for this app (repeatable)")
    ap.add_argument("--strict", action="store_true", help="fail on warnings too")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # consoles that cannot show a character

    rules = [r for r in DEFAULT_RULES if r.id not in set(args.allow)]
    try:
        if args.terms:
            rules += load_terms(args.terms)
        files = list(iter_files(args.paths))
    except (OSError, re.error) as exc:
        sys.stderr.write("check_customer_text: %s\n" % exc)
        return 2

    findings = []
    for f in files:
        findings += check_file(f, rules)

    errors = sum(1 for f in findings if f["level"] == "ERROR")
    warnings = len(findings) - errors
    if args.json:
        print(json.dumps({"files": len(files), "errors": errors, "warnings": warnings,
                          "findings": findings}, indent=1))
    else:
        for f in findings:
            print("%s:%d: %s %s (%s): '%s' in \"%s\"" % (f["file"], f["line"], f["level"],
                                                         f["rule"], f["label"], f["match"],
                                                         f["context"]))
        print("%d files, %d errors (visible text), %d warnings (code)" % (len(files), errors,
                                                                           warnings))
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
