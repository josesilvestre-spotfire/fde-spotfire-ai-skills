# SBDF types: what Spotfire can write back

Spotfire runs a Python data function in its own interpreter and writes every output with the
`spotfire` package (`spotfire.sbdf.export_data`). An output the writer refuses is not created.
Everything below was run with the writer of Spotfire Analyst 15.0 (`spotfire` 2.4.2, Python
3.14.5) under both pandas 2.3.3 and pandas 3.0.5, unless a line says otherwise.

## Which pandas you get

Spotfire 15.0 bundles numpy 2.4.4 and pandas 2.3.3. Python puts the user site-packages folder
(`%APPDATA%\Python\Python314\site-packages` on Windows) ahead of the bundled packages on
`sys.path`. When that folder exists, for example because you installed packages for your own
Python 3.14, Spotfire's data functions import its pandas and numpy instead. On such a machine the
data functions run under pandas 3.

Check what a data function gets:

```bash
"$SPOTFIRE_PYTHON" -c "import pandas, numpy; print(pandas.__version__, numpy.__version__)"
"$SPOTFIRE_PYTHON" -s -c "import pandas; print(pandas.__version__)"   # -s: bundled only
```

Write every function so it runs under both. The rules in this file do.

## Dtype to Spotfire type (pandas 2.3.3, read back with `spotfire.get_spotfire_types`)

| pandas dtype or Python value | Spotfire type |
|---|---|
| `int64`, Python `int` | LongInteger |
| `int32`, `numpy.int32` | Integer |
| `Int64` (nullable) | LongInteger, `pd.NA` is missing |
| `Int32` (nullable) | Integer |
| `float64`, Python `float` | Real |
| `float32`, `numpy.float32` | SingleReal |
| `bool`, `boolean` (nullable) | Boolean |
| `object` holding `str` | String |
| `datetime64` | DateTime |
| `object` holding `datetime.date` | Date |
| `timedelta64` | TimeSpan |
| `object` holding `decimal.Decimal` | Currency |

All of these also export under pandas 3.0.5. Under pandas 3 the writer no longer records the
types in the frame it reads back, so check the column types in Spotfire's column properties the
first time.

## What fails, with the writer's message

| Output | pandas 2.3.3 | pandas 3.0.5 | Fix |
|---|---|---|---|
| text column with the default dtype (`"str"` under pandas 3) | ok (`object`) | `SBDFError: unknown dtype 'str' in column 'Name'` | `df[c] = df[c].astype(object)` |
| `object` column holding ints | ok (LongInteger) | `cannot convert '1' to Spotfire LongInteger type; incompatible types` | `pd.to_numeric(col, errors="coerce")` |
| `object` column holding floats and `None` | ok (Real) | `cannot convert '1.5' to Spotfire Real type; incompatible types` | `pd.to_numeric(col, errors="coerce").astype("float64")` |
| `object` column with mixed types (`1`, `"x"`) | `types in column 'N' do not match` | same | one type per column |
| `object` column where every value is missing | `cannot determine type for column 'T'; all values are missing` | same | a dtype: `float64`, `Int64`, or `pd.StringDtype("python")` for text |
| a scalar output that is `None` | `cannot determine type for value; all values are missing` | same | a typed value on every path |
| an output never assigned on this path | `DataFunctionError: Output variable 'X' was not defined` | same | assign every output on every path |

`pd.StringDtype("python")` exports under both versions and is the way to send an all-empty text
column. `pd.StringDtype("pyarrow")`, `category` and other extension dtypes were not tested: convert
them to `object` or a numeric dtype.

The pandas 3 text failure is easy to miss: Spotfire does not create the table, so a visual built
on it has nothing to show, and the writer's message is only in Spotfire's notifications. When an
output table is missing, check its text columns first.

## Rules that follow

1. Numeric columns go through `pd.to_numeric(col, errors="coerce")` and get a numeric dtype
   (`float64`, `int64` or `Int64`) before the output staging ends.
2. Text columns end as `object` (`.astype(object)`). An all-empty text column is
   `pd.StringDtype("python")`.
3. Missing numbers are `np.nan` or `pd.NA`, never `None` inside a numeric column.
4. Integer columns with missing values use the nullable `Int64`. It exports as LongInteger with
   `pd.NA` as missing. `fillna(0)` turns a missing value into a real zero: use it only where zero
   is the true value.
5. Scalar outputs are native Python values, cast at the staging boundary: `int(float(x))` for
   integers, `float(x)`, `str(x)`, `bool(x)`. Cast on every path, including pass-through branches.
6. A document property keeps the type it was created with. A Python `int` is LongInteger and a
   `float` is Real, so create integer output properties as LongInteger (or return
   `numpy.int32` for an Integer property).
7. A formatted KPI value (`"61.8"`, `"1,284"`) is a String output bound to a String property, and
   the text area shows it through a label control.

## Inputs

- A registered input that is not bound arrives as `None`, not as a missing name. Default on both
  (`NameError` and `None`).
- A Table input arrives as a DataFrame, a Column input as a Series, a Value input as a Python
  scalar.
- Integer input columns arrive as nullable `Int32` or `Int64`. Engine code must tolerate `pd.NA`.
- Spotfire runs the script with `exec()` and globals that hold only the inputs and
  `__builtins__` (spotfire 2.4.2 source), so `__name__` is not `"__main__"` and an
  `if __name__ == "__main__":` smoke test never runs inside Spotfire.

## Check a function before you register it

```bash
python scripts/check_sbdf_outputs.py my_function.py              # static checks
"$SPOTFIRE_PYTHON" scripts/check_sbdf_outputs.py my_function.py  # plus Spotfire's own writer
"$SPOTFIRE_PYTHON" -s scripts/check_sbdf_outputs.py my_function.py --set MinPoints=500
```

With Spotfire's Python the checker also exports every output with the SBDF writer and runs the
function through `spotfire.data_function.AnalyticSpec`, the runner Spotfire's Python service
uses. Run it with and without `-s` when the machine has a user site-packages folder, so both
pandas versions are covered, and use `--set` and `--input` to reach the other branches
(pass-through, empty input).
