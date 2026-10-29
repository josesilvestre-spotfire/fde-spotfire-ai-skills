#!/usr/bin/env python3
"""verify_dxp - read a saved Spotfire .dxp and compare it with the app spec.

CPython 3.14 + lxml. The .dxp is opened read-only with zipfile and never modified; nothing here starts
Spotfire. Contract: references/architecture.md (Report, Naming, HTML policy), references/spec-format.md, references/dxp-anatomy.md
(where every object is persisted). The object graph is read with scripts/sfgraph.py.

Commands
  dump <file.dxp> [--out model.json] [--reveal-secrets]
                                       JSON model of the newest AnalysisDocument: document, pages and
                                       visuals (axes, bounds, KPIs, table columns, text-area HTML and
                                       controls, action triggers, mod metadata, typed properties and
                                       layers), document properties, scripts, triggers, data
                                       functions, tables, relations, markings, filtering schemes, mods
                                       (with the embedded containers' digests and file hashes), archive.
                                       String constants of credential-like data-function inputs
                                       (Password, Token, ...) are masked unless --reveal-secrets
  check <app>                          compare spec.json (defaults resolved like dxpgen) and
                                       build/build-report.json with the DXP at app.output; writes
                                       build/verify-report.md and build/verify-report.json

<app> is an app folder, its spec.json, or an app slug under <workspace>/apps/ (as for dxpgen.py);
"verify_dxp.py <app>" without a command means check. dxpgen.py verify <app> runs check.
Exit codes: 0 no FAIL, 1 at least one FAIL, 2 usage (bad arguments, app, spec or DXP not found, unreadable
DXP). Every check line is PASS, FAIL or WARN with the object path and expected vs found.

What check compares (references/dxp-anatomy.md says where each item is persisted):
  document   saved-by version, CompatibilityVersion vs app.minimumSpotfireVersion, navigation, description,
             keywords, canvas, active page, theme (UseCustomStyles, CustomStyles.json vs app.theme.customStyles)
  pages      present, title, order, visible, filter / details-on-demand panels, filtering scheme, leftovers
  visuals    matched by build-report Guid, else title, else type: type id, title, showTitle, table, marking,
             limits, legend, axis expressions (whitespace, keyword case and <...> tolerant; the builder's
             reading of the spec, lib/60_charts.py and 70_tables.py), color-axis coloring (fixed,
             categorical, gradient, rule classes), reference layers, KPIs, table columns, totals, map
             layers, action triggers (added by hand: a manual step), visualization mods (mod id
             and version, the embedded mod and each of its files against the vizMods project, main-view
             and layer axes typed by the manifest, typed properties, layers in order with type, title,
             table, marking, limits, filtering and where clause)
  layout     each visual's share of its parent within 2 percentage points; order inside rows and columns
  textAreas  tokens resolve, no placeholder left, every spec control with kind, binding, values, label, script
  data       document properties, scripts (identical code), triggers, data functions (names, engine, code,
             refresh, bindings, outputs, parameter = property rule), tables (columns, formats, embedded,
             leftovers), relations, markings (colors, default), filtering schemes
  hygiene    every text entry of the archive: local paths, user names, credential-like assignments; auto
             names; the naming policy of references/architecture.md
  build      build-report.json: spec hash, output, failed steps, every fallback (with its manual step), warnings
Not compared yet: cell colorings (tables, cross tables, heat maps), KPI tile colorings, coloring rule values,
fitting models, graphical-table columns, summary-table statistics, visual descriptions, hierarchy levels.
"""
import argparse
import base64
import copy
import datetime
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
import sfgraph as sg  # noqa: E402
from t3 import _manual  # noqa: E402  (the marker text of each text-area control)
from sfexpr import raw_column_refs, row_level  # noqa: E402  (shared with dxpgen.py)

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

# spec visual type -> persisted TypeId.Name (references/spec-format.md, dxp-anatomy.md section 7)
TYPE_IDS = {
    "lineChart": "Spotfire.LineChart", "barChart": "Spotfire.BarChart", "histogram": "Spotfire.BarChart",
    "combinationChart": "Spotfire.CombinationChart", "scatterPlot": "Spotfire.ScatterPlot",
    "scatterPlot3D": "Spotfire.ScatterPlot3D", "pieChart": "Spotfire.PieChart", "boxPlot": "Spotfire.BoxPlot",
    "heatMap": "Spotfire.HeatMap", "treemap": "Spotfire.Treemap", "waterfallChart": "Spotfire.WaterfallChart",
    "table": "Spotfire.Table", "crossTable": "Spotfire.CrossTable", "summaryTable": "Spotfire.SummaryTable",
    "graphicalTable": "Spotfire.GraphicalTable", "kpiChart": "Spotfire.KpiChart", "map": "Spotfire.WebMapChart",
    "textArea": "Spotfire.HtmlTextArea", "mod": "Spotfire.Mod",
}

# persisted axis field -> API-style name used in the model ("axes")
AXIS_NAMES = {
    "X": "XAxis", "Y": "YAxis", "Z": "ZAxis", "Color": "ColorAxis", "Size": "SizeAxis", "Shape": "ShapeAxis",
    "Line": "LineByAxis", "Marker": "MarkerByAxis", "LabelColumn": "LabelColumn", "DrawingOrder": "DrawingOrderAxis",
    "MarkerRotation": "RotationAxis", "Hierarchy": "HierarchyAxis", "Measures": "MeasureAxis",
    "SectorSize": "SectorSizeAxis", "GeometryByAxis": "GeometryByAxis",
}
TRELLIS_AXES = {"Panels": "PanelAxis", "Rows": "RowAxis", "Columns": "ColumnAxis", "Pages": "PageAxis",
                "PanelPages": "PanelPageAxis"}
LINE_CONNECTION_AXES = {"Line": "ConnectionAxis", "Order": "OrderAxis"}
NESTED_AXIS_HOLDERS = ("ScatterLayer", "Trellis", "LineConnection", "PieMarker")
# Axes of a scatter plot or map marker layer that must aggregate when the markers aggregate (the marker-by
# has no baserowid()); persisted AxisConfiguration.supportsSplit false (references/api-maps.md)
MUST_AGGREGATE_AXES = ("LabelColumn", "SizeAxis", "LineConnection.OrderAxis", "RotationAxis")

# spec control kind -> (persisted control class, RenderType or ViewMode) (dxp-anatomy.md section 8)
CONTROL_KINDS = {
    "label": ("PropertyControl", "Label"), "input": ("PropertyControl", "TextBox"),
    "multilineInput": ("PropertyControl", "MultiLineTextBox"), "dropdown": ("PropertyControl", "DropDown"),
    "listbox": ("PropertyControl", "ListBox"), "multiSelectListbox": ("PropertyControl", "MultiSelectListBox"),
    "slider": ("PropertyControl", "Slider"), "checkbox": ("PropertyControl", "DropDown"),
    "radio": ("PropertyControl", "ListBox"), "button": ("ActionControl", "Button"),
    "link": ("ActionControl", "Link"),
}
EXECUTORS = {"python": "Spotfire.PythonScript.Executor", "terr": "Spotfire.SNextScript.Executor"}
COLOR_AXIS_TYPES = ("lineChart", "barChart", "histogram", "combinationChart", "scatterPlot", "scatterPlot3D",
                    "pieChart", "boxPlot", "treemap", "waterfallChart")
REFERENCE_LAYER_TYPES = ("lineChart", "barChart", "histogram", "combinationChart", "scatterPlot", "boxPlot",
                         "waterfallChart")
CUSTOM_PROPERTY_FLAGS = ("IsPersistent", "IsVisible", "IsEditable", "IsPropagated")
# persisted mod property class -> manifest property type (read from DXPs saved by Analyst 15.0)
MOD_PROPERTY_TYPES = {"StringModProperty": "string", "IntModProperty": "integer", "DoubleModProperty": "double",
                      "BoolModProperty": "boolean"}
MOD_AXIS_MODES = ("categorical", "continuous", "dual")
KNOWN_COLORS = {27: "#00FFFFFF", 35: "#FF000000", 164: "#FFFFFFFF"}     # System.Drawing.KnownColor
LAYOUT_SPACE = 100000          # VisualPanel.RelativeBounds space (dxp-anatomy.md section 5)
LAYOUT_SPLITTER = 3
LAYOUT_SHARE_TOLERANCE = 0.02  # a visual's share of its parent, absolute

_PERSISTED_RE = re.compile(r"_x([0-1][0-9A-Fa-f]|7[Ff]|5[Ff])")       # same as lint_ipy.decode_persisted
_TOKEN_RE = re.compile(r'<SpotfireControl\s+id\s*=\s*["\']([0-9A-Fa-f]{32})["\']\s*/?>')
_PLACEHOLDER_RE = re.compile(r"\{\{\s*control\s*:\s*([^{}\s]+)\s*\}\}")
_MARKER_RE = re.compile(r"\[control:\s*([^\]<]+?)\s*\]")
# the visible marker the builder puts where a text-area control goes (engine/features/controls.py; the
# slim tier's library uses the older color)
_MARKER_SPAN_RE = re.compile(r'<span style="color: #(?:B3261E|E94165); border: 1px dashed #(?:B3261E|E94165); '
                             r'padding: 0 4px">\[([^\]<]+)\]</span>')
MANUAL_NOTE = "a manual step (no public API): add it by hand from build/MANUAL-STEPS-<tier>.md, then save"
_MOD_MARKER_RE = re.compile(r"\[mod:\s*([^\]<]+?)\s*\]")
_PROP_SHORTHAND_RE = re.compile(r"\[\$([A-Za-z0-9_.]+)\]")
_DOCPROP_RE = re.compile(r"""^\s*DocumentProperty\(\s*(["'])((?:\\.|(?!\1).)*)\1\s*\)\s*$""")
_AUTO_NAME_RE = re.compile(r"\(\d{1,2}\)\s*$|^\s*untitled\b", re.I)          # dxpgen._AUTO_NAME
_TEMP_PAGE_RE = re.compile(r"^dxpb-page-\d+$")
_DEFAULT_TITLES = ("Page", "Text Area", "Map chart")


# ---------------------------------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------------------------------
def decode_persisted(text):
    """Spotfire's persisted-string escapes: _x09 -> tab (control characters, _x5F -> '_', _x7F)."""
    if not text or "_x" not in text:
        return text
    return _PERSISTED_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def norm_newlines(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def norm_code(text):
    """Code as compared: decoded, LF newlines, trailing whitespace at the end ignored."""
    return norm_newlines(decode_persisted(text or "")).rstrip()


def norm_ws(text):
    return " ".join(str(text or "").split())


def short(text, n=160):
    s = norm_ws(text) if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n - 3] + "..."


def esc_ident(name):
    """ExpressionUtilities.EscapeIdentifier: Flow Rate -> [Flow Rate] (']' doubled)."""
    return "[" + str(name).replace("]", "]]") + "]"


def esc_string(text):
    """ExpressionUtilities.EscapeStringLiteral: "..." with backslash escapes."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _skip_ident(text, i):
    n = len(text)
    j = i + 1
    while j < n:
        if text[j] == "]":
            if j + 1 < n and text[j + 1] == "]":
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _skip_string(text, i):
    quote = text[i]
    n = len(text)
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            if j + 1 < n and text[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return n


def props_shorthand(text):
    """[$Name] -> DocumentProperty("Name") (65_coloring.coloring_expression)."""
    return _PROP_SHORTHAND_RE.sub(lambda m: 'DocumentProperty("' + m.group(1) + '")', text)


def expr_key(text):
    """Comparison form of an expression: [$Name] shorthand expanded; outside [identifiers] and string
    literals whitespace removed and letters lower-cased (function names and keywords are
    case-insensitive in Spotfire); identifiers and literals kept as written."""
    if text is None:
        return ""
    t = props_shorthand(decode_persisted(str(text)).strip())
    out = []
    i = 0
    n = len(t)
    while i < n:
        ch = t[i]
        if ch == "[":
            j = _skip_ident(t, i)
            out.append(t[i:j])
            i = j
            continue
        if ch in "\"'":
            j = _skip_string(t, i)
            out.append(t[i:j])
            i = j
            continue
        if not ch.isspace():
            out.append(ch.lower())
        i += 1
    return "".join(out)


def strip_angle(key):
    if len(key) >= 2 and key[0] == "<" and key[-1] == ">":
        return key[1:-1]
    return key


def split_top(text):
    """Top-level comma split (outside identifiers, strings and parentheses)."""
    parts, depth, start, i, n = [], 0, 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            i = _skip_ident(text, i)
            continue
        if ch in "\"'":
            i = _skip_string(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def version_tuple(text):
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(x) for x in nums[:4]) if nums else (0,)


def ticks_to_iso(ticks):
    try:
        t = int(ticks) & 0x3FFFFFFFFFFFFFFF
        return (datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=t // 10)).isoformat()
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------------------------------
# the archive (read-only)
# ---------------------------------------------------------------------------------------------------
class DxpError(Exception):
    pass


class DxpArchive(object):
    """A .dxp opened read-only: entries, Metadata.xml, EmbeddedResources.xml, document versions."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.zip = zipfile.ZipFile(str(self.path), "r")
        except (OSError, zipfile.BadZipFile) as e:
            raise DxpError("cannot open %s as a DXP (zip): %s" % (self.path, e))
        self.infos = self.zip.infolist()
        self.names = [zi.filename for zi in self.infos]
        self.documents = []           # [(version, entry)], newest first
        self.compatibility = None
        self.saved_by = None
        self.data_format = None
        self._read_metadata()
        self.resources = {}           # id -> {"id", "name", "entry"}
        self._read_resources()
        self.main_entry = self.documents[0][1] if self.documents else "AnalysisDocument.xml"
        self.main_version = self.documents[0][0] if self.documents else None
        if self.main_entry not in self.names:
            raise DxpError("%s has no %s (not a Spotfire analysis?)" % (self.path, self.main_entry))

    def close(self):
        self.zip.close()

    def read(self, name):
        return self.zip.read(name)

    def text(self, name):
        """Entry as text, or None for binary content."""
        data = self.zip.read(name)
        if b"\x00" in data[:4096]:
            return None
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None

    def _read_metadata(self):
        if "Metadata.xml" not in self.names:
            self.documents = [("?", "AnalysisDocument.xml")]
            return
        root = etree.fromstring(self.zip.read("Metadata.xml"))
        self.compatibility = root.get("CompatibilityVersion")
        docs = []
        for prop in root.iter("Property"):
            if prop.get("ArchiveElementType") == "AnalysisDocument" and prop.get("ArchiveElementPath"):
                docs.append((prop.get("Version") or "?", prop.get("ArchiveElementPath")))
            key = prop.get("Key")
            if key == "SavedByAssemblyFileVersion":
                self.saved_by = prop.get("Value")
            elif key == "EmbeddedDataFormatVersion":
                self.data_format = prop.get("Value")
        docs.sort(key=lambda d: version_tuple(d[0]), reverse=True)
        self.documents = docs or [("?", "AnalysisDocument.xml")]

    def _read_resources(self):
        if "EmbeddedResources.xml" not in self.names:
            return
        root = etree.fromstring(self.zip.read("EmbeddedResources.xml"))
        for r in root.iter("EmbeddedResource"):
            rid = r.get("Id")
            self.resources[rid] = {"id": rid, "name": r.get("Name"), "entry": r.get("ArchiveElementPath")}

    def resource_by_name(self, name):
        for r in self.resources.values():
            if r["name"] == name:
                return r
        return None

    def resource_bytes(self, res):
        if res is None or not res.get("entry") or res["entry"] not in self.names:
            return None
        return self.zip.read(res["entry"])

    def entries(self):
        return [{"name": zi.filename, "size": zi.file_size, "compressedSize": zi.compress_size}
                for zi in self.infos]

    def embedded_mods(self):
        """[read_embedded_mod(...)] of every Mods/*.asice entry, in archive order."""
        out = []
        for name in self.names:
            if name.lower().startswith("mods/") and name.lower().endswith(".asice"):
                out.append(read_embedded_mod(name, self.zip.read(name)))
        return out


def read_embedded_mod(name, data):
    """An embedded mod container (ASiC-E zip: mimetype, mod.zip, META-INF/ASiCManifest.xml, signature):
    {archive, id, version, type, name, apiVersion, digest ("sha512=<base64 of mod.zip>", the hash the visual's
    Metadata carries), asicDigest (the ASiCManifest DigestValue), files {path in mod.zip: sha256}}; a broken
    container gives {archive, error}. mod.zip holds mod-manifest.json (re-serialized by Spotfire, so it is
    not compared byte for byte) and the files the manifest lists."""
    rec = {"archive": name}
    try:
        outer = zipfile.ZipFile(io.BytesIO(data))
        inner_bytes = outer.read("mod.zip")
        rec["digest"] = "sha512=" + base64.b64encode(hashlib.sha512(inner_bytes).digest()).decode("ascii")
        if "META-INF/ASiCManifest.xml" in outer.namelist():
            try:
                root = etree.fromstring(outer.read("META-INF/ASiCManifest.xml"))
                values = [el.text for el in root.iter() if isinstance(el.tag, str)
                          and el.tag.endswith("}DigestValue") and el.text]
                rec["asicDigest"] = "sha512=" + values[0].strip() if values else None
            except etree.XMLSyntaxError:
                rec["asicDigest"] = None
        inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
        files = {}
        manifest = None
        for zi in inner.infolist():
            if zi.filename.endswith("/"):
                continue
            body = inner.read(zi)
            if zi.filename == "mod-manifest.json":
                try:
                    manifest = json.loads(body.decode("utf-8-sig"))
                except (UnicodeDecodeError, ValueError):
                    manifest = None
                continue
            files.setdefault(zi.filename, hashlib.sha256(body).hexdigest())
        manifest = manifest if isinstance(manifest, dict) else {}
        for key in ("id", "version", "type", "name", "apiVersion"):
            rec[key] = manifest.get(key)
        rec["files"] = files
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as e:
        rec["error"] = "%s: %s" % (type(e).__name__, e)
    return rec


# ---------------------------------------------------------------------------------------------------
# graph access helpers
# ---------------------------------------------------------------------------------------------------
class View(object):
    """Null-safe accessors over an sfgraph.Graph; strings come back decoded (_xHH)."""

    def __init__(self, graph):
        self.G = graph

    def r(self, v):
        v = self.G.resolve(v)
        if v is None or v is sg.NULL:
            return None
        return v

    def get(self, node, *names):
        cur = node
        for nm in names:
            cur = self.r(cur)
            if isinstance(cur, sg.Node):
                cur = cur.get(nm)
            elif isinstance(cur, sg.Arr) and isinstance(nm, int):
                cur = cur.items[nm] if nm < len(cur.items) else None
            else:
                return None
            if cur is None:
                return None
        return self.r(cur)

    def node(self, node, *names):
        v = self.get(node, *names)
        return v if isinstance(v, sg.Node) else None

    def s(self, node, *names):
        v = self.get(node, *names)
        if isinstance(v, sg.Str):
            return decode_persisted(v.value)
        return None

    def prim(self, v):
        v = self.r(v)
        if isinstance(v, sg.Node) and v.get("m_value") is not None:          # boxed Int32 / Double / ...
            v = self.r(v.get("m_value"))
        if isinstance(v, sg.Prim):
            k, val = v.kind, v.value
            if k == "Bool":
                return val == "true"
            if k in ("Int", "Long", "Short", "Byte", "SByte", "UShort", "UInt", "ULong"):
                try:
                    return int(val)
                except ValueError:
                    return val
            if k in ("Double", "Float", "Decimal"):
                try:
                    return float(val)
                except ValueError:
                    return val
            return val
        if isinstance(v, sg.Str):
            return decode_persisted(v.value)
        if isinstance(v, sg.EnumVal):
            return v.value
        return None

    def b(self, node, *names):
        v = self.prim(self.get(node, *names))
        return v if isinstance(v, bool) else None

    def num(self, node, *names):
        v = self.prim(self.get(node, *names))
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def enum(self, node, *names):
        v = self.get(node, *names)
        return v.value if isinstance(v, sg.EnumVal) else None

    def items(self, v):
        return [self.r(x) for x in self.G.list_items(v)]

    def kv(self, v):
        """[(key, value)] of a KeyValuePair array, a Dictionary or a collection holding one."""
        v = self.r(v)
        if isinstance(v, sg.Node):
            arr = v.get("KeyValuePairs")
            if arr is None:
                arr = v.get("Items") if v.get("Items") is not None else v.get("Dictionary")
                if isinstance(self.r(arr), sg.Node):
                    return self.kv(arr)
            v = self.r(arr)
        if not isinstance(v, sg.Arr):
            return []
        out = []
        for item in v.items:
            item = self.r(item)
            if isinstance(item, sg.Node):
                out.append((self.r(item.get("key")), self.r(item.get("value"))))
        return out

    def tshort(self, v):
        v = self.r(v)
        if isinstance(v, (sg.Node, sg.Arr)) and v.type is not None:
            return v.type.short
        return None

    def guid(self, v):
        v = self.r(v)
        if isinstance(v, sg.Node) and v.type is not None and v.type.full == "System.Guid":
            return sg.guid_from_struct(self.G, v)
        if isinstance(v, sg.Str):
            return v.value
        return None

    def color(self, v):
        """#AARRGGBB of a System.Drawing.Color (known colors resolved where the value is 0)."""
        v = self.r(v)
        if not isinstance(v, sg.Node):
            return None
        val = self.prim(v.get("value"))
        known = self.prim(v.get("knownColor")) or 0
        name = self.s(v, "name")
        if known and not val:
            return KNOWN_COLORS.get(known, "knownColor:%d" % known)
        if isinstance(val, int):
            return "#%08X" % (val & 0xFFFFFFFF)
        return name

    def value(self, v):
        """JSON-friendly rendering of a persisted value (boxed numbers, DateTime, lists, strings)."""
        v = self.r(v)
        if v is None:
            return None
        if isinstance(v, (sg.Str, sg.Prim, sg.EnumVal)):
            return self.prim(v)
        if isinstance(v, sg.Node):
            t = v.type.full if v.type else ""
            if v.get("m_value") is not None:
                return self.prim(v)
            if t == "System.DateTime":
                return ticks_to_iso(self.prim(v.get("ticks")) or self.prim(v.get("dateData")) or 0)
            if t == "System.TimeSpan":
                ticks = self.prim(v.get("_ticks"))
                return str(datetime.timedelta(microseconds=int(ticks) // 10)) if isinstance(ticks, int) else None
            if t == "System.Guid":
                return self.guid(v)
            if t.startswith("System.Drawing.Color"):
                return self.color(v)
            if v.get("_items") is not None or v.get("_size") is not None:
                return [self.value(x) for x in self.items(v)]
            return "(%s)" % (v.type.short if v.type else "?")
        if isinstance(v, sg.Arr):
            if v.inline is not None:
                return v.inline
            return [self.value(x) for x in v.items]
        return None

    def expr(self, axis_node):
        """Expression text of an axis-like node (ExpressionTexts.Expression), decoded."""
        if axis_node is None:
            return None
        e = self.s(axis_node, "ExpressionTexts", "Expression")
        if e is None:
            e = self.s(axis_node, "Expression")
        return e


# ---------------------------------------------------------------------------------------------------
# the model (dump)
# ---------------------------------------------------------------------------------------------------
def parse_embedded_scripts(data):
    """[{id, name, language, languageVersion, wrapInTransaction, description, parameters, code, approved}]
    from the EmbeddedScripts.xml resource."""
    out = []
    if not data:
        return out
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(huge_tree=True))
    except etree.XMLSyntaxError:
        return out
    for es in root.iter("EmbeddedScript"):
        sd = es.find("ScriptDefinition")
        if sd is None:
            continue
        params = []
        pe = sd.find("Parameters")
        if pe is not None:
            for p in pe.iter("ScriptParameter"):
                desc = p.find("Description")
                params.append({"name": p.get("Name"), "type": p.get("TypeName"),
                               "description": decode_persisted(desc.text or "") if desc is not None else ""})
        desc = sd.find("Description")
        code = sd.find("ScriptCode")
        stamp = sd.find("ApprovalStamp")
        out.append({
            "id": es.get("ManagedScriptId"),
            "name": decode_persisted(sd.get("Name") or ""),
            "language": sd.get("LanguageName") or "",
            "languageVersion": sd.get("LanguageVersion") or "",
            "wrapInTransaction": (sd.get("WrapScript") or "").lower() == "true",
            "description": decode_persisted(desc.text or "") if desc is not None else "",
            "parameters": params,
            "code": decode_persisted(code.text or "") if code is not None else "",
            "approved": bool(stamp is not None and (stamp.text or "").strip()),
        })
    return out


def parse_function_definition(text):
    """Fields of a DataFunctionDefinition.Data XML string (already decoded: the _xHH escapes belong to the
    persisted string that holds the XML, so they are not decoded a second time here)."""
    info = {"functionName": None, "displayName": None, "description": None, "executor": None, "script": None,
            "dataframe": None, "allowCaching": None, "approved": False, "inputs": [], "outputs": []}
    if not text:
        return info
    try:
        root = etree.fromstring(text.encode("utf-8"), parser=etree.XMLParser(huge_tree=True))
    except etree.XMLSyntaxError:
        return info

    def child_text(el, tag):
        c = el.find(tag)
        return (c.text or "").strip() if c is not None and c.text is not None else ("" if c is not None else None)

    info["functionName"] = child_text(root, "FunctionName")
    info["displayName"] = child_text(root, "DisplayName")
    info["description"] = child_text(root, "Description")
    info["allowCaching"] = child_text(root, "OutputsOnlyDependsOnInputs")
    st = root.find("ServiceType")
    if st is not None:
        info["executor"] = child_text(st, "Name")
    isi = root.find("ImplementationSpecificInformation")
    if isi is not None:
        sc = isi.find("script")
        if sc is not None:
            info["script"] = sc.text or ""
        info["dataframe"] = child_text(isi, "dataframe")
    ta = root.find("TrustApproval")
    if ta is not None:
        stamp = ta.find("ApprovalStamp")
        info["approved"] = bool(stamp is not None and (stamp.text or "").strip())
    ia = root.find("InputArguments")
    if ia is not None:
        for arg in ia.findall("InputArgument"):
            allowed = [(d.text or "").strip() for d in arg.iter("DataType")]
            info["inputs"].append({"name": child_text(arg, "Name"), "argumentType": child_text(arg, "ArgumentType"),
                                   "description": child_text(arg, "Description"),
                                   "isOptional": child_text(arg, "IsOptional"), "allowedTypes": allowed})
    orr = root.find("OutputResults")
    if orr is not None:
        for res in orr.findall("OutputResult"):
            info["outputs"].append({"name": child_text(res, "Name"), "argumentType": child_text(res, "ArgumentType"),
                                    "description": child_text(res, "Description")})
    return info


class ModelBuilder(object):
    """Builds the JSON model of a DXP (the `dump` output) from the newest AnalysisDocument."""

    def __init__(self, archive, reveal_secrets=False):
        self.a = archive
        self.reveal_secrets = reveal_secrets
        self.G = sg.Graph(archive.read(archive.main_entry))
        self.v = View(self.G)
        self.notes = []
        self._index()

    # -- indexes ---------------------------------------------------------------------------------
    def _index(self):
        v, G = self.v, self.G
        res = self.a.resource_by_name("EmbeddedScripts.xml")
        self.scripts = parse_embedded_scripts(self.a.resource_bytes(res))
        self.script_by_id = dict((s["id"], s) for s in self.scripts)
        # managed data property node id -> document property name
        self.prop_by_managed = {}
        for n in G.by_id.values():
            if isinstance(n, sg.Node) and n.type is not None and "ManagedDataProperty" in n.type.full:
                dp = v.node(n, "DataProperty")
                if dp is not None:
                    self.prop_by_managed[n.id] = v.s(dp, "Name")
        # column producer node id -> table name; table node id -> table name
        self.table_by_producer = {}
        for t in G.nodes_of("DataTable", exact=True):
            name = v.s(t, "Name")
            prods = [v.r(t.get("ColumnProducer"))] + v.items(t.get("ColumnProducers"))
            for p in prods:
                if isinstance(p, sg.Node):
                    self.table_by_producer[p.id] = name
        # data function impl node id -> data function name
        self.df_by_impl = {}
        for d in G.nodes_of("DataFunction", exact=True):
            impl = v.node(d, "FunctionImpl")
            if impl is not None:
                self.df_by_impl[impl.id] = v.s(d, "Name")

    def script_name(self, managed_script):
        """Name of the script a ManagedScript runs (ManagedScriptDefinition DocumentNodeId ->
        EmbeddedScripts.xml ManagedScriptId)."""
        msd = self.v.node(managed_script, "ScriptDefinitionReference", "ScriptReference")
        if msd is None:
            return None
        sid = self.v.s(msd, "DocumentNodeId")
        s = self.script_by_id.get(sid)
        return s["name"] if s else None

    def script_args(self, managed_script):
        return self._argument_values(self.v.get(managed_script, "ScriptDefinitionReference", "ScriptArguments"))

    def action_mod(self, managed_script):
        """{mod, script, configuration, args, origin, originValue} when a ManagedScript runs an
        action-mod script (ActionModScriptDefinitionReference: ScriptModReference = ManagedActionMod
        {ModId, ModOrigin {Origin, Value}}, Id = the manifest script id, Configuration
        {Name, ScriptArguments}), else None (an IronPython or JavaScript script)."""
        v = self.v
        ref = v.node(managed_script, "ScriptDefinitionReference")
        if ref is None or ref.type is None or not ref.type.is_a("ActionModScriptDefinitionReference"):
            return None
        mod = v.node(ref, "ScriptModReference")
        return {"mod": v.s(mod, "ModId"), "script": v.s(ref, "Id"),
                "configuration": v.s(ref, "Configuration", "Name"),
                "args": self._argument_values(v.get(ref, "Configuration", "ScriptArguments")),
                "origin": v.prim(v.get(mod, "ModOrigin", "Origin")),
                "originValue": v.s(mod, "ModOrigin", "Value")}

    def _argument_values(self, collection):
        """{name: value} of a ManagedScriptArgumentValue dictionary (literal values, or the label of
        the node a node argument points at)."""
        out = {}
        for key, val in self.v.kv(collection):
            name = self.v.prim(key)
            if not isinstance(val, sg.Node):
                continue
            if val.get("LiteralValue") is not None:
                out[name] = self.v.value(val.get("LiteralValue"))
            else:
                target = self.v.node(val, "NodeReference")
                out[name] = self.node_label(target) if target is not None else self.v.s(val, "CachedNodeData", "Name")
        return out

    def node_label(self, node):
        if node is None:
            return None
        t = node.type.short if node.type else ""
        if t in ("Visual", "Page"):
            return self.v.s(node, "TitleExpression", "Expression")
        return self.v.s(node, "Name") or t

    # -- top level -------------------------------------------------------------------------------
    def build(self):
        model = {
            "file": str(self.a.path),
            "document": self.document(),
            "pages": self.pages(),
            "documentProperties": self.document_properties(),
            "scripts": [dict((k, s[k]) for k in ("name", "language", "languageVersion", "wrapInTransaction",
                                                   "description", "parameters", "code", "approved"))
                        for s in self.scripts],
            "propertyTriggers": self.triggers(),
            "dataFunctions": self.data_functions(),
            "tables": self.tables(),
            "relations": self.relations(),
            "markings": self.markings(),
            "filteringSchemes": self.filtering_schemes(),
            "mods": self.mods(),
            "archive": self.archive(),
        }
        if self.notes:
            model["notes"] = self.notes
        return model

    def archive(self):
        return {
            "mainDocument": self.a.main_entry,
            "documents": [{"version": ver, "entry": ent} for ver, ent in self.a.documents],
            "compatibilityVersion": self.a.compatibility,
            "savedByAssemblyFileVersion": self.a.saved_by,
            "embeddedDataFormatVersion": self.a.data_format,
            "resources": sorted(self.a.resources.values(), key=lambda r: int(r["id"]) if str(r["id"]).isdigit() else 0),
            "entries": self.a.entries(),
        }

    def document(self):
        v, root = self.v, self.G.root
        res_id = v.prim(v.get(root, "CustomStylesJson", "Id"))
        styles = None
        if res_id is not None:
            res = self.a.resources.get(str(res_id))
            data = self.a.resource_bytes(res)
            if data:
                text = data.decode("utf-8-sig", errors="replace")
                try:
                    styles = json.loads(text)
                except ValueError:
                    styles = text
        if styles is None:
            res = self.a.resource_by_name("CustomStyles.json")
            data = self.a.resource_bytes(res)
            if data:
                try:
                    styles = json.loads(data.decode("utf-8-sig", errors="replace"))
                except ValueError:
                    styles = data.decode("utf-8-sig", errors="replace")
        pm = v.node(root, "Pages")
        size = v.node(pm, "Pages", "VisualizationAreaSize")
        canvas = None
        if size is not None:
            canvas = {"width": v.num(size, "Size", "width"), "height": v.num(size, "Size", "height"),
                      "fitToWindow": v.b(size, "FitToWindow")}
        active = v.node(root, "ActivePageReference") or v.node(pm, "Pages", "ActivePage")
        dm = v.node(root, "DataManager")
        description, keywords = None, []
        for dp in self._analysis_properties():
            name = v.s(dp, "Name")
            if name == "Description":
                description = v.value(dp.get("Value"))
            elif name == "Keywords":
                val = v.value(dp.get("Value"))
                keywords = val if isinstance(val, list) else ([] if val in (None, "") else [val])
        return {
            "knownTheme": v.enum(root, "KnownTheme"),
            "useCustomStyles": v.b(root, "UseCustomStyles"),
            "customStylesJson": styles,
            "navigationMode": v.enum(pm, "NavigationMode"),
            "activePage": v.s(active, "TitleExpression", "Expression") if active is not None else None,
            "description": description,
            "keywords": keywords,
            "canvas": canvas,
            "defaultTable": v.s(dm, "Tables", "DefaultTable", "Name"),
            "defaultMarking": v.s(dm, "Markings", "DefaultMarking", "Name"),
            "defaultFilteringScheme": v.s(dm, "Filterings", "DefaultFiltering", "Name"),
        }

    # -- pages and visuals -----------------------------------------------------------------------
    def pages(self):
        v = self.v
        out = []
        pm = v.node(self.G.root, "Pages")
        for order, page in enumerate(v.items(v.get(pm, "Pages", "Items"))):
            if not isinstance(page, sg.Node):
                continue
            bounds = {}
            for vp in v.items(v.get(page, "VisualPanels", "Items")):
                vis = v.node(vp, "Visual")
                rb = v.node(vp, "RelativeBounds")
                if vis is not None and rb is not None:
                    bounds[vis.id] = {"x": v.num(rb, "x"), "y": v.num(rb, "y"), "width": v.num(rb, "width"),
                                      "height": v.num(rb, "height")}
            filter_visible, dod_visible, scheme = None, None, None
            filter_layout = None
            for panel in v.items(v.get(page, "Panels", "Items")):
                t = v.tshort(panel)
                if t == "FilterPanel":
                    filter_visible = v.b(panel, "Visible")
                    scheme = v.s(panel, "FilteringScheme", "DataSelection", "Name")
                    try:
                        filter_layout = self.filter_layout(panel)
                    except Exception as e:                       # never lose the dump over the panel
                        filter_layout = {"error": "%s: %s" % (type(e).__name__, e)}
                elif t == "DetailsOnDemandPanel":
                    dod_visible = v.b(panel, "Visible")
            visuals = []
            charts = []
            for vis in v.items(v.get(page, "Visuals", "Items")):
                if isinstance(vis, sg.Node):
                    try:
                        visuals.append(self.visual(vis, bounds.get(vis.id)))
                    except Exception as e:                       # never lose the dump over one visual
                        visuals.append({"guid": v.guid(vis.get("Id")), "error": "%s: %s" % (type(e).__name__, e)})
                    try:
                        charts.append(self.chart_layout(vis))
                    except Exception:                            # noqa: BLE001 - only check_trellis reads it
                        pass
            out.append({
                "title": v.s(page, "TitleExpression", "Expression"),
                "titleShown": v.s(page, "TitleExpression", "PreProcessedExpression"),
                "id": v.guid(page.get("Id")),
                "visible": v.b(page, "Visible"),
                "order": order,
                "filterPanelVisible": filter_visible,
                "detailsOnDemandVisible": dod_visible,
                "filteringScheme": scheme,
                "filterLayout": filter_layout,
                "visuals": visuals,
                "charts": charts,
            })
        return out

    def filter_layout(self, panel):
        """A page's filter panel organization: [{table, visible, expanded, items}] in
        panel order; an item is {kind "filter", column, visible, type (CheckBoxFilter, RangeFilter, ...)} or
        {kind "group", name, visible, expanded, items}. Serialized as TableGroup {VisibleSelectedPair
        {Visible}, Expanded, Items, DataTable}, FilterHandle {VisibleSelectedPair, Filter -> FilterBase ->
        DataColumn (Value -> DataColumn Name)}, FilterSubGroup {VisibleSelectedPair, Expanded, Items, Name}."""
        v = self.v
        out = []
        for tg in v.items(v.get(panel, "TableGroups")):
            if isinstance(tg, sg.Node):
                out.append({"table": v.s(tg, "DataTable", "Name"),
                            "visible": v.b(tg, "VisibleSelectedPair", "Visible"),
                            "expanded": v.b(tg, "Expanded"), "items": self._filter_items(tg)})
        return out

    def _filter_items(self, group):
        v = self.v
        items = []
        for it in v.items(v.get(group, "Items")):
            if not isinstance(it, sg.Node):
                continue
            kind = v.tshort(it)
            if kind == "FilterHandle":
                fb = v.node(it, "Filter", "FilterBase")
                items.append({"kind": "filter", "column": v.s(fb, "DataColumn", "Value", "Name") if fb else None,
                              "visible": v.b(it, "VisibleSelectedPair", "Visible"),
                              "type": v.tshort(fb) if fb else None})
            elif kind == "FilterSubGroup":
                items.append({"kind": "group", "name": v.s(it, "Name"),
                              "visible": v.b(it, "VisibleSelectedPair", "Visible"),
                              "expanded": v.b(it, "Expanded"), "items": self._filter_items(it)})
        return items

    def chart_layout(self, vis):
        """guid, title, content type, trellis (mode, manual grid, axes) and the y axis's individual scaling
        of one visual (Checker.check_trellis). Line and bar charts keep the y axis in
        "Y", scatter plots in "ScatterLayer" > "Y"."""
        v = self.v
        content = v.node(vis, "InternalContent")
        info = {"guid": v.guid(vis.get("Id")), "title": v.s(vis, "TitleExpression", "Expression"),
                "content": v.tshort(content)}
        if content is None:
            return info
        tr = v.node(content, "Trellis")
        if tr is not None:
            info["trellis"] = {"mode": v.enum(tr, "TrellisMode"), "manual": v.b(tr, "ManualLayout"),
                               "rows": v.num(tr, "ManualRowCount"), "columns": v.num(tr, "ManualColumnCount"),
                               "panelBy": v.expr(v.node(tr, "Panels")), "rowsBy": v.expr(v.node(tr, "Rows")),
                               "columnsBy": v.expr(v.node(tr, "Columns"))}
        y = v.node(content, "Y") or v.node(content, "ScatterLayer", "Y")
        if y is not None and v.b(y, "IndividualScaling") is not None:
            info["yIndividual"] = [v.b(y, "IndividualScaling"), v.enum(y, "IndividualScalingMode")]
        return info

    def collect_axes(self, content, type_id):
        """{api axis name: expression} for every axis-like field (ExpressionTexts) of a visual's content,
        including those under ScatterLayer, Trellis, LineConnection and PieMarker."""
        v = self.v
        axes = {}

        def put(name, node):
            e = v.expr(node)
            if e is not None and e.strip() not in ("", "<>"):
                axes.setdefault(name, e)

        def walk(node, holder):
            for fname, fv in node.fields:
                a = v.r(fv)
                if not isinstance(a, sg.Node):
                    continue
                if a.get("ExpressionTexts") is not None:
                    if holder == "Trellis":
                        put("Trellis." + TRELLIS_AXES.get(fname, fname), a)
                    elif holder == "LineConnection":
                        put("LineConnection." + LINE_CONNECTION_AXES.get(fname, fname), a)
                    elif holder == "PieMarker":
                        if type_id == "Spotfire.PieChart":
                            put({"Color": "ColorAxis", "SectorSize": "SectorSizeAxis"}.get(fname, fname), a)
                        else:
                            put("PieMarker." + AXIS_NAMES.get(fname, fname), a)
                    else:
                        name = AXIS_NAMES.get(fname, fname)
                        if type_id == "Spotfire.PieChart" and holder == "ScatterLayer" and fname == "Color":
                            name = "MarkerColorAxis"
                        put(name, a)
                elif fname in NESTED_AXIS_HOLDERS and holder in (None, "ScatterLayer"):
                    walk(a, fname)

        if isinstance(content, sg.Node):
            walk(content, None)
        return axes

    def visual(self, vis, bounds):
        v = self.v
        content = v.node(vis, "InternalContent")
        type_id = v.s(content, "TypeId", "Name")
        m = {
            "guid": v.guid(vis.get("Id")),
            "typeId": type_id,
            "contentClass": content.type.short if content is not None and content.type else None,
            "title": v.s(vis, "TitleExpression", "Expression"),
            "showTitle": v.b(vis, "ShowTitle"),
            "bounds": bounds,
        }
        triggers = self._action_triggers(vis)
        if triggers:
            m["actionTriggers"] = triggers
        if content is None:
            return m
        desc = v.s(content, "DescriptionExpression", "Expression")
        if desc:
            m["description"] = desc
        data = v.node(content, "Data")
        if data is not None:
            m.update(self._data_links(data))
        legend = v.node(content, "Legend")
        if legend is not None:
            m["legendVisible"] = v.b(legend, "Visible")
        m["axes"] = self.collect_axes(content, type_id)
        color_axis = self._color_axis_node(content, type_id)
        if color_axis is not None:
            m["coloring"] = self._coloring(v.node(color_axis, "Rules"))
        layers = self._reference_layers(content)
        if layers:
            m["referenceLayers"] = layers
        cls = m["contentClass"]
        if cls == "KpiChart":
            m["kpis"] = self._kpis(content, m["axes"])
        elif cls == "TablePlot":
            m["tableColumns"] = self._table_columns(content)
            m["tableSort"] = self._table_sort(content)
        elif cls == "CrossTablePlot":
            m["totals"] = {"rows": v.b(content, "ShowRowGrandTotal"), "columns": v.b(content, "ShowColumnGrandTotal")}
        elif cls in ("HtmlTextArea", "TextArea"):
            self._text_area(content, m)
        elif cls == "ModVisualization":
            self._mod_visual(content, m)
        elif cls == "MapChart":
            m["layers"] = self._map_layers(content)
            m["autoZoom"] = v.b(content, "AutoZoom")
        elif cls == "SummaryTable":
            m["summaryColumns"] = self._names_of(v.get(content, "Columns"))
        return m

    def _data_links(self, data):
        """Data settings of a VisualizationData (a visual's, a mod layer's): table, marking (None = cannot be
        marked), limitByMarkings, limitByFilterings, useFiltering, limitExpression, emptyMarkingBehavior."""
        v = self.v
        out = {"table": v.s(data, "DataTable", "Name")}
        mk = v.node(data, "Marking")
        out["marking"] = v.s(mk, "Name") if mk is not None else None
        out["limitByMarkings"], out["limitByFilterings"] = [], []
        for f in v.items(v.get(data, "Filterings", "Items")):
            ref = v.node(f, "Reference")
            if ref is None:
                continue
            if ref.type is not None and ref.type.is_a("DataMarkingSelection"):
                out["limitByMarkings"].append(v.s(ref, "Name"))
            else:
                out["limitByFilterings"].append(v.s(ref, "Name"))
        out["useFiltering"] = v.b(data, "UseActiveFiltering")
        out["limitExpression"] = v.s(data, "WhereClauseExpression", "Expression")
        out["emptyMarkingBehavior"] = v.enum(data, "LimitingMarkingsEmptyBehavior")
        return out

    def _action_triggers(self, vis):
        """A visual's action triggers in order (Visual.ActionTriggers.Items -> ActionTrigger {AccessPoint.Display,
        Target ManagedScriptActionTriggerTarget.ManagedScriptReference}): {display, mod, script, configuration,
        args} for an action-mod script, {display, ironPython (script name), args} for a document script,
        {display, target (class)} for another target."""
        v = self.v
        out = []
        for t in v.items(v.get(vis, "ActionTriggers", "Items")):
            if not isinstance(t, sg.Node):
                continue
            rec = {"display": v.enum(t, "AccessPoint", "Display")}
            ms = v.node(t, "Target", "ManagedScriptReference")
            am = self.action_mod(ms) if ms is not None else None
            if am is not None:
                rec.update((k, am[k]) for k in ("mod", "script", "configuration", "args"))
            elif ms is not None:
                rec["ironPython"] = self.script_name(ms)
                rec["args"] = self.script_args(ms)
            else:
                rec["target"] = v.tshort(v.get(t, "Target"))
            out.append(rec)
        return out

    def _color_axis_node(self, content, type_id):
        """The chart's color axis: Color, or ScatterLayer.Color (scatter), ScatterLayer.PieMarker.Color (pie)."""
        v = self.v
        if type_id == "Spotfire.PieChart":
            return v.node(content, "ScatterLayer", "PieMarker", "Color")
        axis = v.node(content, "Color")
        if axis is None:
            axis = v.node(content, "ScatterLayer", "Color")
        return axis if axis is not None and axis.get("ExpressionTexts") is not None else None

    def _coloring(self, rules):
        """{defaultColor, emptyColor, rules: [{type, colors?, breakpoints?}]} of a Coloring node."""
        v = self.v
        if rules is None:
            return None
        out = {"defaultColor": v.color(rules.get("DefaultColor")), "emptyColor": v.color(rules.get("EmptyColor")),
               "rules": []}
        for rule in v.items(rules.get("Items")):
            if not isinstance(rule, sg.Node):
                continue
            rec = {"type": rule.type.short if rule.type else "?"}
            if rec["type"] == "CategoricalColorRule":
                colors = {}
                for key, val in v.kv(rule.get("UserSetColors")):
                    parts = [v.value(p) for p in v.items(v.get(key, "Parts"))]
                    colors[" | ".join("" if p is None else str(p) for p in parts)] = v.color(val)
                rec["colors"] = colors
            elif rec["type"] == "ContinuousColorRule":
                rec["breakpoints"] = len(v.items(rule.get("Breakpoints")))
            out["rules"].append(rec)
        return out

    def _reference_layers(self, content):
        v = self.v
        out = []
        for layer in v.items(v.get(content, "InternalLayers", "Items")):
            if isinstance(layer, sg.Node) and layer.type is not None and layer.type.short == "ReferenceLayer":
                out.append({"name": v.s(layer, "Name"), "enabled": v.b(layer, "Enabled"),
                            "value": v.expr(v.node(layer, "Value")),
                            "secondaryValue": v.expr(v.node(layer, "SecondaryValue")),
                            "line": v.b(layer, "Line", "Enabled"), "band": v.b(layer, "Band", "FillEnabled")})
        return out

    def _names_of(self, collection):
        names = []
        for it in self.v.items(collection):
            if isinstance(it, sg.Node):
                n = self.v.s(it, "Name") or self.v.s(it, "ColumnName")
                if n is not None:
                    names.append(n)
        return names

    def _kpis(self, content, axes):
        v = self.v
        out = []
        for i, kc in enumerate(v.items(v.get(content, "KpiCollection", "Items"))):
            if not isinstance(kc, sg.Node):
                continue
            kv_ = v.node(kc, "MiniatureVisualization")
            k = {"title": v.s(kc, "TitleExpression", "Expression"), "value": None, "axes": {}}
            for fname in ("YAxis", "XAxis", "TileAxis", "ComparativeAxis", "ColorAxis", "SortColumn"):
                e = v.expr(v.node(kv_, fname))
                if e is not None and e.strip() not in ("", "<>"):
                    k["axes"][fname] = e
                    axes["kpis[%d].%s" % (i, fname)] = e
            k["value"] = k["axes"].get("YAxis")
            k["table"] = v.s(kv_, "Data", "DataTable", "Name")
            k["showSparkline"] = v.b(kv_, "ShowSparkline")
            out.append(k)
        return out

    def _column_name_by_id(self):
        if not hasattr(self, "_col_ids"):
            self._col_ids = {}
            for c in self.G.nodes_of("DataColumn", exact=True):
                gid = self.v.guid(c.get("Id"))
                if gid:
                    self._col_ids[gid] = self.v.s(c, "Name")
        return self._col_ids

    def _table_columns(self, content):
        v = self.v
        names = []
        for c in v.items(v.get(content, "TableColumns", "Items")):
            if isinstance(c, sg.Node):
                names.append(v.s(c, "Name"))
        return names

    def _table_sort(self, content):
        v = self.v
        cols = [v.s(c, "Name") for c in v.items(v.get(content, "SortInfos", "Items")) if isinstance(c, sg.Node)]
        modes = {}
        ids = self._column_name_by_id()
        for key, val in v.kv(v.get(content, "SortInfos", "SortModes")):
            modes[ids.get(v.guid(key), v.guid(key))] = v.prim(val)
        return [{"column": c, "mode": modes.get(c)} for c in cols]

    def _provider(self, vp):
        v = self.v
        if vp is None:
            return None
        t = vp.type.short if vp.type else "?"
        info = {"type": t}
        if t == "FixedValuesProvider":
            items = v.items(vp.get("Values")) or v.items(vp.get("Items"))
            info["values"] = [{"text": v.s(x, "Name"), "value": v.value(x.get("Value"))}
                              for x in items if isinstance(x, sg.Node)]
        elif t == "ColumnValuesProvider":
            col = v.node(vp, "DataColumnReference")
            table = None
            if col is not None:
                owner = self.G.owner(col, "DataTable")
                table = v.s(owner, "Name") if owner is not None else None
            info["column"] = {"table": table, "column": v.s(col, "Name") if col is not None else None}
        elif t == "ColumnNamesValueProvider":
            info["table"] = v.s(vp, "ColumnDataTableReference", "Name")
            info["searchPattern"] = v.s(vp, "SearchPattern")
        elif t == "NumericalRangeValueProvider":
            for f in ("Min", "Max", "Interval"):
                info[f.lower()] = v.value(vp.get(f))
            info["showLabels"] = v.b(vp, "ShowLabels")
        return info

    def _text_area(self, content, m):
        v = self.v
        html = v.s(content, "HtmlContent") or ""
        m["htmlContent"] = html
        tokens = [t.lower() for t in _TOKEN_RE.findall(html)]
        controls = []
        for c in v.items(v.get(content, "Controls", "Items")):
            if not isinstance(c, sg.Node):
                continue
            cid = (v.guid(c.get("Id")) or "").replace("-", "").lower()
            t = c.type.short if c.type else "?"
            rec = {"id": cid, "kind": t, "inHtml": cid in tokens}
            if t == "PropertyControl":
                rec["renderType"] = v.enum(c, "RenderType")
                mp = v.node(c, "DataProperty")
                rec["property"] = self.prop_by_managed.get(mp.id) if mp is not None else None
                rec["values"] = self._provider(v.node(c, "ValueProvider"))
            elif t == "ActionControl":
                rec["label"] = v.s(c, "Label")
                rec["viewMode"] = v.s(c, "ViewMode")
                ms = v.node(c, "ScriptApplication")
                if ms is not None:
                    mod = self.action_mod(ms)
                    if mod is not None:
                        rec["actionMod"] = mod
                    else:
                        rec["script"] = self.script_name(ms)
                        rec["scriptArguments"] = self.script_args(ms)
                link = v.node(c, "ActionLinkReference")
                if link is not None:
                    rec["action"] = self._link_actions(link)
                dfn = v.node(c, "DataFunctionReference")
                if dfn is not None:
                    rec["dataFunction"] = v.s(dfn, "Name")
            elif t == "FilterControl":
                rec["filter"] = v.tshort(c.get("Filter"))
            controls.append(rec)
        m["controls"] = controls
        known = set(c["id"] for c in controls)
        m["danglingTokens"] = [t for t in tokens if t not in known]
        js = []
        for item in v.items(v.get(content, "CustomJavaScripts", "Items")):
            ms = v.node(item, "ScriptApplication")
            if ms is not None:
                js.append(self.script_name(ms))
        m["jsScripts"] = js
        m["actionLinks"] = len(v.items(v.get(content, "ActionLinks", "Items")))

    def _link_actions(self, link):
        v = self.v
        out = []
        for op in v.items(v.get(link, "Actions", "Items")):
            if not isinstance(op, sg.Node):
                continue
            t = op.type.short if op.type else "?"
            if t == "GotoPageDocumentOperation":
                out.append({"gotoPage": v.s(op, "Page", "TitleExpression", "Expression")})
            elif t == "ApplyBookmarkDocumentOperation":
                out.append({"applyBookmark": v.s(op, "BookmarkId") or v.guid(op.get("BookmarkId"))})
            else:
                out.append({"operation": t})
        return out

    def _mod_visual(self, content, m):
        """A visualization mod (ModVisualization): Metadata {id, name, version, apiVersion, hash}, ModReference
        (ManagedVisualizationMod {ModId, ModOrigin {Origin, Value}}), the main view's axes and typed properties,
        and the layers (LayerCollection.Items -> ModLayerContent {TitleExpression, Layer -> ModLayer {Type, Data,
        AxisCollection, Properties, ColorAxis}}) in order. Paths read from DXPs saved by Analyst 15.0."""
        v = self.v
        meta = v.s(content, "Metadata")
        info = {}
        if meta:
            try:
                info = json.loads(meta)
            except ValueError:
                info = {}
        info = info if isinstance(info, dict) else {}
        m["modId"] = info.get("id")
        m["modName"] = info.get("name")
        m["modVersion"] = info.get("version")
        m["modApiVersion"] = info.get("apiVersion")
        m["modHash"] = info.get("hash")
        ref = v.node(content, "ModReference")
        m["modOrigin"] = ({"origin": v.prim(v.get(ref, "ModOrigin", "Origin")), "value": v.s(ref, "ModOrigin", "Value")}
                          if ref is not None else None)
        view = self._mod_view(content)
        for name, e in view["axes"].items():
            if name != "Color" and e and e.strip() not in ("", "<>"):
                m["axes"].setdefault(name, e)
        m["modAxes"] = view["axes"]
        m["modProperties"] = view["properties"]
        m["modPropertyTypes"] = view["propertyTypes"]
        layers = []
        for item in v.items(v.get(content, "LayerCollection", "Items")):
            if not isinstance(item, sg.Node):
                continue
            layer = v.node(item, "Layer")
            rec = {"title": v.s(item, "TitleExpression", "Expression"),
                   "type": v.s(layer, "Type") if layer is not None else None}
            if layer is not None:
                data = v.node(layer, "Data")
                if data is not None:
                    rec.update(self._data_links(data))
                lv = self._mod_view(layer)
                rec["axes"], rec["properties"], rec["propertyTypes"] = lv["axes"], lv["properties"], lv["propertyTypes"]
            layers.append(rec)
        m["modLayers"] = layers

    def _mod_view(self, node):
        """{axes {name: expression ('' when empty)}, properties {name: value}, propertyTypes {name: string |
        integer | double | boolean}} of a mod's main view or of one layer; the color axis (a separate ColorAxis
        field, null when the manifest declares none) is the axis "Color"."""
        v = self.v
        axes = {}
        for key, ax in v.kv(v.get(node, "AxisCollection", "Axes")):
            name = v.prim(key)
            if name is not None:
                axes[name] = v.expr(ax) or ""
        color = v.node(node, "ColorAxis")
        if color is not None:
            axes["Color"] = v.expr(color) or ""
        props, types = {}, {}
        for key, p in v.kv(node.get("Properties")):
            if isinstance(p, sg.Node):
                name = v.prim(key)
                props[name] = v.value(p.get("Value"))
                types[name] = MOD_PROPERTY_TYPES.get(v.tshort(p), v.tshort(p))
        return {"axes": axes, "properties": props, "propertyTypes": types}

    def _map_layers(self, content):
        v = self.v
        out = []
        for layer in v.items(v.get(content, "Layers", "Items")):
            if not isinstance(layer, sg.Node):
                continue
            t = layer.type.short if layer.type else "?"
            rec = {"class": t, "title": v.s(layer, "Title"), "enabled": v.b(layer, "Enabled")}
            viz = v.node(layer, "Visualization")
            if viz is not None:
                vt = v.s(viz, "TypeId", "Name")
                rec["kind"] = {"Spotfire.WebMarkerLayerVisualization": "marker",
                               "Spotfire.WebFeatureLayerVisualization": "feature"}.get(vt, vt)
                rec["table"] = v.s(viz, "Data", "DataTable", "Name")
                rec["axes"] = self.collect_axes(viz, vt)
            else:
                rec["kind"] = "tile" if "Tile" in t else t
            out.append(rec)
        return out

    # -- document properties, scripts, triggers --------------------------------------------------
    def _analysis_properties(self):
        v = self.v
        reg = v.node(self.G.root, "DataManager", "PropertyRegistry", "AnalysisProperties")
        return [p for p in v.items(v.get(reg, "Properties")) if isinstance(p, sg.Node)]

    def document_properties(self):
        v = self.v
        out = []
        for dp in self._analysis_properties():
            attrs = v.enum(dp, "Attributes") or ""
            flags = [a.strip() for a in attrs.split(",") if a.strip()]
            if "IsStandard" in flags:
                continue
            out.append({
                "name": v.s(dp, "Name"),
                "type": v.s(dp, "DataType", "name"),
                "value": v.value(dp.get("Value")),
                "attributes": flags,
                "listValued": "IsListValued" in flags,
                "description": v.s(dp, "Description") or "",
            })
        return out

    def triggers(self):
        v = self.v
        out = []
        sm = v.node(self.G.root, "ScriptManager")
        for h in v.items(v.get(sm, "ScriptEventHandlers")):
            if not isinstance(h, sg.Node):
                continue
            mp = v.node(h, "DataPropertyReference")
            ms = v.node(h, "ScriptReference")
            out.append({"property": self.prop_by_managed.get(mp.id) if mp is not None else None,
                        "script": self.script_name(ms) if ms is not None else None,
                        "arguments": self.script_args(ms) if ms is not None else {},
                        "handler": h.type.short if h.type else None})
        return out

    # -- data functions --------------------------------------------------------------------------
    def data_functions(self):
        v = self.v
        out = []
        for d in self.G.nodes_of("DataFunction", exact=True):
            impl = v.node(d, "FunctionImpl")
            info = parse_function_definition(v.s(impl, "FunctionDefinition", "Data"))
            input_types = {}
            for key, inp in v.kv(v.get(d, "Inputs", "Items")):
                input_types[v.prim(key)] = v.enum(inp, "InputType")
            args = dict((a["name"], a) for a in info["inputs"])
            inputs = []
            seen = set()
            for key, val in v.kv(v.get(impl, "Inputs", "Inputs")):
                name = v.prim(key)
                seen.add(name)
                rec = {"name": name, "expression": None, "inputType": input_types.get(name),
                       "binding": v.tshort(val)}
                if isinstance(val, sg.Node):
                    raw = v.s(val, "Expression", "Expression")
                    rec["expression"] = raw if self.reveal_secrets else safe_expr(name, raw)
                    if credential_name(name) and raw and raw != safe_expr(name, raw):
                        rec["secretConstant"] = True          # a non-placeholder string constant
                    rec["includeActiveFiltering"] = v.b(val, "IncludeActiveFiltering")
                a = args.get(name)
                if a:
                    rec["argumentType"] = a["argumentType"]
                    rec["allowedTypes"] = a["allowedTypes"]
                inputs.append(rec)
            for a in info["inputs"]:
                if a["name"] not in seen:
                    inputs.append({"name": a["name"], "expression": None, "inputType": None, "binding": None,
                                   "argumentType": a["argumentType"], "allowedTypes": a["allowedTypes"]})
            outputs = []
            for key, val in v.kv(v.get(impl, "Outputs", "Outputs")):
                name = v.prim(key)
                t = v.tshort(val)
                rec = {"name": name, "kind": t, "target": None}
                if t == "TableOutputImpl":
                    prod = v.node(val, "Reference", "Reference")
                    rec["kind"] = "table"
                    rec["target"] = self.table_by_producer.get(prod.id) if prod is not None else None
                    rec["suggestedName"] = v.s(val, "SuggestedName")
                    if rec["target"] is None:
                        rec["target"] = rec["suggestedName"]
                elif t == "PropertyOutputImpl":
                    rec["kind"] = "property"
                    rec["target"] = v.s(val, "PropertyName")
                elif t == "ReplaceDataOutputImpl":
                    rec["kind"] = "replaceTable"
                    rec["target"] = v.s(val, "TableReference", "Name")
                outputs.append(rec)
            out.append({
                "name": v.s(d, "Name"),
                "displayName": info["displayName"],
                "functionName": info["functionName"],
                "description": info["description"],
                "executor": info["executor"],
                "script": info["script"],
                "dataframe": info["dataframe"],
                "updateBehavior": v.enum(impl, "UpdateBehavior"),
                "approved": info["approved"],
                "inputs": inputs,
                "outputs": outputs,
                "definitionOutputs": info["outputs"],
            })
        return out

    # -- tables ----------------------------------------------------------------------------------
    def _formatter(self, fmt):
        v = self.v
        if fmt is None:
            return None
        t = fmt.type.short if fmt.type else "?"
        custom = v.s(fmt, "FormatStringV40")
        if custom:
            return custom
        fs = v.s(fmt, "FormatString")
        if fs and not fs.startswith("__SPOTFIRE_NUMBERFORMATTER"):
            return fs
        cat = v.enum(fmt, "Category")
        digits = v.num(fmt, "DecimalDigits")
        if cat:
            return "%s:%s%s" % (t, cat, "" if digits is None or digits < 0 else "(%d)" % digits)
        return t

    def _assigned(self, holder, key):
        """AssignedValue of DataPropertyContainer.ListenableProperties[key] (lower-case key)."""
        v = self.v
        for k, mp in v.kv(v.get(holder, "DataPropertyContainer", "ListenableProperties")):
            if v.prim(k) == key and isinstance(mp, sg.Node):
                return v.r(mp.get("AssignedValue"))
        return None

    def tables(self):
        v = self.v
        dm = v.node(self.G.root, "DataManager")
        save = {}
        for ts in v.items(v.get(dm, "PersistentData", "SaveSettings", "tableSettings")):
            if isinstance(ts, sg.Node):
                save[v.guid(ts.get("tableId"))] = v.b(ts, "useLinkedData")
        embed_all = v.b(dm, "PersistentData", "SaveSettings", "embedAllSourceData")
        stored = {}
        tables_arr = v.items(v.get(dm, "PersistentData", "EmbeddedDataTables"))
        for pi in v.items(v.get(dm, "PersistentData", "EmbeddedCacheItems", "ProducerItems")):
            if not isinstance(pi, sg.Node):
                continue
            idx = v.num(pi, "Index")
            if isinstance(idx, int) and 0 <= idx < len(tables_arr) and isinstance(tables_arr[idx], sg.Node):
                stored[v.s(pi, "Key")] = v.s(tables_arr[idx], "TableId")
        out = []
        for t in v.items(v.get(dm, "Tables", "Items")):
            if not isinstance(t, sg.Node):
                continue
            tid = v.guid(t.get("Id"))
            columns = []
            for c in v.items(v.get(t, "Columns", "Items")):
                if not isinstance(c, sg.Node):
                    continue
                src = v.node(c, "Source")
                col = {"name": v.s(c, "Name"), "type": v.s(c, "DataType", "name"),
                       "format": self._formatter(self._assigned(src, "formatter"))}
                desc = self._assigned(src, "description")
                if isinstance(desc, sg.Str) and desc.value:
                    col["description"] = decode_persisted(desc.value)
                st = v.tshort(src)
                if st == "CalculatedColumnImpl":
                    col["calculated"] = v.s(src, "OwnedColumnProducer", "ExpressionTexts", "Expression")
                elif st == "HierarchyColumnImpl":
                    col["hierarchy"] = v.s(src, "OwnedColumnProducer", "ExpressionTexts", "Expression")
                columns.append(col)
            prods = [v.r(t.get("ColumnProducer"))] + v.items(t.get("ColumnProducers"))
            prods = [p for i, p in enumerate(prods) if isinstance(p, sg.Node) and p not in prods[:i]]
            source_type, file_path, caching, data_function, stored_entry = None, None, None, None, None
            source_table = None
            for p in prods:
                pt = p.type.short if p.type else "?"
                key = v.s(p, "ProducerKey")
                if key and key in stored and stored_entry is None:
                    stored_entry = "DataTables/" + stored[key]
                if p.get("DataFlow") is not None:            # SourceColumnProducer, DataTableDataSource...
                    ds = v.node(p, "DataFlow", "DataSource")
                    if source_type is None:
                        source_type = ds.type.short if ds is not None and ds.type else pt
                        file_path = v.s(ds, "FilePath") if ds is not None else None
                    if source_table is None and v.node(p, "SourceTable") is not None:
                        source_table = v.s(p, "SourceTable", "Name")
                    caching = caching or v.enum(p, "CachingBehavior")
                elif pt == "ExternalColumnProducer":
                    impl = v.node(p, "NeedsRefreshComputer")
                    name = self.df_by_impl.get(impl.id) if impl is not None else None
                    if name and data_function is None:
                        data_function = name
                    if source_type is None:
                        source_type = "DataFunction" if name else pt
            linked = save.get(tid)
            has_entry = bool(stored_entry and stored_entry in self.a.names)
            embedded = bool(has_entry or caching == "Embedded" or linked is False or embed_all)
            if caching == "Linked" and not has_entry and linked is not False and not embed_all:
                embedded = False
            desc = self._assigned(t, "description")
            out.append({
                "name": v.s(t, "Name"),
                "id": tid,
                "columns": columns,
                "rowCount": None,          # rows live in DataTables/<id> in Spotfire's internal format
                "sourceType": source_type,
                "dataFunction": data_function,
                "sourceTable": source_table,
                "filePath": file_path,
                "embedded": embedded,
                "cachingBehavior": caching,
                "useLinkedData": linked,
                "storedData": stored_entry if has_entry else None,
                "description": decode_persisted(desc.value) if isinstance(desc, sg.Str) else None,
            })
        return out

    def relations(self):
        v = self.v
        out = []
        for r in v.items(v.get(self.G.root, "DataManager", "Relations", "Items")):
            if isinstance(r, sg.Node):
                expr = v.s(r, "Expression") or ""
                out.append({"left": v.s(r, "LeftTableName"), "right": v.s(r, "RightTableName"),
                            "expression": expr, "pairs": relation_pairs(expr)})
        return out

    def markings(self):
        v = self.v
        dm = v.node(self.G.root, "DataManager")
        default = v.node(dm, "Markings", "DefaultMarking")
        out = []
        for mk in v.items(v.get(dm, "Markings", "Items")):
            if isinstance(mk, sg.Node):
                out.append({"name": v.s(mk, "Name"), "color": v.color(mk.get("Color")),
                            "default": mk is default,
                            "selectionsCount": v.num(mk, "EmbeddedSelectionsCount"),
                            "partialSelections": len(v.items(mk.get("PartialSelections")))})
        return out

    def filtering_schemes(self):
        v = self.v
        dm = v.node(self.G.root, "DataManager")
        default = v.node(dm, "Filterings", "DefaultFiltering")
        return [{"name": v.s(f, "Name"), "default": f is default}
                for f in v.items(v.get(dm, "Filterings", "Items")) if isinstance(f, sg.Node)]

    def mods(self):
        """Document.ModManager.ManagedMods (ManagedVisualizationMod / ManagedActionMod {ModId, ModOrigin}) with
        the embedded container of each (Mods/mod-<n>.asice, matched by the id in its mod-manifest.json, not by
        <n>): kind, archive (None = not embedded), digest, embeddedVersion, embeddedFiles {name: sha256}.
        Embedded containers no managed mod names are listed after them with origin None."""
        v = self.v
        embedded = self.a.embedded_mods()
        by_id = {}
        for e in embedded:
            if e.get("error"):
                self.notes.append("embedded mod %s not readable: %s" % (e["archive"], e["error"]))
            elif not e.get("id"):
                self.notes.append("embedded mod %s has no readable mod-manifest.json" % e["archive"])
            elif e["id"] not in by_id:
                by_id[e["id"]] = e
        out, seen = [], set()
        for mm in v.items(v.get(self.G.root, "ModManager", "ManagedMods")):
            if not isinstance(mm, sg.Node):
                continue
            mod_id = v.s(mm, "ModId")
            kind = ("visualization" if mm.type is not None and mm.type.is_a("ManagedVisualizationMod") else
                    "action" if mm.type is not None and mm.type.is_a("ManagedActionMod") else v.tshort(mm))
            rec = {"modId": mod_id, "origin": v.enum(mm, "ModOrigin", "Origin"),
                   "value": v.s(mm, "ModOrigin", "Value"), "kind": kind}
            rec.update(self._embedded_fields(by_id.get(mod_id)))
            seen.add(mod_id)
            out.append(rec)
        for mod_id, e in by_id.items():
            if mod_id not in seen:
                kind = {"visualization": "visualization", "action": "action"}.get(str(e.get("type") or "").lower())
                rec = {"modId": mod_id, "origin": None, "value": None, "kind": kind}
                rec.update(self._embedded_fields(e))
                out.append(rec)
        return out

    @staticmethod
    def _embedded_fields(e):
        if e is None:
            return {"archive": None, "digest": None, "embeddedVersion": None, "embeddedFiles": {}}
        return {"archive": e["archive"], "digest": e.get("digest"), "embeddedVersion": e.get("version"),
                "embeddedFiles": dict(e.get("files") or {})}


def relation_pairs(expression):
    """[[left column, right column]] of a relation expression: ([L].[a]=[R].[b]) and ... (the builder writes
    [L].[a]=[R].[b] and ...). Identifiers are masked first, so 'and' inside a column name never splits."""
    idents = []

    def mask(m):
        idents.append(m.group(1).replace("]]", "]"))
        return "\x00%d\x00" % (len(idents) - 1)

    masked = re.sub(r"\[((?:[^\]]|\]\])*)\]", mask, expression or "")
    pairs = []
    for part in re.split(r"(?i)\band\b", masked):
        refs = [idents[int(i)] for i in re.findall(r"\x00(\d+)\x00", part)]
        if len(refs) >= 4:
            pairs.append([refs[1], refs[3]])
    return pairs


def build_model(dxp_path, reveal_secrets=False):
    """(model dict, ModelBuilder, DxpArchive) for a DXP file. Raises DxpError. String constants bound to
    credential-like data-function inputs (Password, Token, ...) are masked unless reveal_secrets."""
    archive = DxpArchive(dxp_path)
    try:
        builder = ModelBuilder(archive, reveal_secrets=reveal_secrets)
        model = builder.build()
    except etree.XMLSyntaxError as e:
        archive.close()
        raise DxpError("cannot parse %s in %s: %s" % (archive.main_entry, dxp_path, e))
    return model, builder, archive


# ---------------------------------------------------------------------------------------------------
# expected expressions: the builder's documented spec interpretation (lib/60_charts.py, 70_tables.py)
# ---------------------------------------------------------------------------------------------------
def _blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _top_level_chars(text):
    out, depth, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            i = _skip_ident(text, i)
            continue
        if ch in "\"'":
            i = _skip_string(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            out.append((i, ch))
        i += 1
    return out


def measure_alias(part):
    """(body, alias) of one measure: 'Sum([A]) as [Total A]' -> ('Sum([A])', 'Total A') (60_charts)."""
    n = len(part)
    found = None
    for i, ch in _top_level_chars(part):
        if ch not in "aA" or part[i:i + 2].lower() != "as":
            continue
        before = part[i - 1] if i > 0 else ""
        after = part[i + 2] if i + 2 < n else ""
        if before and (before.isspace() or before in ")]") and (after.isspace() or after == "["):
            found = i
    if found is None:
        return part.strip(), None
    rest = part[found + 2:].strip()
    if rest.startswith("[") and _skip_ident(rest, 0) == len(rest):
        return part[:found].strip(), rest[1:-1].replace("]]", "]")
    if rest and (rest[0].isalpha() or rest[0] == "_") and all(c.isalnum() or c == "_" for c in rest):
        return part[:found].strip(), rest
    return part.strip(), None


def display_name(body):
    """Spotfire's name of an unaliased measure: the expression without identifier brackets."""
    out, i, n = [], 0, len(body)
    while i < n:
        ch = body[i]
        if ch == "[":
            j = _skip_ident(body, i)
            out.append(body[i + 1:max(i + 1, j - 1)].replace("]]", "]"))
            i = j
            continue
        if ch in "\"'":
            j = _skip_string(body, i)
            out.append(body[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip()


class Expressions(object):
    """Spec value -> the expression the builder writes, for one visual's table columns."""

    NAMES = "[Axis.Default.Names]"

    def __init__(self, columns):
        self.columns = set(columns or [])

    @staticmethod
    def text(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        return str(value).strip()

    def column(self, text):
        if text and text[0] not in "[<" and text in self.columns:
            return esc_ident(text)
        return text

    def expr(self, value):
        if isinstance(value, (list, tuple)):
            return ", ".join(self.expr(v) for v in value if not _blank(v))
        if value is None:
            return ""
        return props_shorthand(self.column(self.text(value)))

    @staticmethod
    def unwrap(text):
        t = text.strip()
        if len(t) >= 2 and t[0] == "<" and t[-1] == ">":
            return t[1:-1].strip()
        return t

    def cat(self, value):
        levels = []
        for item in _as_list(value):
            if _blank(item):
                continue
            inner = self.unwrap(self.text(item))
            if inner:
                levels.append(props_shorthand(self.column(inner)))
        return "<" + " NEST ".join(levels) + ">" if levels else "<>"

    def levels(self, value):
        out = []
        for item in _as_list(value):
            t = str(item).strip()
            if t.startswith("<") and t.endswith(">"):
                t = t[1:-1].strip()
            if not t:
                continue
            if not t.startswith("[") and t in self.columns:
                t = esc_ident(t)
            out.append(props_shorthand(t))
        return out

    def x(self, value):
        return self.cat(value) if isinstance(value, (list, tuple)) else self.expr(value)

    @staticmethod
    def count(expression):
        return len(split_top(Expressions.unwrap(expression or "")))

    @staticmethod
    def titled(expression, title):
        """`expression as [title]` (one measure only, as the builder folds scale titles in)."""
        if _blank(title) or not expression:
            return expression
        text = expression.strip()
        wrapped = len(text) >= 2 and text[0] == "<" and text[-1] == ">"
        inner = text[1:-1].strip() if wrapped else text
        parts = split_top(inner)
        if len(parts) != 1:
            return expression
        out = measure_alias(parts[0])[0] + " as " + esc_ident(str(title))
        return "<" + out + ">" if wrapped else out


def _scale_title(sspec):
    if isinstance(sspec, dict) and not _blank(sspec.get("title")):
        return str(sspec["title"])
    return None


def expected_axes(vspec, columns):
    """[(axis name in the model, expected expression, spec field)] for a chart, cross table, graphical
    table or KPI chart. Only axes the spec sets (plus the documented builder defaults). Mod axes are typed by
    the mod's manifest: mod_axis_text, Checker.check_mod."""
    t = vspec.get("type")
    E = Expressions(columns)
    out = []

    def add(axis, expression, field):
        out.append((axis, expression, field))

    def color(y=None, default_names=False):
        if not _blank(vspec.get("colorBy")):
            cb = vspec["colorBy"]
            add("ColorAxis", E.cat(cb) if isinstance(cb, (list, tuple)) else E.expr(cb), "colorBy")
        elif default_names or (y is not None and Expressions.count(y) > 1):
            add("ColorAxis", "<" + Expressions.NAMES + ">", "colorBy (Column Names default)")

    def trellis():
        ts = vspec.get("trellis")
        if not isinstance(ts, dict):
            return
        for key, axis in (("panelBy", "Trellis.PanelAxis"), ("rowsBy", "Trellis.RowAxis"),
                          ("columnsBy", "Trellis.ColumnAxis")):
            if not _blank(ts.get(key)):
                add(axis, E.cat(ts[key]), "trellis." + key)

    if t in ("lineChart", "barChart", "scatterPlot"):
        x = E.x(vspec.get("x"))
        y = E.expr(vspec.get("y"))
        add("XAxis", E.titled(x, _scale_title(vspec.get("xScale"))), "x")
        add("YAxis", E.titled(y, _scale_title(vspec.get("yScale"))), "y")
        color(y)
        if t == "lineChart" and not _blank(vspec.get("lineBy")):
            add("LineByAxis", E.cat(vspec["lineBy"]), "lineBy")
        if t == "scatterPlot":
            if not _blank(vspec.get("sizeBy")):
                add("SizeAxis", E.expr(vspec["sizeBy"]), "sizeBy")
            if not _blank(vspec.get("shapeBy")):
                add("ShapeAxis", E.cat(vspec["shapeBy"]), "shapeBy")
            if not _blank(vspec.get("labelBy")):
                add("LabelColumn", E.expr(vspec["labelBy"]), "labelBy")
            if not _blank(vspec.get("lineBy")):
                add("LineConnection.ConnectionAxis", E.cat(vspec["lineBy"]), "lineBy")
        trellis()
    elif t == "histogram":
        col = vspec.get("column")
        bins = vspec.get("bins") if vspec.get("bins") is not None else 20
        text = E.text(col) if col is not None else ""
        name = None
        if text and text[0] not in "[<" and text in E.columns:
            name = text
        elif text.startswith("[") and _skip_ident(text, 0) == len(text):
            name = text[1:-1].replace("]]", "]")
        x = "BinByEvenIntervals(%s, %s)" % (E.expr(col), int(bins) if isinstance(bins, (int, float)) else bins)
        if name:
            x += " as " + esc_ident(name)
        add("XAxis", E.titled(x, _scale_title(vspec.get("xScale"))), "column/bins")
        add("YAxis", E.titled("Count()", _scale_title(vspec.get("yScale"))), "(histogram count)")
        color()
        trellis()
    elif t == "combinationChart":
        add("XAxis", E.titled(E.x(vspec.get("x")), _scale_title(vspec.get("xScale"))), "x")
        parts = []
        for item in _as_list(vspec.get("series")):
            expression = item.get("expression") if isinstance(item, dict) else item
            if _blank(expression):
                continue
            raw = E.expr(expression)
            pieces = split_top(raw)
            if len(pieces) != 1:
                parts.append(raw)
                continue
            body, alias = measure_alias(pieces[0])
            parts.append(body + " as " + esc_ident(display_name(body)) if alias is None else pieces[0])
        add("YAxis", ", ".join(parts), "series")
        color(default_names=True)
        trellis()
    elif t == "scatterPlot3D":
        for key, axis in (("x", "XAxis"), ("y", "YAxis"), ("z", "ZAxis")):
            add(axis, E.titled(E.expr(vspec.get(key)), _scale_title(vspec.get(key + "Scale"))), key)
        if not _blank(vspec.get("sizeBy")):
            add("SizeAxis", E.expr(vspec["sizeBy"]), "sizeBy")
        color()
        trellis()
    elif t == "pieChart":
        add("ColorAxis", E.cat(vspec.get("sector")), "sector")
        add("SectorSizeAxis", E.expr(vspec.get("size")), "size")
        trellis()
    elif t == "boxPlot":
        y = E.expr(vspec.get("y"))
        add("XAxis", E.titled(E.cat(vspec.get("x")), _scale_title(vspec.get("xScale"))), "x")
        add("YAxis", E.titled(y, _scale_title(vspec.get("yScale"))), "y")
        color(y)
        trellis()
    elif t == "heatMap":
        add("XAxis", E.titled(E.cat(vspec.get("x")), _scale_title(vspec.get("xScale"))), "x")
        add("YAxis", E.titled(E.cat(vspec.get("y")), _scale_title(vspec.get("yScale"))), "y")
        add("MeasureAxis", E.expr(vspec.get("value")), "value")
        trellis()
    elif t == "treemap":
        add("HierarchyAxis", E.cat(vspec.get("hierarchy")), "hierarchy")
        add("SizeAxis", E.expr(vspec.get("size")), "size")
        if not _blank(vspec.get("colorBy")):
            cb = vspec["colorBy"]
            text = E.cat(cb) if isinstance(cb, (list, tuple)) else E.expr(cb)
            inner = Expressions.unwrap(text)
            if text.strip().startswith("<") and inner and " nest " not in (" " + inner.lower() + " "):
                text = "UniqueConcatenate(" + inner + ")"
            add("ColorAxis", text, "colorBy")
        trellis()
    elif t == "waterfallChart":
        add("XAxis", E.titled(E.cat(vspec.get("category")), _scale_title(vspec.get("xScale"))), "category")
        add("YAxis", E.titled(E.expr(vspec.get("value")), _scale_title(vspec.get("yScale"))), "value")
        color()
        trellis()
    elif t == "crossTable":
        measures = _as_list(vspec.get("measures"))
        if measures:
            add("MeasureAxis", ", ".join(props_shorthand(str(m).strip()) for m in measures), "measures")
        rows = E.levels(vspec.get("rows"))
        cols = E.levels(vspec.get("columns"))
        if not any(Expressions.NAMES in lv for lv in rows + cols) and (not cols or len(measures) > 1):
            cols = cols + [Expressions.NAMES]
        add("RowAxis", "<" + " NEST ".join(rows) + ">" if rows else "<>", "rows")
        add("ColumnAxis", "<" + " NEST ".join(cols) + ">" if cols else "<>", "columns")
    elif t == "graphicalTable":
        rows = E.levels(vspec.get("rows"))
        add("RowAxis", "<" + " NEST ".join(rows) + ">" if rows else "<>", "rows")
    elif t == "kpiChart":
        for i, k in enumerate(_as_list(vspec.get("kpis"))):
            if not isinstance(k, dict):
                continue
            if not _blank(k.get("value")):
                add("kpis[%d].YAxis" % i, props_shorthand(str(k["value"]).strip()), "kpis[%d].value" % i)
            if not _blank(k.get("tileBy")):
                lv = E.levels(k["tileBy"])
                add("kpis[%d].TileAxis" % i, "<" + " NEST ".join(lv) + ">" if lv else "<>", "kpis[%d].tileBy" % i)
            if not _blank(k.get("time")):
                add("kpis[%d].XAxis" % i, props_shorthand(str(k["time"]).strip()), "kpis[%d].time" % i)
            if not _blank(k.get("comparative")):
                add("kpis[%d].ComparativeAxis" % i, props_shorthand(str(k["comparative"]).strip()),
                    "kpis[%d].comparative" % i)
    return out


def match_expression(expected, found, alternatives=()):
    """(status, note): expressions compared in expr_key form; Spotfire's categorical form <...> and the
    expression the builder recorded in build-report.json are accepted."""
    ek, fk = expr_key(expected), expr_key(found)
    if ek == fk:
        return "PASS", None
    if fk and strip_angle(ek) == strip_angle(fk):
        return "PASS", "accepted Spotfire's form with/without angle brackets"
    for alt in alternatives:
        if alt is None:
            continue
        ak = expr_key(alt)
        if ak and (ak == fk or strip_angle(ak) == strip_angle(fk)):
            return "PASS", "matches the expression the builder recorded"
    return "FAIL", None


# ---------------------------------------------------------------------------------------------------
# visualization mods: the manifest types every axis and property (references/spec-format.md "Visualization mods"; the same
# reading as scripts/t3/mod.py, kept here so the check stays independent of the converter)
# ---------------------------------------------------------------------------------------------------
def mod_layer_def(manifest, layer_type):
    """The manifest's layers[] entry of a layer type, or None."""
    for entry in _as_list((manifest or {}).get("layers")):
        if isinstance(entry, dict) and entry.get("type") == layer_type:
            return entry
    return None


def mod_manifest_axes(manifest, layer_type=None):
    """{axis name: mode} of the mod's main view (layer_type None) or of a layer type, in manifest order: the
    dataViewDefinition axes, plus "Color" (mode "dual") when the view declares a colorAxis. None when the
    manifest has no such layer type."""
    view = manifest if layer_type is None else mod_layer_def(manifest, layer_type)
    if not isinstance(view, dict):
        return None
    dvd = view.get("dataViewDefinition") if isinstance(view.get("dataViewDefinition"), dict) else {}
    out = {}
    for ax in _as_list(dvd.get("axes")):
        if isinstance(ax, dict) and isinstance(ax.get("name"), str):
            out[ax["name"]] = ax.get("mode") if ax.get("mode") in MOD_AXIS_MODES else "continuous"
    if dvd.get("colorAxis"):
        out.setdefault("Color", "dual")
    return out


def mod_manifest_props(manifest, layer_type=None):
    """{property name: type} of the mod's main view (layer_type None) or of a layer type; None when the
    manifest has no such layer type."""
    view = manifest if layer_type is None else mod_layer_def(manifest, layer_type)
    if not isinstance(view, dict):
        return None
    return dict((p["name"], p.get("type")) for p in _as_list(view.get("properties"))
                if isinstance(p, dict) and isinstance(p.get("name"), str))


def mod_axis_text(value, mode, columns=()):
    """The expression the builder writes on a mod axis for a spec value: None = the axis is left as the mod
    configures it, "" = cleared; [$P] becomes DocumentProperty("P") everywhere.
      categorical         <...> as written; a bare column name -> <[Col]>; a list -> <[A] NEST [B]>
      continuous, dual    as written; a bare column name -> [Col]; a list -> the measures joined with ", "
      None (no manifest)  as written; a list joined with ", "
    A bare column name is one of `columns` (the view's table) not already in [...] or <...>."""
    if value is None:
        return None
    E = Expressions(columns)
    items = [x for x in value if not _blank(x)] if isinstance(value, (list, tuple)) else None
    if mode == "categorical":
        if items is not None:
            levels = [props_shorthand(E.column(E.unwrap(E.text(x)))) for x in items]
            return "<" + " NEST ".join(levels) + ">" if levels else ""
        text = E.text(value)
        if not text:
            return ""
        return props_shorthand(text) if text.startswith("<") else "<" + props_shorthand(E.column(text)) + ">"
    if mode is None:
        if items is not None:
            return ", ".join(props_shorthand(E.text(x)) for x in items)
        return props_shorthand(E.text(value))
    if items is not None:
        return ", ".join(props_shorthand(E.column(E.text(x))) for x in items)
    return props_shorthand(E.column(E.text(value)))


def mod_prop_matches(want, got, ptype=None):
    """True when a persisted mod property value is the spec value read with the manifest type (string: a JSON
    object or list is compared as JSON; integer and double: numerically; boolean: as a boolean)."""
    if isinstance(want, (dict, list)) and isinstance(got, str):
        try:
            got = json.loads(got)
        except ValueError:
            return False
        return want == got
    if ptype == "boolean" or isinstance(want, bool) or isinstance(got, bool):
        return isinstance(want, bool) and isinstance(got, bool) and want == got
    if ptype == "string" or isinstance(want, str) or isinstance(got, str):
        return isinstance(want, str) and isinstance(got, str) and want == got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        if ptype == "integer" and (float(want) != int(want) or not isinstance(got, int)):
            return False
        return abs(float(want) - float(got)) < 1e-9
    return want == got


def trigger_text(trigger):
    """One line for a persisted action trigger: 'FloatingButton -> mod/script' or 'FloatingButton -> IronPython
    script Name'."""
    if trigger.get("mod") is not None or trigger.get("script") is not None:
        return "%s -> %s/%s" % (trigger.get("display"), trigger.get("mod"), trigger.get("script"))
    if "ironPython" in trigger:
        return "%s -> IronPython script %s" % (trigger.get("display"), trigger.get("ironPython"))
    return "%s -> %s" % (trigger.get("display"), trigger.get("target"))


def pages_expected(tree):
    """{visual id: [x, y, width, height]} in the 100000 x 100000 page space (lib/50_pages._pages_expected)."""
    out = {}

    def weight(item):
        w = item.get("weight", 1) if isinstance(item, dict) else 1
        return float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0 else 1.0

    def cut(share):
        return int(share * LAYOUT_SPACE + 1e-6)

    def rec(node, xs, ys, xe, ye):
        kind = "row" if "row" in node else "column"
        items = [i for i in node.get(kind) or [] if isinstance(i, dict)]
        if not items:
            return
        weights = [weight(i) for i in items]
        total = sum(weights)
        low, high = xs if kind == "row" else ys
        start, edge = xe if kind == "row" else ye
        pos = low
        for i, item in enumerate(items):
            nxt = pos + (high - low) * weights[i] / total
            end = cut(nxt) if i < len(items) - 1 else edge
            if kind == "row":
                child = ((pos, nxt), ys, (start, end), ye)
            else:
                child = (xs, (pos, nxt), xe, (start, end))
            if "visual" in item:
                cxe, cye = child[2], child[3]
                out[item["visual"]] = [cxe[0], cye[0], cxe[1] - cxe[0], cye[1] - cye[0]]
            elif "row" in item or "column" in item:
                rec(item, *child)
            pos = nxt
            start = end + LAYOUT_SPLITTER

    if isinstance(tree, dict) and ("row" in tree or "column" in tree):
        rec(tree, (0.0, 1.0), (0.0, 1.0), (0, LAYOUT_SPACE), (0, LAYOUT_SPACE))
    return out


def layout_visual_ids(node):
    if not isinstance(node, dict):
        return []
    if "visual" in node:
        return [node["visual"]]
    kind = "row" if "row" in node else "column"
    out = []
    for item in node.get(kind) or []:
        out += layout_visual_ids(item)
    return out


def textarea_words(text):
    """'panelControls' -> ['Panel', 'Controls'] (lib/80_textareas._textareas_words)."""
    words, current, prev = [], "", ""
    for ch in str(text or ""):
        if not ch.isalnum():
            if current:
                words.append(current)
            current = ""
        elif ch.isupper() and current and not prev.isupper():
            words.append(current)
            current = ch
        else:
            current += ch
        prev = ch
    if current:
        words.append(current)
    if not words:
        return ["Text", "Area"]
    return [w[:1].upper() + w[1:] for w in words]


def textarea_safe_name(text):
    """lib/80_textareas._textareas_safe_name."""
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(text or "")) or "textarea"


def normalize_color(text):
    """'#RRGGBB' / '#AARRGGBB' -> '#AARRGGBB' upper case."""
    if not isinstance(text, str):
        return text
    t = text.strip().upper()
    if re.match(r"^#[0-9A-F]{6}$", t):
        return "#FF" + t[1:]
    return t


def json_ints(value):
    """Theme numbers as Spotfire reads them: 4.0 -> 4 (lib/10_document._document_json_ints)."""
    if isinstance(value, dict):
        return dict((k, json_ints(v)) for k, v in value.items())
    if isinstance(value, list):
        return [json_ints(v) for v in value]
    if isinstance(value, float) and value == value and abs(value) < 1e15 and value == int(value):
        return int(value)
    return value


def theme_base_normalised(base, found):
    """The general.baseTheme Spotfire stored for an "...Sfx" base when it dropped the suffix
    (a LightSfx theme persists baseTheme "Light" and baseThemeSfx "LightSfx" in DXPs saved by Analyst
    15.0), else None. Only baseTheme is normalised; every other key is compared as is."""
    general = found.get("general") if isinstance(found, dict) else None
    if not isinstance(general, dict) or not isinstance(base, str) or not base.endswith("Sfx"):
        return None
    stored = general.get("baseTheme")
    if stored == base[:-3] and general.get("baseThemeSfx", base) == base:
        return stored
    return None


def first_difference(a, b, width=60):
    a, b = a or "", b or ""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    if i == n and len(a) == len(b):
        return None
    line = a.count("\n", 0, i) + 1
    return "first difference at line %d: spec %r, found %r" % (line, a[i:i + width], b[i:i + width])


def compare_value(dtype, expected, found):
    """True when a document-property value equals the spec default (types as references/spec-format.md writes them)."""
    if isinstance(expected, list) or isinstance(found, list):
        if not isinstance(expected, list) or not isinstance(found, list) or len(expected) != len(found):
            return False
        return all(compare_value(dtype, e, f) for e, f in zip(expected, found))
    if expected is None:
        return found in (None, "")
    if found is None:
        return False
    try:
        if dtype in ("Integer", "LongInteger"):
            return int(expected) == int(found)
        if dtype in ("Real", "SingleReal", "Currency"):
            e, f = float(expected), float(found)
            tol = 1e-6 if dtype == "SingleReal" else 1e-9
            return abs(e - f) <= tol * max(1.0, abs(e))
        if dtype == "Boolean":
            if isinstance(found, str):
                found = found.lower() == "true"
            return bool(expected) == bool(found)
        if dtype == "Date":
            return str(found)[:10] == str(expected)[:10]
        if dtype == "DateTime":
            e = datetime.datetime.fromisoformat(str(expected).replace("Z", ""))
            f = datetime.datetime.fromisoformat(str(found).replace("Z", "")[:26])
            return e.replace(tzinfo=None) == f.replace(tzinfo=None)
        if dtype == "Time":
            f = str(found)
            ftime = f.split("T", 1)[1] if "T" in f else f
            return _seconds(ftime) == _seconds(str(expected))
        if dtype == "TimeSpan":
            return _seconds(str(found)) == _seconds(str(expected))
    except (ValueError, TypeError):
        return False
    return str(expected) == str(found)


def _seconds(text):
    m = re.match(r"^\s*(-)?(?:(\d+)[.\s]|(\d+) days?, )?(\d{1,2}):(\d{2})(?::(\d{2})(\.\d+)?)?", text)
    if not m:
        raise ValueError(text)
    days = int(m.group(2) or m.group(3) or 0)
    total = days * 86400 + int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6) or 0)
    total += float(m.group(7) or 0)
    return -total if m.group(1) else total


# ---------------------------------------------------------------------------------------------------
# hygiene patterns (standards-checklist 1.2, 6.2)
# ---------------------------------------------------------------------------------------------------
_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"'<>|;\r\n\t&*?]{0,240}")
_UNC_RE = re.compile(r"(?<![\\\w])\\\\[A-Za-z0-9][\w.$-]+\\[\w.$ -]+|(?<![\\\w])\\{4}[A-Za-z0-9][\w.$-]+\\{2}\w[\w.$ -]*")
_USERS_DIR_RE = re.compile(r"[\\/]{1,2}Users[\\/]{1,2}([^\\/\"<>|\r\n]+?)(?=[\\/])", re.I)
_CREDENTIAL_RES = (
    re.compile(r"(?i)\b(password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|"
               r"auth[_-]?token|access[_-]?token|token)\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{3,})[\"']"),
    re.compile(r"(?i)(?:^|[;?&\s\"'])(password|pwd|apikey|api_key|access_token|token)=([^;&\s\"'<>]{3,})"),
)
_CREDENTIAL_NAME_RE = re.compile(r"(?i)(^|\s)(password|passwd|pwd|secret|client ?secret|api ?key|apikey|"
                                 r"access ?key|token|access ?token|auth ?token)$")
_SKIP_HYGIENE_FIELDS = ("StyleSheetText",)
_STRING_LITERAL_RE = re.compile(r'"((?:\\.|[^"\\])*)"|' + r"'((?:\\.|[^'\\])*)'")
_CREDENTIAL_NEEDLES = ("password", "passwd", "pwd", "secret", "api_key", "api-key", "apikey", "access_key",
                       "access-key", "token")


def hit_windows(text, needles, before, after):
    """Merged (start, end) windows around every occurrence of the needles (str.find, C speed)."""
    spans = []
    n = len(text)
    for needle in needles:
        i = text.find(needle)
        while i >= 0:
            spans.append((max(0, i - before), min(n, i + len(needle) + after)))
            i = text.find(needle, i + 1)
    if not spans:
        return []
    spans.sort()
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(x) for x in merged]


def _mask(value):
    value = value or ""
    return (value[:2] + "***") if len(value) > 2 else "***"


def credential_name(name):
    """True for a name that holds a credential: Password, DB Password, dbPassword, API_KEY, Token, ..."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name or "")).replace("_", " ").replace("-", " ").strip()
    return bool(_CREDENTIAL_NAME_RE.search(spaced))


def safe_expr(name, expression):
    """An input expression as shown in the model and the report: non-placeholder string literals of
    credential-like inputs masked (a document-property binding is kept)."""
    if not isinstance(expression, str) or not credential_name(name) or _DOCPROP_RE.match(expression):
        return expression

    def mask(m):
        content = m.group(1) if m.group(1) is not None else m.group(2)
        return m.group(0) if _placeholder_secret(content) else '"%s"' % _mask(content)

    return _STRING_LITERAL_RE.sub(mask, expression)


def _placeholder_secret(value):
    v = (value or "").strip()
    return (not v or set(v) <= set("*xX#.") or v[0] in "${%<" or v.lower() in ("none", "null", "true", "false"))


class Results(object):
    """Check lines: {status, area, path, check, expected?, found?, note?}."""

    def __init__(self):
        self.items = []

    def add(self, status, area, path, check, expected=None, found=None, note=None):
        rec = {"status": status, "area": area, "path": path, "check": check, "expected": expected, "found": found}
        if note:
            rec["note"] = note
        self.items.append(rec)
        return rec

    def ok(self, area, path, check, expected=None, found=None, note=None):
        return self.add("PASS", area, path, check, expected, found, note)

    def fail(self, area, path, check, expected=None, found=None, note=None):
        return self.add("FAIL", area, path, check, expected, found, note)

    def warn(self, area, path, check, expected=None, found=None, note=None):
        return self.add("WARN", area, path, check, expected, found, note)

    def eq(self, area, path, check, expected, found, note=None, bad="FAIL"):
        return self.add("PASS" if expected == found else bad, area, path, check, expected, found, note)

    def counts(self):
        c = {"PASS": 0, "FAIL": 0, "WARN": 0}
        for it in self.items:
            c[it["status"]] = c.get(it["status"], 0) + 1
        return c


def load_dxpgen():
    try:
        import dxpgen
        return dxpgen
    except Exception:            # noqa: BLE001 - any import problem means "not available"
        return None


AREAS = (("document", "Document, archive and theme"), ("pages", "Pages"), ("visuals", "Visuals"),
         ("layout", "Layout"), ("textAreas", "Text areas and controls"), ("properties", "Document properties"),
         ("scripts", "Scripts"), ("triggers", "Property triggers"), ("dataFunctions", "Data functions"),
         ("tables", "Tables"), ("relations", "Relations"), ("markings", "Markings"),
         ("filteringSchemes", "Filtering schemes"), ("filters", "Filter panels"), ("hygiene", "Hygiene"),
         ("naming", "Naming policy"),
         ("build", "Build report"), ("spec", "Spec"))


class Checker(object):
    """check <app>: spec.json + build/build-report.json vs the saved DXP."""

    def __init__(self, app_dir, spec_path, dxpgen, dxp_override=None, preloaded=None):
        """preloaded: (model, ModelBuilder, DxpArchive) from build_model() for the same DXP, reused
        instead of parsing the file again (the caller keeps ownership of the open archive)."""
        self.app_dir = Path(app_dir)
        self.spec_path = Path(spec_path)
        self.dxpgen = dxpgen
        self.dxp_override = dxp_override
        self.preloaded = preloaded
        self.R = Results()
        self.spec = None
        self.raw_spec = None
        self.dxp_path = None
        self.report = None
        self.report_path = None
        self.model = None
        self.mb = None
        self.archive = None
        self.unreadable = set()          # spec items whose files could not be read
        self.raw_doc = None              # spec.json as written (before dxpgen.resolve_spec)
        self._viz = {}                   # vizMods id -> (manifest, project folder) or None
        self._mods_checked = set()       # mod ids whose embedded files are checked
        self.status_code = EXIT_OK
        self.out_dir = self.app_dir / "build"

    # -- driver ----------------------------------------------------------------------------------
    def run(self):
        if not self._load_spec():
            return self._finish(EXIT_USAGE)
        if not self._locate_dxp():
            return self._finish(EXIT_USAGE)
        self._load_report()
        if self.preloaded is not None:
            self.model, self.mb, self.archive = self.preloaded
        else:
            try:
                self.model, self.mb, self.archive = build_model(self.dxp_path)
            except DxpError as e:
                self.R.fail("document", str(self.dxp_path), "readable", "a Spotfire analysis", str(e))
                return self._finish(EXIT_USAGE)
        try:
            self._run_checks()
        finally:
            if self.preloaded is None:
                self.archive.close()
        return self._finish(EXIT_FAIL if self.R.counts()["FAIL"] else EXIT_OK)

    def _run_checks(self):
        steps = (self.check_document, self.check_pages, self.check_trellis, self.check_properties,
                 self.check_scripts,
                 self.check_triggers, self.check_data_functions, self.check_tables, self.check_relations,
                 self.check_markings, self.check_filtering_schemes, self.check_hygiene, self.check_naming,
                 self.check_build_report)
        for step in steps:
            try:
                step()
            except Exception as e:                     # a checker bug must not hide the other checks
                import traceback
                self.R.fail("spec", step.__name__, "verifier error", None, "%s: %s" % (type(e).__name__, e),
                            note=traceback.format_exc(limit=3).replace("\n", " | "))

    # -- inputs ----------------------------------------------------------------------------------
    def _load_spec(self):
        try:
            raw = self.spec_path.read_bytes()
            self.raw_spec = raw
            spec, dups = self.dxpgen.parse_spec_text(raw.decode("utf-8-sig"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            self.R.fail("spec", str(self.spec_path), "spec.json readable", "valid JSON", str(e))
            return False
        if not isinstance(spec, dict):
            self.R.fail("spec", str(self.spec_path), "spec.json is an object", "object", type(spec).__name__)
            return False
        for key in sorted(set(dups)):
            self.R.warn("spec", "spec.json", "duplicate key", None, key, note="JSON keeps only the last one")
        self.raw_doc = copy.deepcopy(spec)
        self.spec = self._resolve(spec)
        return self.spec is not None

    def _resolve(self, spec):
        """dxpgen.resolve_spec after neutralizing file references that cannot be read (warned)."""
        s = copy.deepcopy(spec)

        def readable(rel):
            return isinstance(rel, str) and rel.strip() and (self.app_dir / rel.strip()).is_file()

        app = s.get("app") if isinstance(s.get("app"), dict) else {}
        theme = app.get("theme") if isinstance(app.get("theme"), dict) else None
        if theme and isinstance(theme.get("customStyles"), str) and not readable(theme["customStyles"]):
            self.R.warn("spec", "app.theme.customStyles", "file readable", theme["customStyles"], "missing",
                        note="custom styles are checked as given but not compared")
            theme["customStyles"] = {"_verifyUnreadable": True}       # given, but not comparable
            self.unreadable.add("theme")
        for sc in s.get("scripts") or []:
            if isinstance(sc, dict) and sc.get("file") and not readable(sc["file"]):
                self.R.warn("spec", "scripts '%s'" % sc.get("name"), "file readable", sc["file"], "missing")
                sc.pop("file")
                sc.setdefault("code", "")
                self.unreadable.add(("script", sc.get("name")))
        for d in s.get("dataFunctions") or []:
            if isinstance(d, dict) and d.get("script") and not readable(d["script"]):
                self.R.warn("spec", "dataFunctions '%s'" % d.get("name"), "file readable", d["script"], "missing")
                d.pop("script")
                self.unreadable.add(("dataFunction", d.get("name")))
        for pg in s.get("pages") or []:
            for v in (pg.get("visuals") or []) if isinstance(pg, dict) else []:
                if not isinstance(v, dict) or v.get("type") != "textArea":
                    continue
                html = v.get("html")
                if isinstance(html, str) and html.strip() and not html.lstrip().startswith("<") and not readable(html):
                    self.R.warn("spec", "visual '%s'" % v.get("id"), "html file readable", html, "missing")
                    v["html"] = ""
                    self.unreadable.add(("html", v.get("id")))
                css = v.get("css")
                if isinstance(css, str) and css.strip() and "{" not in css and not readable(css):
                    self.R.warn("spec", "visual '%s'" % v.get("id"), "css file readable", css, "missing")
                    v["css"] = ""
                js = []
                for item in v.get("js") or []:
                    if isinstance(item, str) and not readable(item):
                        self.R.warn("spec", "visual '%s'" % v.get("id"), "js file readable", item, "missing")
                        js.append({"name": Path(item).stem, "code": ""})
                    else:
                        js.append(item)
                if v.get("js"):
                    v["js"] = js
        try:
            return self.dxpgen.resolve_spec(s, self.app_dir)
        except Exception as e:                         # noqa: BLE001
            self.R.fail("spec", str(self.spec_path), "spec resolvable (dxpgen.resolve_spec)", None,
                        "%s: %s" % (type(e).__name__, e), note="run dxpgen.py validate on the app")
            return None

    def _locate_dxp(self):
        app = self.spec.get("app") or {}
        out = self.dxp_override or app.get("output") or ("build/%s.dxp" % app.get("name", "analysis"))
        p = Path(out)
        if not p.is_absolute():
            p = self.app_dir / out
        self.dxp_path = p
        if not p.is_file():
            self.R.fail("document", str(p), "DXP present", "the analysis saved by the builder", "not found",
                        note="run the builder in Analyst first (dxpgen.py build, paste, Run Script)")
            return False
        return True

    def _load_report(self):
        candidates = [self.app_dir / "build" / "build-report.json", self.dxp_path.parent / "build-report.json"]
        seen = set()
        for c in candidates:
            key = str(c.resolve()).lower()
            if key in seen or not c.is_file():
                continue
            seen.add(key)
            try:
                self.report = json.loads(c.read_text(encoding="utf-8-sig"))
                self.report_path = c
                return
            except (OSError, ValueError) as e:
                self.R.warn("build", str(c), "build-report.json readable", "JSON", str(e))

    def created(self, key):
        if not isinstance(self.report, dict):
            return {}
        c = self.report.get("created") or {}
        v = c.get(key)
        return v if v is not None else ({} if key != "relations" else [])

    # -- helpers ---------------------------------------------------------------------------------
    def table_columns(self, name):
        for t in self.model["tables"]:
            if t["name"] == name:
                return [c["name"] for c in t["columns"]]
        return []

    def default_table(self):
        """spec defaultTable, else the first file table, else the first table (api-data.md R4)."""
        if self.spec.get("defaultTable"):
            return self.spec["defaultTable"]
        tables = [t for t in self.spec.get("tables") or [] if isinstance(t, dict) and t.get("name")]
        files = [t for t in tables if isinstance(t.get("source"), dict) and t["source"].get("type") in ("sbdf", "csv")]
        return (files or tables)[0]["name"] if (files or tables) else None

    def default_marking(self):
        marks = [m for m in self.spec.get("markings") or [] if isinstance(m, dict) and m.get("name")]
        for m in marks:
            if m.get("default") is True:
                return m["name"]
        return marks[0]["name"] if marks else "Marking"

    def default_scheme(self):
        for f in self.spec.get("filteringSchemes") or []:
            if isinstance(f, dict) and f.get("default") is True:
                return f.get("name")
        return self.model["document"].get("defaultFilteringScheme")

    def visual_titles(self):
        """{spec visual id: spec title} (Visualization script arguments are persisted as visual nodes)."""
        out = {}
        for pg in self.spec.get("pages") or []:
            for v in (pg.get("visuals") or []) if isinstance(pg, dict) else []:
                if isinstance(v, dict) and v.get("id"):
                    out[v["id"]] = v.get("title")
        return out

    def raw_visual(self, vid):
        """A visual as spec.json writes it (before dxpgen fills the defaults), or {}."""
        for pg in _as_list((self.raw_doc or {}).get("pages")):
            for v in _as_list(pg.get("visuals")) if isinstance(pg, dict) else []:
                if isinstance(v, dict) and v.get("id") == vid:
                    return v
        return {}

    def viz_manifest(self, mod_id):
        """(mod-manifest.json as a dict, project folder) of a vizMods entry, or None when the spec does not list
        the mod or its manifest cannot be read (one WARN line per mod)."""
        if mod_id in self._viz:
            return self._viz[mod_id]
        found = None
        for i, entry in enumerate(_as_list((self.raw_doc or {}).get("vizMods"))):
            if not isinstance(entry, dict) or entry.get("id") != mod_id:
                continue
            project = entry.get("project")
            if not isinstance(project, str) or not project.strip():
                break
            folder = Path(project.strip())
            folder = folder if folder.is_absolute() else self.app_dir / folder
            mpath = folder / "mod-manifest.json"
            try:
                manifest = json.loads(mpath.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:
                self.R.warn("spec", "vizMods[%d].project" % i, "mod-manifest.json readable", str(mpath), str(e),
                            note="the mod's axes and properties are compared without the manifest's types and "
                                 "its embedded files are not compared")
                break
            if isinstance(manifest, dict):
                found = (manifest, folder)
            break
        self._viz[mod_id] = found
        return found

    def fallback_targets(self):
        out = set()
        if isinstance(self.report, dict):
            for f in self.report.get("fallbacks") or []:
                if isinstance(f, dict) and f.get("target"):
                    out.add(str(f["target"]))
        return out

    # -- document --------------------------------------------------------------------------------
    def check_document(self):
        R, m, app = self.R, self.model, self.spec.get("app") or {}
        arc = m["archive"]
        doc = m["document"]
        A = "document"
        R.ok(A, "archive", "saved analysis", None, "%s, saved by %s, versions %s" % (
            self.dxp_path.name, arc.get("savedByAssemblyFileVersion"),
            ", ".join(d["version"] for d in arc["documents"])))
        minimum = str(app.get("minimumSpotfireVersion") or "14.6")
        compat = [c.strip() for c in (arc.get("compatibilityVersion") or "").split(";") if c.strip()]
        covered = any(version_tuple(c) <= version_tuple(minimum) for c in compat)
        R.add("PASS" if covered else "FAIL", A, "Metadata.xml", "CompatibilityVersion covers minimumSpotfireVersion",
              minimum, arc.get("compatibilityVersion"))
        R.eq(A, "document", "page navigation", app.get("pageNavigation") or "Tabs", doc.get("navigationMode"))
        R.eq(A, "document", "description", app.get("description") or "", doc.get("description") or "")
        R.eq(A, "document", "keywords", list(app.get("keywords") or []), list(doc.get("keywords") or []))
        canvas = app.get("canvas")
        found_canvas = doc.get("canvas") or {}
        if canvas:
            want = {"width": canvas.get("width"), "height": canvas.get("height"),
                    "fitToWindow": bool(canvas.get("fitToWindow", True))}
        else:
            want = {"width": 0, "height": 0, "fitToWindow": True}
        R.eq(A, "document", "canvas (visualization area size)", want,
             dict((k, found_canvas.get(k)) for k in ("width", "height", "fitToWindow")))
        pages = [p.get("title") for p in self.spec.get("pages") or [] if isinstance(p, dict)]
        want_active = self.spec.get("activePage") or (pages[0] if pages else None)
        if want_active is not None:
            R.eq(A, "document", "active page", want_active, doc.get("activePage"), bad="WARN",
                 note=None if doc.get("activePage") == want_active else "the page shown when the file opens")
        # theme
        theme = app.get("theme") or {}
        base = theme.get("base") or "LightSfx"
        styles = theme.get("customStyles")
        given = isinstance(styles, dict) and bool(styles)
        applied = bool(doc.get("useCustomStyles"))
        if given and not applied:
            R.warn(A, "theme", "UseCustomStyles", True, False, note="app.theme is " + MANUAL_NOTE)
            return
        if not app.get("theme"):
            R.eq(A, "theme", "UseCustomStyles", False, applied, bad="WARN",
                 note=None if not applied else "the spec has no app.theme; the custom styles were added by hand "
                                               "or by the styling-spotfire-dxps skill")
            return
        R.eq(A, "theme", "UseCustomStyles", given, applied)
        if given and "theme" not in self.unreadable:
            want = json.loads(json.dumps(styles))
            general = want.setdefault("general", {}) if isinstance(want.get("general"), dict) else None
            if general is None:
                want["general"] = general = {}
            general["baseTheme"] = base
            general["baseThemeSfx"] = base
            found = doc.get("customStylesJson")
            normalised = theme_base_normalised(base, found)
            if normalised:
                general["baseTheme"] = normalised
            if json_ints(want) == json_ints(found):
                R.ok(A, "theme", "CustomStyles.json equals app.theme.customStyles (base %s)" % base, None, None,
                     note=("Spotfire stores general.baseTheme %s as %s (baseThemeSfx keeps %s)"
                           % (base, normalised, base)) if normalised else None)
            else:
                R.fail(A, "theme", "CustomStyles.json equals app.theme.customStyles (base %s)" % base,
                       short(json_ints(want), 200), short(found, 200), note=self._json_diff(json_ints(want), found))
            theme_file = self.out_dir / "theme.json"
            if theme_file.is_file():
                try:
                    tf = json.loads(theme_file.read_text(encoding="utf-8-sig"))
                    R.eq(A, "theme", "CustomStyles.json equals build/theme.json", True, json_ints(tf) == json_ints(found),
                         bad="WARN")
                except ValueError:
                    R.warn(A, "theme", "build/theme.json readable", "JSON", "invalid")
        else:
            R.eq(A, "theme", "KnownTheme (computed by Spotfire)", base, doc.get("knownTheme"), bad="WARN")

    def _json_diff(self, want, found, path="$"):
        if isinstance(want, dict) and isinstance(found, dict):
            for k in sorted(set(want) | set(found), key=str):
                if k not in found:
                    return "%s.%s missing" % (path, k)
                if k not in want:
                    return "%s.%s not in the spec" % (path, k)
                d = self._json_diff(want[k], found[k], "%s.%s" % (path, k))
                if d:
                    return d
            return None
        if isinstance(want, list) and isinstance(found, list):
            if len(want) != len(found):
                return "%s has %d items, expected %d" % (path, len(found), len(want))
            for i, (a, b) in enumerate(zip(want, found)):
                d = self._json_diff(a, b, "%s[%d]" % (path, i))
                if d:
                    return d
            return None
        return None if want == found else "%s: expected %r, found %r" % (path, want, found)

    # -- pages and visuals -----------------------------------------------------------------------
    def match_pages(self):
        """[(spec page, model page or None)] using report Guids, exact titles, case-insensitive titles
        and finally the position of unmatched pages."""
        specs = [p for p in self.spec.get("pages") or [] if isinstance(p, dict)]
        pages = list(self.model["pages"])
        used = set()
        result = [None] * len(specs)
        self.page_match = {}
        by_id = dict((p.get("id"), p) for p in pages)
        rep = self.created("pages")
        for i, ps in enumerate(specs):
            pid = rep.get(ps.get("title")) if isinstance(rep, dict) else None
            if pid and pid in by_id and pid not in used:
                result[i] = by_id[pid]
                used.add(pid)
                self.page_match[i] = "build report"
        for fold in (False, True):
            for i, ps in enumerate(specs):
                if result[i] is not None:
                    continue
                for p in pages:
                    if p.get("id") in used:
                        continue
                    a, b = str(ps.get("title")), str(p.get("title"))
                    if (a.lower().strip() == b.lower().strip()) if fold else a == b:
                        result[i] = p
                        used.add(p.get("id"))
                        self.page_match[i] = "title (case-insensitive)" if fold else "title"
                        break
        rest = [p for p in pages if p.get("id") not in used]
        for i in range(len(specs)):
            if result[i] is None and rest:
                cand = [p for p in rest if p.get("order") == i]
                pick = cand[0] if cand else None
                if pick is not None:
                    result[i] = pick
                    rest.remove(pick)
                    used.add(pick.get("id"))
                    self.page_match[i] = "position"
        return list(zip(specs, result)), [p for p in pages if p.get("id") not in used]

    def check_pages(self):
        R, A = self.R, "pages"
        pairs, extra = self.match_pages()
        for i, (ps, pm) in enumerate(pairs):
            path = 'pages[%d] "%s"' % (i, ps.get("title"))
            if pm is None:
                R.fail(A, path, "page present", ps.get("title"), None)
                for vs in ps.get("visuals") or []:
                    if isinstance(vs, dict):
                        R.fail("visuals", '%s > %s' % (path, vs.get("id")), "visual present (page missing)",
                               vs.get("type"), None)
                continue
            R.ok(A, path, "page present", ps.get("title"), pm.get("title"),
                 note="matched by " + self.page_match.get(i, "?"))
            R.eq(A, path, "title", ps.get("title"), pm.get("title"))
            R.eq(A, path, "visible", bool(ps.get("visible", True)), pm.get("visible"))
            R.eq(A, path, "filter panel visible", bool(ps.get("filterPanel", False)), pm.get("filterPanelVisible"))
            R.eq(A, path, "details-on-demand visible", bool(ps.get("detailsOnDemand", False)),
                 pm.get("detailsOnDemandVisible"))
            want_scheme = ps.get("filteringScheme") or self.default_scheme()
            R.eq(A, path, "filtering scheme", want_scheme, pm.get("filteringScheme"),
                 note=None if pm.get("filteringScheme") else "FilterPanel.FilteringScheme is null")
            self.check_filter_layout(path, ps, pm)
            self.check_visuals(path, ps, pm)
        for pm in extra:
            R.fail(A, 'page "%s"' % pm.get("title"), "page in spec", None, pm.get("title"),
                   note="leftover page")
        want_order = [ps.get("title") for ps, pm in pairs]
        found_order = [p.get("title") for p in sorted(self.model["pages"], key=lambda p: p.get("order", 0))]
        matched = [pm.get("order") for ps, pm in pairs if pm is not None]
        in_order = matched == sorted(matched) and not extra and None not in [pm for ps, pm in pairs]
        R.add("PASS" if in_order else "FAIL", A, "pages", "page order", want_order, found_order)

    def check_filter_layout(self, path, ps, pm):
        """The page's filter panel organization against its layout (references/spec-format.md "Filter panel"):
        the tables shown and their order (every other table hidden), per table the filters shown in order (the
        top-level columns, then the sub groups; every other column hidden), expanded states, sub groups and
        filter types. A page without a layout ("filters": "all", or none in the spec) is not checked."""
        layout = self.dxpgen.page_filter_layout(self.spec, ps) if hasattr(self.dxpgen, "page_filter_layout") else None
        if layout is None:
            return
        R, A = self.R, "filters"
        found = pm.get("filterLayout")
        if not isinstance(found, list):
            R.fail(A, path, "filter panel organization", "%d table(s)" % len(layout),
                   found.get("error") if isinstance(found, dict) else None, note="no readable filter panel")
            return
        want = [t["table"] for t in layout]
        shown = [t["table"] for t in found if t.get("visible") is not False]
        R.eq(A, path, "filter panel tables shown, in order", want, shown,
             note=None if want == shown else "a table the layout does not list must be hidden")
        by_table = dict((t["table"], t) for t in found)
        for t in layout:
            tp = "%s > filters %s" % (path, t["table"])
            ft = by_table.get(t["table"])
            if ft is None:
                R.fail(A, tp, "table group present", t["table"], None)
                continue
            R.eq(A, tp, "expanded", t["expanded"], ft.get("expanded"))
            top = [i for i in ft["items"] if i["kind"] == "filter"]
            groups = dict((i["name"], i) for i in ft["items"] if i["kind"] == "group")
            moved = set(c for g in t["subGroups"] for c in g["columns"])
            expect = ([i["column"] for i in top if i["column"] not in moved] if t["columns"] == "*"
                      else list(t["columns"]))
            expect += ["[group] %s" % g["name"] for g in t["subGroups"]]
            got = [i["column"] if i["kind"] == "filter" else "[group] %s" % i["name"]
                   for i in ft["items"] if i.get("visible") is not False]
            R.eq(A, tp, "filters shown, in order", expect, got)
            for g in t["subGroups"]:
                gp = "%s / %s" % (tp, g["name"])
                fg = groups.get(g["name"])
                if fg is None:
                    R.fail(A, gp, "sub group present", g["name"], None)
                    continue
                R.eq(A, gp, "expanded", g["expanded"], fg.get("expanded"))
                R.eq(A, gp, "filters shown, in order", g["columns"],
                     [i["column"] for i in fg["items"] if i["kind"] == "filter" and i.get("visible") is not False])
            every = top + [i for fg in groups.values() for i in fg["items"] if i["kind"] == "filter"]
            types = dict((i["column"], i["type"]) for i in every)
            for column, ftype in sorted(t["filterTypes"].items()):
                R.eq(A, "%s.%s" % (tp, column), "filter type", ftype, types.get(column))

    CHART_CONTENT = {"lineChart": "LineChart", "barChart": "BarChart", "scatterPlot": "ScatterPlot"}

    def _chart_for(self, vs, charts, rep, used):
        """The chart_layout entry of a spec visual: by the build report's guid, else by title and type."""
        r = rep.get(vs.get("id")) if isinstance(rep, dict) else None
        guid = r.get("guid") if isinstance(r, dict) else None
        for info in charts:
            if guid and info.get("guid") == guid and info.get("guid") not in used:
                used.add(info.get("guid"))
                return info
        for info in charts:
            if (info.get("guid") not in used and info.get("content") == self.CHART_CONTENT.get(vs.get("type"))
                    and (info.get("title") or "") == (vs.get("title") or "")):
                used.add(info.get("guid"))
                return info
        return None

    def check_trellis(self):
        """Trellis mode and fixed grid, and the y axis's individual scaling, of line, bar and scatter charts
        (the trellis axes are checked with the other axes of the visual)."""
        R, A = self.R, "visuals"
        pairs, _ = self.match_pages()
        rep = self.created("visuals")
        for ps, pm in pairs:
            if pm is None:
                continue
            charts = list(pm.get("charts") or [])
            used = set()
            for vs in ps.get("visuals") or []:
                if not isinstance(vs, dict) or vs.get("type") not in self.CHART_CONTENT:
                    continue
                ts = vs.get("trellis") if isinstance(vs.get("trellis"), dict) else None
                each = isinstance(vs.get("yScale"), dict) and vs["yScale"].get("individualScaling") is True
                if not ts and not each:
                    continue
                path = 'pages "%s" > %s' % (ps.get("title"), vs.get("id"))
                info = self._chart_for(vs, charts, rep, used)
                if info is None:
                    R.warn(A, path, "trellis and y scaling checked", "the visual", None,
                           note="not found by the build report's guid or by title and type")
                    continue
                if ts:
                    tr = info.get("trellis") or {}
                    panel = not _blank(ts.get("panelBy"))
                    R.eq(A, path, "trellis mode", "Panels" if panel else "RowsColumns", tr.get("mode"))
                    if panel and (ts.get("rows") or ts.get("columns")):
                        R.eq(A, path, "trellis fixed grid", True, tr.get("manual"))
                        for key in ("rows", "columns"):
                            if ts.get(key):
                                R.eq(A, path, "trellis " + key, ts[key], tr.get(key))
                if each:
                    R.eq(A, path, "y axis individual scaling", [True, "Trellis" if ts else "Color"],
                         info.get("yIndividual"))

    def match_visuals(self, ps, pm):
        specs = [v for v in ps.get("visuals") or [] if isinstance(v, dict)]
        found = [v for v in pm.get("visuals") or []]
        used = set()
        result = {}
        how = {}
        rep = self.created("visuals")
        by_guid = dict((v.get("guid"), v) for v in found)
        for vs in specs:
            r = rep.get(vs.get("id")) if isinstance(rep, dict) else None
            g = r.get("guid") if isinstance(r, dict) else None
            if g and g in by_guid and g not in used:
                result[vs["id"]] = by_guid[g]
                used.add(g)
                how[vs["id"]] = "build report"
        for vs in specs:
            if vs.get("id") in result:
                continue
            want_type = TYPE_IDS.get(vs.get("type"))
            same = [v for v in found if v.get("guid") not in used and v.get("title") == vs.get("title")]
            if same:
                typed = [v for v in same if v.get("typeId") == want_type]
                pick = (typed or same)[0]
                result[vs["id"]] = pick
                used.add(pick.get("guid"))
                how[vs["id"]] = "title"
        for vs in specs:
            if vs.get("id") in result:
                continue
            want_type = TYPE_IDS.get(vs.get("type"))
            typed = [v for v in found if v.get("guid") not in used and v.get("typeId") == want_type]
            if typed:
                result[vs["id"]] = typed[0]
                used.add(typed[0].get("guid"))
                how[vs["id"]] = "type" + (" (ambiguous: %d candidates)" % len(typed) if len(typed) > 1 else "")
        extra = [v for v in found if v.get("guid") not in used]
        return specs, result, how, extra

    def check_visuals(self, ppath, ps, pm):
        R, A = self.R, "visuals"
        specs, matched, how, extra = self.match_visuals(ps, pm)
        for vs in specs:
            vid = vs.get("id")
            path = "%s > %s (%s)" % (ppath, vid, vs.get("type"))
            vm = matched.get(vid)
            if vm is None:
                note = None
                if vs.get("type") == "mod":
                    note = "see the mod fallback in the build report"
                R.fail(A, path, "visual present", "%s titled %r" % (TYPE_IDS.get(vs.get("type")), vs.get("title")),
                       None, note=note)
                continue
            R.ok(A, path, "visual present", vs.get("title"), vm.get("title"), note="matched by " + how.get(vid, "?"))
            if "error" in vm:
                R.warn(A, path, "visual readable", None, vm["error"])
                continue
            self.guarded(path, self.check_visual, path, vs, vm)
        for vm in extra:
            R.fail(A, '%s > "%s"' % (ppath, vm.get("title")), "visual in spec", None, vm.get("typeId"),
                   note="the page holds a visual the spec does not describe")
        self.guarded(ppath + " layout", self.check_layout, ppath, ps, matched)

    def guarded(self, where, fn, *args):
        """Run one check; a verifier bug becomes a FAIL line for that object instead of ending the area."""
        try:
            fn(*args)
        except Exception as e:                         # noqa: BLE001
            import traceback
            self.R.fail("spec", where, "verifier error", None, "%s: %s" % (type(e).__name__, e),
                        note=traceback.format_exc(limit=3).replace("\n", " | "))

    def check_visual(self, path, vs, vm):
        R, A = self.R, "visuals"
        vtype = vs.get("type")
        want_type = TYPE_IDS.get(vtype)
        if vtype == "mod" and vm.get("typeId") == "Spotfire.HtmlTextArea":
            mark = _MOD_MARKER_RE.search(vm.get("htmlContent") or "")
            R.fail(A, path, "type", want_type, vm.get("typeId"),
                   note="placeholder text area for the mod (%s): do the manual step in the build report"
                   % (mark.group(1) if mark else vs.get("modId")))
            return
        R.eq(A, path, "type", want_type, vm.get("typeId"))
        R.eq(A, path, "title", vs.get("title", ""), vm.get("title"))
        R.eq(A, path, "showTitle", bool(vs.get("showTitle", True)), vm.get("showTitle"))
        self.check_action_triggers(path, vs, vm)
        if vtype == "textArea":
            self.check_text_area(path, vs, vm)
            return
        if vtype != "map":
            table = vs.get("table") or self.default_table()
            if table:
                R.eq(A, path, "data table", table, vm.get("table"))
            want_mark = vs.get("marking") if "marking" in vs else self.default_marking()
            R.eq(A, path, "marking", want_mark, vm.get("marking"))
            limit = vs.get("limitExpression")
            found_limit = vm.get("limitExpression")
            if not _blank(limit) or not _blank(found_limit):
                st, note = match_expression(props_shorthand(str(limit or "")), found_limit or "")
                R.add(st, A, path, "limitExpression", limit, found_limit, note)
            limits = [str(x) for x in _as_list(vs.get("limitByMarkings")) if not _blank(x)]
            if limits or vm.get("limitByMarkings"):
                R.eq(A, path, "limitByMarkings", sorted(limits), sorted(x for x in vm.get("limitByMarkings") or [] if x))
            R.eq(A, path, "useFiltering", bool(vs.get("useFiltering", True)), vm.get("useFiltering"))
        legend = vs.get("legend", {"visible": True})
        want_legend = bool(legend.get("visible", True)) if isinstance(legend, dict) else bool(legend)
        given = True
        if vtype == "mod":                  # no legend in spec.json: the mod keeps its manifest's default
            raw = self.raw_visual(vs.get("id")).get("legend")
            given = isinstance(raw, bool) or (isinstance(raw, dict) and "visible" in raw)
        if given and "legendVisible" in vm:
            R.eq(A, path, "legend visible", want_legend, vm.get("legendVisible"))
        if vtype != "mod":                  # check_mod reads mod axes with the manifest
            self.check_axes(path, vs, vm)
        if vtype in COLOR_AXIS_TYPES:
            self.check_coloring(path, vs, vm)
        if vtype in REFERENCE_LAYER_TYPES:
            self.check_reference_layers(path, vs, vm)
        if vtype == "kpiChart":
            self.check_kpis(path, vs, vm)
        elif vtype == "table":
            self.check_table_visual(path, vs, vm)
        elif vtype == "crossTable":
            totals = vs.get("totals")
            if isinstance(totals, dict):
                for key in ("rows", "columns"):
                    if key in totals:
                        R.eq(A, path, "grand total (%s)" % key, bool(totals[key]), (vm.get("totals") or {}).get(key))
        elif vtype == "mod":
            self.check_mod(path, vs, vm)
        elif vtype == "map":
            self.check_map(path, vs, vm)
        elif vtype == "summaryTable":
            cols = [str(c) for c in _as_list(vs.get("columns"))]
            found = vm.get("summaryColumns") or []
            if cols and found:
                R.eq(A, path, "summary-table columns", cols, found)
            elif cols:
                R.warn(A, path, "summary-table columns", cols, None,
                       note="persisted field names unknown (Not yet tested); check in Analyst")
        self.check_marker_aggregation(path, vm)

    def check_marker_aggregation(self, path, vm):
        """Scatter plots and map marker layers whose marker-by is not row level aggregate their markers:
        a raw label, size, line order or rotation then makes the visual show 'Please specify an
        aggregation method.' and draw nothing (one bad layer blanks a whole map)."""
        holders = []
        if vm.get("contentClass") == "ScatterPlot":
            holders.append((path, vm.get("axes") or {}))
        for i, layer in enumerate(vm.get("layers") or []):
            if layer.get("kind") == "marker":
                holders.append(('%s layers[%d] "%s"' % (path, i, layer.get("title")), layer.get("axes") or {}))
        for where, axes in holders:
            if row_level(axes.get("MarkerByAxis")):
                continue
            for name in MUST_AGGREGATE_AXES:
                if raw_column_refs(axes.get(name)):
                    self.R.fail("visuals", where, name + " aggregated", "an aggregation (First(...), Avg(...))",
                                axes.get(name), note="the markers aggregate (no baserowid() in the marker-by): "
                                "Spotfire shows 'Please specify an aggregation method.' and draws nothing (one "
                                "bad layer blanks a whole map)")

    def check_axes(self, path, vs, vm):
        R, A = self.R, "visuals"
        table = vs.get("table") or self.default_table()
        found_axes = vm.get("axes") or {}
        rep = self.created("charts").get(vs.get("id")) or {}
        rep_axes = rep.get("axes") or {}
        trep = self.created("tableVisuals").get(vs.get("id")) or {}
        alias = {"XAxis": "X", "YAxis": "Y", "ZAxis": "Z", "ColorAxis": "Color", "SizeAxis": "Size",
                 "ShapeAxis": "Shape", "LineByAxis": "Line", "LabelColumn": "Label",
                 "LineConnection.ConnectionAxis": "LineConnection", "HierarchyAxis": "Hierarchy",
                 "MeasureAxis": "Measures", "SectorSizeAxis": "SectorSize"}
        tmap = {"MeasureAxis": "measureAxis", "RowAxis": "rowAxis", "ColumnAxis": "columnAxis"}
        for axis, expected, field in expected_axes(vs, self.table_columns(table)):
            found = found_axes.get(axis, "")
            alts = [rep_axes.get(alias.get(axis, axis))]
            if axis in tmap:
                alts.append(trep.get(tmap[axis]))
            if vs.get("type") == "pieChart" and axis == "ColorAxis":
                alts.append(rep_axes.get("Sector"))
            st, note = match_expression(expected, found, alts)
            R.add(st, A, path, "axis %s (%s)" % (axis, field), expected, found or "(empty)", note)

    def check_coloring(self, path, vs, vm):
        """Chart color-axis coloring (lib/65_coloring): fixed = DefaultColor without background rule,
        categorical = UserSetColors per category, gradient = a ContinuousColorRule, rules = rule classes."""
        R, A = self.R, "visuals"
        cs = vs.get("coloring")
        if not isinstance(cs, dict) or not cs:
            return
        found = vm.get("coloring")
        if found is None:
            R.fail(A, path, "coloring present", sorted(k for k in cs if k != "settings"), None,
                   note="no color-axis coloring found")
            return
        rules = found.get("rules") or []
        if cs.get("fixed") is not None:
            R.eq(A, path, "fixed color (DefaultColor)", normalize_color(cs["fixed"]),
                 normalize_color(found.get("defaultColor")))
            if not cs.get("rules"):
                R.add("PASS" if not rules else "WARN", A, path, "no background rule with a fixed color", [],
                      [r["type"] for r in rules])
        if isinstance(cs.get("categorical"), dict):
            cats = [r for r in rules if r["type"] == "CategoricalColorRule"]
            colors = cats[0].get("colors") or {} if cats else {}
            for key, col in cs["categorical"].items():
                got = found.get("emptyColor") if key == "(Empty)" else colors.get(str(key))
                R.add("PASS" if normalize_color(col) == normalize_color(got) else "FAIL", A, path,
                      "category color %s" % json.dumps(key, ensure_ascii=False), normalize_color(col),
                      normalize_color(got) if got else None,
                      note=None if got or not colors else "colored categories: %s" % ", ".join(sorted(colors)))
        if cs.get("gradient") is not None:
            cont = [r for r in rules if r["type"] == "ContinuousColorRule"]
            R.add("PASS" if cont else "FAIL", A, path, "gradient (ContinuousColorRule)",
                  "%d breakpoints" % len(_as_list(cs["gradient"])),
                  ("%d breakpoints" % cont[0].get("breakpoints", 0)) if cont else [r["type"] for r in rules])
        if cs.get("rules"):
            want = []
            for rule in _as_list(cs["rules"]):
                t = rule.get("type") if isinstance(rule, dict) else None
                if t in ("greaterThan", "lessThan"):
                    want.append("ThresholdColorRule")
                elif t == "equal":
                    value = rule.get("value")
                    want.append("StringColorRule" if isinstance(value, str) and not value.strip().lower() in (
                        "min", "max", "median", "average") and not value.strip().endswith("%") else
                        "ThresholdColorRule")
                elif t == "between":
                    want.append("RangeColorRule")
                elif t in ("top", "bottom"):
                    want.append("TopBottomColorRule")
                elif t == "expression":
                    want.append("ExpressionColorRule")
            got = [r["type"] for r in rules if r["type"] not in ("CategoricalColorRule", "ContinuousColorRule")]
            R.add("PASS" if got[:len(want)] == want else "WARN", A, path, "coloring rules (classes, in order)", want, got,
                  note=None if got[:len(want)] == want else "rule values are not compared (Not yet tested)")

    def check_reference_layers(self, path, vs, vm):
        R, A = self.R, "visuals"
        specs = [l for l in _as_list(vs.get("referenceLayers")) if isinstance(l, dict)]
        if not specs:
            return
        found = vm.get("referenceLayers") or []
        by_name = dict((l.get("name"), l) for l in found)
        bases = {"horizontalLine": "Horizontal line", "verticalLine": "Vertical line", "band": "Band"}
        used = []
        R.eq(A, path, "reference layer count", len(specs), len(found))
        for i, ls in enumerate(specs):
            kind = ls.get("kind")
            if ls.get("label"):
                name = str(ls["label"])
                used.append(name)
            else:
                base = bases.get(kind, str(kind))
                name, n = base, 2
                while name in used:
                    name = "%s %d" % (base, n)
                    n += 1
                used.append(name)
            lp = '%s referenceLayers[%d] "%s"' % (path, i, name)
            fl = by_name.get(name)
            if fl is None:
                R.fail(A, lp, "reference layer present", name, sorted(by_name))
                continue
            pairs = [("value (high)", ls.get("high"), fl.get("value")), ("secondary value (low)", ls.get("low"),
                                                                          fl.get("secondaryValue"))] \
                if kind == "band" else [("value", ls.get("value"), fl.get("value"))]
            for label, want, got in pairs:
                expected = props_shorthand(Expressions.text(want)) if want is not None else ""
                st, note = match_expression(expected, got or "")
                R.add(st, A, lp, label, expected, got or "(empty)", note)

    def check_kpis(self, path, vs, vm):
        R, A = self.R, "visuals"
        kpis = [k for k in _as_list(vs.get("kpis")) if isinstance(k, dict)]
        found = vm.get("kpis") or []
        R.eq(A, path, "KPI count", len(kpis), len(found))
        for i, k in enumerate(kpis):
            if i >= len(found):
                break
            want = k.get("title") if not _blank(k.get("title")) else "${AutoTitle}"
            R.eq(A, path, "kpis[%d] title" % i, want, found[i].get("title"))

    def check_table_visual(self, path, vs, vm):
        R, A = self.R, "visuals"
        cols = []
        for c in _as_list(vs.get("columns")):
            t = str(c)
            if t.startswith("[") and t.endswith("]") and _skip_ident(t, 0) == len(t):
                t = t[1:-1].replace("]]", "]")
            cols.append(t)
        found = vm.get("tableColumns") or []
        if cols:
            R.eq(A, path, "table columns (display order)", cols, found)
        sorts = _as_list(vs.get("sort"))
        if sorts:
            want = []
            for s in sorts:
                if isinstance(s, dict):
                    want.append({"column": s.get("column"), "mode": "Descending" if s.get("descending") else "Ascending"})
                else:
                    want.append({"column": s, "mode": "Ascending"})
            R.eq(A, path, "table sort", want, vm.get("tableSort") or [])

    def check_mod(self, path, vs, vm):
        """A visualization mod (references/spec-format.md "Visualization mods"): mod id and version, the embedded mod, the main
        view's axes and properties typed by the vizMods manifest, and the layers when the spec lists them."""
        R, A = self.R, "visuals"
        mod_id = vs.get("modId")
        if mod_id:
            R.eq(A, path, "mod id", mod_id, vm.get("modId"))
        found = self.viz_manifest(mod_id) if isinstance(mod_id, str) else None
        manifest, folder = found if found else (None, None)
        if manifest is not None and manifest.get("version") is not None:
            want = str(manifest["version"])
            R.eq(A, path, "mod version", want, vm.get("modVersion"),
                 note=None if want == vm.get("modVersion") else "the visual uses another version of the mod than "
                 "the project folder holds: build the DXP again after building the mod")
        if isinstance(mod_id, str) and mod_id:
            self.check_mod_embedded(path, mod_id, vm, manifest, folder)
        table = vs.get("table") or self.default_table()
        self.check_mod_view(path, vs, {"axes": vm.get("modAxes"), "properties": vm.get("modProperties"),
                                       "propertyTypes": vm.get("modPropertyTypes")}, manifest, None, table, "mod ")
        if isinstance(vs.get("layers"), list):
            self.check_mod_layers(path, vs, vm, manifest, table)

    def check_mod_embedded(self, path, mod_id, vm, manifest, folder):
        """The DXP embeds the mod (Mods/*.asice with this id) and it is the build the visual uses (the visual's
        Metadata hash = sha512 of the embedded mod.zip). Once per mod, with the vizMods project: every file the
        manifest lists (and its icon) has the same bytes in the DXP as in the project folder."""
        R, A = self.R, "visuals"
        entry = None
        for m in self.model.get("mods") or []:
            if m.get("modId") == mod_id and m.get("archive"):
                entry = m
                break
        if entry is None:
            R.fail(A, path, "mod embedded in the DXP", "Mods/*.asice with the mod %s" % mod_id, None,
                   note="the DXP does not embed the mod: it opens only where the mod is installed or pinned")
            return
        R.ok(A, path, "mod embedded in the DXP", mod_id, entry["archive"])
        same = bool(vm.get("modHash")) and vm.get("modHash") == entry.get("digest")
        R.add("PASS" if same else "FAIL", A, path, "embedded mod is the one the visual uses", vm.get("modHash"),
              entry.get("digest"), note=None if same else "the visual's mod hash differs from the embedded mod: "
              "the visual was made with another build of the mod")
        if manifest is None or mod_id in self._mods_checked:
            return
        self._mods_checked.add(mod_id)
        mpath = 'mod "%s"' % mod_id
        names = [f for f in _as_list(manifest.get("files")) if isinstance(f, str) and f.strip()]
        icon = manifest.get("icon")
        if isinstance(icon, str) and icon.strip() and icon not in names:
            names.append(icon)
        embedded = entry.get("embeddedFiles") or {}
        for name in names:
            key = name.strip().replace("\\", "/").lstrip("/")
            local = folder / key
            got = embedded.get(key)
            if not local.is_file():
                R.warn(A, mpath, "embedded file %s" % key, "the project's %s" % key, got,
                       note="not in the project folder %s: not compared" % folder)
                continue
            want = hashlib.sha256(local.read_bytes()).hexdigest()
            if got is None:
                R.fail(A, mpath, "embedded file %s" % key, "sha256 " + want[:16], None,
                       note="the embedded mod has no %s" % key)
                continue
            R.add("PASS" if got == want else "FAIL", A, mpath, "embedded file %s" % key, "sha256 " + want[:16],
                  "sha256 " + got[:16], note=None if got == want else "the DXP embeds another build of %s: build "
                  "the DXP again after building the mod" % key)

    def check_mod_view(self, path, spec_view, found, manifest, layer_type, table, prefix):
        """Axes and properties of a mod's main view (layer_type None, labels "mod axis" / "mod property") or of
        one layer (labels "axis" / "property" on the layer's path): axis values read with the manifest's axis
        mode (mod_axis_text), property values and persisted types against the manifest's types."""
        R, A = self.R, "visuals"
        modes = mod_manifest_axes(manifest, layer_type) if manifest is not None else None
        types = mod_manifest_props(manifest, layer_type) if manifest is not None else None
        columns = self.table_columns(table)
        axes = spec_view.get("axes") if isinstance(spec_view.get("axes"), dict) else {}
        found_axes = found.get("axes") or {}
        for name in axes:
            want = mod_axis_text(axes[name], (modes or {}).get(name), columns)
            if want is None:
                continue
            label = "%saxis %s" % (prefix, name)
            if modes is not None and name not in modes:
                R.fail(A, path, label, want, None, note="the mod's manifest has no axis %s on this view (axes: %s)"
                       % (name, ", ".join(modes) or "none"))
                continue
            got = found_axes.get(name)
            if got is None:
                R.fail(A, path, label, want or "(cleared)", None, note="the DXP has no axis %s on this view (axes: %s)"
                       % (name, ", ".join(sorted(found_axes)) or "none"))
            elif want == "":
                R.add("PASS" if got.strip() in ("", "<>") else "FAIL", A, path, label, "(cleared)", got or "(empty)")
            else:
                st, note = match_expression(want, got)
                R.add(st, A, path, label, want, got or "(empty)", note)
        props = spec_view.get("properties") if isinstance(spec_view.get("properties"), dict) else {}
        found_props = found.get("properties") or {}
        found_types = found.get("propertyTypes") or {}
        for name in props:
            label = "%sproperty %s" % (prefix, name)
            ptype = (types or {}).get(name)
            if types is not None and name not in types:
                R.fail(A, path, label, props[name], found_props.get(name),
                       note="the mod's manifest has no property %s on this view (properties: %s)"
                       % (name, ", ".join(sorted(types)) or "none"))
                continue
            got = found_props.get(name)
            same = name in found_props and mod_prop_matches(props[name], got, ptype)
            R.add("PASS" if same else "FAIL", A, path, label, props[name], got,
                  note=None if name in found_props else "the DXP has no such property on this view")
            if ptype is not None and name in found_types:
                R.eq(A, path, label + " type", ptype, found_types.get(name))

    def check_mod_layers(self, path, vs, vm, manifest, table):
        """The spec's layers are exactly the visual's layers, in order; each (matched by title) with its type,
        table (default the visual's), marking (absent = the visual's), limitByMarkings and empty behavior,
        filtering, where clause, axes and properties."""
        R, A = self.R, "visuals"
        specs = [ls for ls in vs["layers"] if isinstance(ls, dict)]
        found = list(vm.get("modLayers") or [])
        R.eq(A, path, "mod layers (type, title, in order)",
             [[ls.get("type"), ls.get("title") or ls.get("type")] for ls in specs],
             [[fl.get("type"), fl.get("title")] for fl in found])
        vis_mark = vs.get("marking") if "marking" in vs else self.default_marking()
        used = set()
        for k, ls in enumerate(specs):
            title = ls.get("title") or ls.get("type")
            lp = "%s layers['%s']" % (path, title)
            j = None
            for i, fl in enumerate(found):
                if i not in used and fl.get("title") == title:
                    j = i
                    break
            if j is None:
                R.fail(A, lp, "layer present", "%s layer titled %r" % (ls.get("type"), title),
                       [fl.get("title") for fl in found])
                continue
            used.add(j)
            fl = found[j]
            R.eq(A, lp, "layer type", ls.get("type"), fl.get("type"))
            ltable = ls.get("table") or table
            R.eq(A, lp, "data table", ltable, fl.get("table"))
            R.eq(A, lp, "marking", ls.get("marking") if "marking" in ls else vis_mark, fl.get("marking"))
            limits = [str(x) for x in _as_list(ls.get("limitByMarkings")) if not _blank(x)]
            if limits or fl.get("limitByMarkings"):
                R.eq(A, lp, "limitByMarkings", sorted(limits), sorted(x for x in fl.get("limitByMarkings") or [] if x))
            if limits:
                R.eq(A, lp, "emptyMarkingBehavior", ls.get("emptyMarkingBehavior") or "ShowAll",
                     fl.get("emptyMarkingBehavior"))
            R.eq(A, lp, "useFiltering", bool(ls.get("useFiltering", True)), fl.get("useFiltering"))
            limit, found_limit = ls.get("limitExpression"), fl.get("limitExpression")
            if not _blank(limit) or not _blank(found_limit):
                st, note = match_expression(props_shorthand(str(limit or "")), found_limit or "")
                R.add(st, A, lp, "limitExpression", limit, found_limit, note)
            self.check_mod_view(lp, ls, fl, manifest, ls.get("type"), ltable, "")
        for i, fl in enumerate(found):
            if i not in used:
                R.fail(A, "%s layers['%s']" % (path, fl.get("title")), "layer in spec", None, fl.get("type"),
                       note="the visual has a layer the spec does not list")

    def check_action_triggers(self, path, vs, vm):
        """Every spec actionTriggers entry is a manual step (no public API adds an action trigger): when the
        visual has a trigger with the same display and action-mod script it is checked with its arguments
        (PASS / FAIL); when it has none yet, WARN. Triggers the spec does not ask for are warned."""
        R, A = self.R, "visuals"
        found = list(vm.get("actionTriggers") or [])
        specs = [t for t in _as_list(vs.get("actionTriggers")) if isinstance(t, dict)]
        used = set()
        for k, ts in enumerate(specs):
            am = ts.get("actionMod") if isinstance(ts.get("actionMod"), dict) else {}
            display = ts.get("display") or "FloatingButton"
            want = "%s -> %s/%s" % (display, am.get("mod"), am.get("script"))
            tp = "%s actionTriggers[%d]" % (path, k)
            j = None
            for i, ft in enumerate(found):
                if i not in used and ft.get("display") == display and ft.get("mod") == am.get("mod") \
                        and ft.get("script") == am.get("script"):
                    j = i
                    break
            if j is None:
                R.warn(A, tp, "action trigger", want, [trigger_text(ft) for ft in found] or None,
                       note="the action trigger is " + MANUAL_NOTE)
                continue
            used.add(j)
            R.ok(A, tp, "action trigger", want, trigger_text(found[j]))
            self._check_arguments(tp, "action trigger arguments", am.get("args"), found[j].get("args"), area=A)
        extra = [trigger_text(ft) for i, ft in enumerate(found) if i not in used]
        if extra:
            R.warn(A, path, "no action triggers beyond the spec", None, extra,
                   note="action triggers the spec does not ask for")

    def check_map(self, path, vs, vm):
        R, A = self.R, "visuals"
        layers = [l for l in _as_list(vs.get("layers")) if isinstance(l, dict)]
        found = vm.get("layers") or []
        R.eq(A, path, "map layer kinds (back to front)", [l.get("kind") for l in layers], [l.get("kind") for l in found])
        if isinstance(vs.get("extent"), dict) and vs["extent"]:
            R.eq(A, path, "auto zoom", False, vm.get("autoZoom"), bad="WARN",
                 note="an extent switches AutoZoom off (standard engine)")
        elif "autoZoom" in vs:
            R.eq(A, path, "auto zoom", bool(vs.get("autoZoom")), vm.get("autoZoom"), bad="WARN",
                 note="a postScript may change it")
        for i, (ls, lf) in enumerate(zip(layers, found)):
            lp = "%s layers[%d]" % (path, i)
            if not _blank(ls.get("title")):
                R.eq(A, lp, "title", ls.get("title"), lf.get("title"))
            if ls.get("kind") in ("marker", "feature"):
                table = ls.get("table") or vs.get("table") or self.default_table()
                if table:
                    R.eq(A, lp, "data table", table, lf.get("table"))
                E = Expressions(self.table_columns(table))
                fa = lf.get("axes") or {}
                checks = []
                if ls.get("kind") == "marker":
                    for key, axis in (("longitude", "XAxis"), ("latitude", "YAxis"), ("sizeBy", "SizeAxis")):
                        if not _blank(ls.get(key)):
                            checks.append((axis, E.expr(ls[key]), key))
                    if not _blank(ls.get("lineBy")):
                        checks.append(("LineConnection.ConnectionAxis", E.cat(ls["lineBy"]), "lineBy"))
                elif str(ls.get("geometry") or "").strip().startswith("<"):
                    checks.append(("GeometryByAxis", E.expr(ls["geometry"]), "geometry"))
                else:                       # a geometry column (or none): one feature per row
                    checks.append(("GeometryByAxis", "<baserowid()>", "geometry"))
                if not _blank(ls.get("colorBy")):
                    checks.append(("ColorAxis", E.expr(ls["colorBy"]), "colorBy"))
                for axis, expected, field in checks:
                    st, note = match_expression(expected, fa.get(axis, ""))
                    R.add(st, A, lp, "axis %s (%s)" % (axis, field), expected, fa.get(axis) or "(empty)", note)

    # -- layout ----------------------------------------------------------------------------------
    def check_layout(self, ppath, ps, matched):
        R, A = self.R, "layout"
        tree = ps.get("layout")
        has_tree = isinstance(tree, dict) and ("row" in tree or "column" in tree)
        spec_ids = [v.get("id") for v in ps.get("visuals") or [] if isinstance(v, dict)]
        rep_layout = self.created("layouts").get(ps.get("title")) or {}

        def bounds(vid):
            vm = matched.get(vid)
            b = vm.get("bounds") if vm else None
            if not b or None in (b.get("x"), b.get("y"), b.get("width"), b.get("height")):
                return None
            return (b["x"], b["y"], b["width"], b["height"])

        def extent(node, axis):
            vids = layout_visual_ids(node)
            spans = []
            for vid in vids:
                b = bounds(vid)
                if b is None:
                    return None
                spans.append((b[axis], b[axis] + b[axis + 2]))
            if not spans:
                return None
            return (min(s[0] for s in spans), max(s[1] for s in spans))

        def label(node):
            if "visual" in node:
                return node["visual"]
            kind = "row" if "row" in node else "column"
            return "%s[%s]" % (kind, ", ".join(layout_visual_ids(node)))

        def weight(item):
            w = item.get("weight", 1)
            return float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0 else 1.0

        def walk(node, where):
            kind = "row" if "row" in node else "column"
            items = [i for i in node.get(kind) or [] if isinstance(i, dict)]
            if len(items) > 1:
                axis = 0 if kind == "row" else 1
                exts = [extent(i, axis) for i in items]
                if None in exts:
                    missing = [label(i) for i, e in zip(items, exts) if e is None]
                    R.warn(A, "%s %s" % (ppath, where), "proportions", None, None,
                           note="not checked: visual(s) missing or without bounds: %s" % ", ".join(missing))
                else:
                    lengths = [e[1] - e[0] for e in exts]
                    total = float(sum(lengths)) or 1.0
                    weights = [weight(i) for i in items]
                    wsum = sum(weights)
                    for i, item in enumerate(items):
                        share = lengths[i] / total
                        want = weights[i] / wsum
                        ok = abs(share - want) <= LAYOUT_SHARE_TOLERANCE
                        note = None
                        if "visual" in item and item["visual"] in expected:
                            note = "expected bounds %s, found %s" % (expected[item["visual"]], list(bounds(item["visual"])))
                        R.add("PASS" if ok else "FAIL", A, "%s %s > %s" % (ppath, where, label(item)),
                              "share of its %s (item %d of %d)" % (kind, i + 1, len(items)),
                              "%.1f%%" % (100 * want), "%.1f%%" % (100 * share), note)
                    starts = [e[0] for e in exts]
                    if starts != sorted(starts):
                        R.fail(A, "%s %s" % (ppath, where), "order (%s)" % ("left to right" if kind == "row" else "top to bottom"),
                               [label(i) for i in items], [label(items[j]) for j in sorted(range(len(items)), key=lambda j: starts[j])])
            for item in items:
                if "row" in item or "column" in item:
                    walk(item, "%s > %s" % (where, label(item)))

        if has_tree:
            expected = pages_expected(tree)
            walk(tree, "layout " + label(tree))
            placed = layout_visual_ids(tree)
            unplaced = [vid for vid in spec_ids if vid not in placed]
            if unplaced:
                R.warn(A, ppath, "every visual in the layout", spec_ids, placed, note="not in the layout: %s"
                       % ", ".join(str(v) for v in unplaced))
        elif len(spec_ids) > 1:
            R.warn(A, ppath, "layout given", "a row/column tree", None, note="dxpgen requires one for several visuals")
        elif len(spec_ids) == 1:
            b = bounds(spec_ids[0])
            if b is not None:
                full = abs(b[2] - LAYOUT_SPACE) <= LAYOUT_SHARE_TOLERANCE * LAYOUT_SPACE and \
                    abs(b[3] - LAYOUT_SPACE) <= LAYOUT_SHARE_TOLERANCE * LAYOUT_SPACE
                R.add("PASS" if full else "WARN", A, "%s > %s" % (ppath, spec_ids[0]), "fills the page (single visual)",
                      [0, 0, LAYOUT_SPACE, LAYOUT_SPACE], list(b))
        for vid, rec in sorted(rep_layout.items()) if isinstance(rep_layout, dict) else []:
            actual = rec.get("actual") if isinstance(rec, dict) else None
            b = bounds(vid)
            if actual and b is not None and list(b) != list(actual):
                R.warn(A, "%s > %s" % (ppath, vid), "bounds unchanged since the build", actual, list(b),
                       note="the layout was changed after the build")

    # -- text areas ------------------------------------------------------------------------------
    def match_controls(self, vid, spec_controls, persisted):
        rep = self.created("controls")
        by_id = dict((c["id"], c) for c in persisted)
        used = set()
        out = {}
        for cid in spec_controls:
            r = rep.get("%s/%s" % (vid, cid)) if isinstance(rep, dict) else None
            rid = (r.get("id") or "").replace("-", "").lower() if isinstance(r, dict) else ""
            if rid and rid in by_id and rid not in used:
                out[cid] = by_id[rid]
                used.add(rid)
        for cid, cs in spec_controls.items():
            if cid in out or not isinstance(cs, dict):
                continue
            cls, mode = CONTROL_KINDS.get(cs.get("kind"), (None, None))
            cands = [c for c in persisted if c["id"] not in used and (cls is None or c["kind"] == cls)]
            best = []
            if cls == "PropertyControl" or (cls is None and cs.get("property")):
                prop = str(cs.get("property") or "").lower()
                same = [c for c in cands if (c.get("property") or "").lower() == prop]
                best = [c for c in same if c.get("renderType") == mode] or same
                if not best:
                    best = [c for c in persisted if c["id"] not in used and (c.get("property") or "").lower() == prop]
            elif cls == "ActionControl":
                label = cs.get("label") or cid
                best = [c for c in cands if c.get("label") == label]
                if not best and cs.get("script"):
                    best = [c for c in cands if c.get("script") == cs.get("script")]
                if not best and isinstance(cs.get("action"), dict) and cs["action"].get("gotoPage"):
                    best = [c for c in cands if {"gotoPage": cs["action"]["gotoPage"]} in (c.get("action") or [])]
            if best:
                out[cid] = best[0]
                used.add(best[0]["id"])
        return out

    def check_text_area(self, path, vs, vm):
        R, A = self.R, "textAreas"
        html = vm.get("htmlContent") or ""
        vid = vs.get("id")
        left = _PLACEHOLDER_RE.findall(html)
        R.add("FAIL" if left else "PASS", A, path, "no {{control:...}} placeholder left", [], left)
        dangling = vm.get("danglingTokens") or []
        tokens = _TOKEN_RE.findall(html)
        R.add("FAIL" if dangling else "PASS", A, path, "every <SpotfireControl> token resolves to a control",
              "%d token(s)" % len(tokens), dangling or "all resolve")
        persisted = vm.get("controls") or []
        orphans = [c["id"] for c in persisted if not c.get("inHtml")]
        if orphans:
            R.warn(A, path, "every control has a token in the HTML", None, orphans,
                   note="Spotfire removes such controls when the HTML is set or the file opens")
        spec_controls = vs.get("controls") if isinstance(vs.get("controls"), dict) else {}
        matched = self.match_controls(vid, spec_controls, persisted)
        marker_texts = set(m.strip() for m in _MARKER_SPAN_RE.findall(html))
        marker_of = self.control_markers(spec_controls)
        for cid, cs in spec_controls.items():
            cpath = "%s > control %s" % (path, cid)
            if not isinstance(cs, dict):
                R.fail(A, cpath, "control spec is an object", "object", type(cs).__name__)
                continue
            kind = cs.get("kind")
            cls, mode = CONTROL_KINDS.get(kind, (None, None))
            pc = matched.get(cid)
            if pc is None:
                shown = [m for m in marker_texts if marker_of.get(m) == cid]
                if shown:
                    R.warn(A, cpath, "control present", kind, "marker [%s]" % shown[0],
                           note="the control is " + MANUAL_NOTE)
                else:
                    R.fail(A, cpath, "control present", "%s %s" % (cls, mode), None,
                           note="neither the control nor its marker is in the HTML")
                continue
            R.ok(A, cpath, "control present", "%s %s" % (cls, mode), pc["id"])
            found_kind = "%s %s" % (pc["kind"], pc.get("renderType") or pc.get("viewMode"))
            R.eq(A, cpath, "kind (%s)" % kind, "%s %s" % (cls, mode), found_kind)
            if cls == "PropertyControl":
                want = str(cs.get("property") or "")
                got = pc.get("property") or ""
                R.add("PASS" if want.lower() == got.lower() else "FAIL", A, cpath, "bound property", want, got,
                      note="case differs" if want != got and want.lower() == got.lower() else None)
                values = cs.get("values") if isinstance(cs.get("values"), dict) else None
                prov = pc.get("values") or {}
                if kind == "checkbox":
                    values = {"fixed": [{"text": "Yes", "value": True}, {"text": "No", "value": False}]}
                if values and values.get("fixed") is not None:
                    want_vals = [(str(x.get("text") if x.get("text") is not None else x.get("value")),
                                  x.get("value", x.get("text"))) for x in values["fixed"] if isinstance(x, dict)]
                    got_vals = [(x.get("text"), x.get("value")) for x in prov.get("values") or []]
                    same = len(want_vals) == len(got_vals) and all(
                        a[0] == b[0] and (a[1] == b[1] or str(a[1]) == str(b[1]) or
                                          (isinstance(a[1], (int, float)) and isinstance(b[1], (int, float))
                                           and abs(float(a[1]) - float(b[1])) < 1e-9))
                        for a, b in zip(want_vals, got_vals))
                    R.add("PASS" if same else "FAIL", A, cpath, "fixed values", want_vals, got_vals)
                elif values and values.get("column"):
                    col = values["column"]
                    R.eq(A, cpath, "values from column", {"table": col.get("table"), "column": col.get("column")},
                         prov.get("column"))
                if kind == "slider":
                    want = [cs.get("min"), cs.get("max"), cs.get("step", 1)]
                    got = [prov.get("min"), prov.get("max"), prov.get("interval")]
                    same = all(isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 1e-9
                               for a, b in zip(want, got))
                    R.add("PASS" if same else "FAIL", A, cpath, "slider range (min, max, step)", want, got)
            elif cls == "ActionControl":
                R.eq(A, cpath, "label", cs.get("label") or cid, pc.get("label"))
                am = cs.get("actionMod") if isinstance(cs.get("actionMod"), dict) else None
                if am and pc.get("actionMod") is not None:
                    self._check_action_mod_button(cpath, cs, am, pc)
                elif cs.get("script"):
                    R.eq(A, cpath, "runs script", cs.get("script"), pc.get("script"),
                         note="the button runs its IronPython script, not the action mod" if am else None)
                    self._check_arguments(cpath, "script arguments", cs.get("args"), pc.get("scriptArguments"))
                elif isinstance(cs.get("action"), dict):
                    act = cs["action"]
                    if act.get("gotoPage"):
                        R.eq(A, cpath, "goes to page", act["gotoPage"],
                             next((a.get("gotoPage") for a in pc.get("action") or [] if "gotoPage" in a), None))
                    elif act.get("refreshDataFunction"):
                        R.eq(A, cpath, "refreshes data function", act["refreshDataFunction"], pc.get("dataFunction"))
                    elif act.get("applyBookmark"):
                        has = any("applyBookmark" in a for a in pc.get("action") or [])
                        R.add("PASS" if has else "FAIL", A, cpath, "applies a bookmark", act["applyBookmark"],
                              "ApplyBookmarkDocumentOperation" if has else pc.get("action"))
        known = set(c["id"] for c in matched.values())
        for c in persisted:
            if c["id"] not in known:
                R.warn(A, "%s > control %s" % (path, c["id"]), "control in spec", None,
                       "%s %s %s" % (c["kind"], c.get("renderType") or c.get("viewMode") or "",
                                     c.get("property") or c.get("label") or ""))
        for mk in sorted(marker_texts):
            if mk not in marker_of:
                R.fail(A, path, "no marker of a control the spec does not describe", None, "[%s]" % mk,
                       note="the HTML has a {{control:...}} placeholder with no entry in 'controls'")
        self._check_text_area_html(path, vs, vm, matched)

    def control_markers(self, spec_controls):
        """{marker text: control id}: the builder's marker for each spec control (t3/_manual.py) and the
        slim tier's "control: <id>"."""
        out = {}
        for cid, cs in spec_controls.items():
            out["control: " + str(cid)] = cid
            if isinstance(cs, dict):
                out[_manual.control_marker(cid, cs)] = cid
        return out

    def _check_arguments(self, cpath, label, args, got, area="textAreas"):
        """PASS/FAIL of a button's or action trigger's argument values (a visual id may stand for its
        title)."""
        args = args if isinstance(args, dict) else {}
        if not args:
            return
        got = got or {}
        titles = self.visual_titles()
        bad = []
        for k, want in sorted(args.items()):
            have = got.get(k)
            same = (have == want or (isinstance(want, str) and have == titles.get(want)) or
                    (isinstance(want, (int, float)) and isinstance(have, (int, float))
                     and not isinstance(want, bool) and abs(float(want) - float(have)) < 1e-9))
            if not same:
                bad.append(k)
        self.R.add("FAIL" if bad else "PASS", area, cpath, label, dict(args),
                   dict((k, got.get(k)) for k in args), note=("different: %s" % ", ".join(bad)) if bad else None)

    def _check_action_mod_button(self, cpath, cs, am, pc):
        """A button added by hand that runs an action-mod script: the script and its arguments."""
        R, A = self.R, "textAreas"
        want = "%s/%s" % (am.get("mod"), am.get("script"))
        found = pc.get("actionMod")
        if found is not None:
            got = "%s/%s" % (found.get("mod"), found.get("script"))
            R.eq(A, cpath, "runs action-mod script", want, got)
            self._check_arguments(cpath, "action-mod arguments", am.get("args"), found.get("args"))
            return
        if pc.get("script") and pc.get("script") == cs.get("script"):
            R.warn(A, cpath, "runs action-mod script", want, "IronPython script %s" % pc.get("script"),
                   note="the documented fallback: the action mod was not available when the builder ran "
                        "(build log: FAILED / TODO action lines)")
            self._check_arguments(cpath, "script arguments (fallback)", cs.get("args"), pc.get("scriptArguments"))
            return
        R.fail(A, cpath, "runs action-mod script", want, pc.get("script"),
               note=("neither the action mod nor the fallback script %s" % cs.get("script"))
               if cs.get("script") else None)

    def _check_text_area_html(self, path, vs, vm, matched):
        R, A = self.R, "textAreas"
        html = vm.get("htmlContent") or ""
        css = vs.get("css") or ""
        safe = (self.spec.get("app") or {}).get("htmlMode", "safe") != "rich"
        vid = vs.get("id")
        body = html
        if css:
            if safe:
                own = 'id="style-container"' in (vs.get("html") or "") or "id='style-container'" in (vs.get("html") or "")
                prefix = '<div id="style-container" class="sfdxb-style-%s"></div>' % textarea_safe_name(vid)
                if not own:
                    R.add("PASS" if html.startswith(prefix) else "FAIL", A, path, "CSS container first (safe mode)",
                          prefix, html[:len(prefix) + 20])
                    if html.startswith(prefix):
                        body = html[len(prefix):]
                js = vm.get("jsScripts") or []
                injector = self._injector_name(vid)
                R.add("PASS" if js and js[0] == injector else "FAIL", A, path, "CSS injector JavaScript attached first",
                      injector, js[:1])
            else:
                R.add("PASS" if html.startswith("<style>") else "FAIL", A, path, "<style> block first (rich mode)",
                      "<style>...", html[:20])
                if html.startswith("<style>") and "</style>" in html:
                    body = html[html.index("</style>") + len("</style>"):]
        for js in vs.get("js") or []:
            name = js.get("name") if isinstance(js, dict) else Path(str(js)).stem
            R.add("PASS" if name in (vm.get("jsScripts") or []) else "FAIL", A, path, "JavaScript attached", name,
                  vm.get("jsScripts"))
        spec_html = vs.get("html") or ""
        if ("html", vid) in self.unreadable or not spec_html:
            return
        token_of = dict((cid, c["id"]) for cid, c in matched.items())
        restored = body
        for cid, tid in token_of.items():
            restored = re.sub(r'<SpotfireControl\s+id\s*=\s*["\']%s["\']\s*/?>' % tid, "{{control:%s}}" % cid,
                              restored, flags=re.I)
        marker_of = self.control_markers(vs.get("controls") if isinstance(vs.get("controls"), dict) else {})
        restored = _MARKER_SPAN_RE.sub(
            lambda m: "{{control:%s}}" % marker_of.get(m.group(1).strip(), m.group(1).strip().replace("control: ", "")),
            restored)
        want = _PLACEHOLDER_RE.sub(lambda m: "{{control:%s}}" % m.group(1), spec_html)
        diff = first_difference(norm_newlines(want), norm_newlines(restored))
        R.add("PASS" if diff is None else "WARN", A, path, "HTML as specified (controls as placeholders)",
              "%d chars" % len(want), "%d chars" % len(restored), diff)

    def _injector_name(self, vid):
        """Name of the builder's CSS injector JavaScript (lib/80_textareas._textareas_css_name)."""
        words = textarea_words(vid)
        if (self.spec.get("app") or {}).get("namingPolicy") == "camelCase":
            return "inject" + "".join(words) + "Styles"
        return "Inject " + " ".join(words) + " Styles"

    # -- document properties ---------------------------------------------------------------------
    def check_properties(self):
        R, A = self.R, "properties"
        found = self.model["documentProperties"]
        by_lower = dict(((p.get("name") or "").lower(), p) for p in found)
        df_targets = set()
        for d in self.spec.get("dataFunctions") or []:
            for o in d.get("outputs") or [] if isinstance(d, dict) else []:
                if isinstance(o, dict) and isinstance(o.get("target"), dict) and o["target"].get("property"):
                    df_targets.add(str(o["target"]["property"]).lower())
        names = set()
        for p in self.spec.get("properties") or []:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name"))
            names.add(name.lower())
            path = 'property "%s"' % name
            fp = by_lower.get(name.lower())
            if fp is None:
                R.fail(A, path, "present", name, None)
                continue
            R.add("PASS" if fp["name"] == name else "FAIL", A, path, "present (exact name)", name, fp["name"])
            R.eq(A, path, "type", p.get("type") or "String", fp.get("type"))
            R.eq(A, path, "list-valued", bool(p.get("listValued", False)), fp.get("listValued"))
            if p.get("default") is not None:
                same = compare_value(p.get("type") or "String", p.get("default"), fp.get("value"))
                bad = "WARN" if name.lower() in df_targets else "FAIL"
                R.add("PASS" if same else bad, A, path, "value (spec default)", p.get("default"), fp.get("value"),
                      note="written by a data function" if not same and bad == "WARN" else None)
            missing = [f for f in CUSTOM_PROPERTY_FLAGS if f not in fp.get("attributes", [])]
            R.add("PASS" if not missing else "WARN", A, path, "attributes", list(CUSTOM_PROPERTY_FLAGS),
                  fp.get("attributes"))
            R.eq(A, path, "description", p.get("description") or "", fp.get("description") or "", bad="WARN")
        for fp in found:
            if (fp.get("name") or "").lower() not in names:
                R.warn(A, 'property "%s"' % fp.get("name"), "property in spec", None, fp.get("type"),
                       note="every property the app uses belongs in spec 'properties'")

    # -- scripts and triggers --------------------------------------------------------------------
    def check_scripts(self):
        R, A = self.R, "scripts"
        scripts = self.model["scripts"]
        iron = [s for s in scripts if s.get("language", "").lower().startswith("ironpython")]
        js = [s for s in scripts if s.get("language", "").lower() == "javascript"]
        spec_names = set()
        for sc in self.spec.get("scripts") or []:
            if not isinstance(sc, dict):
                continue
            name = sc.get("name")
            spec_names.add(name)
            path = 'script "%s"' % name
            found = [s for s in iron if s.get("name") == name]
            if not found:
                other = [s for s in scripts if s.get("name") == name]
                R.fail(A, path, "present (IronPython)", name, None,
                       note=("found as %s" % other[0].get("language")) if other else None)
                continue
            if len(found) > 1:
                R.warn(A, path, "unique name", 1, len(found))
            s = found[0]
            R.eq(A, path, "language", "IronPython 3", "%s %s" % (s.get("language"), s.get("languageVersion")))
            if ("script", name) in self.unreadable:
                R.warn(A, path, "code", None, None, note="spec file missing; code not compared")
            else:
                diff = first_difference(norm_code(sc.get("code")), norm_code(s.get("code")))
                R.add("PASS" if diff is None else "FAIL", A, path, "code identical",
                      "%d lines" % len(norm_code(sc.get("code")).splitlines()),
                      "%d lines" % len(norm_code(s.get("code")).splitlines()), diff)
            R.eq(A, path, "transaction (WrapScript)", bool(sc.get("transaction", True)), s.get("wrapInTransaction"))
            want_params = [(p.get("name"), p.get("type") or "String") for p in sc.get("parameters") or []
                           if isinstance(p, dict)]
            R.eq(A, path, "parameters (name, type)", want_params,
                 [(p.get("name"), p.get("type")) for p in s.get("parameters") or []])
            R.eq(A, path, "description", sc.get("description") or "", s.get("description") or "", bad="WARN")
            R.add("PASS" if s.get("approved") else "WARN", A, path, "trust stamp (ApprovalStamp)", "present",
                  "present" if s.get("approved") else "missing",
                  note=None if s.get("approved") else "users get the trust prompt")
        for s in iron:
            code = s.get("code") or ""
            if "BuildContext(" in code and "run_build(" in code:
                R.fail(A, 'script "%s"' % s.get("name"), "builder not stored in the analysis", None, "builder script",
                       note="close the script dialog with Cancel after Run Script, then rebuild")
            elif s.get("name") not in spec_names:
                R.warn(A, 'script "%s"' % s.get("name"), "script in spec", None, "IronPython script")
        allowed_js = set()
        for pg in self.spec.get("pages") or []:
            for v in pg.get("visuals") or [] if isinstance(pg, dict) else []:
                if isinstance(v, dict) and v.get("type") == "textArea":
                    if v.get("css"):
                        allowed_js.add(self._injector_name(v.get("id")))
                    for item in v.get("js") or []:
                        allowed_js.add(item.get("name") if isinstance(item, dict) else Path(str(item)).stem)
        for s in js:
            if s.get("name") not in allowed_js:
                R.warn(A, 'JavaScript "%s"' % s.get("name"), "JavaScript attached by the spec", None, s.get("name"))
        names = [s.get("name") for s in iron]
        dups = sorted(set(n for n in names if names.count(n) > 1))
        if dups:
            R.warn(A, "scripts", "unique script names", None, dups)

    def check_triggers(self):
        R, A = self.R, "triggers"
        found = self.model["propertyTriggers"]
        seen = set()
        for t in self.spec.get("triggers") or []:
            if not isinstance(t, dict):
                continue
            prop = str(t.get("property"))
            path = 'trigger "%s"' % prop
            hits = [f for f in found if (f.get("property") or "").lower() == prop.lower()]
            if not hits:
                R.warn(A, path, "handler present", "%s -> %s" % (prop, t.get("script")), None,
                       note="the property trigger is " + MANUAL_NOTE)
                continue
            seen.add(id(hits[0]))
            R.ok(A, path, "handler present", prop, hits[0].get("property"))
            R.eq(A, path, "runs script", t.get("script"), hits[0].get("script"))
            if len(hits) > 1:
                R.warn(A, path, "one handler per property", 1, len(hits))
        for f in found:
            if id(f) not in seen:
                R.warn(A, 'trigger "%s"' % f.get("property"), "trigger in spec", None, f.get("script"))

    # -- data functions --------------------------------------------------------------------------
    def expected_binding(self, inp):
        """(expected expression, kind) of a spec input binding (lib/30_datafunctions)."""
        bind = inp.get("bind") if isinstance(inp.get("bind"), dict) else {}
        itype = inp.get("type")
        if bind.get("property") is not None:
            return 'DocumentProperty(%s)' % esc_string(bind["property"]), "property"
        if itype == "table" or (bind.get("table") is not None and bind.get("column") is None):
            t = bind.get("table")
            cols = bind.get("columns", "*")
            if cols is None or cols == "*":
                return '$map("%s.$esc($csearch(%s,%s))",",")' % (esc_ident(t), esc_ident(t), esc_string("*")), "table"
            return ", ".join(esc_ident(t) + "." + esc_ident(c) for c in _as_list(cols)), "columns"
        if bind.get("column") is not None:
            return esc_ident(bind.get("table")) + "." + esc_ident(bind["column"]), "column"
        if bind.get("expression") is not None:
            return str(bind["expression"]), "expression"
        if "value" in bind:
            value = bind["value"]
            types = [str(t) for t in _as_list(inp.get("dataTypes"))]
            if isinstance(value, bool):
                natural = "Boolean"
            elif isinstance(value, int):
                natural = "Integer"
            elif isinstance(value, float):
                natural = "Real"
            else:
                natural = "String"
            t = natural if (not types or natural in types) else types[0]
            if t == "String":
                return esc_string(str(value)), "value"
            if t == "Boolean":
                truthy = value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "yes")
                return ("True" if truthy else "False"), "value"
            if t in ("Integer", "LongInteger"):
                try:
                    return str(int(value)), "value"
                except (TypeError, ValueError):
                    return str(value), "value"
            if t in ("Real", "SingleReal", "Currency"):
                return repr(float(value)), "realValue"
            return str(value), "dateValue"
        return None, None

    def check_data_functions(self):
        R, A = self.R, "dataFunctions"
        found = self.model["dataFunctions"]
        by_name = dict((d.get("name"), d) for d in found)
        rep = self.created("dataFunctions")
        names = set()
        for d in self.spec.get("dataFunctions") or []:
            if not isinstance(d, dict):
                continue
            name = d.get("name")
            names.add(name)
            path = 'data function "%s"' % name
            fd = by_name.get(name)
            if fd is None:
                R.fail(A, path, "present", name, None)
                continue
            R.ok(A, path, "present", name, fd.get("name"))
            R.eq(A, path, "DisplayName", name, fd.get("displayName"))
            R.eq(A, path, "FunctionName", name, fd.get("functionName"))
            R.eq(A, path, "engine (executor)", EXECUTORS.get(d.get("engine") or "python"), fd.get("executor"))
            if ("dataFunction", name) in self.unreadable:
                R.warn(A, path, "script", None, None, note="spec file missing; code not compared")
            elif d.get("scriptCode") is not None:
                diff = first_difference(norm_code(d.get("scriptCode")), norm_code(fd.get("script")))
                R.add("PASS" if diff is None else "FAIL", A, path, "script identical",
                      "%d lines" % len(norm_code(d.get("scriptCode")).splitlines()),
                      "%d lines" % len(norm_code(fd.get("script")).splitlines()), diff)
            R.eq(A, path, "refresh (UpdateBehavior)", (d.get("refresh") or "automatic").capitalize(),
                 fd.get("updateBehavior"))
            R.eq(A, path, "description", d.get("description") or "", fd.get("description") or "", bad="WARN")
            R.add("PASS" if fd.get("approved") else "WARN", A, path, "trust stamp", "present",
                  "present" if fd.get("approved") else "missing")
            inputs = dict((i.get("name"), i) for i in fd.get("inputs") or [])
            rep_inputs = ((rep.get(name) or {}).get("inputs") or {}) if isinstance(rep, dict) else {}
            spec_inputs = set()
            for inp in d.get("inputs") or []:
                if not isinstance(inp, dict):
                    continue
                iname = inp.get("name")
                spec_inputs.add(iname)
                ipath = "%s input %s" % (path, iname)
                fi = inputs.get(iname)
                if fi is None:
                    R.fail(A, ipath, "input present", iname, None)
                    continue
                expected, kind = self.expected_binding(inp)
                if expected is None:
                    R.warn(A, ipath, "binding", inp.get("bind"), safe_expr(iname, fi.get("expression")),
                           note="no binding in the spec")
                    continue
                found_expr = fi.get("expression") or ""
                if kind == "property":
                    m = _DOCPROP_RE.match(found_expr)
                    got = m.group(2) if m else None
                    want = str(inp["bind"]["property"])
                    R.add("PASS" if got == want else "FAIL", A, ipath, "bound to property", want, found_expr)
                    continue
                if kind == "realValue":
                    try:
                        same = abs(float(found_expr) - float(expected)) < 1e-9 * max(1.0, abs(float(expected)))
                    except ValueError:
                        same = False
                    R.add("PASS" if same else "FAIL", A, ipath, "binding (literal)", safe_expr(iname, expected),
                          safe_expr(iname, found_expr))
                    continue
                alts = []
                r = rep_inputs.get(iname) if isinstance(rep_inputs, dict) else None
                if isinstance(r, dict):
                    alts.append(r.get("expression"))
                st, note = match_expression(expected, found_expr, alts)
                if st == "FAIL" and kind == "table" and expr_key(found_expr).startswith(
                        expr_key(esc_ident(inp["bind"].get("table")) + ".")):
                    st, note = "WARN", "explicit column list instead of the whole-table search"
                if st == "FAIL" and kind == "value" and expr_key(found_expr).lower() == expr_key(expected).lower():
                    st, note = "PASS", None
                R.add(st, A, ipath, "binding (%s)" % kind, safe_expr(iname, expected), safe_expr(iname, found_expr), note)
            for iname in inputs:
                if iname not in spec_inputs:
                    R.warn(A, "%s input %s" % (path, iname), "input in spec", None,
                           safe_expr(iname, inputs[iname].get("expression")))
            outputs = dict((o.get("name"), o) for o in fd.get("outputs") or [])
            spec_outputs = set()
            for o in d.get("outputs") or []:
                if not isinstance(o, dict):
                    continue
                oname = o.get("name")
                spec_outputs.add(oname)
                opath = "%s output %s" % (path, oname)
                fo = outputs.get(oname)
                if fo is None:
                    R.fail(A, opath, "output present", oname, None)
                    continue
                target = o.get("target") if isinstance(o.get("target"), dict) else {}
                if target.get("table"):
                    R.eq(A, opath, "writes table", target["table"], fo.get("target") if fo.get("kind") in ("table", "replaceTable") else None)
                elif target.get("property"):
                    got = fo.get("target") if fo.get("kind") == "property" else None
                    R.add("PASS" if str(got or "").lower() == str(target["property"]).lower() else "FAIL", A, opath,
                          "writes property", target["property"], got)
            for oname in outputs:
                if oname not in spec_outputs:
                    R.warn(A, "%s output %s" % (path, oname), "output in spec", None, outputs[oname].get("target"))
        for fd in found:
            if fd.get("name") not in names:
                R.warn(A, 'data function "%s"' % fd.get("name"), "data function in spec", None, fd.get("executor"))
            for fi in fd.get("inputs") or []:
                m = _DOCPROP_RE.match(fi.get("expression") or "")
                if m:
                    R.add("PASS" if m.group(2) == fi.get("name") else "FAIL", A,
                          'data function "%s" input %s' % (fd.get("name"), fi.get("name")),
                          "one name per binding (parameter = property)", m.group(2), fi.get("name"))

    # -- tables ----------------------------------------------------------------------------------
    def check_tables(self):
        R, A = self.R, "tables"
        found = self.model["tables"]
        by_name = dict((t.get("name"), t) for t in found)
        spec_tables = [t for t in self.spec.get("tables") or [] if isinstance(t, dict)]
        df_outputs = set()
        for d in self.spec.get("dataFunctions") or []:
            for o in (d.get("outputs") or []) if isinstance(d, dict) else []:
                if isinstance(o, dict) and isinstance(o.get("target"), dict) and o["target"].get("table"):
                    df_outputs.add(o["target"]["table"])
        names = set()
        source_class = {"sbdf": "SbdfFileDataSource", "csv": "TextFileDataSource", "dataFunction": "DataFunction"}
        for ts in spec_tables:
            name = ts.get("name")
            names.add(name)
            path = 'table "%s"' % name
            ft = by_name.get(name)
            if ft is None:
                folded = [t for t in found if (t.get("name") or "").lower() == str(name).lower()]
                R.fail(A, path, "present", name, folded[0]["name"] if folded else None,
                       note="name differs in case" if folded else None)
                continue
            R.ok(A, path, "present", name, ft.get("name"))
            src = ts.get("source") if isinstance(ts.get("source"), dict) else {}
            stype = src.get("type")
            if stype in source_class:
                R.eq(A, path, "source", source_class[stype], ft.get("sourceType"), bad="WARN")
            if stype == "dataFunction" and src.get("function"):
                R.eq(A, path, "produced by data function", src.get("function"), ft.get("dataFunction"))
            cols = dict((c["name"], c) for c in ft.get("columns") or [])
            meta = ts.get("columns") if isinstance(ts.get("columns"), dict) else {}
            missing = [c for c in meta if c not in cols]
            R.add("FAIL" if missing else "PASS", A, path, "spec columns present", sorted(meta), missing or "all present")
            if stype == "csv" and isinstance(src.get("columns"), dict):
                for cname, dtype in src["columns"].items():
                    if cname in cols:
                        R.eq(A, "%s column %s" % (path, cname), "data type", dtype, cols[cname].get("type"))
            for cname, cspec in sorted(meta.items()):
                if not isinstance(cspec, dict) or cname not in cols:
                    continue
                if cspec.get("format"):
                    R.eq(A, "%s column %s" % (path, cname), "format", cspec["format"], cols[cname].get("format"))
                if cspec.get("description"):
                    R.eq(A, "%s column %s" % (path, cname), "description", cspec["description"],
                         cols[cname].get("description"), bad="WARN")
            for cc in ts.get("calculatedColumns") or []:
                if not isinstance(cc, dict):
                    continue
                cpath = "%s calculated column %s" % (path, cc.get("name"))
                fc = cols.get(cc.get("name"))
                if fc is None:
                    R.fail(A, cpath, "present", cc.get("name"), None)
                    continue
                st, note = match_expression(props_shorthand(str(cc.get("expression") or "")), fc.get("calculated") or "")
                R.add(st, A, cpath, "expression", cc.get("expression"), fc.get("calculated"), note)
            for h in ts.get("hierarchies") or []:
                if isinstance(h, dict):
                    fc = cols.get(h.get("name"))
                    R.add("PASS" if fc is not None and fc.get("hierarchy") else "FAIL", A,
                          "%s hierarchy %s" % (path, h.get("name")), "present", h.get("levels"),
                          fc.get("hierarchy") if fc else None)
            if stype in ("sbdf", "csv"):
                want = bool(ts.get("embed", True))
                if want:
                    R.add("PASS" if ft.get("embedded") else "FAIL", A, path, "data embedded in the file", True,
                          ft.get("embedded"), note="CachingBehavior %s, useLinkedData %s, %s" % (
                              ft.get("cachingBehavior"), ft.get("useLinkedData"), ft.get("storedData") or "no DataTables entry"))
                else:
                    R.add("WARN" if ft.get("embedded") else "PASS", A, path, "data linked (embed: false)", False,
                          ft.get("embedded"), note="linked tables are not allowed in a delivered analysis")
            if ts.get("description"):
                R.eq(A, path, "description", ts.get("description"), ft.get("description"), bad="WARN")
        if self.default_table():
            R.eq(A, "tables", "default table", self.default_table(), self.model["document"].get("defaultTable"),
                 note=None if self.spec.get("defaultTable") else "no defaultTable in the spec: the first file table")
        for ft in found:
            if ft.get("name") not in names and ft.get("name") not in df_outputs:
                R.fail(A, 'table "%s"' % ft.get("name"), "table in spec", None, ft.get("sourceType"),
                       note="leftover table")

    def check_relations(self):
        R, A = self.R, "relations"
        found = self.model["relations"]
        used = set()
        for r in self.spec.get("relations") or []:
            if not isinstance(r, dict):
                continue
            pairs = [list(p) for p in r.get("on") or [] if isinstance(p, (list, tuple)) and len(p) == 2]
            path = "relation %s - %s" % (r.get("left"), r.get("right"))
            hit = None
            for i, f in enumerate(found):
                if i in used:
                    continue
                if f.get("left") == r.get("left") and f.get("right") == r.get("right"):
                    fp = f.get("pairs")
                elif f.get("left") == r.get("right") and f.get("right") == r.get("left"):
                    fp = [[b, a] for a, b in f.get("pairs") or []]
                else:
                    continue
                if sorted(map(tuple, fp)) == sorted(map(tuple, pairs)):
                    hit = i
                    break
            if hit is None:
                R.fail(A, path, "present with the column pairs", pairs,
                       [(f.get("left"), f.get("right"), f.get("pairs")) for f in found])
            else:
                used.add(hit)
                R.ok(A, path, "present with the column pairs", pairs, found[hit].get("expression"))
        for i, f in enumerate(found):
            if i not in used:
                R.warn(A, "relation %s - %s" % (f.get("left"), f.get("right")), "relation in spec", None, f.get("expression"))

    def check_markings(self):
        R, A = self.R, "markings"
        found = self.model["markings"]
        by_name = dict((m.get("name"), m) for m in found)
        spec_marks = [m for m in self.spec.get("markings") or [] if isinstance(m, dict)]
        names = set()
        if not spec_marks:
            spec_marks = [{"name": "Marking", "default": True}]
        for ms in spec_marks:
            name = ms.get("name")
            names.add(name)
            path = 'marking "%s"' % name
            fm = by_name.get(name)
            if fm is None:
                R.fail(A, path, "present", name, None)
                continue
            R.ok(A, path, "present", name, name)
            if ms.get("color"):
                R.eq(A, path, "color", normalize_color(ms["color"]), normalize_color(fm.get("color")))
            if fm.get("selectionsCount") or fm.get("partialSelections"):
                R.warn(A, path, "no saved marked rows", 0, fm.get("partialSelections") or fm.get("selectionsCount"),
                       note="saved marking state is not part of a build")
        R.eq(A, "markings", "default marking", self.default_marking(), self.model["document"].get("defaultMarking"))
        for fm in found:
            if fm.get("name") not in names:
                R.fail(A, 'marking "%s"' % fm.get("name"), "marking in spec", None, fm.get("color"),
                       note="leftover or auto-created marking")

    def check_filtering_schemes(self):
        R, A = self.R, "filteringSchemes"
        found = self.model["filteringSchemes"]
        by_name = dict((f.get("name"), f) for f in found)
        names = set()
        for fs in self.spec.get("filteringSchemes") or []:
            if not isinstance(fs, dict):
                continue
            name = fs.get("name")
            names.add(name)
            path = 'filtering scheme "%s"' % name
            ff = by_name.get(name)
            if ff is None:
                R.fail(A, path, "present", name, None)
                continue
            R.ok(A, path, "present", name, name)
            if fs.get("default"):
                R.eq(A, path, "default scheme", True, ff.get("default"))
        for ff in found:
            if ff.get("name") not in names and not ff.get("default"):
                R.warn(A, 'filtering scheme "%s"' % ff.get("name"), "scheme in spec", None, ff.get("name"))

    # -- hygiene ---------------------------------------------------------------------------------
    def check_hygiene(self):
        R, A = self.R, "hygiene"
        users = set()
        for var in ("USERNAME", "USER"):
            if os.environ.get(var):
                users.add(os.environ[var])
        try:
            users.add(Path.home().name)
        except RuntimeError:
            pass
        users = set(u for u in users if u and len(u) >= 3)

        findings = {}       # (kind, text) -> {"where": [...], "entries": [...], "other": bool}
        # A mod (visualization or action) loaded from its project folder (ModOrigin ManifestFile) or a .mod
        # file (File) persists that path in the document; its findings are WARNs that name the fix.
        mod_strings, mod_paths = self._mod_origin_paths()

        def record(kind, text, where, entry, mod=False):
            key = (kind, text)
            f = findings.setdefault(key, {"where": [], "entries": [], "other": False})
            if not mod:
                f["other"] = True
            w = where() if callable(where) else where
            if w and w not in f["where"] and len(f["where"]) < 4:
                f["where"].append(w)
            if entry not in f["entries"]:
                f["entries"].append(entry)

        user_needles = [u.lower() for u in sorted(users)]

        def scan(text, where, entry, mod=False):
            """Regexes run only on windows around fast substring hits (large documents stay fast)."""
            if not text:
                return
            if not mod:
                for mp in mod_paths:
                    if mp in text:
                        scan(mp, where, entry, mod=True)
                        text = text.replace(mp, " ")
            spans = []
            seen = set()
            for start, end in hit_windows(text, (":\\", ":/"), 2, 262) + hit_windows(text, ("\\\\",), 1, 262):
                chunk = text[start:end]
                for rx in (_DRIVE_PATH_RE, _UNC_RE):
                    for m in rx.finditer(chunk):
                        a = start + m.start()
                        if a in seen:
                            continue
                        seen.add(a)
                        value = m.group(0).rstrip(" .,;:)")
                        spans.append((a, start + m.end()))
                        record("local path", value, where, entry, mod)
                        for u in _USERS_DIR_RE.findall(value):
                            record("user name", u, where, entry, mod)
            if user_needles:
                low = text.lower()
                for needle in user_needles:
                    i = low.find(needle)
                    while i >= 0:
                        if not any(a <= i < b for a, b in spans):
                            record("user name", text[i:i + len(needle)], where, entry, mod)
                        i = low.find(needle, i + 1)
            else:
                low = None
            if "=" in text or ":" in text:
                low = low if low is not None else text.lower()
                cseen = set()
                for start, end in hit_windows(low, _CREDENTIAL_NEEDLES, 2, 300):
                    chunk = text[start:end]
                    for rx in _CREDENTIAL_RES:
                        for m in rx.finditer(chunk):
                            key = (start + m.start(1), m.group(1).lower())
                            if key in cseen or _placeholder_secret(m.group(2)):
                                continue
                            cseen.add(key)
                            record("credential", "%s=%s" % (m.group(1), _mask(m.group(2))), where, entry)

        main = self.archive.main_entry
        G = self.mb.G
        for obj in G.by_id.values():
            if isinstance(obj, sg.Str) and obj.value and obj.pfield not in _SKIP_HYGIENE_FIELDS:
                scan(decode_persisted(obj.value), (lambda o=obj: self.where_of(o)), main, id(obj) in mod_strings)
        for s in self.model["scripts"]:
            scan(s.get("code"), 'script "%s"' % s.get("name"), "EmbeddedScripts.xml")
        styles = self.model["document"].get("customStylesJson")
        if styles:
            scan(json.dumps(styles) if not isinstance(styles, str) else styles, "custom styles", "CustomStyles.json")
        skip_resources = set()
        for r in self.archive.resources.values():
            if r["name"] in ("EmbeddedScripts.xml", "CustomStyles.json"):
                skip_resources.add(r["entry"])
        for zi in self.archive.infos:
            name = zi.filename
            if name == main or name in skip_resources or name.endswith("/"):
                continue
            low = name.lower()
            if low.startswith("datatables/") or low.endswith((".png", ".jpg", ".zip", ".asice")) or low.startswith("mods/"):
                continue
            if zi.file_size > 200 * 1024 * 1024:
                continue
            text = self.archive.text(name)
            if text is None:
                continue
            if low.endswith("analysisdocument.xml"):
                text = text.replace("&#xD;", "\r").replace("&#xA;", "\n").replace("&quot;", '"')
                text = decode_persisted(text)
            scan(text, None, name)
        counts = {"local path": 0, "user name": 0, "credential": 0}
        mod_only = {"local path": 0, "user name": 0, "credential": 0}
        for (kind, text), f in sorted(findings.items(), key=lambda kv: (kv[0][0], kv[0][1].lower())):
            where = "; ".join(f["where"]) if f["where"] else None
            note = "in " + ", ".join(f["entries"])
            if not f["other"] and kind != "credential":
                mod_only[kind] += 1
                R.warn(A, where or f["entries"][0], "no %s" % kind, None, text,
                       note + "; cause: a mod was loaded from its project folder or a .mod file (ModOrigin "
                       "ManifestFile/File), so the document keeps that path; fix: embed the mod via the "
                       "development server (Connect to project, Disconnect) or the library before publishing, "
                       "then rebuild")
                continue
            counts[kind] += 1
            if kind == "local path" and "\\Temp\\Spotfire\\" in text:
                note += "; a stream source spools to this temp path"
            R.fail(A, where or f["entries"][0], "no %s" % kind, None, text, note)
        for kind, label in (("local path", "absolute local paths (drive letters, UNC shares)"),
                            ("user name", "Windows user names"), ("credential", "credential-like assignments")):
            if not counts[kind] and not mod_only[kind]:
                R.ok(A, "archive", "no %s" % label, 0, 0)
        if counts["local path"]:
            R.warn(A, "archive", "known issue: file tables keep their source path", None, None,
                   note="a file table persists its FilePath even when embedded (a stream source persists "
                   "its temp spool file instead); the standard engine loads sbdf tables by file name in apps "
                   "with features (engine/features/pathfree.py), so the "
                   "DXP keeps only NAME.sbdf: rebuild with the current engine, and check the build log's "
                   "'the DXP keeps the source path' NOTE lines")
        # structured: credentials in data-function inputs and property values
        for d in self.model["dataFunctions"]:
            for fi in d.get("inputs") or []:
                if fi.get("secretConstant"):
                    R.fail(A, 'data function "%s" input %s' % (d.get("name"), fi.get("name")),
                           "no credential stored as a constant input", None,
                           safe_expr(fi.get("name"), fi.get("expression")))
        for p in self.model["documentProperties"]:
            if credential_name(p.get("name")) and isinstance(p.get("value"), str) and \
                    not _placeholder_secret(p.get("value")):
                R.fail(A, 'property "%s"' % p.get("name"), "no credential stored in a property value", None,
                       _mask(p.get("value")))
        self.check_auto_names()

    def _mod_origin_paths(self):
        """(ids of the persisted path strings, the path texts) of mods (visualization and action) whose
        ModOrigin is a manifest file (loaded from the project folder) or a .mod file."""
        v = self.mb.v
        ids, paths = set(), []
        for node in self.mb.G.nodes_of("ModOrigin", exact=True):
            if v.prim(node.get("Origin")) not in ("ManifestFile", "File"):
                continue
            raw = self.mb.G.resolve(node.get("Value"))
            if isinstance(raw, sg.Str) and raw.value:
                ids.add(id(raw))
                text = decode_persisted(raw.value)
                if text not in paths:
                    paths.append(text)
        return ids, paths

    def where_of(self, s):
        """Readable owner of a persisted string: table / column / visual / page / data function / property."""
        v = self.mb.v
        field = s.pfield
        cur = s.parent
        while cur is not None:
            if isinstance(cur, sg.Node) and cur.type is not None:
                t = cur.type.short
                if t == "DataColumn":
                    owner = self.mb.G.owner(cur, "DataTable")
                    return 'column "%s" of table "%s" (%s)' % (v.s(cur, "Name"), v.s(owner, "Name") if owner else "?", field)
                if t == "DataTable":
                    return 'table "%s" (%s)' % (v.s(cur, "Name"), field)
                if t == "DataFunctionImpl":
                    return 'data function "%s" (%s)' % (self.mb.df_by_impl.get(cur.id), field)
                if t == "DataFunction":
                    return 'data function "%s" (%s)' % (v.s(cur, "Name"), field)
                if t == "DataProperty":
                    return 'property "%s" (%s)' % (v.s(cur, "Name"), field)
                if t == "Visual":
                    page = self.mb.G.owner(cur, "Page")
                    return 'visual "%s"%s (%s)' % (v.s(cur, "TitleExpression", "Expression"),
                                                  (' on page "%s"' % v.s(page, "TitleExpression", "Expression")) if page else "",
                                                  field)
                if t == "Page":
                    return 'page "%s" (%s)' % (v.s(cur, "TitleExpression", "Expression"), field)
                if t in ("ManagedVisualizationMod", "ManagedActionMod"):
                    return 'mod "%s" origin (%s)' % (v.s(cur, "ModId"), field)
            cur = getattr(cur, "parent", None)
        return "document (%s)" % field

    def check_auto_names(self):
        R, A = self.R, "hygiene"
        m = self.model
        named = []
        for p in m["pages"]:
            named.append(("page", p.get("title")))
            for vis in p.get("visuals") or []:
                named.append(("visual", vis.get("title")))
        for t in m["tables"]:
            named.append(("table", t.get("name")))
            for c in t.get("columns") or []:
                if re.match(r"^Column \d+$", c.get("name") or ""):
                    R.warn(A, 'column "%s" of table "%s"' % (c["name"], t["name"]), "no generated column name",
                           None, c["name"])
        for mk in m["markings"]:
            named.append(("marking", mk.get("name")))
        for f in m["filteringSchemes"]:
            named.append(("filtering scheme", f.get("name")))
        for s in m["scripts"]:
            named.append(("script", s.get("name")))
        for p in m["documentProperties"]:
            named.append(("property", p.get("name")))
        for d in m["dataFunctions"]:
            named.append(("data function", d.get("name")))
            for label, value in (("DisplayName", d.get("displayName")), ("FunctionName", d.get("functionName"))):
                named.append(('data function "%s" %s' % (d.get("name"), label), value))
        bad = 0
        for kind, name in named:
            if not name:
                continue
            problem = None
            if _AUTO_NAME_RE.search(name):
                problem = "auto-generated name"
            elif kind == "page" and _TEMP_PAGE_RE.match(name):
                problem = "builder's temporary page title"
            elif kind in ("page", "visual") and name in _DEFAULT_TITLES:
                problem = "Spotfire's default title"
            if problem:
                bad += 1
                path = kind if kind.startswith("data function \"") else '%s "%s"' % (kind, name)
                R.fail(A, path, "no auto-generated name", None, name, problem)
        if not bad:
            R.ok(A, "names", "no auto-generated names", 0, 0)
        for p in m["pages"]:
            for i, vis in enumerate(p.get("visuals") or []):
                if vis.get("title") and "${AutoTitle}" in vis["title"] and vis.get("showTitle"):
                    R.warn(A, 'page "%s" visual %d (%s)' % (p.get("title"), i + 1, vis.get("typeId")),
                           "no ${AutoTitle} on a visible title", None, vis["title"])

    # -- naming policy ---------------------------------------------------------------------------
    def check_naming(self):
        R, A = self.R, "naming"
        policy = (self.spec.get("app") or {}).get("namingPolicy") or "program"
        m = self.model
        groups = (
            ("table", "tables", [t.get("name") for t in m["tables"]]),
            ("property", "document properties", [p.get("name") for p in m["documentProperties"]]),
            ("script", "scripts", [s.get("name") for s in m["scripts"]
                                   if s.get("language", "").lower().startswith("ironpython")]),
            ("function", "data functions", [d.get("name") for d in m["dataFunctions"]]),
            ("page", "pages", [p.get("title") for p in m["pages"]]),
            ("marking", "markings", [mk.get("name") for mk in m["markings"]]),
        )
        for kind, label, names in groups:
            problems = 0
            for name in names:
                if not name:
                    continue
                for level, message in self.dxpgen.naming_issues(kind, name, policy):
                    if "looks auto-generated" in message:
                        continue                                     # reported by the auto-name scan
                    problems += 1
                    R.add("FAIL" if level == "error" else "WARN", A, '%s "%s"' % (kind, name),
                          "%s naming policy" % policy, None, name, message)
            if not problems:
                R.ok(A, label, "%s naming policy" % policy, "%d name(s)" % len([n for n in names if n]), "all follow it")

    # -- build report ----------------------------------------------------------------------------
    def check_build_report(self):
        R, A = self.R, "build"
        rep = self.report
        if not isinstance(rep, dict):
            R.warn(A, "build/build-report.json", "build report present", "build-report.json", None,
                   note="matching fell back to titles and types")
            return
        R.ok(A, str(self.report_path), "build report read", None, "status %s, finished %s" % (rep.get("status"),
                                                                                              rep.get("finished")))
        if self.raw_spec is not None and rep.get("spec"):
            now = hashlib.sha256(self.raw_spec).hexdigest()
            R.eq(A, "build report", "built from the current spec.json (sha256)", now, rep.get("spec"), bad="WARN",
                 note=None if now == rep.get("spec") else "spec.json changed after the build: rebuild")
        out = rep.get("output")
        if out:
            same = os.path.normcase(os.path.normpath(str(out))) == os.path.normcase(os.path.normpath(str(self.dxp_path)))
            R.add("PASS" if same else "WARN", A, "build report", "output is the DXP checked", str(self.dxp_path), out)
        if rep.get("saved") is False:
            R.warn(A, "build report", "saved by the builder", True, False)
        for s in rep.get("steps") or []:
            if isinstance(s, dict) and s.get("status") == "failed":
                R.warn(A, "%s.%s %s" % (s.get("group"), s.get("name"), s.get("target")), "build step succeeded", "ok",
                       "failed", short(s.get("message"), 300))
        for f in rep.get("fallbacks") or []:
            if isinstance(f, dict):
                R.warn(A, str(f.get("target")), "fallback (%s)" % f.get("feature"), None, short(f.get("reason"), 300),
                       "manual step: " + str(f.get("manual")))
        for w in rep.get("warnings") or []:
            R.warn(A, "build warning", "builder warning", None, short(w, 400))
        if not rep.get("fallbacks"):
            R.ok(A, "build report", "no open manual steps", 0, 0)

    # -- output ----------------------------------------------------------------------------------
    def _finish(self, code):
        self.status_code = code
        try:
            self.write_reports()
        except OSError as e:
            sys.stderr.write("could not write the verify report: %s\n" % e)
        return code

    def summary(self):
        c = self.R.counts()
        if self.status_code == EXIT_USAGE:
            status = "NOT CHECKED"
        else:
            status = "FAIL" if c["FAIL"] else "PASS"
        return status, c

    def write_reports(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        status, c = self.summary()
        app = (self.spec or {}).get("app") or {}
        data = {
            "tool": "verify_dxp.py",
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "app": app.get("name"),
            "appDir": str(self.app_dir),
            "spec": str(self.spec_path),
            "dxp": str(self.dxp_path) if self.dxp_path else None,
            "buildReport": str(self.report_path) if self.report_path else None,
            "status": status,
            "summary": c,
            "checks": self.R.items,
        }
        (self.out_dir / "verify-report.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        (self.out_dir / "verify-report.md").write_text(self.markdown(data), encoding="utf-8")

    @staticmethod
    def line(it):
        def show(value, n):
            if value is None:
                return "-"
            if isinstance(value, str):
                return '""' if value == "" else short(value, n)
            return short(value, n)

        text = "%s %s: %s" % (it["status"], it["path"], it["check"])
        exp, fnd = it.get("expected"), it.get("found")
        if exp is not None or fnd is not None:
            if exp == fnd or (it["status"] == "PASS" and exp is None):
                text += " = %s" % show(fnd, 200)
            elif exp is None:
                text += " - found %s" % show(fnd, 220)
            else:
                text += " - expected %s, found %s" % (show(exp, 220), show(fnd, 220))
        if it.get("note"):
            text += " (%s)" % short(it["note"], 400)
        return text

    def markdown(self, data):
        L = []
        w = L.append
        w("# Verify report: %s" % (data.get("app") or self.app_dir.name))
        w("")
        w("- Result: **%s** - %d PASS, %d FAIL, %d WARN" % (data["status"], data["summary"]["PASS"],
                                                          data["summary"]["FAIL"], data["summary"]["WARN"]))
        w("- DXP: `%s`" % data.get("dxp"))
        w("- Spec: `%s`" % data.get("spec"))
        w("- Build report: %s" % (("`%s`" % data["buildReport"]) if data.get("buildReport") else "none"))
        w("- Generated: %s by scripts/verify_dxp.py" % data["generated"])
        w("")
        fails = [it for it in self.R.items if it["status"] == "FAIL"]
        warns = [it for it in self.R.items if it["status"] == "WARN"]
        if fails:
            w("## Failures")
            w("")
            for it in fails:
                w("- " + self.line(it))
            w("")
        if warns:
            w("## Warnings")
            w("")
            for it in warns:
                w("- " + self.line(it))
            w("")
        w("## All checks")
        w("")
        for area, title in AREAS:
            items = [it for it in self.R.items if it["area"] == area]
            if not items:
                continue
            c = {"PASS": 0, "FAIL": 0, "WARN": 0}
            for it in items:
                c[it["status"]] += 1
            w("### %s (%d PASS, %d FAIL, %d WARN)" % (title, c["PASS"], c["FAIL"], c["WARN"]))
            w("")
            for it in items:
                w("- " + self.line(it))
            w("")
        return "\n".join(L)

    def console_summary(self):
        status, c = self.summary()
        lines = ["verify %s: %s - %d PASS, %d FAIL, %d WARN" % (self.app_dir.name, status, c["PASS"], c["FAIL"], c["WARN"])]
        for it in [it for it in self.R.items if it["status"] == "FAIL"][:25]:
            lines.append("  " + self.line(it))
        nfail = c["FAIL"]
        if nfail > 25:
            lines.append("  ... %d more FAIL lines" % (nfail - 25))
        lines.append("report: %s" % (self.out_dir / "verify-report.md"))
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------
def cmd_dump(args, out=None):
    out = out or sys.stdout
    path = Path(args.dxp)
    if not path.is_file():
        sys.stderr.write("DXP not found: %s\n" % path)
        return EXIT_USAGE
    try:
        model, _, archive = build_model(path, reveal_secrets=args.reveal_secrets)
    except DxpError as e:
        sys.stderr.write("%s\n" % e)
        return EXIT_USAGE
    archive.close()
    text = json.dumps(model, indent=2, ensure_ascii=False, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        out.write("model written to %s\n" % args.out)
    else:
        out.write(text + "\n")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="verify_dxp.py", description=(
        "Read a saved Spotfire DXP (read-only) and compare it with the app spec. "
        "Exit codes: 0 no FAIL, 1 FAIL, 2 usage."))
    sub = parser.add_subparsers(dest="command", metavar="{dump,check}")
    p_dump = sub.add_parser("dump", help="print the JSON model of a DXP")
    p_dump.add_argument("dxp", help="path of the .dxp file")
    p_dump.add_argument("--out", help="write the model to this file instead of stdout")
    p_dump.add_argument("--reveal-secrets", action="store_true",
                        help="show string constants of credential-like data-function inputs (masked by default)")
    p_check = sub.add_parser("check", help="compare an app's spec with its saved DXP")
    p_check.add_argument("app", help="app folder, spec.json, or app slug")
    p_check.add_argument("--dxp", help="the saved DXP to check (default: the spec's app.output for the "
                                       "standard tier)")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ("dump", "check") and not argv[0].startswith("-"):
        argv.insert(0, "check")                   # "verify_dxp.py <app>" (references/architecture.md pipeline) = check
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "dump":
        return cmd_dump(args)
    return cmd_check(args)


def cmd_check(args, out=None):
    out = out or sys.stdout
    dxpgen = load_dxpgen()
    if dxpgen is None:
        sys.stderr.write("dxpgen.py could not be imported; it resolves the spec defaults and the naming "
                         "policy for check\n")
        return EXIT_USAGE
    found = dxpgen.resolve_app(args.app)
    if found is None:
        root = dxpgen.workspace_root()
        where = str(root / "apps") if root is not None else "$DXP_WORKSPACE/apps (DXP_WORKSPACE is not set)"
        sys.stderr.write("app not found: %s (give an app folder, its spec.json, or an app slug under %s)\n"
                         % (args.app, where))
        return EXIT_USAGE
    app_dir, spec_path = found
    if not Path(spec_path).is_file():
        sys.stderr.write("no spec.json in %s\n" % app_dir)
        return EXIT_USAGE
    checker = Checker(Path(app_dir), Path(spec_path), dxpgen, dxp_override=getattr(args, "dxp", None))
    code = checker.run()
    out.write(checker.console_summary() + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
