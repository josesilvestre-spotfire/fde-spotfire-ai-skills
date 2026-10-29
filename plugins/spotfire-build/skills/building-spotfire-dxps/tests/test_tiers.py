"""Tests for the standard engine and the builder tiers (scripts/engine, scripts/t3, dxpgen build --tier).

Run: python -m unittest tests/test_tiers.py   (or python -m unittest discover -s tests)

Temporary app folders only; lint, the IronPython parser and sfapi.py are off (an empty tools folder),
nothing starts Spotfire. The well-tear-sheet tests use assets/examples/well-tear-sheet (spec.json,
html/) with stub data files.
"""
import ast
import contextlib
import copy
import io
import json
import os
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
from t3 import _assemble, _literal  # noqa: E402
from test_dxpgen import minimal_spec  # noqa: E402

EXAMPLE = SKILL / "assets" / "examples" / "well-tear-sheet"
WTS_TABLES = ("WELL_SUMMARY", "CASH_FLOW_ANNUAL", "PRODUCTION_MONTHLY", "PV_PROFILE", "BREAKEVENS",
              "RESERVES", "LOE_PER_BOE", "SENSITIVITIES", "DILIGENCE_FLAGS")


def literals(text):
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("HOME", "STYLE", "APP"):
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def resolve_colors(node, palette, theme=False):
    """'@name' -> '#RRGGBB' (or 'rgb(r, g, b)' inside the theme, as the engine writes it)."""
    if isinstance(node, dict):
        return dict((k, resolve_colors(v, palette, theme or k == "theme")) for k, v in node.items())
    if isinstance(node, list):
        return [resolve_colors(v, palette, theme) for v in node]
    if isinstance(node, str) and node.startswith("@") and node[1:] in palette:
        h = palette[node[1:]].lstrip("#")
        if theme:
            return "rgb(%d, %d, %d)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        return "#" + h
    return node


def functions(text):
    return set(n.name for n in ast.parse(text).body if isinstance(n, ast.FunctionDef))


class EngineFilesTests(unittest.TestCase):
    def test_registry_has_the_nine_kinds_with_builders(self):
        """text, kpi, table, line, bar and cross, plus scatter and map (tests/test_pipeline_kinds.py) and
        mod (tests/test_mod_engine.py: its TYPE_IDS entry is the placeholder text area)."""
        kinds = t3.kinds()
        self.assertEqual(sorted(kinds), ["bar", "cross", "kpi", "line", "map", "mod", "scatter", "table",
                                         "text"])
        self.assertEqual(t3.kind_of("lineChart"), "line")
        self.assertIsNone(t3.kind_of("pieChart"))
        for kind, mod in kinds.items():
            for attr in ("KIND", "SPEC_TYPES", "STYLE_KEYS", "HANDLED", "convert"):
                self.assertTrue(hasattr(mod, attr), (kind, attr))
            text = t3.builder_path(kind).read_text(encoding="utf-8")
            self.assertIn("def build_%s(v, vs):" % kind, text)
            self.assertIn('BUILDERS["%s"] = build_%s' % (kind, kind), text)
            m = re.search(r'TYPE_IDS\["%s"\] = "(\w+)"' % kind, text)
            self.assertTrue(m, kind)
            self.assertIn("VisualTypeIdentifiers." + m.group(1), text)        # in its @api list
            for key, check, tier in mod.STYLE_KEYS:
                self.assertIn(tier, ("compact", "quick", "standard"), (kind, key))

    def test_every_engine_part_parses_in_every_tier(self):
        paths = [t3.ENGINE_DIR / "core.py", t3.ENGINE_DIR / "report.py"]
        paths += sorted((t3.ENGINE_DIR / "builders").glob("*.py"))
        paths += sorted((t3.ENGINE_DIR / "features").glob("*.py"))
        for tier in t3.TIERS:
            for path in paths:
                for features in (None, set()):          # every feature on / none
                    part = _assemble.Part(path.stem, path, path.read_text(encoding="utf-8"), tier, features)
                    ast.parse("\n".join(part.code))
                    for line in part.code:
                        self.assertFalse(line.strip().startswith("# @") and line.strip() != "# @builders", line)
                        self.assertLessEqual(len(line), 79, (path.name, line))
                        self.assertTrue(line.isascii(), (path.name, line))

    def test_tier_blocks(self):
        lines = ["a", "# @tier quick", "b", "# @end", "    # @tier standard", "    c", "    # @end", "d"]
        self.assertEqual(_assemble.strip_tiers(lines, 0), ["a", "d"])
        self.assertEqual(_assemble.strip_tiers(lines, 1), ["a", "b", "d"])
        self.assertEqual(_assemble.strip_tiers(lines, 2), ["a", "b", "    c", "d"])
        for bad in (["# @tier quick", "# @tier standard", "# @end", "# @end"], ["# @end"], ["# @tier quick"],
                    ["# @tier fancy", "# @end"]):
            with self.assertRaises(ValueError):
                _assemble.strip_tiers(bad, 2)

    def test_imports_are_merged_and_pruned(self):
        imp = _assemble.Imports()
        for text in ("import clr", 'clr.AddReference("System.Drawing")', "import json",
                     "from System import Single, Int32", "from System import Double, Int32"):
            imp.add(ast.parse(text).body[0], text)
        self.assertEqual(imp.render({"Single", "Double"}),
                         ["import clr", 'clr.AddReference("System.Drawing")', "from System import Single, Double"])
        long = _assemble.render_from("Spotfire.Dxp.Application.Visuals", ["Name%d" % i for i in range(12)])
        self.assertTrue(all(len(line) <= 79 for line in long))
        self.assertEqual(ast.dump(ast.parse("\n".join(long))),
                         ast.dump(ast.parse("from Spotfire.Dxp.Application.Visuals import %s"
                                            % ", ".join("Name%d" % i for i in range(12)))))


class LiteralTests(unittest.TestCase):
    def test_round_trip_short_lines(self):
        value = {"description": "word " * 40 + "caf\u00e9 \"quoted\" \\ back", "n": [1, 2.5, None, True],
                 "nested": {"k" * 30: [["NAME", {"x": ["v" * 70, "w"]}], {}, []]}}
        text = _literal.literal("APP", value)
        self.assertTrue(text.isascii())
        self.assertLessEqual(max(len(line) for line in text.split("\n")), 79)
        self.assertEqual(ast.literal_eval(text[len("APP = "):]), value)

    def test_home_literal(self):
        path = r"D:\Work\Spotfire\DXP Workspace\apps\a-rather-long-app-name\and-more\and-more"
        text = _literal.home_literal(path)
        self.assertLessEqual(max(len(line) for line in text.split("\n")), 79)
        self.assertEqual(ast.literal_eval(text[len("HOME = "):]), path)
        self.assertEqual(_literal.home_literal(r"C:\apps\x"), 'HOME = r"C:\\apps\\x"')


class TierTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tiers-test-"))
        self.tools = self.tmp / "tools"           # empty: no lint, no IronPython parser, no sfapi
        self.tools.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wts_app(self, spec=None, slug="well-tear-sheet"):
        app = self.tmp / "apps" / slug
        (app / "data").mkdir(parents=True)
        shutil.copytree(EXAMPLE / "html", app / "html")
        for name in WTS_TABLES:
            (app / "data" / (name + ".sbdf")).write_bytes(b"stub sbdf")
        if spec is None:
            spec = json.loads((EXAMPLE / "spec.json").read_text(encoding="utf-8"))
        (app / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return app

    def app_with(self, spec, files=None, slug="TierApp"):
        app = self.tmp / "apps" / slug
        app.mkdir(parents=True)
        for rel, content in (files or {}).items():
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8") if isinstance(content, str) else p.write_bytes(content)
        (app / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return app

    def build(self, app, tier):
        out = io.StringIO()
        options = dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tools)
        with contextlib.redirect_stderr(io.StringIO()):
            code = dxpgen.build_app(app, app / "spec.json", options, out=out, tier=tier)
        return code, out.getvalue()

    def generate(self, spec, app, tier="standard"):
        resolved = dxpgen.resolve_spec(spec, app)
        return t3.generate(resolved, spec, app, tier, dxpgen.column_reader(resolved),
                           {"spec_sha": "0" * 64, "generated": "2026-10-02T00:00:00"})


class WellTearSheetTests(TierTestCase):
    def test_all_tiers_build_and_pass_the_static_checks(self):
        app = self.wts_app()
        sizes = {}
        for tier in ("standard", "quick", "compact", "report", "slim"):
            code, out = self.build(app, tier)
            self.assertEqual(code, 0, out)
            path = app / "build" / ("build_well-tear-sheet_%s.py" % tier)
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            self.assertEqual(slim_builder.text_problems(text), [], tier)
            self.assertEqual(slim_builder.undefined_names(text), {}, tier)
            self.assertIn("Well Tear Sheet %s.dxp" % tier, text)
            self.assertIn("Execute in transaction", text)
            self.assertIn('untick "Execute in transaction"', out)
            sizes[tier] = len(text)
        self.assertLess(sizes["compact"], sizes["quick"])
        self.assertLess(sizes["quick"], sizes["standard"])
        self.assertLess(sizes["standard"], sizes["report"])
        self.assertLess(sizes["report"], sizes["slim"])
        self.assertLess(sizes["standard"], 60000)

    def test_tiers_carry_the_styling_of_their_level(self):
        app = self.wts_app()
        texts = {}
        for tier in ("compact", "quick", "standard", "report"):
            self.assertEqual(self.build(app, tier)[0], 0)
            texts[tier] = (app / "build" / ("build_well-tear-sheet_%s.py" % tier)).read_text(encoding="utf-8")
        quick = {"font", "table_fonts", "negatives", "axis_fonts", "legend_font", "label_font", "kpi_font"}
        standard = {"formatter", "kpi_format", "kpi_tiles", "kpi_empty", "column_width", "y_format",
                    "line_width", "cell_width", "row_header_width"}
        report = {"write_report", "manual_text", "render_page", "render_visual", "after_save", "fix_for"}
        for tier, want, absent in (("compact", set(), quick | standard | report),
                                   ("quick", quick, standard | report),
                                   ("standard", quick | standard, report),
                                   ("report", quick | standard | report, set())):
            defs = functions(texts[tier])
            self.assertTrue(want <= defs, (tier, want - defs))
            self.assertFalse(absent & defs, (tier, absent & defs))
            self.assertNotIn("apply_theme", defs)                              # no public API sets it
        compact = literals(texts["compact"])["STYLE"]
        self.assertNotIn("theme", compact)
        self.assertNotIn("font", compact)
        quick_style = literals(texts["quick"])["STYLE"]
        self.assertNotIn("theme", quick_style)
        self.assertIn("font", quick_style)
        self.assertNotIn("cellWidth", quick_style["visual"]["cross"])
        self.assertNotIn("import json", texts["compact"])                      # unused imports dropped
        report_app = literals(texts["report"])["APP"]
        self.assertEqual(report_app["tag"], "report")
        self.assertEqual(report_app["snapshots"], [1600, 900])
        self.assertEqual(report_app["log"], "build\\build-log-report.txt")

    def test_standard_keeps_the_example_style(self):
        app = self.wts_app()
        self.assertEqual(self.build(app, "standard")[0], 0)
        gen_text = (app / "build" / "build_well-tear-sheet_standard.py").read_text(encoding="utf-8")
        gen = literals(gen_text)
        style = resolve_colors(gen["STYLE"], gen["STYLE"]["palette"])
        self.assertEqual(style["font"], "Segoe UI")
        self.assertEqual(style["negative"], "#BA2C48")
        self.assertEqual(style["visual"]["cross"]["cellWidth"], 84)
        self.assertEqual(gen["APP"]["output"], "build\\Well Tear Sheet standard.dxp")
        for name in ("load", "set_format", "marking", "add_page", "build_visual", "apply_layout", "finish",
                     "build_kpi", "build_table", "build_line", "build_bar", "build_cross", "build_text"):
            self.assertIn(name, functions(gen_text))

    def test_compact_matches_the_compact_variant_level(self):
        app = self.wts_app()
        self.assertEqual(self.build(app, "compact")[0], 0)
        text = (app / "build" / "build_well-tear-sheet_compact.py").read_text(encoding="utf-8")
        app_literal = literals(text)["APP"]
        visuals = dict((v["id"], v) for p in app_literal["pages"] for v in p["visuals"])
        self.assertEqual(visuals["pvTable"]["columns"], ["Discount Rate", "PV ($)", "NPV after Price ($)"])
        self.assertNotIn("negatives", visuals["sensitivities"])
        self.assertNotIn("yFormat", visuals["oilRate"])
        self.assertEqual(visuals["oilRate"]["color"], "#71AB3C")
        self.assertEqual(visuals["oilRate"]["yMin"], 0)
        self.assertEqual(len(visuals["cumCash"]["refs"]), 2)
        self.assertEqual([k[2] for k in visuals["metrics"]["kpis"]], [None] * 7)
        for name in ("SetTheme", "FontMetadata", "AddThresholdColorRule", "CellWidth", "RealFormatter"):
            self.assertNotIn(name, text)


class UnsupportedTests(TierTestCase):
    def test_visual_type_without_builder(self):
        spec = minimal_spec()
        spec["tables"] = [{"name": "T", "source": {"type": "sbdf", "path": "data/T.sbdf"}}]
        spec["pages"][0]["visuals"].append({"id": "pie", "type": "pieChart", "title": "Pie", "table": "T",
                                            "sector": "<[A]>", "size": "Count()"})
        spec["pages"][0]["layout"] = {"row": [{"visual": "intro"}, {"visual": "pie"}]}
        app = self.app_with(spec, {"data/T.sbdf": b"stub"})
        code, out = self.build(app, "standard")
        self.assertEqual(code, 1, out)
        self.assertIn("pages[0].visuals[1]: visual type 'pieChart' is not in the standard engine yet: use "
                      "--tier slim", out)
        self.assertFalse((app / "build" / "build_TierApp_standard.py").exists())
        code, out = self.build(app, "slim")                   # the exception tier builds it
        self.assertEqual(code, 0, out)

    def test_unsupported_fields_are_listed(self):
        spec = json.loads((EXAMPLE / "spec.json").read_text(encoding="utf-8"))
        visuals = spec["pages"][0]["visuals"]
        oil = [v for v in visuals if v["id"] == "oilRate"][0]
        oil["trellis"] = {"panelBy": "<[Period]>"}             # trellis and y individual scaling: built
        oil["yScale"]["individualScaling"] = True              # built (and min and max)
        oil["xScale"] = {"individualScaling": True}            # ... x individual scaling not
        bar = [v for v in visuals if v["id"] == "liftCost"][0]
        bar["labels"] = True                       # horizontal bars are built since 2026-10-02
        sens = spec["pages"][1]["visuals"][2]
        sens["coloring"][0]["rules"][0]["color"] = "#00FF00"   # a cell coloring: built since 2026-10-02 ...
        sens["coloring"][0]["rules"][0]["settings"] = {"ManualDisplayName": "Below zero"}   # ... rule settings not
        cross = spec["pages"][1]["visuals"][0]
        cross["totals"] = {"rows": True, "columns": False}
        app = self.wts_app(spec)
        result = self.generate(json.loads((app / "spec.json").read_text(encoding="utf-8")), app)
        paths = [p for p, _ in result.problems]
        for want in ("pages[0].visuals[5].xScale.individualScaling",
                     "pages[0].visuals[8].labels", "pages[1].visuals[2].coloring[0].rules[0].settings",
                     "pages[1].visuals[0].totals"):
            self.assertIn(want, paths)
        for built in ("pages[0].visuals[5].trellis", "pages[0].visuals[5].yScale.individualScaling"):
            self.assertNotIn(built, paths)
        self.assertTrue(all("not in the standard engine yet: use --tier slim" in m for _, m in result.problems))


class ConverterTests(TierTestCase):
    def test_conversions(self):
        spec = json.loads((EXAMPLE / "spec.json").read_text(encoding="utf-8"))
        app = self.wts_app(spec)
        result = self.generate(spec, app)
        self.assertEqual(result.problems, [])
        self.assertEqual(result.notes, ["table descriptions"])
        visuals = dict((v["id"], v) for p in result.app["pages"] for v in p["visuals"])
        self.assertEqual(visuals["header"], {"id": "header", "type": "text", "title": "Header",
                                             "html": "header.html"})
        self.assertEqual(visuals["sensitivities"]["negatives"], ["PV10 Change ($)", "NPV10 ($)", "PV10 ($)"])
        self.assertEqual(visuals["breakevens"]["columns"], [["Metric", 180], ["Value", 110], ["Unit", 60]])
        self.assertEqual(visuals["liftCost"]["stack"], True)
        self.assertEqual(visuals["cumCash"]["refs"][1], {"label": "Payback Jan-2032", "axis": "X",
                                                         "value": 'Date("2032-01-16")', "color": "#111110",
                                                         "dash": "dot"})
        self.assertEqual(visuals["cashFlow"]["rows"], "<[Axis.Default.Names]>")
        self.assertEqual(visuals["cashFlow"]["columns"], "<[Calendar Period]>")
        self.assertNotIn("totals", visuals["cashFlow"])
        self.assertEqual(visuals["metrics"]["kpis"][3], ["IRR", "Sum([IRR])", "pct1"])
        layout = result.app["pages"][0]["layout"]
        self.assertEqual(layout["column"][3]["row"][0], {"column": [{"visual": "oilRate"},
                                                                    {"visual": "gasRate"}]})
        tables = dict((e[0], e) for e in result.app["tables"])
        self.assertEqual(tables["BREAKEVENS"], ["BREAKEVENS", {"num2": ["Value"]}])
        self.assertEqual(tables["DILIGENCE_FLAGS"], ["DILIGENCE_FLAGS", {}])

    def test_inline_html_navigation_and_house_style(self):
        spec = minimal_spec()
        spec["app"]["pageNavigation"] = "Links"
        app = self.app_with(spec)
        result = self.generate(spec, app, "quick")
        self.assertEqual(result.problems, [])
        intro = result.app["pages"][0]["visuals"][0]
        self.assertEqual(intro["htmlText"], spec["pages"][0]["visuals"][0]["html"])
        self.assertEqual(intro["showTitle"], True)              # SPEC default, house text default is False
        self.assertEqual(result.app["navigation"], "Links")
        self.assertEqual(result.app["marking"], ["Marking", None])
        style = result.style
        self.assertNotIn("theme", style)
        self.assertEqual(sorted(style["palette"]), ["ink", "neg"])
        self.assertEqual(style["formats"], {})
        self.assertEqual(sorted(style["visual"]), ["text"])

    def test_visuals_without_table_use_the_default_table(self):
        spec = {"specVersion": 1, "app": {"name": "Sales", "pageNavigation": "Tabs"},
                "tables": [{"name": "SALES", "source": {"type": "sbdf", "path": "inputs/SALES.sbdf"},
                            "columns": {"Share": {"format": "0.0 %"}}}],
                "pages": [{"title": "Overview", "visuals": [
                    {"id": "b", "type": "barChart", "title": "Share", "x": "<[Region]>",
                     "y": ["Sum([A]) as [A]", "Sum([B]) as [B]"], "stack": "sideBySide"},
                    {"id": "c", "type": "crossTable", "title": "Cross", "rows": ["Region"],
                     "measures": ["Sum([A]) as [A]"], "totals": {"rows": True, "columns": True}}],
                    "layout": {"row": [{"visual": "b"}, {"visual": "c"}]}}]}
        app = self.app_with(spec, {"inputs/SALES.sbdf": b"stub"})
        result = self.generate(spec, app)
        self.assertEqual(result.problems, [])
        b, c = result.app["pages"][0]["visuals"]
        self.assertEqual((b["table"], c["table"], result.app["defaultTable"]), ("SALES", "SALES", "SALES"))
        self.assertEqual(b["colorBy"], "<[Axis.Default.Names]>")          # several measures: Column Names
        self.assertEqual(b["stack"], "sideBySide")
        self.assertEqual(c["columns"], "<[Axis.Default.Names]>")          # no column levels: Column Names
        self.assertEqual(c["rows"], "<[Region]>")
        self.assertTrue(c["totals"])
        self.assertEqual(result.app["tables"], [["SALES", {"0.0 %": ["Share"]}, "inputs\\SALES.sbdf"]])

    def test_engine_style_keys_reach_app_only_from_their_tier(self):
        spec = json.loads((EXAMPLE / "spec.json").read_text(encoding="utf-8"))
        app = self.wts_app(spec)
        oil = lambda r: [v for v in r.app["pages"][0]["visuals"] if v["id"] == "oilRate"][0]   # noqa: E731
        self.assertEqual(oil(self.generate(spec, app, "standard"))["lineWidth"], 2)
        self.assertNotIn("lineWidth", oil(self.generate(spec, app, "quick")))
        self.assertNotIn("yFormat", oil(self.generate(spec, app, "compact")))


class StyleValidationTests(TierTestCase):
    def validate(self, spec, files=None):
        app = self.app_with(spec, files)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tools))
        return report

    def messages(self, report, level):
        return [(i["path"], i["message"]) for i in report.items if i["level"] == level]

    def test_app_style_is_checked(self):
        spec = minimal_spec()
        spec["app"]["style"] = {"palette": {"ink": "#11111", "brand": "#3050EF"}, "text": "@nope",
                                "formats": {"money": 5}, "colour": 1,
                                "visual": {"kpi": {"baseFont": -1, "fancy": 1}, "gauge": {}}}
        report = self.validate(spec)
        errors = self.messages(report, "error")
        warnings = self.messages(report, "warning")
        for path in ("app.style.palette.ink", "app.style.text", "app.style.formats.money",
                     "app.style.visual.kpi.baseFont"):
            self.assertTrue(any(p == path for p, _ in errors), (path, errors))
        for path in ("app.style.colour", "app.style.visual.kpi.fancy", "app.style.visual.gauge"):
            self.assertTrue(any(p == path for p, _ in warnings), (path, warnings))

    def test_per_visual_style_keys(self):
        spec = json.loads((EXAMPLE / "spec.json").read_text(encoding="utf-8"))
        app = self.wts_app(spec)
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tools))
        self.assertEqual([i for i in report.items if i["level"] in ("error", "warning")
                          and "SBDF" not in i["message"]
                          and "has no filter layout" not in i["message"]], [])   # design rule of 2026-10-06
        visuals = spec["pages"][0]["visuals"]
        visuals[5]["yFormat"] = 3
        visuals[1]["kpis"][0]["format"] = "mony"
        visuals[2]["negatives"] = ["Nope"]
        visuals[2]["cellWidth"] = 10
        (app / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        report, _, _ = dxpgen.validate_app(app, app / "spec.json",
                                           dxpgen.Options(lint=False, sanitize=False, tools_dir=self.tools))
        errors = [i["path"] for i in report.errors]
        warnings = [i["path"] for i in report.warnings]
        self.assertIn("pages[0].visuals[5].yFormat", errors)
        self.assertIn("pages[0].visuals[2].negatives[0]", errors)
        self.assertIn("pages[0].visuals[1].kpis[0].format", warnings)
        self.assertIn("pages[0].visuals[2].cellWidth", warnings)          # a cross-table key on a table


class CliTests(TierTestCase):
    def test_unknown_tier_is_a_usage_error(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dxpgen.main(["build", str(self.tmp), "--tier", "fancy"])
        self.assertEqual(code, dxpgen.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
