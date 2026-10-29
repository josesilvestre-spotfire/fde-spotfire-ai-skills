"""Tests for versioned releases: the builder preflight (engine/features/preflight.py, t3.files_read: an
older builder pasted after the app folder changed stops before it changes anything) and dxpgen release (a
frozen copy per version in <app>/versions/vX.Y with the builder generated from it).

Run: python -m unittest tests/test_release.py   (or python -m unittest discover -s tests)

The fixture app (temporary folder) is the Pipeline kitchen of test_pipeline_kinds (sbdf tables, data
functions, IronPython scripts, text-area HTML and JavaScript files, an action-mod project) plus the
folders a release must leave out. One release runs the real paste-safety checks (lint_ipy.py,
ipy_parse.ps1 when Windows PowerShell and Spotfire Analyst 15.0 are installed, sfapi.py); the engine
functions run in CPython with stand-ins. Nothing starts Spotfire.
"""
import contextlib
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
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(HERE))
import dxpgen  # noqa: E402
import slim_builder  # noqa: E402
import t3  # noqa: E402
from t3 import _assemble  # noqa: E402
import test_pipeline_kinds as tp  # noqa: E402
import test_kitchen_features as tw  # noqa: E402
from test_dxpgen import minimal_spec  # noqa: E402

EXTRA = {"DESIGN.md": "# Design\n", "build/RUN-STEPS.md": "Paste the builder.\n", "tools/assemble_dfs.py": "x = 1\n",
         "datafunctions/_src/line_physics.py": "y = 2\n", "_work/scratch.txt": "w\n", "source/app.py": "p\n",
         "docs/guide.md": "d\n", "devtests/t.py": "t\n", "build/session/~build-session.dxp": "scratch",
         "build/build_PipelineKitchen_standard.py": "# the live builder\n",
         "actionmod/node_modules/lib/index.js": "n\n", "tools/__pycache__/assemble_dfs.cpython-314.pyc": "c"}
VERSION_FILES = ["spec.json", "DESIGN.md", "VERSION.md", "build/RUN-STEPS.md", "tools/assemble_dfs.py",
                 "datafunctions/_src/line_physics.py", "datafunctions/make_data.py", "scripts/apply_window.py",
                 "html/controls.html", "html/Apply Template Styles.js", "actionmod/mod-manifest.json",
                 "actionmod/build/add-window.js", "data/ROUTE.sbdf", "data/WEATHER.sbdf"]
LEFT_OUT = ["_work", "source", "docs", "devtests", "build/session", "actionmod/node_modules", "tools/__pycache__",
            "data/UNUSED.sbdf", "build/build_PipelineKitchen_standard.py"]


def release_spec():
    spec = tp.pipeline_spec()
    spec["pages"][0]["visuals"][0]["html"] = "html/controls.html"      # an HTML file the builder reads
    return spec


def preflight_scope(home, app, exists):
    """engine/features/preflight.py run in CPython: File.Exists and Path.Combine stand-ins."""
    class File(object):
        Exists = staticmethod(exists)

    class Path_(object):
        @staticmethod
        def Combine(a, b):
            return a + "\\" + b
    part = _assemble.Part("preflight", t3.ENGINE_DIR / "features" / "preflight.py",
                          (t3.ENGINE_DIR / "features" / "preflight.py").read_text(encoding="utf-8"),
                          "standard", {"preflight"})
    scope = {"File": File, "Path": Path_, "HOME": home, "APP": app}
    exec(compile("\n".join(part.code), "preflight", "exec"), scope)
    return scope


class ReleaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="release-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, spec=None):
        app = self.tmp / "apps" / "PipelineKitchen"
        for rel, text in list(tp.FILES.items()) + list(EXTRA.items()):
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for rel, data in list(tp.SBDF.items()) + [("data/UNUSED.sbdf", b"unused")]:
            (app / rel).parent.mkdir(parents=True, exist_ok=True)
            (app / rel).write_bytes(data)
        (app / "spec.json").write_text(json.dumps(spec or release_spec(), indent=2), encoding="utf-8")
        return app.resolve()               # the long path (the temp folder may be an 8.3 short name)

    def release(self, app, version="v2.1", lint=False, **kw):
        out = io.StringIO()
        options = dxpgen.Options(lint=lint, sanitize=False, tools_dir=SKILL / "scripts")
        with contextlib.redirect_stderr(io.StringIO()):
            code = dxpgen.release_app(app, app / "spec.json", options, version, out=out, **kw)
        return code, out.getvalue()


# ------------------------------------------------------------------------------------------------
# the preflight
# ------------------------------------------------------------------------------------------------
class PreflightTests(ReleaseTestCase):
    def test_engine_functions(self):
        files = ["data\\A.sbdf", "html\\a.html", "scripts\\b.py", "scripts\\c.py", "datafunctions\\d.py",
                 "html\\e.js"]
        home = "C:\\apps\\Pipeline\\versions\\v2.0"
        scope = preflight_scope(home, {"files": files, "spec": "9b07ddfd3a69"},
                                lambda p: p.endswith("A.sbdf"))
        missing = scope["missing_files"]()
        self.assertEqual(missing, files[1:])
        self.assertEqual(scope["mismatch_text"](missing),
                         "This builder does not match the files in C:\\apps\\Pipeline\\versions\\v2.0: missing "
                         "html\\a.html, scripts\\b.py, scripts\\c.py, datafunctions\\d.py (and 1 more). Use the "
                         "builder that belongs to this version (see versions\\README.md). Nothing was changed.")
        self.assertEqual(scope["log_stamp"]("No problems."), "[spec 9b07ddfd3a69] No problems.")
        scope["APP"]["release"] = "v2.0"
        self.assertEqual(scope["log_stamp"]("1 problem(s), the build went on:"),
                         "[v2.0, spec 9b07ddfd3a69] 1 problem(s), the build went on:")
        self.assertEqual(preflight_scope(home, {"files": files}, lambda p: True)["missing_files"](), [])

    def test_core_runs_it_before_the_first_change_and_stamps_the_log(self):
        core = (t3.ENGINE_DIR / "core.py").read_text(encoding="utf-8")
        check = core.index("MISSING = missing_files()")
        self.assertLess(core.index("OPENED_FROM = "), check)                   # after the opened-from guard
        self.assertLess(check, core.index("STARTER_TABLES = "))                # before anything changes
        self.assertIn("if MISSING:\n    raise Exception(mismatch_text(MISSING))", core)
        for part in ("core.py", "report.py"):                                  # report replaces write_log
            text = (t3.ENGINE_DIR / part).read_text(encoding="utf-8")
            self.assertIn("    # @feature preflight\n    head = log_stamp(head)\n    # @endfeature\n"
                          "    File.WriteAllText(LOG_FILE", text, part)

    def test_featured_builder_lists_every_file_it_reads(self):
        app = self.app()
        spec = release_spec()
        mods = tp.PipelineTestCase.generate(self, spec, app, "standard")
        ipy = tp.PipelineTestCase.generate(self, spec, app, "report")
        for result in (mods, ipy):
            self.assertEqual(result.problems, [])
            self.assertIn("preflight", result.features)
            self.assertEqual(result.text.count("MISSING = missing_files()"), 1)
            self.assertEqual(slim_builder.text_problems(result.text), [])
            self.assertEqual(slim_builder.undefined_names(result.text), {})
            self.assertEqual(list(result.app)[:5], ["name", "output", "log", "spec", "files"])
            self.assertEqual(result.app["spec"], tw.META["spec_sha"][:12])
            self.assertNotIn("release", result.app)
        want = ["data\\ROUTE.sbdf", "data\\STATIONS.sbdf", "data\\WEATHER.sbdf", "data\\RESIDUALS.sbdf",
                "datafunctions\\make_data.py", "datafunctions\\score_data.py", "datafunctions\\track_window.py",
                "scripts\\add_window.py", "scripts\\apply_window.py",
                "html\\controls.html", "html\\Apply Template Styles.js"]
        self.assertEqual(mods.app["files"], want)                 # no action-mod file: a manual step
        self.assertEqual(ipy.app["files"], want)
        for rel in want:
            self.assertTrue((app / rel.replace("\\", "/")).is_file(), rel)
        self.assertIn("head = log_stamp(head)", ipy.text)                      # the report tier's write_log

    def test_release_meta_and_featureless_builders(self):
        app = self.app()
        resolved = dxpgen.resolve_spec(release_spec(), app)
        meta = dict(tw.META, release="v2.1")
        result = t3.generate(resolved, release_spec(), app, "standard", dxpgen.column_reader(resolved), meta)
        self.assertEqual(result.app["release"], "v2.1")
        self.assertIn("# Release v2.1: HOME is the version folder versions\\v2.1", result.text)
        plain = self.tmp / "apps" / "Minimal"
        plain.mkdir(parents=True)
        bare = tw.KitchenTestCase.generate(self, minimal_spec(), plain, "standard")
        self.assertEqual(bare.features, set())
        for name in ("missing_files", "log_stamp", '"files"'):
            self.assertNotIn(name, bare.text)        # apps without features keep their proven builders

    def test_action_mods_are_never_files_the_builder_reads(self):
        app = self.tmp / "mods"
        (app / "proj").mkdir(parents=True)
        (app / "proj" / "m1.mod").write_text("x")
        (app / "proj" / "mod-manifest.json").write_text("{}")
        entry = {"actionMods": [["m1", "proj"], ["m2"]], "pages": []}
        self.assertEqual(t3.files_read(entry, app), [])                       # wired by hand after the build


# ------------------------------------------------------------------------------------------------
# dxpgen release
# ------------------------------------------------------------------------------------------------
class ReleaseTests(ReleaseTestCase):
    def test_release_copies_generates_checks_and_records(self):
        app = self.app()
        code, out = self.release(app, lint=True, notes="Scenario tabs | first try")
        self.assertEqual(code, 0, out)
        vdir = app / "versions" / "v2.1"
        for rel in VERSION_FILES:
            self.assertTrue((vdir / rel).is_file(), rel)
        for rel in LEFT_OUT:
            self.assertFalse((vdir / rel).exists(), rel)
        self.assertEqual(sorted(p.name for p in (app / "build").iterdir()),
                         ["RUN-STEPS.md", "build_PipelineKitchen_standard.py", "session"])
        self.assertIn("lint 0 error(s)", out)
        self.assertNotIn("is not in the 15.0 index", out)
        if "IronPython parse not run" not in out:
            self.assertIn("PARSE OK", out)
        for target in (vdir / "build" / "build_PipelineKitchen_v2.1_standard.py",):
            self.assertIn(str(target), out)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(slim_builder.text_problems(text), [])
            home, app_literal = dxpgen.builder_literals(text)
            self.assertEqual(home, str(vdir))
            self.assertEqual(app_literal["output"], "build\\Pipeline Kitchen standard.dxp")
            self.assertEqual(app_literal["release"], "v2.1")
            self.assertEqual(app_literal["spec"], dxpgen.sha256_bytes((app / "spec.json").read_bytes())[:12])
            self.assertEqual(dxpgen.release_check(target, vdir), [])
        readme = (app / "versions" / "README.md").read_text(encoding="utf-8")
        self.assertIn(dxpgen.VERSIONS_TABLE_HEAD, readme)
        row = [line for line in readme.splitlines() if line.startswith("| v2.1 |")]
        self.assertEqual(len(row), 1, readme)
        self.assertIn("| build_PipelineKitchen_v2.1_standard.py |", row[0])
        self.assertIn("| none yet (saves v2.1\\build\\Pipeline Kitchen standard.dxp) ", row[0])
        self.assertIn("| %s | Scenario tabs / first try |" % dxpgen.STATUS_READY, row[0])
        self.assertIn("build_PipelineKitchen_v2.1_standard.py", (vdir / "VERSION.md").read_text())
        self.assertTrue((vdir / "build" / "MANUAL-STEPS-standard.md").is_file())

        # the stale-builder case: a file the version's builder reads is gone -> it stops, naming it
        _, literal = dxpgen.builder_literals(
            (vdir / "build" / "build_PipelineKitchen_v2.1_standard.py").read_text(encoding="utf-8"))
        (vdir / "scripts" / "apply_window.py").unlink()
        scope = preflight_scope(str(vdir), literal, os.path.isfile)
        self.assertEqual(scope["missing_files"](), ["scripts\\apply_window.py"])
        self.assertTrue(scope["mismatch_text"](["scripts\\apply_window.py"]).startswith(
            "This builder does not match the files in %s: missing scripts\\apply_window.py." % vdir))

    def test_never_overwrites_a_version(self):
        app = self.app()
        self.assertEqual(self.release(app)[0], 0)
        readme = app / "versions" / "README.md"
        before = readme.read_text(encoding="utf-8")
        code, out = self.release(app)
        self.assertEqual(code, dxpgen.EXIT_USAGE, out)
        self.assertIn("already exists", out)
        self.assertEqual(readme.read_text(encoding="utf-8"), before)
        code, out = self.release(app, force=True, notes="regenerated")             # never built: allowed
        self.assertEqual(code, 0, out)
        rows = [line for line in readme.read_text(encoding="utf-8").splitlines() if line.startswith("| v2.1 |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("regenerated", rows[0])
        dxp = app / "versions" / "v2.1" / "build" / "Pipeline Kitchen standard.dxp"
        dxp.write_bytes(b"the good build")
        code, out = self.release(app, force=True)
        self.assertEqual(code, dxpgen.EXIT_USAGE, out)
        self.assertIn("holds a saved DXP", out)
        self.assertEqual(dxp.read_bytes(), b"the good build")

    def test_aborts_before_copying(self):
        app = self.app()
        self.assertEqual(self.release(app, version="2.1")[0], dxpgen.EXIT_USAGE)
        self.assertEqual(self.release(app / "versions" / "v2.0", version="v2.1")[0], dxpgen.EXIT_USAGE)
        spec = release_spec()
        spec["scripts"][0]["file"] = "scripts/gone.py"                       # the spec names a missing file
        (app / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        code, out = self.release(app)
        self.assertEqual(code, dxpgen.EXIT_INVALID, out)
        self.assertIn("nothing was copied", out)
        outside = self.tmp / "shared.html"
        outside.write_text("<p>x</p>")
        spec = release_spec()
        spec["pages"][0]["visuals"][0]["html"] = "../../shared.html"
        (app / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        code, out = self.release(app)
        self.assertEqual(code, dxpgen.EXIT_INVALID, out)
        self.assertIn("outside the app folder", out)
        self.assertFalse((app / "versions").exists())
        plain = self.tmp / "apps" / "Minimal"
        plain.mkdir(parents=True)
        (plain / "spec.json").write_text(json.dumps(minimal_spec()), encoding="utf-8")
        self.assertEqual(self.release(plain, tier="slim")[0], dxpgen.EXIT_USAGE)       # the standard engine only

    def test_readme_keeps_hand_written_rows(self):
        readme = self.tmp / "versions" / "README.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# App - versions\n\nRules.\n\n| Version | Date | Spec hash | Builders | Saved DXP | "
                          "Status | Notes |\n|---|---|---|---|---|---|---|\n| v1.0 | 2026-10-03 | aaa | b.py | "
                          "v1.0\\build\\A.dxp | Good | kept |\n\nFooter.\n", encoding="utf-8")
        dxpgen.update_versions_readme(readme, "App", ["v2.0", "d", "h", "b2.py", "-", "Generated", "n"])
        dxpgen.update_versions_readme(readme, "App", ["v2.0", "d", "h2", "b2.py", "-", "Generated", "again"])
        lines = readme.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[:3], ["# App - versions", "", "Rules."])
        self.assertIn("| v1.0 | 2026-10-03 | aaa | b.py | v1.0\\build\\A.dxp | Good | kept |", lines)
        self.assertEqual([x for x in lines if x.startswith("| v2.0")], ["| v2.0 | d | h2 | b2.py | - | Generated | again |"])
        self.assertEqual(lines.index("| v2.0 | d | h2 | b2.py | - | Generated | again |"), 7)
        self.assertEqual(lines[-1], "Footer.")
        fresh = self.tmp / "new" / "README.md"
        dxpgen.update_versions_readme(fresh, "New App", ["v1.0", "d", "h", "b", "-", "s", ""])
        text = fresh.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# New App - versions\n"))
        self.assertTrue(text.endswith(dxpgen.VERSIONS_TABLE_RULE + "\n| v1.0 | d | h | b | - | s |  |\n"))
        self.assertTrue(text.isascii())

    def test_cli(self):
        args = dxpgen.build_parser().parse_args(["release", "x", "--version", "v2.1", "--notes", "n", "--force"])
        self.assertEqual((args.command, args.version, args.notes, args.force, args.tier),
                         ("release", "v2.1", "n", True, "standard"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(dxpgen.main(["release", "x"]), dxpgen.EXIT_USAGE)          # --version required


if __name__ == "__main__":
    unittest.main()
