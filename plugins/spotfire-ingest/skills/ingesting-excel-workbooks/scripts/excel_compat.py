"""Excel behaviour for Python calculation models.

A Python port of a workbook must first reproduce the workbook's numbers. Plain
Python differs from Excel in several places; the functions below follow Excel:

- ROUND, ROUNDUP, ROUNDDOWN round on the 15-digit decimal value, half away from
  zero (Python's round() rounds half to even on the binary value).
- Serial dates use Excel's 1900 date system, including the day 1900-02-29 that
  Excel counts but that never existed (serial 60), or the 1904 system.
- Empty cells count as 0 in arithmetic; SUM, AVERAGE, MAX and MIN skip empty
  cells and text in ranges.
- VLOOKUP, HLOOKUP and MATCH default to an approximate (range) match.
- Results keep 15 significant digits.
- Errors (#DIV/0!, #N/A, #NUM!, #VALUE!) are raised as ExcelError. iferror()
  returns the fallback as Excel does, and records the hidden error in
  HIDDEN_ERRORS so the model reports it instead of hiding it.
- power() follows Excel for negative bases and 0^0; note that Excel evaluates
  =-2^2 as 4 (negation first), Python's -2**2 as -4.

Standard library only, so the functions can be pasted into a Spotfire data
function together with the model.
"""

import datetime as _dt
import math
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, ROUND_UP, Decimal

HIDDEN_ERRORS = []


class ExcelError(Exception):
    """An Excel error value: '#DIV/0!', '#N/A', '#NUM!', '#VALUE!', '#REF!'."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code} {detail}".strip())
        self.code = code


# -- numbers ------------------------------------------------------------------

def sig15(value):
    """Round to 15 significant digits, as Excel stores calculated results."""
    if value is None or not isinstance(value, float) or value == 0 or not math.isfinite(value):
        return value
    return float(f"{value:.15g}")


def _dec(value):
    return Decimal(f"{float(value):.15g}")


def _round(value, digits, mode):
    value = arith(value)
    digits = int(digits)
    quantum = Decimal(1).scaleb(-digits)
    return float(_dec(value).quantize(quantum, rounding=mode))


def xround(value, digits=0):
    """ROUND: half away from zero on the 15-digit value. xround(2.675, 2) = 2.68."""
    return _round(value, digits, ROUND_HALF_UP)


def roundup(value, digits=0):
    """ROUNDUP: away from zero."""
    return _round(value, digits, ROUND_UP)


def rounddown(value, digits=0):
    """ROUNDDOWN: toward zero."""
    return _round(value, digits, ROUND_DOWN)


def ceiling(value, significance=1.0):
    """CEILING with a positive significance."""
    if significance == 0:
        return 0.0
    q = _dec(arith(value)) / _dec(significance)
    return float(q.to_integral_value(rounding=ROUND_CEILING) * _dec(significance))


def floor(value, significance=1.0):
    """FLOOR with a positive significance."""
    if significance == 0:
        raise ExcelError("#DIV/0!", "FLOOR significance 0")
    q = _dec(arith(value)) / _dec(significance)
    return float(q.to_integral_value(rounding=ROUND_FLOOR) * _dec(significance))


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


def power(base, exponent):
    """base ^ exponent as Excel computes it (0^0 and a negative base with a
    fractional exponent give #NUM!; Python would return 1 or a complex number)."""
    base, exponent = arith(base), arith(exponent)
    if base == 0 and exponent == 0:
        raise ExcelError("#NUM!", "0^0")
    if base == 0 and exponent < 0:
        raise ExcelError("#DIV/0!")
    if base < 0 and not float(exponent).is_integer():
        raise ExcelError("#NUM!", "negative base with a fractional exponent")
    return math.pow(base, exponent)


def ln(value):
    value = arith(value)
    if value <= 0:
        raise ExcelError("#NUM!", "LN of a value <= 0")
    return math.log(value)


def log10(value):
    value = arith(value)
    if value <= 0:
        raise ExcelError("#NUM!", "LOG10 of a value <= 0")
    return math.log10(value)


def sqrt(value):
    value = arith(value)
    if value < 0:
        raise ExcelError("#NUM!", "SQRT of a negative value")
    return math.sqrt(value)


def xint(value):
    """INT rounds down (toward minus infinity): INT(-2.5) = -3."""
    return float(math.floor(arith(value)))


def trunc(value, digits=0):
    return rounddown(value, digits)


def mod(n, d):
    """MOD: the result has the sign of the divisor (as Python's %)."""
    d = arith(d)
    if d == 0:
        raise ExcelError("#DIV/0!")
    return arith(n) - d * math.floor(arith(n) / d)


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


def xmin(*ranges):
    nums = _numbers(ranges)
    return min(nums) if nums else 0.0


def count(*ranges):
    return float(len(_numbers(ranges)))


# -- errors -------------------------------------------------------------------

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


def ifna(compute, fallback, where=""):
    try:
        return compute()
    except ExcelError as exc:
        if exc.code != "#N/A":
            raise
        HIDDEN_ERRORS.append({"where": where, "error": exc.code, "detail": str(exc)})
        return fallback


# -- comparisons and lookups --------------------------------------------------

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


def match(value, keys, match_type=1):
    """MATCH, 1-based. match_type 1 (default) and -1 are range lookups."""
    keys = list(_flat(keys))
    if match_type == 0:
        return float(_exact_index(value, keys) + 1)
    return float(_approx_index(value, keys, descending=match_type < 0) + 1)


def vlookup(value, rows, col_index, approximate=True):
    """VLOOKUP over a list of rows. approximate=True is Excel's default when the
    fourth argument is left out."""
    rows = [list(r) for r in rows]
    keys = [r[0] if r else None for r in rows]
    i = _approx_index(value, keys) if approximate else _exact_index(value, keys)
    if not 1 <= col_index <= len(rows[i]):
        raise ExcelError("#REF!", "column index outside the table")
    return rows[i][int(col_index) - 1]


def hlookup(value, columns_rows, row_index, approximate=True):
    """HLOOKUP over a list of rows (the first row holds the keys)."""
    keys = list(columns_rows[0])
    i = _approx_index(value, keys) if approximate else _exact_index(value, keys)
    return columns_rows[int(row_index) - 1][i]


def xlookup(value, keys, results, if_not_found=None):
    """XLOOKUP with exact match (its default)."""
    try:
        return list(_flat(results))[_exact_index(value, list(_flat(keys)))]
    except ExcelError:
        if if_not_found is None:
            raise
        return if_not_found


# -- dates --------------------------------------------------------------------

_EPOCH_1900 = _dt.date(1899, 12, 30)
_EPOCH_1904 = _dt.date(1904, 1, 1)


def to_serial(day, date1904=False):
    """date or datetime -> Excel serial number. In the 1900 system Excel counts
    1900-02-29, so dates before 1900-03-01 are one lower than a plain count."""
    frac = 0.0
    if isinstance(day, _dt.datetime):
        frac = (day.hour * 3600 + day.minute * 60 + day.second +
                day.microsecond / 1e6) / 86400.0
        day = day.date()
    if date1904:
        return float((day - _EPOCH_1904).days) + frac
    serial = (day - _EPOCH_1900).days
    if day < _dt.date(1900, 3, 1):
        serial -= 1
    return float(serial) + frac


def from_serial(serial, date1904=False):
    """Excel serial number -> datetime. Serial 60 in the 1900 system is the day
    1900-02-29 that does not exist: ExcelError('#VALUE!')."""
    serial = arith(serial)
    days = math.floor(serial)
    frac = serial - days
    if date1904:
        base = _dt.datetime.combine(_EPOCH_1904, _dt.time())
    else:
        if days == 60:
            raise ExcelError("#VALUE!", "serial 60 is 1900-02-29, which does not exist")
        base = _dt.datetime(1899, 12, 31) if days < 60 else \
            _dt.datetime.combine(_EPOCH_1900, _dt.time())
    return base + _dt.timedelta(days=days, seconds=round(frac * 86400, 6))


def edate(serial, months, date1904=False):
    """EDATE: same day n months later (clipped to the month end)."""
    day = from_serial(serial, date1904).date()
    month = day.month - 1 + int(months)
    year = day.year + month // 12
    month = month % 12 + 1
    last = _month_end(year, month)
    return to_serial(_dt.date(year, month, min(day.day, last)), date1904)


def eomonth(serial, months, date1904=False):
    day = from_serial(serial, date1904).date()
    month = day.month - 1 + int(months)
    year = day.year + month // 12
    month = month % 12 + 1
    return to_serial(_dt.date(year, month, _month_end(year, month)), date1904)


def _month_end(year, month):
    if month == 12:
        return 31
    return (_dt.date(year, month + 1, 1) - _dt.timedelta(days=1)).day


def year(serial, date1904=False):
    return float(from_serial(serial, date1904).year)


def month(serial, date1904=False):
    return float(from_serial(serial, date1904).month)


def day(serial, date1904=False):
    return float(from_serial(serial, date1904).day)


# -- finance ------------------------------------------------------------------

def npv(rate, values):
    """NPV: the first value is discounted by one full period; empty cells and
    text are skipped."""
    nums = _numbers(values)
    return math.fsum(v / (1.0 + rate) ** (i + 1) for i, v in enumerate(nums))


def irr(values, guess=0.1):
    """IRR by Newton's method with a bisection fallback; #NUM! when no rate is
    found (Excel tries 20 iterations from the guess)."""
    flows = _numbers(values)
    if not any(v < 0 for v in flows) or not any(v > 0 for v in flows):
        raise ExcelError("#NUM!", "IRR needs a positive and a negative cash flow")

    def f(r):
        return math.fsum(v / (1.0 + r) ** i for i, v in enumerate(flows))

    def df(r):
        return math.fsum(-i * v / (1.0 + r) ** (i + 1) for i, v in enumerate(flows))
    r = guess
    for _ in range(100):
        d = df(r)
        if d == 0:
            break
        step = f(r) / d
        r -= step
        if r <= -1:
            break
        if abs(step) < 1e-12:
            return r
    lo, hi = -0.999999, 10.0
    if f(lo) * f(hi) > 0:
        raise ExcelError("#NUM!", "IRR did not converge")
    for _ in range(300):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def pmt(rate, nper, pv, fv=0.0, when=0):
    """PMT: payment per period (negative for a loan received)."""
    if rate == 0:
        return -(pv + fv) / nper
    factor = (1 + rate) ** nper
    return -(rate * (pv * factor + fv)) / ((1 + rate * when) * (factor - 1))


# -- text ---------------------------------------------------------------------

def text_general(value):
    """A number as Excel's General format shows it in text (A1&"" or CONCAT)."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{sig15(value):.15g}".replace("e+", "E+").replace("e-", "E-")
    return str(value)
