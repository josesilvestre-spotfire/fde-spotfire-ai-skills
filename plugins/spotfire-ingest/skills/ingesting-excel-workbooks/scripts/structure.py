"""Stage 2: blocks, cell roles, dependency graph and template copies.

Converts every formula to relative R1C1 text, so a column of filled-down copies
becomes one block. Groups constants the same way. Gives each block a role (input,
parameter, lookup, raw data, label, calculation, output, terminal), a label and a
unit from the nearest header, and the blocks it reads from and feeds. Finds
circular references and sheets copied from one template, and lists where the
copies differ.

Usage:
    python structure.py <workbook.xlsx> --out <ingest folder>

Writes structure.json and dependencies.mmd (Mermaid flowchart of the blocks).
Standard library only.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import xlsxlib as X

LOOKUP_TABLE_ARG = {"VLOOKUP": 1, "HLOOKUP": 1, "MATCH": 1, "LOOKUP": 1, "XLOOKUP": 1,
                    "INDEX": 0, "XMATCH": 1}
INPUT_SHEET = re.compile(r"input|assum|scenario|case|param|setting|control", re.I)
OUTPUT_SHEET = re.compile(r"summar|dashboard|output|result|report|kpi|overview", re.I)
OUTPUT_LABEL = re.compile(r"\b(npv|irr|total|eur|payback|break-?even|result|summary|"
                          r"average|maximum|minimum|net)\b", re.I)
UNIT_RE = re.compile(r"[(\[]([^()\[\]]{1,24})[)\]]\s*:?\s*$")
AGGREGATES = {"SUM", "AVERAGE", "MAX", "MIN", "NPV", "IRR", "XNPV", "XIRR", "SUMPRODUCT",
              "COUNT", "COUNTA", "MEDIAN", "SUMIF", "SUMIFS", "AVERAGEIF", "AVERAGEIFS"}
RANGE_CACHE_LIMIT = 50000


def arg_context(tokens):
    """For each token, the innermost function call it sits in: (name, arg index)
    or None. Plain parentheses and array braces inherit the enclosing call."""
    out, stack = [], []
    pending = None
    for tok in tokens:
        if tok.kind == "func":
            pending = tok.value
            out.append(_ctx(stack))
            continue
        if tok.kind == "open":
            out.append(_ctx(stack))
            stack.append([pending, 0, pending is not None])
            pending = None
            continue
        if tok.kind == "close":
            if stack:
                stack.pop()
            out.append(_ctx(stack))
            continue
        if tok.kind == "sep" and stack and stack[-1][2]:
            stack[-1][1] += 1
        out.append(_ctx(stack))
    return out


def _ctx(stack):
    for entry in reversed(stack):
        if entry[2]:
            return entry[0], entry[1]
    return None


def unit_of(label):
    if not label:
        return None
    match = UNIT_RE.search(label.strip())
    if not match:
        return None
    unit = match.group(1).strip()
    if not unit or len(unit.split()) > 3:
        return None
    return unit


class Block:
    __slots__ = ("id", "sheet", "r1", "c1", "r2", "c2", "kind", "key", "cells", "exceptions",
                 "role", "label", "unit", "precedents", "dependents", "functions",
                 "external", "dynamic", "first")

    def __init__(self, sheet, r1, c1, r2, c2, kind, key):
        self.sheet, self.r1, self.c1, self.r2, self.c2 = sheet, r1, c1, r2, c2
        self.kind, self.key = kind, key
        self.cells, self.exceptions = [], []
        self.role = self.label = self.unit = self.id = self.first = None
        self.precedents, self.dependents = set(), set()
        self.functions, self.external, self.dynamic = set(), set(), set()

    @property
    def range(self):
        return X.range_text(self.r1, self.c1, self.r2, self.c2)

    @property
    def where(self):
        return f"{X.quote_sheet(self.sheet)}!{self.range}"

    @property
    def vertical(self):
        return (self.r2 - self.r1) >= (self.c2 - self.c1)


class Structure:
    def __init__(self, wb):
        self.wb = wb
        self.r1c1 = {}
        self.tokens = {}
        self.blocks = []
        self.block_of = {}
        self.prec = defaultdict(set)
        self.ranges = defaultdict(set)
        self._formula_cells = {}
        self._range_blocks = {}
        self.external = defaultdict(set)
        self.dynamic = defaultdict(list)
        self.lookup_ranges = []
        self.cycles = []
        self.families = []
        self.notes = []
        self._range_cache = {}
        self.chart_refs = set()
        self.chart_values = set()
        self.name_refs = set()


def cell_key(sheet, row, col):
    return (sheet, row, col)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _rectangles(items):
    """items: {(row, col): key}. Greedy rectangles of equal keys."""
    rects = []
    done = set()
    for (row, col) in sorted(items):
        if (row, col) in done:
            continue
        key = items[(row, col)]
        same = lambda r, c: items.get((r, c)) == key and (r, c) not in done
        r2 = row
        while same(r2 + 1, col):
            r2 += 1
        c2 = col
        while same(row, c2 + 1):
            c2 += 1
        if r2 - row >= c2 - col:
            c_end = col
            while all(same(r, c_end + 1) for r in range(row, r2 + 1)):
                c_end += 1
            rect = (row, col, r2, c_end)
        else:
            r_end = row
            while all(same(r_end + 1, c) for c in range(col, c2 + 1)):
                r_end += 1
            rect = (row, col, r_end, c2)
        for r in range(rect[0], rect[2] + 1):
            for c in range(rect[1], rect[3] + 1):
                done.add((r, c))
        rects.append((rect, key))
    return rects


def _filled(sheet, row, col):
    """A gap cell that can stand in for a formula: a formula or a number."""
    cell = sheet.get(row, col)
    if cell is None:
        return False
    return cell.formula is not None or (cell.value is not None and not cell.is_text)


def _merge_with_exceptions(rects, sheet):
    """Join blocks with one R1C1 text that are split only by a few cells (a
    value typed over a formula, a broken copy). The cells between them become
    exceptions of the joined block."""
    by_key = defaultdict(list)
    for rect, key in rects:
        by_key[key].append(rect)
    merged = []
    for key, items in by_key.items():
        items.sort()
        groups = []
        for rect in items:
            joined = False
            for group in groups:
                last = group[-1]
                gap = None
                if (rect[1], rect[3]) == (last[1], last[3]) and rect[0] > last[2]:
                    gap = rect[0] - last[2] - 1
                    gap_cells = [(r, c) for r in range(last[2] + 1, rect[0])
                                 for c in range(rect[1], rect[3] + 1)]
                elif (rect[0], rect[2]) == (last[0], last[2]) and rect[1] > last[3]:
                    gap = rect[1] - last[3] - 1
                    gap_cells = [(r, c) for r in range(rect[0], rect[2] + 1)
                                 for c in range(last[3] + 1, rect[1])]
                if gap is not None and 1 <= gap <= 3 and \
                        all(_filled(sheet, r, c) for r, c in gap_cells):
                    group.append(rect)
                    joined = True
                    break
            if not joined:
                groups.append([rect])
        for group in groups:
            r1 = min(g[0] for g in group)
            c1 = min(g[1] for g in group)
            r2 = max(g[2] for g in group)
            c2 = max(g[3] for g in group)
            size = sum((g[2] - g[0] + 1) * (g[3] - g[1] + 1) for g in group)
            if len(group) > 1 and size < 4:
                for g in group:
                    merged.append((g, key, False))
                continue
            merged.append(((r1, c1, r2, c2), key, len(group) > 1))
    return merged


def build_blocks(st):
    wb = st.wb
    for sheet in wb.sheets:
        formulas, numbers, texts = {}, {}, {}
        for (row, col), cell in sheet.cells.items():
            if cell.formula is not None:
                if cell.ftype in ("dataTable", "array", "array-member"):
                    text = "{=" + cell.formula + "}"
                else:
                    try:
                        text = X.to_r1c1(cell.formula, row, col)
                    except ValueError:
                        text = "=" + cell.formula
                st.r1c1[(sheet.name, row, col)] = text
                formulas[(row, col)] = text
            elif cell.value is None:
                continue
            elif cell.is_text:
                texts[(row, col)] = "text"
            elif cell.vtype == "e":
                numbers[(row, col)] = "number"
            else:
                numbers[(row, col)] = "number"
        for kind, items in (("formula", formulas), ("number", numbers), ("text", texts)):
            rects = _rectangles(items)
            joined = _merge_with_exceptions(rects, sheet) if kind == "formula" else \
                [(rect, key, False) for rect, key in rects]
            for (r1, c1, r2, c2), key, has_gaps in joined:
                block = Block(sheet.name, r1, c1, r2, c2, kind, key)
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        if items.get((r, c)) == key:
                            block.cells.append((r, c))
                        elif has_gaps and sheet.get(r, c) is not None:
                            cell = sheet.get(r, c)
                            if cell.formula is not None or cell.value is not None:
                                block.exceptions.append((r, c))
                if not block.cells:
                    continue
                st.blocks.append(block)
    # Exception cells keep their own small blocks; the joined block holds the
    # regular cells.
    st.blocks.sort(key=lambda b: (wb.sheet(b.sheet).index, b.r1, b.c1))
    for n, block in enumerate(st.blocks, 1):
        block.id = f"B{n:03d}"
        r, c = block.cells[0]
        block.first = (r, c)
        for r, c in block.cells:
            st.block_of[(block.sheet, r, c)] = block


# ---------------------------------------------------------------------------
# Labels and units
# ---------------------------------------------------------------------------

def _text_at(sheet, row, col):
    cell = sheet.get(row, col)
    if cell is not None and cell.formula is None and cell.is_text and cell.value.strip():
        return cell.value.strip()
    return None


def header_above(sheet, row, col, limit=60):
    for r in range(row - 1, max(0, row - limit), -1):
        text = _text_at(sheet, r, col)
        if text:
            return text
    return None


def label_left(sheet, row, col):
    for c in range(col - 1, 0, -1):
        text = _text_at(sheet, row, c)
        if text:
            return text
    return None


def assign_labels(st):
    for block in st.blocks:
        sheet = st.wb.sheet(block.sheet)
        if block.r1 == block.r2 and block.c1 == block.c2:
            label = label_left(sheet, block.r1, block.c1) or \
                header_above(sheet, block.r1, block.c1)
        elif block.vertical:
            label = header_above(sheet, block.r1, block.c1) or \
                label_left(sheet, block.r1, block.c1)
        else:
            label = label_left(sheet, block.r1, block.c1) or \
                header_above(sheet, block.r1, block.c1)
        block.label = label
        block.unit = unit_of(label)
        if block.unit is None:
            r, c = block.first
            cell = sheet.get(r, c)
            if cell is not None and st.wb.is_percent_style(cell.style):
                block.unit = "%"


def cell_label(st, sheet_name, row, col):
    """Label of one cell. Constants (inputs, parameters) take the label on their
    own row first, so a column of inputs gets one label per input."""
    block = st.block_of.get((sheet_name, row, col))
    sheet = st.wb.sheet(sheet_name)
    if block is None or sheet is None:
        return None
    if block.kind != "formula" and len(block.cells) > 1:
        return label_left(sheet, row, col) or header_above(sheet, row, col)
    return block.label


def cell_unit(st, sheet_name, row, col):
    block = st.block_of.get((sheet_name, row, col))
    if block is None:
        return None
    if block.kind != "formula" and len(block.cells) > 1:
        unit = unit_of(cell_label(st, sheet_name, row, col))
        if unit is None:
            cell = st.wb.sheet(sheet_name).get(row, col)
            if cell is not None and st.wb.is_percent_style(cell.style):
                unit = "%"
        return unit
    return block.unit


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def expand(st, sheet_name, r1, c1, r2, c2):
    key = (sheet_name, r1, c1, r2, c2)
    if key in st._range_cache:
        return st._range_cache[key]
    sheet = st.wb.sheet(sheet_name)
    if sheet is None:
        return []
    area = (r2 - r1 + 1) * (c2 - c1 + 1)
    if area <= len(sheet.cells):
        out = [(sheet.name, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)
               if (r, c) in sheet.cells]
    else:
        out = [(sheet.name, r, c) for (r, c) in sheet.cells
               if r1 <= r <= r2 and c1 <= c <= c2]
    if len(out) <= RANGE_CACHE_LIMIT:
        st._range_cache[key] = out
    return out


def add_ref(st, key, sheet_name, r1, c1, r2, c2):
    """Record that the formula at key reads a cell or a range. A range is kept as
    one reference; only the formula cells inside it enter the cell graph (they are
    the only cells that can close a circular reference)."""
    sheet = st.wb.sheet(sheet_name)
    if sheet is None:
        return
    if r1 == r2 and c1 == c2:
        if (r1, c1) in sheet.cells:
            st.prec[key].add((sheet.name, r1, c1))
        return
    bounds = (sheet.name, r1, c1, r2, c2)
    st.ranges[key].add(bounds)
    if bounds not in st._formula_cells:
        st._formula_cells[bounds] = [k for k in expand(st, *bounds)
                                     if sheet.cells[(k[1], k[2])].formula is not None]
    st.prec[key].update(st._formula_cells[bounds])


def precedent_cells(st, key):
    """Every cell a formula reads, ranges expanded."""
    seen = set(st.prec.get(key, ()))
    for bounds in st.ranges.get(key, ()):
        seen.update(expand(st, *bounds))
    seen.discard(key)
    return seen


def range_blocks(st, bounds):
    if bounds not in st._range_blocks:
        st._range_blocks[bounds] = {st.block_of[k] for k in expand(st, *bounds)
                                    if k in st.block_of}
    return st._range_blocks[bounds]


def resolve_struct(st, text, sheet, row, col):
    """Bounds of a structured reference (Table[Column], [@Column], ...)."""
    match = re.match(r"^([A-Za-z_\\][\w.]*)?\[(.*)\]$", text, re.S)
    if not match:
        return []
    name, inner = match.group(1), match.group(2)
    table_sheet, table = (st.wb.table(name) if name else (None, None))
    if table is None:
        for item in sheet.tables:
            r1, c1, r2, c2 = X.parse_range(item["ref"])
            if r1 <= row <= r2 and c1 <= col <= c2:
                table_sheet, table = sheet, item
    if table is None:
        return []
    r1, c1, r2, c2 = X.parse_range(table["ref"])
    data_r1 = r1 + table["headerRows"]
    data_r2 = r2 - table["totalsRows"]
    names = [c["name"].lower() for c in table["columns"]]
    specs = re.findall(r"\[([^\[\]]*)\]", "[" + inner + "]") if "[" in inner else [inner]
    cols, rows = [], (data_r1, data_r2)
    this_row = inner.startswith("@") or any(s.lower() == "#this row" for s in specs)
    for spec in specs:
        spec = spec.lstrip("@").strip()
        low = spec.lower()
        if low == "#all":
            rows = (r1, r2)
        elif low == "#headers":
            rows = (r1, r1)
        elif low == "#totals":
            rows = (r2, r2)
        elif low in ("#data", "#this row", ""):
            continue
        else:
            clean = re.sub(r"'(.)", r"\1", spec).lower()
            if clean in names:
                cols.append(c1 + names.index(clean))
    if ":" in inner and len(cols) == 2:
        cols = list(range(min(cols), max(cols) + 1))
    if not cols:
        cols = list(range(c1, c2 + 1))
    if this_row:
        rows = (row, row)
    return [(table_sheet.name, rows[0], min(cols), rows[1], max(cols))]


def _indirect_target(st, sheet, tokens, index):
    """Resolve INDIRECT("..."&A1&"...") from stored values; None when the text
    cannot be built from literals and single cells."""
    args = X.function_args(tokens, index)
    if not args or not args[0]:
        return None
    if len(args) > 1 and args[1] and args[1][0].kind == "bool" and not args[1][0].value:
        return None
    parts = []
    for tok in args[0]:
        if tok.kind == "str":
            parts.append(tok.text[1:-1].replace('""', '"'))
        elif tok.kind == "op" and tok.text == "&":
            continue
        elif tok.kind == "ref" and ":" not in tok.area:
            ref_sheet, book = X.sheet_of(tok.sheet)
            if book:
                return None
            target = st.wb.sheet(ref_sheet) if ref_sheet else sheet
            if target is None:
                return None
            r, c, _, _ = X.parse_cell(tok.area.replace("$", ""))
            value = target.value(r, c)
            if value is None:
                return None
            if isinstance(value, float):
                value = f"{value:g}"
            parts.append(str(value))
        else:
            return None
    text = "".join(parts)
    refs, names, structs, funcs = X.references(text)
    if len(refs) != 1 or names or structs or funcs:
        return None
    return refs[0]


def resolve_dependencies(st):
    wb = st.wb
    for sheet in wb.sheets:
        for (row, col), cell in sheet.cells.items():
            if cell.formula is None:
                continue
            key = (sheet.name, row, col)
            if cell.ftype == "dataTable":
                _data_table_precedents(st, sheet, key)
                continue
            tokens = X.tokenize(cell.formula)
            st.tokens[key] = tokens
            refs, names, structs, funcs = X.references(cell.formula, tokens)
            block = st.block_of.get(key)
            if block is not None:
                block.functions.update(funcs)
            for ref in refs:
                if ref.book:
                    st.external[key].add(ref.book)
                    continue
                if ref.kind == "error":
                    st.dynamic[key].append("#REF! in formula")
                    continue
                add_ref(st, key, ref.sheet or sheet.name, ref.r1, ref.c1, ref.r2, ref.c2)
            for name in names:
                item = wb.find_name(name, sheet.index)
                if item is None:
                    continue
                st.name_refs.add(item.name)
                for ref in X.defined_name_ranges(wb, item):
                    if ref.book:
                        st.external[key].add(ref.book)
                    elif ref.kind != "error":
                        add_ref(st, key, ref.sheet or sheet.name, ref.r1, ref.c1, ref.r2,
                                ref.c2)
                if not X.defined_name_ranges(wb, item) and re.search(r"[A-Z]+\(", item.text):
                    st.dynamic[key].append(f"name {item.name} is a formula")
            for text in structs:
                for bounds in resolve_struct(st, text, sheet, row, col):
                    add_ref(st, key, *bounds)
            for i, tok in enumerate(tokens):
                if tok.kind != "func":
                    continue
                if tok.value == "INDIRECT":
                    target = _indirect_target(st, sheet, tokens, i)
                    if target is None:
                        st.dynamic[key].append("INDIRECT (target unknown)")
                    else:
                        st.dynamic[key].append(f"INDIRECT resolved from stored values to "
                                               f"{target.text}")
                        add_ref(st, key, target.sheet or sheet.name, target.r1, target.c1,
                                target.r2, target.c2)
                elif tok.value == "OFFSET":
                    st.dynamic[key].append("OFFSET (range depends on values)")
            st.prec[key].discard(key)
            _lookup_ranges(st, sheet, key, tokens)
    for sheet in wb.sheets:
        for chart in sheet.charts:
            for series in chart["series"]:
                for part, text in series.items():
                    refs, _, _, _ = X.references(text)
                    for ref in refs:
                        if ref.kind != "error" and not ref.book:
                            cells = expand(st, ref.sheet or sheet.name,
                                           ref.r1, ref.c1, ref.r2, ref.c2)
                            st.chart_refs.update(cells)
                            if part in ("val", "yVal", "bubbleSize"):
                                st.chart_values.update(cells)


def _data_table_precedents(st, sheet, key):
    _, row, col = key
    for table in st.wb.data_tables:
        if table["sheet"] != sheet.name:
            continue
        r1, c1, r2, c2 = X.parse_range(table["ref"])
        if not (r1 <= row <= r2 and c1 <= col <= c2):
            continue
        for ref in (table["r1"], table["r2"]):
            if ref:
                rr, cc, _, _ = X.parse_cell(ref.replace("$", ""))
                add_ref(st, key, sheet.name, rr, cc, rr, cc)
        add_ref(st, key, sheet.name, r1, c1 - 1, r2, c1 - 1)
        add_ref(st, key, sheet.name, r1 - 1, c1, r1 - 1, c2)
        st.prec[key].discard(key)


def _lookup_ranges(st, sheet, key, tokens):
    ctx = arg_context(tokens)
    for i, tok in enumerate(tokens):
        where = ctx[i]
        if not where or where[0] not in LOOKUP_TABLE_ARG or where[1] != LOOKUP_TABLE_ARG[where[0]]:
            continue
        bounds = None
        if tok.kind == "ref" and tok.area.upper() != "#REF!":
            ref_sheet, book = X.sheet_of(tok.sheet)
            if book:
                continue
            bounds = (ref_sheet or sheet.name,) + X.parse_range(tok.area)
        elif tok.kind == "name":
            item = st.wb.find_name(tok.text, sheet.index)
            refs = X.defined_name_ranges(st.wb, item) if item else []
            if len(refs) == 1 and not refs[0].book and refs[0].kind != "error":
                ref = refs[0]
                bounds = (ref.sheet or sheet.name, ref.r1, ref.c1, ref.r2, ref.c2)
        if bounds:
            st.lookup_ranges.append((key, where[0], bounds))


# ---------------------------------------------------------------------------
# Block graph, roles, cycles
# ---------------------------------------------------------------------------

def block_graph(st):
    for key in set(st.prec) | set(st.ranges):
        block = st.block_of.get(key)
        if block is None:
            continue
        others = {st.block_of[p] for p in st.prec.get(key, ()) if p in st.block_of}
        for bounds in st.ranges.get(key, ()):
            others.update(range_blocks(st, bounds))
        for other in others:
            if other is not block:
                block.precedents.add(other.id)
                other.dependents.add(block.id)
        if key in st.external:
            block.external.update(st.external[key])
        if key in st.dynamic:
            block.dynamic.update(st.dynamic[key])


def assign_roles(st):
    wb = st.wb
    lookup_cells = set()
    for bounds in {b for _, _, b in st.lookup_ranges}:
        lookup_cells.update(expand(st, *bounds))
    validated = set()
    for sheet in wb.sheets:
        for dv in sheet.validations:
            for r1, c1, r2, c2 in X.iter_sqref(dv["sqref"]):
                for (r, c) in sheet.cells:
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        validated.add((sheet.name, r, c))
    named = set()
    for item in wb.names:
        for ref in X.defined_name_ranges(wb, item):
            if not ref.book and ref.kind != "error" and ref.size <= 10000:
                named.update(expand(st, ref.sheet or "", ref.r1, ref.c1, ref.r2, ref.c2))
    referenced = set()
    for precs in st.prec.values():
        referenced.update(precs)
    for bounds in {b for items in st.ranges.values() for b in items}:
        referenced.update(expand(st, *bounds))
    exception_cells = set()
    for block in st.blocks:
        for r, c in block.exceptions:
            exception_cells.add((block.sheet, r, c))
    for block in st.blocks:
        keys = [(block.sheet, r, c) for r, c in block.cells]
        sheet = wb.sheet(block.sheet)
        in_lookup = any(k in lookup_cells for k in keys)
        is_ref = any(k in referenced for k in keys)
        if block.kind == "text":
            if in_lookup:
                block.role = "lookup"
            elif is_ref and (any(k in validated for k in keys) or
                             INPUT_SHEET.search(block.sheet) or
                             any(k in named for k in keys)):
                block.role = "input"
            elif is_ref:
                block.role = "parameter"
            else:
                block.role = "label"
        elif block.kind == "number":
            rows = block.r2 - block.r1 + 1
            if keys and all(k in exception_cells for k in keys):
                block.role = "override"
            elif in_lookup:
                block.role = "lookup"
            elif len(block.cells) >= 10 and rows >= 2:
                block.role = "raw data"
            elif not is_ref:
                block.role = "unreferenced value"
            elif any(k in validated for k in keys) or any(k in named for k in keys) or \
                    INPUT_SHEET.search(block.sheet):
                block.role = "input"
            else:
                block.role = "parameter"
        else:
            first = sheet.get(*block.first)
            if block.dependents or any(k in st.chart_refs for k in keys):
                block.role = "calculation" if block.dependents else "output"
            elif first is not None and first.ftype == "dataTable":
                block.role = "output"
            elif sheet.state != "visible":
                block.role = "terminal"
            elif OUTPUT_SHEET.search(block.sheet):
                block.role = "output"
            elif first is not None and wb.is_date_style(first.style):
                block.role = "output"
            elif (block.r1, block.c1) == (block.r2, block.c2) and (
                    (block.label and OUTPUT_LABEL.search(block.label)) or
                    block.functions & AGGREGATES):
                block.role = "output"
            else:
                block.role = "terminal"


def find_cycles(st):
    """Tarjan's strongly connected components over formula cells (iterative)."""
    graph = st.prec
    index, low, on_stack, stack = {}, {}, set(), []
    counter = [0]
    for start in list(graph):
        if start in index:
            continue
        work = [(start, iter(graph.get(start, ())))]
        index[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in graph:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(graph.get(nxt, ()))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    item = stack.pop()
                    on_stack.discard(item)
                    comp.append(item)
                    if item == node:
                        break
                if len(comp) > 1 or node in graph.get(node, ()):
                    st.cycles.append(sorted(comp))


# ---------------------------------------------------------------------------
# Template copies
# ---------------------------------------------------------------------------

def find_templates(st, threshold=0.6):
    wb = st.wb
    sigs = {}
    for sheet in wb.sheets:
        sig = {(r, c): st.r1c1[(sheet.name, r, c)] for (r, c), cell in sheet.cells.items()
               if cell.formula is not None and (sheet.name, r, c) in st.r1c1}
        if len(sig) >= 5:
            sigs[sheet.name] = sig
    names = list(sigs)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    sims = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa, sb = sigs[a], sigs[b]
            union = set(sa) | set(sb)
            same = sum(1 for p in set(sa) & set(sb) if sa[p] == sb[p])
            sim = same / len(union) if union else 0.0
            sims[(a, b)] = sim
            if sim >= threshold:
                parent[find(a)] = find(b)
    groups = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda n: wb.sheet(n).index)
        positions = Counter()
        for n in members:
            positions.update(sigs[n].keys())
        drift = []
        for pos, count in positions.items():
            if count < 2:
                continue
            texts = Counter(sigs[n][pos] for n in members if pos in sigs[n])
            majority, votes = texts.most_common(1)[0]
            for n in members:
                sheet = wb.sheet(n)
                cell = sheet.get(*pos)
                if pos in sigs[n] and sigs[n][pos] != majority and votes > 1:
                    drift.append((n, pos, "formula differs", sigs[n][pos], majority))
                elif pos not in sigs[n] and count >= max(2, len(members) - 1) and \
                        cell is not None and cell.value is not None:
                    drift.append((n, pos, "value instead of formula", None, majority))
        grouped = defaultdict(list)
        for n, pos, what, text, majority in drift:
            grouped[(n, what, text, majority)].append(pos)
        items = []
        for (n, what, text, majority), cells in sorted(grouped.items(),
                                                        key=lambda kv: (kv[0][0], min(kv[1]))):
            rows = [r for r, _ in cells]
            cols = [c for _, c in cells]
            items.append({"sheet": n, "range": X.range_text(min(rows), min(cols), max(rows),
                                                            max(cols)),
                          "cells": len(cells), "what": what, "r1c1": text,
                          "majority": majority})
        sim = min(sims.get((a, b), sims.get((b, a), 0)) for i, a in enumerate(members)
                  for b in members[i + 1:])
        st.families.append({"sheets": members, "similarity": round(sim, 3), "drift": items})


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def analyze(wb):
    st = Structure(wb)
    build_blocks(st)
    assign_labels(st)
    resolve_dependencies(st)
    block_graph(st)
    assign_roles(st)
    find_cycles(st)
    find_templates(st)
    return st


def to_json(st):
    wb = st.wb
    blocks = []
    for b in st.blocks:
        sheet = wb.sheet(b.sheet)
        r, c = b.first
        cell = sheet.get(r, c)
        item = {"id": b.id, "sheet": b.sheet, "range": b.range, "kind": b.kind, "role": b.role,
                "cells": len(b.cells), "label": b.label, "unit": b.unit}
        if b.kind == "formula":
            item["formula"] = "=" + (cell.formula or "")
            item["r1c1"] = b.key
            item["functions"] = sorted(b.functions)
        elif b.kind == "number" and len(b.cells) == 1:
            item["value"] = cell.value
        elif b.kind == "text" and len(b.cells) == 1:
            item["value"] = cell.value
        if (b.kind != "formula" and b.role in ("input", "parameter", "override") and
                len(b.cells) <= 200):
            item["inputCells"] = []
            for r, c in b.cells:
                other = sheet.get(r, c)
                item["inputCells"].append({
                    "cell": X.addr(r, c), "label": cell_label(st, b.sheet, r, c),
                    "unit": cell_unit(st, b.sheet, r, c), "value": other.value,
                    "date": bool(other is not None and wb.is_date_style(other.style))})
        if b.kind == "formula" and b.external and not (
                b.precedents or st.prec.get((b.sheet,) + b.first) or
                st.ranges.get((b.sheet,) + b.first)):
            item["externalOnly"] = True
        if b.exceptions:
            item["exceptions"] = []
            for er, ec in b.exceptions:
                other = sheet.get(er, ec)
                item["exceptions"].append({
                    "cell": X.addr(er, ec),
                    "kind": "formula" if other.formula is not None else "value",
                    "formula": None if other.formula is None else "=" + other.formula,
                    "value": other.value})
        item["precedents"] = sorted(b.precedents)
        item["dependents"] = sorted(b.dependents)
        if b.external:
            item["external"] = sorted(b.external)
        if b.dynamic:
            item["dynamic"] = sorted(b.dynamic)
        blocks.append(item)
    sheet_flow = Counter()
    by_id = {b.id: b for b in st.blocks}
    for b in st.blocks:
        for pid in b.precedents:
            src = by_id[pid].sheet
            if src != b.sheet:
                sheet_flow[(src, b.sheet)] += 1
    roles = Counter(b.role for b in st.blocks)
    return {
        "workbook": Path(wb.path).name,
        "summary": {"blocks": len(st.blocks), "roles": dict(roles),
                    "formulaCells": len(st.r1c1), "cycles": len(st.cycles),
                    "templateFamilies": len(st.families)},
        "sheets": [{"name": s.name, "state": s.state, "kind": s.kind,
                    "blocks": sum(1 for b in st.blocks if b.sheet == s.name)}
                   for s in wb.sheets],
        "blocks": blocks,
        "sheetFlow": [{"from": a, "to": b, "links": n} for (a, b), n in sorted(sheet_flow.items())],
        "cycles": [{"cells": [f"{X.quote_sheet(s)}!{X.addr(r, c)}" for s, r, c in comp][:50],
                    "size": len(comp),
                    "blocks": sorted({st.block_of[k].id for k in comp if k in st.block_of})}
                   for comp in st.cycles],
        "templateFamilies": st.families,
        "lookups": [{"cell": f"{X.quote_sheet(k[0])}!{X.addr(k[1], k[2])}", "function": f,
                     "range": f"{X.quote_sheet(b[0])}!{X.range_text(*b[1:])}"}
                    for k, f, b in st.lookup_ranges][:500],
        "notes": st.notes,
    }


def mermaid(st, limit=150):
    """Mermaid flowchart: one subgraph per sheet, blocks as nodes. Labels and
    raw constants are left out to keep the diagram readable."""
    keep = [b for b in st.blocks if b.role not in ("label", "unreferenced value")]
    keep = keep[:limit]
    ids = {b.id for b in keep}
    lines = ["flowchart LR"]
    for sheet in st.wb.sheets:
        members = [b for b in keep if b.sheet == sheet.name]
        if not members:
            continue
        sid = re.sub(r"\W", "_", sheet.name)
        lines.append(f'  subgraph {sid}["{sheet.name}"]')
        for b in members:
            label = (b.label or "").replace('"', "'")[:40]
            lines.append(f'    {b.id}["{b.id} {b.range}<br/>{label}<br/><i>{b.role}</i>"]')
        lines.append("  end")
    for b in keep:
        for pid in sorted(b.precedents):
            if pid in ids:
                lines.append(f"  {pid} --> {b.id}")
    if len(keep) < len([b for b in st.blocks if b.role not in ("label", "unreferenced value")]):
        lines.append(f"  %% diagram limited to the first {limit} blocks")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("workbook")
    parser.add_argument("--out", required=True, help="ingest folder for the results")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wb = X.load(args.workbook)
    st = analyze(wb)
    data = to_json(st)
    (out / "structure.json").write_text(json.dumps(data, indent=1, default=str),
                                        encoding="utf-8")
    (out / "dependencies.mmd").write_text(mermaid(st), encoding="utf-8")
    s = data["summary"]
    print(f"{s['blocks']} blocks, {s['formulaCells']} formula cells, {s['cycles']} circular "
          f"groups, {s['templateFamilies']} template families -> {out / 'structure.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
