"""Tests for the column-reference checks of scripts/dxpgen.py validate.

Run: python -B tests/test_columns.py   (or python -m pytest tests)

The checks read the column names and types of the data files the builder loads (the SBDF header, the
header row of a CSV) and report spec references to columns those files do not have. The SBDF files here
are built byte by byte (file header + table-metadata section, the only part the reader looks at), with
the layout of a file written by spotfire.sbdf.export_data. Nothing here starts Spotfire.
"""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
import dxpgen  # noqa: E402

# SBDF value-type ids
STRING, LONG, REAL, DATE, BOOL = 10, 3, 5, 7, 1
# the example app as built in your workspace ($DXP_WORKSPACE/apps/well-tear-sheet), when it exists
WORKSPACE_APP = (dxpgen.workspace_root() or Path("no-workspace")) / "apps" / "well-tear-sheet"


def sbdf_header(columns, table_metadata=0):
    """Bytes of an SBDF file header + table metadata for [(name, value type id)] (no data slices)."""
    out = bytearray(b"\xdf\x5b\x01\x01\x00")                       # file header, format 1.0
    out += b"\xdf\x5b\x02" + struct.pack("<i", table_metadata)     # table metadata section
    for k in range(table_metadata):
        name = ("Meta%d" % k).encode("utf-8")
        value = b"x"
        out += struct.pack("<i", len(name)) + name + bytes([STRING]) + b"\x01" + struct.pack("<i", 1) + value + b"\x00"
    out += struct.pack("<i", len(columns)) + struct.pack("<i", 2)
    for prop, vt in (("Name", STRING), ("DataType", 12)):
        raw = prop.encode("utf-8")
        out += struct.pack("<i", len(raw)) + raw + bytes([vt]) + b"\x00"
    for name, vt in columns:
        raw = name.encode("utf-8")
        out += b"\x01" + struct.pack("<i", len(raw)) + raw + b"\x01" + struct.pack("<i", 1) + bytes([vt])
    out += b"\xdf\x5b\x05"                                          # table end (never read)
    return bytes(out)


class SbdfReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dxpgen-columns-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_names_and_types(self):
        path = self.tmp / "T.sbdf"
        path.write_bytes(sbdf_header([("Month", DATE), ("Model Year", LONG), ("Oil ($/bbl)", REAL),
                                      ("Período", STRING), ("Is Net", BOOL)], table_metadata=2))
        self.assertEqual(dxpgen.sbdf_columns(path),
                         [("Month", "Date"), ("Model Year", "LongInteger"), ("Oil ($/bbl)", "Real"),
                          ("Período", "String"), ("Is Net", "Boolean")])

    def test_rejects_other_files(self):
        path = self.tmp / "stub.sbdf"
        path.write_bytes(b"stub sbdf")
        with self.assertRaises(ValueError):
            dxpgen.sbdf_columns(path)
        path.write_bytes(sbdf_header([("A", REAL)])[:20])           # truncated header
        with self.assertRaises(ValueError):
            dxpgen.sbdf_columns(path)

    @unittest.skipUnless((WORKSPACE_APP / "data" / "BREAKEVENS.sbdf").is_file(), "well-tear-sheet data not built")
    def test_reads_a_file_written_by_spotfire_sbdf(self):
        self.assertEqual(dxpgen.sbdf_columns(WORKSPACE_APP / "data" / "BREAKEVENS.sbdf"),
                         [("Metric", "String"), ("Value", "Real"), ("Unit", "String"), ("Sort Order", "LongInteger")])

    def test_csv_header(self):
        path = self.tmp / "E.csv"
        path.write_text("﻿Event ID;Pump ID;Start\n1;P-1;2026-01-01\n", encoding="utf-8")
        self.assertEqual(dxpgen.csv_columns(path, {"separator": ";", "columns": {"Start": "DateTime"}}),
                         [("Event ID", None), ("Pump ID", None), ("Start", "DateTime")])
        self.assertIsNone(dxpgen.csv_columns(path, {"separator": ";", "header": False}))


class ExpressionColumnsTest(unittest.TestCase):
    def test_identifiers(self):
        ec = dxpgen.expression_columns
        self.assertEqual(ec("Sum([Net Oil (bbl)]) as [Net oil (bbl)]"), [(None, "Net Oil (bbl)")])
        self.assertEqual(ec("Sum([A]) as[B], Avg([T].[C (x)]) THEN [Value] / Sum([Value]) OVER ([Axis.X])"),
                         [(None, "A"), ("T", "C (x)")])
        self.assertEqual(ec('Concatenate("[not a column]", [D]) AS [E]'), [(None, "D")])
        self.assertEqual(ec("[$Threshold] + ${Other} + [Axis.Default.Names] + [Y.FinalValue]"), [])
        self.assertEqual(ec("<[Station] NEST [Pump ID]>"), [(None, "Station"), (None, "Pump ID")])
        self.assertEqual(ec("[Odd]]Name]"), [(None, "Odd]Name")])
        self.assertEqual(ec(None), [])


class ValidateColumnsTest(unittest.TestCase):
    def setUp(self):
        self.app = Path(tempfile.mkdtemp(prefix="dxpgen-columns-app-"))
        (self.app / "data").mkdir()
        (self.app / "data" / "PROD.sbdf").write_bytes(
            sbdf_header([("Month", DATE), ("Model Year", LONG), ("Oil Rate (bbl/d)", REAL), ("Component", STRING)]))
        (self.app / "data" / "EVENTS.csv").write_text("Event ID,Model Year,Note\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.app, ignore_errors=True)

    def spec(self):
        return {
            "specVersion": 1, "app": {"name": "Columns Test"},
            "tables": [
                {"name": "PROD", "source": {"type": "sbdf", "path": "data/PROD.sbdf"},
                 "columns": {"Oil Rate (bbl/d)": {"format": "#,##0"}},
                 "calculatedColumns": [{"name": "Oil Rate (Mbbl/d)", "expression": "[Oil Rate (bbl/d)] / 1000"}],
                 "hierarchies": [{"name": "Time", "levels": ["Model Year", "Month"]}]},
                {"name": "EVENTS", "source": {"type": "csv", "path": "data/EVENTS.csv"}},
            ],
            "relations": [{"left": "PROD", "right": "EVENTS", "on": [["Model Year", "Model Year"]]}],
            "pages": [{"title": "Overview", "visuals": [
                {"id": "rate", "type": "lineChart", "title": "Rate", "table": "PROD", "x": "[Month]",
                 "y": ["Avg([Oil Rate (bbl/d)]) as [Gross]", "Avg([Oil Rate (Mbbl/d)])"],
                 "limitExpression": "[Model Year] <= 10",
                 "referenceLayers": [{"kind": "verticalLine", "value": "Date(2032, 1, 16)"}]},
                {"id": "cost", "type": "barChart", "title": "Cost", "table": "PROD", "x": "<Model Year>",
                 "y": "Count()", "colorBy": "<[component]>"},
                {"id": "grid", "type": "table", "title": "Grid", "table": "PROD",
                 "columns": ["Month", "[Oil Rate (bbl/d)]"], "sort": [{"column": "Month"}],
                 "coloring": {"columns": ["Oil Rate (bbl/d)"], "rules": [{"type": "lessThan", "value": 0.0,
                                                                          "color": "#BA2C48"}]}},
                {"id": "statement", "type": "crossTable", "title": "Statement", "table": "PROD",
                 "rows": ["[Axis.Default.Names]"], "columns": ["Model Year"],
                 "measures": ["Sum([Oil Rate (bbl/d)]) as [Oil]"]},
                {"id": "kpis", "type": "kpiChart", "title": "KPIs", "table": "PROD",
                 "kpis": [{"title": "Oil", "value": "Sum([Oil Rate (bbl/d)])", "tileBy": "Component"}]},
            ], "layout": {"column": [{"visual": "rate"}, {"visual": "cost"}, {"visual": "grid"},
                                     {"visual": "statement"}, {"visual": "kpis"}]}}],
        }

    def run_validator(self, spec):
        report = dxpgen.Validator(spec, self.app, dxpgen.Options(lint=False, sanitize=False,
                                                                 tools_dir=self.app)).run()
        return report

    def column_findings(self, report):
        words = ("is not a column", "neither a column", "SBDF header")
        return ([e["path"] for e in report.errors if any(w in e["message"] for w in words)],
                [w["path"] for w in report.warnings if any(x in w["message"] for x in words)])

    def test_clean_spec_has_no_column_findings(self):
        self.assertEqual(self.column_findings(self.run_validator(self.spec())), ([], []))

    def test_plain_names_are_errors(self):
        spec = self.spec()
        spec["tables"][0]["columns"]["Gas Rate"] = {"format": "0"}
        spec["tables"][0]["hierarchies"][0]["levels"].append("Day")
        spec["relations"][0]["on"][0][1] = "Year"
        grid = spec["pages"][0]["visuals"][2]
        grid["columns"].append("Oil")
        grid["sort"][0]["column"] = "Mnth"
        grid["coloring"]["columns"] = ["Oil Rate"]
        errors, _ = self.column_findings(self.run_validator(spec))
        self.assertEqual(sorted(errors), sorted([
            'tables[0].columns["Gas Rate"]', "tables[0].hierarchies[0].levels[2]", "relations[0].on[0][1]",
            "pages[0].visuals[2].columns[2]", "pages[0].visuals[2].sort[0].column",
            "pages[0].visuals[2].coloring[0].columns[0]"]))

    def test_expression_identifiers_are_warnings(self):
        spec = self.spec()
        visuals = spec["pages"][0]["visuals"]
        visuals[0]["y"][0] = "Avg([Oil Rate]) as [Gross]"
        visuals[0]["limitExpression"] = "[Model Yr] <= 10"
        visuals[0]["referenceLayers"][0]["value"] = "Max([Date])"
        visuals[3]["columns"] = ["Model Yr"]
        visuals[3]["measures"][0] = "Sum([PROD].[Gas]) as [Gas]"
        visuals[4]["kpis"][0]["value"] = "Sum([Oil])"
        report = self.run_validator(spec)
        errors, warnings = self.column_findings(report)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(warnings), sorted([
            "pages[0].visuals[0].y[0]", "pages[0].visuals[0].limitExpression",
            "pages[0].visuals[0].referenceLayers[0].value", "pages[0].visuals[3].columns[0]",
            "pages[0].visuals[3].measures[0]", "pages[0].visuals[4].kpis[0].value"]))
        self.assertTrue(any("did you mean 'Model Year'" in w["message"] for w in report.warnings))

    def test_unreadable_sbdf_is_one_warning_and_no_checks(self):
        (self.app / "data" / "PROD.sbdf").write_bytes(b"stub sbdf")
        spec = self.spec()
        spec["pages"][0]["visuals"][2]["columns"].append("Nope")
        errors, warnings = self.column_findings(self.run_validator(spec))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ["tables[0].source.path"])

    def test_data_function_tables_are_not_checked(self):
        spec = self.spec()
        spec["tables"].append({"name": "OUT", "source": {"type": "dataFunction", "function": "Make Out",
                                                         "output": "OUT"}})
        spec["dataFunctions"] = [{"name": "Make Out", "script": "df.py", "inputs": [],
                                  "outputs": [{"name": "OUT", "type": "table", "target": {"table": "OUT"}}]}]
        (self.app / "df.py").write_text("OUT = None\n", encoding="utf-8")
        spec["pages"][0]["visuals"].append({"id": "out", "type": "table", "title": "Out", "table": "OUT",
                                            "columns": ["Anything"]})
        spec["pages"][0]["layout"]["column"].append({"visual": "out"})
        errors, warnings = self.column_findings(self.run_validator(spec))
        self.assertEqual((errors, warnings), ([], []))


@unittest.skipUnless((WORKSPACE_APP / "spec.json").is_file() and (WORKSPACE_APP / "data" / "WELL_SUMMARY.sbdf").is_file(),
                     "well-tear-sheet app with data not present")
class WellTearSheetColumnsTest(unittest.TestCase):
    def test_reference_app_resolves_every_column(self):
        spec = json.loads((WORKSPACE_APP / "spec.json").read_text(encoding="utf-8"))
        report = dxpgen.Validator(spec, WORKSPACE_APP, dxpgen.Options(lint=False, sanitize=False)).run()
        findings = [i for i in report.items if "column" in i["message"] and i["level"] in ("error", "warning")
                    and "has no filter layout" not in i["message"]]        # the filter design rule
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
