"""Stage 5: expected values for extra input sets, recalculated by Excel.

The stored values cover one input set. Extra cases exercise every branch and
lookup range. cases.csv has a 'case' column and one column per input cell:

    case,Inputs!B3,Inputs!B6
    low_flow,6000,25
    old_pipe,12000,32

Commands:

  make     write one copy of the workbook per case with the inputs set and the
           file marked for full recalculation. The owner (or you) opens each copy
           in Excel, lets it recalculate, saves and closes it. Nothing else in the
           file changes.
      python excel_cases.py make --workbook book.xlsx --cases cases.csv --out cases/

  extract  read the recalculated copies and write the expected values for every
           output in output-map.json (long CSV for reconcile.py compare). A copy
           that Excel has not recalculated and saved is reported and skipped.
      python excel_cases.py extract --cases-dir cases/ --map output-map.json
          --out expected-cases.csv

  recalc   run the cases without opening each copy by hand. Not yet tested.
           --engine excel: a new hidden Excel instance through COM (Windows,
           pywin32), macros disabled, links not updated, read-only, nothing saved;
           workbooks you have open are not touched.
           --engine formulas: the 'formulas' package (pip install formulas), no
           Excel needed; it does not support every Excel function.
      python excel_cases.py recalc --workbook book.xlsx --cases cases.csv
          --map output-map.json --out expected-cases.csv --engine excel
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import reconcile as R
import xlsxlib as X


def read_cases(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    cases = []
    for row in rows:
        name = row.pop("case")
        changes = {}
        for key, text in row.items():
            if text is None or text == "":
                continue
            value = R.parse_value(text)
            changes[key] = value
        cases.append((name, changes))
    return cases


def make(workbook, cases_csv, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = Path(workbook).suffix
    written = []
    for name, changes in read_cases(cases_csv):
        target = out / f"{name}{suffix}"
        X.write_inputs(workbook, target, changes)
        written.append(target)
    return written


def extract(cases_dir, omap):
    rows, skipped = [], []
    for path in sorted(Path(cases_dir).iterdir()):
        if path.suffix.lower() not in (".xlsx", ".xlsm"):
            continue
        wb = X.load(path)
        if wb.calc.get("fullCalcOnLoad") in ("1", "true"):
            skipped.append(path.name)
            continue
        rows.extend(R.extract_expected(path, omap, path.stem))
    return rows, skipped


def _split(ref):
    sheet, _, area = ref.rpartition("!")
    return sheet.strip("'").replace("''", "'"), area.replace("$", "")


def _flatten(value):
    if isinstance(value, tuple):
        out = []
        for item in value:
            out.extend(_flatten(item))
        return out
    return [value]


def recalc_excel(workbook, cases, omap):
    """Not yet tested. One hidden Excel instance; nothing is saved."""
    import win32com.client
    excel = win32com.client.DispatchEx("Excel.Application")
    rows = []
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.ScreenUpdating = False
        excel.EnableEvents = False
        excel.AutomationSecurity = 3
        book = excel.Workbooks.Open(str(Path(workbook).resolve()), UpdateLinks=0,
                                    ReadOnly=True, IgnoreReadOnlyRecommended=True,
                                    AddToMru=False, Notify=False)
        for name, changes in cases:
            for ref, value in changes.items():
                sheet, area = _split(ref)
                book.Worksheets(sheet).Range(area).Value = value
            excel.CalculateFull()
            for item in omap["outputs"]:
                sheet, area = _split(item["range"])
                values = _flatten(book.Worksheets(sheet).Range(area).Value)
                keys = None
                if item.get("key"):
                    ksheet, karea = _split(item["key"])
                    keys = _flatten(book.Worksheets(ksheet).Range(karea).Value)
                for i, value in enumerate(values):
                    index = R.norm_key(keys[i]) if keys else str(i + 1)
                    rows.append((name, item["name"], index,
                                 float(value) if isinstance(value, (int, float)) and
                                 not isinstance(value, bool) else value))
        book.Close(SaveChanges=False)
    finally:
        excel.Quit()
    return rows


def recalc_formulas(workbook, cases, omap):
    """Not yet tested. Uses the optional 'formulas' package."""
    import formulas
    book_name = Path(workbook).name.upper()
    model = formulas.ExcelModel().loads(str(workbook)).finish()

    def key(ref):
        sheet, area = _split(ref)
        return f"'[{book_name}]{sheet.upper()}'!{area.upper()}"
    rows = []
    for name, changes in cases:
        wanted = [key(o["range"]) for o in omap["outputs"]] + \
                 [key(o["key"]) for o in omap["outputs"] if o.get("key")]
        solution = model.calculate(inputs={key(r): v for r, v in changes.items()},
                                   outputs=wanted)
        for item in omap["outputs"]:
            values = list(solution[key(item["range"])].value.ravel())
            keys = list(solution[key(item["key"])].value.ravel()) if item.get("key") else None
            for i, value in enumerate(values):
                index = R.norm_key(keys[i]) if keys else str(i + 1)
                rows.append((name, item["name"], index, value))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--workbook", required=True)
    mk.add_argument("--cases", required=True)
    mk.add_argument("--out", required=True, help="folder for the case copies")
    ex = sub.add_parser("extract")
    ex.add_argument("--cases-dir", required=True)
    ex.add_argument("--map", required=True)
    ex.add_argument("--out", required=True)
    rc = sub.add_parser("recalc")
    rc.add_argument("--workbook", required=True)
    rc.add_argument("--cases", required=True)
    rc.add_argument("--map", required=True)
    rc.add_argument("--out", required=True)
    rc.add_argument("--engine", choices=["excel", "formulas"], required=True)
    args = parser.parse_args()

    if args.command == "make":
        written = make(args.workbook, args.cases, args.out)
        print(f"{len(written)} case copies -> {args.out}")
        print("Open each copy in Excel, let it recalculate, save and close it, then run "
              "'excel_cases.py extract'.")
        return 0
    omap = json.loads(Path(args.map).read_text(encoding="utf-8"))
    if args.command == "extract":
        rows, skipped = extract(args.cases_dir, omap)
        R.write_long(rows, args.out)
        for name in skipped:
            print(f"SKIPPED {name}: not yet recalculated and saved by Excel")
        print(f"{len(rows)} expected values -> {args.out}")
        return 1 if skipped else 0
    cases = read_cases(args.cases)
    try:
        if args.engine == "excel":
            rows = recalc_excel(args.workbook, cases, omap)
        else:
            rows = recalc_formulas(args.workbook, cases, omap)
    except ImportError as exc:
        print(f"The {args.engine} engine is not available ({exc}). Use 'make' and "
              "'extract' instead.")
        return 2
    R.write_long(rows, args.out)
    print(f"{len(rows)} expected values -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
