"""Stage 5: write the scaffold of the Python calculation model.

Writes into the ingest folder:
    calc_model.py     one section per workbook block in calculation order, with the
                      block's Excel formula, R1C1 form, label and the blocks it reads;
                      INPUTS with the workbook's stored input values; OUTPUTS; run()
    excel_compat.py   copy of the Excel behaviour helpers the model imports
    data/*.csv        raw data and lookup ranges, one CSV each
    output-map.json   draft list of outputs to reconcile (name, workbook range, key)

You then port each block following logic-spec.md. The finished model is the data
function code (export_data_function.py), so it uses only the standard library,
numpy and pandas.

Usage:
    python calc_model_scaffold.py <workbook.xlsx> --out <ingest folder> [--force]

An existing calc_model.py is kept unless --force is given.
"""

import argparse
import csv
import heapq
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import xlsxlib as X
import structure as S

HEADER = '''"""Calculation model of {workbook}.

Each section below reproduces one block of the workbook (a range whose cells share
one formula). Port every section following logic-spec.md, run
    python calc_model.py --out actual-model.csv
and compare with Excel's values using reconcile.py until every output matches or
the owner has accepted the difference.

This code becomes the data function code, so it uses only the standard library,
numpy, pandas and the excel_compat functions.
"""

import math
import sys
from pathlib import Path

import pandas as pd

from excel_compat import (HIDDEN_ERRORS, ExcelError, arith, average, div, edate, iferror,
                          irr, log10, npv, power, sqrt, vlookup, xmax, xmin, xround, xsum)

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # inside a Spotfire data function there is no file
    HERE = Path(".")

# Data function interface, filled in at stage 6 (export_data_function.py reads it):
# Spotfire parameter name -> model key.
PARAMETERS = {}          # value inputs bound to document properties: {"FlowRate": "Inputs!B3"}
TABLE_PARAMETERS = {}    # table inputs: {"SEGMENTS": "Segments!A2:D21"}
SPOTFIRE_OUTPUTS = []    # names of the data function outputs: ["SEGMENT_RESULTS"]


def spotfire_outputs(result):
    """Turn the result of run() into the data function outputs (tables as pandas
    DataFrames, single values as numbers or text)."""
    return {}
'''

FOOTER = '''

def load_tables(folder=HERE):
    """Read the raw data and lookup ranges written next to this model."""
    return {key: pd.read_csv(Path(folder) / path) for key, path in TABLES.items()}


def _rows(name, value):
    if isinstance(value, dict):
        return [(name, k, v) for k, v in value.items()]
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        values = value.tolist() if hasattr(value, "tolist") else value
        return [(name, i, v) for i, v in enumerate(values, 1)]
    return [(name, 1, value)]


def _value(text):
    try:
        return float(text)
    except ValueError:
        return text


if __name__ == "__main__":
    import argparse
    import csv

    parser = argparse.ArgumentParser(description="Run the model and write its outputs.")
    parser.add_argument("--cases", help="CSV: a 'case' column, then one column per input "
                        "cell (for example Inputs!B3)")
    parser.add_argument("--out", default="actual-model.csv")
    args = parser.parse_args()
    cases = [("stored", {})]
    if args.cases:
        with open(args.cases, newline="", encoding="utf-8") as fh:
            cases = [(row.pop("case"), {k: _value(v) for k, v in row.items() if v != ""})
                     for row in csv.DictReader(fh)]
    tables = load_tables()
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case", "output", "index", "value"])
        for case, inputs in cases:
            del HIDDEN_ERRORS[:]
            result = run(inputs, tables)
            for name, value in result.items():
                for row in _rows(name, value):
                    writer.writerow([case, *row])
            for item in HIDDEN_ERRORS:
                print(f"case {case}: hidden error {item['error']} at {item['where']}",
                      file=sys.stderr)
    print(f"wrote {args.out}")
'''


def _slug(text):
    return re.sub(r"[^\w]+", "_", text).strip("_") or "range"


def _topo(st):
    by_id = {b.id: b for b in st.blocks}
    indeg = {b.id: 0 for b in st.blocks}
    for b in st.blocks:
        for p in b.precedents:
            if p in by_id:
                indeg[b.id] += 1
    order, heap = [], [i for i, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    while heap:
        bid = heapq.heappop(heap)
        order.append(bid)
        for dep in by_id[bid].dependents:
            indeg[dep] -= 1
            if indeg[dep] == 0:
                heapq.heappush(heap, dep)
    rest = [b.id for b in st.blocks if b.id not in order]
    return [by_id[i] for i in order + rest], set(rest)


def _is_key(cells):
    """Cells that can identify rows: all filled, unique, text or whole numbers."""
    values = []
    for cell in cells:
        if cell is None or cell.value is None or cell.vtype == "e":
            return False
        value = cell.value
        if isinstance(value, float) and not value.is_integer():
            return False
        values.append(value)
    return len(set(values)) == len(values)


def _key_range(st, block):
    """The column (or row) that identifies the rows of a vector output: the input
    column of a what-if data table, else the first column (row) from the left
    (top) whose cells are unique text or whole numbers."""
    sheet = st.wb.sheet(block.sheet)
    if block.r1 == block.r2 and block.c1 == block.c2:
        return None
    first = sheet.get(block.r1, block.c1)
    if first is not None and first.ftype == "dataTable" and block.c1 > 1:
        col = block.c1 - 1
        return f"{X.quote_sheet(block.sheet)}!{X.range_text(block.r1, col, block.r2, col)}"
    if block.vertical:
        for c in range(1, block.c1):
            if _is_key([sheet.get(r, c) for r in range(block.r1, block.r2 + 1)]):
                return f"{X.quote_sheet(block.sheet)}!{X.range_text(block.r1, c, block.r2, c)}"
    else:
        for r in range(1, block.r1):
            if _is_key([sheet.get(r, c) for c in range(block.c1, block.c2 + 1)]):
                return f"{X.quote_sheet(block.sheet)}!{X.range_text(r, block.c1, r, block.c2)}"
    return None


def write_tables(st, folder):
    tables = {}
    data = folder / "data"
    for block in st.blocks:
        if block.role not in ("raw data", "lookup") or block.kind != "number":
            continue
        sheet = st.wb.sheet(block.sheet)
        r1, c1, r2, c2 = block.r1, block.c1, block.r2, block.c2
        headers = [S.header_above(sheet, r1, c) or X.num_to_col(c) for c in range(c1, c2 + 1)]
        name = f"{_slug(block.sheet)}_{_slug(block.range)}.csv"
        data.mkdir(parents=True, exist_ok=True)
        with open(data / name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for r in range(r1, r2 + 1):
                writer.writerow(["" if sheet.value(r, c) is None else sheet.value(r, c)
                                 for c in range(c1, c2 + 1)])
        tables[f"{X.quote_sheet(block.sheet)}!{block.range}"] = (f"data/{name}", block.role,
                                                                  block.label)
    return tables


def inputs_of(st):
    rows = []
    for block in st.blocks:
        sheet = st.wb.sheet(block.sheet)
        if block.kind != "formula" and block.role in ("input", "parameter", "override"):
            for r, c in block.cells:
                cell = sheet.get(r, c)
                rows.append((f"{X.quote_sheet(block.sheet)}!{X.addr(r, c)}", cell.value,
                             S.cell_label(st, block.sheet, r, c), block.role))
        elif block.kind == "formula" and block.external and not block.precedents:
            for r, c in block.cells:
                cell = sheet.get(r, c)
                rows.append((f"{X.quote_sheet(block.sheet)}!{X.addr(r, c)}", cell.value,
                             block.label, "input (external link)"))
    return rows


def _merge_columns(blocks):
    """Join blocks of one column (or row) with the same label that touch, such as
    a first-row formula and the filled-down formula below it."""
    blocks = sorted(blocks, key=lambda b: (b.sheet, b.label or "", b.c1, b.r1))
    groups = []
    for b in blocks:
        last = groups[-1][-1] if groups else None
        if last is not None and last.sheet == b.sheet and last.label == b.label and (
                (last.c1, last.c2) == (b.c1, b.c2) and b.r1 == last.r2 + 1 or
                (last.r1, last.r2) == (b.r1, b.r2) and b.c1 == last.c2 + 1):
            groups[-1].append(b)
        else:
            groups.append([b])
    return groups


def outputs_of(st):
    out = []
    chosen = []
    for block in st.blocks:
        if block.kind != "formula":
            continue
        charted = any((block.sheet, r, c) in st.chart_values for r, c in block.cells)
        first = st.wb.sheet(block.sheet).get(*block.first)
        axis = first is not None and st.wb.is_date_style(first.style)
        if charted or (block.role == "output" and not axis):
            chosen.append(block)
    groups = _merge_columns(chosen)
    groups.sort(key=lambda g: (st.wb.sheet(g[0].sheet).index, g[0].r1, g[0].c1))
    for group in groups:
        first = group[0]
        r1, c1 = min(b.r1 for b in group), min(b.c1 for b in group)
        r2, c2 = max(b.r2 for b in group), max(b.c2 for b in group)
        name = first.label or f"{first.sheet} {X.range_text(r1, c1, r2, c2)}"
        item = {"name": name,
                "range": f"{X.quote_sheet(first.sheet)}!{X.range_text(r1, c1, r2, c2)}",
                "id": None, "blocks": [b.id for b in group]}
        probe = S.Block(first.sheet, r1, c1, r2, c2, "formula", None)
        key = _key_range(st, probe)
        if key:
            item["key"] = key
        out.append(item)
    names = defaultdict(int)
    for item in out:
        names[item["name"]] += 1
    for item in out:
        if names[item["name"]] > 1:
            item["name"] = f"{item['name']} [{item['range']}]"
    return out


def render(st, workbook, tables):
    lines = [HEADER.replace("{workbook}", workbook)]
    lines.append("# Inputs with the workbook's stored values. logic-spec.md maps each one")
    lines.append("# to a document property or a data table column.")
    lines.append("INPUTS = {")
    for ref, value, label, role in inputs_of(st):
        note = f"{label or ''} [{role}]".strip()
        lines.append(f"    {ref!r}: {value!r},  # {note}")
    lines.append("}")
    lines.append("")
    lines.append("# Raw data and lookup ranges, written as CSV next to this model.")
    lines.append("TABLES = {")
    for ref, (path, role, label) in tables.items():
        lines.append(f"    {ref!r}: {path!r},  # {role}: {label or ''}")
    lines.append("}")
    lines.append("")
    lines.append("# Outputs compared with the workbook: output-map.json lists their ranges.")
    lines.append("OUTPUTS = [")
    for item in outputs_of(st):
        lines.append(f"    {item['name']!r},  # {item['range']}")
    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("def run(inputs=None, tables=None):")
    lines.append('    """Return {output name: value, list of values or {key: value}}."""')
    lines.append("    x = dict(INPUTS)")
    lines.append("    x.update(inputs or {})")
    lines.append("    t = tables if tables is not None else load_tables()")
    lines.append("    out = {}")
    order, cyclic = _topo(st)
    for block in order:
        if block.kind != "formula":
            continue
        sheet = st.wb.sheet(block.sheet)
        first = sheet.get(*block.first)
        lines.append("")
        lines.append(f"    # {block.id} {X.quote_sheet(block.sheet)}!{block.range}  "
                     f"{block.label or '(no label)'}  [{block.role}, {len(block.cells)} "
                     f"cell{'s' if len(block.cells) != 1 else ''}]")
        lines.append(f"    #   Excel: ={first.formula}")
        lines.append(f"    #   R1C1:  {block.key}")
        if block.precedents:
            lines.append(f"    #   Reads: {', '.join(sorted(block.precedents))}")
        if block.exceptions:
            lines.append("    #   Exceptions: " + ", ".join(X.addr(r, c)
                                                         for r, c in block.exceptions))
        if block.id in cyclic:
            lines.append("    #   Circular group: iterate until the change is below the "
                         "Logic Spec tolerance.")
        if block.external:
            lines.append("    #   Reads another workbook: its stored value is in INPUTS.")
        lines.append(f"    # Port: {block.label or block.id}")
    lines.append("")
    lines.append("    return out")
    lines.append(FOOTER)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("workbook")
    parser.add_argument("--out", required=True, help="ingest folder")
    parser.add_argument("--force", action="store_true", help="overwrite calc_model.py")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wb = X.load(args.workbook)
    st = S.analyze(wb)
    tables = write_tables(st, out)
    model = out / "calc_model.py"
    if model.exists() and not args.force:
        print(f"{model} exists; kept it (use --force to replace it)")
    else:
        model.write_text(render(st, Path(args.workbook).name, tables), encoding="utf-8")
        print(f"scaffold -> {model}")
    shutil.copyfile(Path(__file__).with_name("excel_compat.py"), out / "excel_compat.py")
    omap = out / "output-map.json"
    if not omap.exists() or args.force:
        omap.write_text(json.dumps({"workbook": Path(args.workbook).name,
                                    "outputs": outputs_of(st)}, indent=1), encoding="utf-8")
        print(f"output map -> {omap}")
    print(f"{len(tables)} tables -> {out / 'data'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
