"""Tests for scripts/verify_dxp.py: the DXP model (dump) and the spec comparison (check).

Run: python -B tests/test_verify.py   (or python -m unittest discover -s tests)

The tests build small synthetic .dxp archives and app folders in DXPB_TEST_TMP (default: the system temp
folder) and remove them afterwards. Nothing here starts Spotfire.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TOOLS = SKILL / "scripts"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
import dxpgen  # noqa: E402
import verify_dxp as V  # noqa: E402

TMP_ROOT = os.environ.get("DXPB_TEST_TMP") or None


def visual(model, page_title, title, type_id=None):
    for p in model["pages"]:
        if p["title"] == page_title:
            for v in p["visuals"]:
                if v.get("title") == title and (type_id is None or v.get("typeId") == type_id):
                    return v
    raise AssertionError("visual %r not found on page %r" % (title, page_title))


def lines(items, area=None, path=None, check=None):
    """Check lines whose area equals and whose path / check contain the given texts."""
    out = []
    for it in items:
        if area is not None and it["area"] != area:
            continue
        if path is not None and path not in it["path"]:
            continue
        if check is not None and check not in it["check"]:
            continue
        out.append(it)
    return out


# ------------------------------------------------------------------------------------------------
# pure helpers
# ------------------------------------------------------------------------------------------------
class TextHelpersTest(unittest.TestCase):
    def test_decode_persisted(self):
        self.assertEqual(V.decode_persisted("for x in y:\n_x09_x09a = 1"), "for x in y:\n\t\ta = 1")
        self.assertEqual(V.decode_persisted("a_x5Fx09b"), "a_x09b")          # escaped underscore stays literal
        self.assertEqual(V.decode_persisted("plain_text_x"), "plain_text_x")
        self.assertEqual(V.norm_code("a\r\nb\r\n\r\n"), "a\nb")

    def test_expr_key(self):
        self.assertEqual(V.expr_key("Sum([Flow Rate])  AS [Total Flow]"), V.expr_key("sum([Flow Rate]) as [Total Flow]"))
        self.assertNotEqual(V.expr_key("Sum([Flow Rate])"), V.expr_key("Sum([flow rate])"))   # identifiers kept
        self.assertEqual(V.expr_key("If(Max([A])=1,1,null)"), V.expr_key("If(Max([A]) = 1, 1, null)"))
        self.assertEqual(V.expr_key("[$Threshold] * 2"), V.expr_key('DocumentProperty("Threshold")*2'))
        self.assertNotEqual(V.expr_key('"a b"'), V.expr_key('"ab"'))                          # literals kept

    def test_match_expression(self):
        self.assertEqual(V.match_expression("[Month]", "[Month]")[0], "PASS")
        st, note = V.match_expression("[Station]", "<[Station]>")
        self.assertEqual(st, "PASS")
        self.assertIn("angle brackets", note)
        self.assertEqual(V.match_expression("[Month]", "[Date]")[0], "FAIL")
        self.assertEqual(V.match_expression("[Month]", "")[0], "FAIL")
        self.assertEqual(V.match_expression("[A]", "[B] as [A2]", alternatives=["[B]  as [A2]"])[0], "PASS")

    def test_split_and_alias(self):
        self.assertEqual(V.split_top("Sum([A, B]), Avg([C]) as [X], 'a,b'"), ["Sum([A, B])", "Avg([C]) as [X]", "'a,b'"])
        self.assertEqual(V.measure_alias("Sum([A]) as [Total A]"), ("Sum([A])", "Total A"))
        self.assertEqual(V.measure_alias("Sum([Gas]) as Total"), ("Sum([Gas])", "Total"))
        self.assertEqual(V.measure_alias("Sum([Basis])"), ("Sum([Basis])", None))
        self.assertEqual(V.display_name("Sum([Baseline_HHP])"), "Sum(Baseline_HHP)")

    def test_relation_pairs(self):
        self.assertEqual(V.relation_pairs("([L].[a]=[R].[b]) And ([L].[c]=[R].[d])"), [["a", "b"], ["c", "d"]])
        self.assertEqual(V.relation_pairs("[L].[Pump ID]=[R].[Pump ID] and [L].[x]=[R].[y]"),
                         [["Pump ID", "Pump ID"], ["x", "y"]])
        self.assertEqual(V.relation_pairs("[L].[Gathering and Transport]=[R].[G and T] and [L].[a]]b]=[R].[c]"),
                         [["Gathering and Transport", "G and T"], ["a]b", "c"]])

    def test_compare_value(self):
        self.assertTrue(V.compare_value("Real", 72.0, 72.0000000001))
        self.assertTrue(V.compare_value("Integer", 5, 5))
        self.assertFalse(V.compare_value("Integer", 5, 6))
        self.assertTrue(V.compare_value("Boolean", True, True))
        self.assertTrue(V.compare_value("Date", "2026-01-31", "2026-01-31T00:00:00"))
        self.assertTrue(V.compare_value("DateTime", "2026-01-31T08:00:00", "2026-01-31T08:00:00"))
        self.assertTrue(V.compare_value("TimeSpan", "01:30:00", "1:30:00"))
        self.assertTrue(V.compare_value("String", ["a", "b"], ["a", "b"]))
        self.assertFalse(V.compare_value("String", "a", "b"))

    def test_credential_names_and_masking(self):
        for name in ("Password", "DB Password", "dbPassword", "API_KEY", "apiKey", "Token", "pwd", "client-secret"):
            self.assertTrue(V.credential_name(name), name)
        for name in ("TokenCount", "Server", "Username", "PasswordHint"):
            self.assertFalse(V.credential_name(name), name)
        self.assertEqual(V.safe_expr("Password", '"hunter22"'), '"hu***"')
        self.assertEqual(V.safe_expr("Password", '""'), '""')                         # empty: nothing to hide
        self.assertEqual(V.safe_expr("Password", 'DocumentProperty("Secret")'), 'DocumentProperty("Secret")')
        self.assertEqual(V.safe_expr("Server", '"db01"'), '"db01"')

    def test_textarea_names(self):
        self.assertEqual(V.textarea_words("panelControls"), ["Panel", "Controls"])
        self.assertEqual(V.textarea_safe_name("a b"), "a_b")
        self.assertEqual(V.normalize_color("#e94165"), "#FFE94165")
        self.assertEqual(V.normalize_color("#80E94165"), "#80E94165")


class ExpectedAxesTest(unittest.TestCase):
    def axes(self, vspec, columns=()):
        return dict((a, e) for a, e, _ in V.expected_axes(vspec, list(columns)))

    def test_line_chart(self):
        got = self.axes({"type": "lineChart", "x": "Month", "y": ["Sum([A]) as [Alpha]", "Sum([B])"],
                         "lineBy": "[Pump]", "yScale": {"title": "ignored for two measures"},
                         "trellis": {"panelBy": ["[Region]", "Station"]}}, columns=["Month", "Station"])
        self.assertEqual(got["XAxis"], "[Month]")                                   # bare column escaped
        self.assertEqual(got["YAxis"], "Sum([A]) as [Alpha], Sum([B])")
        self.assertEqual(got["ColorAxis"], "<[Axis.Default.Names]>")                # several measures
        self.assertEqual(got["LineByAxis"], "<[Pump]>")
        self.assertEqual(got["Trellis.PanelAxis"], "<[Region] NEST [Station]>")

    def test_scale_title_and_props(self):
        got = self.axes({"type": "barChart", "x": "<[Station]>", "y": "Avg([$Metric])",
                         "yScale": {"title": "Head (ft)"}})
        self.assertEqual(got["YAxis"], 'Avg(DocumentProperty("Metric")) as [Head (ft)]')
        self.assertNotIn("ColorAxis", got)

    def test_histogram_treemap_combination(self):
        self.assertEqual(self.axes({"type": "histogram", "column": "Flow", "bins": 12}, ["Flow"])["XAxis"],
                         "BinByEvenIntervals([Flow], 12) as [Flow]")
        self.assertEqual(self.axes({"type": "treemap", "hierarchy": ["[A]", "[B]"], "size": "Count()",
                                    "colorBy": "<[Status]>"})["ColorAxis"], "UniqueConcatenate([Status])")
        comb = self.axes({"type": "combinationChart", "x": "[Day]",
                          "series": [{"expression": "Sum([Basis])", "kind": "bar"},
                                     {"expression": "Avg([Rate]) as [Rate]", "kind": "line"}]})
        self.assertEqual(comb["YAxis"], "Sum([Basis]) as [Sum(Basis)], Avg([Rate]) as [Rate]")
        self.assertEqual(comb["ColorAxis"], "<[Axis.Default.Names]>")

    def test_cross_table_and_kpis(self):
        ct = self.axes({"type": "crossTable", "rows": ["[Axis.Default.Names]"], "columns": ["Calendar Period"],
                        "measures": ["Sum([A]) as [A]", "Sum([B]) as [B]"]}, ["Calendar Period"])
        self.assertEqual(ct["RowAxis"], "<[Axis.Default.Names]>")
        self.assertEqual(ct["ColumnAxis"], "<[Calendar Period]>")
        self.assertEqual(ct["MeasureAxis"], "Sum([A]) as [A], Sum([B]) as [B]")
        ct2 = self.axes({"type": "crossTable", "rows": ["Region"], "measures": ["Sum([A])", "Sum([B])"]}, ["Region"])
        self.assertEqual(ct2["ColumnAxis"], "<[Axis.Default.Names]>")             # Names added to the columns
        kpi = self.axes({"type": "kpiChart", "kpis": [{"title": "PV10", "value": "Sum([PV10 ($)])", "tileBy": "Well"}]},
                        ["Well"])
        self.assertEqual(kpi["kpis[0].YAxis"], "Sum([PV10 ($)])")
        self.assertEqual(kpi["kpis[0].TileAxis"], "<[Well]>")

    def test_layout_worked_example(self):
        # references/dxp-anatomy.md section 5: row[text 20, column 80[trend 60, row 40[a, b]]]
        tree = {"row": [{"visual": "text", "weight": 20},
                        {"column": [{"visual": "trend", "weight": 60},
                                    {"row": [{"visual": "a"}, {"visual": "b"}], "weight": 40}], "weight": 80}]}
        got = V.pages_expected(tree)
        self.assertEqual(got["text"], [0, 0, 20000, 100000])
        self.assertEqual(got["trend"], [20003, 0, 79997, 60000])
        self.assertEqual(got["a"], [20003, 60003, 39997, 39997])
        self.assertEqual(got["b"], [60003, 60003, 39997, 39997])


# ------------------------------------------------------------------------------------------------
# a tiny synthetic DXP: robustness of the model and the dump command line
# ------------------------------------------------------------------------------------------------
MINI_DOC = (
    '<?xml version="1.0" encoding="utf-8"?><Root xmlns="http://www.spotfire.com/schemas/Document1.0.xsd" '
    'SchemaVersion="1.0"><Object Id="1"><Type><TypeObject Id="2" AssemblyName="Spotfire.Dxp.Application" '
    'FullTypeName="Spotfire.Dxp.Application.Document" /></Type><Fields><Field Name="KnownTheme"><Enum '
    'Value="DarkSfx"><Type><TypeObject Id="3" AssemblyName="Spotfire.Dxp.Application" '
    'FullTypeName="Spotfire.Dxp.Application.KnownTheme" /></Type></Enum></Field><Field Name="UseCustomStyles">'
    '<Bool Value="false" /></Field></Fields></Object></Root>')
MINI_META = ('<?xml version="1.0"?><FileMetadata DocumentType="Analysis" SchemaVersion="1.0" '
             'CompatibilityVersion="15.0;14.8;14.6"><Contents><Property ArchiveElementType="AnalysisDocument" '
             'Version="15.0" ArchiveElementPath="AnalysisDocument.xml" /></Contents><Properties><Property '
             'Key="SavedByAssemblyFileVersion" Value="71.0.22206.3863" /></Properties></FileMetadata>')


class MiniDxpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-dxp-mini-", dir=TMP_ROOT))
        self.dxp = self.tmp / "mini.dxp"
        with zipfile.ZipFile(str(self.dxp), "w") as z:
            z.writestr("AnalysisDocument.xml", MINI_DOC)
            z.writestr("Metadata.xml", MINI_META)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_minimal_document(self):
        model, _, archive = V.build_model(self.dxp)
        archive.close()
        self.assertEqual(model["document"]["knownTheme"], "DarkSfx")
        self.assertIs(model["document"]["useCustomStyles"], False)
        for key in ("pages", "documentProperties", "scripts", "propertyTriggers", "dataFunctions", "tables",
                    "relations", "markings", "filteringSchemes"):
            self.assertEqual(model[key], [], key)
        self.assertEqual(model["archive"]["savedByAssemblyFileVersion"], "71.0.22206.3863")
        json.dumps(model)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(TOOLS / "verify_dxp.py")] + list(args),
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_dump_cli(self):
        out = self.tmp / "model.json"
        proc = self.run_cli("dump", str(self.dxp), "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["document"]["knownTheme"], "DarkSfx")
        proc = self.run_cli("dump", str(self.dxp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["archive"]["compatibilityVersion"], "15.0;14.8;14.6")

    def test_dump_cli_errors(self):
        self.assertEqual(self.run_cli("dump", str(self.tmp / "missing.dxp")).returncode, 2)
        bad = self.tmp / "bad.dxp"
        bad.write_bytes(b"not a zip")
        proc = self.run_cli("dump", str(bad))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot open", proc.stderr)
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("check", str(self.tmp / "no-such-app")).returncode, 2)


class ManualStepCheckTest(unittest.TestCase):
    """Text-area controls, property triggers and the theme have no public API: the builder leaves a marker
    for each control and lists the rest in MANUAL-STEPS. check reports an item that is not added yet as WARN
    (a manual step), an item added by hand as PASS or FAIL, and a control with neither marker nor control
    as FAIL."""

    SPEC = {"specVersion": 1, "app": {"name": "Manual Steps", "theme": {"base": "LightSfx", "customStyles": {
                "general": {"font-family": "Segoe UI"}}}},
            "properties": [{"name": "Mode", "type": "String", "default": "A"}],
            "scripts": [{"name": "Reset Mode", "code": "Document.Properties[\"Mode\"] = \"A\""}],
            "triggers": [{"property": "Mode", "script": "Reset Mode"}],
            "pages": [{"title": "Overview", "visuals": [
                {"id": "panel", "type": "textArea", "title": "Panel",
                 "html": "<p>Mode {{control:mode}} {{control:reset}}</p>",
                 "controls": {"mode": {"kind": "dropdown", "property": "Mode",
                                       "values": {"fixed": [{"value": "A"}, {"value": "B"}]}},
                              "reset": {"kind": "button", "label": "Reset", "script": "Reset Mode"}}}]}]}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-dxp-manual-", dir=TMP_ROOT))
        self.app = self.tmp / "manual"
        self.app.mkdir()
        (self.app / "spec.json").write_text(json.dumps(self.SPEC), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def checker(self):
        c = V.Checker(self.app, self.app / "spec.json", dxpgen)
        c.raw_doc = json.loads(json.dumps(self.SPEC))
        c.spec = dxpgen.resolve_spec(json.loads(json.dumps(self.SPEC)), self.app)
        return c

    @staticmethod
    def marker(text):
        return ('<span style="color: #B3261E; border: 1px dashed #B3261E; padding: 0 4px">[%s]</span>' % text)

    def text_area(self, html):
        c = self.checker()
        vs = c.spec["pages"][0]["visuals"][0]
        c.check_text_area('pages[0] "Overview" > panel', vs, {"htmlContent": html, "controls": [],
                                                              "danglingTokens": [], "jsScripts": []})
        return c.R.items

    def test_markers_are_manual_steps(self):
        html = "<p>Mode %s %s</p>" % (self.marker("Drop-down list: Mode"), self.marker("Button: Reset"))
        items = self.text_area(html)
        present = lines(items, "textAreas", None, "control present")
        self.assertEqual([it["status"] for it in present], ["WARN", "WARN"])
        self.assertIn("manual step", present[0]["note"])
        html_line = lines(items, "textAreas", None, "HTML as specified")[0]
        self.assertEqual(html_line["status"], "PASS", html_line)
        self.assertFalse([it for it in items if it["status"] == "FAIL"], items)

    def test_slim_tier_marker_and_missing_marker(self):
        html = "<p>Mode %s</p>" % self.marker("control: mode")
        items = self.text_area(html)
        present = dict((it["path"].rsplit(" ", 1)[-1], it["status"])
                       for it in lines(items, "textAreas", None, "control present"))
        self.assertEqual(present, {"mode": "WARN", "reset": "FAIL"})

    def test_unknown_marker_fails(self):
        html = "<p>%s %s %s</p>" % (self.marker("Drop-down list: Mode"), self.marker("Button: Reset"),
                                    self.marker("control: ghost"))
        bad = [it for it in self.text_area(html) if it["status"] == "FAIL"]
        self.assertEqual([it["check"] for it in bad], ["no marker of a control the spec does not describe"])

    def test_trigger_and_theme_not_added_yet(self):
        c = self.checker()
        c.model = {"propertyTriggers": []}
        c.check_triggers()
        self.assertEqual([it["status"] for it in c.R.items], ["WARN"])
        self.assertIn("manual step", c.R.items[0]["note"])
        c.model = {"propertyTriggers": [{"property": "Mode", "script": "Other Script"}]}
        c.R = V.Results()
        c.check_triggers()
        self.assertEqual(lines(c.R.items, "triggers", None, "runs script")[0]["status"], "FAIL")


class CheckCommandLineTest(unittest.TestCase):
    """check and dxpgen.py verify on an app whose DXP has not been built yet ."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-dxp-cli-", dir=TMP_ROOT))
        self.app = self.tmp / "unbuilt"
        self.app.mkdir()
        (self.app / "spec.json").write_text(json.dumps({"specVersion": 1, "app": {"name": "Unbuilt App"},
                                                        "pages": [{"title": "Overview", "visuals": []}]}),
                                            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_missing_dxp(self):
        proc = subprocess.run([sys.executable, "-B", str(TOOLS / "verify_dxp.py"), "check", str(self.app)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("NOT CHECKED", proc.stdout)
        data = json.loads((self.app / "build" / "verify-report.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "NOT CHECKED")
        self.assertTrue(data["dxp"].endswith("Unbuilt App.dxp"))
        self.assertEqual(data["checks"][0]["check"], "DXP present")

    def test_dxpgen_verify_calls_verify_dxp(self):
        proc = subprocess.run([sys.executable, "-B", str(TOOLS / "dxpgen.py"), "verify", str(self.app)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("not available", proc.stderr)
        self.assertIn("verify unbuilt: NOT CHECKED", proc.stdout)
        self.assertTrue((self.app / "build" / "verify-report.md").is_file())

    def test_in_process_main(self):
        buf = io.StringIO()
        args = V.build_parser().parse_args(["check", str(self.app)])
        self.assertEqual(V.cmd_check(args, out=buf), 2)
        self.assertIn("DXP present", buf.getvalue())

    def test_bare_app_argument_means_check(self):
        proc = subprocess.run([sys.executable, "-B", str(TOOLS / "verify_dxp.py"), str(self.app)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("verify unbuilt: NOT CHECKED", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
