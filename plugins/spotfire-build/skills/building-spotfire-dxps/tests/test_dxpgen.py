"""Tests for scripts/dxpgen.py. Run: python tests/test_dxpgen.py  (or python -m pytest tests).

Every test works in a temporary workspace (DXP_BUILDER_HOME) and an empty tools folder, so the
optional external tools (lint_ipy.py) are absent unless a test provides a fake one;
the built-in sanitizer emulation and the API-index settings check always run. Nothing here starts
Spotfire or touches the clipboard.
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True                    # keep scripts/ free of __pycache__
sys.path.insert(0, str(SKILL / "scripts"))
import dxpgen  # noqa: E402

HAS_INDEX = dxpgen.find_index_file() is not None


# ------------------------------------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------------------------------------
def minimal_spec(name="Pump Station Monitor"):
    return {"specVersion": 1, "app": {"name": name},
            "pages": [{"title": "Overview",
                       "visuals": [{"id": "intro", "type": "textArea", "title": "Intro",
                                    "html": "<p style=\"margin: 0;\">Hello</p>"}]}]}


CONTROLS_HTML = ('<div class="panel"><p>Pump {{control:pumpSelect}}</p>'
                 '<p>{{control:window}} {{control:stations}} {{control:events}}</p>'
                 '<p>{{control:reset}} {{control:toDetail}} {{control:openDetail}} R2: {{control:r2}}</p></div>')

FULL_FILES = {
    "data/PUMP_DATA.sbdf": b"stub sbdf",
    "data/PUMP_EVENTS.csv": "Event ID,Pump ID,Start\n",
    "datafunctions/calculate_pump_curves.py": ("import pandas as pd\n"
                                               "PUMP_CURVES = pd.DataFrame({'Pump ID': []})\n"
                                               "OutR2 = 0.0\n"),
    "scripts/reset_pump_selection.py": 'Document.Properties["SelectedPumpId"] = "P-101"\n',
    "html/controls.html": CONTROLS_HTML,
    "html/controls.css": ".panel { padding: 8px; }\n",
    "html/Show Render Time.js": "var renderedAt = new Date();\n",
    "html/theme.json": '{"general": {"baseTheme": "DarkSfx", "font-family": "Roboto"}}',
}


def full_spec():
    """Uses every section of references/spec-format.md; valid (no errors)."""
    return {
        "specVersion": 1,
        "app": {"name": "Pump Station Monitor", "theme": {"base": "DarkSfx", "customStyles": "html/theme.json"}},
        "tables": [
            {"name": "PUMP_DATA", "source": {"type": "sbdf", "path": "data/PUMP_DATA.sbdf"},
             "calculatedColumns": [{"name": "Head (ft)", "expression": "[Discharge Pressure (psig)] * 2.31"}],
             "columns": {"Flow Rate (bbl/d)": {"description": "Metered flow", "format": "#,##0.0"}}},
            {"name": "PUMP_EVENTS", "source": {"type": "csv", "path": "data/PUMP_EVENTS.csv",
                                               "columns": {"Event ID": "String", "Pump ID": "String",
                                                           "Start": "DateTime"}}},
            {"name": "PUMP_CURVES", "source": {"type": "dataFunction", "function": "Calculate Pump Curves",
                                               "output": "PUMP_CURVES"}, "description": "Curve fits"},
        ],
        "defaultTable": "PUMP_DATA",
        "relations": [{"left": "PUMP_DATA", "right": "PUMP_EVENTS", "on": [["Pump ID", "Pump ID"]]}],
        "markings": [{"name": "Selected Pump", "color": "#E94165", "default": True}],
        "filteringSchemes": [{"name": "Fleet Filters"}],
        "properties": [
            {"name": "SelectedPumpId", "type": "String", "default": "P-101"},
            {"name": "AlertThreshold", "type": "Real", "default": 1200.0},
            {"name": "TrendWindowDays", "type": "Integer", "default": 30},
            {"name": "ShowEvents", "type": "Boolean", "default": True},
            {"name": "SelectedStations", "type": "String", "default": ["North"], "listValued": True},
            {"name": "OutR2", "type": "Real", "default": 0.0},
        ],
        "dataFunctions": [{
            "name": "Calculate Pump Curves", "script": "datafunctions/calculate_pump_curves.py",
            "inputs": [
                {"name": "PUMP_DATA", "type": "table",
                 "bind": {"table": "PUMP_DATA", "columns": "*", "limitByFiltering": "Fleet Filters"}},
                {"name": "SelectedPumpId", "type": "value", "dataTypes": ["String"],
                 "bind": {"property": "SelectedPumpId"}},
                {"name": "minPoints", "type": "value", "dataTypes": ["Integer"], "bind": {"value": 20}},
            ],
            "outputs": [
                {"name": "PUMP_CURVES", "type": "table", "target": {"table": "PUMP_CURVES"}},
                {"name": "OutR2", "type": "value", "target": {"property": "OutR2"}},
            ],
            "executeAtBuild": True}],
        "scripts": [
            {"name": "Reset Pump Selection", "file": "scripts/reset_pump_selection.py"},
            {"name": "Open Page", "code": "Document.ActivePageReference = targetPage\n",
             "parameters": [{"name": "targetPage", "type": "Page"}]},
        ],
        "triggers": [{"property": "AlertThreshold", "script": "Reset Pump Selection"}],
        "pages": [
            {"title": "Fleet Overview",
             "visuals": [
                 {"id": "controls", "type": "textArea", "title": "Controls", "showTitle": False,
                  "html": "html/controls.html", "css": "html/controls.css", "js": ["html/Show Render Time.js"],
                  "controls": {
                      "pumpSelect": {"kind": "dropdown", "property": "SelectedPumpId",
                                     "values": {"column": {"table": "PUMP_DATA", "column": "Pump ID"}}},
                      "window": {"kind": "slider", "property": "TrendWindowDays", "min": 7, "max": 365},
                      "stations": {"kind": "multiSelectListbox", "property": "SelectedStations",
                                   "values": {"fixed": [{"text": "North", "value": "North"}]}},
                      "events": {"kind": "checkbox", "property": "ShowEvents"},
                      "reset": {"kind": "button", "label": "Reset", "script": "Reset Pump Selection"},
                      "toDetail": {"kind": "link", "label": "Pump detail", "action": {"gotoPage": "Pump Detail"}},
                      "openDetail": {"kind": "button", "label": "Open detail", "script": "Open Page",
                                     "args": {"targetPage": "Pump Detail"}},
                      "r2": {"kind": "label", "property": "OutR2"}}},
                 {"id": "trend", "type": "lineChart", "title": "Discharge Pressure", "x": "[Timestamp]",
                  "y": "Avg([Discharge Pressure (psig)])",
                  "referenceLayers": [{"kind": "horizontalLine", "value": "[$AlertThreshold]", "color": "#E94165"}],
                  "settings": {"Legend.Visible": False, "XAxis.Scale.ShowGridlines": True}},
                 {"id": "curves", "type": "table", "title": "Pump Curves", "table": "PUMP_CURVES",
                  "marking": None},
             ],
             "layout": {"row": [{"visual": "controls", "weight": 20},
                                {"column": [{"visual": "trend"}, {"visual": "curves"}], "weight": 80}]}},
            {"title": "Pump Detail", "filteringScheme": "Fleet Filters",
             "visuals": [{"id": "events", "type": "barChart", "title": "Events by Pump", "table": "PUMP_EVENTS",
                          "x": "<[Pump ID]>", "y": "Count()"}]},
        ],
        "activePage": "Fleet Overview",
    }


def visual(spec, vid):
    for page in spec["pages"]:
        for v in page["visuals"]:
            if v["id"] == vid:
                return v
    raise KeyError(vid)


def run_main(argv):
    """(exit code, stdout, stderr) of dxpgen.main."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dxpgen.main(argv)
    return code, out.getvalue(), err.getvalue()


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dxpgen-test-"))
        self.ws = self.tmp / "ws"
        self.tools = self.tmp / "tools"           # empty: no external tools
        self.tools.mkdir()
        self._env = os.environ.get(dxpgen.WORKSPACE_ENV)
        os.environ[dxpgen.WORKSPACE_ENV] = str(self.ws)

    def tearDown(self):
        if self._env is None:
            os.environ.pop(dxpgen.WORKSPACE_ENV, None)
        else:
            os.environ[dxpgen.WORKSPACE_ENV] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_app(self, spec, files=None, slug="TestApp"):
        app = self.ws / "apps" / slug
        if app.exists():
            shutil.rmtree(app)
        for sub in ("data", "html", "scripts", "datafunctions", "build"):
            (app / sub).mkdir(parents=True)
        for rel, content in (files or {}).items():
            target = app / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
        if isinstance(spec, str):
            (app / "spec.json").write_text(spec, encoding="utf-8")
        else:
            (app / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return app

    def options(self, **kw):
        return dxpgen.Options(lint=kw.get("lint", True), sanitize=kw.get("sanitize", True),
                              tools_dir=kw.get("tools_dir", self.tools))

    def validate(self, spec, files=None, **kw):
        app = self.make_app(spec, FULL_FILES if files is None else files)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json", self.options(**kw))
        return report

    def assertHasError(self, report, path_part, text_part):
        for item in report.errors:
            if path_part in item["path"] and text_part in item["message"]:
                return item
        self.fail("no error at '%s' containing '%s'\n%s" % (path_part, text_part, report.render()))

    def assertHasWarning(self, report, path_part, text_part):
        for item in report.warnings:
            if path_part in item["path"] and text_part in item["message"]:
                return item
        self.fail("no warning at '%s' containing '%s'\n%s" % (path_part, text_part, report.render()))

    def assertClean(self, report):
        self.assertEqual(report.errors, [], report.render())


# ------------------------------------------------------------------------------------------------
# build
# ------------------------------------------------------------------------------------------------
class BuildTests(AppTestCase):
    """dxpgen build: the standard engine by default, the whole library only with --tier full."""

    def build(self, spec, files=None, tier=None):
        app = self.make_app(spec, files)
        argv = ["build", str(app), "--no-lint", "--tools-dir", str(self.tools)]
        if tier:
            argv += ["--tier", tier]
        code, out, err = run_main(argv)
        return app, code, out, err

    def builder_text(self, app, tier="standard"):
        return (app / "build" / ("build_%s_%s.py" % (app.name, tier))).read_text(encoding="utf-8")

    def test_minimal_spec_builds_the_standard_tier_by_default(self):
        app, code, out, err = self.build(minimal_spec(), {})
        self.assertEqual(code, 0, out + err)
        self.assertFalse((app / "build" / "build_TestApp.py").exists())     # no full-library builder
        text = self.builder_text(app)
        ast.parse(text)
        self.assertTrue(text.isascii())
        self.assertLessEqual(max(len(line) for line in text.split("\n")), 79)
        self.assertEqual(text.rstrip("\n").splitlines()[-1], "finish()")
        self.assertIn('untick "Execute in transaction"', text)
        self.assertIn("Standard builder written:", out)
        self.assertIn('untick "Execute in transaction"', out)
        self.assertIn("Close the dialog with Cancel", out)
        self.assertIn("Pump Station Monitor standard.dxp", out)
        self.assertNotIn("lib/00_core.py", text)

    def test_full_tier_concatenates_the_library(self):
        app, code, out, err = self.build(minimal_spec(), {}, tier="full")
        self.assertEqual(code, 0, out + err)
        builder = app / "build" / "build_TestApp_full.py"
        self.assertTrue(builder.is_file())
        text = builder.read_text(encoding="utf-8")
        ast.parse(text)                                   # the generated builder parses
        lines = text.rstrip("\n").splitlines()
        self.assertEqual(lines[-1], "run_build()")
        self.assertTrue(lines[-2].startswith("B = BuildContext(SPEC, APP_DIR, Document, Application, "))
        self.assertTrue(lines[-3].startswith("APP_DIR = "))
        spec_sha = hashlib.sha256((app / "spec.json").read_bytes()).hexdigest()
        self.assertIn("# spec.json sha256: " + spec_sha, text)
        self.assertIn('"%s"' % spec_sha, lines[-2])
        for lib in dxpgen.library_files():                # every lib module, in file-name order
            self.assertIn("lib/" + lib.name + " ", text)
        positions = [text.index("lib/" + lib.name + " ") for lib in dxpgen.library_files()]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Edit > Document Properties > Scripts > New", text)
        self.assertIn("Full-library builder written:", out)
        self.assertIn("WARNING: the full library is too big", out)
        self.assertIn("Close the dialog with Cancel", out)

    def test_builder_spec_literal_is_the_resolved_spec(self):
        spec = full_spec()
        app, code, out, err = self.build(spec, FULL_FILES, tier="full")
        self.assertEqual(code, 0, out + err)
        tree = ast.parse(self.builder_text(app, "full"))
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("SPEC", "APP_DIR"):
                    found[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(found["SPEC"], dxpgen.library_spec(dxpgen.resolve_spec(spec, app)))
        self.assertEqual(Path(found["APP_DIR"]), app.resolve())
        self.assertTrue(self.builder_text(app, "full").isascii())

    def test_spec_literal_is_plain_python34(self):
        value = {"html": "<p>caf\u00e9 \u00b2 \u2014 '\"\\</p>\n" * 30, "n": 1, "x": 1.5e-05, "b": True, "z": None,
                 "list": [1, "two", [3.0]]}
        text = dxpgen.spec_literal(value)
        self.assertTrue(text.isascii())
        self.assertEqual(ast.literal_eval(text), value)
        tree = ast.parse("SPEC = " + text)
        allowed = (ast.Module, ast.Assign, ast.Name, ast.Store, ast.Load, ast.Dict, ast.List, ast.Constant,
                   ast.UnaryOp, ast.USub)
        for node in ast.walk(tree):
            self.assertIsInstance(node, allowed)

    def test_build_aborts_on_validation_errors(self):
        spec = minimal_spec()
        del spec["app"]["name"]
        app, code, out, err = self.build(spec, {})
        self.assertEqual(code, 1)
        self.assertIn("Build aborted", out)
        self.assertFalse((app / "build" / "build_TestApp_standard.py").exists())

    def test_full_spec_builds_with_the_library_tiers(self):
        app, code, out, err = self.build(full_spec(), FULL_FILES, tier="full")
        self.assertEqual(code, 0, out + err)
        ast.parse(self.builder_text(app, "full"))
        app, code, out, err = self.build(full_spec(), FULL_FILES, tier="slim")
        self.assertEqual(code, 0, out + err)
        text = (app / "build" / "build_TestApp_slim.py").read_text(encoding="utf-8")
        ast.parse(text)
        self.assertIn("Pump Station Monitor slim.dxp", text)

    def test_full_spec_is_not_in_the_standard_engine(self):
        app, code, out, err = self.build(full_spec(), FULL_FILES)
        self.assertEqual(code, 1, out + err)
        self.assertIn("not in the standard engine yet: use --tier slim", out)
        # properties, data functions, scripts, control markers and text-area JavaScript are standard-engine
        # features (tests/test_features.py, tests/test_kitchen_features.py)
        for path in ("relations", "tables[1].source", "pages[0].visuals[0].css",
                     "dataFunctions[0].inputs[0].bind.limitByFiltering"):
            self.assertIn("  %s: " % path, out)
        for path in ("triggers", "pages[0].visuals[0].js"):
            self.assertNotIn("  %s: " % path, out)
        self.assertFalse((app / "build" / "build_TestApp_standard.py").exists())

    @unittest.skipUnless(os.name == "nt", "PowerShell clipboard path is Windows-only")
    def test_clipboard_text_has_crlf(self):
        app, code, out, err = self.build(minimal_spec(), {})
        builder = app / "build" / "build_TestApp_standard.py"
        sink = self.tmp / "clipboard.txt"
        ok, problem = dxpgen.copy_to_clipboard(builder, sink=sink)
        self.assertTrue(ok, problem)
        data = sink.read_bytes()
        self.assertEqual(data.replace(b"\r\n", b"").count(b"\n"), 0)
        self.assertEqual(data.decode("utf-8-sig").replace("\r\n", "\n"), builder.read_text(encoding="utf-8"))


class LibraryCheckTests(unittest.TestCase):
    def test_reports_duplicates_missing_functions_and_builders(self):
        parts = [("00_core.py", "class BuildContext(object):\n    pass\n\ndef helper():\n    return 1\n"),
                 ("50_x.py", "def helper():\n    return vis_common()\n"),
                 ("90_build.py", "VISUAL_BUILDERS = {'lineChart': 'vis_line'}\n\ndef run_build():\n    helper()\n")]
        spec = {"pages": [{"visuals": [{"type": "lineChart"}, {"type": "map"}]}]}
        issues = dxpgen.library_check(parts, spec)
        text = "\n".join(m for _, m in issues)
        self.assertIn("'helper' is defined in lib/00_core.py and again in lib/50_x.py", text)
        self.assertIn("vis_common() is used by lib/50_x.py but no lib module defines it (expected in lib/60_charts.py)",
                      text)
        self.assertIn("no lib module defines vis_line() for visual type 'lineChart'", text)
        self.assertIn("no entry for visual type 'map'", text)
        self.assertFalse(any(level == "error" for level, _ in issues))

    def test_real_library_has_entry_points(self):
        parts = [(f.name, f.read_text(encoding="utf-8")) for f in dxpgen.library_files()]
        issues = dxpgen.library_check(parts, {"pages": []})
        self.assertFalse([m for level, m in issues if level == "error"], issues)


# ------------------------------------------------------------------------------------------------
# defaults (references/architecture.md "Resolved spec")
# ------------------------------------------------------------------------------------------------
class ResolveTests(AppTestCase):
    def test_defaults_filled(self):
        app = self.make_app(full_spec(), FULL_FILES)
        r = dxpgen.resolve_spec(full_spec(), app)
        a = r["app"]
        self.assertEqual(a["output"], "build/Pump Station Monitor.dxp")
        self.assertEqual(a["namingPolicy"], "program")
        self.assertEqual(a["htmlMode"], "safe")
        self.assertEqual(a["pageNavigation"], "Tabs")
        self.assertEqual(a["snapshots"], {"enabled": True, "width": 1600, "height": 900})
        self.assertEqual(a["minimumSpotfireVersion"], "14.6")
        self.assertEqual(a["description"], "")
        self.assertEqual(a["keywords"], [])
        self.assertIsNone(a["canvas"])
        self.assertEqual(a["theme"]["base"], "DarkSfx")
        self.assertEqual(a["theme"]["customStyles"], {"general": {"baseTheme": "DarkSfx", "font-family": "Roboto"}})
        # tables: absolute paths, embed, csv reader defaults
        data, events, curves = r["tables"]
        self.assertTrue(Path(data["source"]["path"]).is_absolute())
        self.assertEqual(Path(data["source"]["path"]), (app / "data" / "PUMP_DATA.sbdf").resolve())
        self.assertTrue(data["embed"] and events["embed"] and curves["embed"])
        self.assertEqual(data["calculatedColumns"][0]["description"], "")
        self.assertEqual(events["source"]["separator"], ",")
        self.assertEqual(events["source"]["culture"], "en-US")
        self.assertEqual(events["source"]["encoding"], "utf-8")
        self.assertIs(events["source"]["header"], True)
        self.assertEqual(curves["hierarchies"], [])
        # markings, schemes, properties
        self.assertIs(r["filteringSchemes"][0]["default"], False)
        prop = r["properties"][0]
        self.assertEqual((prop["description"], prop["listValued"]), ("", False))
        # data function: defaults and inlined code
        df = r["dataFunctions"][0]
        self.assertEqual((df["engine"], df["refresh"], df["executeAtBuild"], df["description"]),
                         ("python", "automatic", True, ""))
        self.assertIn("OutR2 = 0.0", df["scriptCode"])
        self.assertIsNone(df["inputs"][0]["bind"]["limitByMarking"])
        # scripts: code from file, transaction default true
        reset, open_page = r["scripts"]
        self.assertIn('Document.Properties["SelectedPumpId"]', reset["code"])
        self.assertEqual(reset["file"], "scripts/reset_pump_selection.py")
        self.assertIs(reset["transaction"], True)
        self.assertEqual(reset["parameters"], [])
        self.assertEqual(open_page["parameters"][0]["description"], "")
        # pages
        overview, detail = r["pages"]
        self.assertEqual((detail["visible"], detail["filterPanel"], detail["detailsOnDemand"]), (True, False, False))
        self.assertEqual(detail["layout"], {})
        # visuals: common defaults, default table and marking, explicit null kept
        trend = visual(r, "trend")
        self.assertIs(trend["showTitle"], True)
        self.assertEqual(trend["legend"], {"visible": True})
        self.assertEqual(trend["table"], "PUMP_DATA")
        self.assertEqual(trend["marking"], "Selected Pump")
        self.assertEqual(trend["limitByMarkings"], [])
        self.assertEqual(trend["emptyMarkingBehavior"], "ShowAll")
        self.assertIs(trend["useFiltering"], True)
        self.assertIsNone(trend["coloring"])
        self.assertEqual(trend["fittingModels"], [])
        self.assertIsNone(trend["postScript"])
        self.assertEqual(trend["description"], "")
        self.assertIsNone(visual(r, "curves")["marking"])
        # text area: html/css/js inlined, placeholders intact, control defaults
        ta = visual(r, "controls")
        self.assertEqual(ta["html"], CONTROLS_HTML)
        self.assertIn("{{control:pumpSelect}}", ta["html"])
        self.assertEqual(ta["css"], ".panel { padding: 8px; }\n")
        self.assertEqual(ta["js"], [{"name": "Show Render Time", "code": "var renderedAt = new Date();\n"}])
        self.assertEqual(ta["controls"]["window"]["step"], 1)
        self.assertEqual(ta["controls"]["reset"]["args"], {})
        self.assertNotIn("legend", ta)
        self.assertNotIn("marking", ta)

    def test_minimal_defaults_and_builtin_marking(self):
        spec = minimal_spec()
        spec["pages"][0]["visuals"].append({"id": "chart", "type": "histogram", "column": "[Flow]"})
        spec["pages"][0]["visuals"].append({"id": "map", "type": "map", "layers": [{"kind": "tile"}],
                                            "legend": False, "xScale": None})
        spec["pages"][0]["visuals"][0]["css"] = None
        app = self.make_app(spec, {})
        r = dxpgen.resolve_spec(spec, app)
        self.assertEqual(r["tables"], [])
        self.assertIsNone(r["defaultTable"])
        self.assertIsNone(r["activePage"])
        self.assertEqual(r["app"]["theme"], {"base": "LightSfx"})
        hist = visual(r, "chart")
        self.assertEqual(hist["bins"], 20)
        self.assertEqual(hist["marking"], "Marking")     # no markings: the built-in one is named Marking
        self.assertIsNone(hist["table"])
        self.assertEqual(visual(r, "map")["legend"], {"visible": False})
        self.assertIs(visual(r, "map")["autoZoom"], True)
        intro = visual(r, "intro")
        self.assertEqual((intro["css"], intro["js"], intro["controls"]), ("", [], {}))

    def test_scale_defaults(self):
        spec = minimal_spec()
        spec["pages"][0]["visuals"] = [{"id": "line", "type": "lineChart", "x": "[A]", "y": "[B]",
                                        "yScale": {"min": 0}, "xScale": {"gridlines": False}},
                                       {"id": "cube", "type": "scatterPlot3D", "x": "[A]", "y": "[B]", "z": "[C]",
                                        "zScale": {"log": True, "gridlines": None}}]
        r = dxpgen.resolve_spec(spec, self.make_app(spec, {}))
        # gridlines is never filled: an absent value keeps Spotfire's default for that axis (lib/60_charts.py)
        self.assertEqual(visual(r, "line")["yScale"], {"min": 0, "max": None, "log": False,
                                                        "individualScaling": False, "title": None})
        self.assertIs(visual(r, "line")["xScale"]["gridlines"], False)
        self.assertEqual(visual(r, "cube")["zScale"], {"log": True, "gridlines": None, "min": None, "max": None,
                                                        "individualScaling": False, "title": None})
        self.assertNotIn("xScale", visual(r, "cube"))


# ------------------------------------------------------------------------------------------------
# validation
# ------------------------------------------------------------------------------------------------
class ValidSpecTests(AppTestCase):
    def test_full_spec_is_valid(self):
        self.assertClean(self.validate(full_spec()))

    def test_minimal_spec_is_valid(self):
        report = self.validate(minimal_spec(), {})
        self.assertClean(report)
        self.assertEqual(report.warnings, [], report.render())


class StructureErrorTests(AppTestCase):
    def check(self, mutate, path_part, text_part, files=None):
        spec = full_spec()
        mutate(spec)
        return self.assertHasError(self.validate(spec, files), path_part, text_part)

    def test_missing_required_fields(self):
        self.check(lambda s: s["app"].pop("name"), "app.name", "missing required field 'name'")
        self.check(lambda s: s["properties"][0].pop("type"), "properties[0].type", "missing required field")
        self.check(lambda s: visual(s, "trend").pop("type"), "pages[0].visuals[1].type", "missing required field")
        self.check(lambda s: s["tables"][0].pop("source"), "tables[0].source", "missing required field")

    def test_wrong_types(self):
        self.check(lambda s: visual(s, "trend").update(showTitle="yes"), "visuals[1].showTitle", "must be true or false")
        self.check(lambda s: s.update(pages={}), "pages", "must be a list")
        self.check(lambda s: s["app"].update(minimumSpotfireVersion=14.6), "app.minimumSpotfireVersion",
                   "must be a string")
        self.check(lambda s: s["markings"][0].update(color="red"), "markings[0].color", "#RRGGBB")

    def test_unknown_enumerations(self):
        item = self.check(lambda s: visual(s, "trend").update(type="lineChrt"), "visuals[1].type", "must be one of")
        self.assertIn("did you mean 'lineChart'", item["message"])
        self.check(lambda s: s["app"].update(pageNavigation="Tab"), "app.pageNavigation", "must be one of")
        self.check(lambda s: s["tables"][0]["source"].update(type="xlsx"), "tables[0].source.type", "must be one of")

    def test_duplicate_visual_ids(self):
        self.check(lambda s: visual(s, "events").update(id="trend"), "pages[1].visuals[0].id",
                   "visual id 'trend' is used twice")

    def test_duplicate_page_titles_case_insensitive(self):
        self.check(lambda s: s["pages"][1].update(title="fleet overview"), "pages[1].title", "used twice")

    def test_unknown_field_is_a_warning(self):
        spec = full_spec()
        visual(spec, "trend")["yScal"] = {"min": 0}
        report = self.validate(spec)
        self.assertClean(report)
        self.assertHasWarning(report, "visuals[1].yScal", "did you mean 'yScale'")


class ReferenceErrorTests(AppTestCase):
    def check(self, mutate, path_part, text_part):
        spec = full_spec()
        mutate(spec)
        return self.assertHasError(self.validate(spec), path_part, text_part)

    def test_tables(self):
        self.check(lambda s: visual(s, "events").update(table="PUMP_EVENT"), "visuals[0].table",
                   "unknown data table 'PUMP_EVENT'")
        self.check(lambda s: s.update(defaultTable="NOPE"), "defaultTable", "unknown data table")
        self.check(lambda s: s["relations"][0].update(right="NOPE"), "relations[0].right", "unknown data table")
        self.check(lambda s: s["dataFunctions"][0]["inputs"][0]["bind"].update(table="NOPE"),
                   "dataFunctions[0].inputs[0].bind.table", "unknown data table")

    def test_properties(self):
        self.check(lambda s: visual(s, "controls")["controls"]["r2"].update(property="OutR3"),
                   "controls.r2.property", "unknown document property 'OutR3'")
        self.check(lambda s: s["triggers"][0].update(property="Nope"), "triggers[0].property", "unknown document property")
        self.check(lambda s: visual(s, "trend")["referenceLayers"][0].update(value="[$Threshold]"),
                   "referenceLayers[0]", "unknown document property 'Threshold'")

    def test_scripts_markings_schemes_pages_functions(self):
        self.check(lambda s: visual(s, "controls")["controls"]["reset"].update(script="Reset All"),
                   "controls.reset.script", "unknown script 'Reset All'")
        self.check(lambda s: s["triggers"][0].update(script="Nope"), "triggers[0].script", "unknown script")
        self.check(lambda s: visual(s, "trend").update(marking="Selected Pumps"), "visuals[1].marking",
                   "unknown marking 'Selected Pumps'")
        self.check(lambda s: s["dataFunctions"][0]["inputs"][0]["bind"].update(limitByMarking="Nope"),
                   "bind.limitByMarking", "unknown marking")
        self.check(lambda s: s["pages"][1].update(filteringScheme="Detail Filters"), "pages[1].filteringScheme",
                   "unknown filtering scheme")
        self.check(lambda s: visual(s, "controls")["controls"]["toDetail"]["action"].update(gotoPage="Detail"),
                   "action.gotoPage", "unknown page")
        self.check(lambda s: visual(s, "controls")["controls"]["toDetail"].update(
            action={"refreshDataFunction": "Nope"}), "action.refreshDataFunction", "unknown data function")
        self.check(lambda s: s.update(activePage="Overview"), "activePage", "unknown page")
        self.check(lambda s: s["tables"][2]["source"].update(function="Nope"), "tables[2].source.function",
                   "unknown data function")

    def test_script_arguments(self):
        self.check(lambda s: visual(s, "controls")["controls"]["openDetail"]["args"].update(targetPage="Nope"),
                   "args.targetPage", "must be the title of a page")
        self.check(lambda s: visual(s, "controls")["controls"]["openDetail"]["args"].update(page="Pump Detail"),
                   "args.page", "has no parameter 'page'")


class LayoutErrorTests(AppTestCase):
    def check(self, layout, text_part, path_part="pages[0].layout"):
        spec = full_spec()
        spec["pages"][0]["layout"] = layout
        return self.assertHasError(self.validate(spec), path_part, text_part)

    def test_visual_missing_from_layout(self):
        self.check({"row": [{"visual": "controls"}, {"visual": "trend"}]}, "visual 'curves' is not in the layout")

    def test_visual_twice(self):
        self.check({"row": [{"visual": "controls"}, {"column": [{"visual": "trend"}, {"visual": "trend"},
                                                                 {"visual": "curves"}]}]},
                   "visual 'trend' appears 2 times")

    def test_unknown_and_foreign_visuals(self):
        self.check({"row": [{"visual": "controls"}, {"visual": "trend"}, {"visual": "curves"}, {"visual": "nope"}]},
                   "unknown visual 'nope'")
        self.check({"row": [{"visual": "controls"}, {"visual": "trend"}, {"visual": "curves"}, {"visual": "events"}]},
                   "belongs to page \"Pump Detail\"")

    def test_orientation_must_alternate(self):
        self.check({"row": [{"visual": "controls"}, {"row": [{"visual": "trend"}, {"visual": "curves"}]}]},
                   "nested containers must alternate", "pages[0].layout.row[1]")

    def test_layout_required_with_several_visuals(self):
        self.check({}, "required when a page has more than one visual")

    def test_bad_weight_and_empty_container(self):
        self.check({"row": [{"visual": "controls", "weight": -1}, {"column": [{"visual": "trend"},
                                                                              {"visual": "curves"}]}]},
                   "must be a positive number", "layout.row[0].weight")
        self.check({"row": [{"visual": "controls"}, {"visual": "trend"}, {"visual": "curves"}, {"column": []}]},
                   "must be a non-empty list", "layout.row[3].column")


class NamingTests(AppTestCase):
    def report(self, mutate, policy=None):
        spec = full_spec()
        if policy:
            spec["app"]["namingPolicy"] = policy
        mutate(spec)
        return self.validate(spec)

    def rename_property(self, spec, old, new):
        """Rename a property everywhere so only the naming rule can fail."""
        text = json.dumps(spec).replace('"%s"' % old, '"%s"' % new).replace("[$%s]" % old, "[$%s]" % new)
        spec.clear()
        spec.update(json.loads(text))

    def test_program_policy_violations(self):
        r = self.report(lambda s: self.rename_property(s, "TrendWindowDays", "trendWindowDays"))
        self.assertHasError(r, "properties[2].name", "must be PascalCase")
        r = self.report(lambda s: s["tables"][1].update(name="pumpEvents"))
        self.assertHasError(r, "tables[1].name", "must be UPPER_SNAKE_CASE")
        r = self.report(lambda s: s["scripts"][1].update(name="open page"))
        self.assertHasError(r, "scripts[1].name", "Title Case")
        r = self.report(lambda s: s["pages"][1].update(title="2. Pump Detail"))
        self.assertHasError(r, "pages[1].title", "no numbering")
        r = self.report(lambda s: s["markings"].append({"name": "Marking (2)", "color": "#3050EF"}))
        self.assertHasError(r, "markings[1].name", "auto-generated")
        r = self.report(lambda s: s["dataFunctions"][0].update(name="calculatePumpCurves"))
        self.assertHasError(r, "dataFunctions[0].name", "Title Case")
        r = self.report(lambda s: s["tables"][0]["calculatedColumns"][0].update(name="head_ft"))
        self.assertHasError(r, "calculatedColumns[0].name", "Title Case")

    def test_camel_case_policy(self):
        r = self.report(lambda s: None, policy="camelCase")
        self.assertHasError(r, "properties[0].name", "must be camelCase")
        self.assertHasError(r, "tables[0].name", "lowercase or camelCase")
        self.assertHasError(r, "scripts[0].name", "must be camelCase")
        self.assertHasError(r, "dataFunctions[0].name", "must be camelCase")

    def test_builtins_are_exempt(self):
        r = self.report(lambda s: s["properties"].append({"name": "MaxMissingTimeParts", "type": "Integer",
                                                           "default": 500000}))
        self.assertClean(r)

    def test_property_name_charset_and_case_duplicates(self):
        r = self.report(lambda s: s["properties"].append({"name": "Alert_Limit", "type": "Real"}))
        self.assertHasError(r, "properties[6].name", "only letters and digits")
        r = self.report(lambda s: s["properties"].append({"name": "selectedPumpID", "type": "String"}))
        self.assertHasError(r, "properties[6].name", "differs only in case")


class BindingTests(AppTestCase):
    def check(self, mutate, path_part, text_part, files=None):
        spec = full_spec()
        mutate(spec)
        return self.assertHasError(self.validate(spec, files), path_part, text_part)

    def test_value_input_must_have_property_name(self):
        self.check(lambda s: s["dataFunctions"][0]["inputs"][1].update(name="pumpId"),
                   "dataFunctions[0].inputs[1].name", "one name per binding")

    def test_value_output_must_have_property_name(self):
        def mutate(s):
            s["dataFunctions"][0]["outputs"][1]["name"] = "r2"
        files = dict(FULL_FILES)
        files["datafunctions/calculate_pump_curves.py"] = "PUMP_CURVES = None\nr2 = 1.0\n"
        self.check(mutate, "dataFunctions[0].outputs[1].name", "one name per binding", files)

    def test_control_binding_must_match_case(self):
        self.check(lambda s: visual(s, "controls")["controls"]["r2"].update(property="outR2"),
                   "controls.r2.property", "exactly like the property, 'OutR2'")

    def test_output_must_be_assigned_by_the_script(self):
        files = dict(FULL_FILES)
        files["datafunctions/calculate_pump_curves.py"] = "PUMP_CURVES = None\nr2 = 1.0\n# OutR2 = later\n"
        self.check(lambda s: None, "dataFunctions[0].outputs[1].name", "never assigns output 'OutR2'", files)

    def test_visual_needs_execute_at_build_table(self):
        self.check(lambda s: s["dataFunctions"][0].update(executeAtBuild=False), "pages[0].visuals[2].table",
                   "executeAtBuild: false")

    def test_limit_by_marking_is_one_name(self):
        self.check(lambda s: s["dataFunctions"][0]["inputs"][0]["bind"].update(limitByMarking=["Selected Pump"]),
                   "bind.limitByMarking", "must be one marking name")

    def test_integer_output_property_needs_numpy_int32(self):
        spec = full_spec()
        spec["properties"].append({"name": "OutCount", "type": "Integer", "default": 0})
        spec["dataFunctions"][0]["outputs"].append({"name": "OutCount", "type": "value",
                                                    "target": {"property": "OutCount"}})
        files = dict(FULL_FILES)
        files["datafunctions/calculate_pump_curves.py"] += "OutCount = 3\n"
        report = self.validate(spec, files)
        self.assertClean(report)
        self.assertHasWarning(report, "outputs[2].target.property", "numpy.int32")
        files["datafunctions/calculate_pump_curves.py"] += "import numpy\nOutCount = numpy.int32(3)\n"
        report = self.validate(spec, files)
        self.assertFalse([w for w in report.warnings if "numpy.int32" in w["message"]], report.render())

    def test_property_default_types(self):
        self.check(lambda s: s["properties"][1].update(default=1200), "properties[1].default",
                   "decimal point")
        self.check(lambda s: s["properties"][2].update(default="30"), "properties[2].default", "whole number")
        self.check(lambda s: s["properties"].append({"name": "ReportStart", "type": "DateTime",
                                                     "default": "2026-13-01T00:00:00"}),
                   "properties[6].default", "not a valid DateTime")
        self.check(lambda s: s["properties"][4].update(default="North"), "properties[4].default",
                   "must be a JSON list")


class TextAreaTests(AppTestCase):
    def check(self, mutate, path_part, text_part, files=None):
        spec = full_spec()
        mutate(spec)
        return self.assertHasError(self.validate(spec, files), path_part, text_part)

    def html_files(self, html):
        files = dict(FULL_FILES)
        files["html/controls.html"] = html
        return files

    def test_placeholder_without_control(self):
        self.check(lambda s: None, "visuals[0].html", "placeholder {{control:extra}} has no entry",
                   self.html_files(CONTROLS_HTML + "<p>{{control:extra}}</p>"))

    def test_control_without_placeholder(self):
        self.check(lambda s: None, "controls.r2", "control 'r2' is not placed",
                   self.html_files(CONTROLS_HTML.replace("{{control:r2}}", "")))

    def test_control_placed_twice(self):
        self.check(lambda s: None, "controls.reset", "placed 2 times",
                   self.html_files(CONTROLS_HTML + "<p>{{control:reset}}</p>"))

    def test_control_kinds_and_value_sources(self):
        self.check(lambda s: visual(s, "controls")["controls"]["events"].update(kind="toggle"), "controls.events.kind",
                   "must be one of")
        self.check(lambda s: visual(s, "controls")["controls"]["pumpSelect"].pop("values"),
                   "controls.pumpSelect.values", "missing required field")
        self.check(lambda s: visual(s, "controls")["controls"]["pumpSelect"]["values"].update(
            fixed=[{"text": "P-101", "value": "P-101"}]), "controls.pumpSelect.values", "exactly one of 'fixed' or 'column'")
        self.check(lambda s: visual(s, "controls")["controls"]["stations"].update(property="SelectedPumpId"),
                   "controls.stations.property", "list-valued property")
        self.check(lambda s: visual(s, "controls")["controls"]["events"].update(property="SelectedPumpId"),
                   "controls.events.property", "needs a Boolean property")
        self.check(lambda s: visual(s, "controls")["controls"]["window"].update(min=400), "controls.window",
                   "min must be smaller than max")
        self.check(lambda s: visual(s, "controls")["controls"]["window"].update(property="SelectedPumpId"),
                   "controls.window.property", "needs a numeric property")
        self.check(lambda s: visual(s, "controls")["controls"]["reset"].pop("script"), "controls.reset",
                   "needs 'script' or 'action'")
        self.check(lambda s: visual(s, "controls")["controls"]["pumpSelect"].update(
            property="TrendWindowDays", values={"fixed": [{"text": "A week", "value": "seven"}]}),
            "values.fixed[0].value", "whole number")

    def test_safe_html_is_checked_rich_is_not(self):
        html = CONTROLS_HTML + "<style>.panel{color:red}</style><div style=\"width: calc(100% - 4px)\">x</div>"
        report = self.validate(full_spec(), self.html_files(html))
        self.assertHasError(report, "visuals[0].html", "<style> is removed")
        self.assertHasError(report, "visuals[0].html", "calc(")
        spec = full_spec()
        spec["app"]["htmlMode"] = "rich"
        self.assertClean(self.validate(spec, self.html_files(html)))

    def test_inline_html_and_missing_html_file(self):
        self.check(lambda s: visual(s, "controls").update(html="html/missing.html"), "visuals[0].html",
                   "HTML file (inline HTML must start with '<') not found")

    def test_text_area_extras_the_builder_does_not_apply(self):
        spec = full_spec()
        visual(spec, "controls").update(description="Pump selection")
        visual(spec, "controls")["controls"]["window"]["showLabels"] = False
        report = self.validate(spec)
        self.assertClean(report)
        self.assertHasWarning(report, "visuals[0].description", "text areas have no description")
        self.assertHasWarning(report, "controls.window.showLabels", "always shows the slider's range labels")

    def test_inline_js_names(self):
        self.check(lambda s: visual(s, "controls").update(js=[{"name": "Show: Time", "code": "var x = 1;"}]),
                   "visuals[0].js[0]", "cannot contain")


class FileTests(AppTestCase):
    def test_missing_files(self):
        files = dict(FULL_FILES)
        for rel in ("data/PUMP_DATA.sbdf", "scripts/reset_pump_selection.py",
                    "datafunctions/calculate_pump_curves.py", "html/Show Render Time.js"):
            files.pop(rel)
        report = self.validate(full_spec(), files)
        self.assertHasError(report, "tables[0].source.path", "data file not found")
        self.assertHasError(report, "scripts[0].file", "script file not found")
        self.assertHasError(report, "dataFunctions[0].script", "data-function script not found")
        self.assertHasError(report, "visuals[0].js[0]", "JavaScript file not found")


@unittest.skipUnless(HAS_INDEX, "no api/spotfire-api-*.json")
class SettingsTests(AppTestCase):
    def check(self, settings, path_part, text_part, target="trend"):
        spec = full_spec()
        visual(spec, target)["settings"] = settings
        return self.assertHasError(self.validate(spec), path_part, text_part)

    def test_valid_paths_pass(self):
        spec = full_spec()
        visual(spec, "trend")["settings"] = {"YAxis.Scale.LabelOrientation": "Vertical", "LineWidth": 2,
                                             "ShowMarkers": True}
        spec["tables"][0]["settings"] = {"AutoCreateFilters": True}
        spec["tables"][0]["columns"]["Flow Rate (bbl/d)"]["settings"] = {"Visible": True}
        self.assertClean(self.validate(spec))

    def test_unknown_member(self):
        item = self.check({"XAxis.Scale.ShowGridLinez": True}, 'settings["XAxis.Scale.ShowGridLinez"]',
                          "has no public property 'ShowGridLinez'")
        self.assertIn("did you mean 'ShowGridlines'", item["message"])

    def test_read_only_member(self):
        self.check({"Legend": True}, 'settings.Legend', "read-only")

    def test_value_types(self):
        self.check({"YAxis.Scale.LabelOrientation": "Sideways"}, "LabelOrientation", "is not a member of")
        self.check({"ShowMarkers": "yes"}, "ShowMarkers", "needs true or false")

    def test_other_targets(self):
        spec = full_spec()
        spec["tables"][0]["settings"] = {"AutoCreateFilterz": True}
        self.assertHasError(self.validate(spec), "tables[0].settings", "DataTable has no public property")


class ToolIntegrationTests(AppTestCase):
    # one log file per call: validation lints in parallel, and concurrent appends to one file are not
    # atomic on Windows (lines got lost or mangled now and then)
    FAKE_LINT = (
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "open(%r + '.' + str(os.getpid()), 'w').write(json.dumps(args) + '\\n')\n"
        "src = open(args[0], encoding='utf-8').read()\n"
        "findings = []\n"
        "if 'f\"' in src:\n"
        "    findings.append({'path': args[0], 'line': 1, 'col': 5, 'severity': 'error', 'code': 'syntax',\n"
        "                     'message': 'f-string is not IronPython 3.4 syntax'})\n"
        "print(json.dumps({'files': [args[0]], 'errors': len(findings), 'warnings': 0, 'findings': findings}))\n"
        "sys.exit(1 if findings else 0)\n")

    def test_lint_findings_become_errors_and_parameters_are_globals(self):
        log = self.tmp / "lint-args.txt"
        (self.tools / "lint_ipy.py").write_text(self.FAKE_LINT % str(log), encoding="utf-8")
        spec = full_spec()
        spec["scripts"][1]["code"] = 'x = f"{targetPage}"\nDocument.ActivePageReference = targetPage\n'
        report = self.validate(spec)
        self.assertHasError(report, "scripts[1].code", "lint (script 'Open Page', line 1, col 5): f-string")
        calls = [json.loads(f.read_text()) for f in sorted(self.tmp.glob(log.name + ".*"))]
        open_page = [c for c in calls if "--globals" in c and "targetPage" in c[c.index("--globals") + 1]]
        self.assertTrue(open_page, calls)
        self.assertTrue(all("--document-script" in c and "--json" in c for c in calls), calls)

    def test_missing_tools_are_notes(self):
        report = self.validate(full_spec())
        notes = " ".join(n["message"] for n in report.notes)
        self.assertIn("lint_ipy.py not found", notes)
        self.assertNotIn("sf_sanitize", notes)                 # the sanitizer check is dxpgen's emulation


class JsonAndCliTests(AppTestCase):
    def test_invalid_json(self):
        app = self.make_app('{"specVersion": 1,\n "app": {"name": "X"},,}', {})
        code, out, err = run_main(["validate", str(app), "--tools-dir", str(self.tools)])
        self.assertEqual(code, 1)
        self.assertIn("invalid JSON at line 2, column 23", out)

    def test_duplicate_keys_and_nan(self):
        app = self.make_app('{"specVersion": 1, "app": {"name": "X", "name": "Y"}, "pages": []}', {})
        code, out, err = run_main(["validate", str(app), "--tools-dir", str(self.tools)])
        self.assertEqual(code, 1)
        self.assertIn("key 'name' appears twice", out)
        app = self.make_app('{"specVersion": 1, "app": {"name": "X", "canvas": {"width": NaN}}}', {})
        code, out, err = run_main(["validate", str(app), "--tools-dir", str(self.tools)])
        self.assertEqual(code, 1)
        self.assertIn("NaN is not allowed", out)

    def test_exit_codes_and_numbering(self):
        app = self.make_app(minimal_spec(), {})
        self.assertEqual(run_main(["validate", str(app), "--tools-dir", str(self.tools)])[0], 0)
        spec = full_spec()
        spec["app"].pop("name")
        visual(spec, "trend")["yScal"] = {}
        bad = self.make_app(spec, FULL_FILES, slug="BadApp")
        code, out, err = run_main(["validate", "BadApp", "--tools-dir", str(self.tools)])    # slug lookup
        self.assertEqual(code, 1)
        self.assertIn("  E1. app.name: missing required field 'name'", out)
        self.assertIn("  W1. ", out)
        self.assertIn("Result: ", out)
        code, out, err = run_main(["validate", str(bad / "spec.json"), "--json", "--tools-dir", str(self.tools)])
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["errors"][0]["n"], 1)
        self.assertEqual(data["errors"][0]["path"], "app.name")

    def test_usage_errors_exit_2(self):
        self.assertEqual(run_main([])[0], 2)
        self.assertEqual(run_main(["frobnicate"])[0], 2)
        self.assertEqual(run_main(["validate"])[0], 2)
        self.assertEqual(run_main(["validate", str(self.tmp / "nowhere")])[0], 2)
        self.assertEqual(run_main(["build", "NoSuchApp"])[0], 2)
        self.assertEqual(run_main(["verify", "NoSuchApp"])[0], 2)

    def test_new_scaffolds_a_valid_app(self):
        code, out, err = run_main(["new", "PumpStationMonitor"])
        self.assertEqual(code, 0, err)
        app = self.ws / "apps" / "PumpStationMonitor"
        for sub in ("data", "html", "scripts", "datafunctions", "build"):
            self.assertTrue((app / sub).is_dir(), sub)
        spec = json.loads((app / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["app"]["name"], "Pump Station Monitor")
        self.assertEqual(run_main(["validate", "PumpStationMonitor", "--tools-dir", str(self.tools)])[0], 0)
        code, out, err = run_main(["build", "PumpStationMonitor", "--no-lint", "--tools-dir", str(self.tools)])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(run_main(["new", "PumpStationMonitor"])[0], 2)          # never overwrites
        self.assertEqual(run_main(["new", "Bad Slug"])[0], 2)
        code, out, err = run_main(["new", "StationOps", "--name", "Station Operations"])
        self.assertEqual(code, 0, err)
        spec = json.loads((self.ws / "apps" / "StationOps" / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["app"]["name"], "Station Operations")


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------
class HelperTests(unittest.TestCase):
    def test_script_assigns(self):
        code = ("import pandas as pd\n"
                "def run():\n"
                "    global OutR2\n"
                "    OutR2 = 1.0\n"
                "A, PUMP_CURVES = f()\n"
                "Typed: float = 2.0\n"
                "check = Missing == 3\n"
                "Augmented += 1\n")
        self.assertTrue(dxpgen.script_assigns(code, "OutR2"))
        self.assertTrue(dxpgen.script_assigns(code, "PUMP_CURVES"))
        self.assertTrue(dxpgen.script_assigns(code, "Typed"))
        self.assertFalse(dxpgen.script_assigns(code, "Missing"))
        self.assertFalse(dxpgen.script_assigns(code, "Augmented"))
        self.assertTrue(dxpgen.script_assigns("events <- data.frame()\n", "events", "terr"))
        self.assertTrue(dxpgen.script_assigns("data.frame() -> events\n", "events", "terr"))

    def test_df_build_order_puts_producers_first(self):
        consumer = {"name": "B", "inputs": [{"type": "table", "bind": {"table": "T"}}], "outputs": []}
        producer = {"name": "A", "inputs": [], "outputs": [{"type": "table", "target": {"table": "T"}}]}
        self.assertEqual(dxpgen.df_build_order([consumer, producer]), ([1, 0], []))
        loop1 = {"inputs": [{"bind": {"table": "U"}}], "outputs": [{"type": "table", "target": {"table": "T"}}]}
        loop2 = {"inputs": [{"bind": {"table": "T"}}], "outputs": [{"type": "table", "target": {"table": "U"}}]}
        self.assertEqual(dxpgen.df_build_order([loop1, loop2]), ([0, 1], [0, 1]))

    def test_sanitizer_emulation(self):
        clean = ('<div id="style-container"></div><div class="kpi" style="display: flex; gap: 8px; '
                 'color: rgba(0, 0, 0, 0.5)"><span><SpotfireControl id="0123456789abcdef0123456789abcdef" />'
                 '</span><a href="https://example.com" target="_blank">x</a></div>')
        self.assertEqual(dxpgen.emulate_sanitizer(clean), [])
        dirty = ('<style>.a{}</style><button>Run</button><div data-x="1" onclick="f()">a</div>'
                 '<p style="color: var(--c)">b</p><a style="color: red" href="javascript:x()">c</a>R<sup>2</sup>')
        messages = " | ".join(m for level, m, n in dxpgen.emulate_sanitizer(dirty) if level == "error")
        for expected in ("<style> is removed", "<button> is removed", "attribute 'data-x'", "attribute 'onclick'",
                         "var(", "<a> takes no style", "javascript:", "<sup> is removed"):
            self.assertIn(expected, messages)

    def test_compose_textarea_html_maps_tokens(self):
        html, tokens = dxpgen.compose_textarea_html("<p>{{control:a}} {{ control : b }}</p>", "p{}", True, "panel 1")
        # same container as lib/80_textareas.py: id style-container plus the text area's own class
        self.assertTrue(html.startswith('<div id="style-container" class="sfdxb-style-panel_1"></div>'
                                        '<p><SpotfireControl id="'))
        self.assertEqual(sorted(tokens.values()), ["a", "b"])
        self.assertTrue(all(len(t) == 32 for t in tokens))
        own, _ = dxpgen.compose_textarea_html('<div id="style-container"></div><p>x</p>', "p{}", True, "t")
        self.assertEqual(own.count("style-container"), 1)
        self.assertEqual(dxpgen.emulate_sanitizer(html), [])

    def test_naming_helpers(self):
        self.assertEqual(dxpgen.naming_issues("property", "SelectedPumpId", "program"), [])
        self.assertEqual(dxpgen.naming_issues("page", "Pump Detail (psig)", "program"), [])
        self.assertEqual(dxpgen.naming_issues("page", "3D Scatter of Flow vs Head", "program"), [])
        self.assertEqual(dxpgen.naming_issues("page", "10 Year Forecast", "program"), [])
        self.assertEqual(dxpgen.naming_issues("page", "Production (2023)", "program"), [])
        for numbered in ("1. Overview", "1A. Discover", "2) Detail", "3 - Events", "01 Overview"):
            self.assertTrue(dxpgen.naming_issues("page", numbered, "program"), numbered)
        self.assertEqual(dxpgen.naming_issues("column", "Flow Rate (bbl/d)", "program"), [])
        self.assertEqual(dxpgen.naming_issues("table", "PUMP_DATA", "program"), [])
        self.assertTrue(dxpgen.naming_issues("table", "PUMP_DATA", "camelCase"))
        self.assertEqual(dxpgen.suggest_pascal("selected_pump_id"), "SelectedPumpId")
        self.assertEqual(dxpgen.suggest_upper_snake("pumpData"), "PUMP_DATA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
