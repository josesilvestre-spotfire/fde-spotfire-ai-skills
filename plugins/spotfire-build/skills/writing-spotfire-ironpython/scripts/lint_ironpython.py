"""Check Spotfire IronPython scripts before you paste or build them.

Spotfire Analyst runs document scripts in IronPython 3.4, which targets the
Python 3.4 language. This check parses each file with your CPython (3.10 or
later) and reports:

  errors    syntax newer than Python 3.4 (f-strings, the walrus operator,
            annotations, async/await, PEP 448 unpacking such as {**a},
            [*a, *b] or f(*a, *b), the @ operator, positional-only
            parameters, underscores in numbers), print calls, tab
            characters, imports of CPython-only packages (numpy, pandas,
            scipy, ...), and syntax errors
  warnings  pages or visuals looked up by index, assignments to a
            .Description attribute (read-only on DataProperty), leftover
            "# UNVERIFIED" comments, non-ASCII characters

Usage:
  python lint_ironpython.py FILE_OR_FOLDER [...]
  python lint_ironpython.py --self-test

Exit code 1 when any error is found. Standard library only.
"""

import ast
import io
import os
import re
import sys
import tokenize

CPYTHON_ONLY = {"numpy", "pandas", "scipy", "sklearn", "matplotlib",
                "requests", "spotfire", "pyarrow", "statsmodels"}
INDEX_LOOKUP = re.compile(r"\b(Pages|Visuals)\s*\[\s*-?\d+\s*\]")


class Finding:
    def __init__(self, level, line, text):
        self.level, self.line, self.text = level, line, text

    def __str__(self):
        return "%s line %d: %s" % (self.level, self.line, self.text)


def ast_findings(tree):
    found = []

    def err(node, text):
        found.append(Finding("ERROR", getattr(node, "lineno", 0), text))

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            err(node, "f-string: use % formatting or str.format")
        elif isinstance(node, ast.NamedExpr):
            err(node, "walrus operator := (Python 3.8)")
        elif isinstance(node, ast.AnnAssign):
            err(node, "variable annotation (Python 3.6)")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor,
                               ast.AsyncWith, ast.Await)):
            err(node, "async/await (Python 3.5)")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            err(node, "@ operator (Python 3.5)")
        elif isinstance(node, ast.Dict) and None in node.keys:
            err(node, "{**mapping} unpacking in a dict display (Python 3.5)")
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)) and \
                any(isinstance(e, ast.Starred) for e in node.elts) and \
                not isinstance(getattr(node, "ctx", None), ast.Store):
            err(node, "*iterable unpacking in a display (Python 3.5)")
        elif isinstance(node, ast.Call):
            starred = [a for a in node.args if isinstance(a, ast.Starred)]
            double = [k for k in node.keywords if k.arg is None]
            if len(starred) > 1 or len(double) > 1:
                err(node, "several * or ** arguments in one call "
                          "(Python 3.5)")
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                err(node, "print: write status to a document property or "
                          "a label instead")
        elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
            args = node.args
            if getattr(args, "posonlyargs", []):
                err(node, "positional-only parameters (Python 3.8)")
            if isinstance(node, ast.FunctionDef):
                if node.returns is not None:
                    err(node, "return annotation")
                every = args.args + args.kwonlyargs + \
                    getattr(args, "posonlyargs", [])
                if args.vararg:
                    every.append(args.vararg)
                if args.kwarg:
                    every.append(args.kwarg)
                if any(a.annotation is not None for a in every):
                    err(node, "parameter annotation")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(
                node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] in CPYTHON_ONLY:
                    err(node, "import %s: IronPython cannot load CPython "
                              "packages; use a data function" % name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and \
                        target.attr == "Description":
                    found.append(Finding(
                        "WARNING", node.lineno,
                        "assignment to .Description: read-only on "
                        "DataProperty (pass it to CreateCustomPrototype)"))
    return found


def token_findings(source):
    found = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NUMBER and "_" in tok.string:
                found.append(Finding("ERROR", tok.start[0],
                                     "underscore in a number (Python 3.6)"))
    except (tokenize.TokenError, SyntaxError):
        pass
    return found


def line_findings(source):
    found = []
    for n, line in enumerate(source.splitlines(), 1):
        if "\t" in line:
            found.append(Finding("ERROR", n, "tab character: Spotfire stores "
                                 "it as _x09; use spaces"))
        if INDEX_LOOKUP.search(line):
            found.append(Finding("WARNING", n, "page or visual by index: look "
                                 "it up by title"))
        if "# UNVERIFIED" in line:
            found.append(Finding("WARNING", n, "UNVERIFIED member left in "
                                 "the script"))
        if any(ord(c) > 127 for c in line):
            found.append(Finding("WARNING", n, "non-ASCII character"))
    return found


def lint_source(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("ERROR", exc.lineno or 0, "syntax error: %s" % exc.msg)]
    found = ast_findings(tree) + token_findings(source) + line_findings(source)
    return sorted(found, key=lambda f: (f.line, f.level))


def iter_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                for name in sorted(names):
                    if name.endswith(".py"):
                        yield os.path.join(root, name)
        else:
            yield path


SELF_TEST = '''
import numpy as np
from Spotfire.Dxp.Data import DataProperty
x = f"{1}"
if (n := 3) > 2:
    pass
y: int = 4
def f(a: int) -> int:
    return a
z = {**{}}
w = [*[1], *[2]]
print(x)
page = Document.Pages[0]
prop.Description = "text"
big = 1_000
'''

SELF_TEST_CLEAN = '''
from Spotfire.Dxp.Data import DataPropertyClass
first, *rest = [1, 2, 3]
def g(*args, **kwargs):
    return len(args)
Document.Properties["StatusMessage"] = "%d" % g(*rest)
'''


def self_test():
    found = lint_source(SELF_TEST)
    texts = " | ".join(str(f) for f in found)
    for expected in ("import numpy", "f-string", "walrus", "variable annotation",
                     "parameter annotation", "return annotation",
                     "{**mapping}", "*iterable unpacking", "print",
                     "by index", ".Description", "underscore"):
        assert expected in texts, (expected, texts)
    clean = lint_source(SELF_TEST_CLEAN)
    assert not [f for f in clean if f.level == "ERROR"], clean
    tabbed = lint_source("x = 1\nif x:\n\tx = 2\n")
    assert any("tab" in f.text for f in tabbed), tabbed
    print("self-test passed")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--self-test":
        return self_test()
    errors = 0
    for path in iter_files(argv):
        with open(path, encoding="utf-8") as f:
            found = lint_source(f.read())
        errors += len([f for f in found if f.level == "ERROR"])
        status = "ok" if not found else "%d finding(s)" % len(found)
        print("%s: %s" % (path, status))
        for finding in found:
            print("  " + str(finding))
    print("%d error(s)" % errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
