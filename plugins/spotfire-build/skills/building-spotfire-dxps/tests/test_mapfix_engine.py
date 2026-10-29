"""Tests for map, KPI-tile and interaction rules learned in live builds on Analyst 15.0:

- scripts/sfexpr.py raw_column_refs / unaggregated / row_level, the dxpgen error for a raw label, size, line order
  or rotation on scatter plots and map marker layers (Validator.v_marker_aggregation) and the verify_dxp FAIL
  rule (Checker.check_marker_aggregation): a raw one blanks the visual ("Please specify an aggregation method.",
  one bad layer blanks a whole map);
- map legend.hide on every data layer's own legend (feature layerLegends: scripts/t3 layerLegendHide,
  engine/builders/map.py map_layer_legends, dxpgen MAP_LEGEND_HIDE_KINDS);
- the default marking on cross tables of featured apps (t3.mark_kpi_charts, UNMARKED_KINDS);
- sbdf tables loaded by file name so the DXP keeps no local folder (feature pathFree,
  engine/features/pathfree.py);
- the interaction audit notes of dxpgen validate (Validator.v_marking_reach).

Run: python -m unittest tests/test_mapfix_engine.py   (or python -m unittest discover -s tests)
Nothing starts Spotfire; engine functions run in CPython with stand-ins.
"""
import copy
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import sfexpr  # noqa: E402
import t3  # noqa: E402
import verify_dxp as V  # noqa: E402
import test_features  # noqa: E402
import test_kitchen_features as tw  # noqa: E402
from test_dxpgen import minimal_spec  # noqa: E402
from test_pipeline_kinds import PipelineTestCase, guarded, part_scope, pipeline_spec  # noqa: E402

PROTOTYPE_CASES = [       # _work/map-diagnosis-evidence/raw_column_refs_prototype.py (17 cases)
    ("[Station ID]", ["Station ID"]),
    ("First([Station Label])", []),
    ('Concatenate(UniqueConcatenate([Station_ID])," - ",UniqueConcatenate([Station_Operating_Mode]))', []),
    ('Concatenate(First([Station ID]), " - ", First([Station Status]))', []),
    ("[Flow (bbl/d)]", ["Flow (bbl/d)"]),
    ("Avg([Flow (bbl/d)])", []),
    ("Avg([Diameter (in)]) * [Scale]", ["Scale"]),
    ("Sum([Sales]) OVER (Intersect(Parent([Axis.X]), [Region]))", []),
    ("THEN [Y.FinalValue]", []),
    ("If([A] > 0, Sum([B]))", ["A"]),
    ("Avg(If([A] > 0, [B]))", []),
    ("[T].[C]", ["C"]),
    ("Avg([X]) as [Alias]", []),
    ("12", []),
    ("[$Alpha] * Avg([X])", []),
    ('First([Name]) & " [x]"', []),
    ("Sum([Running (kW)]) as [Running]", []),
]


class SfexprTests(unittest.TestCase):
    def test_prototype_cases(self):
        for text, want in PROTOTYPE_CASES:
            self.assertEqual(sfexpr.raw_column_refs(text), want, text)

    def test_unaggregated_and_row_level(self):
        self.assertEqual(sfexpr.unaggregated("Station ID"), ["Station ID"])          # a bare spec column
        self.assertEqual(sfexpr.unaggregated("Flow (bbl/d)"), ["Flow (bbl/d)"])
        self.assertEqual(sfexpr.unaggregated("<[Segment ID]>"), [])                   # categorical
        self.assertEqual(sfexpr.unaggregated(""), [])
        self.assertEqual(sfexpr.unaggregated(None), [])
        self.assertEqual(sfexpr.unaggregated("Count()"), [])
        self.assertTrue(sfexpr.row_level("<[Axis.Default.Names] NEST baserowid()>"))
        self.assertTrue(sfexpr.row_level("<BaseRowId ()>"))
        self.assertFalse(sfexpr.row_level("<[Station]>"))
        self.assertFalse(sfexpr.row_level(None))

    def test_dxpgen_reads_expressions_with_the_same_regexes(self):
        self.assertIs(dxpgen._EXPR_STRING_RE, sfexpr._EXPR_STRING_RE)
        self.assertEqual(dxpgen.expression_columns('Avg([A]) as [B] & "[x]"'), [(None, "A")])


# ------------------------------------------------------------------------------------------------
# dxpgen: raw marker expressions are errors
# ------------------------------------------------------------------------------------------------
class MarkerAggregationValidationTests(PipelineTestCase):
    def report(self, spec):
        app = self.app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        return report

    def errors(self, report):
        return [(i["path"], i["message"]) for i in report.items if i["level"] == "error"]

    def visuals(self, spec):
        return spec["pages"][-1]["visuals"]

    def test_fixture_is_aggregated(self):
        self.assertEqual(self.errors(self.report(pipeline_spec())), [])

    def test_raw_fields_and_settings(self):
        spec = pipeline_spec()
        scatter, route, stations = self.visuals(spec)[0], self.visuals(spec)[1]["layers"][3], \
            self.visuals(spec)[1]["layers"][4]
        scatter["labelBy"] = "[Segment ID]"
        scatter["sizeBy"] = "Residual (%)"                                            # a bare column
        scatter["settings"]["LineConnection.OrderAxis.Expression"] = "[Day]"
        route["settings"]["LineConnection.OrderAxis.Expression"] = "[Draw Order]"
        stations["labelBy"] = None
        stations["settings"]["LabelColumn.Expression"] = "[Station ID]"
        stations["settings"]["RotationAxis.Expression"] = "[Power (kW)]"
        errors = self.errors(self.report(spec))
        base = "pages[%d].visuals" % (len(spec["pages"]) - 1)
        for where in (base + "[0].labelBy", base + "[0].sizeBy", base + '[0].settings["LineConnection.OrderAxis',
                      base + '[1].layers[3].settings["LineConnection.OrderAxis',
                      base + '[1].layers[4].settings["LabelColumn.Expression',
                      base + '[1].layers[4].settings["RotationAxis.Expression'):
            found = [m for p, m in errors if p.startswith(where)]
            self.assertTrue(found, (where, errors))
            self.assertIn("Please specify an aggregation method.", found[0])
        self.assertIn("one bad layer blanks the whole map",
                      [m for p, m in errors if "layers[4]" in p][0])
        self.assertIn("write First([Segment ID])", [m for p, m in errors if p == base + "[0].labelBy"][0])
        self.assertIn("write Avg([Residual (%)])", [m for p, m in errors if p == base + "[0].sizeBy"][0])

    def test_row_level_marker_by_and_aggregated_values_pass(self):
        spec = pipeline_spec()
        scatter, stations = self.visuals(spec)[0], self.visuals(spec)[1]["layers"][4]
        scatter["labelBy"] = "[Segment ID]"
        scatter["settings"]["MarkerByAxis.Expression"] = "<[Axis.Default.Names] NEST baserowid()>"
        stations["labelBy"] = "THEN [Y.FinalValue]"
        stations["sizeBy"] = "Avg([Power (kW)]) * [$Alpha]"
        stations["settings"]["LabelColumn.Expression"] = "UniqueConcatenate([Station ID])"
        self.assertEqual(self.errors(self.report(spec)), [])

    def test_feature_layers_and_3d_scatter_are_not_checked(self):
        spec = pipeline_spec()
        self.visuals(spec)[1]["layers"][1]["settings"]["LabelColumn.Expression"] = "[Solar (MJ/m2)]"
        self.assertEqual([p for p, _ in self.errors(self.report(spec)) if "aggregat" in _], [])


# ------------------------------------------------------------------------------------------------
# verify_dxp: raw marker axes FAIL
# ------------------------------------------------------------------------------------------------
class MarkerAggregationVerifyTests(unittest.TestCase):
    def check(self, vm):
        checker = object.__new__(V.Checker)
        checker.R = V.Results()
        checker.check_marker_aggregation("pages[0] > v", vm)
        return [it for it in checker.R.items if it["status"] == "FAIL"]

    def test_map_layer_and_scatter(self):
        vm = {"contentClass": "MapChart", "layers": [
            {"kind": "tile", "title": "Tile", "axes": {}},
            {"kind": "marker", "title": "Station Status", "axes": {"LabelColumn": "[Station ID]",
                                                                    "XAxis": "[Longitude]"}},
            {"kind": "marker", "title": "Route", "axes": {"DrawingOrderAxis": "[Draw Order]",
                                                          "ColorAxis": "[Map Value]"}},
            {"kind": "feature", "title": "Solar", "axes": {"LabelColumn": "[x]"}}]}
        fails = self.check(vm)
        self.assertEqual([(f["path"], f["check"]) for f in fails],
                         [('pages[0] > v layers[1] "Station Status"', "LabelColumn aggregated")])
        self.assertEqual(self.check({"contentClass": "ScatterPlot",
                                     "axes": {"LineConnection.OrderAxis": "[Flow (bbl/d)]"}})[0]["found"],
                         "[Flow (bbl/d)]")

    def test_row_level_and_aggregated_pass(self):
        self.assertEqual(self.check({"contentClass": "ScatterPlot", "axes": {
            "MarkerByAxis": "<[Axis.Default.Names] NEST baserowid()>", "LabelColumn": "[Station_ID]"}}), [])
        self.assertEqual(self.check({"contentClass": "MapChart", "layers": [{"kind": "marker", "title": "S", "axes": {
            "LabelColumn": "Concatenate(UniqueConcatenate([A]),\" - \",UniqueConcatenate([B]))",
            "SizeAxis": "Avg([P])"}}]}), [])
        self.assertEqual(self.check({"contentClass": "LineChart", "axes": {"LabelColumn": "[A]"}}), [])


# ------------------------------------------------------------------------------------------------
# map legend.hide reaches the layer legends
# ------------------------------------------------------------------------------------------------
class Item(object):
    def __init__(self, name):
        self._type = type(name, (), {"Name": name})
        self.Visible = True

    def GetType(self):
        return self._type


class MapLegendTests(PipelineTestCase):
    def test_engine_hides_the_kinds_on_every_data_layer(self):
        scope = part_scope("builders/map.py", {"layerLegends"}, {"ok": guarded([]), "BUILDERS": {}, "TYPE_IDS": {},
                                                                  "Single": float})
        names = ("LegendLayerTitleItem", "LegendFilteringsItem", "LegendMarkingItem", "LegendGroupByItem",
                 "LegendColorItem", "LegendMarkerShapeItem", "LegendSizeItem", "LegendFilterRuleItem")

        def viz():
            return type("Viz", (), {"Legend": type("L", (), {"Items": [Item(n) for n in names]})()})()

        route, stations = viz(), viz()
        built = [["tile", None, {"kind": "tile"}], ["r", route, {}], ["s", stations, {}]]
        scope["map_layer_legends"](built, ["filtering", "marking", "markerBy", "shape", "size", "limits", "bogus"])
        for v in (route, stations):
            shown = [i.GetType().__name__ for i in v.Legend.Items if i.Visible]
            self.assertEqual(shown, ["LegendLayerTitleItem", "LegendColorItem"])

    def test_feature_off_keeps_the_map_builder(self):
        path = t3.ENGINE_DIR / "builders" / "map.py"
        off = t3._assemble.Part("map", path, path.read_text(encoding="utf-8"), "standard", {"settings"})
        self.assertNotIn("map_layer_legends", "\n".join(off.code))
        self.assertNotIn("LegendItem.Visible", off.set)
        on = t3._assemble.Part("map", path, path.read_text(encoding="utf-8"), "standard", {"layerLegends"})
        self.assertIn("def map_layer_legends(built, kinds):", "\n".join(on.code))
        self.assertIn("LegendItem.Visible", on.set)

    def test_converter_splits_the_kinds(self):
        spec = pipeline_spec()
        m = spec["pages"][-1]["visuals"][1]
        m["legend"] = {"visible": True, "hide": ["marking", "markerBy", "trellis"]}
        result = self.generate(spec, self.app(spec))
        self.assertEqual(result.problems, [])
        vm = self.visuals(result)["pipelineMap"]
        self.assertEqual((vm["layerLegendHide"], vm["legendHide"]), (["marking", "markerBy"], ["trellis"]))
        self.assertIn("layerLegends", result.features)
        self.assertIn("legendHide", result.features)
        self.assertIn("def map_layer_legends(", result.text)
        m["legend"] = {"visible": True, "hide": ["filtering"]}
        vm = self.visuals(self.generate(spec, self.app(spec, slug="P2")))["pipelineMap"]
        self.assertEqual(vm["layerLegendHide"], ["filtering"])
        self.assertNotIn("legendHide", vm)

    def test_dxpgen_kinds(self):
        spec = pipeline_spec()
        visuals = spec["pages"][-1]["visuals"]
        visuals[1]["legend"] = {"visible": True, "hide": ["markerBy", "shape", "size", "limits", "layerTitle",
                                                          "dataTable", "rotation", "trellis", "referenceLayers"]}
        visuals[5]["legend"] = {"visible": True, "hide": ["markerBy"]}
        app = self.app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        errors = [i["path"] for i in report.items if i["level"] == "error"]
        base = "pages[%d].visuals" % (len(spec["pages"]) - 1)
        self.assertEqual(sorted(errors), sorted([base + "[1].legend.hide[8]", base + "[5].legend.hide[0]"]))


# ------------------------------------------------------------------------------------------------
# cross tables get the default marking (featured apps)
# ------------------------------------------------------------------------------------------------
class CrossTableMarkingTests(PipelineTestCase):
    def test_default_explicit_and_null(self):
        spec = pipeline_spec()
        visuals = spec["pages"][-1]["visuals"]
        visuals.append(copy.deepcopy(visuals[2]))
        visuals[-1].update({"id": "lineUp2", "marking": "Marking"})              # = the default marking
        visuals.append(copy.deepcopy(visuals[2]))
        visuals[-1].update({"id": "lineUp3", "marking": None})
        visuals.append(copy.deepcopy(visuals[2]))
        visuals[-1].update({"id": "lineUp4", "marking": "Window"})
        result = self.generate(spec, self.app(spec))
        v = self.visuals(result)
        self.assertEqual(v["lineUp"]["marking"], "Marking")
        self.assertEqual(v["lineUp2"]["marking"], "Marking")
        self.assertIsNone(v["lineUp3"]["marking"])
        self.assertEqual(v["lineUp4"]["marking"], "Window")
        self.assertIn("links", result.features)
        self.assertNotIn("marking", v["episodes"])                                # AddNew marks tables

    def test_apps_without_features_keep_the_gap(self):
        spec = minimal_spec()
        app = self.tmp / "apps" / "Minimal"
        app.mkdir(parents=True)
        result = self.generate(spec, app)
        self.assertEqual(result.features, set())
        for page in result.app["pages"]:
            for vs in page["visuals"]:
                if vs["type"] in t3.UNMARKED_KINDS:
                    self.assertNotIn("marking", vs)


# ------------------------------------------------------------------------------------------------
# sbdf tables without their folder
# ------------------------------------------------------------------------------------------------
class PathFreeTests(PipelineTestCase):
    def test_feature_selection_and_builder(self):
        spec = pipeline_spec()                                                     # sbdf tables + features
        result = self.generate(spec, self.app(spec))
        self.assertIn("pathFree", result.features)
        self.assertIn("pathfree", [p.name for p in result.parts])
        text = result.text
        self.assertIn("    t = add_sbdf(name, path)\n    settings = Document.Data.SaveSettings", text)
        self.assertIn("Directory.SetCurrentDirectory(Path.GetDirectoryName(path))", text)
        self.assertIn("view.GetAllOperations[DataSourceOperation]()", text)
        api, setters = result.members()
        for spec_ in ("DataTable.GenerateSourceView", "FileDataSource.FilePath", "DataFlow.DataSource",
                      "Spotfire.Dxp.Data.DataOperations.DataSourceOperation.GetDataFlow"):
            self.assertIn(spec_, api)

    def test_featured_apps_without_sbdf_tables_and_apps_without_features(self):
        spec = tw.kitchen_spec()                                                     # data-function tables only
        result = self.generate(spec, self.app(spec, slug="Kitchen2", files=tw.FILES))
        self.assertNotIn("pathFree", result.features)
        self.assertNotIn("add_sbdf", result.text)
        spec = minimal_spec()
        app = self.tmp / "apps" / "Minimal"
        app.mkdir(parents=True)
        result = self.generate(spec, app)
        self.assertNotIn("add_sbdf", result.text)
        self.assertIn("    ds = SbdfFileDataSource(path)\n    ds.IsPromptingAllowed = False\n"
                      "    t = Document.Data.Tables.Add(name, ds, True)\n", result.text)

    def scope(self, fail_by_name=None, columns=3, log=None):
        calls = {"cwd": ["C:\\start"], "added": [], "removed": []}

        class Directory(object):
            @staticmethod
            def GetCurrentDirectory():
                return calls["cwd"][-1]

            @staticmethod
            def SetCurrentDirectory(path):
                calls["cwd"].append(path)

        class Source(object):
            def __init__(self, path):
                self.path, self.IsPromptingAllowed = path, True

        class Table(object):
            def __init__(self, name, ds):
                self.name, self.ds, self.RowCount = name, ds, 10
                self.Columns = type("C", (), {"Count": columns if ds.path == "W.sbdf" else 3})()
                self.folder = calls["cwd"][-1]

            def GenerateSourceView(self):
                ds = self.ds

                class Getter(object):
                    def __getitem__(self, t):
                        flow = type("F", (), {"DataSource": type("S", (), {"FilePath": ds.path})()})()
                        op = type("Op", (), {"GetDataFlow": staticmethod(lambda: flow)})()
                        return lambda: [op]
                return type("V", (), {"GetAllOperations": Getter()})()

        class Tables(object):
            def Add(self, name, ds, flag):
                if fail_by_name and ds.path == "W.sbdf":
                    raise Exception(fail_by_name)
                t = Table(name, ds)
                calls["added"].append(t)
                return t

            def TryGetValue(self, name):
                found = [t for t in calls["added"] if t.name == name and t not in calls["removed"]]
                return (bool(found), found[0] if found else None)

            def Remove(self, t):
                calls["removed"].append(t)

        doc = type("Doc", (), {"Data": type("D", (), {"Tables": Tables()})()})()
        scope = {"Document": doc, "LOG": [] if log is None else log, "why": str, "ok": guarded([]),
                 "SbdfFileDataSource": Source, "DataSourceOperation": "DSO",
                 "Directory": Directory,
                 "Path": type("P", (), {"GetDirectoryName": staticmethod(os.path.dirname),
                                        "GetFileName": staticmethod(os.path.basename)})}
        return part_scope("features/pathfree.py", {"pathFree"}, scope), calls

    def test_loads_by_file_name_and_restores_the_folder(self):
        log = []
        scope, calls = self.scope(log=log)
        t = scope["add_sbdf"]("W", os.path.join("C:\\app", "data", "W.sbdf"))
        self.assertEqual((t.ds.path, t.ds.IsPromptingAllowed), ("W.sbdf", False))
        self.assertEqual(t.folder, os.path.join("C:\\app", "data"))               # loaded from its folder
        self.assertEqual(calls["cwd"][-1], "C:\\start")                            # folder restored
        self.assertEqual(log, ["NOTE W: the DXP keeps the source path 'W.sbdf'"])

    def test_falls_back_to_the_full_path(self):
        log = []
        scope, calls = self.scope(fail_by_name="file not found", log=log)
        full = os.path.join("C:\\app", "data", "W.sbdf")
        t = scope["add_sbdf"]("W", full)
        self.assertEqual(t.ds.path, full)
        self.assertEqual(calls["cwd"][-1], "C:\\start")
        self.assertIn("loaded from the full path, which the DXP keeps (by file name: file not found)", log[0])

    def test_a_table_without_columns_is_removed_before_the_fallback(self):
        log = []
        scope, calls = self.scope(columns=0, log=log)
        full = os.path.join("C:\\app", "data", "W.sbdf")
        t = scope["add_sbdf"]("W", full)
        self.assertEqual(t.ds.path, full)
        self.assertEqual([r.ds.path for r in calls["removed"]], ["W.sbdf"])
        self.assertIn("no columns (10 rows)", log[0])


# ------------------------------------------------------------------------------------------------
# the shapes a KPI band and its interactions need
# ------------------------------------------------------------------------------------------------
class InteractionDesignShapeTests(PipelineTestCase):
    def test_band_links_trackers_markings(self):
        spec = pipeline_spec()
        spec["markings"].append({"name": "Station Pick", "color": "#7E57C2"})
        spec["properties"].append({"name": "KpiOpsFlow", "type": "String", "default": "-"})
        band = spec["pages"][0]["visuals"][0]
        band["html"] += "<span>{{control:kpiOpsFlow}}</span><span>{{control:mapFlow}}</span>"
        controls = band["controls"]
        controls["kpiOpsFlow"] = {"kind": "label", "property": "KpiOpsFlow"}
        controls["mapFlow"] = {"kind": "link", "label": "Show on map", "script": "Add Window",
                               "args": {"Kind": "Flow"},
                               "actionMod": {"mod": tw.MOD_ID, "script": "add-window", "args": {"kind": "Normal"}}}
        page = spec["pages"][-1]["visuals"]
        page[2]["marking"] = "Station Pick"                                        # cross table
        page[2]["settings"] = {"UseSeparateColorForMarkedItems": True}
        stations = page[1]["layers"][4]
        stations["marking"] = "Station Pick"
        stations["settings"]["UseSeparateColorForMarkedItems"] = True
        page[0]["y"] = ["[Actual Drop (psi)] as [Running]", "[Model Drop (psi)] as [Model]"]
        page[0]["colorBy"] = None
        page[0].pop("coloring")
        page[0]["labelBy"] = "[Segment ID]"                                       # raw: fine at row level
        page[0]["settings"]["MarkerByAxis.Expression"] = "<[Axis.Default.Names] NEST baserowid()>"
        page[0]["referenceLayers"].append({"kind": "verticalLine", "label": "View",
                                           "value": "Avg(If([Day] = DocumentProperty(\"Count\"), "
                                                    "[Model Drop (psi)]))"})
        app = self.app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        self.assertEqual(report.errors, [], report.render())
        for _ in (1,):
            result = self.generate(spec, app)
            self.assertEqual(result.problems, [])
            v = self.visuals(result)
            c = v["controls"]["controls"]
            self.assertEqual(c["kpiOpsFlow"], "Label: KpiOpsFlow")             # markers: manual steps
            self.assertEqual(c["mapFlow"], "Link: Show on map")
            how = dict(result.manual)["control controls/mapFlow"]
            self.assertIn("Insert Action Control > Link labeled 'Show on map'", how)
            self.assertIn("runs the IronPython script 'Add Window' with arguments Kind = Flow", how)
            self.assertEqual(v["lineUp"]["marking"], "Station Pick")
            stations_app = v["pipelineMap"]["layers"][4]
            self.assertEqual(stations_app["marking"], "Station Pick")
            self.assertEqual(v["costScatter"]["colorBy"], "<[Axis.Default.Names]>")
            track = [d for d in result.app["dataFunctions"] if d["name"] == "Track Window"][0]
            self.assertEqual(track["in"][0][2], {"table": "SCORES", "columns": ["Timestamp", "Group"],
                                                 "marking": "Window"})              # a data-function table
            self.assertIn("markedInputs", result.features)
            self.assertIn("trigger MarkedWindow -> Apply Window", [m[0] for m in result.app["manual"]])


# ------------------------------------------------------------------------------------------------
# dxpgen validate: interaction audit notes
# ------------------------------------------------------------------------------------------------
class InteractionAuditTests(PipelineTestCase):
    def notes(self, spec, files=None):
        app = self.app(spec, files=files)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        return [i["message"] for i in report.notes if i["message"].startswith("interactions")]

    def test_spans_lonely_and_split_markings(self):
        notes = self.notes(pipeline_spec())
        page = '"Pipeline"'
        spans = [n for n in notes if page in n and "marking 'Marking' spans tables" in n]
        self.assertTrue(spans, notes)
        self.assertIn("RESIDUALS: lineUp, episodes", spans[0])
        split = [n for n in notes if page in n and "table STATIONS is shown with different markings" in n]
        self.assertTrue(split, notes)
        self.assertIn("Window: pipelineMap/Pumps", split[0])
        lonely = [n for n in notes if '"Main"' in n and "marking 'Window' is used only by trend" in n]
        self.assertEqual(lonely, [])                       # Track Window reads Window (a marking-limited input)

    def test_lonely_marking(self):
        spec = test_features.fixture_spec()
        notes = self.notes(spec, files=test_features.FILES)
        self.assertFalse([n for n in notes if "used only by trend" in n], notes)    # "marked" is limited by it
        self.assertTrue([n for n in notes if "table SCORES is shown with different markings" in n], notes)
        spec["pages"][0]["visuals"][4]["limitByMarkings"] = ["Marking"]
        notes = self.notes(spec, files=test_features.FILES)
        lonely = [n for n in notes if "marking 'Window' is used only by trend (SCORES)" in n]
        self.assertTrue(lonely, notes)
        self.assertNotIn("a script names it", lonely[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
