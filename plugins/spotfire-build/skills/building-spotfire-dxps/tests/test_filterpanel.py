"""Tests for filter panel layouts (spec "filterPanelLayout" and page "filters";
engine/features/filterpanel.py, scripts/t3/_filters.py, dxpgen validate, verify_dxp) and trellis plus
individual y scaling on line, bar and scatter charts (feature trellis in engine/builders/_chart.py,
scripts/t3/_charts.py).

Run: python -m unittest tests/test_filterpanel.py   (or python -m unittest discover -s tests)

The fixture is the Pipeline kitchen of test_pipeline_kinds (feature kitchen + sbdf tables ROUTE, STATIONS,
WEATHER, RESIDUALS) with a top-level layout, a page's own layout, a page that keeps every filter, a trellised
line chart with its own y scale per panel and a scatter plot trellised by columns. FilterBuildTests builds
it with the real tools (lint, Spotfire's IronPython parser when installed, sfapi.py); the other tests run
the generator, the validator, the engine functions with stand-ins for the .NET types, and verify_dxp's
reader and comparison. Nothing starts Spotfire.
"""
import ast
import contextlib
import copy
import io
import json
import sys
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
import verify_dxp as V  # noqa: E402
from t3 import _assemble, _filters  # noqa: E402
import test_pipeline_kinds as tp  # noqa: E402

TOP_LAYOUT = {"tables": [
    {"table": "RESIDUALS", "columns": ["Segment ID", "Status", "Day"],
     "filterTypes": {"Segment ID": "ListBoxFilter", "Day": "RangeFilter"},
     "subGroups": [{"name": "Model", "columns": ["Model Drop (psi)", "Actual Drop (psi)"], "expanded": False}]},
    {"table": "STATIONS", "columns": "*", "expanded": False}]}
PIPELINE_LAYOUT = {"tables": [
    {"table": "SCORES", "columns": ["Group", "Score"]},
    {"table": "RESIDUALS", "columns": ["Segment ID"], "filterTypes": {"Segment ID": "ListBoxFilter"}}]}


def filter_spec():
    spec = tp.pipeline_spec()
    spec["app"]["name"] = "Filter Kitchen"
    spec["filterPanelLayout"] = copy.deepcopy(TOP_LAYOUT)
    pages = spec["pages"]
    pages[-1]["filters"] = copy.deepcopy(PIPELINE_LAYOUT)
    pages[1]["filters"] = "all"
    for v in pages[-1]["visuals"]:
        if v["id"] == "residualTrend":
            v["trellis"] = {"panelBy": "Segment ID", "rows": 2, "columns": 3}
            v["yScale"] = {"individualScaling": True}
        if v["id"] == "costScatter":
            v["trellis"] = {"columnsBy": "<[Status]>"}
    return spec


class FilterTestCase(tp.PipelineTestCase):
    def validate(self, spec):
        app = self.app(spec, slug="FilterKitchen")
        report, _, _ = dxpgen.validate_app(app, app / "spec.json", dxpgen.Options(lint=False, sanitize=False))
        return report

    def messages(self, report, level):
        return [i["path"] + ": " + i["message"] for i in report.items if i["level"] == level]


# ------------------------------------------------------------------------------------------------
# full builds with the real tools
# ------------------------------------------------------------------------------------------------
class FilterBuildTests(FilterTestCase):
    def test_builds_pass_every_check(self):
        app = self.app(filter_spec(), slug="FilterKitchen")
        options = dxpgen.Options(lint=True, sanitize=False, tools_dir=SKILL / "scripts")
        for tier in ("standard", "quick", "compact", "report"):
            out = io.StringIO()
            with contextlib.redirect_stderr(io.StringIO()):
                code = dxpgen.build_app(app, app / "spec.json", options, out=out, tier=tier)
            text_out = out.getvalue()
            self.assertEqual(code, 0, text_out)
            text = (app / "build" / ("build_FilterKitchen_%s.py" % tier)).read_text(encoding="utf-8")
            ast.parse(text)
            self.assertEqual(slim_builder.text_problems(text), [], tier)
            self.assertEqual(slim_builder.undefined_names(text), {}, tier)
            self.assertIn("lint 0 error(s)", text_out)
            self.assertNotIn("is not in the 15.0 index", text_out)
            checks = text_out.split("Checks of the generated builder:")[-1].split("To build the analysis")[0]
            self.assertNotIn("Errors (", checks)
            if "IronPython parse not run" not in text_out:
                self.assertIn("PARSE OK", text_out)
            for name in ("def filter_table(", "def filter_others(", "def filter_type(", "def trellis(",
                         "def y_each(", "filter_layout, PAGES[ps[\"title\"]]"):
                self.assertIn(name, text, tier)


# ------------------------------------------------------------------------------------------------
# spec -> APP
# ------------------------------------------------------------------------------------------------
class FilterConversionTests(FilterTestCase):
    def setUp(self):
        super().setUp()
        self.spec = filter_spec()
        self.result = self.generate(self.spec, self.app(self.spec, slug="FilterKitchen"))
        self.assertEqual(self.result.problems, [])
        self.pages = dict((p["title"], p) for p in self.result.app["pages"])

    def test_features_and_parts(self):
        for feature in ("filterLayout", "trellis"):
            self.assertIn(feature, self.result.features)
        names = [p.name for p in self.result.parts]
        self.assertEqual(names.count("filterpanel"), 1)
        self.assertIn("for entry in APP.get(\"filterTypes\", []):", self.result.text)

    def test_page_layouts(self):
        titles = [p["title"] for p in self.spec["pages"]]
        top = [{"table": "RESIDUALS", "columns": ["Segment ID", "Status", "Day"],
                "groups": [["Model", ["Model Drop (psi)", "Actual Drop (psi)"], False]]},
               {"table": "STATIONS", "columns": "*", "expanded": False}]
        self.assertEqual(self.pages[titles[0]]["filters"], top)
        self.assertNotIn("filters", self.pages[titles[1]])                  # "all"
        self.assertEqual(self.pages[titles[-1]]["filters"],
                         [{"table": "SCORES", "columns": ["Group", "Score"]},
                          {"table": "RESIDUALS", "columns": ["Segment ID"]}])

    def test_filter_types_once_per_column(self):
        self.assertEqual(self.result.app["filterTypes"],
                         [["RESIDUALS", "Segment ID", "ListBoxFilter"], ["RESIDUALS", "Day", "RangeFilter"]])
        keys = list(self.result.app)
        self.assertEqual(keys.index("filterTypes") + 1, keys.index("pages"))

    def test_trellis_keys(self):
        v = self.visuals(self.result)
        self.assertEqual(v["residualTrend"]["trellis"], {"panel": "<[Segment ID]>", "rows": 2, "columns": 3})
        self.assertIs(v["residualTrend"]["yEach"], True)
        self.assertEqual(v["costScatter"]["trellis"], {"columnsBy": "<[Status]>"})
        self.assertNotIn("yEach", v["costScatter"])

    def test_apps_without_them_keep_their_builders(self):
        plain = tp.pipeline_spec()
        result = self.generate(plain, self.app(plain, slug="PlainKitchen"))
        self.assertEqual(result.problems, [])
        for feature in ("filterLayout", "trellis"):
            self.assertNotIn(feature, result.features)
        for name in ("filter_layout", "filterTypes", "def trellis(", "TrellisMode", "IndividualScalingMode"):
            self.assertNotIn(name, result.text)
        every = tp.pipeline_spec()
        every["filterPanelLayout"] = copy.deepcopy(TOP_LAYOUT)
        for page in every["pages"]:
            page["filters"] = "all"
        again = self.generate(every, self.app(every, slug="AllKitchen"))
        self.assertNotIn("filterLayout", again.features)
        self.assertEqual(tp.tw.strip_home(again.text).replace("All Kitchen", "x"),
                         tp.tw.strip_home(result.text).replace("Plain Kitchen", "x"))

    def test_library_tiers_drop_the_layouts(self):
        resolved = dxpgen.library_spec(dxpgen.resolve_spec(self.spec, self.app(self.spec, slug="FilterKitchen")))
        self.assertNotIn("filterPanelLayout", resolved)
        self.assertTrue(all("filters" not in p for p in resolved["pages"]))
        self.assertTrue(_filters.uses_layouts(self.spec))


# ------------------------------------------------------------------------------------------------
# dxpgen validate
# ------------------------------------------------------------------------------------------------
class FilterValidationTests(FilterTestCase):
    def assertError(self, spec, text):
        errors = self.messages(self.validate(spec), "error")
        self.assertTrue([e for e in errors if text in e], "no error with %r in %s" % (text, errors))

    def test_fixture_is_valid(self):
        report = self.validate(filter_spec())
        self.assertEqual(self.messages(report, "error"), [])
        self.assertEqual([w for w in self.messages(report, "warning") if "filter" in w.lower()], [])
        self.assertTrue([n for n in self.messages(report, "note") if "keeps Spotfire's default filter panel" in n])

    def test_design_rule_warning(self):
        spec = tp.pipeline_spec()
        warnings = [w for w in self.messages(self.validate(spec), "warning") if "has no filter layout" in w]
        self.assertEqual(len(warnings), len(spec["pages"]))
        spec["pages"][0]["filters"] = "all"
        warnings = [w for w in self.messages(self.validate(spec), "warning") if "has no filter layout" in w]
        self.assertEqual(len(warnings), len(spec["pages"]) - 1)

    def mutate(self, fn):
        spec = filter_spec()
        fn(spec)
        return spec

    def test_unknown_table_and_columns(self):
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"].append(
            {"table": "NOPE", "columns": ["A"]})), "unknown data table 'NOPE'")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["columns"].append("Stauts")),
                         "'Stauts' is not a column of table RESIDUALS")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["columns"].append("status")),
                         "write the column exactly as table RESIDUALS spells it: 'Status'")
        self.assertError(self.mutate(lambda s: s["pages"][-1]["filters"]["tables"][0]["columns"].append("Extra")),
                         "'Extra' is not among the columns declared in tables[].columns of data-function table SCORES")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"].append(
            {"table": "WEATHER", "columns": ["Geometry"]})), "is Binary: Spotfire has no filter for it")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"].append(
            {"table": "EVENTS", "columns": ["Kind"]})), "data-function table EVENTS has no tables[] entry")

    def test_filter_types(self):
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["filterTypes"].update(
            {"Status": "DropDownFilter"})), "unknown filter type")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["filterTypes"].update(
            {"Status": "RangeFilter"})), "a RangeFilter needs a number, date or time column")
        self.assertError(self.mutate(lambda s: s["pages"][-1]["filters"]["tables"][1]["filterTypes"].update(
            {"Segment ID": "CheckBoxFilter"})), "a column has one type in the whole app")

    def test_structure(self):
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["subGroups"][0]["columns"].append(
            "Status")), "column 'Status' is already shown in the top-level columns")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["subGroups"].append(
            {"name": "model", "columns": ["Residual (%)"]})), "is used twice in table RESIDUALS")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"].append(
            {"table": "ROUTE"})), "table ROUTE shows no filter")
        self.assertError(self.mutate(lambda s: s["pages"][0].update({"filters": True})),
                         "must be a filter layout")
        self.assertError(self.mutate(lambda s: s.update({"filterPanelLayout": []})), "must be a filter layout")
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"].append(
            {"table": "STATIONS", "columns": ["Station ID"]})), "table STATIONS is listed twice")

    def test_sub_group_names_are_customer_text(self):
        self.assertError(self.mutate(lambda s: s["filterPanelLayout"]["tables"][0]["subGroups"][0].update(
            {"name": "TODO rename"})), "customer-ready text")

    def test_table_must_exist_at_build(self):
        def no_run(s):
            s["dataFunctions"][1]["executeAtBuild"] = False
        self.assertError(self.mutate(no_run), "executeAtBuild: false")

    def test_trellis_grid_warning(self):
        spec = filter_spec()
        for v in spec["pages"][-1]["visuals"]:
            if v["id"] == "costScatter":
                v["trellis"]["rows"] = 2
        warnings = self.messages(self.validate(spec), "warning")
        self.assertTrue([w for w in warnings if "applies to panelBy only" in w], warnings)
        spec = filter_spec()
        for v in spec["pages"][-1]["visuals"]:
            if v["id"] == "residualTrend":
                del v["trellis"]["columns"]                       # rows without columns
        warnings = self.messages(self.validate(spec), "warning")
        self.assertTrue([w for w in warnings if "needs both rows and columns" in w], warnings)
        self.assertEqual([w for w in self.messages(self.validate(filter_spec()), "warning")
                          if "needs both rows and columns" in w], [])

    def test_null_means_absent(self):
        spec = filter_spec()                                      # references/spec-format.md's skeletons show both as null
        spec["pages"][0]["filters"] = None
        report = self.validate(spec)
        self.assertEqual(self.messages(report, "error"), [])
        self.assertEqual(_filters.page_layout(spec, spec["pages"][0]), spec["filterPanelLayout"])
        spec["filterPanelLayout"] = None
        report = self.validate(spec)
        self.assertEqual(self.messages(report, "error"), [])
        self.assertTrue([w for w in self.messages(report, "warning") if "has no filter layout" in w])

    def test_unused_top_level_layout(self):
        spec = filter_spec()
        warnings = [w for w in self.messages(self.validate(spec), "warning") if "no page uses this layout" in w]
        self.assertEqual(warnings, [])
        for page in spec["pages"]:
            page.setdefault("filters", "all")
        warnings = [w for w in self.messages(self.validate(spec), "warning") if "no page uses this layout" in w]
        self.assertEqual(len(warnings), 1)


# ------------------------------------------------------------------------------------------------
# engine functions in CPython with stand-ins for the .NET types
# ------------------------------------------------------------------------------------------------
class Items(list):
    def IndexOf(self, item):
        for i, x in enumerate(self):
            if x is item:
                return i
        return -1

    def Move(self, a, b):
        self.insert(b, self.pop(a))


class Filter(object):
    def __init__(self, name):
        self.Name, self.TypeId = name, "CheckBoxFilter"


class Handle(object):
    def __init__(self, f, parent):
        self.FilterReference, self.ParentGroup, self.Visible = f, parent, True


class Group(object):
    def __init__(self, name):
        self.Name, self.Items, self.Visible, self.Expanded = name, Items(), True, True

    @property
    def FilterHandles(self):
        return [x for x in self.Items if isinstance(x, Handle)]

    def GetFilter(self, name):
        for h in self.FilterHandles:
            if h.FilterReference.Name == name:
                return h
        return None

    def Add(self, f):
        h = Handle(f, self)
        self.Items.append(h)
        return h

    def Remove(self, f):
        for h in self.FilterHandles:
            if h.FilterReference is f:
                self.Items.remove(h)
                return


class Columns(dict):
    def Contains(self, name):
        return name in self


class Collection(object):
    def __init__(self, names):
        self.filters = dict((n, Filter(n)) for n in names)
        self.DataTableReference = type("T", (), {"Columns": Columns((n, n) for n in names)})()

    def Contains(self, name):
        return name in self.filters

    def __getitem__(self, name):
        return self.filters[name]

    def AddNewFilter(self, column):
        self.filters[column] = Filter(column)
        return self.filters[column]


class SyncingCollection(Collection):
    """A table group's collection whose AddNewFilter behaves as in Spotfire: the new filter gets its
    top-level handle at once (TableGroup.FilterCollectionChanged with AutoSynchronizeFilters)."""
    def __init__(self, group):
        old = group.FilterCollectionReference
        self.filters, self.DataTableReference, self.group = old.filters, old.DataTableReference, group

    def AddNewFilter(self, column):
        f = Collection.AddNewFilter(self, column)
        self.group.Add(f)
        return f


class TableGroup(Group):
    def __init__(self, name, columns):
        Group.__init__(self, name)
        self.FilterCollectionReference = Collection(columns)
        for c in columns:
            self.Add(self.FilterCollectionReference[c])

    @property
    def SubGroups(self):
        return [x for x in self.Items if isinstance(x, Group)]

    def GetSubGroup(self, name):
        for g in self.SubGroups:
            if g.Name == name:
                return g
        return None

    def AddNewSubGroup(self, name):
        g = Group(name)
        self.Items.append(g)
        return g


class Panel(object):
    def __init__(self, groups):
        self.TableGroups = Items(groups)


def labels(group):
    return [(x.FilterReference.Name if isinstance(x, Handle) else "[%s]" % x.Name, x.Visible) for x in group.Items]


class FilterEngineTests(unittest.TestCase):
    def setUp(self):
        self.log = []

        def ok(name, fn, *args):
            try:
                return fn(*args)
            except Exception as e:
                self.log.append("FAILED " + name + ": " + str(e))
                return None
        self.scope = {"ok": ok, "LOG": self.log, "T": {},
                      "FilterTypeIdentifiers": type("FTI", (), dict((n, "id:" + n) for n in _filters.FILTER_TYPES))}
        tp.part_scope("features/filterpanel.py", {"filterLayout"}, self.scope)
        self.wells = TableGroup("WELLS", ["Well", "Region", "Rig", "Spud", "WOB", "ROP", "Notes"])
        self.daily = TableGroup("DAILY", ["Well", "Day", "Depth", "Pressure", "Rate"])
        self.other = TableGroup("OTHER", ["X"])
        self.panel = Panel([self.other, self.daily, self.wells])

    def test_listed_columns_groups_order_and_place(self):
        entry = {"table": "WELLS", "columns": ["Rig", "Well"], "groups": [["Bit Data", ["ROP", "WOB"], False]],
                 "expanded": False}
        shown = self.scope["filter_table"](self.panel, entry, 0)
        self.assertEqual(shown, 4)
        self.assertIs(self.panel.TableGroups[0], self.wells)
        self.assertEqual(labels(self.wells)[:3], [("Rig", True), ("Well", True), ("[Bit Data]", True)])
        self.assertEqual(sorted(labels(self.wells)[3:]), [("Notes", False), ("Region", False), ("Spud", False)])
        sub = self.wells.GetSubGroup("Bit Data")
        self.assertEqual(labels(sub), [("ROP", True), ("WOB", True)])
        self.assertIs(sub.Expanded, False)
        self.assertIs(self.wells.Expanded, False)
        self.assertIsNone(self.wells.GetFilter("ROP"))              # moved, not copied

    def test_star_keeps_order_and_puts_groups_last(self):
        entry = {"table": "DAILY", "columns": "*", "groups": [["Flow Data", ["Pressure", "Rate"]]]}
        self.scope["filter_table"](self.panel, entry, 1)
        self.assertEqual(labels(self.daily), [("Well", True), ("Day", True), ("Depth", True), ("[Flow Data]", True)])
        self.assertIs(self.panel.TableGroups[1], self.daily)

    def test_layout_hides_other_tables_and_logs(self):
        ps = {"title": "Bit Data", "filters": [{"table": "WELLS", "columns": ["Well"]},
                                               {"table": "DAILY", "columns": ["Depth"]}]}
        page = type("Page", (), {"FilterPanel": self.panel})()
        self.scope["filter_layout"](page, ps)
        self.assertEqual([g.Name for g in self.panel.TableGroups], ["WELLS", "DAILY", "OTHER"])
        self.assertEqual([g.Visible for g in self.panel.TableGroups], [True, True, False])
        self.assertEqual(self.log, ["OK filters Bit Data: 2 table(s) with 2 filter(s) shown, 1 other table(s) "
                                    "hidden"])

    def test_a_new_filter_gets_one_handle(self):
        late = TableGroup("LATE", ["A", "B"])
        late.FilterCollectionReference = SyncingCollection(late)
        late.FilterCollectionReference.DataTableReference.Columns["C"] = "C"   # no filter, no handle yet
        panel = Panel([late])
        shown = self.scope["filter_table"](panel, {"table": "LATE", "columns": ["C", "A"]}, 0)
        self.assertEqual(shown, 2)
        self.assertEqual(labels(late), [("C", True), ("A", True), ("B", False)])   # one handle for C

    def test_missing_column_is_left_out_with_a_note(self):
        ps = {"title": "Bit Data", "filters": [{"table": "WELLS", "columns": ["Well", "Gone"],
                                                "groups": [["Empty", ["Lost"]], ["Bit Data", ["ROP", "Lost"]]]}]}
        page = type("Page", (), {"FilterPanel": self.panel})()
        self.scope["filter_layout"](page, ps)
        self.assertEqual(labels(self.wells)[:2], [("Well", True), ("[Bit Data]", True)])
        self.assertIsNone(self.wells.GetSubGroup("Empty"))                    # nothing to put in it
        self.assertEqual(labels(self.wells.GetSubGroup("Bit Data")), [("ROP", True)])
        self.assertEqual(self.log, ["NOTE filters WELLS: no column Lost, Gone in the table, left out",
                                    "NOTE filters Bit Data: 1 table(s) with 2 filter(s) shown, 2 other table(s) "
                                    "hidden"])

    def test_missing_table_is_a_failed_line(self):
        ps = {"title": "P", "filters": [{"table": "GONE", "columns": ["A"]}]}
        page = type("Page", (), {"FilterPanel": self.panel})()
        self.scope["filter_layout"](page, ps)
        self.assertTrue(self.log[0].startswith("FAILED filters P/GONE: the filter panel has no group"))
        self.assertTrue(self.log[-1].startswith("NOTE filters P:"))

    def test_filter_type_on_the_default_scheme(self):
        coll = Collection(["Well", "Depth"])
        coll.DataTableReference.Columns["Rate"] = "Rate"                  # a column without a filter yet
        scheme = {"table-object": coll}
        self.scope["T"]["DAILY"] = "table-object"
        self.scope["Document"] = type("D", (), {"FilteringSchemes": type("S", (), {
            "DefaultFilteringSchemeReference": scheme})()})()
        self.scope["filter_type"]("DAILY", "Depth", "RangeFilter")
        self.assertEqual(coll["Depth"].TypeId, "id:RangeFilter")
        self.scope["filter_type"]("DAILY", "Rate", "TextFilter")         # no filter yet: made, then typed
        self.assertEqual(coll["Rate"].TypeId, "id:TextFilter")


class TrellisEngineTests(unittest.TestCase):
    def setUp(self):
        self.scope = {"TrellisMode": type("TM", (), {"Panels": "Panels", "RowsColumns": "RowsColumns"}),
                      "IndividualScalingMode": type("ISM", (), {"Trellis": "Trellis", "Color": "Color"})}
        tp.part_scope("builders/_chart.py", {"trellis"}, self.scope)

    def chart(self):
        axis = lambda: type("A", (), {"Expression": ""})()             # noqa: E731
        trellis = type("Tr", (), {})()
        trellis.PanelAxis, trellis.RowAxis, trellis.ColumnAxis = axis(), axis(), axis()
        trellis.TrellisMode, trellis.ManualLayout = "RowsColumns", False
        trellis.ManualRowCount = trellis.ManualColumnCount = 2
        chart = type("C", (), {})()
        chart.Trellis, chart.YAxis = trellis, type("Y", (), {"IndividualScaling": False})()
        return chart

    def test_panels_with_a_fixed_grid(self):
        c = self.chart()
        self.scope["trellis"](c, {"panel": "<[Well Name]>", "rows": 3, "columns": 4})
        t = c.Trellis
        self.assertEqual((t.TrellisMode, t.PanelAxis.Expression, t.ManualRowCount, t.ManualColumnCount,
                          t.ManualLayout), ("Panels", "<[Well Name]>", 3, 4, True))

    def test_rows_and_columns(self):
        c = self.chart()
        self.scope["trellis"](c, {"columnsBy": "<[Well Name]>"})
        self.assertEqual((c.Trellis.TrellisMode, c.Trellis.ColumnAxis.Expression, c.Trellis.ManualLayout),
                         ("RowsColumns", "<[Well Name]>", False))

    def test_individual_scaling(self):
        c = self.chart()
        self.scope["y_each"](c, True)
        self.assertEqual((c.YAxis.IndividualScaling, c.YAxis.IndividualScalingMode), (True, "Trellis"))
        self.scope["y_each"](c, False)
        self.assertEqual(c.YAxis.IndividualScalingMode, "Color")


# ------------------------------------------------------------------------------------------------
# verify_dxp: reading the saved organization and comparing it with the spec
# ------------------------------------------------------------------------------------------------
class FilterVerifyTests(unittest.TestCase):
    def checker(self, spec):
        c = object.__new__(V.Checker)
        c.R = V.Results()
        c.dxpgen = dxpgen
        c.spec = spec
        c.report = None
        return c

    def model_page(self, wells_visible=True, order=("Well", "Rig"), rig_type="CheckBoxFilter"):
        items = [{"kind": "filter", "column": order[0], "visible": True, "type": "ListBoxFilter"},
                 {"kind": "filter", "column": order[1], "visible": True, "type": rig_type},
                 {"kind": "group", "name": "Bit Data", "visible": True, "expanded": False,
                  "items": [{"kind": "filter", "column": "ROP", "visible": True, "type": "RangeFilter"}]},
                 {"kind": "filter", "column": "Notes", "visible": False, "type": "TextFilter"}]
        return {"filterLayout": [
            {"table": "WELLS", "visible": True, "expanded": True, "items": items},
            {"table": "OTHER", "visible": not wells_visible, "expanded": True, "items": []}]}

    def spec(self):
        layout = {"tables": [{"table": "WELLS", "columns": ["Well", "Rig"],
                              "filterTypes": {"Well": "ListBoxFilter"},
                              "subGroups": [{"name": "Bit Data", "columns": ["ROP"], "expanded": False}]}]}
        return {"filterPanelLayout": layout, "pages": [{"title": "Wells"}, {"title": "All", "filters": "all"}]}

    def statuses(self, c):
        return [(i["status"], i["check"]) for i in c.R.items]

    def test_matching_organization_passes(self):
        spec = self.spec()
        c = self.checker(spec)
        c.check_filter_layout("pages[0]", spec["pages"][0], self.model_page())
        self.assertTrue(c.R.items)
        self.assertEqual([s for s in self.statuses(c) if s[0] != "PASS"], [])
        c2 = self.checker(spec)
        c2.check_filter_layout("pages[1]", spec["pages"][1], self.model_page())
        self.assertEqual(c2.R.items, [])                                # "all": not checked

    def test_differences_fail(self):
        spec = self.spec()
        c = self.checker(spec)
        c.check_filter_layout("pages[0]", spec["pages"][0], self.model_page(wells_visible=False,
                                                                             order=("Rig", "Well")))
        failed = [s[1] for s in self.statuses(c) if s[0] == "FAIL"]
        self.assertIn("filter panel tables shown, in order", failed)
        self.assertIn("filters shown, in order", failed)
        c = self.checker(spec)
        page = self.model_page()
        page["filterLayout"][0]["items"][0]["type"] = "CheckBoxFilter"
        c.check_filter_layout("pages[0]", spec["pages"][0], page)
        self.assertEqual([s[1] for s in self.statuses(c) if s[0] == "FAIL"], ["filter type"])

    def test_trellis_check(self):
        spec = {"pages": [{"title": "P", "visuals": [
            {"id": "a", "type": "lineChart", "title": "Rate", "trellis": {"panelBy": "<[W]>", "rows": 2, "columns": 3},
             "yScale": {"individualScaling": True}},
            {"id": "b", "type": "barChart", "title": "Depth", "trellis": {"columnsBy": "<[W]>"}}]}]}
        c = self.checker(spec)
        c.model = {"pages": [{"id": "p1", "title": "P", "order": 0, "charts": [
            {"guid": "g1", "title": "Rate", "content": "LineChart", "yIndividual": [True, "Trellis"],
             "trellis": {"mode": "Panels", "manual": True, "rows": 2, "columns": 3}},
            {"guid": "g2", "title": "Depth", "content": "BarChart", "yIndividual": [False, "Color"],
             "trellis": {"mode": "Panels", "manual": False, "rows": 2, "columns": 2}}]}]}
        c.check_trellis()
        result = dict(((i["path"], i["check"]), i["status"]) for i in c.R.items)
        self.assertEqual(result[('pages "P" > a', "trellis mode")], "PASS")
        self.assertEqual(result[('pages "P" > a', "trellis rows")], "PASS")
        self.assertEqual(result[('pages "P" > a', "y axis individual scaling")], "PASS")
        self.assertEqual(result[('pages "P" > b', "trellis mode")], "FAIL")


class SpecHelpersTests(unittest.TestCase):
    def test_page_layout_resolution(self):
        spec = {"filterPanelLayout": {"tables": []}, "pages": [{"title": "A"}, {"title": "B", "filters": "all"},
                                                               {"title": "C", "filters": {"tables": [
                                                                   {"table": "T", "columns": "*"}]}}]}
        self.assertEqual(dxpgen.page_filter_layout(spec, spec["pages"][0]), [])
        self.assertIsNone(dxpgen.page_filter_layout(spec, spec["pages"][1]))
        self.assertEqual(dxpgen.page_filter_layout(spec, spec["pages"][2])[0]["columns"], "*")
        pages, types = _filters.app_keys(spec)
        self.assertEqual(pages, {"A": [], "C": [{"table": "T", "columns": "*"}]})
        self.assertEqual(types, [])


if __name__ == "__main__":
    unittest.main()
