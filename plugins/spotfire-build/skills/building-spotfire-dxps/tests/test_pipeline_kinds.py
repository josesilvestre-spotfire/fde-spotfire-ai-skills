"""Tests for the standard engine's scatter and map kinds (engine/builders/scatter.py, map.py,
_markers.py; scripts/t3/scatter.py, map.py), full colorings on chart color axes, map layers, table and
cross-table cells and KPI tiles (feature coloring: engine/features/coloring.py, scripts/t3/_coloring.py),
x / y axis ranges (feature range) and lines and curves on line, bar and scatter charts (feature fitting).

Run: python -m unittest tests/test_pipeline_kinds.py   (or python -m unittest discover -s tests)

The fixture app (temporary folder) is the kitchen of test_kitchen_features plus a page with a scatter
plot, a map with tile, feature and marker layers, a cross table and a table with cell colorings, a KPI
chart with tile colorings and a line chart with a gradient. PipelineBuildTests builds it with the real
tools (scripts/lint_ipy.py, scripts/ipy_parse.ps1 when Windows PowerShell and Spotfire Analyst 15.0 are
installed, scripts/sfapi.py when an API index is available); the other tests run the generator, the
validator or engine functions in CPython with stand-ins. Nothing starts Spotfire.
"""
import ast
import contextlib
import copy
import hashlib
import io
import json
import math
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
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import slim_builder  # noqa: E402
import t3  # noqa: E402
from t3 import _assemble, _coloring  # noqa: E402
import test_features  # noqa: E402
import test_kitchen_features as tw  # noqa: E402
from test_columns import sbdf_header, STRING, LONG, REAL  # noqa: E402

BINARY = 12
META = tw.META
TABLES = {
    "ROUTE": [("Segment ID", STRING), ("Longitude", REAL), ("Latitude", REAL), ("Draw Order", LONG),
              ("Map Value", REAL), ("Line-Up", STRING)],
    "STATIONS": [("Station ID", STRING), ("Longitude", REAL), ("Latitude", REAL), ("Station Status", STRING),
                 ("Pumps Running", LONG), ("Power (kW)", REAL)],
    "WEATHER": [("Geometry", BINARY), ("Solar (MJ/m2)", REAL)],
    "RESIDUALS": [("Segment ID", STRING), ("Day", LONG), ("Residual (%)", REAL), ("Model Drop (psi)", REAL),
                  ("Actual Drop (psi)", REAL), ("Status", STRING), ("Pump State", STRING)],
}
FILES = dict(tw.FILES)
SBDF = dict(("data/%s.sbdf" % name, sbdf_header(cols)) for name, cols in TABLES.items())
GOLDEN = {   # sha256 of strip_home(builder), generated with META; change only on purpose
    "kitchen/compact": "117b9c0c3b245c98b380a10ff7d16edc78eeacd16ff2b6fbfdb8d3b7f381c354",
    "kitchen/quick": "a7d1baa89ac591d5bd250ae93825a47cf48cd2ab2b559943cc4951c12a744e85",
    "kitchen/report": "4c63dea013cb9c9f2e43bdb122c579e81b32357538b94626f9d1cb5cdb4bed6a",
    "kitchen/standard": "a77372751e3fae47793abf06fb8fbe8b64a986348469784f0d9db981f0813103",
    "kitchen2/compact": "464a75ee83b55cbd340fbc3e644272a2ff2438fb093de8384d5267c65e832f73",
    "kitchen2/quick": "5af40acacdbf55f30df32ffd163bdc4e28cfa5520e6f9bf06e0fe60aaaaac1a5",
    "kitchen2/report": "fbac20d0108722531908c0eb3b208b7010e6188fff09281c0eda2bbdb47cc54d",
    "kitchen2/standard": "e6baeb89e1cb5333afb1799d9cd197cbf9394e7642544995fead104a696dbce6",
}


def pipeline_page():
    return {"title": "Pipeline", "visuals": [
        {"id": "costScatter", "type": "scatterPlot", "title": "Measured vs Model Drop", "table": "RESIDUALS",
         "x": "[Model Drop (psi)]", "y": "[Actual Drop (psi)]", "colorBy": "Status",
         "coloring": {"categorical": {"Normal": "#258750", "Critical": "#C43D4B"}},
         "lineBy": "Segment ID", "labelBy": "First([Segment ID])", "labels": "marked", "markerSize": 2.5,
         "shape": "Diamond", "limitExpression": "[Segment ID] = \"${ViewSegment}\"",
         "xScale": {"min": 0, "max": 900}, "yScale": {"min": 0, "max": 900},
         "referenceLayers": [{"kind": "horizontalLine", "value": "[$Alpha]", "label": "Warn", "dash": "dash"}],
         "fittingModels": [{"kind": "curve", "expression": "[Axis.X]", "label": "y = x", "color": "#8A8A8A",
                            "dash": "dash", "width": 1},
                           {"kind": "curve", "expression": "[$Alpha] * [Axis.X]", "label": "Scaled"}],
         "marking": "Window", "limitByMarkings": ["Marking"], "emptyMarkingBehavior": "ShowAll",
         "legend": {"visible": True, "hide": ["filtering", "marking"]},
         "settings": {"UseSeparateColorForMarkedItems": True}},
        {"id": "pipelineMap", "type": "map", "title": "Pipeline Map", "table": "ROUTE",
         "extent": {"west": -104.2, "south": 28.0, "east": -94.1, "north": 33.5},
         "interactiveLayer": "Station Status",
         "legend": {"visible": True, "hide": ["filtering", "marking", "markerBy", "shape", "size", "limits"]},
         "limitByMarkings": ["Window"], "emptyMarkingBehavior": "ShowEmpty",
         "layers": [
             {"kind": "tile", "settings": {"Transparency": 0.45}},
             {"kind": "feature", "title": "Solar Radiation", "table": "WEATHER", "colorBy": "Sum([Solar (MJ/m2)])",
              "coloring": {"gradient": [{"at": "min", "color": "#9EB6FF"}, {"at": "max", "color": "#FF4E33"}]},
              "marking": None, "settings": {"Enabled": False, "Transparency": 0.71}},
             {"kind": "feature", "title": "Contours", "table": "WEATHER", "geometry": "Geometry",
              "coloring": {"fixed": "#7F7F7F"},
              "settings": {"LineFeatureVisualAttributes.LineWidth": 2.0, "Transparency": 0.56}},
             {"kind": "marker", "title": "Pipeline", "latitude": "[Latitude]", "longitude": "[Longitude]",
              "lineBy": "<[Segment ID]>", "markerSize": 0, "colorBy": "[Map Value] as [PSI/Mile]",
              "coloring": {"gradient": [{"at": "min", "color": "#FFF9CF"}, {"at": "median", "color": "#FFDE5C"},
                                        {"at": "max", "color": "#DB4D37"}]},
              "settings": {"LineConnection.Width": 4.0, "DrawingOrderAxis.Expression": "[Draw Order]"}},
             {"kind": "marker", "title": "Station Status", "table": "STATIONS", "latitude": "Latitude",
              "longitude": "Longitude", "shape": "StarFive", "markerSize": 3.8416,
              "colorBy": "<[Station Status]>",
              "coloring": {"categorical": {"Bypassing": "#C9C9C9", "Boosting": "#239E58"}},
              "labelBy": "Concatenate(First([Station ID]), \" - \", First([Station Status]))",
              "limitExpression": "[Pumps Running] > 0", "limitByMarkings": ["Marking"],
              "emptyMarkingBehavior": "ShowAll", "settings": {"MaxNumberOfLabels": 21}},
             {"kind": "marker", "title": "Pumps", "table": "STATIONS", "colorBy": "Station Status",
              "coloring": {"fixed": "#239E58"}, "marking": "Window"}]},
        {"id": "lineUp", "type": "crossTable", "title": "Pump Line-Up", "table": "RESIDUALS",
         "rows": ["Segment ID"], "columns": ["Status"],
         "measures": ["UniqueConcatenate([Pump State]) as [State]", "Avg([Residual (%)])"],
         "coloring": [{"measures": ["UniqueConcatenate([Pump State]) as [State]"],
                       "categorical": {"On": "#239E58", "Off": "#FFDE5C"}},
                      {"gradient": [{"at": -10, "color": "#3050EF"}, {"at": 0, "color": "#FFFFFF"},
                                    {"at": 10, "color": "#C43D4B"}]}]},
        {"id": "episodes", "type": "table", "title": "Episodes", "table": "RESIDUALS",
         "columns": ["Segment ID", "Residual (%)", "Status"],
         "coloring": [{"columns": ["Status"], "rules": [{"type": "equal", "value": "Critical", "color": "#C43D4B"},
                                                        {"type": "equal", "value": "[$Mode]", "color": "#F2B134"}],
                       "settings": {"SetColorOnText": True}},
                      {"columns": ["Residual (%)"],
                       "rules": [{"type": "greaterThan", "value": 10, "color": "#C43D4B"},
                                 {"type": "between", "low": 5, "high": "[$Alpha]", "color": "#F2B134"}],
                       "default": "#00000000"}]},
        {"id": "stationKpis", "type": "kpiChart", "title": "Stations", "table": "STATIONS",
         "coloring": {"gradient": [{"at": "min", "color": "#FFFFFF"}, {"at": "max", "color": "#257347"}]},
         "kpis": [{"title": "Power", "value": "Sum([Power (kW)])"},
                  {"title": "Pumps", "value": "Sum([Pumps Running])",
                   "coloring": {"rules": [{"type": "lessThan", "value": 1, "color": "#C43D4B"}],
                                "default": "#258750"}}]},
        {"id": "residualTrend", "type": "lineChart", "title": "Residual", "table": "RESIDUALS",
         "x": "[Day]", "y": "Avg([Residual (%)])", "colorBy": "Avg([Residual (%)])",
         "coloring": {"gradient": [{"at": "min", "color": "#3050EF"}, {"at": 0, "color": "#FFFFFF"},
                                   {"at": "max", "color": "#C43D4B"}]},
         "fittingModels": [{"kind": "straightLine", "color": "#333D66"}]},
    ], "layout": {"column": [{"row": [{"visual": "costScatter"}, {"visual": "pipelineMap"}]},
                             {"row": [{"visual": "lineUp"}, {"visual": "episodes"}, {"visual": "stationKpis"},
                                      {"visual": "residualTrend"}]}]}}


def pipeline_spec():
    spec = tw.kitchen_spec()
    spec["app"]["name"] = "Pipeline Kitchen"
    spec["properties"].append({"name": "ViewSegment", "type": "String", "default": "SEG-05"})
    for name in TABLES:
        spec["tables"].append({"name": name, "source": {"type": "sbdf", "path": "data/%s.sbdf" % name}})
    spec["pages"].append(pipeline_page())
    return spec


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pipeline-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, spec=None, slug="PipelineKitchen", files=None):
        app = self.tmp / "apps" / slug
        for rel, text in (FILES if files is None else files).items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for rel, data in SBDF.items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (app / "spec.json").write_text(json.dumps(spec or pipeline_spec(), indent=2), encoding="utf-8")
        return app

    def generate(self, spec, app, tier="standard"):
        resolved = dxpgen.resolve_spec(spec, app)
        return t3.generate(resolved, spec, app, tier, dxpgen.column_reader(resolved), META)

    def visuals(self, result):
        return dict((v["id"], v) for p in result.app["pages"] for v in p["visuals"])


# ------------------------------------------------------------------------------------------------
# full builds with the real tools
# ------------------------------------------------------------------------------------------------
class PipelineBuildTests(PipelineTestCase):
    def test_tiers_build_and_pass_every_check(self):
        app = self.app()
        options = dxpgen.Options(lint=True, sanitize=False, tools_dir=SKILL / "scripts")
        for tier in ("standard", "quick", "compact", "report"):
            out = io.StringIO()
            with contextlib.redirect_stderr(io.StringIO()):
                code = dxpgen.build_app(app, app / "spec.json", options, out=out, tier=tier)
            text_out = out.getvalue()
            self.assertEqual(code, 0, text_out)
            path = app / "build" / ("build_PipelineKitchen_%s.py" % tier)
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            self.assertEqual(slim_builder.text_problems(text), [], tier)
            self.assertEqual(slim_builder.undefined_names(text), {}, tier)
            self.assertIn("lint 0 error(s)", text_out)
            self.assertNotIn("is not in the 15.0 index", text_out)
            checks = text_out.split("Checks of the generated builder:")[-1].split("To build the analysis")[0]
            self.assertNotIn("Errors (", checks)
            if dxpgen.find_index_file() is not None:
                self.assertRegex(text_out, r"sfapi\.py has: \d+ members, \d+ setters OK")
            if "IronPython parse not run" not in text_out:
                self.assertIn("PARSE OK", text_out)
            for name in ("def build_scatter(", "def build_map(", "def configure(", "def add_curve(",
                         "def axis_ranges(", "def cell_coloring(", "def kpi_coloring(", "def marker_style(",
                         "def map_layer_legends(", "def add_sbdf("):
                self.assertIn(name, text, tier)


# ------------------------------------------------------------------------------------------------
# spec -> APP
# ------------------------------------------------------------------------------------------------
class PipelineConversionTests(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.spec = pipeline_spec()
        self.result = self.generate(self.spec, self.app(self.spec))
        self.assertEqual(self.result.problems, [])
        self.v = self.visuals(self.result)

    def test_registry_and_features(self):
        self.assertEqual(t3.kind_of("scatterPlot"), "scatter")
        self.assertEqual(t3.kind_of("map"), "map")
        for feature in ("coloring", "cellColoring", "kpiColoring", "range", "fitting", "scatter", "map",
                        "markers", "settings", "links", "legendHide", "guard", "layerLegends", "pathFree"):
            self.assertIn(feature, self.result.features)
        names = [p.name for p in self.result.parts]
        for part in ("coloring", "settings", "_chart", "_markers", "scatter", "map"):
            self.assertEqual(names.count(part), 1, part)
        self.assertLess(names.index("_markers"), names.index("scatter"))

    def test_scatter(self):
        s = self.v["costScatter"]
        self.assertEqual(s["type"], "scatter")
        self.assertEqual((s["x"], s["y"]), ("[Model Drop (psi)]", "[Actual Drop (psi)]"))
        self.assertEqual(s["colorBy"], "<[Status]>")                     # a String column: a category
        self.assertEqual(s["categories"], {"Normal": "#258750", "Critical": "#C43D4B"})
        self.assertNotIn("coloring", s)                                  # the base chart colors
        self.assertEqual(s["lineBy"], "<[Segment ID]>")
        self.assertEqual((s["labelBy"], s["labels"]), ("First([Segment ID])", "Marked"))
        self.assertEqual((s["markerSize"], s["shape"]), (2.5, "Diamond"))
        self.assertEqual(s["where"], "[Segment ID] = \"${ViewSegment}\"")
        self.assertEqual((s["yMin"], s["yMax"], s["xMin"], s["xMax"]), (0, 900.0, 0.0, 900.0))
        self.assertEqual(s["refs"][0]["value"], "DocumentProperty(\"Alpha\")")
        self.assertEqual(s["curves"][0], {"kind": "curve", "expression": "x", "color": "#8A8A8A", "dash": "dash",
                                          "width": 1, "label": "y = x"})
        self.assertEqual(s["curves"][1], {"kind": "curve", "expression": "DocumentProperty(\"Alpha\") * x",
                                          "alt": "${Alpha} * x", "label": "Scaled"})
        self.assertEqual((s["marking"], s["limits"], s["empty"]), ("Window", ["Marking"], "ShowAll"))
        self.assertEqual(s["legendHide"], ["filtering", "marking"])
        self.assertEqual(s["settings"], {"UseSeparateColorForMarkedItems": True})

    def test_map(self):
        m = self.v["pipelineMap"]
        self.assertEqual((m["table"], m["interactive"]), ("ROUTE", "Station Status"))
        self.assertNotIn("limits", m)                                    # data limits are on the layers
        w, s = m["extent"][0], m["extent"][1]
        self.assertAlmostEqual(w, -104.2 * 20037508.342789244 / 180.0, places=2)
        self.assertAlmostEqual(s, math.log(math.tan((90 + 28.0) * math.pi / 360)) * 20037508.342789244 / math.pi,
                               places=2)
        tile, solar, contours, route, stations, pumps = m["layers"]
        self.assertEqual(tile, {"kind": "tile", "title": "Rich reference map", "settings": {"Transparency": 0.45}})
        self.assertEqual(solar["colorBy"], "Sum([Solar (MJ/m2)])")
        self.assertEqual(solar["coloring"], {"gradient": [["min", "#9EB6FF"], ["max", "#FF4E33"]]})
        self.assertIsNone(solar["marking"])
        self.assertNotIn("limits", solar)                                # another table than the visual's
        self.assertEqual(solar["settings"], {"Enabled": False, "Transparency": 0.71})
        self.assertEqual((contours["column"], contours["colorBy"], contours["coloring"]),
                         ("Geometry", "<>", {"fixed": "#7F7F7F"}))
        self.assertEqual((route["table"], route["x"], route["y"]), ("ROUTE", "[Longitude]", "[Latitude]"))
        self.assertEqual((route["lineBy"], route["markerSize"]), ("<[Segment ID]>", 0.0))
        self.assertEqual(route["colorBy"], "[Map Value] as [PSI/Mile]")
        self.assertEqual(route["coloring"]["gradient"][1], ["median", "#FFDE5C"])
        self.assertEqual((route["limits"], route["empty"]), (["Window"], "ShowEmpty"))   # the visual's
        self.assertEqual((stations["x"], stations["y"]), ("[Longitude]", "[Latitude]"))
        self.assertEqual((stations["shape"], stations["markerSize"]), ("StarFive", 3.8416))
        self.assertEqual(stations["colorBy"], "<[Station Status]>")
        self.assertEqual(stations["coloring"], {"categorical": [["Bypassing", "#C9C9C9"], ["Boosting", "#239E58"]]})
        self.assertEqual((stations["where"], stations["limits"], stations["empty"]),
                         ("[Pumps Running] > 0", ["Marking"], "ShowAll"))
        self.assertEqual(stations["settings"], {"MaxNumberOfLabels": 21})
        self.assertEqual((pumps["colorBy"], pumps["coloring"], pumps["marking"]),
                         ("<[Station Status]>", {"fixed": "#239E58"}, "Window"))
        self.assertEqual(m["layerLegendHide"], ["filtering", "marking", "markerBy", "shape", "size", "limits"])
        self.assertNotIn("legendHide", m)                                # nothing for the map's own legend

    def test_cells_kpis_lines(self):
        cross = self.v["lineUp"]
        self.assertEqual(cross["cellColors"][0], [["State"], {"categorical": [["On", "#239E58"], ["Off", "#FFDE5C"]]}])
        self.assertEqual(cross["cellColors"][1],
                         [None, {"gradient": [[-10.0, "#3050EF"], [0.0, "#FFFFFF"], [10.0, "#C43D4B"]]}])
        self.assertIs(cross["negatives"], False)                         # the spec's numeric coloring wins
        table = self.v["episodes"]
        self.assertEqual(table["cellColors"][0],
                         [["Status"], {"rules": [["equalText", "#C43D4B", "Critical", False],
                                                 ["equalText", "#F2B134", "DocumentProperty(\"Mode\")", True]],
                                       "settings": {"SetColorOnText": True}}])
        self.assertEqual(table["cellColors"][1],
                         [["Residual (%)"], {"rules": [["greaterThan", "#C43D4B", 10.0],
                                                       ["between", "#F2B134", 5.0, "DocumentProperty(\"Alpha\")"]],
                                             "default": "#00000000"}])
        kpis = self.v["stationKpis"]["kpis"]
        self.assertEqual(kpis[0][3], {"gradient": [["min", "#FFFFFF"], ["max", "#257347"]]})
        self.assertEqual(kpis[1][3], {"rules": [["lessThan", "#C43D4B", 1.0]], "default": "#258750"})
        trend = self.v["residualTrend"]
        self.assertEqual(trend["colorBy"], "Avg([Residual (%)])")
        self.assertEqual(trend["coloring"]["gradient"][1], [0.0, "#FFFFFF"])
        self.assertEqual(trend["curves"], [{"kind": "straightLine", "color": "#333D66"}])

    def test_generated_code_has_the_calls(self):
        text = self.result.text
        for call in ('mc.Layers.AddNewMarkerLayer(T[ls["table"]])', "AddNewFeatureLayer(",
                     "AddNewStandardTileLayer()", "GeographicExtent.Create(", "Projection.WebMercator",
                     "lc.UseMarkerColor = True", "PositioningMethod.LongitudeLatitude",
                     "mc.InteractiveLayerReference = chosen", "mc.TrellisLayerReference = ",
                     'content.ShapeAxis.DefaultShape = MarkerShape(', "getattr(LabelVisibility,",
                     "rule.Breakpoints.Add(cond(value), argb(c))", "coloring.Move(index, position)",
                     "colorings.AddMapping(CategoryKey(key), coloring)", 'kpi.ColorAxis.Expression = "THEN',
                     "models.AddCurve(", "AddStraightLineFit()", "chart.XAxis.Range = AxisRange(",
                     "set_setting, target, path,", 'register(DataPropertyClass.Column, GEOMETRY_TAG)'):
            self.assertIn(call, text)

    def test_members_are_declared(self):
        api, setters = self.result.members()
        for spec in ("ScatterPlot.XAxis", "Spotfire.Dxp.Application.Visuals.Maps.MapChart.Layers",
                     "Coloring.AddRangeRule(ConditionValue, ConditionValue, Color)", "ReferenceCurve.LineStyle",
                     "ColoringCollection.AddMapping(CategoryKey, Coloring)", "MarkerShape.ctor(MarkerType)"):
            self.assertIn(spec, api)
        for spec in ("ShapeAxis.DefaultShape", "ReferenceCurve.Width",
                     "Spotfire.Dxp.Application.Visuals.Maps.MapChart.ViewExtent"):
            self.assertIn(spec, setters)

    def test_tiers(self):
        compact = self.generate(self.spec, self.app(self.spec, slug="PipelineCompact"), "compact")
        self.assertEqual(compact.problems, [])
        v = self.visuals(compact)
        self.assertIn("cellColors", v["lineUp"])                          # data colors: every tier
        self.assertNotIn("negatives", v["lineUp"])
        self.assertIn("def build_map(", compact.text)


# ------------------------------------------------------------------------------------------------
# apps without the new kinds and colorings keep their builders
# ------------------------------------------------------------------------------------------------
class GoldenTests(PipelineTestCase):
    """Featured fixtures (the test_features kitchen and the test_kitchen_features kitchen) generate
    byte-identical builders (sha256 without the HOME literal; UnchangedBuilderTests in
    test_kitchen_features covers the apps without features). Re-pin only on purpose."""

    def digest(self, spec, app, tier):
        result = self.generate(spec, app, tier)
        self.assertEqual(result.problems, [])
        return hashlib.sha256(tw.strip_home(result.text).encode("utf-8")).hexdigest()

    def test_feature_kitchen(self):
        spec = test_features.fixture_spec()
        app = self.app(spec, slug="FeatureKitchen", files=test_features.FILES)
        for tier in ("standard", "quick", "compact", "report"):
            self.assertEqual(self.digest(spec, app, tier), GOLDEN["kitchen/" + tier], tier)

    def test_kitchen2(self):
        spec = tw.kitchen_spec()
        app = self.app(spec, slug="FeatureKitchen2", files=tw.FILES)
        for tier in ("standard", "quick", "compact", "report"):
            self.assertEqual(self.digest(spec, app, tier), GOLDEN["kitchen2/" + tier], tier)


# ------------------------------------------------------------------------------------------------
# engine functions in CPython with stand-ins for the .NET types
# ------------------------------------------------------------------------------------------------
def part_scope(rel, features, scope):
    path = t3.ENGINE_DIR / rel
    part = _assemble.Part(path.stem, path, path.read_text(encoding="utf-8"), "standard", features)
    exec(compile("\n".join(part.code), rel, "exec"), scope)
    return scope


class Rule(object):
    def __init__(self, kind, *args):
        self.kind, self.args = kind, args


class CatRule(Rule):
    def __init__(self):
        Rule.__init__(self, "categorical")
        self.colors = None

    def SetColors(self, colors):
        self.colors = list(colors)


class Breakpoints(list):
    def Add(self, value, color):
        self.append((value, color))

    def Clear(self):
        del self[:]


class ContRule(Rule):
    def __init__(self):
        Rule.__init__(self, "continuous")
        self.IntervalMode = None
        self.Breakpoints = Breakpoints([("old", "old")])


class Coloring(object):
    def __init__(self, name="", rules=None):
        self.name, self.rules, self.cats = name, list(rules or []), {}
        self.DefaultColor = self.EmptyColor = None

    @property
    def Count(self):
        return len(self.rules)

    def __getitem__(self, i):
        return self.rules[i]

    def Remove(self, rule):
        self.rules.remove(rule)

    def Clear(self):
        self.rules = []

    def _add(self, rule):
        self.rules.append(rule)
        return rule

    def AddCategoricalColorRule(self):
        return self._add(CatRule())

    def AddContinuousColorRule(self):
        return self._add(ContRule())

    def SetColorForCategory(self, key, color):
        self.cats[key] = color

    def AddThresholdColorRule(self, op, value, color):
        return self._add(Rule("threshold", op, value, color))

    def AddRangeRule(self, low, high, color):
        return self._add(Rule("range", low, high, color))

    def AddStringColorRule(self, op, value, color):
        return self._add(Rule("string", op, value, color))

    def AddTopNRule(self, n, color):
        return self._add(Rule("top", n, color))

    def AddBottomNRule(self, n, color):
        return self._add(Rule("bottom", n, color))

    def AddExpressionRule(self, text, color):
        return self._add(Rule("expression", text, color))

    def IndexOf(self, rule):
        return self.rules.index(rule)

    def Move(self, a, b):
        self.rules.insert(b, self.rules.pop(a))


class Colorings(object):
    def __init__(self):
        self.made, self.mappings, self.DefaultNumericReference = [], {}, None

    def AddNew(self, name):
        c = Coloring(name)
        self.made.append(c)
        return c

    def AddMapping(self, key, coloring):
        self.mappings[key] = coloring


def guarded(failed):
    def ok(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:                      # noqa: BLE001 - the engine's ok() logs every failure
            failed.append((name, str(e)))
            return None
    return ok


def coloring_scope(failed=None, settings=None):
    failed = [] if failed is None else failed
    settings = [] if settings is None else settings

    class ArrayOf(object):
        def __getitem__(self, t):
            return list

    statics = type("ConditionValue", (), {
        "MinValue": "MIN", "MaxValue": "MAX", "MedianValue": "MEDIAN", "AverageValue": "AVERAGE",
        "CreatePercentValue": staticmethod(lambda x: ("pct", x)),
        "CreateLiteral": staticmethod(lambda v, t=None: ("lit", v, t)),
        "CreateExpression": staticmethod(lambda t: ("expr", t))})
    scope = {
        "ok": guarded(failed), "hexcode": lambda v: v, "rgb": lambda h: ("rgb", h), "Array": ArrayOf(),
        "Object": type("Object", (), {"ReferenceEquals": staticmethod(lambda a, b: a is b)}),
        "Double": float, "Int32": int, "Int64": int,
        "Color": type("Color", (), {"FromArgb": staticmethod(lambda a, r, g, b: ("argb", a, r, g, b))}),
        "CategoryKey": lambda k: ("key", k), "CategoricalColorRule": CatRule, "ContinuousColorRule": ContRule,
        "ConditionValue": statics, "IntervalMode": type("IM", (), {"Gradient": "gradient"}),
        "RuleComparisonOperator": type("RCO", (), {"Greater": "gt", "Less": "lt", "Equal": "eq"}),
        "StringComparisonOperator": type("SCO", (), {"Equal": "seq"}),
        "DataType": type("DT", (), {"Real": "Real", "Integer": "Integer", "LongInteger": "LongInteger"}),
        "set_setting": lambda target, path, value: settings.append((target, path, value))}
    return part_scope("features/coloring.py", {"coloring", "cellColoring", "kpiColoring", "settings"}, scope)


class ColoringEngineTests(unittest.TestCase):
    def test_values(self):
        cond = coloring_scope()["cond"]
        self.assertEqual(cond(5.0), ("lit", 5.0, "Real"))
        self.assertEqual(cond(3), ("lit", 3, "Integer"))
        self.assertEqual(cond(2 ** 40), ("lit", 2 ** 40, "LongInteger"))
        self.assertEqual(cond(True), ("lit", True, None))
        self.assertEqual([cond(w) for w in ("min", "Max", "median", "average")],
                         ["MIN", "MAX", "MEDIAN", "AVERAGE"])
        self.assertEqual(cond("25%"), ("pct", 25.0))
        self.assertEqual(cond('DocumentProperty("A")'), ("expr", 'DocumentProperty("A")'))
        self.assertEqual(coloring_scope()["argb"]("#80112233"), ("argb", 0x80, 0x11, 0x22, 0x33))

    def test_gradient_with_rules_on_top(self):
        old = ContRule()
        coloring = Coloring(rules=[CatRule(), old])
        coloring_scope()["configure"]("v: coloring", coloring, {
            "gradient": [["min", "#000001"], [0.0, "#000002"], ["max", "#000003"]],
            "rules": [["greaterThan", "#0000AA", 10.0], ["between", "#0000BB", 5.0, 'DocumentProperty("A")'],
                      ["equalText", "#0000CC", "On", False], ["top", "#0000DD", 3]],
            "default": "#0000EE"})
        kinds = [r.kind for r in coloring.rules]
        self.assertEqual(kinds, ["threshold", "range", "string", "top", "continuous"])   # spec order, then bg
        self.assertIs(coloring.rules[-1], old)                                        # Spotfire's rule reused
        self.assertEqual(old.IntervalMode, "gradient")
        self.assertEqual(list(old.Breakpoints), [("MIN", ("rgb", "#000001")),
                                                 (("lit", 0.0, "Real"), ("rgb", "#000002")),
                                                 ("MAX", ("rgb", "#000003"))])
        self.assertEqual(coloring.rules[0].args, ("gt", ("lit", 10.0, "Real"), ("rgb", "#0000AA")))
        self.assertEqual(coloring.rules[1].args[1], ("expr", 'DocumentProperty("A")'))
        self.assertEqual(coloring.rules[2].args[:2], ("seq", ("lit", "On", None)))
        self.assertEqual(coloring.DefaultColor, ("rgb", "#0000EE"))

    def test_categorical_cells_kpis(self):
        failed, settings = [], []
        scope = coloring_scope(failed, settings)
        coloring = Coloring()
        scope["configure"]("c", coloring, {"categorical": [["On", "#000001"], [1, "#000002"]],
                                           "default": "#000003", "empty": "#000004",
                                           "settings": {"SetColorOnText": True}})
        self.assertEqual(coloring.rules[0].colors, [("rgb", "#000003")])            # one-color palette first
        self.assertEqual(coloring.cats, {("key", "On"): ("rgb", "#000001"), ("key", 1): ("rgb", "#000002")})
        self.assertEqual((coloring.DefaultColor, coloring.EmptyColor), (("rgb", "#000003"), ("rgb", "#000004")))
        self.assertEqual(settings, [(coloring, "SetColorOnText", True)])
        content = type("CT", (), {"Colorings": Colorings()})()
        scope["cell_colorings"](content, {"id": "ct", "cellColors": [
            [["State"], {"rules": [["equalText", "#000001", "On", False]]}],
            [None, {"gradient": [["min", "#000001"], ["max", "#000002"]]}]]})
        state, numeric = content.Colorings.made
        self.assertEqual((state.name, content.Colorings.mappings), ("State", {("key", "State"): state}))
        self.assertEqual(state.DefaultColor, ("argb", 0, 0, 0, 0))                  # unmatched cells uncolored
        self.assertIs(content.Colorings.DefaultNumericReference, numeric)
        self.assertEqual(numeric.name, "Numeric")
        axis = type("Axis", (), {"Expression": None, "Coloring": Coloring()})()
        kpi = type("Kpi", (), {"ColorAxis": axis})()
        scope["kpi_coloring"]("k", kpi, {"fixed": "#000009"})
        self.assertEqual((axis.Expression, axis.Coloring.DefaultColor),
                         ("THEN [Y.FinalValue]", ("rgb", "#000009")))
        self.assertEqual(failed, [])

    def test_a_bad_rule_does_not_stop_the_others(self):
        failed = []
        coloring = Coloring()
        coloring_scope(failed)["configure"]("c", coloring, {"rules": [["top", "#000001", "x"],
                                                                      ["lessThan", "#000002", 0.0]]})
        self.assertEqual([r.kind for r in coloring.rules], ["threshold"])
        self.assertEqual(len(failed), 1)
        self.assertIn("rule top", failed[0][0])

    def test_settings_only_keeps_the_background(self):
        old = ContRule()
        coloring = Coloring(rules=[old])
        coloring_scope()["configure"]("c", coloring, {"settings": {"EmptyColor": "#FFCCCCCC"}})
        self.assertEqual(coloring.rules, [old])


class Filterings(list):
    def Contains(self, m):
        return m in self

    def Add(self, m):
        self.append(m)


class MapEngineTests(unittest.TestCase):
    def scope(self, failed=None, settings=None, log=None, markings=("Marking", "Window")):
        failed = [] if failed is None else failed
        settings = [] if settings is None else settings

        class Markings(object):
            @staticmethod
            def TryGetValue(name):
                return (name in markings, "M:" + name if name in markings else None)

        data = type("Data", (), {"Markings": Markings(), "Properties": None})()
        scope = {"ok": guarded(failed), "MARK": "M:Marking", "T": {}, "LOG": [] if log is None else log,
                 "BUILDERS": {}, "TYPE_IDS": {},
                 "Document": type("Doc", (), {"Data": data})(), "Single": float,
                 "legend": lambda content, vs: None,
                 "set_setting": lambda target, path, value: settings.append((target, path, value)),
                 "LimitingMarkingsEmptyBehavior": type("L", (), {"ShowEmpty": "SE", "ShowAll": "SA"}),
                 "GeographicExtent": type("GE", (), {"Create": staticmethod(lambda *a: ("extent",) + a)}),
                 "Projection": type("P", (), {"WebMercator": "3857"})}
        return part_scope("builders/map.py", {"settings", "coloring"}, scope)

    def test_settings_routing(self):
        settings = []
        scope = self.scope(settings=settings)
        viz = type("Viz", (), {"Data": None, "Transparency": 0.0, "LineConnection": None,
                               "DrawingOrderAxis": None, "MarkerSize": 1.0})()
        layer = type("Layer", (), {"Enabled": True, "Title": "", "IncludeInAutoZoom": True,
                                   "Transparency": 0.0})()
        scope["map_settings"]("m: layer", layer, viz, {
            "Enabled": False, "Title": "X", "Transparency": 0.7, "IncludeInAutoZoom": False,
            "LineConnection.Width": 4.0, "Data.WhereClauseExpression": "[A] = 1", "MarkerSize": 0.0})
        where = dict((path, target) for target, path, _ in settings)
        for path in ("Enabled", "Title", "IncludeInAutoZoom"):
            self.assertIs(where[path], layer, path)
        for path in ("Transparency", "LineConnection.Width", "Data.WhereClauseExpression", "MarkerSize"):
            self.assertIs(where[path], viz, path)
        settings[:] = []
        scope["map_settings"]("m: tile", layer, None, {"Transparency": 0.45})
        self.assertEqual(settings, [(layer, "Transparency", 0.45)])                  # tile: the layer

    def test_interactive_trellis_zoom(self):
        scope = self.scope()

        class Layer(object):
            def __init__(self, enabled):
                self.Enabled = enabled

        tile, solar, route, stations = Layer(True), Layer(False), Layer(True), Layer(True)
        built = [[tile, None, {"kind": "tile", "title": "Tile"}],
                 [solar, "v", {"table": "WEATHER", "title": "Solar"}],
                 [route, "v", {"table": "ROUTE", "title": "Pipeline"}],
                 [stations, "v", {"table": "STATIONS", "title": "Stations"}]]
        mc = type("MC", (), {"InteractiveLayerReference": None, "TrellisLayerReference": None,
                             "AutoZoom": None, "ViewExtent": None})()
        scope["map_interactive"](mc, built)
        self.assertIs(mc.InteractiveLayerReference, stations)                         # top-most enabled data
        built[2][2]["title"] = "Route"
        scope["map_interactive"](mc, built, "Route")
        self.assertIs(mc.InteractiveLayerReference, route)                            # the spec's choice
        scope["map_interactive"](mc, built, "Nope")
        self.assertIs(mc.InteractiveLayerReference, stations)
        self.assertEqual(scope["map_trellis"](mc, built, "ROUTE"), "ROUTE")
        self.assertIs(mc.TrellisLayerReference, route)
        self.assertEqual(scope["map_trellis"](mc, built, "NONE"), "WEATHER")          # first data layer
        scope["map_zoom"](mc, {"extent": [-1.5, -2, 3, 4]})
        self.assertEqual((mc.AutoZoom, mc.ViewExtent), (False, ("extent", "3857", -1.5, -2.0, 3.0, 4.0)))
        scope["map_zoom"](mc, {})
        self.assertIs(mc.AutoZoom, True)
        scope["map_zoom"](mc, {"autoZoom": False})
        self.assertIs(mc.AutoZoom, False)

    def test_layer_data(self):
        failed = []
        scope = self.scope(failed)
        data = type("D", (), {"MarkingReference": None, "Filterings": Filterings(),
                              "LimitingMarkingsEmptyBehavior": None, "WhereClauseExpression": None})()
        viz = type("V", (), {"Data": data})()
        scope["map_layer_data"](viz, {"marking": None, "limits": ["Window", "Window"], "empty": "ShowEmpty",
                                      "where": "[A] > 0"})
        self.assertEqual((data.MarkingReference, list(data.Filterings), data.LimitingMarkingsEmptyBehavior,
                          data.WhereClauseExpression), (None, ["M:Window"], "SE", "[A] > 0"))
        scope["map_layer_data"](viz, {})
        self.assertEqual(data.MarkingReference, "M:Marking")                         # the default marking
        scope["ok"]("x", scope["map_layer_data"], viz, {"marking": "Nope"})
        self.assertIn("no marking Nope", failed[0][1])

    def test_geometry_tagging(self):
        log = []
        scope = self.scope(log=log)
        registry = {}

        class Registry(object):
            @staticmethod
            def ContainsProperty(kind, name):
                return (kind, name) in registry

            @staticmethod
            def AddProperty(kind, proto):
                registry[(kind, proto)] = True

        scope["Document"].Data.Properties = Registry()
        scope["DataProperty"] = type("DP", (), {"DefaultAttributes": 1,
                                                "CreateCustomPrototype": staticmethod(lambda n, t, a: n)})
        scope["DataPropertyAttributes"] = type("DPA", (), {"IsPropagated": 2})
        scope["DataPropertyClass"] = type("DPC", (), {"Column": "col", "Table": "tab"})
        binary = type("DT", (), {"Name": "Binary"})()
        scope["DataType"] = type("DTs", (), {"Binary": binary, "String": "String"})

        class Props(object):
            def __init__(self, values=None):
                self.values, self.ContentType = dict(values or {}), None

            def PropertyExists(self, name):
                return name in self.values

            def GetProperty(self, name):
                return self.values[name]

            def SetProperty(self, name, value):
                self.values[name] = value

            def HasPropertyValue(self, name):
                return name in self.values

        class Column(object):
            def __init__(self, name, dtype, values=None):
                self.Name, self.DataType, self.Properties = name, dtype, Props(values)

        class Columns(list):
            def TryGetValue(self, name):
                hits = [c for c in self if c.Name == name]
                return (bool(hits), hits[0] if hits else None)

        geometry = Column("Geometry", binary)
        table = type("T", (), {"Name": "WEATHER", "Properties": Props(),
                               "Columns": Columns([Column("Solar", type("R", (), {"Name": "Real"})()),
                                                   geometry])})()
        scope["T"]["WEATHER"] = table
        scope["map_geometry"]("m: layer Solar", {"table": "WEATHER"})
        self.assertEqual(geometry.Properties.values["MapChart.ColumnTypeId"], "Geometry")
        self.assertEqual(geometry.Properties.ContentType, "application/x-wkb")
        self.assertEqual(table.Properties.values["MapChart.GeographicCrs"], "EPSG:4326")
        self.assertEqual(sorted(registry), [("col", "MapChart.ColumnTypeId"), ("tab", "MapChart.GeographicCrs")])
        self.assertIn("NOTE m: layer Solar: set by the builder", log[0])
        log[:] = []
        scope["map_geometry"]("m: layer Solar", {"table": "WEATHER", "column": "Geometry"})
        self.assertEqual(log, [])                                                    # already tagged: no NOTE
        tagged = Column("Shape", binary, {"MapChart.ColumnTypeId": "Geometry"})
        table.Columns.insert(0, tagged)
        self.assertIs(scope["geometry_column"](table, None), tagged)                 # the tagged column first

    def test_markers(self):
        visibility = type("LV", (), {"All": "all", "Marked": "marked"})
        setattr(visibility, "None", "none")
        scope = part_scope("builders/_markers.py", set(), {
            "ok": guarded([]), "Single": float, "LabelVisibility": visibility,
            "MarkerShape": lambda t: ("shape", t), "MarkerType": type("MT", (), {"StarFive": "star"})})

        def axis():
            return type("A", (), {"Expression": None, "DefaultShape": None})()

        content = type("C", (), {"SizeAxis": axis(), "ShapeAxis": axis(), "LabelColumn": axis(),
                                 "LabelVisibility": None, "MarkerSize": None,
                                 "LineConnection": type("LC", (), {"ConnectionAxis": axis()})()})()
        scope["marker_style"]("s:", content, {"sizeBy": "Sum([P])", "shape": "StarFive", "labelBy": "[S]",
                                              "markerSize": 0, "lineBy": "<[Seg]>"})
        self.assertEqual((content.SizeAxis.Expression, content.ShapeAxis.DefaultShape,
                          content.LabelColumn.Expression, content.LabelVisibility, content.MarkerSize,
                          content.LineConnection.ConnectionAxis.Expression),
                         ("Sum([P])", ("shape", "star"), "[S]", "all", 0.0, "<[Seg]>"))
        scope["marker_labels"](content, {"labels": "None"})
        self.assertEqual(content.LabelVisibility, "none")                            # getattr: the None member


# ------------------------------------------------------------------------------------------------
# validation and what still needs the slim tier
# ------------------------------------------------------------------------------------------------
class PipelineValidationTests(PipelineTestCase):
    def report(self, spec):
        app = self.app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        return report

    def paths(self, report, level):
        return [i["path"] for i in report.items if i["level"] == level]

    def test_fixture_is_clean(self):
        report = self.report(pipeline_spec())
        self.assertEqual(self.paths(report, "error"), [])
        self.assertEqual([i["path"] for i in report.warnings                # the fixture has no filter
                          if "has no filter layout" not in i["message"]], [])   # layouts (the filter design rule)

    def test_bad_values(self):
        spec = pipeline_spec()
        page = spec["pages"][-1]["visuals"]
        page[0]["shape"] = "Hexagon"
        page[0]["fittingModels"][0].update({"width": 12, "dash": "wavy"})
        layers = page[1]["layers"]
        layers[4]["shape"] = "Star"
        layers[4]["marking"] = "Nope"
        layers[4]["limitByMarkings"] = ["Nope"]
        layers[4]["emptyMarkingBehavior"] = "Hide"
        layers[4]["fancy"] = 1
        layers[0]["labelBy"] = "[A]"
        page[1]["extent"] = {"west": 10, "south": 0, "east": 5, "north": 30}
        page[1]["interactiveLayer"] = "Nope"
        report = self.report(spec)
        errors, warnings = self.paths(report, "error"), self.paths(report, "warning")
        base = "pages[%d].visuals" % (len(spec["pages"]) - 1)
        for path in (base + "[0].shape", base + "[0].fittingModels[0].width", base + "[0].fittingModels[0].dash",
                     base + "[1].layers[4].shape", base + "[1].layers[4].marking",
                     base + "[1].layers[4].limitByMarkings[0]", base + "[1].layers[4].emptyMarkingBehavior",
                     base + "[1].extent", base + "[1].interactiveLayer"):
            self.assertIn(path, errors)
        for path in (base + "[1].layers[4].fancy", base + "[1].layers[0].labelBy"):
            self.assertIn(path, warnings)

    def test_still_unsupported(self):
        spec = pipeline_spec()
        page = spec["pages"][-1]["visuals"]
        page[0]["xScale"]["individualScaling"] = True          # trellis is built
        page[0]["fittingModels"][0]["settings"] = {"Curve.Width": 2}
        page[0]["referenceLayers"].append({"kind": "band", "low": "0", "high": "1"})
        page[1]["layers"][1]["labelBy"] = "[Solar (MJ/m2)]"
        page[1]["useFiltering"] = False
        page[3]["coloring"][0]["rules"][0]["settings"] = {"ManualDisplayName": "Critical"}
        result = self.generate(spec, self.app(spec))
        paths = [p for p, _ in result.problems]
        base = "pages[%d].visuals" % (len(spec["pages"]) - 1)
        for want in (base + "[0].xScale.individualScaling", base + "[0].fittingModels[0].settings",
                     base + "[0].referenceLayers[1]",
                     base + "[1].layers[1].labelBy", base + "[1].useFiltering",
                     base + "[3].coloring[0].rules[0].settings"):
            self.assertIn(want, paths)
        self.assertTrue(all("use --tier slim" in m for _, m in result.problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
