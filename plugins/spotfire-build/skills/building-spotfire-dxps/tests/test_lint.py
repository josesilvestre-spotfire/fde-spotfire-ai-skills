"""Tests for scripts/lint_ipy.py (CPython 3.10+, stdlib unittest).

    python tests/test_lint.py            (or: python -m unittest tests.test_lint -v)

Synthetic snippets cover every rule. The API-member, import and version tests need the API index that
scripts/dump_api.ps1 writes from your Spotfire install (SFAPI_INDEX, or $DXP_WORKSPACE/api); they are
skipped without it.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TOOL = SKILL / "scripts" / "lint_ipy.py"
sys.dont_write_bytecode = True          # keep scripts/ free of __pycache__ artifacts
sys.path.insert(0, str(SKILL / "scripts"))
import lint_ipy  # noqa: E402

LINE_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+):(?P<col>\d+): (?P<sev>error|warning): (?P<msg>.+)$")

API = lint_ipy.load_api()
needs_index = unittest.skipUnless(API.loaded, "no Spotfire API index (set SFAPI_INDEX; scripts/dump_api.ps1)")


def lint(code, **kw):
    return lint_ipy.lint_source(textwrap.dedent(code), path="snippet.py", **kw)


def only(findings, code):
    return [f for f in findings if f.code == code]


class SyntaxSubsetTest(unittest.TestCase):

    def assertRule(self, code, rule, line=None, contains=None, **kw):
        fs = only(lint(code, **kw), rule)
        self.assertTrue(fs, "expected a %s finding for:\n%s\ngot %s" % (rule, code, lint(code, **kw)))
        for f in fs:
            self.assertEqual(f.severity, "error", f)
        if line is not None:
            self.assertIn(line, [f.line for f in fs])
        if contains is not None:
            self.assertTrue(any(contains in f.message for f in fs), fs)
        return fs

    def test_fstring(self):
        fs = self.assertRule('x = 1\ny = f"{x}"\nz = f"{x:{3}}"\n', "syntax", line=2, contains="f-string")
        self.assertEqual(len(fs), 2, "one finding per f-string, nested format specs included")

    def test_walrus(self):
        self.assertRule("if (n := 10) > 5:\n    pass\n", "syntax", line=1, contains="walrus")

    def test_annotations(self):
        code = "def f(a: int, b=1, *args: str, **kw: int) -> int:\n    return a\nv: int = 3\n"
        fs = self.assertRule(code, "syntax", contains="annotation")
        msgs = " ".join(f.message for f in fs)
        self.assertIn("parameter annotation", msgs)
        self.assertIn("return annotation", msgs)
        self.assertIn("variable annotation", msgs)
        self.assertEqual(len(fs), 5)

    def test_async_await(self):
        code = """\
        async def g():
            await g()
            async for i in g():
                pass
            async with g() as h:
                pass
            return [i async for i in g()]
        """
        fs = self.assertRule(code, "syntax")
        msgs = " ".join(f.message for f in fs)
        for word in ("async def", "await", "async for", "async with", "async comprehension"):
            self.assertIn(word, msgs)

    def test_pep448_calls(self):
        self.assertRule("f(*a, *b)\n", "syntax", contains="several '*'")
        self.assertRule("f(**a, **b)\n", "syntax", contains="several '**'")
        self.assertRule("f(*a, b)\n", "syntax", contains="positional argument after '*'")
        self.assertRule("f(**k, a=1)\n", "syntax", contains="keyword argument after '**'")

    def test_pep448_displays(self):
        self.assertRule("x = [*a, 1]\n", "syntax", contains="list/tuple/set display")
        self.assertRule("x = (*a, 1)\n", "syntax", contains="list/tuple/set display")
        self.assertRule("x = {*a}\n", "syntax", contains="list/tuple/set display")
        self.assertRule("x = {**k, 'a': 1}\n", "syntax", contains="dict display")

    def test_numeric_underscores(self):
        self.assertRule("big = 1_000_000\n", "syntax", line=1, contains="write 1000000")

    def test_positional_only(self):
        self.assertRule("def f(a, /, b):\n    pass\n", "syntax", contains="positional-only")
        self.assertRule("g = lambda a, /: a\n", "syntax", contains="positional-only")

    def test_matrix_multiply(self):
        self.assertRule("c = a @ b\n", "syntax", contains="'@'")
        self.assertRule("a @= b\n", "syntax", contains="'@='")

    def test_newer_statements(self):
        self.assertRule("match x:\n    case 1:\n        pass\n", "syntax", contains="match")
        self.assertRule("try:\n    pass\nexcept* ValueError:\n    pass\n", "syntax", contains="except*")
        self.assertRule("type Alias = int\n", "syntax", contains="type alias")
        self.assertRule("def gen[T](x):\n    pass\n", "syntax", contains="type parameters")
        self.assertRule("@buttons[0].clicked\ndef h():\n    pass\n", "syntax", contains="decorator")
        self.assertRule("for i in x:\n    try:\n        pass\n    finally:\n        continue\n",
                        "syntax", contains="'continue' inside 'finally'")
        self.assertRule("try:\n    pass\nexcept ValueError, TypeError:\n    pass\n", "syntax",
                        contains="without parentheses")

    @needs_index
    def test_none_attribute(self):
        code = "from Spotfire.Dxp.Data import DataType\nw = DataType.None\nz = DataType.True\nq = Document.Data.Tabels\n"
        fs = self.assertRule(code, "none-attr", line=2, contains='getattr(<object>, "None")')
        self.assertEqual(len(fs), 2)
        # the rest of the file is still linted after the patch
        self.assertTrue(only(lint(code), "unknown-member"))
        self.assertFalse(only(lint(code), "parse-error"))

    def test_tabs(self):
        fs = lint("if x:\n\ty = 1\nz = 'a\tb'\n")
        tabs = only(fs, "tab")
        self.assertEqual([(f.line, f.col) for f in tabs], [(2, 1), (3, 7)])
        self.assertIn("indentation", tabs[0].message)
        self.assertTrue(all(f.severity == "error" for f in tabs))

    def test_mixed_tabs_still_analysed(self):
        # 8 spaces then a tab: TabError in Python 3 / IronPython 3; reported, then re-parsed with
        # tabs expanded so the other rules still run
        fs = lint("if x:\n        y = 1\n\tz = f'{y}'\n")
        self.assertEqual([f.line for f in only(fs, "tab")], [3])
        self.assertIn("TabError", only(fs, "parse-error")[0].message)
        self.assertTrue(any("f-string" in f.message for f in only(fs, "syntax")))

    @needs_index
    def test_columns_are_characters_not_bytes(self):
        line = 'x = "' + chr(233) * 3 + '" + Document.Data.Tabels'
        fs = only(lint(line + "\n"), "unknown-member")
        self.assertEqual((fs[0].line, fs[0].col), (1, line.index("Tabels") + 1))

    def test_parse_error(self):
        fs = lint('print "python 2"\n')
        self.assertEqual([f.code for f in fs], ["parse-error"])
        self.assertEqual(fs[0].severity, "error")

    def test_valid_34_code_is_clean(self):
        code = """\
        import json
        def f(a, b=1, *args, **kwargs):
            return a
        def g(*, key=None):
            nonlocal_value = [x for x in range(3)]
            yield from nonlocal_value
        f(*args, **kwargs)
        f(a, *args, c=1, **kw)
        f(c=1, *args)
        first, *rest = [1, 2, 3]
        for p, *q in []:
            pass
        s = "%s %d" % ("a", 1) + "{}".format(2) + r"\\d" + rb"x".decode()
        h = 0x1F + 1e5 + 0o17 + 0b101 + 3j.imag
        @staticmethod
        def h2(): pass
        @a.b(c)
        def h3(): pass
        try:
            pass
        except (ValueError, TypeError) as e:
            raise RuntimeError("x") from e
        finally:
            pass
        d = {k: v for k, v in []}
        """
        fs = lint(code)
        self.assertEqual([f for f in fs if f.severity == "error"], [])


class PrintTest(unittest.TestCase):

    def test_print_warning_by_default(self):
        fs = only(lint("print('x')\n"), "print")
        self.assertEqual([f.severity for f in fs], ["warning"])

    def test_print_error_in_document_script(self):
        fs = only(lint("print('x')\n", document_script=True), "print")
        self.assertEqual([f.severity for f in fs], ["error"])

    def test_shadowed_print_and_method_print_ignored(self):
        self.assertFalse(only(lint("def print(*a):\n    pass\nprint(1)\n"), "print"))
        self.assertFalse(only(lint("logger.print(1)\n"), "print"))


@needs_index
class ApiMemberTest(unittest.TestCase):

    def test_index_loaded_once(self):
        self.assertTrue(API.loaded, API.load_error)
        self.assertIs(lint_ipy.load_api(), API)
        self.assertGreater(len(API.public), 3000)
        self.assertEqual(API.internal_nonpublic, set())          # the public index only

    def test_unknown_member_with_suggestion(self):
        fs = only(lint("x = Document.Data.Tabels\n"), "unknown-member")
        self.assertEqual(len(fs), 1)
        self.assertEqual((fs[0].line, fs[0].col), (1, 19))       # column of the member name
        self.assertTrue(fs[0].message.startswith("unknown member 'Tabels'"))
        self.assertIn("Tables", fs[0].message)
        self.assertEqual(fs[0].severity, "warning")

    def test_known_spotfire_members(self):
        code = """\
        from Spotfire.Dxp.Application.Visuals import LineChart, VisualTypeIdentifiers, AxisRange
        for v in Document.ActivePageReference.Visuals:
            if v.TypeId == VisualTypeIdentifiers.LineChart:
                lc = v.As[LineChart]()
                lc.YAxis.Range = AxisRange(0, 1)
                lc.YAxis.Scale.ShowGridlines = True
                lc.Data.DataTableReference = Document.Data.Tables.DefaultTableReference
                lc.Legend.Visible = False
        """
        self.assertEqual(lint(code), [])

    def test_bcl_allowlist(self):
        code = """\
        import clr
        clr.AddReference("System.Drawing")
        from System import DateTime, TimeSpan, Guid, String, Array, Type, Activator, Convert, Math
        from System.IO import File, Path, Directory, MemoryStream, StreamReader, SeekOrigin
        from System.Drawing import Color, ColorTranslator, Bitmap, Graphics, Rectangle, Size, Point
        from System.Reflection import BindingFlags
        from System.Collections.Generic import List, Dictionary, KeyValuePair
        from System.Globalization import CultureInfo
        t = DateTime.Now.AddHours(1).ToString("yyyy")
        s = TimeSpan.FromMinutes(5).TotalSeconds
        g = Guid.NewGuid()
        e = String.IsNullOrEmpty(str.Empty)
        p = Path.Combine(Path.GetTempPath(), "x")
        ok = File.Exists(p) and Directory.Exists(p)
        ms = MemoryStream()
        ms.Seek(0, SeekOrigin.Begin)
        c = Color.FromArgb(255, 1, 2) if ColorTranslator.FromHtml("#fff").R else Color.White
        flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public
        m = Document.GetType().GetProperty("Data", flags).GetValue(Document, None)
        lst = List[str]()
        lst.Add("a")
        n = lst.Count
        d = Dictionary[str, int]()
        has = d.ContainsKey("a") or d.Keys.Count
        inv = CultureInfo.InvariantCulture
        x = Math.Round(Math.PI, 2) + Convert.ToDouble("1")
        """
        self.assertEqual(only(lint(code), "unknown-member"), [])

    def test_python_module_attributes_not_checked(self):
        code = "import re\nimport collections\nfrom collections import OrderedDict\nf = re.IGNORECASE\nd = collections.Counter()\nx = OrderedDict.Fromkeys\n"
        self.assertEqual(only(lint(code), "unknown-member"), [])

    def test_names_defined_in_file_not_checked(self):
        code = """\
        class Helper(object):
            Registry = {}
            def __init__(self):
                self.Total = 0
            def Run(self):
                self.Total += 1
                return Helper.Registry
        h = Helper()
        h.Run()
        h.Whatever = 1
        y = h.Whatever
        """
        self.assertEqual(lint(code), [])

    def test_namespace_chains(self):
        code = "import System\nimport Spotfire.Dxp.Application.Visuals\nt = System.DateTime.Now\np = System.IO.Path.Combine('a', 'b')\nk = Spotfire.Dxp.Application.Visuals.LineChart\n"
        self.assertEqual(lint(code), [])
        fs = only(lint("import Spotfire\nx = Spotfire.Dxp.Application.Visualz.LineChart\n"), "unknown-member")
        self.assertEqual(len(fs), 1)
        self.assertIn("Spotfire.Dxp.Application.Visualz", fs[0].message)
        # .NET namespaces/types outside the index and the BCL allowlist are not guessed at
        code = """\
        import System
        import Microsoft.VisualBasic
        from System.Data import DataTable
        from System.IO import DriveInfo
        t = System.Data.DataTable()
        s = Microsoft.VisualBasic.Interaction.InputBox("x")
        r = DataTable().NewRow()
        d = DriveInfo.GetDrives()
        """
        self.assertEqual(lint(code), [])

    def test_namespace_alias_and_snippet_alias(self):
        code = "from Spotfire.Dxp.Application.Visuals import Maps\nm = visual.As[Maps.MapChart]()\n"
        self.assertEqual(lint(code), [])
        # postScript-style snippet without the import: still a namespace, not the obsolete member
        self.assertEqual(lint("m = visual.As[Maps.MapChart]()\n"), [])

    def test_non_public_member_is_unknown(self):
        fs = only(lint("x = Document.UseCustomStyles\n"), "unknown-member")
        self.assertEqual(len(fs), 1)

    def test_obsolete(self):
        fs = only(lint("from Spotfire.Dxp.Application.Visuals import VisualTypeIdentifiers\nt = VisualTypeIdentifiers.MapChart\n"),
                  "obsolete")
        self.assertEqual(len(fs), 1)
        self.assertIn("MapChart2", fs[0].message)

    def test_two_level_check_catches_yaxis_showlabels(self):
        code = "sp = vis.As[ScatterPlot]()\nsp.YAxis.ShowLabels = False\nsp.YAxis.Scale.ShowLabels = False\n"
        fs = lint(code)
        self.assertEqual(only(fs, "unknown-member"), [], "ShowLabels exists on ScaleBase: name level passes")
        res = only(fs, "member-of-result")
        self.assertEqual([f.line for f in res], [2])
        self.assertIn("'.YAxis'", res[0].message)
        self.assertIn("ScaleAxis", res[0].message)

    def test_two_level_check_on_calls(self):
        fs = only(lint("r = marking.GetSelection(t).ShowLabels\n"), "member-of-result")
        self.assertEqual(len(fs), 1)
        self.assertIn("'.GetSelection()' (RowSelection)", fs[0].message)
        self.assertEqual(lint("ok = marking.GetSelection(t).AsIndexSet()\n"), [])
        # AddNew has generic overloads (returns T): undecidable, so no verdict either way
        self.assertEqual(lint("p = Document.Pages.AddNew().ShowLabels\n"), [])
        self.assertEqual(only(lint("p = Document.Pages.AddNew().Visualz\n"), "unknown-member")[0].line, 1)

    def test_limitation_variable_breaks_the_chain(self):
        # documented limitation: types are not tracked through variables
        code = "axis = sp.YAxis\naxis.ShowLabels = False\n"
        self.assertEqual(lint(code), [])

    def test_bcl_type_roots_skip_two_level_check(self):
        self.assertEqual(lint("from System import DateTime\ny = DateTime.Now.Date.Year\n"), [])


@needs_index
class ImportTest(unittest.TestCase):

    def test_good_imports(self):
        code = """\
        from Spotfire.Dxp.Application.Visuals import LineChart, VisualTypeIdentifiers as VTI
        from Spotfire.Dxp.Data import *
        from Spotfire.Dxp.Application import Visuals
        from Spotfire.Dxp import Application
        import Spotfire.Dxp.Application.Visuals.Maps
        from System.Windows.Forms import MessageBox
        """
        self.assertEqual(only(lint(code), "import"), [])

    def test_type_in_wrong_namespace(self):
        fs = only(lint("from Spotfire.Dxp.Application.Visuals import DataType\n"), "import")
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].severity, "error")
        self.assertIn("it is in Spotfire.Dxp.Data", fs[0].message)

    def test_unknown_namespace(self):
        for code in ("from Spotfire.Dxp.Nope import Thing\n", "from Spotfire.Dxp.Nope import *\n",
                     "import Spotfire.Dxp.Nope\n"):
            fs = only(lint(code), "import")
            self.assertEqual(len(fs), 1, code)
            self.assertIn("unknown Spotfire namespace", fs[0].message)

    def test_non_public_type_import(self):
        fs = only(lint("from Spotfire.Dxp.Application.Scripting import ManagedScript\n"), "import")
        self.assertEqual(len(fs), 1)
        self.assertIn("has no public type 'ManagedScript'", fs[0].message)

    def test_non_public_namespace(self):
        fs = only(lint("from Spotfire.Dxp.Application.HtmlTextAreaControls import PropertyControl\n"), "import")
        self.assertEqual(len(fs), 1)
        self.assertIn("unknown Spotfire namespace", fs[0].message)


@needs_index
class VersionTest(unittest.TestCase):

    def test_member_newer_than_target(self):
        code = "m = vis.As[ModVisualization]()\na = m.Axes\n"
        fs = only(lint(code), "version")
        self.assertEqual(len(fs), 1)
        self.assertIn("requires Spotfire 14.7", fs[0].message)
        self.assertEqual(only(lint(code, min_version="14.7"), "version"), [])
        self.assertEqual(only(lint(code, min_version="15.0"), "version"), [])

    def test_15_only_member(self):
        fs = only(lint("x = vis.YAxis.Scale.AdaptiveTimeLabels\n"), "version")
        self.assertEqual(len(fs), 1)
        self.assertIn("requires Spotfire 15.0", fs[0].message)

    def test_old_member_no_warning(self):
        self.assertEqual(lint("e = vis.YAxis.Expression\n"), [])

    def test_imported_type_version(self):
        code = "from Spotfire.Dxp.Application.Visuals.Distributions import ProbitPlot\n"
        fs = only(lint(code), "version")
        self.assertEqual(len(fs), 1)
        self.assertIn("requires Spotfire 15.0", fs[0].message)
        self.assertEqual(only(lint(code, min_version="15.0"), "version"), [])

    def test_bcl_names_have_no_version(self):
        # Day is [api 15.0] on a Spotfire type but also System.DateTime.Day
        self.assertEqual(lint("from System import DateTime\nd = DateTime.Now.Day\nq = x.Day\n"), [])

    def test_parse_version(self):
        self.assertEqual(lint_ipy.parse_version("14.6"), (14, 6, 0))
        self.assertEqual(lint_ipy.parse_version("15"), (15, 0, 0))
        self.assertEqual(lint_ipy.format_version((15, 0, 0)), "15.0")
        self.assertEqual(lint_ipy.format_version((2, 0, 3)), "2.0.3")
        with self.assertRaises(ValueError):
            lint_ipy.parse_version("14.x")


class NonPublicApiTest(unittest.TestCase):
    """Reflection into non-public members is an error, with or without the API index."""

    def test_binding_flags_non_public(self):
        code = "from System.Reflection import BindingFlags\nf = BindingFlags.Instance | BindingFlags.NonPublic\n"
        fs = only(lint(code), "non-public-api")
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].severity, "error")
        self.assertEqual((fs[0].line, fs[0].col), (2, 29))
        code = "import System\nf = System.Reflection.BindingFlags.NonPublic\n"
        self.assertEqual(len(only(lint(code), "non-public-api")), 1)

    def test_public_reflection_is_fine(self):
        code = "from System.Reflection import BindingFlags\nf = BindingFlags.Instance | BindingFlags.Public\n"
        self.assertEqual(only(lint(code), "non-public-api"), [])


class UndefinedNameTest(unittest.TestCase):

    def test_missing_import(self):
        code = "for v in Document.ActivePageReference.Visuals:\n    ok = v.TypeId == VisualTypeIdentifiers.LineChart\n"
        fs = only(lint(code, document_script=True), "undefined-name")
        self.assertEqual([f.message.split("'")[1] for f in fs], ["VisualTypeIdentifiers"])
        self.assertEqual(only(lint(code), "undefined-name"), [], "only for document scripts / --check-names")
        self.assertTrue(only(lint(code, check_names=True), "undefined-name"))

    @needs_index
    def test_star_import_and_globals(self):
        code = "from Spotfire.Dxp.Application.Visuals import *\nok = page.Title == VisualTypeIdentifiers.LineChart\n"
        fs = only(lint(code, document_script=True), "undefined-name")
        self.assertEqual([f.message.split("'")[1] for f in fs], ["page"])
        self.assertEqual(only(lint(code, document_script=True, script_globals=("page",)), "undefined-name"), [])

    def test_non_enumerable_star_import_disables_check(self):
        self.assertEqual(only(lint("from System import *\nx = Whatever\n", document_script=True), "undefined-name"), [])


class NoqaTest(unittest.TestCase):

    @needs_index
    def test_noqa(self):
        self.assertEqual(lint("print('x')  # noqa\n", document_script=True), [])
        self.assertEqual(lint("x = Document.Data.Tabels  # noqa: unknown-member\n"), [])
        self.assertTrue(lint("x = Document.Data.Tabels  # noqa: print\n"))


@needs_index
class CliTest(unittest.TestCase):

    def run_cli(self, *args, stdin=None):
        p = subprocess.run([sys.executable, str(TOOL)] + list(args), capture_output=True, text=True,
                           input=stdin, timeout=120)
        return p.returncode, p.stdout.splitlines()

    def test_output_format_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.py"
            bad.write_text("x = f'{1}'\ny = Document.Data.Tabels\n", encoding="utf-8")
            warn = Path(tmp) / "warn.py"
            warn.write_text("y = Document.Data.Tabels\n", encoding="utf-8")
            clean = Path(tmp) / "clean.py"
            clean.write_text("y = Document.Data.Tables\n", encoding="utf-8")
            code, out = self.run_cli(str(bad))
            self.assertEqual(code, 1)
            finding_lines = out[:-1]
            self.assertEqual(len(finding_lines), 2)
            for line in finding_lines:
                m = LINE_RE.match(line)
                self.assertIsNotNone(m, line)
                self.assertEqual(Path(m.group("path")), bad)
            self.assertEqual(LINE_RE.match(finding_lines[0]).group("sev"), "error")
            self.assertIn("1 error(s), 1 warning(s)", out[-1])
            code, out = self.run_cli(str(warn))
            self.assertEqual(code, 0)
            code, out = self.run_cli(str(clean), "--document-script", "--min-version", "14.6")
            self.assertEqual(code, 0)
            self.assertEqual(len(out), 1)
            self.assertIn("0 error(s), 0 warning(s)", out[0])
            code, out = self.run_cli(str(bad), "--json")
            data = json.loads("\n".join(out))
            self.assertEqual((data["errors"], data["warnings"]), (1, 1))
            self.assertEqual(data["findings"][0]["code"], "syntax")

    def test_stdin_and_document_script(self):
        code, out = self.run_cli("-", "--document-script", stdin="print('x')\n")
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("<stdin>:1:1: error: print()"), out)

    def test_bad_version_is_usage_error(self):
        code, _ = self.run_cli("x.py", "--min-version", "fourteen")
        self.assertEqual(code, 2)

    def test_directory_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.py", "b.py"):
                (Path(tmp) / name).write_text("x = Document.Data.Tables\n", encoding="utf-8")
            code, out = self.run_cli(tmp)
            self.assertEqual(code, 0)
            self.assertIn("2 file(s)", out[-1])
            code, out = self.run_cli(str(Path(tmp) / "missing.py"))
            self.assertEqual(code, 1)
            self.assertIn("cannot read file", out[0])


class LibraryTest(unittest.TestCase):
    """The build library must lint without errors, unknown/internal members or wrong imports."""

    def test_lib_modules(self):
        mods = sorted((SKILL / "scripts" / "lib").glob("[0-9][0-9]_*.py"))
        self.assertTrue(mods)
        bad = []
        for m in mods:
            for f in lint_ipy.lint_file(str(m)):
                if f.severity == "error" or f.code in ("unknown-member", "internal-member", "member-of-result",
                                                       "import", "internal-name", "print"):
                    bad.append(lint_ipy.format_finding(f))
        self.assertEqual(bad, [])

    def test_concatenated_builder_is_fast(self):
        mods = sorted((SKILL / "scripts" / "lib").glob("[0-9][0-9]_*.py"))
        text = "\n".join(m.read_text(encoding="utf-8") for m in mods)
        text += '\nSPEC = {"app": {"name": "X"}}\nAPP_DIR = r"C:\\x"\nB = BuildContext(SPEC, APP_DIR, Document, Application, "a", "b")\nrun_build()\n'
        t0 = time.perf_counter()
        fs = lint_ipy.lint_source(text, path="build_X.py")
        elapsed = time.perf_counter() - t0
        self.assertEqual([f for f in fs if f.severity == "error"], [])
        self.assertLess(elapsed, 5.0, "lint of the concatenated library took %.2fs" % elapsed)


class PersistedTest(unittest.TestCase):

    def test_decode(self):
        self.assertEqual(lint_ipy.decode_persisted("for x in y:\n_x09_x09a = 1"), "for x in y:\n\t\ta = 1")
        self.assertEqual(lint_ipy.decode_persisted("my_x41 = 1"), "my_x41 = 1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
