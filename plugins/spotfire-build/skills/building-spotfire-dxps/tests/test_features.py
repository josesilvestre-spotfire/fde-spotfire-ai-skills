"""Tests for the standard engine's feature parts (engine/features, scripts/t3/_sections.py): document
properties, several markings, Python data functions and dataFunction tables, IronPython scripts,
text-area control markers (the controls are manual steps), per-visual marking / limitByMarkings, limit
expressions on tables and KPI charts, log y scale, horizontal sorted bars, the visual settings escape
hatch.

Run: python -m unittest tests/test_features.py   (or python -m unittest discover -s tests)

The fixture app (temporary folder) uses every feature. FeatureBuildTests builds it with the real
tools (scripts/lint_ipy.py, scripts/ipy_parse.ps1 when Windows PowerShell and Spotfire Analyst 15.0 are
installed, scripts/sfapi.py when an API index is available); the other tests run the generator only.
Nothing starts Spotfire.
"""
import ast
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
import dxpgen  # noqa: E402
import slim_builder  # noqa: E402
import t3  # noqa: E402
from t3 import _assemble, _literal, _sections  # noqa: E402
from t3._common import Context  # noqa: E402

DF_MAKE = '''import numpy as np
import pandas as pd
n = int(Days) * 24
DATA = pd.DataFrame({"Timestamp": pd.date_range("2026-01-01", periods=n, freq="h"),
                     "Group": np.where(np.arange(n) % 2 == 0, "A", "B").astype(object),
                     "Value": np.linspace(1.0, float(Alpha) * 100.0, n),
                     "Is Flagged": np.arange(n) % 7 == 0})
EVENTS = pd.DataFrame({"Event": np.array(["start"], dtype=object), "Hours": [float(n)]})
Note = "made %d rows" % n
'''
DF_SCORE = '''import pandas as pd
SCORES = DATA.copy()
SCORES["Score"] = SCORES["Value"] * float(Weight)
Count = int(len(SCORES))
'''
SCRIPT = 'Document.Properties["Note"] = "clicked " + Kind\n'
CONTROL_IDS = ("note", "input", "multi", "group", "list", "trains", "alpha", "days", "mode", "flag", "run",
               "toDetail", "refresh")
HTML = "<div>" + "".join("<p>{{control:%s}}</p>" % c for c in CONTROL_IDS) + "</div>"


def fixture_spec():
    return {
        "specVersion": 1,
        "app": {"name": "Feature Kitchen", "description": "Every standard-engine feature.",
                "theme": {"base": "DarkSfx"}},
        "tables": [
            {"name": "DATA", "source": {"type": "dataFunction", "function": "Make Data", "output": "DATA"},
             "columns": {"Timestamp": {}, "Group": {}, "Value": {"format": "#,##0.00"}, "Is Flagged": {}}},
            {"name": "SCORES", "source": {"type": "dataFunction", "function": "Score Data",
                                          "output": "SCORES"},
             "columns": {"Timestamp": {}, "Group": {}, "Value": {}, "Is Flagged": {},
                         "Score": {"format": "0.000"}}},
        ],
        "defaultTable": "DATA",
        "markings": [{"name": "Marking", "color": "#60A5FA", "default": True},
                     {"name": "Window", "color": "#A78BFA"}],
        "properties": [
            {"name": "Trains", "type": "String", "default": ["A"], "listValued": True},
            {"name": "Days", "type": "Integer", "default": 2},
            {"name": "Alpha", "type": "Real", "default": 0.995, "description": "Confidence"},
            {"name": "Window", "type": "LongInteger", "default": 24},
            {"name": "Flag", "type": "Boolean", "default": True},
            {"name": "Start", "type": "DateTime", "default": "2026-01-01T00:00:00"},
            {"name": "Mode", "type": "String", "default": "quantile"},
            {"name": "Note", "type": "String", "default": ""},
            {"name": "Count", "type": "LongInteger", "default": 0},
        ],
        "dataFunctions": [
            {"name": "Make Data", "script": "datafunctions/make_data.py", "refresh": "manual",
             "inputs": [{"name": "Days", "type": "value", "dataTypes": ["Integer"], "bind": {"property": "Days"}},
                        {"name": "Alpha", "type": "value", "dataTypes": ["Real"], "bind": {"property": "Alpha"}}],
             "outputs": [{"name": "DATA", "type": "table", "target": {"table": "DATA"}},
                         {"name": "EVENTS", "type": "table", "target": {"table": "EVENTS"}},
                         {"name": "Note", "type": "value", "target": {"property": "Note"}}]},
            {"name": "Score Data", "script": "datafunctions/score_data.py",
             "inputs": [{"name": "DATA", "type": "table", "bind": {"table": "DATA", "columns": "*"}},
                        {"name": "Weight", "type": "value", "dataTypes": ["Real"], "bind": {"value": 0.5}}],
             "outputs": [{"name": "SCORES", "type": "table", "target": {"table": "SCORES"}},
                         {"name": "Count", "type": "value", "target": {"property": "Count"}}]},
        ],
        "scripts": [{"name": "Add Window", "file": "scripts/add_window.py", "description": "Adds a window.",
                     "parameters": [{"name": "Kind", "type": "String"}]}],
        "pages": [
            {"title": "Main", "visuals": [
                {"id": "controls", "type": "textArea", "title": "Controls", "showTitle": False,
                 "html": "html/controls.html",
                 "controls": {
                     "note": {"kind": "label", "property": "Note"},
                     "input": {"kind": "input", "property": "Start"},
                     "multi": {"kind": "multilineInput", "property": "Mode"},
                     "group": {"kind": "dropdown", "property": "Mode",
                               "values": {"column": {"table": "DATA", "column": "Group"}}},
                     "list": {"kind": "listbox", "property": "Window",
                              "values": {"fixed": [{"text": "Day", "value": 24}, {"text": "Week", "value": 168}]}},
                     "trains": {"kind": "multiSelectListbox", "property": "Trains",
                                "values": {"fixed": [{"text": "Train A", "value": "A"}, {"value": "B"}]}},
                     "alpha": {"kind": "slider", "property": "Alpha", "min": 0.95, "max": 0.9995, "step": 0.0005},
                     "days": {"kind": "slider", "property": "Days", "min": 1, "max": 30},
                     "mode": {"kind": "radio", "property": "Mode",
                              "values": {"fixed": [{"text": "Chi-square", "value": "chi2"},
                                                   {"text": "Quantile", "value": "quantile"}]}},
                     "flag": {"kind": "checkbox", "property": "Flag"},
                     "run": {"kind": "button", "label": "Mark Anomaly", "script": "Add Window",
                             "args": {"Kind": "Anomaly"}},
                     "toDetail": {"kind": "link", "label": "Detail", "action": {"gotoPage": "Detail"}},
                     "refresh": {"kind": "button", "label": "Run Simulator",
                                 "action": {"refreshDataFunction": "Make Data"}}}},
                {"id": "trend", "type": "lineChart", "title": "${Mode} trend", "table": "SCORES",
                 "x": "[Timestamp]", "y": "Avg($esc(${Mode}))", "colorBy": "Group", "marking": "Window",
                 "limitExpression": "[Group] = \"${Mode}\"", "yScale": {"log": True},
                 "coloring": {"categorical": {"A": "#2DD4BF", "B": "#EF4444"}},
                 "settings": {"BreakOnEmpty": True, "YAxis.Scale.LabelOrientation": "Horizontal"},
                 "referenceLayers": [{"kind": "verticalLine", "value": "DocumentProperty(\"Start\")",
                                      "label": "Start", "dash": "dash", "color": "#A78BFA"},
                                     {"kind": "horizontalLine", "value": "${Alpha}", "label": "Alpha"}]},
                {"id": "byGroup", "type": "barChart", "title": "By group", "table": "SCORES",
                 "x": "Group", "y": "Sum([Score])", "orientation": "horizontal", "sort": "descending",
                 "coloring": {"fixed": "#A78BFA"}},
                {"id": "rows", "type": "table", "title": "Rows", "table": "DATA",
                 "columns": ["Timestamp", "Group", "Value", "Is Flagged"],
                 "limitExpression": "[Is Flagged]", "marking": None},
                {"id": "marked", "type": "table", "title": "Marked", "table": "SCORES",
                 "columns": ["Timestamp", "Score"], "limitByMarkings": ["Marking", "Window"],
                 "emptyMarkingBehavior": "ShowEmpty"},
                {"id": "kpis", "type": "kpiChart", "title": "KPIs", "table": "SCORES",
                 "limitExpression": "[Group] = \"A\"",
                 "kpis": [{"title": "Rows", "value": "Count()"},
                          {"title": "Score", "value": "Sum([Score])", "format": "0.000"}]},
            ], "layout": {"row": [{"visual": "controls", "weight": 22},
                                  {"column": [{"visual": "trend"},
                                              {"row": [{"visual": "byGroup"}, {"visual": "kpis"}]},
                                              {"row": [{"visual": "rows"}, {"visual": "marked"}]}],
                                   "weight": 78}]}},
            {"title": "Detail", "visuals": [
                {"id": "events", "type": "table", "title": "Events", "table": "EVENTS",
                 "columns": ["Event", "Hours"]}]},
        ],
        "activePage": "Main",
    }


FILES = {"datafunctions/make_data.py": DF_MAKE, "datafunctions/score_data.py": DF_SCORE,
         "scripts/add_window.py": SCRIPT, "html/controls.html": HTML}


def literals(text):
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("HOME", "STYLE", "APP"):
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


class FeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="features-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, spec=None, slug="FeatureKitchen"):
        app = self.tmp / "apps" / slug
        for rel, text in FILES.items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (app / "spec.json").write_text(json.dumps(spec or fixture_spec(), indent=2), encoding="utf-8")
        return app

    def generate(self, spec, app, tier="standard"):
        resolved = dxpgen.resolve_spec(spec, app)
        return t3.generate(resolved, spec, app, tier, dxpgen.column_reader(resolved),
                           {"spec_sha": "0" * 64, "generated": "2026-10-02T00:00:00"})


class FeatureBuildTests(FeatureTestCase):
    """dxpgen build with the real tools: every check the build runs must pass."""

    def test_engine_tiers_build_and_pass_every_check(self):
        app = self.app()
        options = dxpgen.Options(lint=True, sanitize=False, tools_dir=SKILL / "scripts")
        for tier in ("standard", "quick", "compact"):
            out = io.StringIO()
            with contextlib.redirect_stderr(io.StringIO()):
                code = dxpgen.build_app(app, app / "spec.json", options, out=out, tier=tier)
            text_out = out.getvalue()
            self.assertEqual(code, 0, text_out)
            path = app / "build" / ("build_FeatureKitchen_%s.py" % tier)
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            self.assertEqual(slim_builder.text_problems(text), [], tier)        # <= 79, ASCII, no tabs
            self.assertEqual(slim_builder.undefined_names(text), {}, tier)
            self.assertIn("lint 0 error(s)", text_out)
            checks = text_out.partition("Checks of the generated builder:")[2].split("To build the analysis")[0]
            self.assertNotIn("Errors (", checks)                               # notes only (tool not run)
            self.assertNotIn("Warnings (", checks)
            if dxpgen.find_index_file() is not None:
                self.assertRegex(text_out, r"sfapi\.py has: \d+ members, \d+ setters OK")
            if "IronPython parse not run" not in text_out:
                self.assertIn("PARSE OK", text_out)
            self.assertLess(len(text), 70000, tier)


class FeatureConversionTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.spec = fixture_spec()
        self.result = self.generate(self.spec, self.app(self.spec))
        self.assertEqual(self.result.problems, [])
        self.visuals = dict((v["id"], v) for p in self.result.app["pages"] for v in p["visuals"])

    def test_sections(self):
        app = self.result.app
        self.assertEqual(app["marking"], ["Marking", "#60A5FA"])
        self.assertEqual(app["markings"], [["Window", "#A78BFA"]])
        self.assertEqual(app["tables"], [])
        self.assertEqual(app["properties"][0], ["Trains", "String", ["A"], True])
        self.assertEqual(app["properties"][2], ["Alpha", "Real", 0.995, False, "Confidence"])
        self.assertEqual(app["properties"][5], ["Start", "DateTime", "2026-01-01T00:00:00"])
        make, score = app["dataFunctions"]
        self.assertEqual(make, {"name": "Make Data", "file": "make_data.py",
                                "in": [["Days", "value", {"property": "Days"}, ["Integer"]],
                                       ["Alpha", "value", {"property": "Alpha"}, ["Real"]]],
                                "out": [["DATA", "table", "DATA"], ["EVENTS", "table", "EVENTS"],
                                        ["Note", "value", "Note"]],
                                "refresh": "manual"})
        # DATA comes from an earlier function that runs at build: the engine lists its own columns
        self.assertEqual(score["in"], [["DATA", "table", {"table": "DATA"}],
                                       ["Weight", "value", {"expression": "0.5"}, ["Real"]]])
        self.assertNotIn("refresh", score)
        self.assertEqual(app["dfTables"], [["DATA", {"#,##0.00": ["Value"]}], ["SCORES", {"0.000": ["Score"]}]])
        self.assertEqual(app["scripts"], [{"name": "Add Window", "file": "add_window.py",
                                           "description": "Adds a window.", "params": [["Kind", "String"]]}])
        self.assertEqual(self.result.features, {"properties", "markings", "dataFunctions", "scripts",
                                                "controls", "manual", "links", "log", "barLayout",
                                                "settings", "guard", "preflight"})  # every featured app
        self.assertEqual([p.name for p in self.result.parts][:9],
                         ["core", "guard", "preflight", "properties", "markings", "datafunctions",
                          "scripts", "controls", "links"])

    def test_controls(self):
        """Each control becomes a marker text in APP and a manual step (no public API adds one)."""
        c = self.visuals["controls"]["controls"]
        self.assertEqual(c["note"], "Label: Note")
        self.assertEqual(c["input"], "Input field: Start")
        self.assertEqual(c["multi"], "Input field (multiple lines): Mode")
        self.assertEqual(c["group"], "Drop-down list: Mode")
        self.assertEqual(c["list"], "List box: Window")
        self.assertEqual(c["mode"], "List box: Mode")                           # radio substitute
        self.assertEqual(c["flag"], "Drop-down list: Flag")                     # checkbox substitute
        self.assertEqual(c["run"], "Button: Mark Anomaly")
        self.assertEqual(c["toDetail"], "Link: Detail")
        self.assertEqual(c["refresh"], "Button: Run Simulator")
        how = dict(self.result.manual)
        self.assertIn("with values from column DATA.Group", how["control controls/group"])
        self.assertIn("with fixed values Day = 24, Week = 168", how["control controls/list"])
        self.assertIn("(range 0.95 to 0.9995, step 0.0005)", how["control controls/alpha"])
        self.assertIn("Yes = True, No = False", how["control controls/flag"])
        self.assertIn("runs the IronPython script 'Add Window' with arguments Kind = Anomaly",
                      how["control controls/run"])
        self.assertIn("goes to page 'Detail'", how["control controls/toDetail"])
        self.assertIn("refreshes data function 'Make Data'", how["control controls/refresh"])
        self.assertIn("delete the marker [Drop-down list: Mode]", how["control controls/group"])

    def test_visual_additions(self):
        trend = self.visuals["trend"]
        self.assertEqual(trend["title"], "${Mode} trend")                      # live references untouched
        self.assertEqual(trend["y"], "Avg($esc(${Mode}))")
        self.assertEqual(trend["where"], "[Group] = \"${Mode}\"")
        self.assertEqual(trend["colorBy"], "<[Group]>")                        # data-function table column
        self.assertTrue(trend["yLog"])
        self.assertEqual(trend["marking"], "Window")
        self.assertEqual(trend["refs"][0]["value"], "DocumentProperty(\"Start\")")
        self.assertEqual(trend["refs"][1]["value"], "${Alpha}")
        bar = self.visuals["byGroup"]
        self.assertEqual((bar["x"], bar["horizontal"], bar["sort"]), ("<[Group]>", True, "descending"))
        self.assertNotIn("marking", bar)                                       # default marking
        rows = self.visuals["rows"]
        self.assertEqual((rows["where"], rows["marking"]), ("[Is Flagged]", None))
        self.assertEqual(rows["columns"], ["Timestamp", "Group", "Value", "Is Flagged"])
        marked = self.visuals["marked"]
        self.assertEqual((marked["limits"], marked["empty"]), (["Marking", "Window"], "ShowEmpty"))
        self.assertEqual(self.visuals["kpis"]["where"], "[Group] = \"A\"")
        # a KPI chart gets the default marking explicitly in a featured app (AddNew leaves it unmarked)
        self.assertEqual(self.visuals["kpis"]["marking"], "Marking")

    def test_build_order_in_the_builder(self):
        text = self.result.text
        build = text[text.index("# " + "=" * 64 + " build"):]
        order = ["rename starter table", "property \" + p[0]", "load \" + entry[0]", "ok(\"marking\", marking)",
                 "marking \" + entry[0]", "data function \" + d[\"name\"]", "in APP[\"dfTables\"]",
                 "script \" + s[\"name\"]", "build_page", "for entry in APP[\"manual\"]:", "finish()"]
        found = [build.find(o) for o in order]
        self.assertTrue(all(f >= 0 for f in found), list(zip(order, found)))
        self.assertEqual(found, sorted(found))
        self.assertIn("APP = {\n    \"name\": \"Feature Kitchen\",", text)    # dense APP layout

    def test_engine_bind_expressions(self):
        """bind_expr of engine/features/datafunctions.py, run in CPython with stand-ins for Spotfire's
        ExpressionUtilities and a table registry."""
        part = _assemble.Part("datafunctions", t3.ENGINE_DIR / "features" / "datafunctions.py",
                              (t3.ENGINE_DIR / "features" / "datafunctions.py").read_text(encoding="utf-8"),
                              "standard", set())
        tree = ast.parse("\n".join(part.code))
        wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("ident", "lit", "bind_expr")]

        class Utilities(object):
            @staticmethod
            def EscapeIdentifier(name):
                return "[" + name.replace("]", "]]") + "]"

            @staticmethod
            def EscapeStringLiteral(text):
                return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        class Column(object):
            def __init__(self, name):
                self.Name = name

        class Table(object):
            Columns = [Column("A"), Column("B c")]

        scope = {"ExpressionUtilities": Utilities, "T": {"LIVE": Table()}}
        exec(compile(ast.Module(body=wanted, type_ignores=[]), "datafunctions", "exec"), scope)
        bind = scope["bind_expr"]
        self.assertEqual(bind({"property": "Days"}), 'DocumentProperty("Days")')
        self.assertEqual(bind({"expression": "Max([T].[A])"}), "Max([T].[A])")
        self.assertEqual(bind({"value": "x\"y"}), '"x\\"y"')
        self.assertEqual(bind({"table": "T", "column": "Flow (bbl/d)"}), "[T].[Flow (bbl/d)]")
        self.assertEqual(bind({"table": "T", "columns": ["A", "B"]}), "[T].[A], [T].[B]")
        self.assertEqual(bind({"table": "LIVE"}), "[LIVE].[A], [LIVE].[B c]")   # the table's own columns
        self.assertEqual(bind({"table": "LATER"}),                                 # Spotfire's own template
                         '$map("[LATER].$esc($csearch([LATER],"*"))",",")')


class SettingsTests(FeatureTestCase):
    """The visual settings escape hatch (engine/features/settings.py): APP key, gating, the engine's
    path walk and value conversion (run in CPython with stand-ins for the .NET types)."""

    def test_app_key_part_and_build_step(self):
        spec = fixture_spec()
        result = self.generate(spec, self.app(spec))
        self.assertEqual(result.problems, [])
        trend = [v for v in result.app["pages"][0]["visuals"] if v["id"] == "trend"][0]
        self.assertEqual(trend["settings"], {"BreakOnEmpty": True, "YAxis.Scale.LabelOrientation": "Horizontal"})
        self.assertIn("settings", result.features)
        self.assertEqual([p.name for p in result.parts].count("settings"), 1)
        self.assertIn("def visual_settings(v, vs):", result.text)
        self.assertIn('ok(vid + ": settings", visual_settings, v, vs)', result.text)
        report = self.generate(spec, self.app(spec), "report")
        self.assertIn('if key == "set_setting":', report.text)                 # its manual fix

    def test_absent_without_settings(self):
        spec = fixture_spec()
        del spec["pages"][0]["visuals"][1]["settings"]
        for tier in ("standard", "report"):
            result = self.generate(spec, self.app(spec), tier)
            self.assertEqual(result.problems, [])
            self.assertNotIn("settings", result.features)
            self.assertNotIn("settings", [p.name for p in result.parts])
            self.assertNotIn("visual_settings", result.text)
            self.assertNotIn("set_setting", result.text)

    def test_engine_walk_and_conversion(self):
        path = t3.ENGINE_DIR / "features" / "settings.py"
        part = _assemble.Part("settings", path, path.read_text(encoding="utf-8"), "standard", {"settings"})

        class NetType(object):
            def __init__(self, name, enum=(), statics=None):
                self.FullName = name
                self.IsEnum = bool(enum)
                self.members = enum
                self.statics = statics or {}

            def GetProperty(self, name, flags):
                if name in self.statics:
                    value = self.statics[name]
                    return type("Member", (), {"GetValue": lambda s, a, b: value})()
                return None

            def GetField(self, name, flags):
                return None

        class Enum(object):
            @staticmethod
            def Parse(t, text):
                for item in [x.strip() for x in text.split(",")]:
                    if item not in t.members:
                        raise ValueError("%s is not a member of %s" % (item, t.FullName))
                return t.FullName + "." + text

        class Color(object):
            @staticmethod
            def FromArgb(a, r, g, b):
                return ("argb", a, r, g, b)

        class Node(object):
            """A content object: attributes plus their declared property types."""

            def __init__(self, name, **props):
                self.name = name
                self.types = {}
                for key, (t, value) in props.items():
                    self.types[key] = t
                    setattr(self, key, value)

            def GetType(self):
                node = self

                class Info(object):
                    FullName = node.name

                    def GetProperty(self, prop, flags):
                        t = node.types.get(prop)
                        return type("Prop", (), {"PropertyType": t})() if t is not None else None
                return Info()

        boolean, int32, real, text = (NetType("System.Boolean"), NetType("System.Int32"),
                                      NetType("System.Double"), NetType("System.String"))
        color = NetType("System.Drawing.Color")
        orient = NetType("LabelOrientation", enum=("Horizontal", "Vertical"))
        pseudo = NetType("DataType", statics={"Real": "DataType.Real"})
        clr_types = {bool: boolean, int: int32, float: real, str: text, Color: color,
                     "Int64": NetType("System.Int64"), "Single": NetType("System.Single")}
        clr = type("clr", (), {"GetClrType": staticmethod(lambda t: clr_types[t])})
        failed = []

        def ok(name, fn, *args):
            try:
                return fn(*args)
            except Exception:
                failed.append(name)
                return None

        scale = Node("Scale", LabelOrientation=(orient, "Vertical"), ShowGridlines=(boolean, False))
        axis = type("Axis", (), {"Scale": scale})()
        content = Node("LineChart", BreakOnEmpty=(boolean, False), LineWidth=(int32, 1), Title=(text, ""),
                       Back=(color, None), Fore=(color, None), Kind=(pseudo, None), Ratio=(real, 0.0),
                       YAxis=(NetType("ScaleAxis"), axis))
        content_type = object()
        visual = type("Visual", (), {"As": {content_type: lambda: content}})()
        flags = type("BindingFlags", (), {"Instance": 1, "Public": 2, "Static": 4})
        scope = {"clr": clr, "Boolean": bool, "Int32": int, "Int64": "Int64", "Double": float,
                 "Single": "Single", "String": str, "Enum": Enum, "Color": Color, "BindingFlags": flags,
                 "VisualContent": content_type, "ok": ok, "rgb": lambda h: ("rgb", h)}
        exec(compile("\n".join(part.code), "settings", "exec"), scope)
        scope["visual_settings"](visual, {"id": "trend", "settings": {
            "BreakOnEmpty": True, "LineWidth": 3, "Title": 12, "Ratio": 2, "Back": "#80112233",
            "Fore": "#112233", "Kind": "Real", "YAxis.Scale.LabelOrientation": "Horizontal",
            "YAxis.Scale.ShowGridlines": True, "YAxis.Nope.Visible": True, "NoSuch": 1,
            "YAxis.Scale.ShowGridlines.Deeper": 1}})
        self.assertEqual(sorted(failed), ["trend: setting NoSuch", "trend: setting YAxis.Nope.Visible",
                                          "trend: setting YAxis.Scale.ShowGridlines.Deeper"])
        self.assertIs(content.BreakOnEmpty, True)
        self.assertEqual((content.LineWidth, content.Title, content.Ratio), (3, "12", 2.0))
        self.assertEqual(content.Back, ("argb", 0x80, 0x11, 0x22, 0x33))          # '#AARRGGBB'
        self.assertEqual(content.Fore, ("rgb", "#112233"))                         # '#RRGGBB' via rgb()
        self.assertEqual(content.Kind, "DataType.Real")                            # pseudo-enum member
        self.assertEqual(scale.LabelOrientation, "LabelOrientation.Horizontal")
        self.assertIs(scale.ShowGridlines, True)                                   # bad paths blocked nothing


class HiddenPageTests(FeatureTestCase):
    """Page "visible": false (feature hiddenPages): public Page.Visible, set after the
    active page so every page is built while shown; a link control may still go to the hidden page."""

    def test_hidden_page_is_built(self):
        spec = fixture_spec()
        spec["pages"][1]["visible"] = False                    # Detail, the target of toDetail
        for tier in ("standard", "report"):
            result = self.generate(spec, self.app(spec), tier)
            self.assertEqual(result.problems, [])
            self.assertIs(result.app["pages"][1]["visible"], False)
            self.assertNotIn("visible", result.app["pages"][0])
            self.assertIn("hiddenPages", result.features)
            self.assertIn("def hide_page(page):", result.text)
            build = result.text[result.text.index("# " + "=" * 64 + " build"):]
            self.assertLess(build.index('ok("active page", set_active)'),
                            build.index("hide_page, PAGES[ps[\"title\"]]"))
            api, setters = result.members()
            self.assertIn("Page.Visible", api)
            self.assertIn("Page.Visible", setters)
        self.assertIn('if key == "hide_page":', result.text)                  # report: its manual fix

    def test_absent_without_hidden_pages(self):
        spec = fixture_spec()
        for tier in ("standard", "report"):
            result = self.generate(spec, self.app(spec), tier)
            self.assertNotIn("hiddenPages", result.features)
            self.assertNotIn("hide_page", result.text)
            self.assertNotIn("Page.Visible", result.members()[0])


class SectionUnitTests(FeatureTestCase):
    def ctx(self, spec):
        app = self.app(spec) if spec.get("dataFunctions") else self.tmp
        resolved = dxpgen.resolve_spec(spec, app)
        return resolved, Context(resolved, spec, app, "standard", {"palette": {}, "visual": {}})

    def test_literals(self):
        resolved, ctx = self.ctx({"app": {"name": "x"}})
        lit = lambda v, t=None: _sections.literal(v, t or [], "p", ctx)      # noqa: E731
        self.assertEqual(lit("text"), {"value": "text"})
        self.assertEqual(lit(True), {"expression": "True"})
        self.assertEqual(lit(20), {"expression": "20"})
        self.assertEqual(lit(1e-05), {"expression": "0.00001"})
        self.assertEqual(lit(3, ["Real"]), {"expression": "3.0"})
        self.assertEqual(lit("2026-01-31T08:30:00", ["DateTime"]),
                         {"expression": "DateTime(2026, 1, 31, 8, 30, 0, 0)"})
        self.assertEqual(lit("2026-01-31", ["Date"]), {"expression": "Date(2026, 1, 31)"})
        self.assertEqual(lit("7.00:00:00", ["TimeSpan"]), {"expression": "TimeSpan(7, 0, 0, 0, 0)"})
        self.assertEqual(ctx.problems, [])
        lit(2.5, ["Integer"])
        self.assertEqual(len(ctx.problems), 1)

    def test_declared_columns_when_the_table_is_not_produced_earlier(self):
        spec = fixture_spec()
        spec["dataFunctions"][0]["executeAtBuild"] = False
        resolved, ctx = self.ctx(spec)
        make, score = _sections.data_functions(resolved, spec, self.tmp, ctx)
        self.assertFalse(make["run"])
        self.assertEqual(score["in"][0][2], {"table": "DATA",
                                             "columns": ["Timestamp", "Group", "Value", "Is Flagged"]})

    def test_still_unsupported(self):
        """(table inputs limited by a marking are built: tests/test_kitchen_features.py; controls of any
        kind are manual steps, never unsupported)"""
        spec = fixture_spec()
        spec["dataFunctions"][0]["engine"] = "terr"
        spec["dataFunctions"][1]["inputs"][0]["bind"]["limitByFiltering"] = True
        page = spec["pages"][0]["visuals"]
        page[0]["controls"]["toDetail"]["action"] = {"applyBookmark": "Morning"}
        page[0]["css"] = "p { color: red; }"
        spec["tables"][0]["settings"] = {"Name": "x"}                          # settings: visuals only
        spec["tables"][0]["columns"]["Value"]["settings"] = {"Name": "y"}
        page[1]["referenceLayers"][1]["settings"] = {"Name": "z"}
        result = self.generate(spec, self.app(spec))
        paths = [p for p, _ in result.problems]
        for want in ("dataFunctions[0].engine", "dataFunctions[1].inputs[0].bind.limitByFiltering",
                     "pages[0].visuals[0].css",
                     "tables[0].settings", "tables[0].columns.Value.settings",
                     "pages[0].visuals[1].referenceLayers[1].settings"):
            self.assertIn(want, paths)
        self.assertTrue(all("use --tier slim" in m for _, m in result.problems))


class AssemblyTests(unittest.TestCase):
    def test_feature_blocks(self):
        lines = ["a", "# @feature x", "b", "# @endfeature", "    # @feature !x", "    c", "    # @endfeature",
                 "# @tier quick", "# @feature y", "d", "# @endfeature", "# @end"]
        self.assertEqual(_assemble.strip_features(lines, {"x"}),
                         ["a", "b", "# @tier quick", "# @end"])
        self.assertEqual(_assemble.strip_features(lines, set()),
                         ["a", "    c", "# @tier quick", "# @end"])
        self.assertEqual(_assemble.strip_features(lines, None)[:2], ["a", "b"])
        for bad in (["# @feature x", "# @feature y", "# @endfeature", "# @endfeature"], ["# @endfeature"],
                    ["# @feature x"]):
            with self.assertRaises(ValueError):
                _assemble.strip_features(bad, set())

    def test_dense_literal(self):
        value = {"name": "x", "description": "word " * 60, "pages": [{"a": ["v" * 70, -1, 2.5, None]}, {"b": {}}],
                 "deep": [[["k" * 75]]], "odd": "café \"q\" \\"}
        text = _literal.dense("APP", value)
        self.assertTrue(text.isascii())
        self.assertLessEqual(max(len(line) for line in text.split("\n")), 79)
        self.assertEqual(ast.literal_eval(text[len("APP = "):]), value)
        self.assertLess(len(text), len(_literal.literal("APP", value)) + 40)

    def test_docstrings_dropped_only_in_dense_builders(self):
        lines = ["def f():", '    """doc', '    more"""', "    return 1", "def g():", '    """only"""']
        self.assertEqual(_assemble.drop_docstrings(lines), ["def f():", "    return 1", "def g():",
                                                            '    """only"""'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
