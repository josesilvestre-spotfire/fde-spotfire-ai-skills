"""Tests for the standard engine's visualization mods: engine/builders/mod.py (kind "mod": the main view
and its layers), engine/features/modload.py (load_viz: a mod embedded, installed or pinned) and the
core/report blocks of feature vizMods.

Run: python -m unittest tests/test_mod_engine.py   (or python -m unittest discover -s tests)

The engine functions run in CPython with stand-ins for Spotfire's objects (the part_scope pattern of
test_kitchen_features / test_pipeline_kinds): build order (table before axes, Layers.Clear before
AddLayer, the layer marking always set), axis clearing, the color axis, typed properties with read
back, the placeholder when the mod is not in the analysis, and the load_viz routes. The feature
blocks are checked to leave every builder without a mod visual as it was. Nothing starts Spotfire.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
import t3  # noqa: E402
from t3 import _assemble  # noqa: E402


def part_code(rel, features):
    path = t3.ENGINE_DIR / rel
    part = _assemble.Part(path.stem, path, path.read_text(encoding="utf-8"), "standard", features)
    return "\n".join(part.code)


def run_part(rel, features, scope):
    exec(compile(part_code(rel, features), rel, "exec"), scope)
    return scope


def core_functions(names, features, scope):
    """Only the named function definitions of core.py (its build runs at module level)."""
    tree = ast.parse(part_code("core.py", features))
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=keep, type_ignores=[]), "core.py", "exec"), scope)
    return scope


# ------------------------------------------------------------------------------------------------
# stand-ins
# ------------------------------------------------------------------------------------------------
class ModVisualization(object):
    pass


class HtmlTextArea(object):
    pass


class Behavior(object):
    ShowAll, ShowEmpty, ShowMessage = "ShowAll", "ShowEmpty", "ShowMessage"


class Recorder(object):
    """Records every attribute set as (owner name, attribute, value) in a shared list."""

    def __init__(self, events, label):
        object.__setattr__(self, "_events", events)
        object.__setattr__(self, "_label", label)

    def __setattr__(self, name, value):
        self._events.append((self._label, name, value))
        object.__setattr__(self, name, value)


class Selections(list):
    def Contains(self, m):
        return m in self

    def Add(self, m):
        self.append(m)


class Data(Recorder):
    def __init__(self, events, label):
        Recorder.__init__(self, events, label + ".Data")
        object.__setattr__(self, "Filterings", Selections())
        object.__setattr__(self, "WhereClauseExpression", None)
        object.__setattr__(self, "MarkingReference", "default marking")


class Axis(Recorder):
    def __init__(self, events, label, name, refuse=()):
        Recorder.__init__(self, events, label + "." + name)
        object.__setattr__(self, "Name", name)
        object.__setattr__(self, "Expression", "")
        object.__setattr__(self, "_refuse", refuse)

    def __setattr__(self, name, value):
        if name == "Expression" and value in self._refuse:
            raise Exception("refused " + repr(value))
        Recorder.__setattr__(self, name, value)


class Prop(object):
    def __init__(self, value, back=None):
        self._value = value
        self._back = back

    @property
    def Value(self):
        return self._value if self._back is None else self._back

    @Value.setter
    def Value(self, value):
        self._value = value


class View(Recorder):
    """A main view or a layer: Data, axes, typed properties."""

    def __init__(self, events, label, axes=(), props=None, color=False, valid=True):
        Recorder.__init__(self, events, label)
        object.__setattr__(self, "Data", Data(events, label))
        object.__setattr__(self, "_axes", dict((a, Axis(events, label, a)) for a in axes))
        object.__setattr__(self, "AxesNames", list(axes))
        object.__setattr__(self, "HasColorAxis", color)
        object.__setattr__(self, "ColorAxis", Axis(events, label, "ColorAxis") if color else None)
        object.__setattr__(self, "_props", props or {})
        object.__setattr__(self, "_valid", valid)
        object.__setattr__(self, "Title", label)
        object.__setattr__(self, "Legend", Recorder(events, label + ".Legend"))
        view = self

        class Typed(object):
            def __getitem__(self, net_type):
                def get(name):
                    found = view._props.get(name)
                    if found is None or found[0] is not net_type:
                        return None
                    return found[1]
                return get
        object.__setattr__(self, "Property", Typed())

    @property
    def Axes(self):
        return list(self._axes.values())

    def Axis(self, name):
        return self._axes.get(name)

    def IsConfigurationValid(self):
        return self._valid


class Layers(object):
    def __init__(self, events, kinds, keep_title=True):
        self.events, self.kinds, self.keep_title = events, kinds, keep_title
        self.items = []

    def Clear(self):
        self.events.append(("Layers", "Clear", None))
        self.items = []

    def AddLayer(self, layer_type, title):
        self.events.append(("Layers", "AddLayer", (layer_type, title)))
        axes, props = self.kinds[layer_type]
        layer = View(self.events, "layer:" + title, axes, dict(props))
        if not self.keep_title:
            object.__setattr__(layer, "Title", layer_type)
        self.items.append(layer)
        return layer


class Markings(object):
    def __init__(self, names):
        self.names = names

    def TryGetValue(self, name):
        return (True, "marking:" + name) if name in self.names else (False, None)


def doc(markings=("Marking", "Event Pick"), listed=()):
    mm = type("MM", (), {"GetVisualizationModsIncludingPinned": lambda self: list(listed)})()
    data = type("D", (), {"Markings": Markings(markings)})()
    return type("Doc", (), {"Data": data, "ModManager": mm})()


def ok_factory(log):
    def ok(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            log.append("FAILED " + name + ": " + str(e))
            return None
    return ok


def mod_scope(events, log, viz=None, markings=("Marking", "Event Pick")):
    scope = {"LOG": log, "ok": ok_factory(log), "why": str, "T": {"READINGS": "t:READINGS", "EVENTS": "t:EVENTS"},
             "MARK": "marking:Marking", "Document": doc(markings), "VIZ": dict(viz or {}),
             "VIZ_FIX": "make it available", "BUILDERS": {}, "TYPE_IDS": {},
             "ModVisualization": ModVisualization, "HtmlTextArea": HtmlTextArea,
             "LimitingMarkingsEmptyBehavior": Behavior, "String": str, "Int32": int, "Double": float,
             "Boolean": bool, "Array": None, "Type": None, "clr": None}

    def legend(content, vs):
        content.Legend.Visible = bool(vs.get("legend", True))
    scope["legend"] = legend
    return run_part("builders/mod.py", {"vizMods"}, scope)


SERIES = (("X", "Values", "Series", "Bin"), {"role": (str, Prop("")), "lineWidth": (float, Prop(1.0)),
                                             "visible": (bool, Prop(True))})
RECORDS = (("Key", "Attributes", "Values"), {"role": (str, Prop(""))})


def mod_visual(events, keep_title=True):
    mv = View(events, "main", (), {"heading": (str, Prop("Layers")), "showGrid": (bool, Prop(False)),
                                   "lineWidth": (float, Prop(1.0)), "maxRows": (int, Prop(1000))})
    object.__setattr__(mv, "Layers", Layers(events, {"Series": SERIES, "Records": RECORDS}, keep_title))
    visual = type("V", (), {"As": {ModVisualization: lambda: mv}})()
    return mv, visual


APP_VISUAL = {
    "id": "demoLayers", "type": "mod", "title": "Readings and events", "mod": "demo-layers", "table": "READINGS",
    "props": [["heading", "string", "Pump readings"], ["showGrid", "boolean", True], ["lineWidth", "double", 1.5],
              ["maxRows", "integer", 5000]],
    "layers": [
        {"type": "Series", "title": "Readings", "table": "READINGS", "marking": None,
         "where": "[Asset] = \"${ViewAsset}\"",
         "axes": {"Series": "<[Axis.Default.Names]>", "X": "[Timestamp]",
                  "Values": "[Pressure (psig)], [Flow (bbl/d)]"},
         "props": [["role", "string", "raw"], ["lineWidth", "double", 1.0]]},
        {"type": "Series", "title": "Daily range", "table": "READINGS", "marking": None, "filtering": False,
         "where": "[Asset] = \"${ViewAsset}\"",
         "axes": {"X": "Min([Timestamp])", "Bin": ""},
         "props": [["role", "string", "binned"], ["visible", "boolean", False]]},
        {"type": "Records", "title": "Events", "table": "EVENTS", "marking": "Event Pick",
         "limits": ["Marking"], "empty": "ShowMessage",
         "axes": {"Key": "<[Event ID]>", "Attributes": "<[Asset] NEST [Start]>", "Values": "Max([Severity])"},
         "props": [["role", "string", "events"]]}],
    "legend": False}


# ------------------------------------------------------------------------------------------------
# builders/mod.py
# ------------------------------------------------------------------------------------------------
class ModBuilderTests(unittest.TestCase):
    def build(self, vs=None, keep_title=True):
        events, log = [], []
        scope = mod_scope(events, log)
        mv, visual = mod_visual(events, keep_title)
        scope["build_mod"](visual, vs or APP_VISUAL)
        return scope, mv, events, log

    def test_registration(self):
        scope = mod_scope([], [])
        self.assertIs(scope["BUILDERS"]["mod"], scope["build_mod"])
        self.assertEqual(scope["TYPE_IDS"]["mod"], "HtmlTextArea")

    def test_main_view_layers_and_order(self):
        scope, mv, events, log = self.build()
        self.assertEqual(log, [])
        self.assertEqual(mv.Data.DataTableReference, "t:READINGS")
        self.assertEqual([(p[0], mv.Property[t](p[0]).Value) for p, t in
                          zip(APP_VISUAL["props"], (str, bool, float, int))],
                         [("heading", "Pump readings"), ("showGrid", True), ("lineWidth", 1.5),
                          ("maxRows", 5000)])
        self.assertIs(mv.Legend.Visible, False)
        calls = [e for e in events if e[0] == "Layers"]
        self.assertEqual(calls[0], ("Layers", "Clear", None))       # Clear before every AddLayer
        self.assertEqual([c[2] for c in calls[1:]], [("Series", "Readings"), ("Series", "Daily range"),
                                                     ("Records", "Events")])
        readings, daily, records = mv.Layers.items
        # the table is set before any axis of the layer
        first_axis = min(i for i, e in enumerate(events) if e[0].startswith("layer:Readings.") and
                         e[1] == "Expression")
        table = [i for i, e in enumerate(events) if e[0] == "layer:Readings.Data" and e[1] == "DataTableReference"]
        self.assertTrue(table and table[0] < first_axis)
        # the axes follow the mod's own order (AxesNames), not the APP dict order
        order = [e[0].split(".")[1] for e in events if e[0].startswith("layer:Readings.") and e[1] == "Expression"]
        self.assertEqual(order, ["X", "Values", "Series"])
        self.assertEqual(readings.Axis("Values").Expression, "[Pressure (psig)], [Flow (bbl/d)]")
        self.assertEqual(readings.Data.WhereClauseExpression, "[Asset] = \"${ViewAsset}\"")
        self.assertEqual(readings.Property[float]("lineWidth").Value, 1.0)
        # marking always set: None stays None (AddLayer leaves layers unmarked), names are looked up
        self.assertIsNone(readings.Data.MarkingReference)
        self.assertIn(("layer:Readings.Data", "MarkingReference", None), events)
        self.assertEqual(records.Data.MarkingReference, "marking:Event Pick")
        self.assertEqual(list(records.Data.Filterings), ["marking:Marking"])
        self.assertEqual(records.Data.LimitingMarkingsEmptyBehavior, "ShowMessage")
        self.assertIs(daily.Data.UseActiveFiltering, False)
        self.assertFalse(hasattr(readings.Data, "UseActiveFiltering"))
        self.assertIs(daily.Property[bool]("visible").Value, False)

    def test_layer_marking_absent_is_the_default_marking(self):
        vs = dict(APP_VISUAL, layers=[{"type": "Records", "title": "Events", "table": "EVENTS"}])
        scope, mv, events, log = self.build(vs)
        self.assertEqual(mv.Layers.items[0].Data.MarkingReference, "marking:Marking")

    def test_no_layers_key_keeps_the_mods_own_layers(self):
        vs = dict(APP_VISUAL)
        del vs["layers"]
        scope, mv, events, log = self.build(vs)
        self.assertNotIn(("Layers", "Clear", None), events)
        self.assertEqual(log, [])

    def test_no_legend_key_keeps_the_manifest_default(self):
        vs = dict(APP_VISUAL)
        del vs["legend"]
        scope, mv, events, log = self.build(vs)
        self.assertFalse(hasattr(mv.Legend, "Visible"))

    def test_title_set_again_when_addlayer_does_not_keep_it(self):
        scope, mv, events, log = self.build(keep_title=False)
        self.assertEqual([x.Title for x in mv.Layers.items], ["Readings", "Daily range", "Events"])

    def test_axis_clear_and_refused_clear(self):
        events, log = [], []
        scope = mod_scope(events, log)
        view = View(events, "v", ("Bin", "X"))
        object.__setattr__(view._axes["Bin"], "_refuse", ("",))
        scope["mod_axis_set"](view, "Bin", "")
        self.assertEqual(view.Axis("Bin").Expression, "<>")        # "" refused -> "<>"
        scope["mod_axis_set"](view, "X", "")
        self.assertEqual(view.Axis("X").Expression, "")

    def test_axis_read_back_and_lookup(self):
        events, log = [], []
        scope = mod_scope(events, log)
        view = View(events, "v", ("X",), color=True)
        view._axes["x2"] = Axis(events, "v", "Lower")                # found by name through Axes
        scope["mod_axis_set"](view, "Color", "[Asset]")
        self.assertEqual(view.ColorAxis.Expression, "[Asset]")
        scope["mod_axis_set"](view, "lower", "Sum([A])")
        self.assertEqual(view._axes["x2"].Expression, "Sum([A])")
        scope["mod_axis_set"](view, "X", "Sum( [A] )")              # whitespace and case aside
        with self.assertRaises(Exception) as cm:
            scope["mod_axis_set"](view, "Nope", "[A]")
        self.assertIn("no axis Nope (axes: X)", str(cm.exception))

        class Sticky(Axis):
            def __setattr__(self, name, value):
                if name == "Expression":
                    value = "[Other]"
                Axis.__setattr__(self, name, value)
        view._axes["X"] = Sticky(events, "v", "X")
        with self.assertRaises(Exception) as cm:
            scope["mod_axis_set"](view, "X", "[A]")
        self.assertIn("reads back [Other]", str(cm.exception))

    def test_typed_properties(self):
        events, log = [], []
        scope = mod_scope(events, log)
        view = View(events, "v", (), {"n": (int, Prop(1)), "d": (float, Prop(0.5)), "s": (str, Prop("")),
                                      "b": (bool, Prop(False)), "bad": (float, Prop(0.0, back=9.0))})
        for p in (["n", "integer", 7], ["d", "double", 2.25], ["s", "string", "{\"a\":1}"],
                  ["b", "boolean", True]):
            scope["mod_prop"](view, p)
        self.assertEqual([view._props[k][1].Value for k in "ndsb"], [7, 2.25, "{\"a\":1}", True])
        with self.assertRaises(Exception) as cm:
            scope["mod_prop"](view, ["n", "string", "x"])               # stored as another type
        self.assertIn("no string property n", str(cm.exception))
        with self.assertRaises(Exception) as cm:
            scope["mod_prop"](view, ["bad", "double", 1.0])
        self.assertIn("reads back 9.0", str(cm.exception))

    def test_check_notes_invalid_views(self):
        events, log = [], []
        scope = mod_scope(events, log)
        mv = View(events, "main", (), valid=False)
        layer = View(events, "Events", (), valid=False)
        scope["mod_check"]("demoLayers", mv, [layer])
        self.assertEqual(log, ["NOTE demoLayers: Spotfire reports these views as not valid: main view, Events"])

    def test_where_without_property_reference_is_noted(self):
        events, log = [], []
        scope = mod_scope(events, log)

        class Strip(Data):
            def __setattr__(self, name, value):
                if name == "WhereClauseExpression":
                    value = value.replace("${ViewAsset}", "Pump A")
                Data.__setattr__(self, name, value)
        view = View(events, "v", ())
        object.__setattr__(view, "Data", Strip(events, "v"))
        scope["mod_data"]("demoLayers: layer Readings", view, {"table": "READINGS", "where": "[A] = \"${ViewAsset}\""})
        self.assertTrue(log and log[0].startswith("NOTE demoLayers: layer Readings: the limiting expression reads "
                                                  "back without ${...}"))
        with self.assertRaises(Exception) as cm:
            scope["mod_data"]("x", view, {"table": "NOPE"})
        self.assertIn("table NOPE is not loaded", str(cm.exception))

    def test_placeholder_when_the_mod_is_not_in_the_analysis(self):
        events, log = [], []
        scope = mod_scope(events, log)
        added = []
        area = Recorder(events, "area")

        def new_visual(page, kind):
            added.append(kind)
            return type("V", (), {"As": {HtmlTextArea: lambda: area}})()
        scope["new_visual"] = new_visual
        scope["TYPE_IDS"]["mod"] = "HtmlTextArea"
        v = scope["new_mod_visual"]("page", APP_VISUAL)
        self.assertEqual(added, ["mod"])
        self.assertIn("[mod: demo-layers]", area.HtmlContent)
        self.assertEqual(scope["MOD_PLACEHOLDERS"], ["demoLayers"])
        self.assertEqual(log, ["TODO demoLayers: placeholder for mod demo-layers; make it available"])
        scope["build_mod"](v, APP_VISUAL)                              # nothing to build on a placeholder
        self.assertNotIn("FAILED", " ".join(log))

    def test_refused_addnew_falls_back_to_the_placeholder(self):
        events, log = [], []
        scope = mod_scope(events, log, viz={"demo-layers": "mid"})
        scope["new_visual"] = lambda page, kind: type("V", (), {"As": {HtmlTextArea: lambda: Recorder([], "a")}})()

        class Page(object):
            class Visuals(object):
                @staticmethod
                def AddNew(mid):
                    raise Exception("untrusted")
        scope["new_mod_visual"](Page, APP_VISUAL)
        self.assertEqual(log[0], "FAILED demoLayers: add mod demo-layers: untrusted")
        self.assertTrue(log[1].startswith("TODO demoLayers: placeholder"))

    def test_addnew_returns_the_visual(self):
        events, log = [], []
        scope = mod_scope(events, log, viz={"demo-layers": "mid"})
        visual = object()

        class Page(object):
            class Visuals(object):
                @staticmethod
                def AddNew(mid):
                    return type("MV", (), {"Visual": visual})()
        self.assertIs(scope["new_mod_visual"](Page, APP_VISUAL), visual)
        self.assertEqual(scope["MOD_PLACEHOLDERS"], [])


# ------------------------------------------------------------------------------------------------
# features/modload.py
# ------------------------------------------------------------------------------------------------
class Mid(object):
    def __init__(self, mod_id, version):
        self.Id, self.Version = mod_id, version


class LoadVizTests(unittest.TestCase):
    def scope(self, listed=()):
        log = []
        mm = type("MM", (), {"GetVisualizationModsIncludingPinned": lambda self: list(listed)})()
        scope = {"LOG": log, "Document": type("Doc", (), {"ModManager": mm})()}
        run_part("features/modload.py", {"vizMods"}, scope)
        return scope, log

    def test_listed_with_the_manifest_version_wins(self):
        scope, log = self.scope(listed=[Mid("other", "1.0.0"), Mid("demo-layers", "1.0.0")])
        self.assertTrue(scope["load_viz"](["demo-layers", "mods\\demo-layers", "1.0.0"]))
        self.assertEqual(scope["VIZ"]["demo-layers"].Version, "1.0.0")
        self.assertEqual(log, ["OK viz mod demo-layers 1.0.0 (embedded or pinned)"])

    def test_another_listed_version_is_used_with_a_note(self):
        scope, log = self.scope(listed=[Mid("demo-layers", "0.9.0")])
        self.assertTrue(scope["load_viz"](["demo-layers", "mods\\demo-layers", "1.0.0"]))
        self.assertEqual(scope["VIZ"]["demo-layers"].Version, "0.9.0")
        self.assertEqual(log, ["NOTE viz mod demo-layers: using version 0.9.0 instead of 1.0.0 (the version in "
                               "the project's manifest)"])

    def test_nothing_listed_raises(self):
        scope, log = self.scope()
        with self.assertRaises(Exception) as cm:
            scope["load_viz"](["demo-layers", "mods\\demo-layers", "1.0.0"])
        self.assertIn("not embedded, installed or pinned", str(cm.exception))
        self.assertNotIn("demo-layers", scope["VIZ"])
        self.assertIn("pin or install it in your library", scope["VIZ_FIX"])

    def test_no_version_takes_any_listed(self):
        scope, log = self.scope(listed=[Mid("demo-layers", "3.0.0")])
        scope["load_viz"](["demo-layers", "mods\\demo-layers"])
        self.assertEqual(log, ["OK viz mod demo-layers 3.0.0 (embedded or pinned)"])

    def test_public_api_only(self):
        code = (t3.ENGINE_DIR / "features" / "modload.py").read_text(encoding="utf-8")
        for word in ("TryCreateWithOrigin", "SigningService", "icall", "istatic", "NonPublic", "@internal"):
            self.assertNotIn(word, code)


# ------------------------------------------------------------------------------------------------
# feature blocks: builders without a mod visual are unchanged
# ------------------------------------------------------------------------------------------------
class FeatureBlockTests(unittest.TestCase):
    VIZ_NAMES = ("load_viz", "viz_listed", "viz_identifier", "VIZ_FIX", "new_mod_visual", "MOD_PLACEHOLDERS",
                 "ModIdentifier", "VisualizationMod", "visualization mods")

    def test_modload_for_viz_mods_only(self):
        code = part_code("features/modload.py", {"vizMods"})
        names = [n.name for n in ast.parse(code).body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(names, ["viz_listed", "load_viz"])
        for name in ("MOD_FIX", "AM_SC", "AM_ACT", "\nMODS = ", "CONFIGS", "load_mod", "from_file",
                     "from_project", "NOTE action mod"):
            self.assertNotIn(name, code)

    def test_core_and_report_blocks(self):
        for rel in ("core.py", "report.py"):
            off = part_code(rel, {"links", "settings", "legendHide"})
            for name in self.VIZ_NAMES:
                self.assertNotIn(name, off, rel)
            on = part_code(rel, {"vizMods"})
            self.assertIn("load_viz", on, rel)

    def test_core_build_visual_skips_the_links_of_a_placeholder(self):
        log, done = [], []
        scope = {"LOG": log, "ok": ok_factory(log), "VIS": {}, "MOD_PLACEHOLDERS": ["demoLayers"]}
        for name in ("set_title", "run_builder", "data_links", "visual_settings", "hide_legend_items"):
            scope[name] = (lambda n: lambda *a: done.append(n))(name)
        scope["new_visual"] = lambda page, kind: done.append("new_visual") or "text area"
        scope["new_mod_visual"] = lambda page, vs: done.append("new_mod_visual") or "placeholder"
        core_functions(("build_visual",), {"vizMods", "links", "settings", "legendHide"}, scope)
        vs = {"id": "demoLayers", "type": "mod", "marking": None, "settings": {"A": 1}, "legendHide": ["marking"]}
        self.assertTrue(scope["build_visual"]("page", vs))
        self.assertEqual(done, ["new_mod_visual", "set_title", "run_builder"])
        del done[:]
        scope["MOD_PLACEHOLDERS"] = []
        scope["build_visual"]("page", vs)
        self.assertEqual(done, ["new_mod_visual", "set_title", "run_builder", "data_links", "visual_settings",
                                "hide_legend_items"])
        del done[:]
        scope["build_visual"]("page", {"id": "t", "type": "table"})
        self.assertEqual(done[0], "new_visual")


if __name__ == "__main__":
    unittest.main(verbosity=2)
