#!/usr/bin/env python3
"""sbdf_export.py - write a table to SBDF with exact Spotfire column types (building-spotfire-dxps).

Run it with Spotfire's bundled Python (SPOTFIRE_PYTHON), which has the ``spotfire`` package that
writes SBDF:

    "%SPOTFIRE_PYTHON%" scripts\\sbdf_export.py data\\pumps.csv apps\\PumpMonitor\\data\\PUMP_DATA.sbdf
    "%SPOTFIRE_PYTHON%" scripts\\sbdf_export.py pumps.parquet PUMP_DATA.sbdf --types "Pump ID=String,Starts=Integer"
    "%SPOTFIRE_PYTHON%" scripts\\sbdf_export.py readings.csv READINGS.sbdf --date-format "%m/%d/%Y %H:%M"

SPOTFIRE_PYTHON is the python.exe under SPOTFIRE_HOME/Modules/Python Interpreter_<version>/python/.

Inputs   .csv .tsv .txt .tab (delimited text), .parquet .pq, .pkl .pickle (a pickled pandas DataFrame or
         Series - only open pickles you trust), .json (records, columns, split or table orient),
         .jsonl .ndjson (one record per line).
Output   one SBDF file written by spotfire.sbdf.export_data, then read back with spotfire.sbdf.import_data
         and compared with what was meant to be written (types, row count, missing values, every value).
         Prints the column -> Spotfire type table.

Spotfire types: String Integer LongInteger Real SingleReal Currency Date DateTime Time TimeSpan Boolean Binary

Options
  --types "Col=Type,Other=Type"  explicit types (type names case-insensitive); repeatable; a column name may
                                 contain commas; naming a column that does not exist is an error.
  --date-format FMT              strptime format for text dates (or "ISO8601" / "mixed", passed to pandas);
                                 "Col=FMT" applies to one column, which must then parse. Repeatable.
  --tz wall|utc                  time-zone-aware values: keep the wall-clock time as written (default; what a
                                 prototype chart shows) or convert to UTC. Spotfire DateTime has no zone.
  --drop COL[,COL]               leave columns out (for example "Unnamed: 0", a saved pandas index).
  --sep CHAR, --encoding NAME    delimited text: separator (default "," for .csv, tab for .tsv/.tab, else
                                 detected from the header) and encoding (default UTF-8, BOM aware, falling
                                 back to cp1252, then latin-1).
  --dry-run                      analyse and print the planned types; write nothing.
  --json                         print the result as one JSON object (ASCII).

How the type of a column is chosen when --types does not name it
  parquet / pickle (typed): from the dtype - int8/int16/int32/uint8/uint16 Integer, int64/uint32 LongInteger,
    uint64 LongInteger when every value fits, float16/float32 SingleReal, float64 Real, bool/boolean Boolean,
    datetime64 DateTime, timedelta64 TimeSpan, str/string String, decimal Currency, date Date, time Time,
    bytes Binary, category -> the type of its values. Object columns: from the Python value types
    (int + float -> Real, datetime + date -> DateTime); other mixtures are refused. A non-default index
    (DatetimeIndex, named index, MultiIndex) becomes ordinary columns.
  delimited text: an empty field is missing; for every type except String the tokens NA, N/A, NULL, NaN,
    None, #N/A (pandas' list) are missing too. true/false in any case -> Boolean; integers -> LongInteger,
    except leading zeros (007) or more than 64 bits, which keep the column String; other numbers -> Real;
    ISO dates (2026-01-31) -> Date; ISO date-times (2026-01-31 08:00[:00[.123]], T, Z, +hh:mm) -> DateTime;
    text matching --date-format -> Date (format without time directives) or DateTime; anything else String.
    Times of day (08:30) and durations are never guessed: use --types Col=Time or Col=TimeSpan.
  JSON: booleans, numbers and strings as typed in the file (integers with nulls stay LongInteger); ISO date
    strings -> Date / DateTime; the schema of orient="table" files is honoured.
  Missing values go out as NaN (Real, SingleReal), pandas NA in nullable Int32 / Int64 (Integer, LongInteger -
  missing stays missing, never 0) and None / NaT elsewhere. DateTime, Time and TimeSpan keep milliseconds
  (what SBDF stores); finer precision is cut and reported. Row numbers in messages count data rows from 1.

Refused (exit 1, nothing written)
  a column with no values and no --types; mixed value types; nested values (lists, dicts); values an explicit
  type cannot hold (text for Real, fractions for Integer, a time of day for Date, out of range);
  duplicate, empty or pandas-placeholder ("Unnamed: 0") column names.

Facts this relies on (spotfire 2.4.2, verified with pandas 3.0.5 and with the bundled 2.3.3):
  - the pandas 3 default string dtype "str" is rejected by export_data ("unknown dtype 'str'"), so strings
    go out as object;
  - nullable Int64 / Int32 / boolean / Float64 export;
  - per-column Series.attrs do not survive in pandas 3 (no item cache), so spotfire.set_spotfire_types()
    silently does nothing and import_data loses the 'spotfire_type' it attaches; this tool pins every
    column's type with a DataFrame subclass that hands attrs to the writer, and recovers the read-back
    types the same way;
  - export_data converts time-zone-aware datetimes to the PC's local zone; this tool removes the zone
    first (--tz) so the file does not depend on the machine.
  Run plainly, the bundled interpreter puts the user site-packages (for example a newer pandas and pyarrow)
  before its own pandas 2.3.3; "python.exe -s" runs this tool on 2.3.3. Spotfire's own data functions
  probably get 2.3.3 too: Spotfire.Dxp.Data.dll has a "-I" (isolated mode) literal next to its python.exe
  launcher code (static finding, not confirmed live). Both work here; Parquet input and pandas 3 pickles need
  pyarrow, which only the user site-packages has.

Importable
  export_frame(df, path, types=None, *, date_format=None, tz="wall", text=None, drop=None)
      -> {column: Spotfire type as read back}; raises ExportRefused (a ValueError) with .problems.
  export_table(...) -> the full result dict the CLI prints; read_input(path) -> (DataFrame, info).

Exit codes: 0 written and verified (or --dry-run analysed); 1 refused; 2 usage, input or verification error.
"""

import argparse
import contextlib
import csv
import datetime as _dt
import decimal
import json
import math
import os
import re
import sys
import traceback
import warnings

try:
    import numpy as np
    import pandas as pd
    import spotfire as _spotfire
    from spotfire import sbdf as _sbdf
except ImportError as _exc:  # pragma: no cover - wrong interpreter
    np = pd = _spotfire = _sbdf = None
    _IMPORT_ERROR = _exc
else:
    _IMPORT_ERROR = None

SPOTFIRE_TYPES = ("String", "Integer", "LongInteger", "Real", "SingleReal", "Currency",
                  "Date", "DateTime", "Time", "TimeSpan", "Boolean", "Binary")
_TYPE_BY_LOWER = dict((t.lower(), t) for t in SPOTFIRE_TYPES)

# pandas' default NA strings (read_csv keep_default_na) - missing for every type except String
NA_TOKENS = frozenset(["", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
                       "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"])
_INT_RANGE = {"Integer": (-2 ** 31, 2 ** 31 - 1), "LongInteger": (-2 ** 63, 2 ** 63 - 1)}
_TRUE_TOKENS = frozenset(["true", "t", "yes", "y", "1"])
_FALSE_TOKENS = frozenset(["false", "f", "no", "n", "0"])
_TIME_DIRECTIVES = frozenset("HIMSfpXcTRrz")
_ISO_RE = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:[T ](?P<time>[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:[.,][0-9]+)?)?)"
    r"\s*(?P<tz>Z|[+-][0-9]{2}(?::?[0-9]{2})?)?)?$")
_INT_TEXT = r"[+-]?[0-9]+"
_LEADING_ZERO_TEXT = r"[+-]?0[0-9]+"
_TIME_TEXT_RE = re.compile(r"^(?P<h>[0-9]{1,2}):(?P<m>[0-9]{2})(?::(?P<s>[0-9]{2})(?:[.,](?P<f>[0-9]{1,9}))?)?"
                           r"\s*(?P<ampm>[AaPp][Mm])?$")
_BARE_NUMBER_RE = re.compile(r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$")


class ExportRefused(ValueError):
    """Some columns cannot be typed; nothing was written. ``problems`` lists them."""

    def __init__(self, problems, notes=None):
        ValueError.__init__(self, "refused: " + "; ".join(problems))
        self.problems = list(problems)
        self.notes = list(notes or [])


class UsageError(Exception):
    """Bad arguments or an unreadable input file."""


class VerificationError(RuntimeError):
    """The SBDF file read back differs from what was written."""

    def __init__(self, problems):
        RuntimeError.__init__(self, "read-back check failed: " + "; ".join(problems))
        self.problems = list(problems)


class _Refuse(Exception):
    """One column cannot be typed (internal)."""


def _require_spotfire():
    if _IMPORT_ERROR is not None:
        raise ImportError("sbdf_export needs pandas, numpy and the spotfire package: run it with Spotfire's "
                          "bundled Python (" + (_find_spotfire_python() or "<Spotfire>/Modules/Python "
                          "Interpreter_*/python/python.exe") + "). Import error: " + str(_IMPORT_ERROR))


def _find_spotfire_python():
    """SPOTFIRE_PYTHON, else the interpreter under SPOTFIRE_HOME, else the newest Spotfire install."""
    env = os.environ.get("SPOTFIRE_PYTHON")
    if env and os.path.isfile(env):
        return env
    home = os.environ.get("SPOTFIRE_HOME")
    if home and os.path.isdir(os.path.join(home, "Modules")):
        mods = os.path.join(home, "Modules")
        for name in sorted(os.listdir(mods), reverse=True):
            exe = os.path.join(mods, name, "python", "python.exe")
            if name.startswith("Python Interpreter_") and os.path.isfile(exe):
                return exe
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Spotfire")
    if not os.path.isdir(base):
        return None
    for ver in sorted(os.listdir(base), reverse=True):
        mods = os.path.join(base, ver, "Modules")
        if not os.path.isdir(mods):
            continue
        for name in sorted(os.listdir(mods), reverse=True):
            if name.startswith("Python Interpreter_"):
                exe = os.path.join(mods, name, "python", "python.exe")
                if os.path.isfile(exe):
                    return exe
    return None


# --------------------------------------------------------------------------------------------- frames
if pd is not None:
    class _TypedFrame(pd.DataFrame):
        """DataFrame whose column Series carry attrs['spotfire_type'] when spotfire.sbdf reads them.

        pandas 3 builds a new Series for every df[col], so attrs set on a column (what
        spotfire.set_spotfire_types does) are lost before export_data looks at them."""

        @property
        def _constructor(self):
            return pd.DataFrame

        def __getitem__(self, key):
            item = pd.DataFrame.__getitem__(self, key)
            types = self.__dict__.get("_sbdf_types")
            if types and isinstance(item, pd.Series) and isinstance(key, str) and key in types:
                item.attrs["spotfire_type"] = types[key]
            return item

    class _ItemCacheFrame(pd.DataFrame):
        """DataFrame that returns the same Series object for the same column (pandas 2 item cache), so the
        attrs spotfire.sbdf.import_data sets per column survive."""

        @property
        def _constructor(self):
            return pd.DataFrame

        def __getitem__(self, key):
            if isinstance(key, str):
                cache = self.__dict__.setdefault("_sbdf_item_cache", {})
                if key not in cache:
                    cache[key] = pd.DataFrame.__getitem__(self, key)
                return cache[key]
            return pd.DataFrame.__getitem__(self, key)


@contextlib.contextmanager
def _keep_column_attrs():
    """While import_data runs, make pd.concat return an _ItemCacheFrame (import_data builds its frame with
    pd.concat and then sets frame[col].attrs['spotfire_type'])."""
    original = pd.concat

    def concat(*args, **kwargs):
        res = original(*args, **kwargs)
        if type(res) is pd.DataFrame:
            res = _ItemCacheFrame(res)
        return res

    pd.concat = concat
    try:
        yield
    finally:
        pd.concat = original


# --------------------------------------------------------------------------------------------- readers
def read_input(path, sep=None, encoding=None):
    """Read a supported file. Returns (DataFrame, info); info has "format", "text" (None, "csv" or
    "json": how text columns are inferred), "declared" ({column: (type, source)}), "notes", "problems"."""
    _require_spotfire()
    if not os.path.isfile(path):
        raise UsageError("input file not found: " + path)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv", ".txt", ".tab"):
        return _read_delimited(path, ext, sep, encoding)
    if ext in (".parquet", ".pq"):
        try:
            return _read_parquet(path)
        except ImportError as exc:
            raise UsageError("reading Parquet needs pyarrow, which this Python cannot import (%s); the bundled "
                             "interpreter finds it in the user site-packages, so do not run it with -s" % exc)
        except Exception as exc:
            raise UsageError("cannot read %s as Parquet: %s: %s" % (path, type(exc).__name__, exc))
    if ext in (".pkl", ".pickle"):
        try:
            return _read_pickle(path)
        except UsageError:
            raise
        except Exception as exc:
            raise UsageError("cannot unpickle %s: %s: %s (a pickle needs the pandas version that wrote it or newer; "
                             "pandas 3 pickles with text columns also need pyarrow)" % (path, type(exc).__name__, exc))
    if ext == ".json":
        return _read_json(path, lines=False)
    if ext in (".jsonl", ".ndjson"):
        return _read_json(path, lines=True)
    raise UsageError("unsupported input type '%s' (use .csv .tsv .txt .tab .parquet .pq .pkl .pickle .json "
                     ".jsonl .ndjson)" % ext)


def _new_info(fmt, text=None):
    return {"format": fmt, "text": text, "declared": {}, "notes": [], "problems": []}


def _sniff_sep(header):
    if header.count(",") > 0:
        return ","
    best = max([";", "\t", "|"], key=header.count)
    return best if header.count(best) > 0 else ","


def _read_delimited(path, ext, sep, encoding):
    info = _new_info("delimited text", "csv")
    if sep == "\\t":
        sep = "\t"
    if sep is not None and len(sep) != 1:
        raise UsageError("--sep must be one character, got %r" % sep)
    encodings = [encoding] if encoding else ["utf-8-sig", "cp1252", "latin-1"]
    df = None
    header = ""
    last_error = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                header = fh.readline()
            use_sep = sep
            if use_sep is None:
                if ext in (".tsv", ".tab"):
                    use_sep = "\t"
                else:
                    use_sep = _sniff_sep(header)
                    if use_sep != "," and not any(use_sep in n for n in info["notes"]):
                        info["notes"].append("no comma in the header line; separator %r detected (override "
                                             "with --sep)" % use_sep)
            df = pd.read_csv(path, sep=use_sep, dtype=str, keep_default_na=False, na_filter=False,
                             encoding=enc, skip_blank_lines=True)
            if enc not in ("utf-8-sig", encoding):
                info["notes"].append("the file is not valid UTF-8; read as %s (choose with --encoding)" % enc)
            sep = use_sep
            break
        except UnicodeDecodeError as exc:
            last_error = exc
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise UsageError("cannot parse %s as delimited text: %s" % (path, exc))
    if df is None:
        raise UsageError("cannot decode %s: %s" % (path, last_error))
    names = next(csv.reader([header.lstrip("\ufeff").rstrip("\r\n")], delimiter=sep)) if header.strip() else []
    seen = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    dupes = sorted(n for n, k in seen.items() if k > 1)
    if dupes:
        info["problems"].append("duplicate column names in the header: %s (pandas would rename them %s.1, ...)"
                                % (", ".join(repr(d) for d in dupes), dupes[0]))
    return df, info


_ARROW_INT_MAPPER = None


def _arrow_types_mapper():
    global _ARROW_INT_MAPPER
    if _ARROW_INT_MAPPER is None:
        import pyarrow as pa
        _ARROW_INT_MAPPER = {
            pa.int8(): pd.Int8Dtype(), pa.int16(): pd.Int16Dtype(), pa.int32(): pd.Int32Dtype(),
            pa.int64(): pd.Int64Dtype(), pa.uint8(): pd.UInt8Dtype(), pa.uint16(): pd.UInt16Dtype(),
            pa.uint32(): pd.UInt32Dtype(), pa.uint64(): pd.UInt64Dtype(), pa.bool_(): pd.BooleanDtype(),
        }
    return _ARROW_INT_MAPPER.get


def _arrow_type(t):
    """pyarrow DataType -> (Spotfire type or None, reason when None)."""
    import pyarrow as pa
    T = pa.types
    if T.is_dictionary(t):
        return _arrow_type(t.value_type)
    if T.is_boolean(t):
        return "Boolean", ""
    if T.is_integer(t):
        if T.is_signed_integer(t):
            return ("Integer" if t.bit_width <= 32 else "LongInteger"), ""
        return ("Integer" if t.bit_width <= 16 else "LongInteger"), ""
    if T.is_floating(t):
        return ("SingleReal" if t.bit_width <= 32 else "Real"), ""
    if T.is_decimal(t):
        return "Currency", ""
    if T.is_timestamp(t):
        return "DateTime", ""
    if T.is_date(t):
        return "Date", ""
    if T.is_time(t):
        return "Time", ""
    if T.is_duration(t):
        return "TimeSpan", ""
    if T.is_string(t) or T.is_large_string(t) or (hasattr(T, "is_string_view") and T.is_string_view(t)):
        return "String", ""
    if T.is_binary(t) or T.is_large_binary(t) or T.is_fixed_size_binary(t) or \
            (hasattr(T, "is_binary_view") and T.is_binary_view(t)):
        return "Binary", ""
    if T.is_null(t):
        return None, "all values are missing"
    return None, "nested or unsupported type %s" % t


def _read_parquet(path):
    import pyarrow.parquet as pq
    info = _new_info("parquet")
    table = pq.read_table(path)
    df = table.to_pandas(types_mapper=_arrow_types_mapper())
    for field in table.schema:
        t, _why = _arrow_type(field.type)
        if t:
            info["declared"][str(field.name)] = (t, "parquet %s" % field.type)
    return df, info


def _read_pickle(path):
    info = _new_info("pickle")
    obj = pd.read_pickle(path)
    if isinstance(obj, pd.Series):
        obj = obj.to_frame(name=obj.name if obj.name is not None else "Value")
    if not isinstance(obj, pd.DataFrame):
        raise UsageError("the pickle holds a %s, not a pandas DataFrame or Series" % type(obj).__name__)
    return obj, info


_JSON_SCHEMA_TYPES = {"integer": "LongInteger", "number": "Real", "boolean": "Boolean", "datetime": "DateTime",
                      "duration": "TimeSpan", "string": "String"}


def _records_to_columns(records, where):
    order = []
    seen = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise UsageError("%s: item %d is not an object (records need column names)" % (where, i + 1))
        for k in rec:
            if k not in seen:
                seen.add(k)
                order.append(k)
    return dict((str(k), [rec.get(k) for rec in records]) for k in order), order


def _read_json(path, lines):
    info = _new_info("JSON lines" if lines else "JSON", "json")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            if lines:
                data = [json.loads(line) for line in fh if line.strip()]
            else:
                data = json.load(fh)
    except ValueError as exc:
        raise UsageError("cannot parse %s as JSON: %s" % (path, exc))
    columns = None
    if isinstance(data, list):
        columns, _ = _records_to_columns(data, path)
    elif isinstance(data, dict):
        if isinstance(data.get("schema"), dict) and isinstance(data.get("data"), list):
            columns, _ = _records_to_columns(data["data"], path + " (table orient)")
            info["format"] = "JSON (table orient)"
            fields = data["schema"].get("fields") or []
            for f in fields:
                name = str(f.get("name"))
                t = _JSON_SCHEMA_TYPES.get(str(f.get("type", "")).lower())
                if t and name in columns:
                    info["declared"][name] = (t, "JSON schema %s" % f.get("type"))
            pk = data["schema"].get("primaryKey") or []
            if pk == ["index"] and "index" in columns and columns["index"] == list(range(len(columns["index"]))):
                del columns["index"]
                info["declared"].pop("index", None)
                info["notes"].append("dropped the default pandas 'index' field of the table-orient file")
        elif isinstance(data.get("columns"), list) and isinstance(data.get("data"), list):
            names = [str(c) for c in data["columns"]]
            rows = data["data"]
            for i, r in enumerate(rows):
                if not isinstance(r, list) or len(r) != len(names):
                    raise UsageError("%s (split orient): row %d does not have %d values" % (path, i + 1, len(names)))
            columns = dict((n, [r[j] for r in rows]) for j, n in enumerate(names))
            info["format"] = "JSON (split orient)"
        elif data and all(isinstance(v, list) for v in data.values()):
            lengths = set(len(v) for v in data.values())
            if len(lengths) > 1:
                raise UsageError("%s: the column lists have different lengths %s" % (path, sorted(lengths)))
            columns = dict((str(k), list(v)) for k, v in data.items())
        elif data and all(isinstance(v, dict) for v in data.values()):
            index = []
            seen = set()
            for v in data.values():
                for k in v:
                    if k not in seen:
                        seen.add(k)
                        index.append(k)
            columns = dict((str(c), [v.get(k) for k in index]) for c, v in data.items())
            info["format"] = "JSON (columns orient)"
    if columns is None:
        raise UsageError("unsupported JSON layout in %s: use a list of records, {column: [values]}, "
                         "{column: {row: value}}, or pandas split / table orient" % path)
    df = pd.DataFrame(dict((k, pd.Series(v, dtype=object)) for k, v in columns.items()))
    return df, info


# --------------------------------------------------------------------------------------------- columns
class _Column(object):
    """One input column: typed values, or raw text (delimited text, JSON strings) with missing masks."""

    def __init__(self, name, series, text=None):
        s = series.reset_index(drop=True)
        self.name = name
        self.s = s
        self.n = len(s)
        self.text = text
        if text:
            raw = s.astype(object)
            raw = raw.where(raw.notna(), None)
            stripped = raw.str.strip()
            empty = stripped.isna() | (stripped == "")
            self.raw = raw
            self.stripped = stripped
            if text == "csv":
                self.blank = empty.to_numpy(dtype=bool)
                self.na = (empty | stripped.isin(NA_TOKENS)).to_numpy(dtype=bool)
            else:
                self.blank = raw.isna().to_numpy(dtype=bool)
                self.na = empty.to_numpy(dtype=bool)
        else:
            self.raw = self.stripped = None
            self.na = s.isna().to_numpy(dtype=bool)
            self.blank = self.na

    def values(self):
        """(row, value) for every non-missing row; text columns give the stripped text."""
        src = self.stripped if self.text else self.s
        vals = src.tolist()
        return [(i, vals[i]) for i in range(self.n) if not self.na[i]]


def _short(v):
    r = repr(v)
    return r if len(r) <= 40 else r[:37] + "..."


def _fail(failures, what):
    ex = ", ".join("row %d: %s%s" % (r + 1, _short(v), (" (" + why + ")") if why else "")
                   for r, v, why in failures[:3])
    more = "" if len(failures) <= 3 else ", ..."
    raise _Refuse("%d value(s) cannot be stored as %s (%s%s)" % (len(failures), what, ex, more))


def _kind_of_type(t):
    # numpy's timedelta64 derives from np.signedinteger, so the date/time kinds are tested first
    if issubclass(t, (_dt.datetime, np.datetime64)):
        return "datetime"
    if issubclass(t, _dt.date):
        return "date"
    if issubclass(t, _dt.time):
        return "time"
    if issubclass(t, (_dt.timedelta, np.timedelta64)):
        return "timedelta"
    if issubclass(t, (bool, np.bool_)):
        return "bool"
    if issubclass(t, (int, np.integer)):
        return "int"
    if issubclass(t, (float, np.floating)):
        return "float"
    if issubclass(t, decimal.Decimal):
        return "decimal"
    if issubclass(t, str):
        return "str"
    if issubclass(t, (bytes, bytearray, memoryview)):
        return "bytes"
    return "other:" + t.__name__


def _object_kinds(col):
    vals = col.s[~col.na]
    if len(vals) == 0:
        return set()
    return set(_kind_of_type(t) for t in pd.unique(vals.map(type)))


def _is_text_series(s):
    """String dtype, or object dtype whose present values are all str (and at least one is present)."""
    if isinstance(s.dtype, pd.StringDtype):
        return True
    if s.dtype != object:
        return False
    present = s.dropna()
    return len(present) > 0 and all(issubclass(t, str) for t in pd.unique(present.map(type)))


def _is_aware(v):
    if isinstance(v, pd.Timestamp):
        return v.tz is not None
    return isinstance(v, _dt.datetime) and v.tzinfo is not None and v.utcoffset() is not None


def _naive_value(v, tz):
    """Timestamp / datetime -> naive datetime per --tz (wall: drop the zone; utc: convert, then drop)."""
    if isinstance(v, np.datetime64):
        v = pd.Timestamp(v)
    if isinstance(v, pd.Timestamp):
        if v.tz is not None:
            v = v.tz_convert("UTC").tz_localize(None) if tz == "utc" else v.tz_localize(None)
        return v.to_pydatetime() if v.nanosecond == 0 else pd.Timestamp(v).floor("us").to_pydatetime()
    if v.tzinfo is not None and v.utcoffset() is not None:
        if tz == "utc":
            v = v.astimezone(_dt.timezone.utc)
        v = v.replace(tzinfo=None)
    return v


def _naive_series(s, tz):
    if getattr(s.dt, "tz", None) is None:
        return s
    if tz == "utc":
        return s.dt.tz_convert("UTC").dt.tz_localize(None)
    return s.dt.tz_localize(None)


def _has_time_directive(fmt):
    if fmt in ("ISO8601", "mixed"):
        return True
    return any(("%" + c) in fmt for c in _TIME_DIRECTIVES)


def _parse_text_datetimes(texts, fmt, tz, notes, name):
    """Series of str (NaN for missing) -> naive datetime64 Series (NaT where it does not parse)."""
    if fmt:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(texts, format=fmt, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = _naive_series(parsed, tz)
            notes.append("column '%s': time-zone offsets %s" % (name, _tz_words(tz)))
        return parsed
    m = texts.str.extract(_ISO_RE)
    matched = m["date"].notna()
    norm = m["date"].where(m["time"].isna(), m["date"] + "T" + m["time"].str.replace(",", ".", regex=False))
    norm = norm.where(matched)
    has_tz = m["tz"].notna() & matched
    if has_tz.any():
        if tz == "utc":
            full = norm.where(~has_tz, norm + m["tz"])
            parsed = pd.to_datetime(full, format="ISO8601", errors="coerce", utc=True).dt.tz_localize(None)
            if (matched & ~has_tz).any():
                notes.append("column '%s': values without an offset were taken as UTC" % name)
        else:
            parsed = pd.to_datetime(norm, format="ISO8601", errors="coerce")
        notes.append("column '%s': time-zone offsets %s" % (name, _tz_words(tz)))
    else:
        parsed = pd.to_datetime(norm, format="ISO8601", errors="coerce")
    return parsed


def _tz_words(tz):
    return "converted to UTC, then dropped (--tz utc)" if tz == "utc" else \
        "dropped, wall-clock time kept (--tz utc converts to UTC instead)"


def _parse_time_text(v):
    m = _TIME_TEXT_RE.match(v)
    if not m:
        return None
    h, mi = int(m.group("h")), int(m.group("m"))
    sec = int(m.group("s") or 0)
    frac = (m.group("f") or "")[:6].ljust(6, "0")
    ampm = (m.group("ampm") or "").lower()
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if ampm == "pm" else 0)
    if h > 23 or mi > 59 or sec > 59:
        return None
    return _dt.time(h, mi, sec, int(frac))


# ----------------------------------------------------------------------------------------- converters
def _to_string(col, ctx):
    if col.text:
        out = col.raw.where(~pd.Series(col.blank), None)
        return out.astype(object)
    if _is_text_series(col.s) or not (~col.na).any():
        return col.s.astype(object).where(~pd.Series(col.na), None)
    failures = []
    out = [None] * col.n
    for i, v in col.values():
        try:
            out[i] = _text_of(v)
        except TypeError as exc:
            failures.append((i, v, str(exc)))
    if failures:
        _fail(failures, "String")
    return pd.Series(out, dtype=object)


def _text_of(v):
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, np.bool_)):
        return "True" if v else "False"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating, decimal.Decimal)):
        return str(v)
    if isinstance(v, (pd.Timestamp, _dt.datetime)):
        return v.isoformat(sep=" ")
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, (pd.Timedelta, _dt.timedelta, np.timedelta64)):
        return str(pd.Timedelta(v))
    if isinstance(v, np.datetime64):
        return str(pd.Timestamp(v))
    raise TypeError("%s is not text" % type(v).__name__)


def _to_boolean(col, ctx):
    s = col.s
    if not col.text and pd.api.types.is_bool_dtype(s.dtype):
        return s.astype("boolean")
    out = np.empty(col.n, dtype=object)
    out[:] = None
    failures = []
    strict = ctx.get("strict_bool", False)
    t_tokens, f_tokens = (("true",), ("false",)) if strict else (_TRUE_TOKENS, _FALSE_TOKENS)
    numeric = not col.text and pd.api.types.is_numeric_dtype(s.dtype)
    for i, v in col.values():
        if isinstance(v, (bool, np.bool_)):
            out[i] = bool(v)
        elif isinstance(v, str):
            low = v.strip().lower()
            if low in t_tokens:
                out[i] = True
            elif low in f_tokens:
                out[i] = False
            else:
                failures.append((i, v, ""))
        elif numeric or isinstance(v, (int, float, np.integer, np.floating)):
            if v == 1:
                out[i] = True
            elif v == 0:
                out[i] = False
            else:
                failures.append((i, v, "only 0 and 1"))
        else:
            failures.append((i, v, ""))
    if failures:
        _fail(failures, "Boolean")
    return pd.Series(out, dtype="boolean")


def _to_integer(col, ctx):
    target = ctx["type"]
    lo, hi = _INT_RANGE[target]
    dtype_name = "Int32" if target == "Integer" else "Int64"
    s = col.s
    failures = []
    if not col.text and pd.api.types.is_integer_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        present = s[~col.na]
        if len(present):
            mn, mx = int(present.min()), int(present.max())
            if mn < lo or mx > hi:
                for i, v in col.values():
                    if not lo <= int(v) <= hi:
                        failures.append((i, v, "out of %s range" % target))
                _fail(failures, target)
        return s.astype(dtype_name)
    out = [None] * col.n
    for i, v in col.values():
        iv = None
        why = ""
        if isinstance(v, (bool, np.bool_)):
            iv = int(v)
        elif isinstance(v, (int, np.integer)):
            iv = int(v)
        elif isinstance(v, (float, np.floating)):
            if math.isfinite(v) and float(v).is_integer():
                iv = int(v)
            else:
                why = "not a whole number"
        elif isinstance(v, decimal.Decimal):
            if v.is_finite() and v == v.to_integral_value():
                iv = int(v)
            else:
                why = "not a whole number"
        elif isinstance(v, str):
            t = v.strip()
            if re.fullmatch(_INT_TEXT, t):
                iv = int(t)
            else:
                try:
                    f = float(t)
                except ValueError:
                    f = None
                if f is not None and math.isfinite(f) and f.is_integer() and abs(f) < 2 ** 53:
                    iv = int(f)
                else:
                    why = "not a whole number" if f is not None else ""
        if iv is None:
            failures.append((i, v, why))
        elif not lo <= iv <= hi:
            failures.append((i, v, "out of %s range" % target))
        else:
            out[i] = iv
    if failures:
        _fail(failures, target)
    return pd.Series(pd.array(out, dtype=dtype_name))


def _to_real(col, ctx):
    single = ctx["type"] == "SingleReal"
    s = col.s
    notes = ctx["notes"]
    if not col.text and pd.api.types.is_numeric_dtype(s.dtype):
        vals = s.to_numpy(dtype="float64", na_value=np.nan)
        if pd.api.types.is_integer_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype) and \
                len(s[~col.na]) and max(abs(int(s[~col.na].min())), abs(int(s[~col.na].max()))) > 2 ** 53:
            notes.append("column '%s': integers above 2**53 lose precision as Real" % col.name)
    elif col.text:
        texts = col.stripped.where(~pd.Series(col.na))
        vals = pd.to_numeric(texts, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
        bad = np.flatnonzero(~col.na & np.isnan(vals))
        if len(bad):
            stripped = col.stripped.tolist()
            _fail([(int(i), stripped[i], "") for i in bad], ctx["type"])
    else:
        vals = np.full(col.n, np.nan)
        failures = []
        for i, v in col.values():
            if isinstance(v, (bool, np.bool_, int, float, np.integer, np.floating, decimal.Decimal)):
                vals[i] = float(v)
            elif isinstance(v, str):
                try:
                    vals[i] = float(v.strip())
                except ValueError:
                    failures.append((i, v, ""))
            else:
                failures.append((i, v, ""))
        if failures:
            _fail(failures, ctx["type"])
    vals = np.where(col.na, np.nan, vals)
    if np.isinf(vals).any():
        notes.append("column '%s': contains infinite values" % col.name)
    if single:
        with np.errstate(over="ignore"):
            f32 = vals.astype("float32")
        over = np.flatnonzero(np.isfinite(vals) & ~np.isfinite(f32))
        if len(over):
            _fail([(int(i), vals[i], "outside SingleReal range") for i in over], "SingleReal")
        return pd.Series(f32, dtype="float32")
    return pd.Series(vals, dtype="float64")


def _currency_value(v):
    if isinstance(v, decimal.Decimal):
        d = v
    elif isinstance(v, (bool, np.bool_)):
        raise ValueError("a Boolean is not an amount")
    elif isinstance(v, (int, np.integer)):
        d = decimal.Decimal(int(v))
    elif isinstance(v, (float, np.floating)):
        d = decimal.Decimal(repr(float(v)))
    elif isinstance(v, str):
        try:
            d = decimal.Decimal(v.strip())
        except decimal.InvalidOperation:
            raise ValueError("")
    else:
        raise ValueError("")
    if not d.is_finite():
        raise ValueError("not a finite number")
    ctx = decimal.Context(prec=120)
    if d.as_tuple().exponent > 0:
        d = d.quantize(decimal.Decimal(1), context=ctx)
    sign, digits, exp = d.as_tuple()
    if exp < -28:
        raise ValueError("more than 28 decimal places")
    if int("".join(str(x) for x in digits) or "0") >= 2 ** 96:
        raise ValueError("too many digits for Currency")
    return d


def _to_currency(col, ctx):
    out = [None] * col.n
    failures = []
    for i, v in col.values():
        try:
            out[i] = _currency_value(v)
        except ValueError as exc:
            failures.append((i, v, str(exc)))
    if failures:
        _fail(failures, "Currency")
    return pd.Series(out, dtype=object)


def _to_datetime(col, ctx):
    s = col.s
    tz, notes, name = ctx["tz"], ctx["notes"], col.name
    if not col.text and pd.api.types.is_datetime64_any_dtype(s.dtype):
        if getattr(s.dt, "tz", None) is not None:
            notes.append("column '%s': time zone %s %s" % (name, s.dt.tz, _tz_words(tz)))
        out = _naive_series(s, tz)
    elif col.text:
        texts = col.stripped.where(~pd.Series(col.na))
        out = _parse_text_datetimes(texts, ctx.get("fmt"), tz, notes, name)
        bad = np.flatnonzero(~col.na & out.isna().to_numpy(dtype=bool))
        if len(bad):
            stripped = col.stripped.tolist()
            _fail([(int(i), stripped[i], "") for i in bad],
                  "DateTime" + (" with format %r" % ctx["fmt"] if ctx.get("fmt") else " (ISO 8601 expected; "
                                                                                     "pass --date-format)"))
    elif pd.api.types.is_numeric_dtype(s.dtype):
        raise _Refuse("numbers are not dates (epoch values need converting first)")
    else:
        vals = np.empty(col.n, dtype=object)
        vals[:] = None
        failures = []
        aware = False
        for i, v in col.values():
            if isinstance(v, (pd.Timestamp, _dt.datetime, np.datetime64)):
                aware = aware or _is_aware(v)
                vals[i] = _naive_value(v, tz)
            elif isinstance(v, _dt.date):
                vals[i] = _dt.datetime(v.year, v.month, v.day)
            elif isinstance(v, str):
                p = _parse_text_datetimes(pd.Series([v.strip()], dtype=object), ctx.get("fmt"), tz, [], name)[0]
                if pd.isna(p):
                    failures.append((i, v, ""))
                else:
                    vals[i] = p.to_pydatetime()
            else:
                failures.append((i, v, ""))
        if failures:
            _fail(failures, "DateTime")
        if aware:
            notes.append("column '%s': time-zone-aware values %s" % (name, _tz_words(tz)))
        out = pd.Series(np.array(vals.tolist(), dtype="datetime64[us]"))
    out = out.reset_index(drop=True)
    floored = out.dt.floor("ms")
    if not floored.equals(out):
        notes.append("column '%s': sub-millisecond precision cut (SBDF DateTime stores milliseconds)" % name)
    return floored


def _to_date(col, ctx):
    s = col.s
    name = col.name
    out = [None] * col.n
    failures = []
    if (not col.text and pd.api.types.is_datetime64_any_dtype(s.dtype)) or col.text:
        if col.text:
            texts = col.stripped.where(~pd.Series(col.na))
            parsed = _parse_text_datetimes(texts, ctx.get("fmt"), ctx["tz"], ctx["notes"], name)
        else:
            parsed = _naive_series(s, ctx["tz"]).reset_index(drop=True)
        src = col.stripped.tolist() if col.text else s.tolist()
        plist = parsed.tolist()
        for i in range(col.n):
            if col.na[i]:
                continue
            p = plist[i]
            if p is None or pd.isna(p):
                failures.append((i, src[i], ""))
            elif (p.hour, p.minute, p.second, p.microsecond) != (0, 0, 0, 0):
                failures.append((i, src[i], "has a time of day; use DateTime"))
            else:
                out[i] = _dt.date(p.year, p.month, p.day)
    else:
        for i, v in col.values():
            if isinstance(v, (pd.Timestamp, _dt.datetime, np.datetime64)):
                d = _naive_value(v, ctx["tz"])
                if (d.hour, d.minute, d.second, d.microsecond) != (0, 0, 0, 0):
                    failures.append((i, v, "has a time of day; use DateTime"))
                else:
                    out[i] = d.date()
            elif isinstance(v, _dt.date):
                out[i] = v
            elif isinstance(v, str):
                p = _parse_text_datetimes(pd.Series([v.strip()], dtype=object), ctx.get("fmt"), ctx["tz"], [],
                                          name)[0]
                if pd.isna(p) or (p.hour, p.minute, p.second, p.microsecond) != (0, 0, 0, 0):
                    failures.append((i, v, ""))
                else:
                    out[i] = p.date()
            else:
                failures.append((i, v, ""))
    if failures:
        _fail(failures, "Date")
    return pd.Series(out, dtype=object)


def _to_time(col, ctx):
    s = col.s
    fmt = ctx.get("fmt")
    out = [None] * col.n
    failures = []
    cut = False
    tz_dropped = False
    is_td = not col.text and pd.api.types.is_timedelta64_dtype(s.dtype)
    for i, v in col.values():
        t = None
        why = ""
        if isinstance(v, _dt.time):
            t = v
            if t.tzinfo is not None:
                t = t.replace(tzinfo=None)
                tz_dropped = True
        elif is_td or isinstance(v, (_dt.timedelta, np.timedelta64)):
            td = pd.Timedelta(v)
            if pd.Timedelta(0) <= td < pd.Timedelta(days=1):
                us = int(td / pd.Timedelta(microseconds=1))
                t = _dt.time(us // 3600000000, (us // 60000000) % 60, (us // 1000000) % 60, us % 1000000)
            else:
                why = "not between 00:00 and 24:00"
        elif isinstance(v, str):
            txt = v.strip()
            if fmt and fmt not in ("ISO8601", "mixed"):
                try:
                    t = _dt.datetime.strptime(txt, fmt).time()
                except ValueError:
                    t = None
            else:
                t = _parse_time_text(txt)
        elif isinstance(v, (pd.Timestamp, _dt.datetime, np.datetime64)):
            why = "has a date; use DateTime"
        if t is None:
            failures.append((i, v, why))
            continue
        if t.microsecond % 1000:
            t = t.replace(microsecond=t.microsecond // 1000 * 1000)
            cut = True
        out[i] = t
    if failures:
        _fail(failures, "Time" + (" with format %r" % fmt if fmt else " (HH:MM[:SS[.fff]] [AM|PM] expected)"))
    if cut:
        ctx["notes"].append("column '%s': sub-millisecond precision cut (SBDF Time stores milliseconds)" % col.name)
    if tz_dropped:
        ctx["notes"].append("column '%s': time-of-day zone information dropped" % col.name)
    return pd.Series(out, dtype=object)


def _to_timespan(col, ctx):
    s = col.s
    if not col.text and pd.api.types.is_timedelta64_dtype(s.dtype):
        out = s.reset_index(drop=True)
    elif not col.text and pd.api.types.is_numeric_dtype(s.dtype):
        raise _Refuse("numbers have no time unit; convert them to durations first (pd.to_timedelta(x, unit=...))")
    else:
        vals = [None] * col.n
        failures = []
        for i, v in col.values():
            if isinstance(v, str):
                txt = v.strip()
                if _BARE_NUMBER_RE.match(txt):
                    failures.append((i, v, "a number without a unit"))
                    continue
                try:
                    vals[i] = pd.Timedelta(txt)
                except (ValueError, TypeError):
                    failures.append((i, v, ""))
            elif isinstance(v, (_dt.timedelta, np.timedelta64)):
                vals[i] = pd.Timedelta(v)
            else:
                failures.append((i, v, ""))
        if failures:
            _fail(failures, "TimeSpan")
        out = pd.Series(pd.to_timedelta(pd.Series(vals, dtype=object)))
    floored = out.dt.floor("ms")
    if not floored.equals(out):
        ctx["notes"].append("column '%s': sub-millisecond precision cut (SBDF TimeSpan stores milliseconds)"
                            % col.name)
    return floored


def _to_binary(col, ctx):
    if col.text:
        raise _Refuse("Binary needs bytes values (pickle or parquet input), not text")
    out = [None] * col.n
    failures = []
    for i, v in col.values():
        if isinstance(v, (bytes, bytearray, memoryview)):
            out[i] = bytes(v)
        else:
            failures.append((i, v, ""))
    if failures:
        _fail(failures, "Binary")
    return pd.Series(out, dtype=object)


_CONVERTERS = {
    "String": _to_string, "Boolean": _to_boolean, "Integer": _to_integer, "LongInteger": _to_integer,
    "Real": _to_real, "SingleReal": _to_real, "Currency": _to_currency, "DateTime": _to_datetime,
    "Date": _to_date, "Time": _to_time, "TimeSpan": _to_timespan, "Binary": _to_binary,
}


# ----------------------------------------------------------------------------------------- inference
def _infer_text(col, ctx):
    """Delimited text ("csv": every rule) or JSON strings ("json": dates only) -> (type, source)."""
    vals = col.stripped[~pd.Series(col.na)]
    if len(vals) == 0:
        raise _Refuse("all values are missing, so the type cannot be inferred: name it in --types")
    fmt = ctx.get("fmt")
    if fmt:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(vals, format=fmt, errors="coerce")
        if parsed.notna().all():
            return ("DateTime" if _has_time_directive(fmt) else "Date"), "text, date format %s" % fmt
    if col.text == "csv":
        low = vals.str.lower()
        if low.isin(["true", "false"]).all():
            ctx["strict_bool"] = True
            return "Boolean", "text: true/false"
        if vals.str.fullmatch(_INT_TEXT).all():
            if vals.str.fullmatch(_LEADING_ZERO_TEXT).any():
                ctx["notes"].append("column '%s': integers with leading zeros (e.g. %r) kept as String"
                                    % (col.name, vals[vals.str.fullmatch(_LEADING_ZERO_TEXT)].iloc[0]))
                return "String", "text: leading zeros"
            if any(not _INT_RANGE["LongInteger"][0] <= int(v) <= _INT_RANGE["LongInteger"][1]
                   for v in vals[vals.str.lstrip("+-").str.len() > 18]):
                ctx["notes"].append("column '%s': integers beyond 64 bits kept as String" % col.name)
                return "String", "text: integers beyond 64 bits"
            return "LongInteger", "text: integer"
        if pd.to_numeric(vals, errors="coerce").notna().all():
            return "Real", "text: number"
    m = vals.str.extract(_ISO_RE)
    if m["date"].notna().all():
        if m["time"].isna().all():
            return "Date", "text: ISO date"
        return "DateTime", "text: ISO date-time"
    hint = _text_hint(vals)
    if hint:
        ctx["notes"].append("column '%s': %s" % (col.name, hint))
    return "String", "text"


def _text_hint(vals):
    sample = vals.head(200)
    if sample.str.fullmatch(r"[0-9]{1,2}:[0-9]{2}(:[0-9]{2}([.,][0-9]+)?)?(\s*[AaPp][Mm])?").all():
        return "looks like times of day or durations; kept as String (use --types Col=Time or Col=TimeSpan)"
    if sample.str.fullmatch(r"[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}([ T].*)?").all():
        return "looks like dates in a local format; kept as String (pass --date-format, e.g. '%m/%d/%Y')"
    if sample.str.fullmatch(r"[+-]?[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?").all():
        return "looks like numbers with thousands separators; kept as String (remove the separators first)"
    if sample.str.fullmatch(r"[+-]?[0-9]+,[0-9]+").all():
        return "looks like numbers with decimal commas; kept as String (convert them to '.' first)"
    return ""


def _infer_typed(col, ctx):
    """Typed column (parquet, pickle, JSON values) -> (type, source); may replace col.s."""
    s = col.s
    dt = s.dtype
    dname = str(dt)
    if isinstance(dt, pd.CategoricalDtype):
        # the categories carry the type (even when every value is missing); the values go on as objects
        values = s.astype(object).where(s.notna(), None)
        if len(dt.categories):
            t, src = _infer_typed(_Column(col.name, pd.Series(dt.categories), None), ctx)
        else:
            t, src = _infer_typed(_Column(col.name, values, None), ctx)
        col.s = values
        col.na = values.isna().to_numpy(dtype=bool)
        return t, "category of " + src
    if hasattr(pd, "SparseDtype") and isinstance(dt, pd.SparseDtype):
        col.s = s.sparse.to_dense()
        return _infer_typed(col, ctx)
    if hasattr(pd, "ArrowDtype") and isinstance(dt, pd.ArrowDtype):
        t, why = _arrow_type(dt.pyarrow_dtype)
        if not t:
            raise _Refuse(why)
        col.s = s.astype(object).where(s.notna(), None)
        return t, dname
    if pd.api.types.is_bool_dtype(dt):
        return "Boolean", dname
    if pd.api.types.is_integer_dtype(dt):
        size = np.dtype(dt.numpy_dtype if hasattr(dt, "numpy_dtype") else dt).itemsize
        signed = pd.api.types.is_signed_integer_dtype(dt)
        if (signed and size <= 4) or (not signed and size <= 2):
            return "Integer", dname
        return "LongInteger", dname
    if pd.api.types.is_float_dtype(dt):
        size = np.dtype(dt.numpy_dtype if hasattr(dt, "numpy_dtype") else dt).itemsize
        return ("SingleReal" if size <= 4 else "Real"), dname
    if pd.api.types.is_datetime64_any_dtype(dt):
        return "DateTime", dname
    if pd.api.types.is_timedelta64_dtype(dt):
        return "TimeSpan", dname
    if pd.api.types.is_complex_dtype(dt):
        raise _Refuse("complex numbers have no Spotfire type")
    if isinstance(dt, pd.PeriodDtype):
        raise _Refuse("period values have no Spotfire type (convert with .dt.to_timestamp())")
    if isinstance(dt, pd.IntervalDtype):
        raise _Refuse("interval values have no Spotfire type")
    if isinstance(dt, pd.StringDtype):
        return "String", dname
    if dt != object:
        raise _Refuse("dtype %s has no Spotfire type" % dname)
    kinds = _object_kinds(col)
    src = "object: " + "+".join(sorted(kinds))
    if not kinds:
        raise _Refuse("all values are missing, so the type cannot be inferred: name it in --types")
    others = sorted(k[6:] for k in kinds if k.startswith("other:"))
    if others:
        raise _Refuse("values of type %s have no Spotfire type%s" % (
            ", ".join(others), " (nested JSON: flatten it first)" if set(others) & {"list", "dict"} else ""))
    simple = {
        frozenset(["bool"]): "Boolean", frozenset(["int"]): "LongInteger", frozenset(["float"]): "Real",
        frozenset(["int", "float"]): "Real", frozenset(["decimal"]): "Currency",
        frozenset(["decimal", "int"]): "Currency", frozenset(["bytes"]): "Binary",
        frozenset(["datetime"]): "DateTime", frozenset(["datetime", "date"]): "DateTime",
        frozenset(["date"]): "Date", frozenset(["time"]): "Time", frozenset(["timedelta"]): "TimeSpan",
    }
    key = frozenset(kinds)
    if key == frozenset(["str"]):
        return "String", src
    if key in simple:
        if key == frozenset(["datetime", "date"]):
            ctx["notes"].append("column '%s': mixes dates and date-times; written as DateTime" % col.name)
        return simple[key], src
    raise _Refuse("mixed value types (%s); name the column in --types (e.g. String) to convert them"
                  % ", ".join(sorted(kinds)))


# ------------------------------------------------------------------------------------------ planning
def parse_types(specs):
    """'Col=Type,Other=Type' (or a list of such strings, or a dict) -> {column: Type}."""
    if not specs:
        return {}
    if isinstance(specs, dict):
        items = list(specs.items())
    else:
        if isinstance(specs, str):
            specs = [specs]
        items = []
        for spec in specs:
            pending = ""
            for piece in spec.split(","):
                pending = piece if not pending else pending + "," + piece
                m = re.match(r"^(.*)=\s*([A-Za-z]+)\s*$", pending)
                if m and m.group(2).lower() in _TYPE_BY_LOWER:
                    items.append((m.group(1).strip(), m.group(2)))
                    pending = ""
            if pending.strip():
                raise UsageError("cannot read --types entry %r: write Column=Type with Type one of %s"
                                 % (pending, ", ".join(SPOTFIRE_TYPES)))
    out = {}
    for name, t in items:
        canon = _TYPE_BY_LOWER.get(str(t).strip().lower())
        if not canon:
            raise UsageError("unknown Spotfire type %r for column %r (use %s)" % (t, name, ", ".join(SPOTFIRE_TYPES)))
        if not name:
            raise UsageError("--types entry with an empty column name")
        out[str(name)] = canon
    return out


def parse_date_formats(specs):
    """--date-format values -> {None: global format, column: format}."""
    if not specs:
        return {}
    if isinstance(specs, dict):
        return dict(specs)
    if isinstance(specs, str):
        specs = [specs]
    out = {}
    for spec in specs:
        m = re.match(r"^([^%=]+)=(.+)$", spec)
        if m and ("%" in m.group(2) or m.group(2) in ("ISO8601", "mixed")):
            out[m.group(1).strip()] = m.group(2)
        else:
            if None in out:
                raise UsageError("give one global --date-format (use Column=FORMAT for others)")
            out[None] = spec
    return out


def _split_names(specs):
    out = []
    for spec in specs or []:
        out.extend(p.strip() for p in spec.split(",") if p.strip())
    return out


def _is_default_index(idx):
    return isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1 and idx.name is None


def coerce_frame(df, types=None, date_format=None, tz="wall", text=None, declared=None, drop=None, notes=None):
    """Plan and convert every column. Returns (frame, plan, notes, problems); frame is None when there are
    problems. plan: [{"name", "type", "source", "missing"}]."""
    _require_spotfire()
    if tz not in ("wall", "utc"):
        raise UsageError("--tz must be wall or utc")
    if not isinstance(df, pd.DataFrame):
        raise UsageError("expected a pandas DataFrame, got %s" % type(df).__name__)
    notes = list(notes or [])
    problems = []
    types = parse_types(types)
    formats = parse_date_formats(date_format)
    declared = dict(declared or {})
    if isinstance(df.columns, pd.MultiIndex):
        raise ExportRefused(["the columns have several levels (MultiIndex): flatten them first"], notes)
    if not _is_default_index(df.index):
        names = [n for n in df.index.names]
        df = df.reset_index()
        notes.append("the index (%s) became column(s) %s" % (
            ", ".join("unnamed" if n is None else str(n) for n in names),
            ", ".join(repr(str(c)) for c in df.columns[:len(names)])))
    if not all(isinstance(c, str) for c in df.columns):
        notes.append("non-text column names converted to text")
        df = df.copy()
        df.columns = [str(c) for c in df.columns]
    drop_names = _split_names(drop)
    unknown = [d for d in drop_names if d not in df.columns]
    if unknown:
        raise UsageError("--drop names columns that do not exist: %s" % ", ".join(repr(u) for u in unknown))
    if drop_names:
        df = df.drop(columns=drop_names)
        notes.append("dropped column(s): %s" % ", ".join(repr(d) for d in drop_names))
    cols = [str(c) for c in df.columns]
    if not cols:
        raise ExportRefused(["the table has no columns"], notes)
    for name in list(types) + [k for k in formats if k is not None]:
        if name not in cols:
            raise UsageError("column %r (in --types / --date-format) does not exist; columns: %s"
                             % (name, ", ".join(repr(c) for c in cols)))
    counts = {}
    for c in cols:
        counts[c] = counts.get(c, 0) + 1
    for c, k in counts.items():
        if k > 1:
            problems.append("column name %r appears %d times" % (c, k))
    lower = {}
    for c in cols:
        lower.setdefault(c.lower(), []).append(c)
        if not c.strip():
            problems.append("a column has an empty name")
        elif re.match(r"^Unnamed: \d+$", c):
            problems.append("column %r is pandas' placeholder for an empty header (often a saved index): "
                            "name it, or leave it out with --drop %r" % (c, c))
        elif c != c.strip():
            notes.append("column %r has leading or trailing spaces" % c)
    for group in lower.values():
        if len(group) > 1 and len(set(group)) > 1:
            notes.append("column names %s differ only in letter case; Spotfire may rename one of them"
                         % ", ".join(repr(g) for g in group))
    if problems:
        raise ExportRefused(problems, notes)

    out_cols = {}
    plan = []
    for pos, name in enumerate(cols):
        series = df.iloc[:, pos]
        # raw text: every column of delimited text; string columns of JSON (dates only) or of a frame
        # handed over with text="csv" / "json"
        is_text = text if (text in ("csv", "json") and _is_text_series(series)) else None
        col = _Column(name, series, is_text)
        ctx = {"tz": tz, "notes": notes, "fmt": formats.get(name, formats.get(None))}
        try:
            if name in types:
                target = types[name]
                source = "--types (%s)" % ("text" if col.text else str(series.dtype))
            elif name in formats:
                if not col.text:
                    raise _Refuse("--date-format names it, but it does not hold text")
                fmt = formats[name]
                target = "DateTime" if _has_time_directive(fmt) else "Date"
                source = "text, date format %s" % fmt
            elif name in declared:
                target, source = declared[name]
            elif col.text:
                target, source = _infer_text(col, ctx)
            else:
                target, source = _infer_typed(col, ctx)
            ctx["type"] = target
            converted = _CONVERTERS[target](col, ctx)
        except _Refuse as exc:
            problems.append("column %r: %s" % (name, exc))
            continue
        converted = converted.reset_index(drop=True)
        out_cols[name] = converted
        plan.append({"name": name, "type": target, "source": source, "missing": int(converted.isna().sum())})
    if problems:
        return None, plan, notes, problems
    frame = pd.DataFrame(out_cols, index=pd.RangeIndex(len(df)))
    return frame, plan, notes, problems


# ------------------------------------------------------------------------------------- write and check
def write_sbdf(frame, types, path):
    """Write frame with every column's Spotfire type pinned. Returns the writer's warnings."""
    _require_spotfire()
    tf = _TypedFrame(frame)
    tf.__dict__["_sbdf_types"] = dict(types)
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    tmp = path + ".tmp"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                _sbdf.export_data(tf, tmp)
            except _sbdf.SBDFError as exc:
                raise RuntimeError("spotfire.sbdf.export_data failed: %s" % exc)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return [str(w.message) for w in caught]


def _type_from_values(series):
    name = str(series.dtype)
    if name in ("Int32", "int32"):
        return "Integer"
    if name in ("Int64", "int64"):
        return "LongInteger"
    if name == "float32":
        return "SingleReal"
    if name == "float64":
        return "Real"
    present = series.dropna()
    if not len(present):
        return None
    kind = _kind_of_type(type(present.iloc[0]))
    return {"bool": "Boolean", "datetime": "DateTime", "date": "Date", "time": "Time", "timedelta": "TimeSpan",
            "str": "String", "bytes": "Binary", "decimal": "Currency"}.get(kind)


def read_back(path):
    """Read an SBDF file with spotfire.sbdf.import_data -> (DataFrame, {column: Spotfire type})."""
    _require_spotfire()
    with _keep_column_attrs():
        back = _sbdf.import_data(path)
    types = {}
    for c in back.columns:
        t = back[c].attrs.get("spotfire_type")
        types[str(c)] = t or _type_from_values(back[c])
    return pd.DataFrame(back), types


def _same_values(a, b, t):
    if t in ("Integer", "LongInteger"):
        return np.array_equal(a.to_numpy(dtype="int64"), pd.to_numeric(b).to_numpy(dtype="int64"))
    if t == "Real":
        return np.array_equal(a.to_numpy(dtype="float64"), b.to_numpy(dtype="float64"))
    if t == "SingleReal":
        return np.array_equal(a.to_numpy(dtype="float32"), b.to_numpy(dtype="float32"))
    if t == "Boolean":
        return [bool(x) for x in a.tolist()] == [bool(x) for x in b.tolist()]
    if t == "DateTime":
        return np.array_equal(a.to_numpy(dtype="datetime64[ms]"), np.array(b.tolist(), dtype="datetime64[ms]"))
    if t == "TimeSpan":
        return np.array_equal(a.to_numpy(dtype="timedelta64[ms]"), np.array(b.tolist(), dtype="timedelta64[ms]"))
    return a.tolist() == b.tolist()


def verify(frame, types, back, back_types):
    """Compare what was meant to be written with what import_data returns. -> list of problems."""
    problems = []
    if [str(c) for c in back.columns] != list(frame.columns):
        problems.append("columns read back %s, written %s" % (list(back.columns), list(frame.columns)))
        return problems
    if len(back) != len(frame):
        problems.append("%d rows read back, %d written" % (len(back), len(frame)))
        return problems
    for c in frame.columns:
        want, got = types[c], back_types.get(c)
        if got is not None and got != want:
            problems.append("column %r: written as %s, read back as %s" % (c, want, got))
            continue
        if got is None and frame[c].notna().any():
            problems.append("column %r: type not readable from the file" % c)
            continue
        a = frame[c].reset_index(drop=True)
        b = back[c].reset_index(drop=True)
        a_na = a.isna().to_numpy(dtype=bool)
        b_na = b.isna().to_numpy(dtype=bool)
        if not np.array_equal(a_na, b_na):
            problems.append("column %r: %d missing written, %d read back" % (c, a_na.sum(), b_na.sum()))
            continue
        if not _same_values(a[~a_na], b[~b_na], want):
            problems.append("column %r: values differ after the round trip" % c)
    return problems


def _example(v):
    if v is None:
        return ""
    if isinstance(v, _dt.datetime):
        return v.isoformat(sep=" ", timespec="milliseconds" if v.microsecond else "seconds")
    if isinstance(v, _dt.time):
        return v.isoformat(timespec="milliseconds" if v.microsecond else "seconds")
    if isinstance(v, bytes):
        return "0x" + v[:12].hex() + ("..." if len(v) > 12 else "")
    text = str(v)
    return text if len(text) <= 30 else text[:27] + "..."


def export_table(df, path, types=None, date_format=None, tz="wall", text=None, declared=None, drop=None,
                 dry_run=False, notes=None, problems=None):
    """Coerce, write, read back and verify. Returns the result dict the CLI prints; raises ExportRefused
    when columns cannot be typed and VerificationError when the read-back differs."""
    _require_spotfire()
    try:
        frame, plan, notes, col_problems = coerce_frame(df, types=types, date_format=date_format, tz=tz,
                                                        text=text, declared=declared, drop=drop, notes=notes)
    except ExportRefused as exc:
        raise ExportRefused(list(problems or []) + exc.problems, exc.notes)
    all_problems = list(problems or []) + list(col_problems)
    if all_problems:
        raise ExportRefused(all_problems, notes)
    planned = dict((p["name"], p["type"]) for p in plan)
    result = {"output": os.path.abspath(path) if path else None, "rows": int(len(frame)), "dry_run": bool(dry_run),
              "columns": [], "notes": notes, "warnings": [], "verified": False, "bytes": None}
    examples = {}
    back_types = planned
    if not dry_run:
        result["warnings"] = write_sbdf(frame, planned, path)
        back, back_types = read_back(path)
        check = verify(frame, planned, back, back_types)
        if check:
            try:
                os.remove(path)
            except OSError:
                pass
            raise VerificationError(check)
        result["verified"] = True
        result["bytes"] = os.path.getsize(path)
        for c in back.columns:
            present = back[c].dropna()
            examples[str(c)] = _example(present.iloc[0]) if len(present) else ""
    else:
        for c in frame.columns:
            present = frame[c].dropna()
            v = present.iloc[0] if len(present) else None
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            examples[c] = _example(v)
    for p in plan:
        result["columns"].append({"name": p["name"], "type": back_types.get(p["name"]) or p["type"],
                                  "source": p["source"], "missing": p["missing"],
                                  "example": examples.get(p["name"], "")})
    return result


def export_frame(df, path, types=None, *, date_format=None, tz="wall", text=None, drop=None):
    """Write a DataFrame to SBDF with exact Spotfire types and verify it by reading it back.

    types: {column: Spotfire type} or "Col=Type,...". date_format: "FMT" or {column: FMT} (None key = all
    text columns). text: None (respect dtypes), "csv" (object/str columns are raw text: infer numbers,
    booleans and dates) or "json" (infer ISO dates in string columns). Returns {column: Spotfire type} as
    read back. Raises ExportRefused (ValueError) listing the columns that cannot be typed."""
    if isinstance(date_format, dict):
        formats = date_format
    else:
        formats = parse_date_formats(date_format)
    res = export_table(df, path, types=types, date_format=formats, tz=tz, text=text, drop=drop)
    return dict((c["name"], c["type"]) for c in res["columns"])


# ------------------------------------------------------------------------------------------------ CLI
def _format_report(res, input_path, info):
    lines = []
    if res["dry_run"]:
        lines.append("sbdf_export: %s (dry run, nothing written)" % input_path)
    else:
        lines.append("sbdf_export: %s -> %s" % (input_path, res["output"]))
    lines.append("  %d rows, %d columns%s; %s" % (
        res["rows"], len(res["columns"]), (", %d bytes" % res["bytes"]) if res["bytes"] is not None else "",
        "read back with spotfire.sbdf.import_data: types, missing values and values match" if res["verified"]
        else "planned types (not written)"))
    lines.append("  input %s; python %s, pandas %s, numpy %s, spotfire %s" % (
        info.get("format", "DataFrame"), sys.version.split()[0], pd.__version__, np.__version__, _spotfire_version()))
    headers = ("column", "Spotfire type", "from", "missing", "example")
    rows = [(c["name"], c["type"], c["source"], str(c["missing"]), c["example"]) for c in res["columns"]]
    widths = [min(max([len(h)] + [len(r[i]) for r in rows]), cap) for i, (h, cap) in
              enumerate(zip(headers, (40, 13, 34, 7, 30)))]

    def cell(text, w, right=False):
        text = text if len(text) <= w else text[:w - 3] + "..."
        return text.rjust(w) if right else text.ljust(w)

    lines.append("")
    lines.append("  " + "  ".join(cell(h, widths[i], i == 3) for i, h in enumerate(headers)).rstrip())
    lines.append("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  " + "  ".join(cell(v, widths[i], i == 3) for i, v in enumerate(r)).rstrip())
    extra = list(res["notes"]) + ["writer warning: " + w for w in res["warnings"]]
    if extra:
        lines.append("")
        lines.append("notes:")
        for n in extra:
            lines.append("  - " + n)
    return "\n".join(lines) + "\n"


def _spotfire_version():
    try:
        from spotfire import version as _v
        return _v.__version__
    except Exception:  # pragma: no cover
        return "?"


def _configure_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _build_parser():
    p = argparse.ArgumentParser(
        prog="sbdf_export.py",
        description="Write CSV / Parquet / pickle / JSON data to SBDF with exact Spotfire column types, "
                    "verified by reading the file back. Run with Spotfire's bundled Python.",
        epilog="Spotfire types: " + ", ".join(SPOTFIRE_TYPES) + ". Exit codes: 0 written and verified, "
               "1 refused (columns that cannot be typed), 2 usage, input or verification error.")
    p.add_argument("input", help="input file: .csv .tsv .txt .tab .parquet .pq .pkl .pickle .json .jsonl .ndjson")
    p.add_argument("output", nargs="?", help="output .sbdf file (not needed with --dry-run)")
    p.add_argument("--types", action="append", default=[], metavar="'Col=Type,...'",
                   help="explicit Spotfire types per column (repeatable)")
    p.add_argument("--date-format", action="append", default=[], dest="date_format", metavar="FMT",
                   help="strptime format for text dates, e.g. '%%m/%%d/%%Y %%H:%%M'; 'Col=FMT' for one column; "
                        "also ISO8601 or mixed")
    p.add_argument("--tz", choices=("wall", "utc"), default="wall",
                   help="time-zone-aware values: keep wall-clock time (default) or convert to UTC")
    p.add_argument("--drop", action="append", default=[], metavar="COL[,COL]", help="columns to leave out")
    p.add_argument("--sep", help="delimited text: separator character (default: ',' / tab / detected)")
    p.add_argument("--encoding", help="delimited text: encoding (default: UTF-8, then cp1252, then latin-1)")
    p.add_argument("--dry-run", action="store_true", help="analyse and print the planned types; write nothing")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    return p


def main(argv=None):
    _configure_stdout()
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = sys.stdout
    status = {"status": "error", "input": args.input, "output": args.output}

    def emit_error(code, message, problems=None, notes=None):
        if args.json:
            status.update({"status": "refused" if code == 1 else "error", "error": message,
                           "problems": problems or [], "notes": notes or []})
            out.write(json.dumps(status, indent=2) + "\n")
        else:
            sys.stderr.write("sbdf_export: %s\n" % message)
            for p in problems or []:
                sys.stderr.write("  - %s\n" % p)
            if notes:
                sys.stderr.write("notes:\n")
                for n in notes:
                    sys.stderr.write("  - %s\n" % n)
        return code

    if _IMPORT_ERROR is not None:
        return emit_error(2, "this Python lacks pandas/numpy/spotfire (%s). Run sbdf_export.py with Spotfire's "
                             "bundled Python: %s" % (_IMPORT_ERROR, _find_spotfire_python() or
                                                     "<Spotfire>\\Modules\\Python Interpreter_*\\python\\python.exe"))
    if not args.dry_run and not args.output:
        return emit_error(2, "give the output .sbdf path (or --dry-run)")
    if args.output and not args.output.lower().endswith(".sbdf"):
        return emit_error(2, "the output file should end in .sbdf: %s" % args.output)
    try:
        types = parse_types(args.types)
        formats = parse_date_formats(args.date_format)
        df, info = read_input(args.input, sep=args.sep, encoding=args.encoding)
        res = export_table(df, args.output, types=types, date_format=formats, tz=args.tz, text=info["text"],
                           declared=info["declared"], drop=args.drop, dry_run=args.dry_run, notes=info["notes"],
                           problems=info["problems"])
    except UsageError as exc:
        return emit_error(2, str(exc))
    except ExportRefused as exc:
        return emit_error(1, "refused - nothing written. Fix these columns (or name them in --types):",
                          exc.problems, exc.notes)
    except VerificationError as exc:
        return emit_error(2, "the SBDF read back differs from what was written (file removed)", exc.problems)
    except Exception as exc:  # pragma: no cover - unexpected
        return emit_error(2, "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    if args.json:
        res.update({"status": "ok", "input": os.path.abspath(args.input), "format": info["format"],
                    "python": sys.version.split()[0], "pandas": pd.__version__, "spotfire": _spotfire_version()})
        out.write(json.dumps(res, indent=2) + "\n")
    else:
        out.write(_format_report(res, args.input, info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
