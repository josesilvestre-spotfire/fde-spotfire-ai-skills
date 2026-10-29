"""Tests for the standard engine's kitchen features: data-function inputs limited by a marking,
text-area JavaScript, legend item hiding, the visual settings shorthands, the refused-save re-check with
the build session switch, the default marking of KPI charts, and the items the public API cannot build
(text-area controls, property triggers, action mods, the theme), which become manual steps.

Run: python -m unittest tests/test_kitchen_features.py   (or python -m unittest discover -s tests)

The fixture app (temporary folder) is the test_features kitchen plus every feature above, with an
action-mod project folder (mod-manifest.json and a built bundle). KitchenBuildTests builds it with the
real tools (scripts/lint_ipy.py, scripts/ipy_parse.ps1 when Windows PowerShell and Spotfire Analyst 15.0
are installed, scripts/sfapi.py when an API index is available); the other tests run the generator, the
validator or engine functions in CPython with stand-ins. Nothing starts Spotfire.
"""
import ast
import contextlib
import copy
import hashlib
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
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import slim_builder  # noqa: E402
import t3  # noqa: E402
from t3 import _assemble  # noqa: E402
import test_features  # noqa: E402
from test_dxpgen import minimal_spec  # noqa: E402

META = {"spec_sha": "0" * 64, "generated": "2026-10-02T00:00:00"}
MOD_ID = "kitchen-actions"
MANIFEST = {
    "apiVersion": "2.1", "version": "1.0.0", "type": "action", "id": MOD_ID, "name": "Kitchen actions",
    "icon": "icon.svg",
    "scripts": [
        {"id": "add-window", "name": "Add window", "file": "build/add-window.js", "entryPoint": "addWindow",
         "parameters": [{"name": "kind", "type": "String", "enum": ["Normal", "Anomaly"]}]},
        {"id": "go-page", "name": "Go to page", "file": "build/go-page.js", "entryPoint": "goPage",
         "parameters": [{"name": "page", "type": "Page"}, {"name": "count", "type": "Integer"},
                        {"name": "note", "type": "String", "optional": True}]},
    ]}
TRACK = '''import pandas as pd
rows = MarkedRows if MarkedRows is not None else pd.DataFrame()
MarkedWindow = "" if len(rows) == 0 else str(len(rows)) + "|" + str(Mode)
'''
APPLY = ('value = Document.Properties["MarkedWindow"]\n'
         'if value:\n'
         '    Document.Properties["Note"] = "window " + value\n')
TEMPLATE_JS = "var sfHost = $(\"#styleDivSF\").first();\n"
FILES = dict(test_features.FILES)
FILES.update({
    "datafunctions/track_window.py": TRACK,
    "scripts/apply_window.py": APPLY,
    "html/Apply Template Styles.js": TEMPLATE_JS,
    "actionmod/mod-manifest.json": json.dumps(MANIFEST, indent=2),
    "actionmod/build/add-window.js": "function addWindow(a) {}\nRegisterEntryPoint(addWindow);\n",
    "actionmod/build/go-page.js": "function goPage(a) {}\nRegisterEntryPoint(goPage);\n",
    "actionmod/icon.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>",
})
HOST_HTML = '<div id="style-container"></div><div id="styleDivSF"></div>'


def kitchen_spec():
    spec = test_features.fixture_spec()
    spec["app"]["theme"] = {"base": "LightSfx"}
    spec["properties"].append({"name": "MarkedWindow", "type": "String", "default": ""})
    spec["dataFunctions"].append({
        "name": "Track Window", "script": "datafunctions/track_window.py",
        "inputs": [{"name": "MarkedRows", "type": "table",
                    "bind": {"table": "SCORES", "columns": ["Timestamp", "Group"], "limitByMarking": "Window"}},
                   {"name": "Mode", "type": "value", "dataTypes": ["String"], "bind": {"property": "Mode"}}],
        "outputs": [{"name": "MarkedWindow", "type": "value", "target": {"property": "MarkedWindow"}}],
        "refresh": "automatic", "executeAtBuild": True})
    spec["scripts"].append({"name": "Apply Window", "file": "scripts/apply_window.py"})
    spec["triggers"] = [{"property": "MarkedWindow", "script": "Apply Window"}]
    spec["actionMods"] = [{"id": MOD_ID, "project": "actionmod"}]
    visuals = spec["pages"][0]["visuals"]
    controls = visuals[0]
    controls["html"] = HOST_HTML + test_features.HTML
    controls["js"] = ["html/Apply Template Styles.js", {"name": "Note Render", "code": "var shown = 1;"}]
    controls["controls"]["run"]["actionMod"] = {"mod": MOD_ID, "script": "add-window", "args": {"kind": "Anomaly"}}
    controls["controls"]["toDetail"]["actionMod"] = {"mod": MOD_ID, "script": "go-page",
                                                     "args": {"page": "Detail", "count": 3}}
    trend = visuals[1]
    trend["legend"] = {"visible": True, "hide": ["filtering", "marking", "referenceLayers"]}
    trend["settings"].update({"Description": "Drag to mark a window.", "ShowDescription": True,
                              "UseSeparateColorForMarkedItems": True, "YAxis.ShowAxisSelector": False})
    trend["actionTriggers"] = [
        {"display": "FloatingButton", "actionMod": {"mod": MOD_ID, "script": "add-window",
                                                    "args": {"kind": "Normal"}}},
        {"display": "TitleBarButton", "actionMod": {"mod": MOD_ID, "script": "go-page",
                                                    "args": {"page": "Detail", "count": 1}}}]
    marked = visuals[4]
    marked["settings"] = {"LimitingMarkingsEmptyMessage": "Mark rows on the trend",
                          "LimitingMarkingsEmptyBehavior": "ShowMessage"}
    return spec


def strip_home(text):
    """The builder without its HOME literal (the temporary app folder)."""
    out, skip = [], False
    for line in text.split("\n"):
        if line.startswith("HOME = "):
            skip = True
        if skip and line.startswith("# " + "=" * 64 + " STYLE"):
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out)


def app_literal(text):
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "APP":
            return ast.literal_eval(node.value)
    return None


class KitchenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kitchen-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, spec=None, slug="FeatureKitchen2", files=None):
        app = self.tmp / "apps" / slug
        for rel, text in (FILES if files is None else files).items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (app / "spec.json").write_text(json.dumps(spec or kitchen_spec(), indent=2), encoding="utf-8")
        return app

    def generate(self, spec, app, tier="standard"):
        resolved = dxpgen.resolve_spec(spec, app)
        return t3.generate(resolved, spec, app, tier, dxpgen.column_reader(resolved), META)

    def validate(self, spec, app=None):
        app = app or self.app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tmp))
        return report


# ------------------------------------------------------------------------------------------------
# full builds with the real tools
# ------------------------------------------------------------------------------------------------
class KitchenBuildTests(KitchenTestCase):
    def test_tiers_build_and_pass_every_check(self):
        app = self.app()
        options = dxpgen.Options(lint=True, sanitize=False, tools_dir=SKILL / "scripts")
        for tier in ("standard", "compact", "report"):
            out = io.StringIO()
            with contextlib.redirect_stderr(io.StringIO()):
                code = dxpgen.build_app(app, app / "spec.json", options, out=out, tier=tier)
            text_out = out.getvalue()
            self.assertEqual(code, 0, text_out)
            path = app / "build" / ("build_FeatureKitchen2_%s.py" % tier)
            self.assertTrue(path.is_file(), text_out)
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            self.assertEqual(slim_builder.text_problems(text), [], tier)
            self.assertEqual(slim_builder.undefined_names(text), {}, tier)
            self.assertIn("lint 0 error(s)", text_out)
            self.assertNotIn("is not in the 15.0 index", text_out)
            if dxpgen.find_index_file() is not None:
                self.assertRegex(text_out, r"sfapi\.py has: \d+ members, \d+ setters OK")
            if "IronPython parse not run" not in text_out:
                self.assertIn("PARSE OK", text_out)
            name = "Feature Kitchen %s.dxp" % tier
            self.assertIn(name, text_out)
            self.assertEqual(app_literal(text)["output"], "build\\" + name)
            for word in ("NonPublic", "icall", "GetActionModsIncludingPinned", "AddScriptEventHandler",
                         "SetTheme"):
                self.assertIsNone(re.search(r"%s" % word, text), (tier, word))
            self.assertIn("manual steps:", text_out)
            manual = (app / "build" / ("MANUAL-STEPS-%s.md" % tier)).read_text(encoding="utf-8")
            self.assertIn("Insert Property Control", manual)
            self.assertIn("Edit > Document Properties > Properties", manual)
            self.assertLess(len(text), 90000, tier)

    def test_cli_has_no_variant_option(self):
        parser = dxpgen.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["build", "x", "--variant", "actionmods"])
        self.assertEqual(parser.parse_args(["build", "x"]).tier, "standard")


# ------------------------------------------------------------------------------------------------
# spec -> APP
# ------------------------------------------------------------------------------------------------
class KitchenConversionTests(KitchenTestCase):
    def setUp(self):
        super().setUp()
        self.spec = kitchen_spec()
        self.app_dir = self.app(self.spec)
        self.result = self.generate(self.spec, self.app_dir)
        self.assertEqual(self.result.problems, [])

    def visuals(self, result):
        return dict((v["id"], v) for p in result.app["pages"] for v in p["visuals"])

    def test_marked_input_js_legend(self):
        app = self.result.app
        track = [d for d in app["dataFunctions"] if d["name"] == "Track Window"][0]
        self.assertEqual(track["in"][0], ["MarkedRows", "table",
                                          {"table": "SCORES", "columns": ["Timestamp", "Group"],
                                           "marking": "Window"}])
        self.assertNotIn("refresh", track)
        self.assertNotIn("triggers", app)                                    # a manual step now
        v = self.visuals(self.result)
        self.assertEqual(v["controls"]["js"], [["Apply Template Styles", "html\\Apply Template Styles.js"],
                                               ["Note Render", None, "var shown = 1;"]])
        self.assertEqual(v["trend"]["legendHide"], ["filtering", "marking", "referenceLayers"])
        self.assertNotIn("legend", v["trend"])                               # visible: the default
        self.assertEqual(v["trend"]["settings"]["Description"], "Drag to mark a window.")
        self.assertEqual(v["marked"]["settings"], {"Data.LimitingMarkingsEmptyMessage": "Mark rows on the trend",
                                                   "Data.LimitingMarkingsEmptyBehavior": "ShowMessage"})
        for feature in ("guard", "markedInputs", "textjs", "legendHide", "scripts", "controls", "manual"):
            self.assertIn(feature, self.result.features)
        for feature in ("triggers", "reflect", "actionMods"):
            self.assertNotIn(feature, self.result.features)
        parts = [p.name for p in self.result.parts]
        for part in ("guard", "textjs", "legend", "controls"):
            self.assertIn(part, parts)

    def test_manual_steps(self):
        """Controls, the property trigger, the action mod, its visual triggers and the theme are manual
        steps: APP "manual" in build order, markers for the controls, no action-mod keys in APP."""
        app = self.result.app
        whats = [m[0] for m in app["manual"]]
        self.assertIn("control controls/run", whats)
        self.assertIn("control controls/toDetail", whats)
        self.assertIn("action trigger trend[0]", whats)
        self.assertIn("action trigger trend[1]", whats)
        self.assertIn("trigger MarkedWindow -> Apply Window", whats)
        self.assertIn("action mod " + MOD_ID, whats)
        self.assertEqual(whats[-1], "theme")
        self.assertLess(whats.index("control controls/run"), whats.index("trigger MarkedWindow -> Apply Window"))
        how = dict(app["manual"])
        self.assertIn("Insert Action Control > Button", how["control controls/run"])
        self.assertIn("runs the IronPython script 'Add Window'", how["control controls/run"])
        self.assertIn("action mod 'kitchen-actions'", how["control controls/run"])
        self.assertIn("select the script 'Apply Window'", how["trigger MarkedWindow -> Apply Window"])
        self.assertIn("TitleBarButton", how["action trigger trend[1]"])
        self.assertEqual(self.result.manual, app["manual"])
        self.assertNotIn("actionMods", app)
        v = self.visuals(self.result)
        markers = v["controls"]["controls"]
        self.assertTrue(all(isinstance(text, str) for text in markers.values()), markers)
        self.assertTrue(markers["run"].startswith("Button: "), markers)
        self.assertNotIn("actions", v["trend"])
        for name in ("load_mod", "mod_script", "mod_action", "visual_actions", "GetActionModsIncludingPinned"):
            self.assertNotIn(name, self.result.text)
        self.assertNotIn("Variant ", self.result.text)
        self.assertTrue(app["output"].endswith("Feature Kitchen standard.dxp"))
        self.assertTrue(app["log"].endswith("build-log-standard.txt"))
        report = self.generate(self.spec, self.app_dir, "report")
        self.assertEqual(report.app["tag"], "report")
        self.assertTrue(report.app["output"].endswith("Feature Kitchen report.dxp"))

    def test_generated_code_has_the_calls(self):
        text = self.result.text
        for needle in ("recheck()", "df.Inputs.SetInput(parameter(params, i[0]), bind_expr(i[2]), False,",
                       "Array[DataSelection]([m])", 'for entry in APP["manual"]:', "ScriptLanguage.JavaScript",
                       "ta.Scripts.Add(HtmlTextAreaScript(sd, Dictionary[String, String]()))",
                       "text_scripts(v, vs)", "item.Visible = False", "hide_legend_items, v, vs",
                       "html = place_controls(v, vs, html)"):
            self.assertIn(needle, text)
        for needle in ("ValidateApplicationIsIdle", "GUARD_TEXT", "NonPublic", "def icall", "def iget",
                       "AddScriptEventHandler", "build_trigger", "apply_theme"):
            self.assertNotIn(needle, text)
        build = text[text.index("# " + "=" * 64 + " build"):]
        order = ["OPENED_FROM", "property \" + p[0]", "data function \" + d[\"name\"]",
                 "script \" + s[\"name\"]", "build_page", 'for entry in APP["manual"]:', "finish()"]
        found = [build.find(o) for o in order]
        self.assertTrue(all(f >= 0 for f in found), list(zip(order, found)))
        self.assertEqual(found, sorted(found))
        report = self.generate(self.spec, self.app_dir, "report").text
        for key in ("hide_legend_items", "attach_js"):
            self.assertIn('if key == "%s":' % key, report)
        for key in ("add_trigger", "load_mod", "mod_script", "add_action", "apply_theme"):
            self.assertNotIn('if key == "%s":' % key, report)
        self.assertIn('"then check: " + recheck())', report)
        self.assertIn('if key in ("switch_session", "session_page", "repoint"):', report)
        self.assertIn('lines.append("## Add by hand (" + str(len(by_hand)) + ")")', report)

    def test_build_session_switch_after_the_real_save(self):
        """finish() switches the open analysis to the build session only after the inline save of the
        real DXP succeeded; the queued-save path never switches. Report tier: after the report files and
        the snapshots, only when SAVED."""
        for result in (self.result,):
            text = result.text
            finish = text[text.index("def finish():"):]
            finish = finish[:finish.index("\n\n\n")]
            save = finish.index('if ok("save", save_now):')
            switch = finish.index('ok("build session", switch_session)')
            queued = finish.index('ok("queue save", queue, save)')
            self.assertLess(save, switch)
            self.assertLess(switch, queued)                    # inside the success branch, not the else
            self.assertEqual(finish.count("switch_session"), 1)
            body = text[text.index("def switch_session():"):]
            body = body[:body.index("\n\n\n")]
            self.assertLess(body.index('ok("build session page", session_page)'),
                            body.index('ok("build session save", repoint)'))
            self.assertIn('"Session re-pointed to " + target', body)
            repoint = text[text.index("def repoint():"):]
            repoint = repoint[:repoint.index("\n\n\n")]
            self.assertIn("Application.SaveAs(target, DocumentSaveSettings())", repoint)
            self.assertNotIn("SaveAs(OUT", repoint)
            header = " ".join(line[1:].strip() for line in text.splitlines() if line.startswith("#"))
            self.assertIn("the open analysis shows a 'Build Session' page", header)
        report = self.generate(self.spec, self.app_dir, "report").text
        finish = report[report.rindex("def finish():"):]
        self.assertLess(finish.index("after_save()"), finish.index('ok("build session", switch_session)'))
        self.assertIn('if SAVED[0]:\n        ok("build session", switch_session)', finish)
        self.assertIn("if page.Title == SESSION_PAGE:", report)        # the snapshots skip the page
        self.assertIn('"switch_session": "save"', report)

    def test_kpi_charts_get_the_default_marking(self):
        for result in (self.result,):
            kpis = [v for p in result.app["pages"] for v in p["visuals"] if v["type"] == "kpi"]
            self.assertTrue(kpis)
            for vs in kpis:
                self.assertEqual(vs["marking"], "Marking")
            self.assertIn("links", result.features)

    def test_members_are_declared(self):
        api, setters = self.result.members()
        for spec in ("DataFunctionInputCollection.SetInput(InputParameter, String, Boolean, DataSelection[])",
                     "ScriptLanguage.JavaScript", "Legend.Items", "PageCollection.AddNew(String)",
                     "VisualTypeIdentifiers.HtmlTextArea", "AnalysisApplication.SaveAs(String, DocumentSaveSettings)",
                     "HtmlTextArea.HtmlContent"):
            self.assertIn(spec, api)
        self.assertIn("LegendItem.Visible", setters)
        for spec in ("Document.ActivePageReference", "HtmlTextArea.HtmlContent", "Visual.ShowTitle"):
            self.assertIn(spec, setters)
        self.assertFalse([s for s in api if s.startswith("Spotfire.Dxp.") and "Internal" in s])

    def test_marking_limit_on_a_property_bind_is_still_unsupported(self):
        spec = kitchen_spec()
        spec["dataFunctions"][-1]["inputs"][1]["bind"]["limitByMarking"] = "Window"
        result = self.generate(spec, self.app_dir)
        self.assertIn("dataFunctions[2].inputs[1].bind.limitByMarking", [p for p, _ in result.problems])
        spec = kitchen_spec()
        spec["dataFunctions"][-1]["inputs"][0]["bind"]["limitByFiltering"] = True
        result = self.generate(spec, self.app_dir)
        self.assertIn("dataFunctions[2].inputs[0].bind.limitByFiltering", [p for p, _ in result.problems])


# ------------------------------------------------------------------------------------------------
# apps without the new features keep their builders
# ------------------------------------------------------------------------------------------------
class UnchangedBuilderTests(KitchenTestCase):
    """The builders of apps without features stay byte-identical (sha256 of the builder without its HOME
    literal; generated with META). Change these hashes only on purpose."""
    WTS = {"standard": "80e076b8ae0ae19f638174009ce33cc6a6eb1f8740634a4415f8cb1de724238b",
           "quick": "349530e35cb8cfe591f745f12965f329200e17cac784f6ecbb8fbbb71f87832e",
           "compact": "a859543e7e6401447109ebf2d9fb224c1de0123f16ead1768e9d7be22a461e74",
           "report": "99cdd5ffa90409b6128fc2167d767c663867e06326891f66a33f2371ef21d4ef"}
    MINIMAL = {"standard": "801187837affbef274bbc6bddfffbecd5497cd5fbc76bddd1fd0048f57fa15c1",
               "quick": "2b693bdf62f31b2b3d09b7fe03ad133fc986a9e092ab47b0efecce9160347098",
               "compact": "0dadd5e5df9ee28c8bf1129494d15866e2b047e2641e767a4decedf8078ac29d",
               "report": "0620f795f3a7b700b0cc78d48c177f6a903d66fe7bb7c6eeace233d49a1437d4"}
    NEW = ("recheck", "place_controls", "text_scripts", "hide_legend_items", "marked_rows", "load_viz",
           "build_mod", "new_mod_visual", "MOD_PLACEHOLDERS", "VIZ_FIX", "rename_starter_page",
           'APP["manual"]')
    SESSION = ("switch_session", "SESSION_PAGE", "Build Session", "build session", "repoint")

    def check(self, spec, app, hashes):
        for tier, want in hashes.items():
            result = self.generate(spec, app, tier)
            self.assertEqual(result.problems, [])
            self.assertEqual(result.manual, [])
            got = hashlib.sha256(strip_home(result.text).encode("utf-8")).hexdigest()
            self.assertEqual(got, want, "%s builder changed" % tier)
            for name in self.NEW + self.SESSION:
                self.assertNotIn(name, result.text)
            for page in result.app["pages"]:
                for vs in page["visuals"]:
                    if vs["type"] == "kpi":                   # no default marking added without features
                        self.assertNotIn("marking", vs)

    def test_well_tear_sheet(self):
        example = SKILL / "assets" / "examples" / "well-tear-sheet"
        app = self.tmp / "apps" / "well-tear-sheet"
        (app / "data").mkdir(parents=True)
        shutil.copytree(example / "html", app / "html")
        for name in ("WELL_SUMMARY", "CASH_FLOW_ANNUAL", "PRODUCTION_MONTHLY", "PV_PROFILE", "BREAKEVENS",
                     "RESERVES", "LOE_PER_BOE", "SENSITIVITIES", "DILIGENCE_FLAGS"):
            (app / "data" / (name + ".sbdf")).write_bytes(b"stub sbdf")
        self.check(json.loads((example / "spec.json").read_text(encoding="utf-8")), app, self.WTS)

    def test_minimal(self):
        app = self.tmp / "apps" / "Minimal"
        app.mkdir(parents=True)
        self.check(minimal_spec(), app, self.MINIMAL)

    def test_featured_app_without_new_keys_gets_only_the_guard(self):
        spec = test_features.fixture_spec()
        spec["app"].pop("theme", None)                         # a manual step
        for c in spec["pages"][0]["visuals"]:
            c.pop("controls", None)                            # controls are a feature of their own
        result = self.generate(spec, self.app(spec, files=test_features.FILES))
        self.assertIn("recheck", result.text)
        for name in self.SESSION:
            self.assertIn(name, result.text)                   # the switch comes with the guard
        for name in self.NEW[1:]:
            self.assertNotIn(name, result.text)
        self.assertNotIn("guard", [p.name for p in t3.engine_parts([], "standard", set())])


# ------------------------------------------------------------------------------------------------
# validation
# ------------------------------------------------------------------------------------------------
class KitchenValidationTests(KitchenTestCase):
    def errors(self, report):
        return [(e["path"], e["message"]) for e in report.errors]

    def test_fixture_is_clean(self):
        report = self.validate(kitchen_spec())
        self.assertEqual(report.errors, [], report.render())
        self.assertFalse([w for w in report.warnings if "unknown field" in w["message"]], report.render())

    def has(self, items, path, text):
        self.assertTrue([1 for p, m in items if path in p and text in m], items)

    def test_action_mod_references(self):
        spec = kitchen_spec()
        c = spec["pages"][0]["visuals"][0]["controls"]
        c["run"]["actionMod"] = {"mod": "nope", "script": "add-window"}
        c["toDetail"]["actionMod"] = {"mod": MOD_ID, "script": "add-windw", "args": {}}
        trend = spec["pages"][0]["visuals"][1]
        trend["actionTriggers"][0]["actionMod"]["args"] = {"kind": "Weird", "extra": 1}
        trend["actionTriggers"][1]["display"] = "Hover"
        errors = self.errors(self.validate(spec))
        self.has(errors, "controls.run.actionMod.mod", "unknown action mod 'nope'")
        self.has(errors, "controls.toDetail.actionMod.script", "has no script 'add-windw'")
        self.has(errors, "actionTriggers[0].actionMod.args.kind", "must be one of Normal, Anomaly")
        self.has(errors, "actionTriggers[0].actionMod.args.extra", "has no parameter 'extra'")
        self.has(errors, "actionTriggers[1].display", "must be one of FloatingButton")

    def test_missing_manifest_is_a_warning(self):
        spec = kitchen_spec()
        spec["actionMods"][0]["project"] = "nowhere"
        report = self.validate(spec)
        self.assertEqual(report.errors, [], report.render())
        warnings = [(w["path"], w["message"]) for w in report.warnings]
        self.has(warnings, "actionMods[0].project", "folder not found")
        self.has(warnings, "actionMod.script", "is not checked")

    def test_manifest_id_must_match(self):
        spec = kitchen_spec()
        spec["actionMods"][0]["id"] = "other-id"
        for v in spec["pages"][0]["visuals"]:
            for t in v.get("actionTriggers", []):
                t["actionMod"]["mod"] = "other-id"
            for c in (v.get("controls") or {}).values():
                if c.get("actionMod"):
                    c["actionMod"]["mod"] = "other-id"
        self.has(self.errors(self.validate(spec)), "actionMods[0].id", "the manifest's id is")

    def test_legend_hide_js_names_and_settings_shorthands(self):
        spec = kitchen_spec()
        spec["pages"][0]["visuals"][1]["legend"]["hide"].append("axes")
        spec["pages"][0]["visuals"][0]["js"].append({"name": "Apply Window", "code": "var a = 1;"})
        spec["pages"][0]["visuals"][4]["settings"]["LimitingMarkingsEmptyBehavior"] = "Hide"
        errors = self.errors(self.validate(spec))
        self.has(errors, "legend.hide[3]", '"axes" is not a legend item kind')
        self.has(errors, "js[2]", "has the name of an IronPython script")
        if dxpgen.find_index_file() is not None:              # the settings paths are checked in the index
            self.has(errors, "Data.LimitingMarkingsEmptyBehavior", "'Hide' is not a member")

    def test_same_js_name_with_other_code(self):
        spec = kitchen_spec()
        spec["pages"][1]["visuals"].insert(0, {"id": "detailGuide", "type": "textArea", "title": "Guide",
                                               "showTitle": False, "html": HOST_HTML,
                                               "js": [{"name": "Note Render", "code": "var other = 2;"}]})
        spec["pages"][1]["layout"] = {"row": [{"visual": "detailGuide"}, {"visual": "events"}]}
        self.has(self.errors(self.validate(spec)), "js[0]", "differs from the one of the same name")

    def test_button_without_script_warns(self):
        spec = kitchen_spec()
        run = spec["pages"][0]["visuals"][0]["controls"]["run"]
        del run["script"]
        del run["args"]
        report = self.validate(spec)
        self.assertEqual(report.errors, [], report.render())
        self.has([(w["path"], w["message"]) for w in report.warnings], "controls.run", "actionMod without 'script'")
        self.assertFalse([w for w in report.warnings if "controls.toDetail" in w["path"]])   # gotoPage is its action


# ------------------------------------------------------------------------------------------------
# engine functions in CPython with stand-ins
# ------------------------------------------------------------------------------------------------
def part_scope(name, features, scope):
    path = t3.ENGINE_DIR / "features" / (name + ".py")
    part = _assemble.Part(name, path, path.read_text(encoding="utf-8"), "standard", features)
    exec(compile("\n".join(part.code), name, "exec"), scope)
    return scope


class EngineFunctionTests(unittest.TestCase):
    def test_guard(self):
        """recheck() names what to check after a manual save; no engine part reaches Spotfire's internal
        idle check (the builder relies on the inline save and the refused-save log line)."""
        app = {"marking": ["Marking", None], "markings": [["Label Window", "#333D66"]]}
        scope = part_scope("guard", {"guard"}, {"why": str, "APP": app})
        text = scope["recheck"]()
        self.assertIn("Markings must list Marking, Label Window", text)
        self.assertIn("General > Description", text)
        for path in sorted(t3.ENGINE_DIR.rglob("*.py")):
            code = path.read_text(encoding="utf-8")
            for word in ("ValidateApplicationIsIdle", "NonPublic", "@internal"):
                self.assertNotIn(word, code, path.name)

    def test_session_switch(self):
        """switch_session(): a 'Build Session' page made active, then SaveAs to build\\session\\
        ~build-session-<tag>.dxp (never the saved DXP), then the log line; a failed step is logged and
        the saved DXP is left alone."""
        out = "C:\\apps\\Demo\\build\\Demo v2 & co standard.dxp"
        log_file = "C:\\apps\\Demo\\build\\build-log-standard.txt"

        class FakePath(object):
            @staticmethod
            def GetFileNameWithoutExtension(p):
                return p.rsplit("\\", 1)[-1].rsplit(".", 1)[0]

            @staticmethod
            def GetDirectoryName(p):
                return p.rsplit("\\", 1)[0]

            @staticmethod
            def Combine(*parts):
                return "\\".join(parts)

        made = []

        class FakeDirectory(object):
            @staticmethod
            def CreateDirectory(p):
                made.append(p)

        class TextArea(object):
            HtmlContent = None

        class Visual(object):
            def __init__(self):
                self.Title, self.ShowTitle, self.area = None, True, TextArea()
                self.As = {"HtmlTextArea": lambda: self.area}

        class Page(object):
            def __init__(self, title):
                self.Title = title
                self.added = []
                outer = self

                class Visuals(object):
                    @staticmethod
                    def AddNew(type_id):
                        v = Visual()
                        outer.added.append((type_id, v))
                        return v
                self.Visuals = Visuals()

        class Pages(object):
            def __init__(self):
                self.items = []

            def AddNew(self, title):
                page = Page(title)
                self.items.append(page)
                return page

        class Doc(object):
            def __init__(self):
                self.Pages = Pages()
                self.ActivePageReference = None

        def run(fail_save=False, fail_page=False):
            saved = []

            class App(object):
                @staticmethod
                def SaveAs(path, settings):
                    if fail_save:
                        raise Exception("not idle")
                    saved.append(path)

            log = []

            def ok(name, fn, *args):
                try:
                    return fn(*args)
                except Exception as e:
                    log.append("FAILED " + name + ": " + str(e))
                    return None

            doc = Doc()
            if fail_page:
                doc.Pages = None
            scope = {"why": str, "APP": {"marking": ["Marking", None]}, "OUT": out,
                     "LOG_FILE": log_file, "LOG": log, "ok": ok, "Document": doc, "Application": App,
                     "Path": FakePath, "Directory": FakeDirectory, "DocumentSaveSettings": lambda: "settings",
                     "HtmlTextArea": "HtmlTextArea",
                     "VisualTypeIdentifiers": type("VT", (), {"HtmlTextArea": "HtmlTextAreaId"})}
            part = part_scope("guard", {"guard"}, scope)          # Part.code has no imports
            part["switch_session"]()
            return doc, saved, log

        scratch = "C:\\apps\\Demo\\build\\session\\~build-session-standard.dxp"
        doc, saved, log = run()
        self.assertEqual(saved, [scratch])
        self.assertNotIn(out, saved)
        self.assertIn("C:\\apps\\Demo\\build\\session", made)
        page = doc.Pages.items[0]
        self.assertEqual(page.Title, "Build Session")
        self.assertIs(doc.ActivePageReference, page)
        type_id, visual = page.added[0]
        self.assertEqual((type_id, visual.ShowTitle), ("HtmlTextAreaId", False))
        html = visual.area.HtmlContent
        self.assertIn("This is the build session, not the app. Closing the Document Properties dialog resets "
                      "its markings.", html)
        self.assertIn("Close this analysis without saving and open:", html)
        self.assertIn("Demo v2 &amp; co standard.dxp", html)               # the path, HTML-escaped
        for bad in ("<style", "<script", "<button", "<input", "url(", "var("):
            self.assertNotIn(bad, html)
        self.assertEqual(log, ["Session re-pointed to " + scratch + " - open the saved DXP to use the app"])

        doc, saved, log = run(fail_save=True)                   # the re-point fails: logged, no retry
        self.assertEqual(saved, [])
        self.assertTrue(log[0].startswith("FAILED build session save: not idle"), log)
        self.assertTrue(log[1].startswith("NOTE this analysis may still be linked to " + out), log)

        doc, saved, log = run(fail_page=True)                   # no page: still re-pointed
        self.assertEqual(saved, [scratch])
        self.assertTrue(log[0].startswith("FAILED build session page"), log)
        self.assertTrue(log[1].startswith("Session re-pointed to "), log)

    def test_legend_items(self):
        class Item(object):
            def __init__(self, type_name):
                self.Visible = True
                self.name = type_name

            def GetType(self):
                return type("T", (), {"Name": self.name})()

        names = ("LegendFilteringsItem", "LegendMarkingItem", "LegendGroupByItem", "LegendColorItem",
                 "LegendReferenceLayerItem", "LegendFittingModelCollectionItem", "LegendTrellisItem",
                 "LegendTitleItem")
        items = [Item(n) for n in names]
        content = type("C", (), {"Legend": type("L", (), {"Items": items})()})()
        visualization = object()
        visual = type("V", (), {"As": {visualization: lambda: content}})()
        scope = part_scope("legend", {"legendHide"}, {"Visualization": visualization})
        scope["hide_legend_items"](visual, {"legendHide": ["filtering", "marking", "referenceLayers"]})
        hidden = [i.name for i in items if not i.Visible]
        self.assertEqual(hidden, ["LegendFilteringsItem", "LegendMarkingItem", "LegendReferenceLayerItem",
                                  "LegendFittingModelCollectionItem"])
        self.assertEqual(sorted(scope["LEGEND_ITEMS"]), sorted(dxpgen.LEGEND_HIDE_KINDS))

    def test_feature_blocks_strip_cleanly(self):
        """The feature blocks leave datafunctions.py, core.py, text.py and report.py free of the feature
        code when the features are off (the builders of apps without them stay byte-identical)."""
        for rel in ("features/datafunctions.py", "core.py", "builders/text.py", "report.py"):
            path = t3.ENGINE_DIR / rel
            text = path.read_text(encoding="utf-8")
            off = _assemble.Part(path.stem, path, text, "standard", {"controls", "dataFunctions", "settings"})
            code = "\n".join(off.code)
            for name in ("marked_rows", "text_scripts", "hide_legend_items", "recheck", "switch_session",
                         "SESSION_PAGE", "load_viz", "new_mod_visual", "MOD_PLACEHOLDERS", "VIZ_FIX",
                         "rename_starter_page", 'APP["manual"]'):
                self.assertNotIn(name, code, rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
