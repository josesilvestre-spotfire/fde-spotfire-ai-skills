"""Compare calculated outputs with the workbook's values, output by output.

Two commands:

  extract   read the expected values from the workbook (its stored results) for
            every output in output-map.json and write them as a long CSV
            (case, output, index, value)

      python reconcile.py extract --workbook book.xlsx --map output-map.json
          --out expected.csv [--case stored]

  compare   compare a table of actual values with the expected CSV within the
            tolerances of the Logic Spec, and write a report

      python reconcile.py compare --expected expected.csv --actual actual.csv
          [--map output-map.json] [--logic-spec logic-spec.md] [--key "Segment"]
          [--case stored] [--tolerance "abs=1e-6,rel=1e-9"] [--explain explain.csv]
          --out reconciliation

The actual table is either long (columns case, output, index, value: what the
calculation model writes) or wide (one column per output, one row per key: a CSV
exported from a Spotfire data table). In a wide table, --key names the column
that holds the index (segment, month, well); without it rows are matched by
position. Output columns are matched to output names without regard to case,
spaces or punctuation; output-map.json may give a "column" for each output.

Tolerance per output, first match wins: --tolerance, "abs"/"rel" in
output-map.json, the Logic Spec's Conventions line (for example
"Rounding and tolerance for reconciliation: default abs=1e-6 rel=1e-9; L05
abs=0.001"), then abs=1e-9 rel=1e-9. A value passes when
|actual - expected| <= abs + rel * |expected|.

An Excel error value (#DIV/0!, #N/A) matches an empty or error value in the
actual table. --explain takes a CSV (output, index, explanation; index * for all
rows) so a known, owner-accepted difference is reported as EXPLAINED.

Writes <out>.md and <out>.csv. Exit code 0 when every expected value matches or
is explained, 1 otherwise. compare uses the standard library only; extract needs
xlsxlib.py from this folder.
"""

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_ABS = 1e-9
DEFAULT_REL = 1e-9
ERRORS = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#SPILL!",
          "#CALC!", "#GETTING_DATA")


def norm_name(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def norm_key(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return f"{value:.12g}"
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return norm_key(number) if math.isfinite(number) else text


def parse_value(text):
    if text is None:
        return None
    if not isinstance(text, str):
        return text
    s = text.strip()
    if s == "" or s.lower() in ("nan", "none", "null", "(empty)"):
        return None
    if s.upper() in ("TRUE", "FALSE"):
        return s.upper() == "TRUE"
    if s.upper() in ERRORS:
        return s.upper()
    try:
        return float(s)
    except ValueError:
        return s


# -- extract ------------------------------------------------------------------

def _range_values(wb, ref):
    import xlsxlib as X
    sheet_text, _, area = ref.rpartition("!")
    name = sheet_text.strip("'").replace("''", "'")
    sheet = wb.sheet(name)
    if sheet is None:
        raise ValueError(f"no sheet '{name}' in the workbook (range {ref})")
    r1, c1, r2, c2 = X.parse_range(area)
    if r1 != r2 and c1 != c2:
        return [sheet.value(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
    if r1 == r2:
        return [sheet.value(r1, c) for c in range(c1, c2 + 1)]
    return [sheet.value(r, c1) for r in range(r1, r2 + 1)]


def extract_expected(workbook, omap, case="stored"):
    """Rows (case, output, index, value) of the workbook's stored values."""
    import xlsxlib as X
    wb = X.load(workbook)
    if wb.calc.get("fullCalcOnLoad") in ("1", "true"):
        print(f"WARNING {workbook}: marked for recalculation and not yet saved by Excel; "
              "its stored values are stale", file=sys.stderr)
    rows = []
    for item in omap["outputs"]:
        values = _range_values(wb, item["range"])
        keys = _range_values(wb, item["key"]) if item.get("key") else None
        if keys is not None and len(keys) != len(values):
            raise ValueError(f"output {item['name']}: key range {item['key']} has "
                             f"{len(keys)} cells, value range has {len(values)}")
        for i, value in enumerate(values):
            index = norm_key(keys[i]) if keys is not None else str(i + 1)
            rows.append((case, item["name"], index, value))
    return rows


def write_long(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case", "output", "index", "value"])
        for case, output, index, value in rows:
            if isinstance(value, float):
                value = repr(value)
            elif isinstance(value, bool):
                value = "TRUE" if value else "FALSE"
            writer.writerow([case, output, index, "" if value is None else value])


# -- read tables --------------------------------------------------------------

def read_long(path, default_case):
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            case = row.get("case") or default_case
            key = (case, row["output"], norm_key(row.get("index", "1")))
            out[key] = parse_value(row.get("value"))
    return out


def read_actual(path, outputs, key_col, default_case, columns):
    """Return {(case, output, index): value}, the unmatched columns, and the
    format found."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)
    lower = {f.lower(): f for f in fields}
    if "output" in lower and "value" in lower:
        out = {}
        for row in rows:
            case = row.get(lower.get("case", ""), "") or default_case
            index = norm_key(row.get(lower.get("index", ""), "1") or "1")
            out[(case, row[lower["output"]], index)] = parse_value(row[lower["value"]])
        return out, [], "long"
    by_norm = {norm_name(f): f for f in fields}
    mapping = {}
    for name in outputs:
        wanted = columns.get(name) or name
        col = wanted if wanted in fields else by_norm.get(norm_name(wanted))
        if col is None:
            col = by_norm.get(norm_name(re.sub(r"\s*\[.*\]$", "", name)))
        if col is not None:
            mapping[name] = col
    key_field = None
    if key_col:
        key_field = key_col if key_col in fields else by_norm.get(norm_name(key_col))
        if key_field is None:
            raise ValueError(f"key column '{key_col}' is not in {path}")
    case_field = lower.get("case")
    out = {}
    for pos, row in enumerate(rows, 1):
        case = row.get(case_field) if case_field else default_case
        index = norm_key(row[key_field]) if key_field else str(pos)
        for name, col in mapping.items():
            out[(case, name, index)] = parse_value(row[col])
    used = set(mapping.values()) | {key_field, case_field}
    return out, [f for f in fields if f not in used], "wide"


# -- tolerances ---------------------------------------------------------------

def logic_spec_tolerances(path):
    """Return ({'default' or L-ID: (abs, rel)}, {output name: L-ID})."""
    text = Path(path).read_text(encoding="utf-8")
    tol = {}
    conv = re.search(r"tolerance[^\n]*", text, re.I)
    if conv:
        line = conv.group(0)
        for part in re.split(r";", line):
            who = re.search(r"\b(default|L\d+)\b", part)
            a = re.search(r"abs\s*=\s*([-+0-9.eE]+)", part)
            r = re.search(r"rel\s*=\s*([-+0-9.eE]+)", part)
            if who and (a or r):
                tol[who.group(1)] = (float(a.group(1)) if a else None,
                                     float(r.group(1)) if r else None)
    ids = {}
    for entry in re.split(r"^### ", text, flags=re.M)[1:]:
        lid = re.match(r"(L\d+)", entry)
        out = re.search(r"^- Output:\s*`([^`]+)`", entry, re.M)
        if lid and out:
            ids[norm_name(out.group(1))] = lid.group(1)
        if lid:
            local = re.search(r"^- Tolerance:\s*(.*)$", entry, re.M)
            if local:
                a = re.search(r"abs\s*=\s*([-+0-9.eE]+)", local.group(1))
                r = re.search(r"rel\s*=\s*([-+0-9.eE]+)", local.group(1))
                tol[lid.group(1)] = (float(a.group(1)) if a else None,
                                     float(r.group(1)) if r else None)
    return tol, ids


def parse_tolerance(text):
    a = re.search(r"abs\s*=\s*([-+0-9.eE]+)", text or "")
    r = re.search(r"rel\s*=\s*([-+0-9.eE]+)", text or "")
    return (float(a.group(1)) if a else None, float(r.group(1)) if r else None)


def resolve_tolerance(name, entry, override, spec_tol, spec_ids):
    lid = (entry or {}).get("id") or spec_ids.get(norm_name(name)) or \
        spec_ids.get(norm_name(re.sub(r"\s*\[.*\]$", "", name)))
    for source, pair in (("--tolerance", override),
                         ("output-map.json", ((entry or {}).get("abs"), (entry or {}).get("rel"))),
                         (f"logic-spec {lid}", spec_tol.get(lid) if lid else None),
                         ("logic-spec default", spec_tol.get("default"))):
        if pair and (pair[0] is not None or pair[1] is not None):
            a = DEFAULT_ABS if pair[0] is None else pair[0]
            r = DEFAULT_REL if pair[1] is None else pair[1]
            return a, r, source, lid
    return DEFAULT_ABS, DEFAULT_REL, "default", lid


# -- compare ------------------------------------------------------------------

def compare_value(expected, actual, tol_abs, tol_rel):
    """Return (status, abs diff, rel diff, note)."""
    is_err = isinstance(expected, str) and expected in ERRORS
    if is_err:
        if actual is None or (isinstance(actual, float) and math.isnan(actual)) or \
                (isinstance(actual, str) and actual in ERRORS):
            return "PASS", None, None, f"Excel {expected} reproduced as empty or error"
        return "FAIL", None, None, f"Excel shows {expected}"
    if expected is None:
        if actual is None or actual == "" or actual == 0.0:
            return "PASS", None, None, "empty cell"
        return "FAIL", None, None, "Excel cell is empty"
    if isinstance(expected, bool) or isinstance(actual, bool):
        e = expected if isinstance(expected, bool) else (expected == 1.0 if
                                                         isinstance(expected, float) else None)
        a = actual if isinstance(actual, bool) else (actual == 1.0 if
                                                     isinstance(actual, float) else None)
        return ("PASS" if e == a and e is not None else "FAIL"), None, None, ""
    if isinstance(expected, float):
        if actual is None:
            return "FAIL", None, None, "no value"
        if not isinstance(actual, float):
            return "FAIL", None, None, f"text {actual!r}"
        diff = abs(actual - expected)
        rel = diff / abs(expected) if expected != 0 else (0.0 if diff == 0 else math.inf)
        ok = diff <= tol_abs + tol_rel * abs(expected)
        return ("PASS" if ok else "FAIL"), diff, rel, ""
    a = "" if actual is None else (repr(actual) if isinstance(actual, float) else str(actual))
    if a == expected:
        return "PASS", None, None, ""
    if a.lower() == str(expected).lower():
        return "FAIL", None, None, "text differs in case only"
    return "FAIL", None, None, ""


def read_explanations(path):
    out = {}
    if not path:
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            out[(row["output"], norm_key(row.get("index", "*")) or "*")] = row["explanation"]
    return out


def compare(expected, actual, entries, override, spec_tol, spec_ids, explanations):
    results = []
    tolerances = {}
    for key in sorted(expected, key=lambda k: (k[0], k[1], _sort_index(k[2]))):
        case, name, index = key
        if name not in tolerances:
            tolerances[name] = resolve_tolerance(name, entries.get(name), override, spec_tol,
                                                 spec_ids)
        tol_abs, tol_rel, _, _ = tolerances[name]
        exp = expected[key]
        if key not in actual:
            status, diff, rel, note = "MISSING", None, None, "not in the actual table"
            act = None
        else:
            act = actual[key]
            status, diff, rel, note = compare_value(exp, act, tol_abs, tol_rel)
        if status in ("FAIL", "MISSING"):
            why = explanations.get((name, index)) or explanations.get((name, "*"))
            if why:
                status, note = "EXPLAINED", why
        results.append({"case": case, "output": name, "index": index, "expected": exp,
                        "actual": act, "absDiff": diff, "relDiff": rel, "status": status,
                        "note": note})
    extra = sorted(k for k in actual if k not in expected)
    return results, extra, tolerances


def _sort_index(index):
    try:
        return (0, float(index), "")
    except ValueError:
        return (1, 0.0, index)


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def write_report(stem, results, extra, tolerances, meta):
    stem = Path(stem)
    if stem.suffix in (".md", ".csv"):
        stem = stem.with_suffix("")
    stem.parent.mkdir(parents=True, exist_ok=True)
    with open(stem.with_suffix(".csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case", "output", "index", "expected", "actual", "abs_diff",
                         "rel_diff", "status", "note"])
        for r in results:
            writer.writerow([r["case"], r["output"], r["index"], _fmt(r["expected"]),
                             _fmt(r["actual"]), _fmt(r["absDiff"]), _fmt(r["relDiff"]),
                             r["status"], r["note"]])
    per = defaultdict(lambda: defaultdict(int))
    worst = defaultdict(lambda: [0.0, 0.0])
    for r in results:
        per[r["output"]][r["status"]] += 1
        per[r["output"]]["values"] += 1
        if r["absDiff"] is not None:
            worst[r["output"]][0] = max(worst[r["output"]][0], r["absDiff"])
            if math.isfinite(r["relDiff"]):
                worst[r["output"]][1] = max(worst[r["output"]][1], r["relDiff"])
    failed = sum(1 for r in results if r["status"] in ("FAIL", "MISSING"))
    explained = sum(1 for r in results if r["status"] == "EXPLAINED")
    verdict = "PASS" if failed == 0 else "FAIL"
    lines = ["# Reconciliation report", "",
             f"- Expected: `{meta['expected']}` (the workbook's values)",
             f"- Actual: `{meta['actual']}` ({meta['format']} table)",
             f"- Written: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
             f"- Values compared: {len(results)}; failed or missing: {failed}; "
             f"explained: {explained}", "",
             f"**Result: {verdict}**" + ("" if failed == 0 else
                                         f" ({failed} values differ or are missing)"), "",
             "## Per output", "",
             "| Output | Logic Spec ID | Values | Pass | Fail | Missing | Explained | "
             "Max abs diff | Max rel diff | Tolerance (source) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in sorted(per):
        c = per[name]
        tol_abs, tol_rel, source, lid = tolerances[name]
        lines.append(f"| {name} | {lid or ''} | {c['values']} | {c['PASS']} | {c['FAIL']} | "
                     f"{c['MISSING']} | {c['EXPLAINED']} | {_fmt(worst[name][0])} | "
                     f"{_fmt(worst[name][1])} | abs={tol_abs:g} rel={tol_rel:g} ({source}) |")
    bad = [r for r in results if r["status"] in ("FAIL", "MISSING", "EXPLAINED")]
    if bad:
        lines += ["", "## Differences", "",
                  "| Case | Output | Index | Expected | Actual | Abs diff | Status | Note |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in bad[:300]:
            lines.append(f"| {r['case']} | {r['output']} | {r['index']} | {_fmt(r['expected'])}"
                         f" | {_fmt(r['actual'])} | {_fmt(r['absDiff'])} | {r['status']} | "
                         f"{r['note']} |")
        if len(bad) > 300:
            lines.append(f"| ... | {len(bad) - 300} more rows in {stem.with_suffix('.csv').name}"
                         " | | | | | | |")
    if extra:
        lines += ["", f"## Values in the actual table with no expected value ({len(extra)})", ""]
        lines += [f"- {c} / {o} / {i}" for c, o, i in extra[:50]]
    if meta.get("unmatched"):
        lines += ["", "Columns of the actual table not compared: " +
                  ", ".join(f"`{c}`" for c in meta["unmatched"][:30])]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="expected values from the workbook")
    ex.add_argument("--workbook", required=True)
    ex.add_argument("--map", required=True, help="output-map.json")
    ex.add_argument("--out", required=True, help="expected CSV")
    ex.add_argument("--case", default="stored")
    cp = sub.add_parser("compare", help="compare actual values with expected values")
    cp.add_argument("--expected", required=True)
    cp.add_argument("--actual", required=True)
    cp.add_argument("--map", help="output-map.json (tolerances, column names, Logic Spec IDs)")
    cp.add_argument("--logic-spec", help="logic-spec.md (tolerances)")
    cp.add_argument("--key", help="index column of a wide actual table")
    cp.add_argument("--case", default="stored", help="case name for a wide actual table")
    cp.add_argument("--tolerance", help='override for every output, "abs=1e-6,rel=1e-9"')
    cp.add_argument("--explain", help="CSV: output, index, explanation")
    cp.add_argument("--out", required=True, help="report path without suffix")
    args = parser.parse_args()

    if args.command == "extract":
        omap = json.loads(Path(args.map).read_text(encoding="utf-8"))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        rows = extract_expected(args.workbook, omap, args.case)
        write_long(rows, args.out)
        print(f"{len(rows)} expected values -> {args.out}")
        return 0

    omap = json.loads(Path(args.map).read_text(encoding="utf-8")) if args.map else \
        {"outputs": []}
    entries = {o["name"]: o for o in omap.get("outputs", [])}
    columns = {o["name"]: o.get("column") for o in omap.get("outputs", []) if o.get("column")}
    expected = read_long(args.expected, args.case)
    names = sorted({k[1] for k in expected})
    actual, unmatched, fmt = read_actual(args.actual, names, args.key, args.case, columns)
    spec_tol, spec_ids = logic_spec_tolerances(args.logic_spec) if args.logic_spec else ({}, {})
    override = parse_tolerance(args.tolerance) if args.tolerance else None
    results, extra, tolerances = compare(expected, actual, entries, override, spec_tol,
                                         spec_ids, read_explanations(args.explain))
    verdict, failed = write_report(args.out, results, extra, tolerances,
                                   {"expected": args.expected, "actual": args.actual,
                                    "format": fmt, "unmatched": unmatched})
    print(f"{verdict}: {len(results)} values, {failed} failed or missing -> "
          f"{Path(args.out).with_suffix('.md')}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
