"""Read .xlsx and .xlsm workbooks straight from their zip XML, without Excel.

The other scripts of this skill import this module. It reads every cell's formula
and stored (cached) value, expands shared formulas, and lists named ranges,
tables, data validation, conditional formats, hidden sheets, rows and columns,
comments, charts, pivots, external links, form controls, connections, VBA
presence, array formulas and what-if data tables.

Nothing is executed: macros never run and external links are never updated,
because the file is read as XML. Standard library only.

Formula helpers:
    tokenize(formula)            tokens with kinds (ref, name, func, num, ...)
    to_r1c1(formula, row, col)   relative R1C1 text, equal for filled-down copies
    shift(formula, drow, dcol)   move relative references (shared formulas)
    references(formula)          the cell and range references in a formula
"""

import functools
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_ROW = 1048576
MAX_COL = 16384

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "x14": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main",
    "xm": "http://schemas.microsoft.com/office/excel/2006/main",
}
M = "{%s}" % NS["m"]
R_ID = "{%s}id" % NS["r"]

ERROR_VALUES = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A",
                "#GETTING_DATA", "#SPILL!", "#CALC!", "#FIELD!", "#BLOCKED!",
                "#UNKNOWN!", "#BUSY!", "#CONNECT!", "#PYTHON!", "#EXTERNAL!")

# Built-in number formats that show dates, times or percentages.
DATE_FORMAT_IDS = set(range(14, 23)) | {45, 46, 47}
PERCENT_FORMAT_IDS = {9, 10}


# ---------------------------------------------------------------------------
# Cell addresses
# ---------------------------------------------------------------------------

def col_to_num(letters):
    """'A' -> 1, 'AB' -> 28."""
    num = 0
    for ch in letters.upper():
        num = num * 26 + ord(ch) - 64
    return num


def num_to_col(num):
    """1 -> 'A', 28 -> 'AB'."""
    letters = ""
    while num:
        num, rem = divmod(num - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def addr(row, col):
    return f"{num_to_col(col)}{row}"


_CELL_PARTS = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$")


def parse_cell(text):
    """'$B5' -> (row, col, row_abs, col_abs)."""
    match = _CELL_PARTS.match(text)
    if not match:
        raise ValueError(f"not a cell reference: {text}")
    col_abs, letters, row_abs, digits = match.groups()
    return int(digits), col_to_num(letters), bool(row_abs), bool(col_abs)


def parse_range(text):
    """'A1:C5', 'B:B', '3:4' or 'A1' -> (r1, c1, r2, c2); whole rows and columns
    use the sheet limits."""
    text = text.replace("$", "")
    parts = text.split(":")
    if len(parts) == 1:
        row, col, _, _ = parse_cell(parts[0])
        return row, col, row, col
    first, last = parts[0], parts[1]
    if first.isalpha() and last.isalpha():
        return 1, col_to_num(first), MAX_ROW, col_to_num(last)
    if first.isdigit() and last.isdigit():
        return int(first), 1, int(last), MAX_COL
    r1, c1, _, _ = parse_cell(first)
    r2, c2, _, _ = parse_cell(last)
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def range_text(r1, c1, r2, c2):
    if (r1, c1) == (r2, c2):
        return addr(r1, c1)
    return f"{addr(r1, c1)}:{addr(r2, c2)}"


def iter_sqref(sqref):
    """Yield (r1, c1, r2, c2) for each area of a space-separated sqref."""
    for part in (sqref or "").split():
        try:
            yield parse_range(part)
        except ValueError:
            continue


def quote_sheet(name):
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name) and not re.fullmatch(
            r"[A-Za-z]{1,3}\d+", name):
        return name
    return "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Formula tokens
# ---------------------------------------------------------------------------

_SHEET = (r"(?:'(?:[^']|'')+'"
          r"|\[\d+\](?:[^\s!'\"(),;:+\-*/^&=<>{}\[\]]+)?"
          r"|[A-Za-z_\u00a1-\uffff][\w.\u00a1-\uffff]*"
          r"(?::[A-Za-z_\u00a1-\uffff][\w.\u00a1-\uffff]*)?)!")
_CELL = r"\$?[A-Za-z]{1,3}\$?\d{1,7}"
_AREA = (rf"(?:{_CELL}(?::{_CELL})?|\$?[A-Za-z]{{1,3}}:\$?[A-Za-z]{{1,3}}"
         r"|\$?\d{1,7}:\$?\d{1,7}|\#REF!)")
_ERRORS = "|".join(re.escape(e) for e in ERROR_VALUES)

TOKEN_RE = re.compile(
    rf"""
    (?P<str>"(?:[^"]|"")*")
   |(?P<ref>(?P<sheet>{_SHEET})?(?P<area>{_AREA})(?![\w(.!\[]))
   |(?P<err>{_ERRORS})
   |(?P<struct>(?:[A-Za-z_\\][\w.]*)?\[(?:[^\[\]]|\[(?:[^\[\]']|'.)*\])*\])
   |(?P<func>[A-Za-z_][\w.]*)(?=\()
   |(?P<name>[A-Za-z_\\\u00a1-\uffff][\w.?\\\u00a1-\uffff]*)
   |(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
   |(?P<op><>|<=|>=|[-+*/^&=<>%@\#])
   |(?P<sep>[,;])
   |(?P<open>[({{])
   |(?P<close>[)}}])
   |(?P<ws>\s+)
   |(?P<other>.)
    """,
    re.X | re.S)


class Token:
    __slots__ = ("kind", "text", "start", "sheet", "area", "value")

    def __init__(self, kind, text, start, sheet=None, area=None, value=None):
        self.kind, self.text, self.start = kind, text, start
        self.sheet, self.area, self.value = sheet, area, value

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r})"


def tokenize(formula):
    """Split a formula (with or without the leading '=') into tokens. The list is
    cached and shared: treat it as read-only."""
    if formula.startswith("="):
        formula = formula[1:]
    return _tokenize(formula)


@functools.lru_cache(maxsize=65536)
def _tokenize(formula):
    tokens = []
    for match in TOKEN_RE.finditer(formula):
        kind = match.lastgroup
        text = match.group(0)
        if kind in ("sheet", "area"):
            kind = "ref"
        if match.group("ref") is not None:
            tokens.append(Token("ref", text, match.start(), match.group("sheet"),
                                match.group("area")))
        elif kind == "name" and text.upper() in ("TRUE", "FALSE"):
            tokens.append(Token("bool", text, match.start(),
                                value=text.upper() == "TRUE"))
        elif kind == "num":
            value = float(text)
            end = match.end()
            if end < len(formula) and formula[end] == "%":
                value /= 100.0
            tokens.append(Token("num", text, match.start(), value=value))
        elif kind == "func":
            tokens.append(Token("func", text, match.start(),
                                value=strip_prefix(text).upper()))
        else:
            tokens.append(Token(kind, text, match.start()))
    return tuple(tokens)


def strip_prefix(name):
    for prefix in ("_xlfn._xlws.", "_xlfn.", "_xlws.", "_xll."):
        if name.lower().startswith(prefix.lower()):
            return name[len(prefix):]
    return name


def sheet_of(sheet_text):
    """Return (sheet name, external book index or None) for a token prefix."""
    if not sheet_text:
        return None, None
    text = sheet_text[:-1]
    if text.startswith("'") and text.endswith("'"):
        text = text[1:-1].replace("''", "'")
    book = None
    match = re.match(r"^\[(\d+)\](.*)$", text)
    if match:
        book, text = int(match.group(1)), match.group(2)
    return text, book


def _cell_r1c1(cell, row, col):
    r, c, r_abs, c_abs = parse_cell(cell)
    return _part("R", r, row, r_abs) + _part("C", c, col, c_abs)


def _part(letter, value, base, absolute):
    if absolute:
        return f"{letter}{value}"
    off = value - base
    return letter if off == 0 else f"{letter}[{off}]"


def area_to_r1c1(area, row, col):
    if area.upper() == "#REF!":
        return "#REF!"
    a, _, b = area.partition(":")
    if not b:
        return _cell_r1c1(a, row, col)
    if a.replace("$", "").isalpha():
        return (_part("C", col_to_num(a.replace("$", "")), col, a.startswith("$")) + ":" +
                _part("C", col_to_num(b.replace("$", "")), col, b.startswith("$")))
    if a.replace("$", "").isdigit():
        return (_part("R", int(a.replace("$", "")), row, a.startswith("$")) + ":" +
                _part("R", int(b.replace("$", "")), row, b.startswith("$")))
    return _cell_r1c1(a, row, col) + ":" + _cell_r1c1(b, row, col)


def to_r1c1(formula, row, col):
    """Formula text in relative R1C1 form. Copies of one formula filled down or
    across give the same text, so equal text means one block."""
    out = []
    for tok in tokenize(formula):
        if tok.kind == "ref":
            out.append((tok.sheet or "") + area_to_r1c1(tok.area, row, col))
        elif tok.kind in ("func", "bool"):
            out.append(tok.text.upper())
        elif tok.kind == "ws":
            continue
        else:
            out.append(tok.text)
    return "=" + "".join(out)


def _shift_cell(cell, drow, dcol):
    r, c, r_abs, c_abs = parse_cell(cell)
    if not r_abs:
        r += drow
    if not c_abs:
        c += dcol
    if not (1 <= r <= MAX_ROW and 1 <= c <= MAX_COL):
        return None
    return ("$" if c_abs else "") + num_to_col(c) + ("$" if r_abs else "") + str(r)


def shift_area(area, drow, dcol):
    if area.upper() == "#REF!":
        return area
    a, _, b = area.partition(":")
    if b and a.replace("$", "").isalpha():
        out = []
        for part in (a, b):
            if part.startswith("$"):
                out.append(part)
            else:
                c = col_to_num(part) + dcol
                if not 1 <= c <= MAX_COL:
                    return "#REF!"
                out.append(num_to_col(c))
        return ":".join(out)
    if b and a.replace("$", "").isdigit():
        out = []
        for part in (a, b):
            if part.startswith("$"):
                out.append(part)
            else:
                r = int(part) + drow
                if not 1 <= r <= MAX_ROW:
                    return "#REF!"
                out.append(str(r))
        return ":".join(out)
    parts = [_shift_cell(p, drow, dcol) for p in ([a, b] if b else [a])]
    if None in parts:
        return "#REF!"
    return ":".join(parts)


def shift(formula, drow, dcol):
    """Move every relative reference by (drow, dcol), as Excel does when it
    copies a formula. Used to expand shared formulas."""
    if formula.startswith("="):
        formula = formula[1:]
    out = []
    for tok in tokenize(formula):
        if tok.kind == "ref":
            out.append((tok.sheet or "") + shift_area(tok.area, drow, dcol))
        else:
            out.append(tok.text)
    return "".join(out)


class Ref:
    """One reference found in a formula."""
    __slots__ = ("sheet", "book", "r1", "c1", "r2", "c2", "text", "kind")

    def __init__(self, sheet, book, bounds, text, kind):
        self.sheet, self.book, self.text, self.kind = sheet, book, text, kind
        self.r1, self.c1, self.r2, self.c2 = bounds

    @property
    def size(self):
        return (self.r2 - self.r1 + 1) * (self.c2 - self.c1 + 1)

    def __repr__(self):
        return f"Ref({self.sheet}!{self.text})"


def references(formula, tokens=None):
    """Return (refs, names, structured, functions) for a formula. Sheet is None
    for references to the formula's own sheet."""
    refs, names, structs, funcs = [], [], [], []
    for tok in tokens if tokens is not None else tokenize(formula):
        if tok.kind == "ref":
            sheet, book = sheet_of(tok.sheet)
            if tok.area.upper() == "#REF!":
                refs.append(Ref(sheet, book, (0, 0, 0, 0), tok.text, "error"))
                continue
            bounds = parse_range(tok.area)
            kind = "cell" if ":" not in tok.area else "range"
            refs.append(Ref(sheet, book, bounds, tok.text, kind))
        elif tok.kind == "name":
            names.append(tok.text)
        elif tok.kind == "struct":
            structs.append(tok.text)
        elif tok.kind == "func":
            funcs.append(tok.value)
    return refs, names, structs, funcs


def function_args(tokens, start_index):
    """Return the argument token lists of the function whose 'func' token is at
    tokens[start_index]."""
    args, current, depth = [], [], 0
    i = start_index + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "open":
            depth += 1
            if depth > 1:
                current.append(tok)
        elif tok.kind == "close":
            depth -= 1
            if depth == 0:
                args.append(current)
                return args
            current.append(tok)
        elif tok.kind == "sep" and depth == 1:
            args.append(current)
            current = []
        elif tok.kind != "ws":
            current.append(tok)
        i += 1
    args.append(current)
    return args


# ---------------------------------------------------------------------------
# Workbook model
# ---------------------------------------------------------------------------

class Cell:
    """value: float, str, bool, error text or None. formula: text without '='.
    ftype: None, 'normal', 'shared', 'array', 'array-member', 'dataTable'."""
    __slots__ = ("row", "col", "value", "vtype", "formula", "ftype", "style", "fref")

    def __init__(self, row, col):
        self.row, self.col = row, col
        self.value = self.vtype = self.formula = self.ftype = self.fref = None
        self.style = 0

    @property
    def address(self):
        return addr(self.row, self.col)

    @property
    def is_error(self):
        return self.vtype == "e"

    @property
    def is_number(self):
        return isinstance(self.value, float) and self.vtype != "e"

    @property
    def is_text(self):
        return isinstance(self.value, str) and self.vtype in ("s", "str", "inlineStr")


class Sheet:
    def __init__(self, name, index, state, path, kind="worksheet"):
        self.name, self.index, self.state, self.path, self.kind = name, index, state, path, kind
        self.cells = {}
        self.merged = []
        self.hidden_rows = set()
        self.hidden_cols = set()
        self.validations = []
        self.conditional_formats = []
        self.tables = []
        self.charts = []
        self.pivots = []
        self.comments = {}
        self.controls = []
        self.protected = False
        self.has_drawing_images = False

    def get(self, row, col):
        return self.cells.get((row, col))

    def value(self, row, col):
        cell = self.cells.get((row, col))
        return None if cell is None else cell.value


class DefinedName:
    __slots__ = ("name", "scope", "hidden", "text")

    def __init__(self, name, scope, hidden, text):
        self.name, self.scope, self.hidden, self.text = name, scope, hidden, text


class Workbook:
    def __init__(self, path):
        self.path = path
        self.sheets = []
        self.names = []
        self.calc = {}
        self.date1904 = False
        self.external_links = []
        self.data_tables = []
        self.array_formulas = []
        self.connections = []
        self.vba = False
        self.macrosheets = []
        self.custom_xml_mashup = False
        self.query_tables = []
        self.pivot_caches = {}
        self.num_formats = {}
        self.cell_formats = []
        self.notes = []
        self.protected = False
        self._name_index = {}
        self._name_count = -1
        self._name_refs = {}

    def sheet(self, name):
        for sheet in self.sheets:
            if sheet.name.lower() == name.lower():
                return sheet
        return None

    def number_format(self, style):
        if style is None or style >= len(self.cell_formats):
            return "General"
        fmt_id = self.cell_formats[style]
        if fmt_id in self.num_formats:
            return self.num_formats[fmt_id]
        if fmt_id in DATE_FORMAT_IDS:
            return "date"
        if fmt_id in PERCENT_FORMAT_IDS:
            return "0%"
        return "General"

    def is_date_style(self, style):
        fmt = self.number_format(style)
        if fmt == "date":
            return True
        clean = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", fmt).lower()
        return bool(re.search(r"[dmy]", clean)) and "general" not in clean

    def is_percent_style(self, style):
        return "%" in self.number_format(style)

    def find_name(self, name, sheet_index=None):
        """Defined name lookup: sheet scope first, then workbook scope."""
        if self._name_count != len(self.names):
            self._name_index = {(item.name.lower(), item.scope): item for item in self.names}
            self._name_count = len(self.names)
        low = name.lower()
        return (self._name_index.get((low, sheet_index)) or
                self._name_index.get((low, None)))

    def table(self, name):
        for sheet in self.sheets:
            for table in sheet.tables:
                if table["name"].lower() == name.lower():
                    return sheet, table
        return None, None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _rels(zf, part):
    """Relationships of a part: {rId: (type suffix, absolute target, external)}."""
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    out = {}
    if rels_path not in zf.namelist():
        return out
    root = ET.fromstring(zf.read(rels_path))
    for rel in root.findall("pr:Relationship", NS):
        target = rel.get("Target", "")
        external = rel.get("TargetMode") == "External"
        if not external:
            if target.startswith("/"):
                target = target[1:]
            else:
                target = posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], target, external)
    return out


def _text(elem):
    """All text below an element (shared strings with rich text runs)."""
    if elem is None:
        return ""
    parts = []
    for node in elem.iter():
        if node.tag in (M + "t",) and node.text:
            parts.append(node.text)
        elif node.tag == M + "rPh":
            continue
    return "".join(parts)


def _shared_strings(zf, path):
    if not path or path not in zf.namelist():
        return []
    out = []
    with zf.open(path) as fh:
        for event, elem in ET.iterparse(fh):
            if elem.tag == M + "si":
                # phonetic runs are not part of the value
                for ph in elem.findall(M + "rPh"):
                    elem.remove(ph)
                out.append(_text(elem))
                elem.clear()
    return out


def _styles(zf, path, wb):
    if not path or path not in zf.namelist():
        return
    root = ET.fromstring(zf.read(path))
    for fmt in root.findall("m:numFmts/m:numFmt", NS):
        wb.num_formats[int(fmt.get("numFmtId"))] = fmt.get("formatCode", "")
    for xf in root.findall("m:cellXfs/m:xf", NS):
        wb.cell_formats.append(int(xf.get("numFmtId", "0")))


def _parse_value(raw, vtype, inline, strings):
    if vtype == "inlineStr":
        return inline
    if raw is None:
        return None
    if vtype == "s":
        try:
            return strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if vtype in ("str", "e", "d"):
        return raw
    if vtype == "b":
        return raw.strip() in ("1", "true")
    try:
        return float(raw)
    except ValueError:
        return raw


def _read_sheet(zf, wb, sheet, strings):
    shared = {}
    pending = []
    array_members = []
    with zf.open(sheet.path) as fh:
        _parse_sheet_xml(fh, wb, sheet, strings, shared, pending, array_members)
    _finish_sheet(wb, sheet, shared, pending, array_members)


def _parse_sheet_xml(fh, wb, sheet, strings, shared, pending, array_members):
    for event, elem in ET.iterparse(fh):
        tag = elem.tag
        if tag == M + "c":
            ref = elem.get("r")
            row, col, _, _ = parse_cell(ref)
            cell = Cell(row, col)
            cell.vtype = elem.get("t", "n")
            cell.style = int(elem.get("s", "0"))
            f = elem.find(M + "f")
            v = elem.find(M + "v")
            inline = _text(elem.find(M + "is")) if cell.vtype == "inlineStr" else None
            cell.value = _parse_value(None if v is None else v.text, cell.vtype, inline, strings)
            if f is not None:
                ftype = f.get("t", "normal")
                text = f.text or ""
                if ftype == "shared":
                    si = f.get("si")
                    if text:
                        shared[si] = (text, row, col)
                        cell.formula, cell.ftype = text, "shared"
                    else:
                        pending.append((cell, si))
                        cell.ftype = "shared"
                elif ftype == "array":
                    cell.formula, cell.ftype, cell.fref = text, "array", f.get("ref")
                    wb.array_formulas.append({"sheet": sheet.name, "ref": f.get("ref") or ref,
                                              "formula": "=" + text,
                                              "dynamic": elem.get("cm") is not None})
                    if f.get("ref") and ":" in f.get("ref"):
                        array_members.append((f.get("ref"), text, row, col))
                elif ftype == "dataTable":
                    r1, r2 = f.get("r1"), f.get("r2")
                    dt2d = f.get("dt2D") in ("1", "true")
                    dtr = f.get("dtr") in ("1", "true")
                    if dt2d:
                        text = f"TABLE({r1},{r2})"
                    elif dtr:
                        text = f"TABLE({r1},)"
                    else:
                        text = f"TABLE(,{r1})"
                    cell.formula, cell.ftype, cell.fref = text, "dataTable", f.get("ref")
                    wb.data_tables.append({"sheet": sheet.name, "ref": f.get("ref") or ref,
                                           "r1": r1, "r2": r2, "twoInputs": dt2d,
                                           "inputsInRow": dtr, "formula": "{=" + text + "}"})
                    if f.get("ref") and ":" in f.get("ref"):
                        array_members.append((f.get("ref"), text, row, col))
                else:
                    cell.formula, cell.ftype = text, "normal"
            sheet.cells[(row, col)] = cell
            elem.clear()
        elif tag == M + "row":
            if elem.get("hidden") in ("1", "true"):
                sheet.hidden_rows.add(int(elem.get("r")))
            elem.clear()
        elif tag == M + "col":
            if elem.get("hidden") in ("1", "true"):
                for c in range(int(elem.get("min")), min(int(elem.get("max")), MAX_COL) + 1):
                    sheet.hidden_cols.add(c)
        elif tag == M + "mergeCell":
            sheet.merged.append(elem.get("ref"))
        elif tag == M + "sheetProtection":
            sheet.protected = elem.get("sheet") in ("1", "true")
        elif tag == M + "dataValidation":
            sheet.validations.append({
                "sqref": elem.get("sqref", ""), "type": elem.get("type", "any"),
                "operator": elem.get("operator"),
                "formula1": (elem.findtext(M + "formula1") or ""),
                "formula2": (elem.findtext(M + "formula2") or "")})
        elif tag == "{%s}dataValidation" % NS["x14"]:
            f1 = elem.find("x14:formula1/xm:f", NS)
            f2 = elem.find("x14:formula2/xm:f", NS)
            sheet.validations.append({
                "sqref": elem.findtext("xm:sqref", "", NS), "type": elem.get("type", "any"),
                "operator": elem.get("operator"),
                "formula1": "" if f1 is None else f1.text or "",
                "formula2": "" if f2 is None else f2.text or ""})
        elif tag == M + "conditionalFormatting":
            for rule in elem.findall(M + "cfRule"):
                sheet.conditional_formats.append({
                    "sqref": elem.get("sqref", ""), "type": rule.get("type"),
                    "operator": rule.get("operator"),
                    "formulas": [f.text or "" for f in rule.findall(M + "formula")]})
        elif tag == "{%s}conditionalFormatting" % NS["x14"]:
            sqref = elem.findtext("xm:sqref", "", NS)
            for rule in elem.findall("x14:cfRule", NS):
                sheet.conditional_formats.append({
                    "sqref": sqref, "type": rule.get("type"), "operator": rule.get("operator"),
                    "formulas": [f.text or "" for f in rule.findall("xm:f", NS)]})


def _finish_sheet(wb, sheet, shared, pending, array_members):
    """Expand shared formulas and mark the cells of array formulas and data tables."""
    for cell, si in pending:
        if si in shared:
            text, mrow, mcol = shared[si]
            cell.formula = shift(text, cell.row - mrow, cell.col - mcol)
        else:
            wb.notes.append(f"{sheet.name}!{cell.address}: shared formula {si} has no master")
    for ref, text, mrow, mcol in array_members:
        r1, c1, r2, c2 = parse_range(ref)
        ftype = "dataTable" if text.startswith("TABLE(") else "array-member"
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if (r, c) == (mrow, mcol):
                    continue
                cell = sheet.cells.get((r, c))
                if cell is None:
                    cell = sheet.cells[(r, c)] = Cell(r, c)
                if cell.formula is None:
                    cell.formula, cell.ftype = text, ftype


def _read_chart(zf, path):
    root = ET.fromstring(zf.read(path))
    chart = {"part": path, "types": [], "title": "", "series": []}
    title = root.find("c:chart/c:title", NS)
    if title is not None:
        chart["title"] = "".join(t.text or "" for t in title.iter("{%s}t" % NS["a"]))
    plot = root.find("c:chart/c:plotArea", NS)
    if plot is None:
        return chart
    for child in plot:
        local = child.tag.split("}")[-1]
        if local.endswith("Chart"):
            chart["types"].append(local)
            for ser in child.findall("c:ser", NS):
                item = {}
                for key in ("tx", "cat", "val", "xVal", "yVal", "bubbleSize"):
                    node = ser.find(f"c:{key}", NS)
                    if node is not None:
                        f = node.find(".//c:f", NS)
                        if f is not None and f.text:
                            item[key] = f.text
                chart["series"].append(item)
    return chart


def _read_drawing(zf, wb, sheet, drawing_path):
    rels = _rels(zf, drawing_path)
    for rid, (rtype, target, external) in rels.items():
        if rtype == "chart" and target in zf.namelist():
            sheet.charts.append(_read_chart(zf, target))
        elif rtype == "image":
            sheet.has_drawing_images = True


def _read_comments(zf, sheet, path):
    if path not in zf.namelist():
        return
    root = ET.fromstring(zf.read(path))
    for comment in root.findall("m:commentList/m:comment", NS):
        sheet.comments[comment.get("ref")] = _text(comment.find(M + "text")).strip()


def _read_table(zf, path):
    root = ET.fromstring(zf.read(path))
    columns = []
    for col in root.findall("m:tableColumns/m:tableColumn", NS):
        columns.append({"name": col.get("name"),
                        "formula": col.findtext(M + "calculatedColumnFormula")})
    return {"name": root.get("displayName") or root.get("name"), "ref": root.get("ref"),
            "headerRows": int(root.get("headerRowCount", "1")),
            "totalsRows": int(root.get("totalsRowCount", "0")), "columns": columns}


def _read_ctrl(zf, path):
    root = ET.fromstring(zf.read(path))
    return {"part": path, "type": root.get("objectType"), "link": root.get("fmlaLink"),
            "range": root.get("fmlaRange"), "macro": root.get("fmlaMacro")}


def load(path):
    """Read a workbook. Raises ValueError for files that are not .xlsx/.xlsm."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError(f"{path} is not an .xlsx or .xlsm file (zip). Save .xls and .xlsb "
                         "workbooks as .xlsx or .xlsm first.")
    with zf:
        return _load(zf, path)


def _load(zf, path):
    wb = Workbook(str(path))
    names = set(zf.namelist())
    wb_part = "xl/workbook.xml"
    for rel in ET.fromstring(zf.read("_rels/.rels")).findall("pr:Relationship", NS):
        if rel.get("Type", "").endswith("/officeDocument"):
            wb_part = rel.get("Target").lstrip("/")
    root = ET.fromstring(zf.read(wb_part))
    rels = _rels(zf, wb_part)
    pr = root.find("m:workbookPr", NS)
    wb.date1904 = pr is not None and pr.get("date1904") in ("1", "true")
    wb.protected = root.find("m:workbookProtection", NS) is not None
    calc = root.find("m:calcPr", NS)
    if calc is not None:
        wb.calc = dict(calc.attrib)
    strings_part = styles_part = None
    for rid, (rtype, target, external) in rels.items():
        if rtype == "sharedStrings":
            strings_part = target
        elif rtype == "styles":
            styles_part = target
        elif rtype == "connections":
            croot = ET.fromstring(zf.read(target))
            for conn in croot.findall("m:connection", NS):
                db = conn.find("m:dbPr", NS)
                text = "" if db is None else db.get("connection", "")
                wb.connections.append({
                    "name": conn.get("name"), "type": conn.get("type"),
                    "powerQuery": "Mashup" in text or conn.get("name", "").startswith("Query - "),
                    "command": "" if db is None else db.get("command", "")})
    strings = _shared_strings(zf, strings_part)
    _styles(zf, styles_part, wb)
    for index, node in enumerate(root.findall("m:sheets/m:sheet", NS)):
        rtype, target, _ = rels.get(node.get(R_ID), ("", "", False))
        kind = {"worksheet": "worksheet", "chartsheet": "chartsheet",
                "dialogsheet": "dialogsheet"}.get(rtype, "macrosheet" if "macro" in rtype.lower()
                                                  else rtype or "unknown")
        sheet = Sheet(node.get("name"), index, node.get("state", "visible"), target, kind)
        wb.sheets.append(sheet)
        if kind == "macrosheet":
            wb.macrosheets.append(sheet.name)
    for node in root.findall("m:definedNames/m:definedName", NS):
        scope = node.get("localSheetId")
        wb.names.append(DefinedName(node.get("name"), None if scope is None else int(scope),
                                    node.get("hidden") in ("1", "true"), node.text or ""))
    for node in root.findall("m:externalReferences/m:externalReference", NS):
        rtype, target, _ = rels.get(node.get(R_ID), ("", "", False))
        link = {"index": len(wb.external_links) + 1, "part": target, "target": "",
                "sheets": []}
        if target in names:
            lroot = ET.fromstring(zf.read(target))
            book = lroot.find("m:externalBook", NS)
            if book is not None:
                lrels = _rels(zf, target)
                link["target"] = lrels.get(book.get(R_ID), ("", "", True))[1]
                link["sheets"] = [s.get("val") for s in
                                  book.findall("m:sheetNames/m:sheetName", NS)]
            elif lroot.find("m:ddeLink", NS) is not None:
                link["target"] = "DDE link"
            elif lroot.find("m:oleLink", NS) is not None:
                link["target"] = "OLE link"
        wb.external_links.append(link)
    for sheet in wb.sheets:
        if sheet.path not in names:
            wb.notes.append(f"sheet '{sheet.name}': part {sheet.path} not found")
            continue
        if sheet.kind in ("worksheet", "macrosheet", "dialogsheet"):
            _read_sheet(zf, wb, sheet, strings)
        srels = _rels(zf, sheet.path)
        for rid, (rtype, target, external) in srels.items():
            if external or target not in names:
                continue
            if rtype == "drawing":
                _read_drawing(zf, wb, sheet, target)
            elif rtype == "comments":
                _read_comments(zf, sheet, target)
            elif rtype == "table":
                sheet.tables.append(_read_table(zf, target))
            elif rtype == "pivotTable":
                proot = ET.fromstring(zf.read(target))
                loc = proot.find("m:location", NS)
                sheet.pivots.append({"name": proot.get("name"), "part": target,
                                     "cacheId": proot.get("cacheId"),
                                     "location": None if loc is None else loc.get("ref")})
            elif rtype == "ctrlProp":
                sheet.controls.append(_read_ctrl(zf, target))
    for part in sorted(names):
        if part.startswith("xl/pivotCache/pivotCacheDefinition") and part.endswith(".xml"):
            croot = ET.fromstring(zf.read(part))
            src = croot.find("m:cacheSource/m:worksheetSource", NS)
            wb.pivot_caches[part] = {} if src is None else dict(src.attrib)
        elif part.startswith("xl/queryTables/"):
            qroot = ET.fromstring(zf.read(part))
            wb.query_tables.append({"part": part, "name": qroot.get("name")})
        elif part.startswith("customXml/item") and part.endswith(".xml"):
            head = zf.read(part)[:4000]
            if b"DataMashup" in head:
                wb.custom_xml_mashup = True
    wb.vba = any(n.lower().endswith("vbaproject.bin") for n in names)
    return wb


def defined_name_ranges(wb, item):
    """Return the Refs a defined name points to (empty for constants or formulas
    that are not plain references)."""
    cache = wb._name_refs
    key = (item.name, item.scope, item.text)
    if key not in cache:
        cache[key] = _name_refs(item)
    return cache[key]


def _name_refs(item):
    text = item.text.strip()
    if text.startswith("="):
        text = text[1:]
    refs, _, _, funcs = references(text)
    if funcs:
        return []
    return refs


# ---------------------------------------------------------------------------
# Writing input values into a copy (for recalculation by Excel)
# ---------------------------------------------------------------------------

def _xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _cell_xml(ref, value, style):
    s = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{repr(float(value))}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{_xml_escape(str(value))}</t></is></c>'


def write_inputs(src, dst, changes):
    """Copy a workbook and set input cells. changes: {"Sheet!B3": value}.
    The copy is marked for a full recalculation when Excel opens it; its stored
    results stay stale until Excel has recalculated and saved it. Only input
    cells without a formula can be set."""
    wb = load(src)
    by_part = {}
    for key, value in changes.items():
        sheet_name, _, ref = key.rpartition("!")
        sheet = wb.sheet(sheet_name.strip("'"))
        if sheet is None:
            raise ValueError(f"no sheet '{sheet_name}' for {key}")
        row, col, _, _ = parse_cell(ref.replace("$", ""))
        cell = sheet.get(row, col)
        if cell is not None and cell.formula is not None:
            raise ValueError(f"{key} holds a formula; only input cells can be set")
        by_part.setdefault(sheet.path, []).append(
            (row, col, value, 0 if cell is None else cell.style))
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in by_part:
                text = data.decode("utf-8")
                for row, col, value, style in by_part[info.filename]:
                    text = _set_cell(text, row, col, value, style)
                data = text.encode("utf-8")
            elif info.filename == "xl/workbook.xml":
                text = data.decode("utf-8")
                if "<calcPr" in text:
                    text = re.sub(r"<calcPr\b([^>]*?)(/?)>",
                                  lambda m: "<calcPr" + re.sub(r'\s+fullCalcOnLoad="[^"]*"', "",
                                                               m.group(1))
                                  + ' fullCalcOnLoad="1"' + m.group(2) + ">", text, count=1)
                else:
                    text = text.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
                data = text.encode("utf-8")
            zout.writestr(info, data)


def _set_cell(text, row, col, value, style):
    ref = addr(row, col)
    new = _cell_xml(ref, value, style)
    cell_pat = re.compile(rf'<c r="{ref}"[^>]*?(?:/>|>.*?</c>)', re.S)
    if cell_pat.search(text):
        return cell_pat.sub(lambda m: new, text, count=1)
    open_pat = re.compile(rf'<row r="{row}"([^>]*?)(/?)>')
    match = open_pat.search(text)
    if match:
        attrs, closed = match.group(1), match.group(2)
        if closed:
            filled = f'<row r="{row}"{attrs}>{new}</row>'
            return text[:match.start()] + filled + text[match.end():]
        end = text.index("</row>", match.end())
        body = text[match.end():end]
        pieces = re.findall(r'<c r="[A-Z]+\d+"[^>]*?(?:/>|>.*?</c>)', body, re.S)
        out, placed = [], False
        for piece in pieces:
            letters = re.match(r'<c r="([A-Z]+)', piece).group(1)
            if not placed and col_to_num(letters) > col:
                out.append(new)
                placed = True
            out.append(piece)
        if not placed:
            out.append(new)
        return text[:match.end()] + "".join(out) + text[end:]
    insert_at = None
    for item in re.finditer(r'<row r="(\d+)"', text):
        if int(item.group(1)) > row:
            insert_at = item.start()
            break
    new_row = f'<row r="{row}">{new}</row>'
    if insert_at is None:
        if "<sheetData/>" in text:
            return text.replace("<sheetData/>", f"<sheetData>{new_row}</sheetData>")
        insert_at = text.index("</sheetData>")
    return text[:insert_at] + new_row + text[insert_at:]
