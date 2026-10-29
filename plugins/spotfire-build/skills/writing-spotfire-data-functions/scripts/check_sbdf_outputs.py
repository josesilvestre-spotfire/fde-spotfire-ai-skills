"""Run a Spotfire Python data function standalone and check its outputs.

The script executes the data function file the way Spotfire does (exec with
its own globals, so the `if __name__ == "__main__":` smoke test does not
run), then checks every registered output for the problems that stop
Spotfire from writing it as SBDF:

  - an output that is not defined on this code path
  - a None output (Spotfire cannot determine its type)
  - pandas 3 text columns with the dtype "str" (the SBDF writer refuses them)
  - object columns that hold numbers, mixed types or only missing values
  - numpy or other non-native scalars

When the `spotfire` package is importable (run the script with the Python
Spotfire uses, $SPOTFIRE_PYTHON), every output is also exported to a
temporary SBDF file with Spotfire's own writer, and the whole function is run
once more through `spotfire.data_function.AnalyticSpec`, the runner Spotfire's
Python service uses: inputs given with --set or --input are passed as SBDF
files, every other registered input arrives as None, as an unbound input
does in Spotfire.

Usage:
  python check_sbdf_outputs.py FUNCTION.py [--outputs A,B] [--set NAME=VALUE]
                               [--input NAME=FILE.csv]
  python check_sbdf_outputs.py --self-test

Output names come from --outputs, else from the STAGING: OUTPUT PARAMETERS
table in the file's header. --set gives a value input (JSON, else text);
--input loads a CSV (or an SBDF file when the spotfire package is present)
as a table input. Exit code 1 when any output fails.
"""

import argparse
import datetime as dt
import decimal
import json
import os
import re
import sys
import tempfile
import warnings

try:
    import numpy as np
    import pandas as pd
except ImportError:  # pragma: no cover
    sys.exit("check_sbdf_outputs.py needs numpy and pandas")

try:
    from spotfire import sbdf as SBDF
except ImportError:
    SBDF = None
try:
    from spotfire import data_function as RUNNER
except ImportError:
    RUNNER = None

PANDAS_MAJOR = int(pd.__version__.split(".")[0])
TEXT_TYPES = (str,)
OK_OBJECT_TYPES = (str, dt.datetime, dt.date, dt.time, dt.timedelta,
                   decimal.Decimal, bytes)


def registration_table(source, marker):
    """(name, kind) pairs of a registration table in the header; kind is
    Table, Column or Value."""
    lines = source.splitlines()
    start = None
    for i, line in enumerate(lines):
        if marker in line:
            start = i + 1
            break
    if start is None:
        return []
    found = []
    for line in lines[start:]:
        text = line.strip()
        if not text:
            continue
        if set(text) <= set("-="):
            if found:
                break
            continue
        parts = text.split()
        if parts[0] == "name":
            continue
        if len(parts) >= 2 and parts[1] in ("Table", "Value", "Column"):
            found.append((parts[0], parts[1]))
    return found


def output_names(source):
    """Names listed in the STAGING: OUTPUT PARAMETERS table of the header."""
    return [n for n, _ in registration_table(source,
                                             "STAGING: OUTPUT PARAMETERS")]


def runner_check(source, names, values, tables, folder):
    """Run the script through Spotfire's own data function runner. Returns
    "" on success, else the runner's summary."""
    inputs = []
    for name, kind in registration_table(source, "STAGING: INPUT PARAMETERS"):
        if name in tables or name in values:
            value = tables[name] if name in tables else values[name]
            if isinstance(value, pd.DataFrame):
                value = value.copy()
                for col in value.columns:
                    if str(value[col].dtype) == "str":
                        value[col] = value[col].astype(object)
            file_path = os.path.join(folder, "in_%s.sbdf" % name)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                SBDF.export_data(value, file_path, default_column_name=name)
            inputs.append(RUNNER.AnalyticInput(name, kind.lower(), file_path))
        else:
            inputs.append(RUNNER.AnalyticInput(name, "NULL", ""))
    outputs = [RUNNER.AnalyticOutput(n, os.path.join(folder, "out_%s.sbdf" % n))
               for n in names]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        result = RUNNER.AnalyticSpec("script", inputs, outputs, source).evaluate()
    if result.success:
        return ""
    return " ".join(str(result.summary or "failed").split())[:400]


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def load_table(path):
    if path.lower().endswith(".sbdf"):
        if SBDF is None:
            raise SystemExit("reading SBDF needs the spotfire package "
                             "(run with $SPOTFIRE_PYTHON)")
        return SBDF.import_data(path)
    return pd.read_csv(path)


def run_function(path, values, tables):
    """Execute the data function with Spotfire-like globals."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    namespace = {"__builtins__": __builtins__}
    namespace.update(values)
    namespace.update(tables)
    exec(compile(source, path, "exec"), namespace)
    return source, namespace


def object_problem(series):
    """Why an object column cannot be written, or "" when it can."""
    values = [v for v in series.tolist()
              if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not values:
        return ("every value is missing, so the SBDF writer cannot determine "
                "the type: give the column a dtype (float64, Int64, or "
                "pd.StringDtype(\"python\") for text)")
    kinds = set()
    for v in values:
        if isinstance(v, bool) or isinstance(v, np.bool_):
            kinds.add("bool")
        elif isinstance(v, (int, float, np.integer, np.floating)):
            kinds.add("number")
        elif isinstance(v, OK_OBJECT_TYPES):
            kinds.add(type(v).__name__)
        else:
            kinds.add("other:" + type(v).__name__)
    if len(kinds) > 1:
        return ("mixed value types (%s): the SBDF writer raises 'types do "
                "not match'" % ", ".join(sorted(kinds)))
    kind = kinds.pop()
    if kind == "number":
        return ("numbers in an object column: under pandas 3 the SBDF writer "
                "refuses them ('cannot convert ... incompatible types'); use "
                "pd.to_numeric(col, errors=\"coerce\")")
    if kind.startswith("other:"):
        return "values of type %s cannot be written" % kind[6:]
    return ""


def check_table(name, frame):
    problems, notes = [], []
    for col in frame.columns:
        label = "%s[%s]" % (name, col)
        if not isinstance(col, str):
            notes.append("%s: column name is not text" % label)
        dtype = frame[col].dtype
        dname = str(dtype)
        if dname == "str":
            problems.append("%s: dtype 'str' (pandas 3 text). The SBDF writer "
                            "refuses it and Spotfire does not create the "
                            "table: use .astype(object)" % label)
        elif isinstance(dtype, pd.StringDtype) and \
                getattr(dtype, "storage", "python") != "python":
            notes.append("%s: dtype %s is not checked; prefer object or "
                         "pd.StringDtype(\"python\")" % (label, dname))
        elif dname == "object":
            why = object_problem(frame[col])
            if why:
                problems.append("%s: %s" % (label, why))
        elif dname == "category":
            notes.append("%s: category dtype is not checked; convert it to "
                         "object (text) or a numeric dtype" % label)
    return problems, notes


def check_scalar(name, value):
    if value is None:
        return ["%s: None. Spotfire cannot determine the type of a missing "
                "value: return a typed value on every path" % name], []
    if isinstance(value, (bool, int, float, str, dt.datetime, dt.date,
                          dt.time, dt.timedelta, decimal.Decimal)):
        return [], []
    if isinstance(value, np.generic):
        return [], ["%s: numpy %s; cast it at the staging boundary "
                    "(int(float(x)), float(x), str(x))"
                    % (name, type(value).__name__)]
    return ["%s: %s is not a value Spotfire can store in a document property"
            % (name, type(value).__name__)], []


def sbdf_roundtrip(name, value, folder):
    path = os.path.join(folder, re.sub(r"\W", "_", name) + ".sbdf")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            SBDF.export_data(value, path, default_column_name=name)
    except Exception as exc:  # report every writer error
        return "%s: SBDF writer: %s: %s" % (name, type(exc).__name__, exc)
    return ""


def check(path, names=None, values=None, tables=None, quiet=False):
    """Return (problems, notes) for the outputs of one data function file."""
    source, ns = run_function(path, values or {}, tables or {})
    names = names or output_names(source)
    problems, notes = [], []
    if not names:
        problems.append("no outputs: pass --outputs or add the STAGING: "
                        "OUTPUT PARAMETERS table to the header")
    with tempfile.TemporaryDirectory() as folder:
        for name in names:
            if name not in ns:
                problems.append("%s: not defined on this code path (Spotfire: "
                                "Output variable '%s' was not defined)"
                                % (name, name))
                continue
            value = ns[name]
            if isinstance(value, pd.Series):
                value = value.to_frame(name=value.name or name)
            if isinstance(value, pd.DataFrame):
                p, n = check_table(name, value)
                shape = "%d rows x %d columns" % value.shape
            else:
                p, n = check_scalar(name, value)
                shape = type(value).__name__
            if SBDF is not None and not p:
                err = sbdf_roundtrip(name, value, folder)
                if err:
                    p.append(err)
            problems += p
            notes += n
            if not quiet:
                print("  %-4s %s (%s)" % ("FAIL" if p else "ok", name, shape))
        if RUNNER is not None and SBDF is not None and names:
            why = runner_check(source, names, values or {}, tables or {},
                               folder)
            if why:
                problems.append("Spotfire's data function runner: " + why)
            if not quiet:
                print("  %-4s run through spotfire.data_function"
                      % ("FAIL" if why else "ok"))
    return problems, notes


def environment_note():
    parts = ["pandas %s" % pd.__version__, "numpy %s" % np.__version__,
             "SBDF writer %s" % ("present" if SBDF is not None
                                 else "absent (static checks only)")]
    user_site = [p for p in sys.path if "site-packages" in p.lower()
                 and ("appdata" in p.lower() or ".local" in p.lower())]
    if SBDF is not None and user_site and PANDAS_MAJOR >= 3:
        parts.append("pandas comes from the user site-packages folder, "
                     "which is ahead of the bundled packages on sys.path")
    return "; ".join(parts)


SELF_TEST_BAD = '''"""
STAGING: OUTPUT PARAMETERS
------------------------------------------------------------------------------
  name        type    destination
  GOOD        Table   new data table GOOD
  NUMBERS     Table   new data table NUMBERS
  EMPTY_TEXT  Table   new data table EMPTY_TEXT
  Count       Value   document property Count
  Missing     Value   document property Missing
  NotSet      Value   document property NotSet
------------------------------------------------------------------------------
"""
import numpy as np
import pandas as pd
GOOD = pd.DataFrame({"Name": pd.Series(["a", "b"]).astype(object),
                     "Value": [1.0, np.nan]})
NUMBERS = pd.DataFrame({"N": pd.Series([1, "x"], dtype=object)})
EMPTY_TEXT = pd.DataFrame({"T": pd.Series([None, None], dtype=object)})
Count = np.int64(3)
Missing = None
'''


def self_test():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "bad_function.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SELF_TEST_BAD)
        assert output_names(SELF_TEST_BAD) == [
            "GOOD", "NUMBERS", "EMPTY_TEXT", "Count", "Missing", "NotSet"]
        problems, notes = check(path, quiet=True)
        joined = "\n".join(problems)
        for expected in ("NUMBERS[N]: mixed", "EMPTY_TEXT[T]: every value",
                         "Missing: None", "NotSet: not defined"):
            assert expected in joined, (expected, joined)
        assert not any(p.startswith("GOOD") for p in problems), joined
        assert any(n.startswith("Count: numpy") for n in notes), notes
        if PANDAS_MAJOR >= 3:
            frame = pd.DataFrame({"Name": ["a", "b"]})
            p, _ = check_table("T", frame)
            assert p and "dtype 'str'" in p[0], p
    print("self-test passed (%s)" % environment_note())
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("function", nargs="?", help="data function .py file")
    parser.add_argument("--outputs", help="comma-separated output names")
    parser.add_argument("--set", action="append", default=[],
                        metavar="NAME=VALUE", help="value input")
    parser.add_argument("--input", action="append", default=[],
                        metavar="NAME=FILE", help="table input (CSV or SBDF)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.function:
        parser.error("give a data function file or --self-test")
    values = {}
    for item in args.set:
        key, _, raw = item.partition("=")
        values[key] = parse_value(raw)
    tables = {}
    for item in args.input:
        key, _, file_path = item.partition("=")
        tables[key] = load_table(file_path)
    names = [n.strip() for n in args.outputs.split(",")] if args.outputs \
        else None
    print("Checking %s (%s)" % (os.path.basename(args.function),
                                environment_note()))
    problems, notes = check(args.function, names, values, tables)
    for note in notes:
        print("  NOTE " + note)
    for problem in problems:
        print("  PROBLEM " + problem)
    print("%d problem(s), %d note(s)" % (len(problems), len(notes)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
