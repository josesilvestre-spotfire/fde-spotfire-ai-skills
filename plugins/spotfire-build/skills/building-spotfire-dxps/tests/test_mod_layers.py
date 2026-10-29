"""Tests for visualization mods with layers in the standard engine: the vizMods spec section, the mod
visual and its layers (dxpgen validate), the spec -> APP converter (scripts/t3/mod.py, _sections, the t3
wiring), the customer-ready text of a mod project, the release copy and the slim tier refusal.

Run: python -m unittest tests/test_mod_layers.py   (or python -m unittest discover -s tests)

The fixture app (temporary folder) mirrors assets/examples/mod-layers-demo: two SBDF tables (headers
only), a tiny visualization mod with two layer types, a tiny action mod, one mod visual with three layers
on two tables and a FloatingButton action trigger (a manual step: no public API adds it). The tests that generate a whole builder need the engine
parts (engine/builders/mod.py, engine/features/modload.py) and are skipped without them. Nothing starts
Spotfire.
"""
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import slim_builder  # noqa: E402
import t3  # noqa: E402
import textlint  # noqa: E402
from t3 import _sections, mod as t3mod  # noqa: E402
from t3._common import Context  # noqa: E402
from test_columns import sbdf_header, STRING, REAL  # noqa: E402

DATETIME = 6
META = {"spec_sha": "0" * 64, "generated": "2026-10-20T00:00:00"}
MOD_BUILDER = t3.ENGINE_DIR / "builders" / "mod.py"
MODLOAD = t3.ENGINE_DIR / "features" / "modload.py"
ENGINE_READY = MOD_BUILDER.is_file() and MODLOAD.is_file()

AXIS_NONE = {"expressionHeuristics": "none"}
VIZ_MANIFEST = {
    "apiVersion": "2.4", "version": "1.0.0", "name": "Layer demo", "id": "demo-layers", "icon": "icon.svg",
    "type": "visualization",
    "description": "Shows each layer of the visual with its rows, marking and settings.",
    "properties": [{"name": "heading", "type": "string", "defaultValue": ""},
                   {"name": "showGrid", "type": "boolean", "defaultValue": True},
                   {"name": "lineWidth", "type": "double", "defaultValue": 1.0},
                   {"name": "maxRows", "type": "integer", "defaultValue": 10000}],
    "dataViewDefinition": {"tooltip": {"enabled": False}},
    "legend": {"defaultPlacement": "right", "defaultVisibility": "hidden"},
    "layers": [
        {"type": "Series",
         "properties": [{"name": "role", "type": "string", "defaultValue": ""},
                        {"name": "lineWidth", "type": "double", "defaultValue": 1.0},
                        {"name": "visible", "type": "boolean", "defaultValue": True}],
         "dataViewDefinition": {"axes": [
             {"name": "X", "mode": "continuous", "propertyControl": {"title": "Time"},
              "automaticConfiguration": AXIS_NONE},
             {"name": "Values", "mode": "continuous", "allowMultipleMeasures": True,
              "propertyControl": {"title": "Values"}, "automaticConfiguration": AXIS_NONE},
             {"name": "Series", "mode": "categorical", "optional": True, "automaticConfiguration": AXIS_NONE},
             {"name": "Bin", "mode": "categorical", "optional": True, "automaticConfiguration": AXIS_NONE}]}},
        {"type": "Records",
         "properties": [{"name": "role", "type": "string", "defaultValue": ""}],
         "dataViewDefinition": {"axes": [
             {"name": "Key", "mode": "categorical",
              "automaticConfiguration": {"expressionHeuristics": {"expression": "<baserowid()>"}}},
             {"name": "Attributes", "mode": "categorical", "optional": True, "automaticConfiguration": AXIS_NONE},
             {"name": "Values", "mode": "continuous", "optional": True,
              "automaticConfiguration": AXIS_NONE}]}}],
    "files": ["index.html", "main.css", "main.js", "icon.svg"]}
ACTION_MANIFEST = {
    "apiVersion": "2.1", "version": "1.0.0", "type": "action", "id": "demo-layers-actions",
    "name": "Layer demo actions", "icon": "icon.svg",
    "scripts": [{"id": "next-asset", "name": "Next asset", "file": "build/next-asset.js", "entryPoint": "nextAsset",
                 "parameters": [{"name": "Assets", "type": "String",
                                 "description": "Comma-separated assets to step through"}]}]}
FILES = {
    "data/READINGS.sbdf": sbdf_header([("Asset", STRING), ("Timestamp", DATETIME), ("Pressure (psig)", REAL),
                                       ("Flow (bbl/d)", REAL)]),
    "data/EVENTS.sbdf": sbdf_header([("Event ID", STRING), ("Asset", STRING), ("Start", DATETIME),
                                     ("End", DATETIME), ("Severity", REAL)]),
    "mods/demo-layers/mod-manifest.json": json.dumps(VIZ_MANIFEST, indent=2),
    "mods/demo-layers/index.html": "<html><body><div id=\"mod-container\"></div></body></html>\n",
    "mods/demo-layers/main.css": "/* Card layout of the layers */\n.card { margin: 4px; }\n",
    "mods/demo-layers/main.js": "// Renders one card per layer.\nSpotfire.initialize(function (mod) {});\n",
    "mods/demo-layers/icon.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>",
    "mods/demo-layers/node_modules/pkg/index.js": "module.exports = 1;\n",
    "actionmod/mod-manifest.json": json.dumps(ACTION_MANIFEST, indent=2),
    "actionmod/build/next-asset.js": "function nextAsset(a) {}\nRegisterEntryPoint(nextAsset);\n",
    "actionmod/icon.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>",
}
WHERE = "[Asset] = \"${ViewAsset}\""
BIN = "<BinByDateTime([Timestamp],\"Year.Quarter.Month.Day.Hour\",${BinLevel})>"


def demo_visual():
    return {
        "id": "demoLayers", "type": "mod", "modId": "demo-layers", "title": "Readings and events",
        "table": "READINGS", "marking": None, "legend": {"visible": False},
        "properties": {"heading": "Pump readings", "showGrid": True, "lineWidth": 1.5, "maxRows": 5000},
        "layers": [
            {"type": "Series", "title": "Readings", "table": "READINGS", "marking": None, "limitExpression": WHERE,
             "axes": {"X": "Timestamp", "Values": ["Pressure (psig)", "Flow (bbl/d)"],
                      "Series": "<[Axis.Default.Names]>"},
             "properties": {"role": "raw", "lineWidth": 1}},
            {"type": "Series", "title": "Daily range", "table": "READINGS", "marking": None,
             "limitExpression": WHERE, "useFiltering": False,
             "axes": {"X": "Min([Timestamp])",
                      "Values": ["Min([Pressure (psig)]) as [Pressure min]",
                                 "Max([Pressure (psig)]) as [Pressure max]"],
                      "Series": "<[Axis.Default.Names]>", "Bin": BIN},
             "properties": {"role": "binned", "visible": True}},
            {"type": "Records", "title": "Events", "table": "EVENTS", "marking": "Event Pick",
             "limitExpression": WHERE,
             "axes": {"Key": "<[Event ID]>", "Attributes": ["Asset", "Start", "End"], "Values": "Max([Severity])"},
             "properties": {"role": "events"}}],
        "actionTriggers": [{"display": "FloatingButton",
                            "actionMod": {"mod": "demo-layers-actions", "script": "next-asset",
                                          "args": {"Assets": "Pump A,Pump B"}}}]}


def demo_spec():
    return {
        "specVersion": 1,
        "app": {"name": "Mod Layers Demo", "minimumSpotfireVersion": "15.0",
                "description": "Pump readings and events in one visual with three layers."},
        "tables": [{"name": "READINGS", "source": {"type": "sbdf", "path": "data/READINGS.sbdf"}},
                   {"name": "EVENTS", "source": {"type": "sbdf", "path": "data/EVENTS.sbdf"}}],
        "defaultTable": "READINGS",
        "markings": [{"name": "Marking", "default": True}, {"name": "Event Pick", "color": "#E94165"}],
        "properties": [{"name": "ViewAsset", "type": "String", "default": "Pump A",
                        "description": "Asset the layers show"},
                       {"name": "BinLevel", "type": "LongInteger", "default": 3,
                        "description": "Time bin of the Daily range layer: 3 day, 4 hour"}],
        "vizMods": [{"id": "demo-layers", "project": "mods/demo-layers"}],
        "actionMods": [{"id": "demo-layers-actions", "project": "actionmod"}],
        "pages": [{"title": "Layers", "visuals": [
            demo_visual(),
            {"id": "eventTable", "type": "table", "title": "Marked events", "table": "EVENTS",
             "columns": ["Event ID", "Asset", "Start", "End", "Severity"], "limitByMarkings": ["Event Pick"],
             "emptyMarkingBehavior": "ShowMessage", "marking": None}],
            "layout": {"row": [{"visual": "demoLayers", "weight": 70}, {"visual": "eventTable", "weight": 30}]}}]}


EXPECTED_LAYERS = [
    {"type": "Series", "title": "Readings", "table": "READINGS", "marking": None, "where": WHERE,
     "axes": {"X": "[Timestamp]", "Values": "[Pressure (psig)], [Flow (bbl/d)]",
              "Series": "<[Axis.Default.Names]>"},
     "props": [["role", "string", "raw"], ["lineWidth", "double", 1.0]]},
    {"type": "Series", "title": "Daily range", "table": "READINGS", "marking": None, "where": WHERE,
     "filtering": False,
     "axes": {"X": "Min([Timestamp])",
              "Values": "Min([Pressure (psig)]) as [Pressure min], Max([Pressure (psig)]) as [Pressure max]",
              "Series": "<[Axis.Default.Names]>", "Bin": BIN},
     "props": [["role", "string", "binned"], ["visible", "boolean", True]]},
    {"type": "Records", "title": "Events", "table": "EVENTS", "marking": "Event Pick", "where": WHERE,
     "axes": {"Key": "<[Event ID]>", "Attributes": "<[Asset] NEST [Start] NEST [End]>",
              "Values": "Max([Severity])"},
     "props": [["role", "string", "events"]]}]
EXPECTED_VISUAL = {
    "id": "demoLayers", "type": "mod", "title": "Readings and events", "mod": "demo-layers", "table": "READINGS",
    "props": [["heading", "string", "Pump readings"], ["showGrid", "boolean", True], ["lineWidth", "double", 1.5],
              ["maxRows", "integer", 5000]],
    "layers": EXPECTED_LAYERS, "legend": False, "marking": None}

@contextlib.contextmanager
def builder_present():
    """The converter runs only when engine/builders/mod.py exists; without it (the engine part not there
    yet) the converter tests stand in another builder file. Nothing reads it."""
    if MOD_BUILDER.is_file():
        yield
        return
    real = t3.builder_path
    with mock.patch.object(t3, "builder_path",
                           lambda kind: real("text") if kind == "mod" else real(kind)):
        yield


class ModTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mod-layers-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, spec=None, files=None, slug="ModLayersDemo"):
        app = self.tmp / "apps" / slug
        for rel, data in (FILES if files is None else files).items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                p.write_bytes(data)
            else:
                p.write_text(data, encoding="utf-8")
        (app / "spec.json").write_text(json.dumps(demo_spec() if spec is None else spec, indent=2),
                                       encoding="utf-8")
        return app

    def generate(self, spec, app, tier="standard"):
        resolved = dxpgen.resolve_spec(spec, app)
        with builder_present():
            return t3.generate(resolved, spec, app, tier, dxpgen.column_reader(resolved), META)

    def build_app(self, spec, app, tier="standard"):
        """APP of one tier without the engine parts (t3.build_app: the converter and the sections)."""
        resolved = dxpgen.resolve_spec(spec, app)
        style, _, _ = t3.compose_style(resolved, [])
        ctx = Context(resolved, spec, Path(app).resolve(), tier, style, dxpgen.column_reader(resolved))
        with builder_present():
            out, _, _ = t3.build_app(resolved, spec, Path(app).resolve(), tier, ctx)
        return out, ctx

    def validate(self, spec, files=None):
        app = self.app(spec, files)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        return report

    @staticmethod
    def messages(report, level="error"):
        items = report.errors if level == "error" else report.warnings if level == "warning" else report.notes
        return [((i.get("path") or ""), i["message"]) for i in items]

    def assert_message(self, report, level, path, fragment):
        found = self.messages(report, level)
        self.assertTrue(any(p == path and fragment in m for p, m in found),
                        "no %s at %s with %r in:\n%s" % (level, path, fragment,
                                                         "\n".join("%s: %s" % x for x in found)))


# ------------------------------------------------------------------------------------------------
# shared helpers of scripts/t3/mod.py
# ------------------------------------------------------------------------------------------------
class AxisTextTests(unittest.TestCase):
    def column(self, text):
        return "[" + text + "]" if text in ("Asset", "Start", "Pressure (psig)") else text

    def expr(self, text):
        return t3._common.PROP_RE.sub(lambda m: 'DocumentProperty("%s")' % m.group(1), text)

    def text(self, value, mode):
        return t3mod.axis_text(value, mode, self.column, self.expr)

    def test_categorical(self):
        self.assertEqual(self.text("<[Event ID]>", "categorical"), "<[Event ID]>")
        self.assertEqual(self.text("Asset", "categorical"), "<[Asset]>")
        self.assertEqual(self.text("[Asset]", "categorical"), "<[Asset]>")
        self.assertEqual(self.text(["Asset", "Start"], "categorical"), "<[Asset] NEST [Start]>")
        self.assertEqual(self.text(["<[Asset]>", "[$Level]"], "categorical"),
                         '<[Asset] NEST DocumentProperty("Level")>')
        self.assertEqual(self.text("<[Axis.Default.Names]>", "categorical"), "<[Axis.Default.Names]>")
        self.assertEqual(self.text(BIN, "categorical"), BIN)

    def test_continuous_and_dual(self):
        for mode in ("continuous", "dual"):
            self.assertEqual(self.text("Pressure (psig)", mode), "[Pressure (psig)]")
            self.assertEqual(self.text("Max([Severity])", mode), "Max([Severity])")
            self.assertEqual(self.text(["Asset", "Avg([X]) as [Mean]"], mode), "[Asset], Avg([X]) as [Mean]")
            self.assertEqual(self.text("[$Limit] * 2", mode), 'DocumentProperty("Limit") * 2')

    def test_clear_and_leave(self):
        for mode in ("categorical", "continuous", "dual"):
            self.assertEqual(self.text("", mode), "")
            self.assertEqual(self.text("  ", mode), "")
            self.assertIsNone(self.text(None, mode))
        self.assertEqual(t3mod.axis_text("Asset", "categorical"), "<Asset>")      # no column helper given

    def test_axis_mode_and_manifest_axes(self):
        self.assertEqual(t3mod.axis_mode({"mode": "categorical"}), "categorical")
        self.assertEqual(t3mod.axis_mode({}), "dual")
        self.assertEqual(list(t3mod.manifest_axes(VIZ_MANIFEST, "Series")), ["X", "Values", "Series", "Bin"])
        self.assertEqual(list(t3mod.manifest_axes(VIZ_MANIFEST)), [])
        man = copy.deepcopy(VIZ_MANIFEST)
        man["dataViewDefinition"]["colorAxis"] = {"mode": "categorical"}
        man["dataViewDefinition"]["axes"] = [{"name": "Y", "mode": "continuous"}]
        axes = t3mod.manifest_axes(man)
        self.assertEqual(list(axes), ["Y", "Color"])
        self.assertEqual(axes["Color"]["mode"], "categorical")
        man["dataViewDefinition"]["colorAxis"] = {}
        self.assertEqual(t3mod.manifest_axes(man)["Color"]["mode"], "dual")
        self.assertEqual(t3mod.layer_types(VIZ_MANIFEST), ["Series", "Records"])
        self.assertIsNone(t3mod.layer_def(VIZ_MANIFEST, "Nope"))
        self.assertEqual(t3mod.manifest_props(VIZ_MANIFEST, "Series"),
                         {"role": "string", "lineWidth": "double", "visible": "boolean"})

    def test_required_unset(self):
        self.assertEqual(t3mod.required_unset(VIZ_MANIFEST, "Series", {}), ["X", "Values"])
        self.assertEqual(t3mod.required_unset(VIZ_MANIFEST, "Series", {"X": "[T]", "Values": None}), ["Values"])
        self.assertEqual(t3mod.required_unset(VIZ_MANIFEST, "Records", {}), [])      # Key configures itself


class PropValueTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(t3mod.prop_value("a", "string"), "a")
        self.assertEqual(t3mod.prop_value({"b": 1, "a": [1, 2]}, "string"), '{"a":[1,2],"b":1}')
        self.assertEqual(t3mod.prop_value(5000, "integer"), 5000)
        self.assertEqual(t3mod.prop_value(3.0, "integer"), 3)
        self.assertIsInstance(t3mod.prop_value(1, "double"), float)
        self.assertEqual(t3mod.prop_value(1.5, "double"), 1.5)
        self.assertIs(t3mod.prop_value(False, "boolean"), False)

    def test_refused(self):
        cases = [(1, "string", "property 'p' is string in the mod's manifest, got a whole number 1"),
                 (True, "integer", "property 'p' is an integer (32-bit), got a boolean true"),
                 (1.5, "integer", "property 'p' is an integer (32-bit), got a number 1.5"),
                 (2 ** 31, "integer", "property 'p' is an integer (32-bit)"),
                 ("1", "double", "property 'p' is double in the mod's manifest, got a string"),
                 (float("nan"), "double", "property 'p' is double"),
                 (1, "boolean", "property 'p' is boolean in the mod's manifest"),
                 ("x" * 102401, "string", "the text has 102401 characters; a mod string property holds at most "
                                          "102400"),
                 ("x", "color", "the builder sets string, integer, double, boolean properties")]
        for value, ptype, fragment in cases:
            with self.assertRaises(ValueError) as cm:
                t3mod.prop_value(value, ptype, "p")
            self.assertIn(fragment, str(cm.exception), (value, ptype))


# ------------------------------------------------------------------------------------------------
# spec -> APP
# ------------------------------------------------------------------------------------------------
class ConverterTests(ModTestCase):
    def test_fixture_visual(self):
        app = self.app()
        out, ctx = self.build_app(demo_spec(), app)
        self.assertEqual(ctx.problems, [])
        vs = out["pages"][0]["visuals"][0]
        want = dict(EXPECTED_VISUAL)
        self.assertEqual(vs, want)
        self.assertEqual(list(vs), list(want))                           # key order of the APP literal
        for got, layer in zip(vs["layers"], EXPECTED_LAYERS):
            self.assertEqual(list(got), list(layer))
            self.assertEqual(list(got["axes"]), list(layer["axes"]))      # manifest order
        self.assertEqual(out["vizMods"], [["demo-layers", "mods\\demo-layers", "1.0.0"]])
        self.assertNotIn("actionMods", out)                              # action mods are manual steps
        whats = [m[0] for m in out["manual"]]
        self.assertIn("action trigger demoLayers[0]", whats)
        self.assertIn("action mod demo-layers-actions", whats)

    def test_unused_vizmods_entry_is_left_out(self):
        spec = demo_spec()
        spec["vizMods"].append({"id": "other-mod", "project": "mods/other"})
        files = dict(FILES)
        other = dict(VIZ_MANIFEST, id="other-mod", version="2.0.0")
        files["mods/other/mod-manifest.json"] = json.dumps(other)
        out, ctx = self.build_app(spec, self.app(spec, files))
        self.assertEqual(out["vizMods"], [["demo-layers", "mods\\demo-layers", "1.0.0"]])
        self.assertIn("other-mod", ctx.viz_manifests)

    def test_no_version_no_layers_no_legend_given(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        for key in ("layers", "legend", "marking", "properties"):
            v.pop(key)
        files = dict(FILES)
        man = dict(VIZ_MANIFEST)
        man.pop("version")
        files["mods/demo-layers/mod-manifest.json"] = json.dumps(man)
        out, ctx = self.build_app(spec, self.app(spec, files))
        self.assertEqual(ctx.problems, [])
        vs = out["pages"][0]["visuals"][0]
        self.assertEqual(vs, {"id": "demoLayers", "type": "mod", "title": "Readings and events",
                              "mod": "demo-layers", "table": "READINGS"})
        self.assertEqual(out["vizMods"], [["demo-layers", "mods\\demo-layers"]])

    def test_main_view_keys_and_explicit_legend(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v.update({"legend": {"visible": True, "hide": ["filtering"]}, "limitExpression": "[Asset] = [$ViewAsset]",
                  "useFiltering": False, "layers": [], "marking": "Event Pick", "showTitle": False,
                  "settings": {"Transparency": 0.2}})
        out, ctx = self.build_app(spec, self.app(spec))
        self.assertEqual(ctx.problems, [])
        vs = out["pages"][0]["visuals"][0]
        self.assertEqual(vs["where"], '[Asset] = DocumentProperty("ViewAsset")')
        self.assertIs(vs["filtering"], False)
        self.assertEqual(vs["layers"], [])                        # given empty: every layer is removed
        self.assertIs(vs["legend"], True)                         # written only because the spec says so
        self.assertEqual(vs["legendHide"], ["filtering"])
        self.assertEqual(vs["marking"], "Event Pick")
        self.assertIs(vs["showTitle"], False)
        self.assertEqual(vs["settings"], {"Transparency": 0.2})

    def test_layer_defaults(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["marking"] = "Event Pick"
        v["layers"] = [{"type": "Records", "limitByMarkings": ["Marking"]},
                       {"type": "Series", "title": "Raw", "marking": None, "limitByMarkings": ["Marking"],
                        "emptyMarkingBehavior": "ShowEmpty"}]
        out, _ = self.build_app(spec, self.app(spec))
        layers = out["pages"][0]["visuals"][0]["layers"]
        self.assertEqual(layers[0], {"type": "Records", "title": "Records", "table": "READINGS",
                                     "marking": "Event Pick", "limits": ["Marking"], "empty": "ShowAll"})
        self.assertEqual(layers[1], {"type": "Series", "title": "Raw", "table": "READINGS", "marking": None,
                                     "limits": ["Marking"], "empty": "ShowEmpty"})
        v.pop("marking")                                           # absent: the default marking
        out, _ = self.build_app(spec, self.app(spec))
        self.assertEqual(out["pages"][0]["visuals"][0]["layers"][0]["marking"], "Marking")

    def test_mod_not_in_vizmods_needs_slim(self):
        spec = demo_spec()
        spec.pop("vizMods")
        out, ctx = self.build_app(spec, self.app(spec))
        self.assertIn(("pages[0].visuals[0].modId", "a mod visual whose mod is not listed in vizMods is not in "
                       "the standard engine yet: use --tier slim"), ctx.problems)
        self.assertNotIn("vizMods", out)

    def test_coloring_on_a_mod_is_unsupported(self):
        spec = demo_spec()
        spec["pages"][0]["visuals"][0]["coloring"] = {"fixed": "#112233"}
        _, ctx = self.build_app(spec, self.app(spec))
        self.assertIn("pages[0].visuals[0].coloring", [p for p, _ in ctx.problems])

    def test_useFiltering_false_still_unsupported_elsewhere(self):
        spec = demo_spec()
        spec["pages"][0]["visuals"][1]["useFiltering"] = False
        _, ctx = self.build_app(spec, self.app(spec))
        self.assertIn(("pages[0].visuals[1].useFiltering", "useFiltering false is not in the standard engine yet: "
                       "use --tier slim"), ctx.problems)

    def test_files_read(self):
        app = self.app()
        files = t3.files_read({"vizMods": [["demo-layers", "mods\\demo-layers", "1.0.0"]]}, app.resolve())
        self.assertEqual(files, ["mods\\demo-layers\\mod-manifest.json", "mods\\demo-layers\\index.html",
                                 "mods\\demo-layers\\main.css", "mods\\demo-layers\\main.js",
                                 "mods\\demo-layers\\icon.svg"])
        (app / "mods" / "demo-layers" / "main.css").unlink()      # only what exists at generation time
        files = t3.files_read({"vizMods": [["demo-layers", "mods\\demo-layers", "1.0.0"]]}, app.resolve())
        self.assertNotIn("mods\\demo-layers\\main.css", files)

    def test_features_and_parts(self):
        app = {"vizMods": [["demo-layers", "mods\\demo-layers"]], "tables": [["T", {}]], "pages": []}
        features = t3.features_of(app)
        for name in ("vizMods", "guard", "preflight", "pathFree"):
            self.assertIn(name, features)
        for name in ("reflect", "reflectPlus", "actionMods"):
            self.assertNotIn(name, features)
        parts = t3.FEATURE_PARTS
        self.assertEqual(parts.index("modload"), parts.index("controls") + 1)
        self.assertNotIn("actionmods", parts)
        self.assertEqual(t3.FEATURE_NEEDS["vizMods"], ("modload",))
        self.assertNotIn("vizMods", t3.features_of({"pages": []}))
        self.assertIn("mod", t3.registry())
        self.assertEqual(t3.kind_of("mod"), "mod")

    def test_every_feature_part_exists(self):
        # strict: every part FEATURE_PARTS names is a file (a missing one fails the build, never
        # silently leaves code out)
        for name in t3.FEATURE_PARTS:
            self.assertTrue((t3.ENGINE_DIR / "features" / (name + ".py")).is_file(), name)
        self.assertEqual(t3.feature_part_names({"vizMods"}), ["modload"])


@unittest.skipUnless(ENGINE_READY, "needs engine/builders/mod.py and engine/features/modload.py")
class GenerateTests(ModTestCase):
    def test_every_tier_passes_the_static_checks(self):
        app = self.app()
        spec = demo_spec()
        for tier in t3.TIERS:
            result = self.generate(spec, app, tier)
            self.assertEqual(result.problems, [], tier)
            names = [p.name for p in result.parts]
            self.assertIn("modload", names)
            self.assertIn("mod", names)
            self.assertNotIn("actionmods", names)
            self.assertIn("vizMods", result.features)
            target = self.tmp / ("build_%s.py" % tier)
            target.write_text(result.text, encoding="utf-8")
            checks, summary = dxpgen.engine_checks(target, result.text, result,
                                                   dxpgen.Options(lint=False, sanitize=False), "15.0")
            self.assertEqual([e["message"] for e in checks.errors], [], tier)
            files = result.app["files"]
            self.assertIn("mods\\demo-layers\\mod-manifest.json", files)
            self.assertIn("mods\\demo-layers\\main.js", files)

    def test_app_without_mods_has_no_mod_code(self):
        spec = demo_spec()
        spec.pop("vizMods")
        spec["pages"][0]["visuals"].pop(0)
        spec["pages"][0]["layout"] = {"row": [{"visual": "eventTable"}]}
        spec.pop("actionMods")
        result = self.generate(spec, self.app(spec))
        self.assertEqual(result.problems, [])
        self.assertNotIn("modload", [p.name for p in result.parts])
        for name in ("load_viz", "build_mod", "new_mod_visual", "VIZ_FIX", "rename_starter_page"):
            self.assertNotIn(name, result.text)
        text = result.text
        # without mod visuals: the starter page goes before the visuals are built (unchanged order)
        self.assertLess(text.index('ok("remove starter page"'), text.index("build_page, page, ps)"))

    def test_starter_page_goes_after_the_mod_visuals(self):
        # a mod visual on the starter page keeps the mod in the analysis; the starter goes only after the
        # new mod visuals exist, so the starter pages are renamed first and removed after build_page
        text = self.generate(demo_spec(), self.app(), "standard").text
        tail = text[text.index('OLD_PAGES = ok("list pages"'):]
        self.assertEqual(tail.count('ok("remove starter page"'), 1)
        self.assertLess(tail.index("rename_starter_page, p)"), tail.index("add_page, ps[\"title\"])"))
        self.assertLess(tail.index("build_page, page, ps)"), tail.index('ok("remove starter page"'))
        self.assertLess(tail.index('ok("remove starter page"'), tail.index('ok("active page", set_active)'))
        self.assertLess(text.index("load_viz, entry)"), text.index('OLD_PAGES = ok("list pages"'))


# ------------------------------------------------------------------------------------------------
# validation
# ------------------------------------------------------------------------------------------------
class ValidationTests(ModTestCase):
    def test_fixture_is_clean(self):
        report = self.validate(demo_spec())
        self.assertEqual(self.messages(report), [])
        notes = [m for _, m in self.messages(report, "note")]
        self.assertIn("visualization mod 'demo-layers' 1.0.0 (API 2.4): 2 layer type(s) (Series, Records), 4 mod "
                      "properties", notes)
        warned = [p for p, _ in self.messages(report, "warning")]
        self.assertFalse([p for p in warned if "visuals[0]" in p or p.startswith("vizMods")], warned)

    def test_vizmods_entries(self):
        spec = demo_spec()
        spec["vizMods"] = [{"id": "demo-layers", "project": "mods/demo-layers", "extra": 1},
                           {"id": "demo-layers", "project": "mods/demo-layers"},
                           {"id": "demo-layers-actions", "project": "actionmod"},
                           {"id": "no-project"},
                           {"id": "gone", "project": "mods/gone"},
                           {"project": "mods/demo-layers"}]
        report = self.validate(spec)
        self.assert_message(report, "warning", "vizMods[0].extra", "unknown field 'extra'")
        self.assert_message(report, "error", "vizMods[1].id", "visualization mod 'demo-layers' is listed twice")
        self.assert_message(report, "error", "vizMods[2].id", "'demo-layers-actions' is listed in actionMods too")
        self.assert_message(report, "error", "vizMods[2].project", "the manifest's type is a string \"action\", "
                            "not \"visualization\"")
        self.assert_message(report, "error", "vizMods[3].project", "missing required field 'project': the standard "
                            "engine reads the mod's mod-manifest.json")
        self.assert_message(report, "error", "vizMods[4].project", "folder not found: ")
        self.assert_message(report, "error", "vizMods[5].id", "missing required field 'id'")
        self.assert_message(report, "warning", "vizMods[3]", "visualization mod 'no-project' is listed but no mod "
                            "visual uses it; the builder leaves it out")

    def test_manifest_problems(self):
        files = dict(FILES)
        files["mods/empty/readme.txt"] = "x"
        files["mods/bad/mod-manifest.json"] = "{not json"
        files["mods/list/mod-manifest.json"] = "[]"
        man = dict(VIZ_MANIFEST, id="other", icon="missing.svg", files=["main.js", "dist/bundle.js"])
        files["mods/wrong/mod-manifest.json"] = json.dumps(man)
        files["mods/wrong/main.js"] = "var a = 1;\n"
        nofiles = dict(VIZ_MANIFEST, id="nofiles")
        nofiles.pop("files")
        files["mods/nofiles/mod-manifest.json"] = json.dumps(nofiles)
        files["mods/nofiles/icon.svg"] = "<svg/>"
        spec = demo_spec()
        spec["vizMods"] += [{"id": "empty", "project": "mods/empty"}, {"id": "bad", "project": "mods/bad"},
                            {"id": "list", "project": "mods/list"}, {"id": "wrong", "project": "mods/wrong"},
                            {"id": "nofiles", "project": "mods/nofiles"}]
        report = self.validate(spec, files)
        self.assert_message(report, "error", "vizMods[1].project", "no mod-manifest.json in ")
        self.assert_message(report, "error", "vizMods[2].project", "is not valid JSON")
        self.assert_message(report, "error", "vizMods[3].project", "must hold a JSON object")
        self.assert_message(report, "error", "vizMods[4].id", "the manifest's id is a string \"other\", not 'wrong'")
        self.assert_message(report, "error", "vizMods[4].project", "mod-manifest.json lists 1 file(s) that are not "
                            "in ")
        self.assert_message(report, "error", "vizMods[4].project", "dist/bundle.js; build the mod first")
        self.assert_message(report, "warning", "vizMods[4].project", "the manifest's icon missing.svg is not in ")
        self.assert_message(report, "warning", "vizMods[5].project", "the manifest lists no 'files'; Spotfire "
                            "embeds only the files it lists")

    def test_mod_id(self):
        spec = demo_spec()
        spec["pages"][0]["visuals"][0]["modId"] = "demo-layer"
        report = self.validate(spec)
        self.assert_message(report, "error", "pages[0].visuals[0].modId", "unknown visualization mod 'demo-layer' "
                            "(did you mean 'demo-layers'?) (list it in vizMods)")
        spec = demo_spec()
        spec.pop("vizMods")
        spec["pages"][0]["visuals"][0].pop("layers")
        report = self.validate(spec)
        self.assert_message(report, "warning", "pages[0].visuals[0].modId", "mod 'demo-layers' is not listed in "
                            "vizMods: the standard engine builds mod visuals only from vizMods")

    def test_axes(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["axes"] = {"X": "[Timestamp]"}
        layers = v["layers"]
        layers[0]["axes"]["Valuez"] = "[Flow (bbl/d)]"
        layers[0]["axes"]["Series"] = "BinByDateTime([Timestamp],\"Year\",1)"
        layers[1]["axes"]["X"] = ["Min([Timestamp])", "Max([Timestamp])"]
        layers[1]["axes"]["Values"] = "<[Asset]>"
        layers[2]["axes"]["Key"] = "Event ID"                       # a bare column on a categorical axis: fine
        layers[2]["axes"]["Attributes"] = "[Asset] & [Start]"
        report = self.validate(spec)
        base = "pages[0].visuals[0]"
        self.assert_message(report, "error", base + ".axes.X", "mod 'demo-layers' has no axis 'X' on its main view "
                            "(main view axes: none)")
        self.assert_message(report, "error", base + ".layers[0].axes.Valuez", "layer type 'Series' of mod "
                            "'demo-layers' has no axis 'Valuez' (did you mean 'Values'?) (its axes: X, Values, "
                            "Series, Bin)")
        self.assert_message(report, "error", base + ".layers[0].axes.Series", "'Series' is a categorical axis: "
                            "give <...>, a column name or a list of levels")
        self.assert_message(report, "error", base + ".layers[1].axes.X", "axis 'X' takes one expression (its "
                            "manifest entry has no allowMultipleMeasures); give one string")
        self.assert_message(report, "error", base + ".layers[1].axes.Values", "'Values' is a continuous axis: give "
                            "an expression or a column name, not <...>")
        self.assert_message(report, "error", base + ".layers[2].axes.Attributes", "'Attributes' is a categorical "
                            "axis")
        self.assertFalse([p for p, _ in self.messages(report) if p.endswith("layers[2].axes.Key")])

    def test_required_axes(self):
        spec = demo_spec()
        layers = spec["pages"][0]["visuals"][0]["layers"]
        layers[0]["axes"].pop("X")
        layers[1].pop("axes")
        report = self.validate(spec)
        base = "pages[0].visuals[0].layers"
        self.assert_message(report, "warning", base + "[0].axes", "required axis 'X' of layer 'Readings' gets no "
                            "expression and the manifest configures none; the view stays invalid until it is set")
        self.assert_message(report, "warning", base + "[1]", "required axis 'Values' of layer 'Daily range'")
        self.assertFalse([m for p, m in self.messages(report, "warning") if p.startswith(base + "[2]")
                          and "required axis" in m])

    def test_properties(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["properties"].update({"heading": 3, "maxRows": 2.5, "showGrid": "yes", "colour": "red"})
        v["layers"][0]["properties"].update({"lineWidth": "1", "roles": "x"})
        v["layers"][1]["properties"] = ["role"]
        report = self.validate(spec)
        base = "pages[0].visuals[0]"
        self.assert_message(report, "error", base + ".properties.heading", "property 'heading' is string in the "
                            "mod's manifest, got a whole number 3")
        self.assert_message(report, "error", base + ".properties.maxRows", "property 'maxRows' is an integer "
                            "(32-bit), got a number 2.5")
        self.assert_message(report, "error", base + ".properties.showGrid", "property 'showGrid' is boolean")
        self.assert_message(report, "error", base + ".properties.colour", "mod 'demo-layers' has no property "
                            "'colour' (its properties: heading, showGrid, lineWidth, maxRows)")
        self.assert_message(report, "error", base + ".layers[0].properties.lineWidth", "property 'lineWidth' is "
                            "double in the mod's manifest, got a string")
        self.assert_message(report, "error", base + ".layers[0].properties.roles", "layer type 'Series' of mod "
                            "'demo-layers' has no property 'roles' (did you mean 'role'?) (its properties: role, "
                            "lineWidth, visible)")
        self.assert_message(report, "error", base + ".layers[1].properties", "must be an object of property name")

    def test_layers(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["layers"] += [{"type": "Serie", "title": "Other"},
                        {"title": "No type"},
                        {"type": "Records", "title": "Events", "table": "NOPE", "marking": "Nope",
                         "limitByMarkings": ["Gone"], "emptyMarkingBehavior": "Hide", "useFiltering": "no",
                         "colour": 1},
                        {"type": "Records"}, {"type": "Records"},
                        "layer"]
        report = self.validate(spec)
        base = "pages[0].visuals[0].layers"
        self.assert_message(report, "error", base + "[3].type", "mod 'demo-layers' has no layer type 'Serie' (did you "
                            "mean 'Series'?) (its layer types: Series, Records)")
        self.assert_message(report, "error", base + "[4].type", "missing required field 'type'")
        self.assert_message(report, "error", base + "[5].title", "layer title 'Events' is used twice in this visual "
                            "(also layers[2]); titles identify the layers for the mod and verify_dxp")
        self.assert_message(report, "error", base + "[5].table", "unknown data table 'NOPE'")
        self.assert_message(report, "error", base + "[5].marking", "unknown marking 'Nope'")
        self.assert_message(report, "error", base + "[5].limitByMarkings[0]", "unknown marking")
        self.assert_message(report, "error", base + "[5].emptyMarkingBehavior", "must be one of ShowAll")
        self.assert_message(report, "error", base + "[5].useFiltering", "must be true or false")
        self.assert_message(report, "warning", base + "[5].colour", "unknown field 'colour'")
        self.assert_message(report, "error", base + "[7].title", "layer title 'Records' is used twice in this visual "
                            "(also layers[6])")
        self.assert_message(report, "error", base + "[8]", "must be a layer object")
        spec = demo_spec()
        spec["pages"][0]["visuals"][0]["layers"] = {"type": "Series"}
        self.assert_message(self.validate(spec), "error", base, "must be a list of layers, got an object")
        files = dict(FILES)
        man = dict(VIZ_MANIFEST)
        man.pop("layers")
        files["mods/demo-layers/mod-manifest.json"] = json.dumps(man)
        self.assert_message(self.validate(demo_spec(), files), "error", base, "mod 'demo-layers' declares no layer "
                            "types (manifest 'layers'), so it takes no layers")

    def test_live_properties_in_mod_views_are_errors(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["limitExpression"] = "[Asset] = \"${ViewAset}\""
        v["layers"][0]["limitExpression"] = "[Asset] = \"${Nope}\""
        v["layers"][1]["axes"]["Bin"] = "<BinByDateTime([Timestamp],\"Year\",${BinLvl})>"
        v["layers"][2]["axes"]["Values"] = "Max([Severity]) * [$Factor]"
        report = self.validate(spec)
        base = "pages[0].visuals[0]"
        self.assert_message(report, "error", base + ".limitExpression", "${ViewAset} names no declared document "
                            "property (did you mean 'ViewAsset'?); the mod limiting expression cannot be evaluated")
        self.assert_message(report, "error", base + ".layers[0].limitExpression", "${Nope} names no declared "
                            "document property; the mod layer's limiting expression cannot be evaluated")
        self.assert_message(report, "error", base + ".layers[1].axes.Bin", "${BinLvl} names no declared document "
                            "property (did you mean 'BinLevel'?); the mod axis 'Bin' cannot be evaluated")
        self.assert_message(report, "error", base + ".layers[2].axes.Values", "unknown document property 'Factor'")
        self.assertFalse([p for p, _ in self.messages(report, "warning") if p.startswith(base + ".")
                          and "${" in _])

    def test_column_references(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["layers"][0]["axes"]["X"] = "Timestmp"
        v["layers"][2]["axes"]["Values"] = "Max([Severty])"
        v["layers"][2]["limitExpression"] = "[Aset] = \"${ViewAsset}\""
        v["layers"][1]["axes"]["Values"] = ["Min([${ViewAsset}]) as [${ViewAsset} min]"]
        report = self.validate(spec)
        base = "pages[0].visuals[0].layers"
        self.assert_message(report, "warning", base + "[0].axes.X", "'Timestmp' is neither a column of table "
                            "READINGS")
        self.assert_message(report, "warning", base + "[2].axes.Values", "[Severty] is not a column of table EVENTS")
        self.assert_message(report, "warning", base + "[2].limitExpression", "[Aset] is not a column of table EVENTS")
        self.assertFalse([p for p, _ in self.messages(report, "warning") if p == base + "[1].axes.Values"])

    def test_legend_and_coloring(self):
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["legend"] = {"visible": True, "hide": ["filtering", "lineBy"]}
        v["coloring"] = {"fixed": "#112233"}
        report = self.validate(spec)
        self.assert_message(report, "error", "pages[0].visuals[0].legend.hide[1]", "\"lineBy\" is not a legend item "
                            "kind of a mod visual")
        self.assert_message(report, "warning", "pages[0].visuals[0].coloring", "(the standard engine stops: use "
                            "--tier slim, or color through the mod's properties)")

    def test_marking_audit_counts_layers(self):
        spec = demo_spec()
        spec["pages"][0]["visuals"][1]["limitByMarkings"] = []
        report = self.validate(spec)
        notes = [m for _, m in self.messages(report, "note")]
        self.assertTrue([m for m in notes if "marking 'Event Pick' is used only by demoLayers/Events (EVENTS)" in m],
                        notes)


class ExpressionColumnsTests(unittest.TestCase):
    def test_identifiers_built_from_live_properties(self):
        self.assertEqual(dxpgen.expression_columns("[${Signal}]"), [])
        self.assertEqual(dxpgen.expression_columns("Min([${S}]) as [${S} min]"), [])
        self.assertEqual(dxpgen.expression_columns("[A ${x}]"), [])
        self.assertEqual(dxpgen.expression_columns("[Asset] = \"${ViewAsset}\" and [B]"), [(None, "Asset"),
                                                                                           (None, "B")])
        self.assertEqual(dxpgen.expression_columns("<BinByDateTime([T],\"Year\",${Level})>"), [(None, "T")])


# ------------------------------------------------------------------------------------------------
# customer-ready text, release, slim
# ------------------------------------------------------------------------------------------------
class TextLintTests(ModTestCase):
    def found(self, spec, files):
        app = self.app(spec, files)

        def read(rel):
            full = app / rel
            return (full.read_text(encoding="utf-8") if full.is_file() else None), str(full)
        return textlint.check_app(spec, read)

    def test_mod_project_and_text_properties(self):
        files = dict(FILES)
        man = dict(VIZ_MANIFEST, description="Layer cards, v2.0 of the layer demo")
        files["mods/demo-layers/mod-manifest.json"] = json.dumps(man)
        files["mods/demo-layers/main.js"] = "// TODO remove the debug card\nvar a = 1;\n"
        files["mods/demo-layers/main.css"] = "/* legacy colors */\n.card { color: red; }\n"
        files["mods/demo-layers/index.html"] = "<html><body><!-- FIXME --><div></div></body></html>"
        spec = demo_spec()
        v = spec["pages"][0]["visuals"][0]
        v["properties"]["heading"] = "Readings (prototype)"
        v["properties"]["uiState"] = {"note": "TODO"}
        v["layers"][0]["title"] = "Readings R2.0"
        found = self.found(spec, files)
        by_path = dict((p, (lvl, m)) for lvl, p, m in found)
        self.assertEqual(by_path["vizMods[0].project (manifest description)"][0], "error")
        self.assertEqual(by_path["vizMods[0].project (manifest files[2])"][0], "warning")      # main.js
        self.assertIn("TODO", by_path["vizMods[0].project (manifest files[2])"][1])
        self.assertIn("legacy", by_path["vizMods[0].project (manifest files[1])"][1])           # main.css
        self.assertIn("FIXME", by_path["vizMods[0].project (manifest files[0])"][1])            # index.html
        self.assertEqual(by_path["pages[0].visuals[0].properties.heading"][0], "error")
        self.assertEqual(by_path["pages[0].visuals[0].layers[0].title"][0], "error")
        self.assertFalse([p for p in by_path if "uiState" in p])

    def test_clean_fixture(self):
        self.assertEqual(self.found(demo_spec(), FILES), [])


class ReleaseTests(ModTestCase):
    def test_release_copies_the_mod_project_without_node_modules(self):
        app = self.app()
        refs = dxpgen.spec_file_refs(demo_spec())
        self.assertIn(("vizMods[0].project", "mods/demo-layers", True), refs)
        files, folders, errors, warnings = dxpgen.release_plan(app, demo_spec())
        self.assertEqual(errors, [])
        rels = [rel for _, rel in folders]
        self.assertIn("mods/demo-layers", rels)
        self.assertIn("actionmod", rels)
        version = self.tmp / "v0.1"
        dxpgen.copy_release(files, folders, version)
        self.assertTrue((version / "mods" / "demo-layers" / "main.js").is_file())
        self.assertFalse((version / "mods" / "demo-layers" / "node_modules").exists())
        for rel in t3.files_read({"vizMods": [["demo-layers", "mods\\demo-layers", "1.0.0"]]}, version):
            self.assertTrue((version / rel.replace("\\", "/")).is_file(), rel)


class SlimTests(ModTestCase):
    def test_slim_refuses_mod_layers(self):
        app = self.app()
        out = io.StringIO()
        code = slim_builder.slim_app(app, app / "spec.json", dxpgen.Options(lint=False, sanitize=False,
                                                                            tools_dir=self.tmp), out=out)
        self.assertEqual(code, dxpgen.EXIT_INVALID)
        self.assertIn("pages[0].visuals[0].layers: mod layers are built by the standard engine only; build without "
                      "--tier slim", out.getvalue())

    def test_library_spec_drops_vizmods(self):
        app = self.app()
        resolved = dxpgen.library_spec(dxpgen.resolve_spec(demo_spec(), app))
        self.assertNotIn("vizMods", resolved)
        self.assertIn("vizMods", dxpgen.resolve_spec(demo_spec(), app))


if __name__ == "__main__":
    unittest.main(verbosity=2)
