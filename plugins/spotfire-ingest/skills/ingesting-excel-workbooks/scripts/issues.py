"""Stage 3: scan a workbook for calculation issues and rate their severity.

Finds hardcoded constants in formulas (and constants that repeat an input value),
broken fill-down or fill-right patterns, values typed over formulas, error values,
broken references, circular references, OFFSET, INDIRECT and other volatile
functions, approximate lookups on unsorted data, IFERROR wrappers that hide
errors, calculations nothing uses, mixed units, template copies that differ,
external links, hidden sheets, manual calculation mode, VBA functions and macros.

Every issue carries a question for the workbook owner. The scan reports; it never
changes the workbook.

Usage:
    python issues.py <workbook.xlsx> --out <ingest folder>

Writes issues.json and issues.csv. Standard library only.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import xlsxlib as X
import structure as S

SEVERITY = ("high", "medium", "low", "info")

STRUCTURAL_ARGS = {
    "VLOOKUP": {2, 3}, "HLOOKUP": {2, 3}, "INDEX": {1, 2, 3}, "MATCH": {2},
    "XLOOKUP": {4, 5}, "XMATCH": {2, 3}, "ROUND": {1}, "ROUNDUP": {1}, "ROUNDDOWN": {1},
    "MROUND": {1}, "TRUNC": {1}, "OFFSET": {1, 2, 3, 4}, "LEFT": {1}, "RIGHT": {1},
    "MID": {1, 2}, "LARGE": {1}, "SMALL": {1}, "CHOOSE": {0}, "WEEKDAY": {1},
    "WEEKNUM": {1}, "TEXT": {1}, "SUBTOTAL": {0}, "AGGREGATE": {0, 1}, "FIXED": {1},
    "DATE": {0, 1, 2}, "TIME": {0, 1, 2}, "RANK": {2}, "PERCENTILE": {1},
    "QUARTILE": {1}, "CEILING": {1}, "FLOOR": {1}, "SEQUENCE": {0, 1, 2, 3},
    "IF": set(), "EDATE": set(), "EOMONTH": {1},
}

# Common conversion factors and engineering constants, with what they usually mean.
KNOWN_FACTORS = [
    (5.615, "cubic feet per barrel"), (5.6146, "cubic feet per barrel"),
    (86400, "seconds per day"), (3600, "seconds per hour"), (1440, "minutes per day"),
    (144, "square inches per square foot"), (32.174, "gravitational acceleration (ft/s2)"),
    (32.2, "gravitational acceleration (ft/s2)"), (9.81, "gravitational acceleration (m/s2)"),
    (9.80665, "gravitational acceleration (m/s2)"), (6.894757, "kPa per psi"),
    (6.895, "kPa per psi"), (14.696, "atmospheric pressure (psi)"), (14.7, "atmospheric "
    "pressure (psi)"), (101.325, "atmospheric pressure (kPa)"), (0.433, "fresh water "
    "gradient (psi/ft)"), (2.31, "feet of water per psi"), (1488, "unit factor of the "
    "Reynolds number in field units"), (30.4375, "average days per month"),
    (30.42, "average days per month"), (365, "days per year"), (365.25, "days per year"),
    (12, "months per year or inches per foot"), (24, "hours per day"), (60, "minutes or "
    "seconds"), (1000, "thousand"), (1e6, "million"), (0.001, "thousandth"), (42, "gallons "
    "per barrel"), (7.48052, "gallons per cubic foot"), (6.2898, "barrels per cubic meter"),
    (0.158987, "cubic meters per barrel"), (35.3147, "cubic feet per cubic meter"),
    (3.28084, "feet per meter"), (0.3048, "meters per foot"), (2.54, "centimeters per inch"),
    (25.4, "millimeters per inch"), (459.67, "Fahrenheit to Rankine offset"),
    (273.15, "Celsius to Kelvin offset"), (1.8, "Celsius to Fahrenheit factor"),
    (32, "Fahrenheit offset"), (0.0283168, "cubic meters per cubic foot"),
    (2.20462, "pounds per kilogram"), (0.453592, "kilograms per pound"),
    (10.7316, "gas constant (psia ft3 / lbmol R)"), (8.314, "gas constant (J / mol K)"),
    (62.4, "density of water (lb/ft3)"), (100, "percent"),
]

LOOKUP_SORTED = {"VLOOKUP", "HLOOKUP", "MATCH", "LOOKUP", "XLOOKUP", "XMATCH"}
ERROR_WRAPPERS = {"IFERROR", "IFNA", "ISERROR", "ISERR", "ISNA"}
VOLATILE = {"NOW": "the current date and time", "TODAY": "the current date",
            "RAND": "a random number", "RANDBETWEEN": "a random number",
            "RANDARRAY": "random numbers"}

EXCEL_FUNCTIONS = set("""
ABS ACCRINT ACCRINTM ACOS ACOSH ACOT ACOTH ADDRESS AGGREGATE AMORDEGRC AMORLINC AND ARABIC
AREAS ARRAYTOTEXT ASC ASIN ASINH ATAN ATAN2 ATANH AVEDEV AVERAGE AVERAGEA AVERAGEIF
AVERAGEIFS BAHTTEXT BASE BESSELI BESSELJ BESSELK BESSELY BETADIST BETA.DIST BETAINV
BETA.INV BIN2DEC BIN2HEX BIN2OCT BINOMDIST BINOM.DIST BINOM.DIST.RANGE BINOM.INV BITAND
BITLSHIFT BITOR BITRSHIFT BITXOR BYCOL BYROW CALL CEILING CEILING.MATH CEILING.PRECISE CELL
CHAR CHIDIST CHIINV CHITEST CHISQ.DIST CHISQ.DIST.RT CHISQ.INV CHISQ.INV.RT CHISQ.TEST
CHOOSE CHOOSECOLS CHOOSEROWS CLEAN CODE COLUMN COLUMNS COMBIN COMBINA COMPLEX CONCAT
CONCATENATE CONFIDENCE CONFIDENCE.NORM CONFIDENCE.T CONVERT CORREL COS COSH COT COTH COUNT
COUNTA COUNTBLANK COUNTIF COUNTIFS COUPDAYBS COUPDAYS COUPDAYSNC COUPNCD COUPNUM COUPPCD
COVAR COVARIANCE.P COVARIANCE.S CRITBINOM CSC CSCH CUBEKPIMEMBER CUBEMEMBER
CUBEMEMBERPROPERTY CUBERANKEDMEMBER CUBESET CUBESETCOUNT CUBEVALUE CUMIPMT CUMPRINC DATE
DATEDIF DATEVALUE DAVERAGE DAY DAYS DAYS360 DB DBCS DCOUNT DCOUNTA DDB DEC2BIN DEC2HEX
DEC2OCT DECIMAL DEGREES DELTA DEVSQ DGET DISC DMAX DMIN DOLLAR DOLLARDE DOLLARFR DPRODUCT
DROP DSTDEV DSTDEVP DSUM DURATION DVAR DVARP EDATE EFFECT ENCODEURL EOMONTH ERF ERF.PRECISE
ERFC ERFC.PRECISE ERROR.TYPE EUROCONVERT EVEN EXACT EXP EXPAND EXPON.DIST EXPONDIST FACT
FACTDOUBLE FALSE FDIST F.DIST F.DIST.RT FILTER FILTERXML FIND FINDB FINV F.INV F.INV.RT
FISHER FISHERINV FIXED FLOOR FLOOR.MATH FLOOR.PRECISE FORECAST FORECAST.ETS
FORECAST.ETS.CONFINT FORECAST.ETS.SEASONALITY FORECAST.ETS.STAT FORECAST.LINEAR
FORMULATEXT FREQUENCY FTEST F.TEST FV FVSCHEDULE GAMMA GAMMADIST GAMMA.DIST GAMMAINV
GAMMA.INV GAMMALN GAMMALN.PRECISE GAUSS GCD GEOMEAN GESTEP GETPIVOTDATA GROUPBY GROWTH
HARMEAN HEX2BIN HEX2DEC HEX2OCT HLOOKUP HOUR HSTACK HYPERLINK HYPGEOMDIST HYPGEOM.DIST IF
IFERROR IFNA IFS IMABS IMAGE IMAGINARY IMARGUMENT IMCONJUGATE IMCOS IMCOSH IMCOT IMCSC
IMCSCH IMDIV IMEXP IMLN IMLOG10 IMLOG2 IMPOWER IMPRODUCT IMREAL IMSEC IMSECH IMSIN IMSINH
IMSQRT IMSUB IMSUM IMTAN INDEX INDIRECT INFO INT INTERCEPT INTRATE IPMT IRR ISBLANK ISERR
ISERROR ISEVEN ISFORMULA ISLOGICAL ISNA ISNONTEXT ISNUMBER ISODD ISOMITTED ISOWEEKNUM ISPMT
ISREF ISTEXT JIS KURT LAMBDA LARGE LCM LEFT LEFTB LEN LENB LET LINEST LN LOG LOG10 LOGEST
LOGINV LOGNORM.DIST LOGNORMDIST LOGNORM.INV LOOKUP LOWER MAKEARRAY MAP MATCH MAX MAXA MAXIFS
MDETERM MDURATION MEDIAN MID MIDB MIN MINA MINIFS MINUTE MINVERSE MIRR MMULT MOD MODE
MODE.MULT MODE.SNGL MONTH MROUND MULTINOMIAL MUNIT N NA NEGBINOMDIST NEGBINOM.DIST
NETWORKDAYS NETWORKDAYS.INTL NOMINAL NORMDIST NORM.DIST NORMINV NORM.INV NORMSDIST
NORM.S.DIST NORMSINV NORM.S.INV NOT NOW NPER NPV NUMBERVALUE OCT2BIN OCT2DEC OCT2HEX ODD
ODDFPRICE ODDFYIELD ODDLPRICE ODDLYIELD OFFSET OR PDURATION PEARSON PERCENTILE
PERCENTILE.EXC PERCENTILE.INC PERCENTOF PERCENTRANK PERCENTRANK.EXC PERCENTRANK.INC PERMUT
PERMUTATIONA PHI PHONETIC PI PIVOTBY PMT POISSON POISSON.DIST POWER PPMT PRICE PRICEDISC
PRICEMAT PROB PRODUCT PROPER PV QUARTILE QUARTILE.EXC QUARTILE.INC QUOTIENT RADIANS RAND
RANDARRAY RANDBETWEEN RANK RANK.AVG RANK.EQ RATE RECEIVED REDUCE REGEXEXTRACT REGEXREPLACE
REGEXTEST REGISTER.ID REPLACE REPLACEB REPT RIGHT RIGHTB ROMAN ROUND ROUNDDOWN ROUNDUP ROW
ROWS RRI RSQ RTD SCAN SEARCH SEARCHB SEC SECH SECOND SEQUENCE SERIESSUM SHEET SHEETS SIGN
SIN SINH SKEW SKEW.P SLN SLOPE SMALL SORT SORTBY SQRT SQRTPI STANDARDIZE STDEV STDEV.P
STDEV.S STDEVA STDEVP STDEVPA STEYX STOCKHISTORY SUBSTITUTE SUBTOTAL SUM SUMIF SUMIFS
SUMPRODUCT SUMSQ SUMX2MY2 SUMX2PY2 SUMXMY2 SWITCH SYD T TABLE TAKE TAN TANH TBILLEQ
TBILLPRICE TBILLYIELD TDIST T.DIST T.DIST.2T T.DIST.RT TEXT TEXTAFTER TEXTBEFORE TEXTJOIN
TEXTSPLIT TIME TIMEVALUE TINV T.INV T.INV.2T TOCOL TODAY TOROW TRANSPOSE TREND TRIM
TRIMMEAN TRIMRANGE TRUE TRUNC TTEST T.TEST TYPE UNICHAR UNICODE UNIQUE UPPER VALUE
VALUETOTEXT VAR VAR.P VAR.S VARA VARP VARPA VDB VLOOKUP VSTACK WEBSERVICE WEEKDAY WEEKNUM
WEIBULL WEIBULL.DIST WORKDAY WORKDAY.INTL WRAPCOLS WRAPROWS XIRR XLOOKUP XMATCH XNPV XOR
YEAR YEARFRAC YIELD YIELDDISC YIELDMAT Z.TEST ZTEST ANCHORARRAY SINGLE FIELDVALUE
""".split())

QUESTIONS = {
    "typed-over-formula": "Was this value typed on purpose (a manual override), or should the "
                          "cell follow the formula of its neighbours?",
    "broken-pattern": "Should this cell use the same formula as its neighbours?",
    "error-value": "Is this error expected (for example, an empty or placeholder row), and "
                   "what should the result be?",
    "broken-reference": "Which cell or range should this formula read?",
    "hardcoded-constant": "Where do these numbers come from, and may they become named "
                          "parameters?",
    "constant-equals-input": "Should the formula read the input cell instead of repeating "
                             "its value?",
    "circular-reference": "Is the circular calculation intended, and what convergence "
                          "tolerance is acceptable?",
    "volatile-reference": "Which cells does this formula need to read? Can a fixed "
                          "reference or a lookup replace it?",
    "volatile-function": "Which fixed value should the reconciliation use?",
    "approximate-lookup": "Should this lookup find the nearest lower value (range lookup) "
                          "or an exact match?",
    "approximate-lookup-sorted": "Is a range lookup intended here, and will new rows keep "
                                 "the table sorted?",
    "iferror-masks": "What should happen when the wrapped calculation fails?",
    "unused-calculation": "Is this calculation still used (read by a person, a chart or a "
                          "report), or can it be left out?",
    "mixed-units": "Which unit is intended for the result, and which operand needs a "
                   "conversion?",
    "template-drift": "Which version of the formula is correct for all copies?",
    "external-link": "Where does the linked file come from, and how often does it change?",
    "hidden-content": "Why is this content hidden, and is it still needed?",
    "manual-calculation": "Was the workbook fully recalculated before it was saved?",
    "vba-function": "What does this function compute? Please share the macro code.",
    "vba-macros": "What do the macros do, and which steps do users run by hand?",
    "npv-timing": "Do the cash flows occur at the end of each period?",
    "data-table": "Which input values does the sensitivity table need in the app?",
}


class IssueList:
    def __init__(self):
        self.items = []

    def add(self, kind, severity, sheet, rng, message, block=None, cells=None, evidence=None,
            question=None):
        self.items.append({
            "type": kind, "severity": severity, "sheet": sheet, "range": rng,
            "block": block, "cells": (cells or [])[:25], "cellCount": len(cells or []),
            "message": message, "evidence": evidence,
            "question": question or QUESTIONS.get(kind, "")})


def _where(sheet, rng):
    return f"{X.quote_sheet(sheet)}!{rng}"


def _factor_hint(value):
    for factor, meaning in KNOWN_FACTORS:
        if abs(value - factor) <= 1e-4 * max(1.0, abs(factor)):
            return meaning
    return None


def _fmt(value):
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def check_exceptions(st, out):
    for block in st.blocks:
        if block.kind != "formula" or not block.exceptions:
            continue
        sheet = st.wb.sheet(block.sheet)
        for r, c in block.exceptions:
            cell = sheet.get(r, c)
            ref = X.addr(r, c)
            regular = sheet.get(*block.first)
            if cell.formula is None:
                out.add("typed-over-formula", "high", block.sheet, ref,
                        f"{_where(block.sheet, ref)} holds the typed value {_fmt(cell.value)} "
                        f"inside {_where(block.sheet, block.range)}, where the other cells "
                        f"use ={regular.formula}.", block.id, [ref],
                        {"value": cell.value, "blockFormula": "=" + regular.formula,
                         "r1c1": block.key})
            else:
                out.add("broken-pattern", "high", block.sheet, ref,
                        f"{_where(block.sheet, ref)} uses ={cell.formula}, which differs from "
                        f"the pattern of {_where(block.sheet, block.range)} "
                        f"({block.key}).", block.id, [ref],
                        {"formula": "=" + cell.formula,
                         "r1c1": st.r1c1.get((block.sheet, r, c)), "blockR1C1": block.key})


def check_errors(st, out):
    per_block = defaultdict(list)
    for sheet in st.wb.sheets:
        for (r, c), cell in sheet.cells.items():
            if cell.vtype == "e":
                block = st.block_of.get((sheet.name, r, c))
                per_block[(sheet.name, block.id if block else None)].append((r, c, cell.value))
            if cell.formula and "#REF!" in cell.formula.upper():
                block = st.block_of.get((sheet.name, r, c))
                out.add("broken-reference", "high", sheet.name, X.addr(r, c),
                        f"{_where(sheet.name, X.addr(r, c))} refers to a deleted range "
                        f"(={cell.formula}).", block.id if block else None, [X.addr(r, c)])
    for (sheet_name, block_id), cells in per_block.items():
        refs = [X.addr(r, c) for r, c, _ in sorted(cells)]
        values = sorted({v for _, _, v in cells})
        out.add("error-value", "high", sheet_name, refs[0] if len(refs) == 1 else
                f"{refs[0]}:{refs[-1]}",
                f"{len(refs)} cell(s) on {sheet_name} hold {', '.join(values)} "
                f"({', '.join(refs[:8])}{' ...' if len(refs) > 8 else ''}).", block_id, refs)


def _sweep_cells(wb):
    """Input values of what-if data tables: they are test values, not inputs."""
    cells = set()
    for table in wb.data_tables:
        r1, c1, r2, c2 = X.parse_range(table["ref"])
        if table["inputsInRow"] or table["twoInputs"]:
            cells.update((table["sheet"], r1 - 1, c) for c in range(c1, c2 + 1))
        if not table["inputsInRow"] or table["twoInputs"]:
            cells.update((table["sheet"], r, c1 - 1) for r in range(r1, r2 + 1))
    return cells


def _input_values(st):
    values = []
    sweep = _sweep_cells(st.wb)
    for block in st.blocks:
        if block.kind == "number" and block.role in ("input", "parameter"):
            sheet = st.wb.sheet(block.sheet)
            for r, c in block.cells:
                cell = sheet.get(r, c)
                if cell.is_number and (block.sheet, r, c) not in sweep:
                    label = S.cell_label(st, block.sheet, r, c)
                    values.append((cell.value, _where(block.sheet, X.addr(r, c)), label))
    return values


def check_constants(st, out):
    inputs = _input_values(st)
    exceptions = {(b.sheet, r, c) for b in st.blocks for r, c in b.exceptions}
    for block in st.blocks:
        if block.kind != "formula" or block.key.startswith("{="):
            continue
        if all((block.sheet, r, c) in exceptions for r, c in block.cells):
            continue
        sheet = st.wb.sheet(block.sheet)
        first = sheet.get(*block.first)
        tokens = X.tokenize(first.formula)
        ctx = S.arg_context(tokens)
        found, repeats = [], []
        prev = None
        for i, tok in enumerate(tokens):
            if tok.kind == "ws":
                continue
            if tok.kind == "num":
                value = tok.value
                where = ctx[i]
                skip = value in (0.0, 1.0, 2.0) or (prev is not None and prev.text == "^"
                                                    and value in (0.5, 3.0))
                if where and where[0] in STRUCTURAL_ARGS and where[1] in STRUCTURAL_ARGS[
                        where[0]]:
                    skip = True
                if not skip:
                    hint = _factor_hint(value)
                    found.append((tok.text, hint))
                    small_int = float(value).is_integer() and abs(value) <= 12
                    if not small_int and value not in (0.5, 100.0):
                        for ivalue, iref, ilabel in inputs:
                            if abs(ivalue - value) <= 1e-9 * max(1.0, abs(value)):
                                repeats.append((tok.text, iref, ilabel))
                                break
            prev = tok
        if found:
            listed = ", ".join(f"{text} ({hint})" if hint else text for text, hint in found)
            out.add("hardcoded-constant", "low", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} (={first.formula}) contains the "
                    f"constants {listed}.", block.id, [X.addr(r, c) for r, c in block.cells],
                    {"constants": [t for t, _ in found], "formula": "=" + first.formula})
        for text, iref, ilabel in repeats:
            out.add("constant-equals-input", "medium", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} uses the constant {text}, which is "
                    f"the value of the input {iref}"
                    f"{' (' + ilabel + ')' if ilabel else ''}. The formula does not change "
                    "when the input changes.", block.id,
                    [X.addr(r, c) for r, c in block.cells],
                    {"constant": text, "input": iref, "formula": "=" + first.formula})


def check_dynamic(st, out):
    for block in st.blocks:
        if block.kind != "formula":
            continue
        cells = [X.addr(r, c) for r, c in block.cells]
        for name in ("OFFSET", "INDIRECT"):
            if name in block.functions:
                notes = sorted(n for n in block.dynamic if n.startswith(name))
                out.add("volatile-reference", "medium", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} uses {name}, so the cells it "
                        "reads are chosen at calculation time and the dependency graph may "
                        f"be incomplete. {'; '.join(notes[:3])}".strip(), block.id, cells,
                        {"function": name, "notes": notes[:10]})
        for name, what in VOLATILE.items():
            if name in block.functions:
                out.add("volatile-function", "medium", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} uses {name}() ({what}); its "
                        "result changes on every recalculation.", block.id, cells)


def _lookup_mode(func, args):
    """Return 'approx', 'exact', 'binary', 'unknown-type' for a lookup call."""
    def literal(arg):
        if len(arg) == 1 and arg[0].kind in ("num", "bool"):
            return float(arg[0].value)
        if len(arg) == 2 and arg[0].text == "-" and arg[1].kind == "num":
            return -arg[1].value
        return None
    if func in ("VLOOKUP", "HLOOKUP"):
        if len(args) < 4 or not args[3]:
            return "approx"
        value = literal(args[3])
        if value is None:
            return "unknown-type"
        return "exact" if value == 0 else "approx"
    if func == "MATCH":
        if len(args) < 3 or not args[2]:
            return "approx"
        value = literal(args[2])
        if value is None:
            return "unknown-type"
        return "exact" if value == 0 else ("desc" if value < 0 else "approx")
    if func == "LOOKUP":
        return "approx"
    if func == "XLOOKUP" and len(args) >= 6 and literal(args[5]) in (2.0, -2.0):
        return "binary"
    if func == "XMATCH" and len(args) >= 4 and literal(args[3]) in (2.0, -2.0):
        return "binary"
    return "exact"


def _range_of(st, sheet, arg):
    if len(arg) != 1:
        return None
    tok = arg[0]
    if tok.kind == "ref" and tok.area.upper() != "#REF!":
        name, book = X.sheet_of(tok.sheet)
        if book:
            return None
        return (name or sheet.name,) + X.parse_range(tok.area)
    if tok.kind == "name":
        item = st.wb.find_name(tok.text, sheet.index)
        refs = X.defined_name_ranges(st.wb, item) if item else []
        if len(refs) == 1 and not refs[0].book and refs[0].kind != "error":
            ref = refs[0]
            return (ref.sheet or sheet.name, ref.r1, ref.c1, ref.r2, ref.c2)
    return None


def _sort_key(value):
    if isinstance(value, bool):
        return (2, value)
    if isinstance(value, float):
        return (0, value)
    return (1, str(value).lower())


def check_lookups(st, out):
    seen = set()
    for block in st.blocks:
        if block.kind != "formula" or not (block.functions & LOOKUP_SORTED):
            continue
        sheet = st.wb.sheet(block.sheet)
        first = sheet.get(*block.first)
        tokens = X.tokenize(first.formula)
        for i, tok in enumerate(tokens):
            if tok.kind != "func" or tok.value not in LOOKUP_SORTED:
                continue
            args = X.function_args(tokens, i)
            mode = _lookup_mode(tok.value, args)
            if mode == "exact" or len(args) < 2:
                continue
            bounds = _range_of(st, sheet, args[1])
            cells = [X.addr(r, c) for r, c in block.cells]
            if mode == "unknown-type":
                out.add("approximate-lookup", "medium", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} uses {tok.value} with a match "
                        "type read from a cell, so it may be a range lookup.", block.id, cells)
                continue
            if bounds is None:
                continue
            key = (block.id, tok.value, bounds)
            if key in seen:
                continue
            seen.add(key)
            tsheet = st.wb.sheet(bounds[0])
            r1, c1, r2, c2 = bounds[1:]
            if tok.value == "VLOOKUP" or (tok.value == "LOOKUP" and r2 - r1 >= c2 - c1):
                keys = [(r, c1) for r in range(r1, min(r2, r1 + 100000) + 1)]
            elif tok.value == "HLOOKUP" or tok.value == "LOOKUP":
                keys = [(r1, c) for c in range(c1, c2 + 1)]
            elif r2 - r1 >= c2 - c1:
                keys = [(r, c1) for r in range(r1, min(r2, r1 + 100000) + 1)]
            else:
                keys = [(r1, c) for c in range(c1, c2 + 1)]
            values = [(pos, tsheet.value(*pos)) for pos in keys if tsheet is not None]
            values = [(pos, v) for pos, v in values if v is not None and not (
                isinstance(v, str) and v.startswith("#"))]
            descending = mode == "desc"
            broken = None
            for (pa, va), (pb, vb) in zip(values, values[1:]):
                ka, kb = _sort_key(va), _sort_key(vb)
                if (kb < ka) if not descending else (kb > ka):
                    broken = (pa, va, pb, vb)
                    break
            rng = _where(bounds[0], X.range_text(*bounds[1:]))
            if broken:
                pa, va, pb, vb = broken
                out.add("approximate-lookup", "high", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} uses {tok.value} as a range "
                        f"lookup on {rng}, which is not sorted "
                        f"({X.addr(*pa)} = {_fmt(va)} comes before {X.addr(*pb)} = "
                        f"{_fmt(vb)}). Excel can return a wrong row without an error.",
                        block.id, cells, {"function": tok.value, "range": rng,
                                          "formula": "=" + first.formula})
            else:
                out.add("approximate-lookup-sorted", "info", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} uses {tok.value} as a range "
                        f"lookup on {rng} (sorted today).", block.id, cells,
                        {"function": tok.value, "range": rng})


def check_iferror(st, out):
    for block in st.blocks:
        wrappers = block.functions & ERROR_WRAPPERS
        if block.kind != "formula" or not wrappers:
            continue
        sheet = st.wb.sheet(block.sheet)
        hidden = []
        for r, c in block.cells:
            for p in S.precedent_cells(st, (block.sheet, r, c)):
                psheet = st.wb.sheet(p[0])
                pcell = psheet.get(p[1], p[2]) if psheet else None
                if pcell is not None and pcell.vtype == "e":
                    hidden.append((X.addr(r, c), _where(p[0], X.addr(p[1], p[2])), pcell.value))
        first = sheet.get(*block.first)
        cells = [X.addr(r, c) for r, c in block.cells]
        names = "/".join(sorted(wrappers))
        if hidden:
            cell, src, value = hidden[0]
            out.add("iferror-masks", "high", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} (={first.formula}) uses {names}; "
                    f"it hides an error now: {src} holds {value}, and the stored result is "
                    f"{_fmt(sheet.value(*block.first))}.", block.id, cells,
                    {"hidden": [{"cell": h[0], "source": h[1], "value": h[2]}
                                for h in hidden[:10]]})
        else:
            out.add("iferror-masks", "low", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} uses {names}, which turns errors "
                    "into a fallback value. The port reports such errors instead.",
                    block.id, cells)


def check_circular(st, out):
    groups = defaultdict(list)
    for comp in st.cycles:
        key = tuple(sorted({st.block_of[k].id for k in comp if k in st.block_of}))
        groups[key].append(comp)
    iterate = st.wb.calc.get("iterate") in ("1", "true")
    for key, comps in groups.items():
        cells = sorted({k for comp in comps for k in comp})
        sheet = cells[0][0]
        refs = [_where(s, X.addr(r, c)) for s, r, c in cells]
        state = ("Iterative calculation is on, so Excel stops after "
                 f"{st.wb.calc.get('iterateCount', '100')} iterations or a change below "
                 f"{st.wb.calc.get('iterateDelta', '0.001')}." if iterate else
                 "Iterative calculation is off, so the stored values may not be converged.")
        out.add("circular-reference", "high", sheet, refs[0].split("!")[-1],
                f"{len(comps)} circular reference group(s) through blocks {', '.join(key)} "
                f"({len(cells)} cells, for example {', '.join(refs[:5])}). {state}",
                key[0] if key else None, [r.split("!")[-1] for r in refs],
                {"blocks": list(key), "iterate": iterate})


def check_unused(st, out):
    for block in st.blocks:
        if block.kind == "formula" and block.role == "terminal":
            sheet = st.wb.sheet(block.sheet)
            where = "on a hidden sheet " if sheet.state != "visible" else ""
            out.add("unused-calculation", "low", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} ({block.label or 'no label'}) is a "
                    f"calculation {where}that no formula, chart or name reads.",
                    block.id, [X.addr(r, c) for r, c in block.cells])


def _operand_unit(st, sheet, tok):
    if tok.kind == "ref" and ":" not in tok.area and tok.area.upper() != "#REF!":
        name, book = X.sheet_of(tok.sheet)
        if book:
            return None, None
        r, c, _, _ = X.parse_cell(tok.area.replace("$", ""))
        target = name or sheet.name
        return S.cell_unit(st, target, r, c), _where(target, X.addr(r, c))
    if tok.kind == "name":
        item = st.wb.find_name(tok.text, sheet.index)
        refs = X.defined_name_ranges(st.wb, item) if item else []
        if len(refs) == 1 and refs[0].size == 1 and not refs[0].book:
            ref = refs[0]
            return S.cell_unit(st, ref.sheet, ref.r1, ref.c1), tok.text
    return None, None


def _norm_unit(unit):
    return re.sub(r"\s+", "", unit.lower()) if unit else None


def check_units(st, out):
    for block in st.blocks:
        if block.kind != "formula" or block.key.startswith("{="):
            continue
        sheet = st.wb.sheet(block.sheet)
        first = sheet.get(*block.first)
        tokens = [t for t in X.tokenize(first.formula) if t.kind != "ws"]
        for i in range(1, len(tokens) - 1):
            op = tokens[i]
            if op.kind != "op" or op.text not in "+-":
                continue
            left, right = tokens[i - 1], tokens[i + 1]
            if left.kind not in ("ref", "name") or right.kind not in ("ref", "name"):
                continue
            before = tokens[i - 2] if i >= 2 else None
            after = tokens[i + 2] if i + 2 < len(tokens) else None
            if before is not None and before.kind == "op" and before.text in "*/^":
                continue
            if after is not None and ((after.kind == "op" and after.text in "*/^%") or
                                      after.kind == "open"):
                continue
            lu, lref = _operand_unit(st, sheet, left)
            ru, rref = _operand_unit(st, sheet, right)
            if lu and ru and _norm_unit(lu) != _norm_unit(ru):
                out.add("mixed-units", "high", block.sheet, block.range,
                        f"{_where(block.sheet, block.range)} (={first.formula}) "
                        f"{'adds' if op.text == '+' else 'subtracts'} {lref} ({lu}) and "
                        f"{rref} ({ru}).", block.id, [X.addr(r, c) for r, c in block.cells],
                        {"left": [lref, lu], "right": [rref, ru], "result": block.unit})
                break


def check_templates(st, out, reported):
    for family in st.families:
        for item in family["drift"]:
            key = (item["sheet"], item["range"])
            if item["what"] == "value instead of formula" and key in reported:
                continue
            out.add("template-drift", "high", item["sheet"], item["range"],
                    f"{', '.join(family['sheets'])} are copies of one template. "
                    f"{_where(item['sheet'], item['range'])} differs from the other copies: "
                    + (f"it uses {item['r1c1']} where the others use {item['majority']}."
                       if item["what"] == "formula differs" else
                       f"it holds typed values where the others use {item['majority']}."),
                    None, [item["range"]], {"family": family["sheets"], **item})


def check_external(st, out):
    links = {link["index"]: link for link in st.wb.external_links}
    for block in st.blocks:
        if block.external:
            targets = ", ".join(f"[{i}] {links.get(i, {}).get('target', 'unknown file')}"
                                for i in sorted(block.external))
            out.add("external-link", "medium", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} reads another workbook ({targets}). "
                    "The stored value is used; links are not updated.", block.id,
                    [X.addr(r, c) for r, c in block.cells])


def check_hidden(st, out):
    for sheet in st.wb.sheets:
        formulas = sum(1 for c in sheet.cells.values() if c.formula is not None)
        if sheet.state != "visible" and sheet.cells:
            out.add("hidden-content", "medium" if sheet.state == "veryHidden" else "low",
                    sheet.name, "A1",
                    f"Sheet {sheet.name} is {sheet.state} and holds {len(sheet.cells)} cells "
                    f"({formulas} formulas).", None, [])
        rows = sorted({r for (r, c), cell in sheet.cells.items()
                       if cell.formula is not None and r in sheet.hidden_rows})
        cols = sorted({c for (r, c), cell in sheet.cells.items()
                       if cell.formula is not None and c in sheet.hidden_cols})
        if rows or cols:
            parts = []
            if rows:
                parts.append(f"hidden rows {', '.join(map(str, rows[:10]))}")
            if cols:
                parts.append(f"hidden columns {', '.join(X.num_to_col(c) for c in cols[:10])}")
            out.add("hidden-content", "low", sheet.name, "A1",
                    f"Sheet {sheet.name} has formulas in {' and '.join(parts)}.", None, [])


def check_workbook(st, out):
    wb = st.wb
    if wb.calc.get("calcMode") == "manual":
        out.add("manual-calculation", "high", wb.sheets[0].name, "A1",
                "The workbook was saved in manual calculation mode; stored values may be "
                "stale. Recalculate in Excel (F9) and save before reconciling.")
    lambdas = {n.name.upper() for n in wb.names}
    for block in st.blocks:
        unknown = sorted(f for f in block.functions if f not in EXCEL_FUNCTIONS and
                         f not in lambdas and not f.startswith("_XL"))
        if unknown and block.kind == "formula":
            out.add("vba-function", "medium", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} calls {', '.join(unknown)}, which is "
                    "not an Excel function (probably a VBA function).", block.id,
                    [X.addr(r, c) for r, c in block.cells], {"functions": unknown})
        if "NPV" in block.functions and block.kind == "formula":
            out.add("npv-timing", "info", block.sheet, block.range,
                    f"{_where(block.sheet, block.range)} uses NPV(), which discounts the first "
                    "value by one full period.", block.id,
                    [X.addr(r, c) for r, c in block.cells])
    for table in wb.data_tables:
        out.add("data-table", "info", table["sheet"], table["ref"],
                f"{_where(table['sheet'], table['ref'])} is a what-if data table "
                f"{table['formula']} that Excel recalculates for each input value.", None,
                [table["ref"]])
    if wb.vba or wb.macrosheets:
        what = "VBA macros" if wb.vba else "Excel 4 macro sheets"
        out.add("vba-macros", "medium", wb.sheets[0].name, "A1",
                f"The workbook contains {what}. They are not run; their effect on the "
                "stored values is unknown until the code is read.")


def scan(wb, st=None):
    st = st or S.analyze(wb)
    out = IssueList()
    check_exceptions(st, out)
    reported = {(i["sheet"], i["range"]) for i in out.items}
    check_errors(st, out)
    check_constants(st, out)
    check_dynamic(st, out)
    check_lookups(st, out)
    check_iferror(st, out)
    check_circular(st, out)
    check_unused(st, out)
    check_units(st, out)
    check_templates(st, out, reported)
    check_external(st, out)
    check_hidden(st, out)
    check_workbook(st, out)
    order = {s: i for i, s in enumerate(SEVERITY)}
    sheet_order = {s.name: s.index for s in wb.sheets}
    out.items.sort(key=lambda i: (order[i["severity"]], sheet_order.get(i["sheet"], 99),
                                  i["type"]))
    for n, item in enumerate(out.items, 1):
        item["id"] = f"I{n:02d}"
    return out.items, st


def write(items, wb, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITY}
    data = {"workbook": Path(wb.path).name, "counts": counts, "issues": items}
    (folder / "issues.json").write_text(json.dumps(data, indent=1, default=str),
                                        encoding="utf-8")
    with open(folder / "issues.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "severity", "type", "sheet", "range", "block", "message",
                         "question"])
        for i in items:
            writer.writerow([i["id"], i["severity"], i["type"], i["sheet"], i["range"],
                             i["block"] or "", i["message"], i["question"]])
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("workbook")
    parser.add_argument("--out", required=True, help="ingest folder for the results")
    args = parser.parse_args()
    wb = X.load(args.workbook)
    items, _ = scan(wb)
    counts = write(items, wb, args.out)
    print(f"{len(items)} issues ({', '.join(f'{v} {k}' for k, v in counts.items())}) -> "
          f"{Path(args.out) / 'issues.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
