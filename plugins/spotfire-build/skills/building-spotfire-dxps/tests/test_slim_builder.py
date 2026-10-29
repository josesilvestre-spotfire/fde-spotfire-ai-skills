"""Tests for scripts/slim_builder.py. Run: python -m unittest tests/test_slim_builder.py

Temporary app folders only, no external tools (lint and sanitizer off), nothing starts Spotfire.
"""
import ast
import contextlib
import io
import json
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
from test_dxpgen import FULL_FILES, full_spec, minimal_spec  # noqa: E402


def library_parts():
    return [(f.name, f.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")) for f in dxpgen.library_files()]


def top_level_defs(text):
    return set(s.name for s in ast.parse(text).body if isinstance(s, (ast.FunctionDef, ast.ClassDef)))


class SlimBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="slim-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_app(self, spec, files):
        app = self.tmp / "apps" / "PumpStation"
        for rel, content in files.items():
            path = app / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        app.mkdir(parents=True, exist_ok=True)
        (app / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return app

    def slim(self, spec, files, tag=None):
        app = self.write_app(spec, files)
        resolved = dxpgen.resolve_spec(spec, app)
        if tag:
            resolved["app"]["output"] = slim_builder.tagged_output(resolved["app"]["output"], tag)
        code, info = slim_builder.slim_library(library_parts(), resolved)
        text = slim_builder.render_slim(resolved, app, "PumpStation", "a" * 64, "b" * 64, code, info, tag,
                                        "2026-10-01T00:00:00")
        errors = [m for level, m in slim_builder.check_builder(text, resolved) if level == "error"]
        self.assertEqual(errors, [])
        return resolved, text, info

    def test_full_spec_keeps_every_feature_it_uses(self):
        resolved, text, info = self.slim(full_spec(), FULL_FILES)
        defs = top_level_defs(text)
        for name in ("df_build_all", "scripts_add_all", "scripts_add_triggers", "data_relations",
                     "data_add_properties", "data_filtering_schemes", "_textareas_manual",
                     "_textareas_attach", "attach_js", "_data_csv_settings", "_data_calculated_column",
                     "apply_reference_layers", "vis_line", "vis_bar", "vis_table", "vis_textarea"):
            self.assertIn(name, defs)
        for name in ("vis_map", "vis_mod", "vis_pie", "vis_kpi", "apply_fitting_models"):
            self.assertNotIn(name, defs)
        self.assertEqual(sorted(info["builders"]), ["barChart", "lineChart", "table", "textArea"])

    def test_minimal_spec_drops_and_stubs_unused_features(self):
        resolved, text, info = self.slim(minimal_spec(), {}, tag="T9")
        defs = top_level_defs(text)
        self.assertIn("df_build_all = _slim_stub('df_build_all')", text)
        self.assertNotIn("vis_line", defs)
        self.assertNotIn("df_build", defs)
        self.assertEqual(resolved["app"]["output"], "build/Pump Station Monitor T9.dxp")
        self.assertEqual(info["builders"], {"textArea": "vis_textarea"})
        self.assertLess(len(text), 100000)

    def test_whole_library_rewraps_to_79_characters(self):
        for module, source in library_parts():
            noqa = slim_builder.noqa_comments(source)
            for node in ast.parse(source).body:
                # wrap_source itself raises when the wrapped code parses to a different AST
                wrapped = slim_builder.wrap_source(slim_builder.unparse_unit(node, slim_builder.INDENT), noqa)
                self.assertLessEqual(max(len(line) for line in wrapped.split("\n")), 79, module)

    def test_wrap_line_cases(self):
        cases = ["x = '" + "a b " * 40 + "'",                                       # string at depth 0
                 "from System import " + ", ".join("Name%d" % i for i in range(20)),   # long import
                 "  if alpha_value and beta_value or gamma_value and delta_value or epsilon_value:"]
        for line in cases:
            out = slim_builder.wrap_line(line)
            self.assertTrue(all(len(x) <= 79 for x in out), out)
            self.assertEqual(ast.dump(ast.parse("\n".join(out).strip() + "\n    pass" if line.endswith(":")
                                                else "\n".join(out))),
                             ast.dump(ast.parse(line.strip() + "\n    pass" if line.endswith(":") else line)))
        out = slim_builder.wrap_line("        visual.Render(g, Rectangle(0, 0, bounds.Width, bounds.Height))",
                                     comment="# noqa: obsolete")
        self.assertTrue(out[0].endswith("# noqa: obsolete") and "visual.Render(" in out[0], out)

    def test_spec_literal_round_trips(self):
        value = {"html": '<p class="x">' + "word " * 60 + "\u00e9\\'\"" + "x" * 150 + "</p>",
                 "numbers": [1, 2.5, -3, True, None], "nested": {"k" * 60: ["v" * 90, {}]}}
        text = slim_builder.spec_literal(value)
        self.assertTrue(text.isascii())
        self.assertLessEqual(max(len(line) for line in text.split("\n")), 79)
        self.assertEqual(ast.literal_eval(text[len("SPEC = "):]), value)

    def test_cli_writes_a_checked_builder(self):
        app = self.write_app(minimal_spec(), {})
        tools = self.tmp / "tools"
        tools.mkdir()
        target = self.tmp / "out" / "slim.py"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = slim_builder.main([str(app), "--tag", "T1", "--out", str(target), "--no-lint",
                                      "--no-sanitize", "--tools-dir", str(tools)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("slim builder:", out.getvalue())
        text = target.read_text(encoding="utf-8")
        self.assertTrue(text.isascii() and text.rstrip().endswith("run_build()"))
        self.assertEqual(slim_builder.undefined_names(text), {})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(slim_builder.main([str(app), "--tag", "bad tag"]), dxpgen.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
