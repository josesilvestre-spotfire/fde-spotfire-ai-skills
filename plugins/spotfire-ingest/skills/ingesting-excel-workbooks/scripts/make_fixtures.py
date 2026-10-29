"""Write synthetic engineering workbooks with known, seeded defects.

The workbooks exercise every stage of the Excel ingest scripts. Each one stores
formulas together with their results (as Excel does), so the scripts can read
stored values without Excel. Results are computed here in Python.

    pipe_pressure_drop.xlsx   liquid line pressure drop per segment (Darcy-Weisbach,
                              Swamee-Jain friction factor)
    production_decline.xlsx   Arps decline forecast, one sheet per well copied from
                              one template, what-if data table
    project_economics.xlsx    10-year cash flow with debt, circular interest
                              calculation, external price link, hidden sheet

SEEDED lists every defect with the cell where it sits. The tests assert that the
scripts find each one.

Usage:
    python make_fixtures.py [--out FOLDER]      (default: ../assets/fixtures)

Opening these files in Excel: Not yet tested. They are read by openpyxl and by
this skill's reader. Standard library only.
"""

import argparse
import datetime as dt
import math
import random
import zipfile
from pathlib import Path

SEEDED = {
    "pipe_pressure_drop.xlsx": [
        ("typed-over-formula", "Calc", "G14"),
        ("broken-pattern", "Calc", "F19"),
        ("mixed-units", "Calc", "I5"),
        ("error-value", "Calc", "K13"),
        ("iferror-masks", "Summary", "B7"),
        ("approximate-lookup", "Inputs", "B7"),
        ("unused-calculation", "Calc", "M5"),
        ("hardcoded-constant", "Calc", "D5"),
    ],
    "production_decline.xlsx": [
        ("template-drift", "Well C", "C9"),
        ("typed-over-formula", "Well B", "E20"),
        ("volatile-reference", "Summary", "B4"),
        ("hardcoded-constant", "Well A", "D9"),
    ],
    "project_economics.xlsx": [
        ("circular-reference", "Cashflow", "C9"),
        ("broken-pattern", "Cashflow", "H13"),
        ("constant-equals-input", "Cashflow", "C6"),
        ("external-link", "Inputs", "B4"),
        ("unused-calculation", "Calc_old", "B3"),
        ("hidden-content", "Calc_old", "A1"),
    ],
}

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"

STYLE = {"general": 0, "date": 1, "percent": 2, "fixed2": 3, "header": 4}


def col_letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_number(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def split(ref):
    i = 0
    while ref[i].isalpha():
        i += 1
    return int(ref[i:]), col_number(ref[:i])


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def excel_serial(day):
    return float((day - dt.date(1899, 12, 30)).days)


# ---------------------------------------------------------------------------
# Minimal workbook writer
# ---------------------------------------------------------------------------

class XSheet:
    def __init__(self, book, name, state="visible"):
        self.book, self.name, self.state = book, name, state
        self.cells = {}
        self.validations = []
        self.cond_formats = []
        self.charts = []
        self.tables = []
        self.widths = {}

    def put(self, ref, value, style="general"):
        """A constant (number, text or bool)."""
        row, col = split(ref)
        self.cells[(row, col)] = {"v": value, "s": STYLE[style]}

    def f(self, ref, formula, value, style="general", **extra):
        """A formula with its stored result."""
        row, col = split(ref)
        self.cells[(row, col)] = dict({"f": formula, "v": value, "s": STYLE[style]}, **extra)

    def fill_down(self, col, rows, make, style="general"):
        """Write make(row) -> (formula, value) for each row as Excel stores a
        filled-down range: shared formulas over each contiguous run of rows."""
        run = []
        for row in list(rows) + [None]:
            if run and (row is None or row != run[-1] + 1):
                self._shared(col, run, make, style, down=True)
                run = []
            if row is not None:
                run.append(row)

    def fill_right(self, row, cols, make, style="general"):
        run = []
        for col in list(cols) + [None]:
            if run and (col is None or col != run[-1] + 1):
                self._shared(row, run, make, style, down=False)
                run = []
            if col is not None:
                run.append(col)

    def _shared(self, fixed, run, make, style, down):
        si = self.book.next_si()
        first, last = run[0], run[-1]
        for i, pos in enumerate(run):
            row, col = (pos, col_number(fixed)) if down else (fixed, pos)
            formula, value = make(pos)
            cell = {"v": value, "s": STYLE[style]}
            if len(run) == 1:
                cell["f"] = formula
            elif i == 0:
                ref = (f"{fixed}{first}:{fixed}{last}" if down else
                       f"{col_letters(first)}{fixed}:{col_letters(last)}{fixed}")
                cell.update(f=formula, shared=si, sref=ref)
            else:
                cell.update(shared=si)
            self.cells[(row, col)] = cell

    def data_table(self, ref, input_cell, values):
        """One-variable what-if data table with its column input cell."""
        r1, c1 = split(ref.split(":")[0])
        for i, value in enumerate(values):
            cell = {"v": value, "s": 0}
            if i == 0:
                cell["dt"] = (ref, input_cell)
            self.cells[(r1 + i, c1)] = cell

    def xml(self, strings, rels):
        rows = {}
        for (row, col), cell in self.cells.items():
            rows.setdefault(row, []).append((col, cell))
        max_row = max(rows) if rows else 1
        max_col = max((c for (_, c) in self.cells), default=1)
        out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}">'
               f'<dimension ref="A1:{col_letters(max_col)}{max_row}"/>'
               '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
               '<sheetFormatPr defaultRowHeight="15"/>']
        if self.widths:
            out.append("<cols>")
            for col in sorted(self.widths):
                out.append(f'<col min="{col}" max="{col}" width="{self.widths[col]}" '
                           'customWidth="1"/>')
            out.append("</cols>")
        out.append("<sheetData>")
        for row in sorted(rows):
            out.append(f'<row r="{row}">')
            for col, cell in sorted(rows[row], key=lambda item: item[0]):
                out.append(self._cell_xml(row, col, cell, strings))
            out.append("</row>")
        out.append("</sheetData>")
        for sqref, ctype, operator, formula in self.cond_formats:
            out.append(f'<conditionalFormatting sqref="{sqref}"><cfRule type="{ctype}" '
                       f'dxfId="0" priority="1" operator="{operator}"><formula>{esc(formula)}'
                       '</formula></cfRule></conditionalFormatting>')
        if self.validations:
            out.append(f'<dataValidations count="{len(self.validations)}">')
            for sqref, formula in self.validations:
                out.append(f'<dataValidation type="list" allowBlank="1" showInputMessage="1" '
                           f'showErrorMessage="1" sqref="{sqref}"><formula1>{esc(formula)}'
                           '</formula1></dataValidation>')
            out.append("</dataValidations>")
        out.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
                   'header="0.3" footer="0.3"/>')
        if self.charts:
            out.append(f'<drawing r:id="{rels.add("drawing", "drawing")}"/>')
        if self.tables:
            out.append(f'<tableParts count="{len(self.tables)}">')
            for table in self.tables:
                out.append(f'<tablePart r:id="{rels.add("table", table["part"])}"/>')
            out.append("</tableParts>")
        out.append("</worksheet>")
        return "".join(out)

    @staticmethod
    def _cell_xml(row, col, cell, strings):
        ref = f"{col_letters(col)}{row}"
        style = f' s="{cell["s"]}"' if cell["s"] else ""
        value = cell.get("v")
        if isinstance(value, bool):
            tattr, vtext = ' t="b"', str(int(value))
        elif isinstance(value, (int, float)):
            tattr, vtext = "", repr(float(value))
        elif value is None:
            tattr, vtext = "", None
        elif isinstance(value, str) and value.startswith("#") and value.endswith(("!", "?", "A")):
            tattr, vtext = ' t="e"', value
        elif "f" in cell or "shared" in cell:
            tattr, vtext = ' t="str"', esc(value)
        else:
            tattr, vtext = ' t="s"', str(strings.index(value))
        if "dt" in cell:
            ref_range, input_cell = cell["dt"]
            ftext = (f'<f t="dataTable" ref="{ref_range}" dt2D="0" dtr="0" '
                     f'r1="{input_cell}"/>')
        elif "shared" in cell and "f" in cell:
            ftext = (f'<f t="shared" ref="{cell["sref"]}" si="{cell["shared"]}">'
                     f'{esc(cell["f"])}</f>')
        elif "shared" in cell:
            ftext = f'<f t="shared" si="{cell["shared"]}"/>'
        elif "f" in cell:
            ftext = f'<f>{esc(cell["f"])}</f>'
        else:
            ftext = ""
        vpart = "" if vtext is None else f"<v>{vtext}</v>"
        return f'<c r="{ref}"{style}{tattr}>{ftext}{vpart}</c>'


class Rels:
    def __init__(self):
        self.items = []

    def add(self, kind, target, external=False):
        rid = f"rId{len(self.items) + 1}"
        self.items.append((rid, kind, target, external))
        return rid

    def xml(self):
        out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               f'<Relationships xmlns="{PKG}">']
        for rid, kind, target, external in self.items:
            mode = ' TargetMode="External"' if external else ""
            out.append(f'<Relationship Id="{rid}" Type="{REL}/{kind}" '
                       f'Target="{esc(target)}"{mode}/>')
        out.append("</Relationships>")
        return "".join(out)


class XBook:
    def __init__(self):
        self.sheets = []
        self.names = []
        self.links = []
        self.calc = {}
        self._si = -1

    def next_si(self):
        self._si += 1
        return self._si

    def sheet(self, name, state="visible"):
        sheet = XSheet(self, name, state)
        self.sheets.append(sheet)
        return sheet

    def define(self, name, ref, scope=None, hidden=False):
        self.names.append((name, ref, scope, hidden))

    def link(self, target, sheet_name, cached):
        self.links.append((target, sheet_name, cached))
        return len(self.links)

    def save(self, path):
        strings = []
        for sheet in self.sheets:
            for cell in sheet.cells.values():
                value = cell.get("v")
                if isinstance(value, str) and "f" not in cell and "shared" not in cell \
                        and value not in strings:
                    strings.append(value)
        ctypes = [("/xl/workbook.xml",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
                  ("/xl/styles.xml",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
                  ("/xl/sharedStrings.xml",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"),
                  ("/docProps/core.xml",
                   "application/vnd.openxmlformats-package.core-properties+xml")]
        wb_rels = Rels()
        parts = {}
        chart_no = table_no = 0
        sheet_entries = []
        for index, sheet in enumerate(self.sheets, 1):
            srels = Rels()
            for table in sheet.tables:
                table_no += 1
                table["part"] = f"../tables/table{table_no}.xml"
                table["id"] = table_no
            xml = sheet.xml(strings, srels)
            if sheet.charts:
                drels = Rels()
                anchors = []
                for k, chart in enumerate(sheet.charts):
                    chart_no += 1
                    rid = drels.add("chart", f"../charts/chart{chart_no}.xml")
                    anchors.append(_anchor(k, rid))
                    parts[f"xl/charts/chart{chart_no}.xml"] = _chart_xml(chart)
                    ctypes.append((f"/xl/charts/chart{chart_no}.xml",
                                   "application/vnd.openxmlformats-officedocument."
                                   "drawingml.chart+xml"))
                parts[f"xl/drawings/drawing{index}.xml"] = _drawing_xml(anchors)
                parts[f"xl/drawings/_rels/drawing{index}.xml.rels"] = drels.xml()
                ctypes.append((f"/xl/drawings/drawing{index}.xml",
                               "application/vnd.openxmlformats-officedocument.drawing+xml"))
                srels.items = [(rid, kind, f"../drawings/drawing{index}.xml"
                                if kind == "drawing" else target, ext)
                               for rid, kind, target, ext in srels.items]
            for table in sheet.tables:
                name = table["part"].split("/")[-1]
                parts[f"xl/tables/{name}"] = _table_xml(table)
                ctypes.append((f"/xl/tables/{name}", "application/vnd.openxmlformats-"
                               "officedocument.spreadsheetml.table+xml"))
            parts[f"xl/worksheets/sheet{index}.xml"] = xml
            if srels.items:
                parts[f"xl/worksheets/_rels/sheet{index}.xml.rels"] = srels.xml()
            ctypes.append((f"/xl/worksheets/sheet{index}.xml", CT_SHEET))
            rid = wb_rels.add("worksheet", f"worksheets/sheet{index}.xml")
            state = "" if sheet.state == "visible" else f' state="{sheet.state}"'
            sheet_entries.append(f'<sheet name="{esc(sheet.name)}" sheetId="{index}"{state} '
                                 f'r:id="{rid}"/>')
        link_entries = []
        for n, (target, sheet_name, cached) in enumerate(self.links, 1):
            lrels = Rels()
            lrid = lrels.add("externalLinkPath", target, external=True)
            rows = "".join(f'<row r="{split(ref)[0]}"><cell r="{ref}"><v>{value!r}</v></cell>'
                           f'</row>' for ref, value in cached.items())
            parts[f"xl/externalLinks/externalLink{n}.xml"] = (
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<externalLink xmlns="{MAIN}" xmlns:r="{REL}"><externalBook r:id="{lrid}">'
                f'<sheetNames><sheetName val="{esc(sheet_name)}"/></sheetNames>'
                f'<sheetDataSet><sheetData sheetId="0">{rows}</sheetData></sheetDataSet>'
                '</externalBook></externalLink>')
            parts[f"xl/externalLinks/_rels/externalLink{n}.xml.rels"] = lrels.xml()
            ctypes.append((f"/xl/externalLinks/externalLink{n}.xml",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml."
                           "externalLink+xml"))
            rid = wb_rels.add("externalLink", f"externalLinks/externalLink{n}.xml")
            link_entries.append(f'<externalReference r:id="{rid}"/>')
        wb_rels.add("styles", "styles.xml")
        wb_rels.add("sharedStrings", "sharedStrings.xml")
        names = []
        for name, ref, scope, hidden in self.names:
            attrs = f' localSheetId="{scope}"' if scope is not None else ""
            attrs += ' hidden="1"' if hidden else ""
            names.append(f'<definedName name="{name}"{attrs}>{esc(ref)}</definedName>')
        calc = " ".join(f'{k}="{v}"' for k, v in dict({"calcId": "191029"},
                                                    **self.calc).items())
        parts["xl/workbook.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><workbookPr/>'
            '<bookViews><workbookView/></bookViews>'
            f'<sheets>{"".join(sheet_entries)}</sheets>'
            + (f'<externalReferences>{"".join(link_entries)}</externalReferences>'
               if link_entries else "")
            + (f'<definedNames>{"".join(names)}</definedNames>' if names else "")
            + f'<calcPr {calc}/></workbook>')
        parts["xl/_rels/workbook.xml.rels"] = wb_rels.xml()
        parts["xl/styles.xml"] = STYLES_XML
        parts["xl/sharedStrings.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<sst xmlns="{MAIN}" count="{len(strings)}" uniqueCount="{len(strings)}">'
            + "".join(f"<si><t>{esc(s)}</t></si>" for s in strings) + "</sst>")
        parts["docProps/core.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>Synthetic test workbook</dc:title>'
            '<dc:creator>Fixture generator</dc:creator></cp:coreProperties>')
        parts["_rels/.rels"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
            'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>')
        parts["[Content_Types].xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            + "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in ctypes)
            + "</Types>")
        order = ["[Content_Types].xml", "_rels/.rels"]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in order + sorted(n for n in parts if n not in order):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, parts[name])


STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<styleSheet xmlns="{MAIN}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="5">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '<dxfs count="1"><dxf><font><color rgb="FF9C0006"/></font></dxf></dxfs>'
    '</styleSheet>')


def _anchor(k, rid):
    top = 2 + 18 * k
    return (f'<xdr:twoCellAnchor><xdr:from><xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff>'
            f'<xdr:row>{top}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to>'
            f'<xdr:col>12</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{top + 16}</xdr:row>'
            '<xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
            f'<xdr:cNvPr id="{k + 2}" name="Chart {k + 1}"/><xdr:cNvGraphicFramePr/>'
            '</xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '</xdr:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
            f'drawingml/2006/chart"><c:chart r:id="{rid}"/></a:graphicData></a:graphic>'
            '</xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>')


def _drawing_xml(anchors):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/'
            'spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            f'xmlns:r="{REL}" xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            + "".join(anchors) + "</xdr:wsDr>")


def _chart_xml(chart):
    kind = chart["kind"]
    series = []
    for i, (name_ref, cat_ref, val_ref) in enumerate(chart["series"]):
        series.append(f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/><c:tx><c:strRef>'
                      f'<c:f>{esc(name_ref)}</c:f></c:strRef></c:tx><c:cat><c:numRef>'
                      f'<c:f>{esc(cat_ref)}</c:f></c:numRef></c:cat><c:val><c:numRef>'
                      f'<c:f>{esc(val_ref)}</c:f></c:numRef></c:val></c:ser>')
    extra = '<c:barDir val="col"/><c:grouping val="clustered"/>' if kind == "barChart" \
        else '<c:grouping val="standard"/>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            f'xmlns:r="{REL}"><c:chart><c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r>'
            f'<a:t>{esc(chart["title"])}</a:t></a:r></a:p></c:rich></c:tx>'
            '<c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/><c:plotArea>'
            f'<c:layout/><c:{kind}>{extra}<c:varyColors val="0"/>{"".join(series)}'
            f'<c:axId val="1"/><c:axId val="2"/></c:{kind}>'
            '<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
            '<c:delete val="0"/><c:axPos val="b"/><c:crossAx val="2"/></c:catAx>'
            '<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
            '<c:delete val="0"/><c:axPos val="l"/><c:crossAx val="1"/></c:valAx>'
            '</c:plotArea><c:plotVisOnly val="1"/></c:chart></c:chartSpace>')


def _table_xml(table):
    cols = "".join(f'<tableColumn id="{i + 1}" name="{esc(c)}"/>'
                   for i, c in enumerate(table["columns"]))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<table xmlns="{MAIN}" id="{table["id"]}" name="{table["name"]}" '
            f'displayName="{table["name"]}" ref="{table["ref"]}" totalsRowShown="0">'
            f'<autoFilter ref="{table["ref"]}"/><tableColumns count="{len(table["columns"])}">'
            f'{cols}</tableColumns><tableStyleInfo name="TableStyleMedium2" '
            'showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>'
            '</table>')


# ---------------------------------------------------------------------------
# Workbook 1: liquid line pressure drop
# ---------------------------------------------------------------------------

def pipe_pressure_drop(path):
    rng = random.Random(7)
    book = XBook()
    inputs = book.sheet("Inputs")
    segs = book.sheet("Segments")
    lookups = book.sheet("Lookups")
    calc = book.sheet("Calc")
    summary = book.sheet("Summary")

    flow, density, visc, age, inlet = 12000.0, 53.0, 4.5, 25.0, 950.0
    ages = [0.0, 10.0, 5.0, 20.0, 30.0]          # SEEDED: not sorted (rows 4 and 5)
    rough_by_age = [0.0018, 0.003, 0.0024, 0.006, 0.009]
    rough = rough_by_age[3]                        # what a range lookup of 25 returns

    inputs.put("A1", "Line inputs", "header")
    rows = [("Flow rate (bbl/d)", flow), ("Fluid density (lb/ft3)", density),
            ("Viscosity (cP)", visc), ("Pipe age (years)", age)]
    for i, (label, value) in enumerate(rows, 3):
        inputs.put(f"A{i}", label)
        inputs.put(f"B{i}", value)
    inputs.put("A7", "Roughness (in)")
    inputs.f("B7", "VLOOKUP(B6,Lookups!$A$3:$B$7,2)", rough)        # SEEDED approximate
    inputs.put("A8", "Inlet pressure (psi)")
    inputs.put("B8", inlet)
    inputs.put("A9", "Pipe material")
    inputs.put("B9", "Carbon steel")
    inputs.validations.append(("B9", '"Carbon steel,Stainless steel,Coated steel"'))
    for name, ref in [("FlowRate", "Inputs!$B$3"), ("Density", "Inputs!$B$4"),
                      ("Viscosity", "Inputs!$B$5"), ("Roughness", "Inputs!$B$7"),
                      ("InletPressure", "Inputs!$B$8")]:
        book.define(name, ref)

    lookups.put("A1", "Roughness by pipe age", "header")
    lookups.put("A2", "Age (years)")
    lookups.put("B2", "Roughness (in)")
    for i, (a, r) in enumerate(zip(ages, rough_by_age), 3):
        lookups.put(f"A{i}", a)
        lookups.put(f"B{i}", r)

    headers = ["Segment", "Length (ft)", "Inner diameter (in)", "Elevation change (ft)"]
    for j, h in enumerate(headers, 1):
        segs.put(f"{col_letters(j)}1", h)
    data = []
    for k in range(1, 21):
        length = 0.0 if k == 9 else float(rng.randint(8, 25) * 100)   # SEEDED zero length
        diam = 10.02 if k <= 10 else 7.981
        elev = float(rng.randint(-4, 6) * 10)
        data.append((k, length, diam, elev))
        segs.put(f"A{k + 1}", float(k))
        segs.put(f"B{k + 1}", length)
        segs.put(f"C{k + 1}", diam)
        segs.put(f"D{k + 1}", elev)
    segs.tables.append({"name": "SegmentData", "ref": "A1:D21", "columns": headers})

    calc.put("A1", "Pressure drop per segment", "header")
    calc.put("A2", "Darcy-Weisbach with the Swamee-Jain friction factor")
    heads = {"A": "Segment", "B": "Length (ft)", "C": "Inner diameter (in)",
             "D": "Velocity (ft/s)", "E": "Reynolds number", "F": "Friction factor",
             "G": "Friction loss (psi)", "H": "Elevation loss (kPa)",
             "I": "Segment drop (psi)", "J": "Outlet pressure (psi)",
             "K": "Pressure gradient (psi/ft)", "M": "Friction factor, Blasius"}
    for col, text in heads.items():
        calc.put(f"{col}4", text)
    rows = range(5, 25)
    res = {}
    pressure = inlet
    for r in rows:
        k, length, diam, elev = data[r - 5]
        v = flow * 5.615 / 86400 / (math.pi * (diam / 12) ** 2 / 4)
        re_ = 1488 * density * v * (diam / 12) / visc
        f = 0.25 / math.log10(rough / (3.7 * diam) + 5.74 / re_ ** 0.9) ** 2
        if r == 19:                                    # SEEDED broken pattern uses C5
            f = 0.25 / math.log10(rough / (3.7 * data[0][2]) + 5.74 / re_ ** 0.9) ** 2
        g = f * (length / (diam / 12)) * density * v ** 2 / (2 * 32.174) / 144
        if r == 14:                                    # SEEDED typed over the formula
            g = 0.35
        h = density * elev / 144 * 6.894757           # SEEDED kPa, added to psi below
        i_ = g + h
        pressure = pressure - i_
        kgrad = "#DIV/0!" if length == 0 else i_ / length
        blasius = 0.316 / re_ ** 0.25
        res[r] = dict(k=k, length=length, diam=diam, v=v, re=re_, f=f, g=g, h=h, i=i_,
                      p=pressure, kgrad=kgrad, blasius=blasius)
    calc.fill_down("A", rows, lambda r: (f"Segments!A{r - 3}", float(res[r]["k"])))
    calc.fill_down("B", rows, lambda r: (f"Segments!B{r - 3}", res[r]["length"]))
    calc.fill_down("C", rows, lambda r: (f"Segments!C{r - 3}", res[r]["diam"]))
    calc.fill_down("D", rows, lambda r: (f"FlowRate*5.615/86400/(PI()*(C{r}/12)^2/4)",
                                         res[r]["v"]), "fixed2")
    calc.fill_down("E", rows, lambda r: (f"1488*Density*D{r}*(C{r}/12)/Viscosity",
                                         res[r]["re"]))
    calc.fill_down("F", [r for r in rows if r != 19],
                   lambda r: (f"0.25/LOG10(Roughness/(3.7*C{r})+5.74/E{r}^0.9)^2",
                              res[r]["f"]))
    calc.f("F19", "0.25/LOG10(Roughness/(3.7*$C$5)+5.74/E19^0.9)^2", res[19]["f"])
    calc.fill_down("G", [r for r in rows if r != 14],
                   lambda r: (f"F{r}*(B{r}/(C{r}/12))*Density*D{r}^2/(2*32.174)/144",
                              res[r]["g"]))
    calc.put("G14", 0.35)
    calc.fill_down("H", rows, lambda r: (f"Density*Segments!D{r - 3}/144*6.894757",
                                         res[r]["h"]))
    calc.fill_down("I", rows, lambda r: (f"G{r}+H{r}", res[r]["i"]))
    calc.f("J5", "InletPressure-I5", res[5]["p"])
    calc.fill_down("J", range(6, 25), lambda r: (f"J{r - 1}-I{r}", res[r]["p"]))
    calc.fill_down("K", rows, lambda r: (f"I{r}/B{r}", res[r]["kgrad"]))
    calc.fill_down("M", rows, lambda r: (f"0.316/E{r}^0.25", res[r]["blasius"]))
    calc.cond_formats.append(("D5:D24", "cellIs", "greaterThan", "10"))

    total = sum(res[r]["i"] for r in rows)
    summary.put("A1", "Line pressure summary", "header")
    summary.put("A3", "Pipe material")
    summary.f("B3", "Inputs!B9", "Carbon steel")
    summary.put("A4", "Total pressure drop (psi)")
    summary.f("B4", "SUM(Calc!I5:I24)", total)
    summary.put("A5", "Outlet pressure (psi)")
    summary.f("B5", "Calc!J24", res[24]["p"])
    summary.put("A6", "Maximum velocity (ft/s)")
    summary.f("B6", "MAX(Calc!D5:D24)", max(res[r]["v"] for r in rows))
    summary.put("A7", "Average gradient (psi/ft)")
    summary.f("B7", "IFERROR(AVERAGE(Calc!K5:K24),0)", 0.0)        # SEEDED hides #DIV/0!
    summary.charts.append({"kind": "lineChart", "title": "Outlet pressure profile",
                           "series": [("Calc!$J$4", "Calc!$A$5:$A$24", "Calc!$J$5:$J$24")]})
    book.save(path)


# ---------------------------------------------------------------------------
# Workbook 2: production decline, one sheet per well
# ---------------------------------------------------------------------------

def _edate(day, months):
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.date(year, month, min(day.day, last))


def _well_rates(qi, di, b, exponential=False):
    rates = []
    for month in range(1, 37):
        t = month - 0.5
        if exponential:
            rates.append(qi * math.exp(-di / 12 * t))
        else:
            rates.append(qi / (1 + b * di / 12 * t) ** (1 / b))
    return rates


def production_decline(path):
    book = XBook()
    summary = book.sheet("Summary")
    wells = [("Well A", 850.0, 0.9, 0.8), ("Well B", 1200.0, 1.1, 0.9),
             ("Well C", 640.0, 0.7, 0.6), ("Well D", 980.0, 0.85, 1.0)]
    start = dt.date(2025, 1, 1)
    eur = {}
    for name, qi, di, b in wells:
        ws = book.sheet(name)
        ws.put("A1", "Well forecast", "header")
        ws.put("A2", "Initial rate qi (bbl/d)")
        ws.put("B2", qi)
        ws.put("A3", "Initial decline Di (1/yr)")
        ws.put("B3", di)
        ws.put("A4", "b factor")
        ws.put("B4", b)
        ws.put("A5", "First production date")
        ws.put("B5", excel_serial(start), "date")
        for col, text in zip("ABCDE", ["Month", "Date", "Rate (bbl/d)",
                                       "Monthly volume (bbl)", "Cumulative (bbl)"]):
            ws.put(f"{col}8", text)
        drift = name == "Well C"                       # SEEDED exponential, not hyperbolic
        rates = _well_rates(qi, di, b, exponential=drift)
        vols = [q * 30.4375 for q in rates]
        cum, total = [], 0.0
        for i, v in enumerate(vols):
            total = total + v
            if name == "Well B" and i == 11:          # SEEDED typed over (row 20)
                total = 152000.0
            cum.append(total)
        rows = range(9, 45)
        ws.put("A9", 1.0)
        ws.fill_down("A", range(10, 45), lambda r: (f"A{r - 1}+1", float(r - 8)))
        ws.fill_down("B", rows, lambda r: ("EDATE($B$5,A%d-1)" % r,
                                           excel_serial(_edate(start, r - 9))), "date")
        if drift:
            ws.fill_down("C", rows, lambda r: (f"$B$2*EXP(-$B$3/12*(A{r}-0.5))", rates[r - 9]))
        else:
            ws.fill_down("C", rows, lambda r: (f"$B$2/(1+$B$4*$B$3/12*(A{r}-0.5))^(1/$B$4)",
                                               rates[r - 9]))
        ws.fill_down("D", rows, lambda r: (f"C{r}*30.4375", vols[r - 9]))
        ws.f("E9", "D9", cum[0])
        skip = {20} if name == "Well B" else set()
        ws.fill_down("E", [r for r in range(10, 45) if r not in skip],
                     lambda r: (f"E{r - 1}+D{r}", cum[r - 9]))
        if skip:
            ws.put("E20", 152000.0)
        eur[name] = cum[-1]
        if name == "Well A":
            ws.put("G8", "b factor")
            ws.put("H8", "EUR 36 months (bbl)")
            ws.f("H9", "E44", cum[-1])
            bs = [0.5, 0.7, 0.9, 1.1, 1.3]
            for i, value in enumerate(bs, 10):
                ws.put(f"G{i}", value)
            sweep = [sum(q * 30.4375 for q in _well_rates(qi, di, value)) for value in bs]
            ws.data_table("H10:H14", "B4", sweep)
    summary.put("A1", "Field forecast summary", "header")
    summary.put("A3", "Well")
    summary.put("B3", "EUR 36 months (bbl)")
    summary.put("C3", "Initial rate (bbl/d)")
    for i, (name, qi, _, _) in enumerate(wells, 4):
        summary.put(f"A{i}", name)
    summary.fill_down("B", range(4, 8), lambda r: (
        "INDIRECT(\"'\"&A%d&\"'!E44\")" % r, eur[wells[r - 4][0]]))   # SEEDED INDIRECT
    summary.fill_down("C", range(4, 8), lambda r: (
        "INDIRECT(\"'\"&A%d&\"'!B2\")" % r, wells[r - 4][1]))
    summary.put("A9", "Total EUR (bbl)")
    summary.f("B9", "SUM(B4:B7)", sum(eur.values()))
    summary.charts.append({"kind": "barChart", "title": "EUR by well",
                           "series": [("Summary!$B$3", "Summary!$A$4:$A$7",
                                       "Summary!$B$4:$B$7")]})
    book.save(path)


# ---------------------------------------------------------------------------
# Workbook 3: project economics with a circular interest calculation
# ---------------------------------------------------------------------------

def _irr(flows):
    lo, hi = -0.99, 10.0
    npv = lambda r: sum(cf / (1 + r) ** (i + 1) for i, cf in enumerate(flows))
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def project_economics(path):
    book = XBook()
    book.calc = {"iterate": "1", "iterateCount": "100", "iterateDelta": "0.001"}
    inputs = book.sheet("Inputs")
    profile = book.sheet("Profile")
    cash = book.sheet("Cashflow")
    old = book.sheet("Calc_old", state="hidden")             # SEEDED hidden sheet
    capex, price, opex, royalty, tax, disc = 250.0, 70.0, 8.0, 0.125, 0.25, 0.10
    debt, rate = 100.0, 0.07
    inputs.put("A1", "Project economics inputs", "header")
    items = [("Capex ($MM)", capex, "Capex", "general"),
             ("Oil price ($/bbl)", None, "Price", "general"),
             ("Opex ($MM/yr)", opex, "Opex", "general"),
             ("Royalty rate", royalty, "Royalty", "percent"),
             ("Tax rate", tax, "TaxRate", "percent"),
             ("Discount rate", disc, "DiscountRate", "percent"),
             ("Debt amount ($MM)", debt, "Debt", "general"),
             ("Interest rate", rate, "InterestRate", "percent")]
    for i, (label, value, name, style) in enumerate(items, 3):
        inputs.put(f"A{i}", label)
        if value is not None:
            inputs.put(f"B{i}", value, style)
        book.define(name, f"Inputs!$B${i}")
    link = book.link("price_deck.xlsx", "Deck", {"B2": price})
    inputs.f("B4", f"[{link}]Deck!$B$2", price)                    # SEEDED external link
    inputs.validations.append(("B8", '"0.08,0.1,0.12"'))

    prod = [2.0, 3.5, 3.2, 2.8, 2.4, 2.0, 1.7, 1.4, 1.2, 1.0]
    profile.put("A1", "Production profile", "header")
    profile.put("A3", "Year")
    profile.put("A4", "Production (MMbbl)")
    for j, p in enumerate(prod):
        col = col_letters(2 + j)
        profile.put(f"{col}3", float(j + 1))
        profile.put(f"{col}4", p)

    years = range(10)
    rev = [p * price for p in prod]
    roy = [r * 0.125 for r in rev]
    res = []
    opening = debt
    for y in years:
        interest = 0.0
        for _ in range(500):
            taxable = rev[y] - roy[y] - opex - interest - capex / 10
            taxbase = rev[y] if y == 5 else taxable                  # SEEDED wrong row
            tax_v = max(0.0, taxbase) * tax
            avail = rev[y] - roy[y] - opex - interest - tax_v
            closing = max(0.0, opening - min(opening, max(0.0, avail) * 0.5))
            new_interest = rate * (opening + closing) / 2
            if abs(new_interest - interest) < 1e-13:
                interest = new_interest
                break
            interest = new_interest
        net = rev[y] - roy[y] - opex - interest - tax_v - (opening - closing) - \
            (capex - debt if y == 0 else 0.0)
        factor = 1 / (1 + disc) ** (y + 1)
        res.append(dict(opening=opening, interest=interest, avail=avail, closing=closing,
                        taxable=taxable, tax=tax_v, net=net, factor=factor, dcf=net * factor))
        opening = closing
    labels = {3: "Year", 4: "Production (MMbbl)", 5: "Revenue ($MM)", 6: "Royalty ($MM)",
              7: "Opex ($MM)", 8: "Opening debt ($MM)", 9: "Interest ($MM)",
              10: "Cash available for debt ($MM)", 11: "Closing debt ($MM)",
              12: "Taxable income ($MM)", 13: "Tax ($MM)", 14: "Net cash flow ($MM)",
              15: "Discount factor", 16: "Discounted cash flow ($MM)",
              17: "Cumulative DCF ($MM)", 19: "NPV ($MM)", 20: "NPV, NPV function ($MM)",
              21: "IRR"}
    cash.put("A1", "Cash flow", "header")
    for row, text in labels.items():
        cash.put(f"A{row}", text)
    cols = range(3, 13)                                   # C..L
    L = col_letters

    def y(c):
        return c - 3

    cash.fill_right(3, cols, lambda c: (f"Profile!{L(c - 1)}3", float(y(c) + 1)))
    cash.fill_right(4, cols, lambda c: (f"Profile!{L(c - 1)}4", prod[y(c)]))
    cash.fill_right(5, cols, lambda c: (f"{L(c)}4*Price", rev[y(c)]))
    cash.fill_right(6, cols, lambda c: (f"{L(c)}5*0.125", roy[y(c)]))     # SEEDED 0.125
    cash.fill_right(7, cols, lambda c: ("Opex", opex))
    cash.f("C8", "Debt", debt)
    cash.fill_right(8, range(4, 13), lambda c: (f"{L(c - 1)}11", res[y(c)]["opening"]))
    cash.fill_right(9, cols, lambda c: (f"InterestRate*({L(c)}8+{L(c)}11)/2",
                                        res[y(c)]["interest"]))
    cash.fill_right(10, cols, lambda c: (
        f"{L(c)}5-{L(c)}6-{L(c)}7-{L(c)}9-{L(c)}13", res[y(c)]["avail"]))
    cash.fill_right(11, cols, lambda c: (
        f"MAX(0,{L(c)}8-MIN({L(c)}8,MAX(0,{L(c)}10)*0.5))", res[y(c)]["closing"]))
    cash.fill_right(12, cols, lambda c: (f"{L(c)}5-{L(c)}6-{L(c)}7-{L(c)}9-Capex/10",
                                         res[y(c)]["taxable"]))
    cash.fill_right(13, [c for c in cols if c != 8],
                    lambda c: (f"MAX(0,{L(c)}12)*TaxRate", res[y(c)]["tax"]))
    cash.f("H13", "MAX(0,H5)*TaxRate", res[5]["tax"])                    # SEEDED H5
    cash.fill_right(14, cols, lambda c: (
        f"{L(c)}5-{L(c)}6-{L(c)}7-{L(c)}9-{L(c)}13-({L(c)}8-{L(c)}11)"
        f"-IF({L(c)}3=1,Capex-Debt,0)", res[y(c)]["net"]))
    cash.fill_right(15, cols, lambda c: (f"1/(1+DiscountRate)^{L(c)}3", res[y(c)]["factor"]))
    cash.fill_right(16, cols, lambda c: (f"{L(c)}14*{L(c)}15", res[y(c)]["dcf"]))
    cum = []
    total = 0.0
    for item in res:
        total += item["dcf"]
        cum.append(total)
    cash.f("C17", "C16", cum[0])
    cash.fill_right(17, range(4, 13), lambda c: (f"{L(c - 1)}17+{L(c)}16", cum[y(c)]))
    npv = sum(item["dcf"] for item in res)
    flows = [item["net"] for item in res]
    cash.f("C19", "SUM(C16:L16)", npv)
    cash.f("C20", "NPV(DiscountRate,C14:L14)", npv)
    cash.f("C21", "IRR(C14:L14)", _irr(flows), "percent")
    cash.cond_formats.append(("C17:L17", "cellIs", "lessThan", "0"))
    cash.charts.append({"kind": "lineChart", "title": "Cumulative discounted cash flow",
                        "series": [("Cashflow!$A$17", "Cashflow!$C$3:$L$3",
                                    "Cashflow!$C$17:$L$17")]})
    for name, ref in [("solver_opt", "Cashflow!$C$19"), ("solver_adj", "Inputs!$B$4"),
                      ("solver_typ", "3"), ("solver_val", "0")]:
        book.define(name, ref, scope=2, hidden=True)

    old.put("A1", "Old NPV check", "header")
    old.put("A3", "NPV at 8% ($MM)")
    old.f("B3", "NPV(0.08,Cashflow!C14:L14)",
          sum(cf / 1.08 ** (i + 1) for i, cf in enumerate(flows)))          # SEEDED unused
    book.save(path)


BUILDERS = {"pipe_pressure_drop.xlsx": pipe_pressure_drop,
            "production_decline.xlsx": production_decline,
            "project_economics.xlsx": project_economics}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    default = Path(__file__).resolve().parent.parent / "assets" / "fixtures"
    parser.add_argument("--out", default=str(default), help="output folder")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, build in BUILDERS.items():
        build(out / name)
        print(f"wrote {out / name}")


if __name__ == "__main__":
    main()
