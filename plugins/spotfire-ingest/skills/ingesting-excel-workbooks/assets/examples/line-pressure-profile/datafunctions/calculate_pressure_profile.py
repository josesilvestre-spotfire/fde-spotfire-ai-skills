"""Calculate Pressure Profile.

Calculation model of pipe_pressure_drop.xlsx: pressure drop per pipe segment.

The model reproduces the workbook as it is, including the behaviour listed in
change-list.md, so its outputs match the workbook's values. Each change in that
list goes in only after the owner approves it, followed by a new reconciliation.

Calculation IDs (L01 ...) refer to logic-spec.md.

The model code below is the code that was reconciled against the workbook's
values; the Excel behaviour functions it uses come first.
"""

# Excel behaviour functions used by the model
import datetime as _dt
import math
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, ROUND_UP, Decimal


HIDDEN_ERRORS = []


class ExcelError(Exception):
    """An Excel error value: '#DIV/0!', '#N/A', '#NUM!', '#VALUE!', '#REF!'."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code} {detail}".strip())
        self.code = code


def arith(value):
    """A value as Excel uses it in arithmetic: empty = 0, TRUE = 1, numeric text
    converted, other text = #VALUE!, an error stays an error."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return 0.0
        return float(value)
    if isinstance(value, str):
        if value.startswith("#"):
            raise ExcelError(value)
        try:
            return float(value.replace(",", ""))
        except ValueError:
            raise ExcelError("#VALUE!", repr(value))
    raise ExcelError("#VALUE!", repr(value))


def div(a, b):
    """a / b with Excel's #DIV/0! (empty b counts as 0)."""
    b = arith(b)
    if b == 0:
        raise ExcelError("#DIV/0!")
    return arith(a) / b


def log10(value):
    value = arith(value)
    if value <= 0:
        raise ExcelError("#NUM!", "LOG10 of a value <= 0")
    return math.log10(value)


def _numbers(values):
    """Numbers of a range for SUM, AVERAGE, MAX, MIN: empty cells, text and
    logical values in ranges are skipped; error values raise."""
    out = []
    for v in _flat(values):
        if isinstance(v, str) and v.startswith("#"):
            raise ExcelError(v)
        if isinstance(v, bool) or v is None or isinstance(v, str):
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        out.append(float(v))
    return out


def _flat(values):
    if isinstance(values, (list, tuple)):
        for v in values:
            yield from _flat(v)
    elif hasattr(values, "tolist"):
        yield from _flat(values.tolist())
    else:
        yield values


def xsum(*ranges):
    return float(math.fsum(_numbers(ranges)))


def average(*ranges):
    nums = _numbers(ranges)
    if not nums:
        raise ExcelError("#DIV/0!", "AVERAGE of no numbers")
    return math.fsum(nums) / len(nums)


def xmax(*ranges):
    nums = _numbers(ranges)
    return max(nums) if nums else 0.0


def iferror(compute, fallback, where=""):
    """IFERROR(compute(), fallback). Returns the fallback as Excel does, and
    records the hidden error in HIDDEN_ERRORS so the model can report it.
    compute is a function without arguments (lambda: div(a, b))."""
    try:
        return compute()
    except ExcelError as exc:
        HIDDEN_ERRORS.append({"where": where, "error": exc.code, "detail": str(exc)})
        return fallback
    except (ZeroDivisionError, ValueError, OverflowError) as exc:
        HIDDEN_ERRORS.append({"where": where, "error": "#NUM!", "detail": str(exc)})
        return fallback


def _key(value):
    """Excel's ordering: numbers < text < logical; text ignores case."""
    if isinstance(value, bool):
        return (2, value)
    if value is None:
        return (0, 0.0)
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (1, str(value).lower())


def eq(a, b):
    """Excel '=': text compares without regard to case; empty equals 0 and ''."""
    if a is None:
        a = "" if isinstance(b, str) else 0.0
    if b is None:
        b = "" if isinstance(a, str) else 0.0
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    return _key(a) == _key(b)


def _approx_index(value, keys, descending=False):
    """Binary search as a range lookup does: the last key <= value (ascending).
    On unsorted keys the answer can differ from Excel's; the issue scan flags
    such lookups."""
    target = _key(value)
    lo, hi, found = 0, len(keys) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        k = keys[mid]
        if k is None:
            lo = mid + 1
            continue
        km = _key(k)
        ok = km[0] == target[0] and (km >= target if descending else km <= target)
        if ok:
            found = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if found < 0:
        raise ExcelError("#N/A", f"no key <= {value!r}")
    return found


def _exact_index(value, keys):
    for i, k in enumerate(keys):
        if k is not None and eq(k, value):
            return i
    raise ExcelError("#N/A", f"{value!r} not found")


def vlookup(value, rows, col_index, approximate=True):
    """VLOOKUP over a list of rows. approximate=True is Excel's default when the
    fourth argument is left out."""
    rows = [list(r) for r in rows]
    keys = [r[0] if r else None for r in rows]
    i = _approx_index(value, keys) if approximate else _exact_index(value, keys)
    if not 1 <= col_index <= len(rows[i]):
        raise ExcelError("#REF!", "column index outside the table")
    return rows[i][int(col_index) - 1]


# Calculation model
import math
import sys
from pathlib import Path

import pandas as pd


try:
    HERE = Path(__file__).resolve().parent
except NameError:  # inside a Spotfire data function there is no file
    HERE = Path(".")

# Data function interface: Spotfire parameter name -> model key.
PARAMETERS = {"FlowRate": "Inputs!B3", "FluidDensity": "Inputs!B4", "Viscosity": "Inputs!B5",
              "PipeAge": "Inputs!B6", "InletPressure": "Inputs!B8"}
TABLE_PARAMETERS = {"SEGMENTS": "Segments!A2:D21", "ROUGHNESS_BY_AGE": "Lookups!A3:B7"}
SPOTFIRE_OUTPUTS = ["SEGMENT_RESULTS", "TotalPressureDrop", "OutletPressure", "MaxVelocity",
                    "AverageGradient"]

# Inputs with the workbook's stored values.
INPUTS = {
    "Inputs!B3": 12000.0,   # Flow rate (bbl/d)
    "Inputs!B4": 53.0,      # Fluid density (lb/ft3)
    "Inputs!B5": 4.5,       # Viscosity (cP)
    "Inputs!B6": 25.0,      # Pipe age (years)
    "Inputs!B8": 950.0,     # Inlet pressure (psi)
    "Calc!G14": 0.35,       # friction loss typed over the formula of segment 10 (C4)
}

TABLES = {"Segments!A2:D21": "../data/SEGMENTS.csv",
          "Lookups!A3:B7": "../data/ROUGHNESS_BY_AGE.csv"}

OUTPUTS = ["Velocity (ft/s)", "Friction Loss (psi)", "Segment Drop (psi)",
           "Outlet Pressure (psi)", "Pressure Gradient (psi/ft)", "Total Pressure Drop (psi)",
           "Outlet Pressure at Line End (psi)", "Maximum Velocity (ft/s)",
           "Average Gradient (psi/ft)"]

OVERRIDE_SEGMENT = 10      # Calc!G14 holds a typed value (change C4)
BROKEN_SEGMENT = 15        # Calc!F19 reads the diameter of segment 1 (change C2)


def run(inputs=None, tables=None):
    """Return {output name: value or {segment: value}}."""
    x = dict(INPUTS)
    x.update(inputs or {})
    t = tables if tables is not None else load_tables()
    segments = t["Segments!A2:D21"]
    lookup = t["Lookups!A3:B7"]
    flow, density, viscosity = x["Inputs!B3"], x["Inputs!B4"], x["Inputs!B5"]

    # L01 Roughness: range lookup on the age table as stored (change C1)
    roughness = vlookup(x["Inputs!B6"], lookup.values.tolist(), 2)

    first_diameter = float(segments["Inner Diameter (in)"].iloc[0])
    velocity, friction, drop, outlet, gradient = {}, {}, {}, {}, {}
    pressure = x["Inputs!B8"]
    for row in segments.itertuples(index=False):
        seg = int(row[0])
        length, diameter, elevation = float(row[1]), float(row[2]), float(row[3])
        # L02 Velocity (ft/s)
        v = flow * 5.615 / 86400 / (math.pi * (diameter / 12) ** 2 / 4)
        # L03 Reynolds number
        reynolds = 1488 * density * v * (diameter / 12) / viscosity
        # L04 Friction factor, Swamee-Jain
        d_f = first_diameter if seg == BROKEN_SEGMENT else diameter
        f = 0.25 / log10(roughness / (3.7 * d_f) + 5.74 / reynolds ** 0.9) ** 2
        # L05 Friction loss (psi)
        if seg == OVERRIDE_SEGMENT:
            g = x["Calc!G14"]
        else:
            g = f * (length / (diameter / 12)) * density * v ** 2 / (2 * 32.174) / 144
        # L06 Elevation loss, in kPa as in the workbook (change C3)
        h = density * elevation / 144 * 6.894757
        # L07 Segment drop
        d = g + h
        # L08 Outlet pressure, running from the inlet
        pressure = pressure - d
        # L09 Pressure gradient; a zero-length segment gives #DIV/0! (change C5)
        try:
            grad = div(d, length)
        except ExcelError as exc:
            grad = exc.code
        velocity[seg], friction[seg], drop[seg] = v, g, d
        outlet[seg], gradient[seg] = pressure, grad

    last = max(outlet)
    return {
        "Velocity (ft/s)": velocity,
        "Friction Loss (psi)": friction,
        "Segment Drop (psi)": drop,
        "Outlet Pressure (psi)": outlet,
        "Pressure Gradient (psi/ft)": gradient,
        "Total Pressure Drop (psi)": xsum(list(drop.values())),                  # L10
        "Outlet Pressure at Line End (psi)": outlet[last],                      # L08
        "Maximum Velocity (ft/s)": xmax(list(velocity.values())),               # L11
        "Average Gradient (psi/ft)": iferror(                                   # L12
            lambda: average(list(gradient.values())), 0.0, "Summary!B7"),
    }


def spotfire_outputs(result):
    """The data function outputs: one table per segment and four single values."""
    segs = sorted(result["Outlet Pressure (psi)"])
    numeric = [g if isinstance(g, float) else None
               for g in (result["Pressure Gradient (psi/ft)"][s] for s in segs)]
    table = pd.DataFrame({
        "Segment": [float(s) for s in segs],
        "Velocity (ft/s)": [result["Velocity (ft/s)"][s] for s in segs],
        "Friction Loss (psi)": [result["Friction Loss (psi)"][s] for s in segs],
        "Segment Drop (psi)": [result["Segment Drop (psi)"][s] for s in segs],
        "Outlet Pressure (psi)": [result["Outlet Pressure (psi)"][s] for s in segs],
        "Pressure Gradient (psi/ft)": pd.Series(numeric, dtype="float64"),
    })
    return {"SEGMENT_RESULTS": table,
            "TotalPressureDrop": result["Total Pressure Drop (psi)"],
            "OutletPressure": result["Outlet Pressure at Line End (psi)"],
            "MaxVelocity": result["Maximum Velocity (ft/s)"],
            "AverageGradient": result["Average Gradient (psi/ft)"]}


def load_tables(folder=HERE):
    """Read the raw data and lookup tables of the app folder."""
    return {key: pd.read_csv(Path(folder) / path) for key, path in TABLES.items()}


def _rows(name, value):
    if isinstance(value, dict):
        return [(name, k, v) for k, v in value.items()]
    return [(name, 1, value)]


# Data function inputs and outputs
_inputs = {
    'Inputs!B3': FlowRate,
    'Inputs!B4': FluidDensity,
    'Inputs!B5': Viscosity,
    'Inputs!B6': PipeAge,
    'Inputs!B8': InletPressure,
}
_tables = {
    'Segments!A2:D21': SEGMENTS,
    'Lookups!A3:B7': ROUGHNESS_BY_AGE,
}
_outputs = spotfire_outputs(run(_inputs, _tables))
SEGMENT_RESULTS = _outputs['SEGMENT_RESULTS']
TotalPressureDrop = _outputs['TotalPressureDrop']
OutletPressure = _outputs['OutletPressure']
MaxVelocity = _outputs['MaxVelocity']
AverageGradient = _outputs['AverageGradient']
