"""Tests for scripts/sbdf_export.py.

Run with any CPython 3:   python tests/test_data_tools.py -v

The SBDF tests run scripts/sbdf_export.py with Spotfire's Python (SPOTFIRE_PYTHON, else the interpreter
under SPOTFIRE_HOME or the newest %LOCALAPPDATA%/Spotfire/<version>): once on the pandas that interpreter
finds first (the user site-packages may hold a newer pandas) and once with "-s" (the bundled pandas).
Every file is read back with spotfire.sbdf.import_data and compared value by value. The tests are
skipped, not failed, when Spotfire's Python is missing.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
EXPORTER = os.path.join(SKILL, "scripts", "sbdf_export.py")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import sfenv  # noqa: E402
TIMEOUT = 300


def find_spotfire_python():
    """SPOTFIRE_PYTHON, else the python.exe under SPOTFIRE_HOME (or the newest Spotfire install)."""
    found = sfenv.spotfire_python()
    return str(found) if found is not None and found.is_file() else None


SFPY = find_spotfire_python()


def run(cmd, stdin=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"   # no __pycache__ next to scripts/sbdf_export.py
    p = subprocess.run(cmd, input=stdin.encode("utf-8") if stdin is not None else None, capture_output=True,
                       timeout=TIMEOUT, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def show(title, text):
    sys.stdout.write("\n----- %s -----\n%s" % (title, text if text.endswith("\n") else text + "\n"))
    sys.stdout.flush()


# A frame with every Spotfire type, missing values included, written with export_frame and read back
# with spotfire.sbdf.import_data in a child process of the bundled Python.
CHILD_EVERY_TYPE = textwrap.dedent(r'''
    import datetime as dt, decimal, importlib.util, json, sys, warnings
    import numpy as np, pandas as pd
    import spotfire
    from spotfire import sbdf

    spec = importlib.util.spec_from_file_location("sbdf_export", sys.argv[1])
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)
    out = sys.argv[2]
    D = decimal.Decimal
    expected = {
        "Name": ("String", ["alpha", None, "gamma"]),
        "Label": ("String", ["x", "y", None]),
        "Count": ("Integer", [1, None, -2147483648]),
        "Big Count": ("LongInteger", [2 ** 40, None, -5]),
        "Plain": ("LongInteger", [1, 2, 3]),
        "Value (bbl/d)": ("Real", [1.5, None, -2.25]),
        "Value32": ("SingleReal", [1.5, None, 3.25]),
        "Amount": ("Currency", [D("12.34"), None, D("-0.5")]),
        "Day": ("Date", [dt.date(2026, 1, 31), None, dt.date(1, 1, 1)]),
        "Stamp": ("DateTime", [dt.datetime(2026, 1, 31, 8, 0, 0, 123000), None, dt.datetime(2026, 12, 31, 23, 59, 59)]),
        "Clock": ("Time", [dt.time(8, 30, 15, 250000), None, dt.time(0, 0)]),
        "Duration": ("TimeSpan", [dt.timedelta(hours=1, minutes=30), None, dt.timedelta(days=2, seconds=1, milliseconds=500)]),
        "Flag": ("Boolean", [True, None, False]),
        "Blob": ("Binary", [b"\x00\x01", None, b"abc"]),
        "No Dates Yet": ("Date", [None, None, None]),
    }
    df = pd.DataFrame({
        "Name": pd.Series(["alpha", None, "gamma"], dtype=object),
        "Label": pd.Series(["x", "y", None]),                       # pandas 3: dtype 'str'
        "Count": pd.Series([1, None, -2147483648], dtype="Int32"),
        "Big Count": pd.Series([2 ** 40, None, -5], dtype="Int64"),
        "Plain": pd.Series([1, 2, 3], dtype="int64"),
        "Value (bbl/d)": pd.Series([1.5, np.nan, -2.25], dtype="float64"),
        "Value32": pd.Series([1.5, np.nan, 3.25], dtype="float32"),
        "Amount": pd.Series([D("12.34"), None, D("-0.5")], dtype=object),
        "Day": pd.Series([dt.date(2026, 1, 31), None, dt.date(1, 1, 1)], dtype=object),
        "Stamp": pd.to_datetime(pd.Series(["2026-01-31 08:00:00.123", None, "2026-12-31 23:59:59"]), format="ISO8601"),
        "Clock": pd.Series([dt.time(8, 30, 15, 250000), None, dt.time(0, 0)], dtype=object),
        "Duration": pd.to_timedelta(pd.Series(["01:30:00", None, "2 days 00:00:01.5"])),
        "Flag": pd.Series([True, None, False], dtype="boolean"),
        "Blob": pd.Series([b"\x00\x01", None, b"abc"], dtype=object),
        "No Dates Yet": pd.Series([None, None, None], dtype=object),
    })
    report = {"pandas": pd.__version__, "label_dtype": str(df["Label"].dtype)}

    # the facts the tool works around, recorded (not asserted): plain export of a 'str' column and
    # spotfire.set_spotfire_types under this pandas
    try:
        sbdf.export_data(pd.DataFrame({"s": pd.Series(["a", None])}), out + ".raw.sbdf")
        report["raw_str_export"] = "ok"
    except Exception as exc:
        report["raw_str_export"] = "%s: %s" % (type(exc).__name__, exc)
    probe = pd.DataFrame({"x": [1, 2]})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spotfire.set_spotfire_types(probe, {"x": "Integer"})
    report["set_spotfire_types_kept"] = spotfire.get_spotfire_types(probe).to_dict()

    types = se.export_frame(df, out, types={"No Dates Yet": "Date"})
    report["types"] = types
    back = sbdf.import_data(out)
    report["rows_back"] = len(back)
    report["dtypes_back"] = dict((c, str(back[c].dtype)) for c in back.columns)

    def norm(v):
        if v is None or isinstance(v, (bytes, str)):
            return v
        try:
            return None if pd.isna(v) else v
        except (TypeError, ValueError):
            return v

    mismatches = []
    for col, (want_type, want_values) in expected.items():
        if types.get(col) != want_type:
            mismatches.append("%s: type %r, expected %r" % (col, types.get(col), want_type))
        got = [norm(v) for v in back[col].tolist()]
        if got != want_values:
            mismatches.append("%s: read back %r, expected %r" % (col, got, want_values))
    report["mismatches"] = mismatches
    _, back_types = se.read_back(out)
    report["read_back_types"] = back_types
    print(json.dumps(report, default=str))
''')

CHILD_PARQUET = textwrap.dedent(r'''
    import datetime as dt, decimal, sys
    import pyarrow as pa, pyarrow.parquet as pq
    t = pa.table({
        "Small": pa.array([1, None, 3], pa.int32()),
        "Big": pa.array([2 ** 40, None, 7], pa.int64()),
        "F32": pa.array([1.5, None, 2.5], pa.float32()),
        "Flag": pa.array([True, None, False], pa.bool_()),
        "Name": pa.array(["a", None, "c"], pa.string()),
        "Day": pa.array([dt.date(2026, 1, 31), None, dt.date(2026, 2, 1)], pa.date32()),
        "Clock": pa.array([dt.time(8, 30), None, dt.time(23, 59, 59)], pa.time64("us")),
        "Stamp": pa.array([dt.datetime(2026, 1, 31, 8), None, dt.datetime(2026, 1, 31, 9)], pa.timestamp("us")),
        "Dur": pa.array([dt.timedelta(hours=1), None, dt.timedelta(days=1)], pa.duration("us")),
        "Amount": pa.array([decimal.Decimal("1.25"), None, decimal.Decimal("-3.50")], pa.decimal128(10, 2)),
        "Blob": pa.array([b"ab", None, b"\x00"], pa.binary()),
        "Category": pa.array(["x", None, "y"]).dictionary_encode(),
    })
    pq.write_table(t, sys.argv[1])
''')


@unittest.skipUnless(SFPY, "Spotfire's bundled Python not found (set SPOTFIRE_PYTHON)")
class SbdfExportTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sbdf_export_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def write(self, name, text, encoding="utf-8"):
        with open(self.path(name), "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return self.path(name)

    def cli(self, *args, isolated=False):
        cmd = [SFPY] + (["-s"] if isolated else []) + [EXPORTER] + list(args)
        return run(cmd)

    def every_type(self, isolated):
        script = self.write("child_every_type.py", CHILD_EVERY_TYPE)
        out = self.path("EVERY_TYPE.sbdf")
        rc, stdout, stderr = run([SFPY] + (["-s"] if isolated else []) + [script, EXPORTER, out])
        self.assertEqual(rc, 0, "child failed:\n" + stdout + stderr)
        report = json.loads(stdout.strip().splitlines()[-1])
        show("every type, pandas %s (%s)" % (report["pandas"], "python -s" if isolated else "default sys.path"),
             json.dumps(report, indent=1, default=str))
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["rows_back"], 3)
        expected_types = {
            "Name": "String", "Label": "String", "Count": "Integer", "Big Count": "LongInteger",
            "Plain": "LongInteger", "Value (bbl/d)": "Real", "Value32": "SingleReal", "Amount": "Currency",
            "Day": "Date", "Stamp": "DateTime", "Clock": "Time", "Duration": "TimeSpan", "Flag": "Boolean",
            "Blob": "Binary", "No Dates Yet": "Date"}
        self.assertEqual(report["types"], expected_types)
        self.assertEqual(report["read_back_types"], expected_types)
        self.assertEqual(sorted(set(report["types"].values())), sorted(
            ["String", "Integer", "LongInteger", "Real", "SingleReal", "Currency", "Date", "DateTime", "Time",
             "TimeSpan", "Boolean", "Binary"]))
        return report

    def test_every_type_round_trip(self):
        report = self.every_type(isolated=False)
        if report["pandas"].startswith("3."):
            # the reason the tool exists: pandas 3's default string dtype is rejected by export_data
            self.assertEqual(report["label_dtype"], "str")
            self.assertIn("unknown dtype 'str'", report["raw_str_export"])

    def test_every_type_round_trip_bundled_pandas(self):
        rc, stdout, _ = run([SFPY, "-s", "-c", "import pandas, spotfire; print(pandas.__version__)"])
        if rc != 0:
            self.skipTest("the bundled site-packages alone cannot import pandas/spotfire")
        self.every_type(isolated=True)

    def test_csv_inference_and_table(self):
        csv_path = self.write("pumps.csv", (
            "Timestamp,Pump ID,Flow Rate (bbl/d),Running,Starts,Zip,Day,Clock,Note,Offset Time\n"
            "2026-01-31 08:00:00,P-101,1234.5,true,3,01234,2026-01-31,08:30,hello,2026-01-31T08:00:00-05:00\n"
            "2026-01-31 09:00:00.250,P-102,,FALSE,4,99501,2026-02-01,09:45:30,NA,2026-06-30T08:00:00-06:00\n"
            "2026-01-31 10:00:00,P-103,NaN,True,,00501,,10:00,,2026-01-31T13:00:00Z\n"))
        out = self.path("PUMP_DATA.sbdf")
        rc, stdout, stderr = self.cli(csv_path, out)
        show("sbdf_export.py pumps.csv PUMP_DATA.sbdf", stdout + stderr)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("read back with spotfire.sbdf.import_data", stdout)
        rc, stdout, stderr = self.cli(csv_path, out, "--json")
        self.assertEqual(rc, 0, stderr)
        res = json.loads(stdout)
        types = dict((c["name"], c["type"]) for c in res["columns"])
        self.assertEqual(types, {
            "Timestamp": "DateTime", "Pump ID": "String", "Flow Rate (bbl/d)": "Real", "Running": "Boolean",
            "Starts": "LongInteger", "Zip": "String", "Day": "Date", "Clock": "String", "Note": "String",
            "Offset Time": "DateTime"})
        missing = dict((c["name"], c["missing"]) for c in res["columns"])
        self.assertEqual(missing["Flow Rate (bbl/d)"], 2)   # empty field and NaN
        self.assertEqual(missing["Starts"], 1)              # stays missing, never 0
        self.assertEqual(missing["Note"], 1)                # "NA" is text in a String column
        self.assertTrue(res["verified"])

    def test_explicit_types_and_date_format(self):
        csv_path = self.write("readings.csv", (
            "Reading Date,Clock,Count,Zip,Level\n"
            "01/31/2026,08:30,1,01234,1.5\n"
            "02/01/2026,9:45 PM,,99501,2\n"))
        out = self.path("READINGS.sbdf")
        rc, stdout, stderr = self.cli(csv_path, out, "--types", "Clock=Time,Count=Integer,Zip=String,Level=singlereal",
                                      "--date-format", "Reading Date=%m/%d/%Y", "--json")
        self.assertEqual(rc, 0, stdout + stderr)
        res = json.loads(stdout)
        types = dict((c["name"], c["type"]) for c in res["columns"])
        self.assertEqual(types, {"Reading Date": "Date", "Clock": "Time", "Count": "Integer", "Zip": "String",
                                 "Level": "SingleReal"})
        examples = dict((c["name"], c["example"]) for c in res["columns"])
        self.assertEqual(examples["Reading Date"], "2026-01-31")
        self.assertEqual(examples["Zip"], "01234")

    def test_refuses_columns_it_cannot_type(self):
        csv_path = self.write("bad.csv", "Name,Empty,Value\nA,,1\nB,,x\n")
        out = self.path("BAD.sbdf")
        rc, stdout, stderr = self.cli(csv_path, out, "--types", "Value=Real")
        show("refusal (exit %d)" % rc, stdout + stderr)
        self.assertEqual(rc, 1)
        self.assertIn("column 'Empty': all values are missing", stderr)
        self.assertIn("column 'Value': 1 value(s) cannot be stored as Real", stderr)
        self.assertFalse(os.path.exists(out), "nothing may be written when a column is refused")
        json_path = self.write("mixed.json", json.dumps([{"a": 1, "b": [1, 2]}, {"a": "x", "b": {"c": 1}}]))
        rc, stdout, stderr = self.cli(json_path, out, "--json")
        self.assertEqual(rc, 1)
        res = json.loads(stdout)
        self.assertEqual(res["status"], "refused")
        self.assertTrue(any("mixed value types" in p for p in res["problems"]))
        self.assertTrue(any("nested JSON" in p for p in res["problems"]))
        self.assertFalse(os.path.exists(out))

    def test_usage_errors(self):
        csv_path = self.write("ok.csv", "a\n1\n")
        rc, _, stderr = self.cli(csv_path, self.path("x.sbdf"), "--types", "Nope=Real")
        self.assertEqual(rc, 2)
        self.assertIn("does not exist", stderr)
        rc, _, stderr = self.cli(csv_path, self.path("x.sbdf"), "--types", "a=Float")
        self.assertEqual(rc, 2)
        rc, _, stderr = self.cli(self.path("missing.csv"), self.path("x.sbdf"))
        self.assertEqual(rc, 2)

    def test_json_records_and_table_orient(self):
        recs = self.write("records.json", json.dumps([
            {"id": 1, "when": "2026-01-31T08:00:00", "ok": True, "x": 1.5, "day": "2026-01-31"},
            {"id": None, "when": None, "ok": False, "x": 2, "day": "2026-02-01"}]))
        rc, stdout, stderr = self.cli(recs, self.path("R.sbdf"), "--json")
        self.assertEqual(rc, 0, stdout + stderr)
        types = dict((c["name"], c["type"]) for c in json.loads(stdout)["columns"])
        self.assertEqual(types, {"id": "LongInteger", "when": "DateTime", "ok": "Boolean", "x": "Real",
                                 "day": "Date"})
        table = self.write("table.json", json.dumps({
            "schema": {"fields": [{"name": "index", "type": "integer"}, {"name": "a", "type": "integer"},
                                  {"name": "t", "type": "datetime"}], "primaryKey": ["index"]},
            "data": [{"index": 0, "a": 1, "t": "2026-01-01T00:00:00.000"}, {"index": 1, "a": None, "t": None}]}))
        rc, stdout, stderr = self.cli(table, self.path("T.sbdf"), "--json")
        self.assertEqual(rc, 0, stdout + stderr)
        types = dict((c["name"], c["type"]) for c in json.loads(stdout)["columns"])
        self.assertEqual(types, {"a": "LongInteger", "t": "DateTime"})

    def test_parquet_types(self):
        rc, _, _ = run([SFPY, "-c", "import pyarrow"])
        if rc != 0:
            self.skipTest("pyarrow not importable by the bundled Python")
        script = self.write("child_parquet.py", CHILD_PARQUET)
        pq_path = self.path("types.parquet")
        rc, stdout, stderr = run([SFPY, script, pq_path])
        self.assertEqual(rc, 0, stdout + stderr)
        rc, stdout, stderr = self.cli(pq_path, self.path("P.sbdf"), "--json")
        self.assertEqual(rc, 0, stdout + stderr)
        types = dict((c["name"], c["type"]) for c in json.loads(stdout)["columns"])
        self.assertEqual(types, {"Small": "Integer", "Big": "LongInteger", "F32": "SingleReal", "Flag": "Boolean",
                                 "Name": "String", "Day": "Date", "Clock": "Time", "Stamp": "DateTime",
                                 "Dur": "TimeSpan", "Amount": "Currency", "Blob": "Binary", "Category": "String"})


if __name__ == "__main__":
    unittest.main()
