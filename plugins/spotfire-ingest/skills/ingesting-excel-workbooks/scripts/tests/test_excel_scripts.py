"""Tests for the Excel ingest scripts. They run every script on the synthetic
fixture workbooks and check that each seeded defect is found.

    python scripts/tests/test_excel_scripts.py
    python -m unittest discover -s scripts/tests

Needs pandas for the calculation model tests; openpyxl is optional (cross-check).
Excel is never started.
"""

import contextlib
import csv
import datetime as dt
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL = SCRIPTS.parent
EXAMPLE = SKILL / "assets" / "examples" / "line-pressure-profile"
sys.path.insert(0, str(SCRIPTS))

import calc_model_scaffold  # noqa: E402
import check_handoff  # noqa: E402
import dossier  # noqa: E402
import excel_cases  # noqa: E402
import excel_compat as XC  # noqa: E402
import export_data_function  # noqa: E402
import inventory  # noqa: E402
import issues as I  # noqa: E402
import make_fixtures  # noqa: E402
import reconcile as R  # noqa: E402
import structure as S  # noqa: E402
import xlsxlib as X  # noqa: E402

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def run_cli(module, argv):
    """Run a script's main() with arguments; return (exit code, stdout)."""
    old = sys.argv
    out = io.StringIO()
    sys.argv = [module.__name__] + [str(a) for a in argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = module.main()
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = old
    return code, out.getvalue()


def build_skill_folder():
    """The building-spotfire-dxps skill folder: $BUILDING_SPOTFIRE_DXPS, else the
    library's own layout (plugins/spotfire-build/...), else None."""
    import os
    env = os.environ.get("BUILDING_SPOTFIRE_DXPS")
    candidates = [Path(env)] if env else []
    candidates.append(SKILL.parents[2] / "spotfire-build" / "skills" / "building-spotfire-dxps")
    for folder in candidates:
        if (folder / "scripts" / "dxpgen.py").exists():
            return folder
    return None


def in_range(cell, rng):
    r, c, _, _ = X.parse_cell(cell)
    r1, c1, r2, c2 = X.parse_range(rng)
    return r1 <= r <= r2 and c1 <= c <= c2


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="excel_ingest_"))
        cls.books = {}
        for name, build in make_fixtures.BUILDERS.items():
            path = cls.tmp / name
            build(path)
            cls.books[name] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestFormulaTools(unittest.TestCase):
    def test_r1c1_equal_for_filled_down_copies(self):
        a = X.to_r1c1("F5*(B5/(C5/12))*Density*D5^2", 5, 7)
        b = X.to_r1c1("F6*(B6/(C6/12))*Density*D6^2", 6, 7)
        self.assertEqual(a, b)
        self.assertNotEqual(X.to_r1c1("$C$5*2", 19, 6), X.to_r1c1("C19*2", 19, 6))

    def test_tokens_skip_strings_and_functions(self):
        kinds = [(t.kind, t.text) for t in X.tokenize('=LOG10(C5)&"A1"&\'Well A\'!B2')
                 if t.kind != "ws"]
        self.assertIn(("func", "LOG10"), kinds)
        self.assertIn(("str", '"A1"'), kinds)
        self.assertIn(("ref", "'Well A'!B2"), kinds)
        self.assertNotIn(("ref", "A1"), kinds)

    def test_shift(self):
        self.assertEqual(X.shift("A1+$B$2+B$3", 2, 1), "B3+$B$2+C$3")
        self.assertEqual(X.shift("A1", -1, 0), "#REF!")


class TestReaderAndInventory(Fixtures):
    def test_reader_matches_openpyxl(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl is not installed")
        for path in self.books.values():
            wb = X.load(path)
            result = inventory.crosscheck(path, wb)
            for row in result["sheets"]:
                self.assertTrue(row["match"], f"{path.name} {row}")

    def test_inventory_features(self):
        _, pipe = inventory.run(self.books["pipe_pressure_drop.xlsx"], self.tmp / "inv_pipe")
        self.assertEqual(len(pipe["definedNames"]), 5)
        self.assertEqual(pipe["totals"]["dataValidations"], 1)
        self.assertEqual(pipe["totals"]["conditionalFormats"], 1)
        self.assertEqual(pipe["totals"]["charts"], 1)
        self.assertEqual(pipe["totals"]["tables"], 1)
        self.assertEqual(pipe["totals"]["errors"], 1)
        self.assertTrue((self.tmp / "inv_pipe" / "snapshots" / "04-Calc.values.csv").exists())
        _, decline = inventory.run(self.books["production_decline.xlsx"],
                                   self.tmp / "inv_decline")
        self.assertEqual(len(decline["dataTables"]), 1)
        self.assertEqual(decline["dataTables"][0]["r1"], "B4")
        _, econ = inventory.run(self.books["project_economics.xlsx"], self.tmp / "inv_econ")
        self.assertEqual(len(econ["externalLinks"]), 1)
        self.assertEqual(econ["externalLinks"][0]["target"], "price_deck.xlsx")
        self.assertTrue(econ["calculation"]["iterative"])
        self.assertIn("solver_opt", econ["solver"])
        self.assertEqual([s["state"] for s in econ["sheets"]].count("hidden"), 1)

    def test_vba_and_pivot_detection(self):
        src = self.books["pipe_pressure_drop.xlsx"]
        dst = self.tmp / "with_vba.xlsm"
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                zout.writestr(info, zin.read(info.filename))
            zout.writestr("xl/vbaProject.bin", b"not a real VBA project")
            zout.writestr("xl/pivotCache/pivotCacheDefinition1.xml",
                          '<pivotCacheDefinition xmlns="http://schemas.openxmlformats.org/'
                          'spreadsheetml/2006/main"><cacheSource type="worksheet">'
                          '<worksheetSource ref="A1:D21" sheet="Segments"/></cacheSource>'
                          '</pivotCacheDefinition>')
        wb = X.load(dst)
        self.assertTrue(wb.vba)
        self.assertEqual(list(wb.pivot_caches.values())[0]["sheet"], "Segments")
        items, _ = I.scan(wb)
        self.assertIn("vba-macros", {i["type"] for i in items})

    def test_shipped_fixtures_are_current(self):
        shipped = SKILL / "assets" / "fixtures"
        for name, path in self.books.items():
            with zipfile.ZipFile(path) as fresh, zipfile.ZipFile(shipped / name) as old:
                self.assertEqual(sorted(fresh.namelist()), sorted(old.namelist()), name)
                for part in fresh.namelist():
                    self.assertEqual(fresh.read(part), old.read(part), f"{name} {part}")


class TestStructureAndIssues(Fixtures):
    def test_blocks_and_exceptions(self):
        st = S.analyze(X.load(self.books["pipe_pressure_drop.xlsx"]))
        by_range = {(b.sheet, b.range): b for b in st.blocks}
        velocity = by_range[("Calc", "D5:D24")]
        self.assertEqual(len(velocity.cells), 20)
        self.assertEqual(velocity.unit, "ft/s")
        friction = by_range[("Calc", "F5:F24")]
        self.assertEqual([X.addr(r, c) for r, c in friction.exceptions], ["F19"])
        self.assertEqual(by_range[("Calc", "G14")].role, "override")
        self.assertEqual(by_range[("Calc", "M5:M24")].role, "terminal")
        self.assertEqual(by_range[("Lookups", "A3:B7")].role, "lookup")
        self.assertEqual(by_range[("Segments", "A2:D21")].role, "raw data")

    def test_templates_cycles_and_indirect(self):
        st = S.analyze(X.load(self.books["production_decline.xlsx"]))
        self.assertEqual(len(st.families), 1)
        self.assertEqual(st.families[0]["sheets"], ["Well A", "Well B", "Well C", "Well D"])
        notes = [n for b in st.blocks for n in b.dynamic]
        self.assertTrue(any("resolved from stored values" in n for n in notes))
        econ = S.analyze(X.load(self.books["project_economics.xlsx"]))
        self.assertGreaterEqual(len(econ.cycles), 1)

    def test_seeded_defects_found(self):
        for name, seeded in make_fixtures.SEEDED.items():
            items, _ = I.scan(X.load(self.books[name]))
            for kind, sheet, cell in seeded:
                hits = [i for i in items if i["type"] == kind and i["sheet"] == sheet and
                        in_range(cell, i["range"])]
                self.assertTrue(hits, f"{name}: {kind} at {sheet}!{cell} not found; found "
                                f"{[(i['type'], i['sheet'], i['range']) for i in items]}")

    def test_issue_severity_and_questions(self):
        items, _ = I.scan(X.load(self.books["pipe_pressure_drop.xlsx"]))
        high = {i["type"] for i in items if i["severity"] == "high"}
        self.assertTrue({"typed-over-formula", "broken-pattern", "mixed-units",
                         "approximate-lookup", "error-value", "iferror-masks"} <= high)
        self.assertTrue(all(i["question"] for i in items))

    def test_ingest_workbook_and_dossier(self):
        out = self.tmp / "ingest_pipe"
        code, text = run_cli(__import__("ingest_workbook"), [self.books["pipe_pressure_drop.xlsx"],
                                                     "--out", out])
        self.assertEqual(code, 0)
        for name in ("inventory.json", "structure.json", "dependencies.mmd", "issues.json",
                     "issues.csv", "dossier.html"):
            self.assertTrue((out / name).exists(), name)
        html_text = (out / "dossier.html").read_text(encoding="utf-8")
        self.assertIn("Questions for the owner", html_text)
        self.assertIn("Checkpoint 1", html_text)
        self.assertIn("Calc!G14", html_text)
        shutil.copy(EXAMPLE / "ingest" / "meaning.json", out / "meaning.json")
        html_text = dossier.render(out)
        self.assertIn("Estimate the pressure at the outlet", html_text)
        self.assertIn("Swamee-Jain", html_text)


class TestExcelCompat(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(XC.xround(2.675, 2), 2.68)
        self.assertEqual(XC.xround(-2.5), -3.0)
        self.assertEqual(XC.xround(0.5), 1.0)
        self.assertEqual(XC.xround(1234.5, -2), 1200.0)
        self.assertEqual(XC.roundup(1.21, 1), 1.3)
        self.assertEqual(XC.rounddown(-1.29, 1), -1.2)
        self.assertEqual(XC.sig15(0.1 + 0.2), 0.3)
        self.assertEqual(XC.text_general(0.1 + 0.2), "0.3")

    def test_dates_1900_system(self):
        self.assertEqual(XC.to_serial(dt.date(1900, 1, 1)), 1.0)
        self.assertEqual(XC.to_serial(dt.date(1900, 2, 28)), 59.0)
        self.assertEqual(XC.to_serial(dt.date(1900, 3, 1)), 61.0)
        self.assertEqual(XC.to_serial(dt.date(2025, 1, 1)), 45658.0)
        self.assertEqual(XC.from_serial(59).date(), dt.date(1900, 2, 28))
        self.assertEqual(XC.from_serial(61).date(), dt.date(1900, 3, 1))
        with self.assertRaises(XC.ExcelError):
            XC.from_serial(60)
        jan31 = XC.to_serial(dt.date(2025, 1, 31))
        self.assertEqual(XC.from_serial(XC.edate(jan31, 1)).date(), dt.date(2025, 2, 28))
        self.assertEqual(XC.to_serial(dt.date(1904, 1, 2), date1904=True), 1.0)

    def test_empty_cells_and_errors(self):
        self.assertEqual(XC.arith(None), 0.0)
        self.assertEqual(XC.arith(True), 1.0)
        self.assertEqual(XC.xsum([1.0, None, "text", True, 2.0]), 3.0)
        self.assertEqual(XC.average([1.0, None, 3.0]), 2.0)
        self.assertEqual(XC.xmax([]), 0.0)
        with self.assertRaises(XC.ExcelError):
            XC.div(1.0, None)
        with self.assertRaises(XC.ExcelError):
            XC.power(-8.0, 1 / 3)
        del XC.HIDDEN_ERRORS[:]
        self.assertEqual(XC.iferror(lambda: XC.average(["#DIV/0!", 1.0]), 0.0, "B7"), 0.0)
        self.assertEqual(XC.HIDDEN_ERRORS[0]["error"], "#DIV/0!")

    def test_lookups(self):
        rows = [[0.0, "a"], [10.0, "b"], [20.0, "c"]]
        self.assertEqual(XC.vlookup(15.0, rows, 2), "b")
        self.assertEqual(XC.vlookup(10.0, rows, 2, approximate=False), "b")
        with self.assertRaises(XC.ExcelError):
            XC.vlookup(15.0, rows, 2, approximate=False)
        with self.assertRaises(XC.ExcelError):
            XC.vlookup(-1.0, rows, 2)
        self.assertEqual(XC.match("B", ["a", "b", "c"], 0), 2.0)
        self.assertTrue(XC.eq("Steel", "STEEL"))

    def test_finance(self):
        self.assertAlmostEqual(XC.npv(0.1, [110.0]), 100.0)
        self.assertAlmostEqual(XC.irr([-100.0, 110.0]), 0.1, places=9)
        self.assertAlmostEqual(XC.pmt(0.0, 10, 1000.0), -100.0)


@unittest.skipIf(pd is None, "pandas is not installed")
class TestModelReconcileExport(Fixtures):
    def _example_model(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("example_model",
                                                      EXAMPLE / "ingest" / "calc_model.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _expected(self):
        omap = json.loads((EXAMPLE / "ingest" / "output-map.json").read_text(encoding="utf-8"))
        path = self.tmp / "expected.csv"
        R.write_long(R.extract_expected(self.books["pipe_pressure_drop.xlsx"], omap), path)
        return path

    def _actual(self, change=None):
        model = self._example_model()
        result = model.run()
        rows = []
        for name, value in result.items():
            items = value.items() if isinstance(value, dict) else [(1, value)]
            for index, v in items:
                if change and (name, str(index)) == change[0]:
                    v = v + change[1]
                rows.append(("stored", name, str(index), v))
        path = self.tmp / "actual.csv"
        R.write_long(rows, path)
        return path, model

    def test_example_model_reconciles(self):
        expected = self._expected()
        actual, model = self._actual()
        code, _ = run_cli(R, ["compare", "--expected", expected, "--actual", actual,
                              "--map", EXAMPLE / "ingest" / "output-map.json",
                              "--logic-spec", EXAMPLE / "logic-spec.md",
                              "--out", self.tmp / "recon"])
        self.assertEqual(code, 0)
        report = (self.tmp / "recon.md").read_text(encoding="utf-8")
        self.assertIn("**Result: PASS**", report)
        self.assertIn("logic-spec default", report)

    def test_difference_is_caught_and_can_be_explained(self):
        expected = self._expected()
        actual, _ = self._actual(change=(("Outlet Pressure (psi)", "12"), 0.01))
        code, _ = run_cli(R, ["compare", "--expected", expected, "--actual", actual,
                              "--out", self.tmp / "recon_fail"])
        self.assertEqual(code, 1)
        with open(self.tmp / "recon_fail.csv", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        failed = [r for r in rows if r["status"] == "FAIL"]
        self.assertEqual([(r["output"], r["index"]) for r in failed],
                         [("Outlet Pressure (psi)", "12")])
        explain = self.tmp / "explain.csv"
        explain.write_text("output,index,explanation\nOutlet Pressure (psi),12,"
                           "accepted by the owner\n", encoding="utf-8")
        code, _ = run_cli(R, ["compare", "--expected", expected, "--actual", actual,
                              "--explain", explain, "--out", self.tmp / "recon_explained"])
        self.assertEqual(code, 0)
        code, _ = run_cli(R, ["compare", "--expected", expected, "--actual", actual,
                              "--tolerance", "abs=0.05", "--out", self.tmp / "recon_tol"])
        self.assertEqual(code, 0)

    def test_wide_export_like_a_dxp_table(self):
        expected = self._expected()
        per_segment = self.tmp / "expected_segments.csv"
        with open(expected, encoding="utf-8") as fh, open(per_segment, "w", newline="",
                                                          encoding="utf-8") as out:
            lines = fh.read().splitlines()
            out.write("\n".join([lines[0]] + [ln for ln in lines[1:] if ln.split(",")[1] in (
                "Velocity (ft/s)", "Outlet Pressure (psi)", "Pressure Gradient (psi/ft)")]))
        model = self._example_model()
        table = model.spotfire_outputs(model.run())["SEGMENT_RESULTS"]
        wide = self.tmp / "SEGMENT_RESULTS.csv"
        table.to_csv(wide, index=False)
        code, _ = run_cli(R, ["compare", "--expected", per_segment, "--actual", wide,
                              "--key", "Segment", "--out", self.tmp / "recon_wide"])
        self.assertEqual(code, 0, (self.tmp / "recon_wide.md").read_text(encoding="utf-8"))
        values = model.spotfire_outputs(model.run())
        props = self.tmp / "properties.csv"
        names = ("TotalPressureDrop", "OutletPressure", "MaxVelocity", "AverageGradient")
        props.write_text(",".join(names) + "\n" +
                         ",".join(repr(values[k]) for k in names) + "\n", encoding="utf-8")
        scalars = self.tmp / "expected_scalars.csv"
        with open(expected, encoding="utf-8") as fh, open(scalars, "w", newline="",
                                                          encoding="utf-8") as out:
            lines = fh.read().splitlines()
            out.write("\n".join([lines[0]] + [ln for ln in lines[1:] if ln.split(",")[1] in (
                "Total Pressure Drop (psi)", "Outlet Pressure at Line End (psi)",
                "Maximum Velocity (ft/s)", "Average Gradient (psi/ft)")]))
        code, _ = run_cli(R, ["compare", "--expected", scalars, "--actual", props,
                              "--map", EXAMPLE / "ingest" / "output-map.json",
                              "--out", self.tmp / "recon_props"])
        self.assertEqual(code, 0, (self.tmp / "recon_props.md").read_text(encoding="utf-8"))

    def test_export_data_function_matches_model(self):
        target = self.tmp / "calculate_pressure_profile.py"
        export_data_function.export(EXAMPLE / "ingest" / "calc_model.py", target,
                                    "Calculate Pressure Profile")
        ns = {"FlowRate": 12000.0, "FluidDensity": 53.0, "Viscosity": 4.5, "PipeAge": 25.0,
              "InletPressure": 950.0,
              "SEGMENTS": pd.read_csv(EXAMPLE / "data" / "SEGMENTS.csv"),
              "ROUGHNESS_BY_AGE": pd.read_csv(EXAMPLE / "data" / "ROUGHNESS_BY_AGE.csv")}
        exec(compile(target.read_text(encoding="utf-8"), str(target), "exec"), ns)
        model = self._example_model()
        reference = model.spotfire_outputs(model.run())
        self.assertEqual(ns["OutletPressure"], reference["OutletPressure"])
        self.assertTrue(ns["SEGMENT_RESULTS"].equals(reference["SEGMENT_RESULTS"]))
        shipped = (EXAMPLE / "datafunctions" / "calculate_pressure_profile.py").read_text(
            encoding="utf-8")
        self.assertEqual(shipped, target.read_text(encoding="utf-8"))

    def test_scaffold_for_every_fixture(self):
        for name, path in self.books.items():
            out = self.tmp / f"scaffold_{Path(name).stem}"
            code, _ = run_cli(calc_model_scaffold, [path, "--out", out])
            self.assertEqual(code, 0)
            omap = json.loads((out / "output-map.json").read_text(encoding="utf-8"))
            self.assertTrue(omap["outputs"], name)
            self.assertTrue((out / "excel_compat.py").exists())
            sys.path.insert(0, str(out))
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(f"scaffold_{name}",
                                                              out / "calc_model.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(module.run(), {})
            finally:
                sys.path.remove(str(out))
            rows = R.extract_expected(path, omap)
            self.assertTrue(rows)


class TestCasesAndHandoff(Fixtures):
    def test_case_copies(self):
        cases = self.tmp / "cases.csv"
        cases.write_text("case,Inputs!B3,Inputs!B6\nlow_flow,6000,25\nold_pipe,12000,32\n",
                         encoding="utf-8")
        written = excel_cases.make(self.books["pipe_pressure_drop.xlsx"], cases,
                                   self.tmp / "cases")
        self.assertEqual(len(written), 2)
        wb = X.load(written[0])
        self.assertEqual(wb.sheet("Inputs").value(3, 2), 6000.0)
        self.assertEqual(wb.calc.get("fullCalcOnLoad"), "1")
        omap = json.loads((EXAMPLE / "ingest" / "output-map.json").read_text(encoding="utf-8"))
        rows, skipped = excel_cases.extract(self.tmp / "cases", omap)
        self.assertEqual(sorted(skipped), ["low_flow.xlsx", "old_pipe.xlsx"])
        with self.assertRaises(ValueError):
            X.write_inputs(self.books["pipe_pressure_drop.xlsx"], self.tmp / "bad.xlsx",
                           {"Calc!D5": 1.0})
        X.write_inputs(self.books["pipe_pressure_drop.xlsx"], self.tmp / "new_cell.xlsx",
                       {"Inputs!D3": 7.0, "Inputs!C30": "note"})
        wb = X.load(self.tmp / "new_cell.xlsx")
        self.assertEqual(wb.sheet("Inputs").value(3, 4), 7.0)
        self.assertEqual(wb.sheet("Inputs").value(30, 3), "note")

    def test_example_handoff_passes(self):
        code, text = run_cli(check_handoff, [EXAMPLE])
        self.assertEqual(code, 0, text)
        self.assertIn("0 errors, 0 warnings", text)

    def test_examples_validate_with_the_build_skill(self):
        build = build_skill_folder()
        if build is None:
            self.skipTest("the building-spotfire-dxps skill is not installed next to this one")
        prototype = SKILL.parent / "ingesting-prototypes" / "assets" / "examples" / \
            "pump-vibration-monitor"
        for folder in (EXAMPLE, prototype):
            if not folder.exists():
                continue
            code, text = run_cli(check_handoff, [folder, "--build-skill", build])
            self.assertEqual(code, 0, text)
            self.assertIn("dxpgen validate: 0 errors, 0 warnings", text)
            self.assertIn("0 errors, 0 warnings", text.splitlines()[-1])

    def test_standard_engine_limits(self):
        draft = self.tmp / "slim_only_app"
        shutil.copytree(EXAMPLE, draft)
        spec = json.loads((draft / "spec.json").read_text(encoding="utf-8"))
        spec["relations"] = [{"left": "SEGMENTS", "right": "ROUGHNESS_BY_AGE",
                              "on": [["Segment", "Age (years)"]]}]
        spec["tables"][0]["calculatedColumns"] = [{"name": "Length (m)",
                                                   "expression": "[Length (ft)] * 0.3048"}]
        spec["tables"][1]["source"]["path"] = "data/MISSING.csv"
        chart = spec["pages"][0]["visuals"][1]
        chart["showMarkers"] = True
        chart["referenceLayers"] = [{"kind": "band", "low": "0", "high": "10"}]
        spec["pages"][0]["filters"] = {"tables": [{"table": "SEGMENT_RESULTS",
                                                   "columns": ["Friction Loss (psi)"]}]}
        spec["properties"][5]["type"] = "Integer"
        spec["properties"][5]["default"] = 0
        (draft / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        code, text = run_cli(check_handoff, [draft])
        self.assertEqual(code, 1)
        for needle in ("relations is not built", "calculatedColumns is not built",
                       "data/MISSING.csv does not exist", "'showMarkers' on a lineChart",
                       "a 'band' reference layer", "'Friction Loss (psi)' of data function "
                       "table SEGMENT_RESULTS is not declared", "exports as LongInteger"):
            self.assertIn(needle, text)

    def test_broken_handoff_fails(self):
        broken = self.tmp / "broken_app"
        shutil.copytree(EXAMPLE, broken)
        brief = broken / "app-brief.md"
        brief.write_text(brief.read_text(encoding="utf-8").replace("| L10 |", "| L99 |")
                         .replace("## Refresh cadence", "## Refresh"), encoding="utf-8")
        code, text = run_cli(check_handoff, [broken])
        self.assertEqual(code, 1)
        self.assertIn("L99", text)
        self.assertIn("Refresh cadence", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
