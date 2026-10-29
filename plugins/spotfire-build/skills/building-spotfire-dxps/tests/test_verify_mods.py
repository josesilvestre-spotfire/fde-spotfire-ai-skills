"""Tests for the visualization-mod reading and checks of scripts/verify_dxp.py.

Everything runs on synthetic models and mod containers and on the assets/examples/mod-layers-demo
fixture. Nothing starts Spotfire.

Run: python -B tests/test_verify_mods.py
"""
import base64
import copy
import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TOOLS = SKILL / "scripts"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import verify_dxp as V  # noqa: E402
from test_verify import MINI_DOC, MINI_META  # noqa: E402

try:
    from t3 import mod as T3MOD  # noqa: E402  (the converter's reading; absent before the engine work lands)
except ImportError:
    T3MOD = None

FIXTURE = SKILL / "assets" / "examples" / "mod-layers-demo"
TMP_ROOT = os.environ.get("DXPB_TEST_TMP") or None

_MODELS = {}


def model_of(path):
    """(model, builder, archive) of a DXP, parsed once per test run."""
    key = str(path)
    if key not in _MODELS:
        _MODELS[key] = V.build_model(path)
    return _MODELS[key]


def tearDownModule():
    for _, _, archive in _MODELS.values():
        try:
            archive.close()
        except Exception:
            pass


def lines(items, area=None, path=None, check=None):
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


def statuses(items, path=None, check=None, area=None):
    """Statuses of the lines whose path contains `path` and whose check is exactly `check`."""
    return [it["status"] for it in lines(items, area, path) if check is None or it["check"] == check]


def make_asice(manifest, files, digest_ok=True):
    """An embedded mod container as Spotfire writes it: mimetype, mod.zip (mod-manifest.json + files; the
    icon twice when files lists it too), META-INF/ASiCManifest.xml with the sha512 of mod.zip."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("mod-manifest.json", json.dumps(manifest, separators=(",", ":")))
        for name, body in files.items():
            z.writestr(name, body)
        if manifest.get("icon") in files:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)          # zipfile: duplicate name, on purpose
                z.writestr(manifest["icon"], files[manifest["icon"]])
    mod_zip = inner.getvalue()
    digest = base64.b64encode(hashlib.sha512(mod_zip if digest_ok else b"x").digest()).decode("ascii")
    asic = ('<?xml version="1.0" encoding="UTF-8"?><ASiCManifest xmlns="http://uri.etsi.org/02918/v1.2.1#" '
            'xmlns:ns2="http://www.w3.org/2000/09/xmldsig#"><SigReference URI="META-INF/signature.p7s"/>'
            '<DataObjectReference URI="mod.zip"><ns2:DigestMethod Algorithm="http://www.w3.org/2001/04/'
            'xmlenc#sha512"/><ns2:DigestValue>%s</ns2:DigestValue></DataObjectReference></ASiCManifest>' % digest)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("mimetype", "application/vnd.etsi.asic-e+zip")
        z.writestr("mod.zip", mod_zip)
        z.writestr("META-INF/ASiCManifest.xml", asic)
        z.writestr("META-INF/signature.p7s", b"\x30\x00")
    return outer.getvalue(), "sha512=" + base64.b64encode(hashlib.sha512(mod_zip).digest()).decode("ascii")


# ------------------------------------------------------------------------------------------------
# reading a spec value with the manifest
# ------------------------------------------------------------------------------------------------
COLUMNS = ["Asset", "Timestamp", "Pressure (psig)", "Flow (bbl/d)", "Event ID", "Start", "End"]
AXIS_CASES = [
    ("Timestamp", "continuous", "[Timestamp]"),
    ("Timestamp", "dual", "[Timestamp]"),
    ("Min([Timestamp])", "continuous", "Min([Timestamp])"),
    (["Pressure (psig)", "Flow (bbl/d)"], "continuous", "[Pressure (psig)], [Flow (bbl/d)]"),
    (["Min([Pressure (psig)]) as [Pressure min]", "Max([Pressure (psig)]) as [Pressure max]"], "continuous",
     "Min([Pressure (psig)]) as [Pressure min], Max([Pressure (psig)]) as [Pressure max]"),
    ("[$Signal] * 2", "continuous", 'DocumentProperty("Signal") * 2'),
    ("Not A Column", "continuous", "Not A Column"),
    ("Asset", "categorical", "<[Asset]>"),
    ("[Asset]", "categorical", "<[Asset]>"),
    ("<[Event ID]>", "categorical", "<[Event ID]>"),
    (["Asset", "Start", "End"], "categorical", "<[Asset] NEST [Start] NEST [End]>"),
    (["<[Asset]>", "[Start]"], "categorical", "<[Asset] NEST [Start]>"),
    ('<BinByDateTime([Timestamp],"Year.Quarter.Month.Day.Hour",${BinLevel})>', "categorical",
     '<BinByDateTime([Timestamp],"Year.Quarter.Month.Day.Hour",${BinLevel})>'),
    ("<[Axis.Default.Names]>", "categorical", "<[Axis.Default.Names]>"),
    ("", "categorical", ""),
    ("", "continuous", ""),
    ([], "categorical", ""),
    (None, "continuous", None),
    (None, "categorical", None),
]


class ModAxisTextTest(unittest.TestCase):
    def test_cases(self):
        for value, mode, want in AXIS_CASES:
            self.assertEqual(V.mod_axis_text(value, mode, COLUMNS), want, (value, mode))

    def test_without_manifest_is_the_text_as_written(self):
        self.assertEqual(V.mod_axis_text("Timestamp", None, COLUMNS), "Timestamp")
        self.assertEqual(V.mod_axis_text(["[A]", "[B]"], None, COLUMNS), "[A], [B]")
        self.assertEqual(V.mod_axis_text("[$P]", None), 'DocumentProperty("P")')

    @unittest.skipIf(T3MOD is None or not hasattr(T3MOD, "axis_text"), "scripts/t3/mod.py not available")
    def test_same_reading_as_the_converter(self):
        E = V.Expressions(COLUMNS)
        for value, mode, _ in AXIS_CASES:
            self.assertEqual(T3MOD.axis_text(value, mode, E.column, V.props_shorthand),
                             V.mod_axis_text(value, mode, COLUMNS), (value, mode))
        man = json.loads((FIXTURE / "mods" / "demo-layers" / "mod-manifest.json").read_text(encoding="utf-8"))
        for layer_type in (None, "Series", "Records"):
            self.assertEqual(dict((k, T3MOD.axis_mode(d)) for k, d in T3MOD.manifest_axes(man, layer_type).items()),
                             V.mod_manifest_axes(man, layer_type), layer_type)
            self.assertEqual(T3MOD.manifest_props(man, layer_type), V.mod_manifest_props(man, layer_type))


class ModManifestTest(unittest.TestCase):
    def setUp(self):
        self.man = json.loads((FIXTURE / "mods" / "demo-layers" / "mod-manifest.json").read_text(encoding="utf-8"))

    def test_views(self):
        self.assertEqual(V.mod_manifest_axes(self.man), {})
        self.assertEqual(V.mod_manifest_props(self.man), {"heading": "string", "showGrid": "boolean",
                                                         "lineWidth": "double", "maxRows": "integer"})
        self.assertEqual(list(V.mod_manifest_axes(self.man, "Series").items()),
                         [("X", "continuous"), ("Values", "continuous"), ("Series", "categorical"),
                          ("Bin", "categorical")])
        self.assertEqual(V.mod_manifest_axes(self.man, "Records"),
                         {"Key": "categorical", "Attributes": "categorical", "Values": "continuous"})
        self.assertEqual(V.mod_manifest_props(self.man, "Series"),
                         {"role": "string", "lineWidth": "double", "visible": "boolean"})
        self.assertIsNone(V.mod_manifest_axes(self.man, "Nope"))
        self.assertIsNone(V.mod_manifest_props(self.man, "Nope"))

    def test_color_axis_is_dual(self):
        man = {"layers": [{"type": "Marker layer", "dataViewDefinition": {
            "axes": [{"name": "X", "mode": "continuous"}], "colorAxis": {"mode": "dual"}}}]}
        self.assertEqual(V.mod_manifest_axes(man, "Marker layer"), {"X": "continuous", "Color": "dual"})


class ModPropMatchTest(unittest.TestCase):
    def test_types(self):
        self.assertTrue(V.mod_prop_matches("Pump readings", "Pump readings", "string"))
        self.assertFalse(V.mod_prop_matches("1", 1, "string"))
        self.assertTrue(V.mod_prop_matches({"b": 1, "a": [2]}, '{"a":[2],"b":1}', "string"))
        self.assertFalse(V.mod_prop_matches({"a": 1}, "not json", "string"))
        self.assertTrue(V.mod_prop_matches(5000, 5000, "integer"))
        self.assertTrue(V.mod_prop_matches(5000.0, 5000, "integer"))
        self.assertFalse(V.mod_prop_matches(5000, 5000.0, "integer"))        # persisted as a double
        self.assertTrue(V.mod_prop_matches(1, 1.0, "double"))
        self.assertTrue(V.mod_prop_matches(1.5, 1.5000000000001, "double"))
        self.assertTrue(V.mod_prop_matches(True, True, "boolean"))
        self.assertFalse(V.mod_prop_matches(True, 1, "boolean"))
        self.assertFalse(V.mod_prop_matches(1, True, "integer"))
        self.assertTrue(V.mod_prop_matches(1.5, 1.5))                           # no manifest


# ------------------------------------------------------------------------------------------------
# embedded mod containers
# ------------------------------------------------------------------------------------------------
class EmbeddedModTest(unittest.TestCase):
    MAN = {"id": "demo", "version": "2.0.1", "type": "visualization", "name": "Demo", "apiVersion": "2.4",
           "icon": "icon.svg", "files": ["main.js", "icon.svg"]}

    def test_read_container(self):
        data, digest = make_asice(self.MAN, {"main.js": b"var a = 1;\n", "icon.svg": b"<svg/>"})
        rec = V.read_embedded_mod("Mods/mod-0.asice", data)
        self.assertNotIn("error", rec)
        self.assertEqual((rec["id"], rec["version"], rec["type"], rec["apiVersion"]),
                         ("demo", "2.0.1", "visualization", "2.4"))
        self.assertEqual(rec["digest"], digest)
        self.assertEqual(rec["asicDigest"], digest)
        self.assertEqual(rec["files"], {"main.js": hashlib.sha256(b"var a = 1;\n").hexdigest(),
                                        "icon.svg": hashlib.sha256(b"<svg/>").hexdigest()})

    def test_broken_container(self):
        rec = V.read_embedded_mod("Mods/mod-9.asice", b"not a zip")
        self.assertEqual(rec["archive"], "Mods/mod-9.asice")
        self.assertIn("BadZipFile", rec["error"])

    def test_model_lists_embedded_mods(self):
        tmp = Path(tempfile.mkdtemp(prefix="verify-mods-mini-", dir=TMP_ROOT))
        try:
            dxp = tmp / "mini.dxp"
            data, digest = make_asice(self.MAN, {"main.js": b"x", "icon.svg": b"<svg/>"})
            with zipfile.ZipFile(str(dxp), "w") as z:
                z.writestr("AnalysisDocument.xml", MINI_DOC)
                z.writestr("Metadata.xml", MINI_META)
                z.writestr("Mods/mod-0.asice", data)
                z.writestr("Mods/mod-1.asice", b"broken")
            model, _, archive = V.build_model(dxp)
            archive.close()
            self.assertEqual(len(model["mods"]), 1)
            m = model["mods"][0]
            self.assertEqual((m["modId"], m["kind"], m["origin"], m["archive"], m["digest"], m["embeddedVersion"]),
                             ("demo", "visualization", None, "Mods/mod-0.asice", digest, "2.0.1"))
            self.assertTrue(any("Mods/mod-1.asice" in n for n in model.get("notes") or []))
            json.dumps(model)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ------------------------------------------------------------------------------------------------
# check_mod / check_action_triggers on a synthetic model of the fixture (the expected G1 result)
# ------------------------------------------------------------------------------------------------
def fixture_files():
    folder = FIXTURE / "mods" / "demo-layers"
    man = json.loads((folder / "mod-manifest.json").read_text(encoding="utf-8"))
    return man, dict((f, (folder / f).read_bytes()) for f in man["files"])


def fixture_layers():
    names = "<[Axis.Default.Names]>"
    where = '[Asset] = "${ViewAsset}"'
    common = {"limitByMarkings": [], "limitByFilterings": [], "emptyMarkingBehavior": "ShowEmpty"}
    return [
        dict(common, title="Readings", type="Series", table="READINGS", marking=None, useFiltering=True,
             limitExpression=where,
             axes={"X": "[Timestamp]", "Values": "[Pressure (psig)], [Flow (bbl/d)]", "Series": names, "Bin": ""},
             properties={"role": "raw", "lineWidth": 1.0, "visible": True},
             propertyTypes={"role": "string", "lineWidth": "double", "visible": "boolean"}),
        dict(common, title="Daily range", type="Series", table="READINGS", marking=None, useFiltering=False,
             limitExpression=where,
             axes={"X": "Min([Timestamp])", "Values": "Min([Pressure (psig)]) as [Pressure min], "
                   "Max([Pressure (psig)]) as [Pressure max]", "Series": names,
                   "Bin": '<BinByDateTime([Timestamp],"Year.Quarter.Month.Day.Hour",${BinLevel})>'},
             properties={"role": "binned", "lineWidth": 1.0, "visible": True},
             propertyTypes={"role": "string", "lineWidth": "double", "visible": "boolean"}),
        dict(common, title="Events", type="Records", table="EVENTS", marking="Event Pick", useFiltering=True,
             limitExpression=where,
             axes={"Key": "<[Event ID]>", "Attributes": "<[Asset] NEST [Start] NEST [End]>",
                   "Values": "Max([Severity])"},
             properties={"role": "events"}, propertyTypes={"role": "string"}),
    ]


def fixture_model(digest, files):
    vm = {"guid": "g-mod", "typeId": "Spotfire.Mod", "contentClass": "ModVisualization",
          "title": "Readings and events", "showTitle": True, "table": "READINGS", "marking": None,
          "limitByMarkings": [], "limitByFilterings": [], "useFiltering": True, "limitExpression": None,
          "emptyMarkingBehavior": "ShowEmpty", "legendVisible": False, "axes": {}, "modId": "demo-layers",
          "modName": "Layer demo", "modVersion": "1.0.0", "modApiVersion": "2.4", "modHash": digest,
          "modOrigin": {"origin": "ManifestFile", "value": "C:\\x\\mods\\demo-layers\\mod-manifest.json"},
          "modAxes": {}, "modProperties": {"heading": "Pump readings", "showGrid": True, "lineWidth": 1.5,
                                           "maxRows": 5000},
          "modPropertyTypes": {"heading": "string", "showGrid": "boolean", "lineWidth": "double",
                               "maxRows": "integer"},
          "modLayers": fixture_layers(),
          "actionTriggers": [{"display": "FloatingButton", "mod": "demo-layers-actions", "script": "next-asset",
                              "configuration": None, "args": {"Assets": "Pump A,Pump B"}}]}
    model = {
        "tables": [{"name": "READINGS", "columns": [{"name": c} for c in
                                                     ("Asset", "Timestamp", "Pressure (psig)", "Flow (bbl/d)")]},
                   {"name": "EVENTS", "columns": [{"name": c} for c in
                                                  ("Event ID", "Asset", "Start", "End", "Severity")]}],
        "mods": [{"modId": "demo-layers", "origin": "ManifestFile", "value": None, "kind": "visualization",
                  "archive": "Mods/mod-0.asice", "digest": digest, "embeddedVersion": "1.0.0",
                  "embeddedFiles": dict((k, hashlib.sha256(v).hexdigest()) for k, v in files.items())}],
        "markings": [], "pages": [],
    }
    return model, vm


class FixtureCheckTest(unittest.TestCase):
    """What verify_dxp reports for a DXP that is exactly what the fixture asks for, and for each kind of
    difference."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-mods-fixture-", dir=TMP_ROOT))
        self.app = self.tmp / "ModLayersDemo"
        shutil.copytree(str(FIXTURE), str(self.app))
        self.raw = json.loads((self.app / "spec.json").read_text(encoding="utf-8"))
        man, files = fixture_files()
        _, self.digest = make_asice(man, files)
        self.model, self.vm = fixture_model(self.digest, files)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def checker(self, raw=None):
        raw = raw if raw is not None else self.raw
        c = V.Checker(self.app, self.app / "spec.json", dxpgen)
        c.raw_doc = copy.deepcopy(raw)
        c.spec = dxpgen.resolve_spec(copy.deepcopy(raw), self.app)
        c.model = self.model
        return c

    def vs(self, c):
        return [v for v in c.spec["pages"][0]["visuals"] if v["id"] == "demoLayers"][0]

    def run_check(self, raw=None, vm=None):
        c = self.checker(raw)
        c.check_visual("Layers > demoLayers (mod)", self.vs(c), vm if vm is not None else self.vm)
        return c.R.items

    def test_expected_result_passes(self):
        items = self.run_check()
        bad = [it for it in items if it["status"] != "PASS"]
        self.assertEqual(bad, [])
        checks = set(it["check"] for it in items)
        for want in ("mod id", "mod version", "mod embedded in the DXP", "embedded mod is the one the visual uses",
                     "embedded file main.js", "embedded file icon.svg", "mod property maxRows",
                     "mod property maxRows type", "mod layers (type, title, in order)", "layer type", "data table",
                     "marking", "useFiltering", "limitExpression", "axis Values", "axis Attributes", "axis Bin",
                     "property lineWidth type", "action trigger", "action trigger arguments", "legend visible"):
            self.assertIn(want, checks)
        self.assertEqual(statuses(items, path="layers['Events']", check="marking"), ["PASS"])
        self.assertEqual(len(lines(items, check="embedded file")), 4)

    def test_embedded_files_once_per_mod(self):
        c = self.checker()
        vs = self.vs(c)
        c.check_visual("p > a (mod)", vs, self.vm)
        c.check_visual("p > b (mod)", vs, self.vm)
        self.assertEqual(len(lines(c.R.items, check="embedded file main.js")), 1)
        self.assertEqual(len(lines(c.R.items, check="embedded mod is the one the visual uses")), 2)

    def test_mod_differences_fail(self):
        vm = copy.deepcopy(self.vm)
        vm["modVersion"] = "0.9.0"
        vm["modHash"] = "sha512=other"
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="mod version"), ["FAIL"])
        self.assertEqual(statuses(items, check="embedded mod is the one the visual uses"), ["FAIL"])
        self.model["mods"] = []
        items = self.run_check()
        self.assertEqual(statuses(items, check="mod embedded in the DXP"), ["FAIL"])
        self.assertFalse(lines(items, check="embedded file"))

    def test_embedded_file_differs_or_is_missing(self):
        (self.app / "mods" / "demo-layers" / "main.js").write_text("// another build\n", encoding="utf-8")
        (self.app / "mods" / "demo-layers" / "main.css").unlink()
        items = self.run_check()
        js = lines(items, check="embedded file main.js")[0]
        self.assertEqual(js["status"], "FAIL")
        self.assertIn("another build", js["note"])
        self.assertEqual(statuses(items, check="embedded file main.css"), ["WARN"])
        self.assertEqual(statuses(items, check="embedded file index.html"), ["PASS"])

    def test_view_differences_fail(self):
        vm = copy.deepcopy(self.vm)
        vm["modPropertyTypes"]["maxRows"] = "double"
        vm["modProperties"]["showGrid"] = False
        vm["modLayers"][0]["axes"]["Values"] = "[Pressure (psig)]"
        vm["modLayers"][0]["axes"]["Bin"] = "<[Asset]>"
        vm["modLayers"][2]["marking"] = None
        vm["modLayers"][1]["useFiltering"] = True
        vm["modLayers"][2]["limitExpression"] = '[Asset] = "Pump A"'
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="mod property maxRows type"), ["FAIL"])
        self.assertEqual(statuses(items, check="mod property showGrid"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Readings']", check="axis Values"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Events']", check="marking"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Daily range']", check="useFiltering"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Events']", check="limitExpression"), ["FAIL"])

    def test_cleared_axis(self):
        raw = copy.deepcopy(self.raw)
        raw["pages"][0]["visuals"][0]["layers"][0]["axes"]["Bin"] = ""
        items = self.run_check(raw)
        self.assertEqual(statuses(items, path="layers['Readings']", check="axis Bin"), ["PASS"])
        vm = copy.deepcopy(self.vm)
        vm["modLayers"][0]["axes"]["Bin"] = "<[Asset]>"
        items = self.run_check(raw, vm)
        self.assertEqual(statuses(items, path="layers['Readings']", check="axis Bin"), ["FAIL"])

    def test_layer_order_and_extra_layer(self):
        vm = copy.deepcopy(self.vm)
        vm["modLayers"] = [vm["modLayers"][1], vm["modLayers"][0], vm["modLayers"][2],
                           dict(vm["modLayers"][2], title="Old events")]
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="mod layers (type, title, in order)"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Readings']", check="layer type"), ["PASS"])
        self.assertEqual(statuses(items, path="layers['Old events']", check="layer in spec"), ["FAIL"])
        vm["modLayers"] = vm["modLayers"][:1]
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, path="layers['Events']", check="layer present"), ["FAIL"])

    def test_unknown_names_and_layer_marking_default(self):
        raw = copy.deepcopy(self.raw)
        visual = raw["pages"][0]["visuals"][0]
        visual["layers"][0]["axes"]["Nope"] = "[A]"
        visual["layers"][0]["properties"]["nope"] = 1
        visual["marking"] = "Event Pick"
        del visual["layers"][2]["marking"]                     # absent: the visual's marking
        items = self.run_check(raw)
        self.assertEqual(statuses(items, path="layers['Readings']", check="axis Nope"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Readings']", check="property nope"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Events']", check="marking"), ["PASS"])

    def test_without_manifest_axes_are_compared_as_written(self):
        raw = copy.deepcopy(self.raw)
        raw["vizMods"] = []
        items = self.run_check(raw)
        self.assertFalse(lines(items, check="mod version"))
        self.assertFalse(lines(items, check="embedded file"))
        self.assertEqual(statuses(items, check="mod embedded in the DXP"), ["PASS"])
        # "Timestamp" is not read as a column without the manifest's axis mode
        self.assertEqual(statuses(items, path="layers['Readings']", check="axis X"), ["FAIL"])
        self.assertEqual(statuses(items, path="layers['Events']", check="axis Key"), ["PASS"])

    def test_legend_only_when_the_spec_gives_it(self):
        raw = copy.deepcopy(self.raw)
        del raw["pages"][0]["visuals"][0]["legend"]
        vm = dict(self.vm, legendVisible=False)
        items = self.run_check(raw, vm)
        self.assertFalse(lines(items, check="legend visible"))
        raw["pages"][0]["visuals"][0]["legend"] = {"visible": True}
        self.assertEqual(statuses(self.run_check(raw, vm), check="legend visible"), ["FAIL"])

    def test_action_triggers(self):
        vm = copy.deepcopy(self.vm)
        vm["actionTriggers"][0]["args"] = {"Assets": "Pump A"}
        vm["actionTriggers"].append({"display": "ContextMenuItem", "ironPython": "Old Script", "args": {}})
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="action trigger arguments"), ["FAIL"])
        extra = lines(items, check="no action triggers beyond the spec")
        self.assertEqual([it["status"] for it in extra], ["WARN"])
        self.assertEqual(extra[0]["found"], ["ContextMenuItem -> IronPython script Old Script"])
        # another display: the spec's trigger is still a manual step (WARN), the found one is extra
        vm["actionTriggers"] = [dict(vm["actionTriggers"][0], display="TitleBarButton")]
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="action trigger"), ["WARN"])
        self.assertEqual(statuses(items, check="no action triggers beyond the spec"), ["WARN"])
        # none added yet: a manual step, never a FAIL
        vm["actionTriggers"] = []
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="action trigger"), ["WARN"])
        self.assertIn("manual step", lines(items, check="action trigger")[0]["note"])
        self.assertFalse(lines(items, check="action trigger arguments"))

    @unittest.skipIf(T3MOD is None, "scripts/t3/mod.py not available")
    def test_what_the_engine_is_told_passes(self):
        """The DXP the engine makes from the converter's APP visual (each APP key set as written, layer
        markings always set, AddNew's defaults elsewhere) passes every check: the converter and the
        verifier read the spec the same way."""
        import t3
        resolved = dxpgen.resolve_spec(copy.deepcopy(self.raw), self.app)
        result = t3.generate(resolved, self.raw, self.app, "standard", dxpgen.column_reader(resolved), {})
        self.assertEqual(result.problems, [])
        av = [v for p in result.app["pages"] for v in p["visuals"] if v["id"] == "demoLayers"][0]

        def view(entry):
            return {"axes": dict(entry.get("axes") or {}),
                    "properties": dict((p[0], p[2]) for p in entry.get("props") or []),
                    "propertyTypes": dict((p[0], p[1]) for p in entry.get("props") or [])}
        layers = []
        for al in av.get("layers") or []:
            layer = {"title": al["title"], "type": al["type"], "table": al["table"], "marking": al["marking"],
                     "limitByMarkings": list(al.get("limits") or []), "limitByFilterings": [],
                     "useFiltering": al.get("filtering", True), "limitExpression": al.get("where"),
                     "emptyMarkingBehavior": al.get("empty", "ShowEmpty")}
            layer.update(view(al))
            layers.append(layer)
        main = view(av)
        vm = dict(self.vm, table=av["table"], marking=av.get("marking"), legendVisible=av.get("legend", False),
                  limitExpression=av.get("where"), useFiltering=av.get("filtering", True), modAxes=main["axes"],
                  modProperties=main["properties"], modPropertyTypes=main["propertyTypes"], modLayers=layers,
                  actionTriggers=[])                        # the engine adds none: a manual step
        self.assertNotIn("actions", av)
        items = self.run_check(vm=vm)
        self.assertEqual([(it["check"], it["status"]) for it in items if it["status"] != "PASS"],
                         [("action trigger", "WARN")])
        self.assertEqual(len(lines(items, check="layer type")), 3)

    def test_placeholder_text_area(self):
        vm = {"guid": "g", "typeId": "Spotfire.HtmlTextArea", "title": "Readings and events",
              "htmlContent": "<p><b>[mod: demo-layers]</b></p>"}
        items = self.run_check(vm=vm)
        self.assertEqual(statuses(items, check="type"), ["FAIL"])
        self.assertIn("demo-layers", lines(items, check="type")[0]["note"])


# ------------------------------------------------------------------------------------------------
# the fixture app itself
# ------------------------------------------------------------------------------------------------
class FixtureFilesTest(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((FIXTURE / "spec.json").read_text(encoding="utf-8"))
        self.man = json.loads((FIXTURE / "mods" / "demo-layers" / "mod-manifest.json").read_text(encoding="utf-8"))
        self.visual = self.spec["pages"][0]["visuals"][0]

    def test_projects(self):
        self.assertEqual(self.spec["vizMods"], [{"id": "demo-layers", "project": "mods/demo-layers"}])
        self.assertEqual((self.man["id"], self.man["type"], self.man["apiVersion"]), ("demo-layers", "visualization",
                                                                                     "2.4"))
        for f in self.man["files"]:
            self.assertTrue((FIXTURE / "mods" / "demo-layers" / f).is_file(), f)
        act = json.loads((FIXTURE / "actionmod" / "mod-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((act["id"], act["type"]), ("demo-layers-actions", "action"))
        for sc in act["scripts"]:
            self.assertTrue((FIXTURE / "actionmod" / sc["file"]).is_file())
            self.assertTrue((FIXTURE / "actionmod" / sc["icon"]).is_file())
        for t in self.spec["tables"]:
            self.assertGreater((FIXTURE / t["source"]["path"]).stat().st_size, 100, t["name"])

    def test_layers_match_the_manifest(self):
        self.assertEqual(len(self.visual["layers"]), 3)
        self.assertEqual(len(set(t["table"] for t in self.visual["layers"])), 2)
        for name, value in self.visual["properties"].items():
            self.assertTrue(V.mod_prop_matches(value, value, V.mod_manifest_props(self.man)[name]), name)
        for layer in self.visual["layers"]:
            modes = V.mod_manifest_axes(self.man, layer["type"])
            types = V.mod_manifest_props(self.man, layer["type"])
            self.assertLessEqual(set(layer["axes"]), set(modes), layer["title"])
            self.assertLessEqual(set(layer["properties"]), set(types), layer["title"])

    def test_axis_readings(self):
        """The expressions the builder writes for the fixture (the design's APP visual)."""
        cols = {"READINGS": ["Asset", "Timestamp", "Pressure (psig)", "Flow (bbl/d)"],
                "EVENTS": ["Event ID", "Asset", "Start", "End", "Severity"]}
        got = {}
        for layer in self.visual["layers"]:
            modes = V.mod_manifest_axes(self.man, layer["type"])
            got[layer["title"]] = dict((n, V.mod_axis_text(v, modes[n], cols[layer["table"]]))
                                       for n, v in layer["axes"].items())
        self.assertEqual(got["Readings"], {"X": "[Timestamp]", "Values": "[Pressure (psig)], [Flow (bbl/d)]",
                                           "Series": "<[Axis.Default.Names]>"})
        self.assertEqual(got["Events"], {"Key": "<[Event ID]>", "Attributes": "<[Asset] NEST [Start] NEST [End]>",
                                         "Values": "Max([Severity])"})
        self.assertEqual(got["Daily range"]["Bin"],
                         '<BinByDateTime([Timestamp],"Year.Quarter.Month.Day.Hour",${BinLevel})>')

    def test_csv_is_reproducible(self):
        spec = importlib.util.spec_from_file_location("make_demo_csv", str(FIXTURE / "data" / "make_demo_csv.py"))
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        for name, rows in (("READINGS.csv", gen.readings()), ("EVENTS.csv", gen.events())):
            with open(str(FIXTURE / "data" / "csv" / name), newline="", encoding="utf-8") as f:
                self.assertEqual(list(csv.reader(f))[1:], rows, name)
        self.assertEqual(len(gen.readings()), 144)

    def test_customer_text(self):
        import textlint

        def read(rel):
            p = FIXTURE / rel
            return (p.read_text(encoding="utf-8"), str(p.resolve())) if p.is_file() else (None, rel)
        found = textlint.check_app(self.spec, read)
        tl = textlint.TextLint(self.spec, read)
        for rel in ("mods/demo-layers/main.js", "mods/demo-layers/main.css"):
            tl.code_file(rel, rel, "js")
        tl.text("manifest name", self.man["name"])
        tl.text("manifest description", self.man["description"])
        self.assertEqual(found + tl.found, [])

    def test_dxpgen_validate_has_no_errors(self):
        report, spec, _ = dxpgen.validate_app(FIXTURE, FIXTURE / "spec.json", dxpgen.Options(lint=False,
                                                                                              sanitize=False))
        self.assertIsNotNone(spec)
        self.assertEqual(report.errors, [])


# ------------------------------------------------------------------------------------------------
# real DXPs
# ------------------------------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main(verbosity=2)
