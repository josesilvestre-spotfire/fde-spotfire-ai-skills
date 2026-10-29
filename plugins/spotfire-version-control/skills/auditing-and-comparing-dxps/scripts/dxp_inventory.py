"""dxp_inventory.py: read Spotfire .dxp files without Spotfire and audit them.

The DXP is opened read-only as a ZIP archive and is never modified. Only the
Python standard library is used (Python 3.10 or newer).

Commands:

  python dxp_inventory.py inventory analysis.dxp [--json out.json] [--md out.md]
      Lists pages, visuals (type, table, marking, axes, layout), text areas,
      data functions (script, inputs, outputs, trust stamp), IronPython and
      JavaScript scripts, property triggers, document properties, data tables,
      markings, filtering schemes, mods and the colors in use. Prints a
      Markdown summary unless --json or --md is given.

  python dxp_inventory.py text analysis.dxp [-o out.txt]
      Writes the whole inventory as one readable text document, one section
      per page, data function, script and table. Objects are keyed by name,
      never by internal id, so a plain re-save gives the same text. The
      command also works as a git textconv driver (see the skill).

  python dxp_inventory.py compare old.dxp new.dxp [--stat] [-o out.diff]
      Unified diff of the two text documents, section by section, with a
      summary of added and removed pages, visuals, data functions and
      scripts. Exit code 1 when the files differ, 0 when they match.

  python dxp_inventory.py check analysis.dxp [--json out.json]
      Runs the design-rule checks (references/design-rule-checks.md) and
      prints one line per finding: FAIL, WARN or INFO. Exit code 1 when any
      FAIL is found.

  python dxp_inventory.py library <folder> -o <report folder> [--recursive]
      Inventories and checks every .dxp in the folder, groups the files that
      are versions of one analysis (name_v1.dxp, name_v2.dxp, "Name (3).dxp",
      name_20261026.dxp), diffs consecutive versions and writes LIBRARY.md
      with text/, diffs/ and checks/ next to it.

Exit codes: 0 success, 1 differences or FAIL findings, 2 bad input.
"""
import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = "{http://www.spotfire.com/schemas/Document1.0.xsd}"
EXIT_OK, EXIT_DIFF, EXIT_USAGE = 0, 1, 2
LAYOUT_GRID = 100000.0


# --------------------------------------------------------------------------
# Object graph reader for AnalysisDocument.xml
#
# Spotfire writes the analysis as a serialized object graph: every Object,
# Struct, Array and String carries a document-wide Id, a value written before
# is repeated as <ObjectRef Value="Id"/>, and each type is declared once
# (TypeObject) and referenced afterwards (TypeRef).
# --------------------------------------------------------------------------
class TypeInfo:
    __slots__ = ("id", "full", "base")

    def __init__(self, type_id, full, base=None):
        self.id, self.full, self.base = type_id, full or "", base

    @property
    def name(self):
        return self.full.split("[")[0].split(",")[0].split(".")[-1]

    def is_a(self, short_name):
        t = self
        while t is not None:
            if t.name.split("`")[0] == short_name:
                return True
            t = t.base
        return False


class Node:
    __slots__ = ("kind", "id", "type", "fields")

    def __init__(self, kind, node_id, node_type):
        self.kind, self.id, self.type, self.fields = kind, node_id, node_type, []

    def get(self, name):
        for key, value in self.fields:
            if key == name:
                return value
        return None


class Arr:
    __slots__ = ("id", "type", "items", "inline")

    def __init__(self, arr_id, arr_type):
        self.id, self.type, self.items, self.inline = arr_id, arr_type, [], None


class Str:
    __slots__ = ("id", "value")

    def __init__(self, str_id, value):
        self.id, self.value = str_id, value


class Ref:
    __slots__ = ("id",)

    def __init__(self, ref_id):
        self.id = ref_id


class Prim:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind, self.value = kind, value


class Graph:
    def __init__(self, xml_bytes):
        self.by_id = {}
        self.types = {}
        root = ET.fromstring(xml_bytes)
        self.root = self._value(list(root)[0])

    def _type(self, el):
        if el is None:
            return None
        tag = el.tag[len(NS):]
        if tag in ("Type", "GenericArgument", "BaseType"):
            kids = list(el)
            return self._type(kids[0]) if kids else None
        if tag == "TypeRef":
            return self.types.get(int(el.get("Value")))
        if tag == "TypeObject":
            info = TypeInfo(int(el.get("Id")), el.get("FullTypeName"))
            self.types[info.id] = info
            for part in el:
                if part.tag == NS + "NonSystemTypeInfo":
                    base = part.find(NS + "BaseType")
                    if base is not None:
                        info.base = self._type(base)
                elif part.tag == NS + "GenericTypeInfo":
                    for group in part:
                        for arg in group:
                            self._type(arg)
            return info
        return None

    def _value(self, el):
        tag = el.tag[len(NS):]
        if tag in ("Object", "Struct"):
            node = Node(tag, int(el.get("Id")),
                        self._type(el.find(NS + "Type")))
            self.by_id[node.id] = node
            fields = el.find(NS + "Fields")
            if fields is not None:
                for field in fields:
                    kids = list(field)
                    node.fields.append(
                        (field.get("Name"),
                         self._value(kids[0]) if kids else None))
            return node
        if tag in ("Array", "MultiDimensionalArray"):
            arr = Arr(int(el.get("Id")), self._type(el.find(NS + "Type")))
            self.by_id[arr.id] = arr
            elements = el.find(NS + "Elements")
            if elements is not None:
                kids = list(elements)
                if not kids:
                    arr.inline = elements.text
                for kid in kids:
                    if kid.tag == NS + "IndexedElement":
                        inner = list(kid)
                        arr.items.append(self._value(inner[0])
                                         if inner else None)
                    else:
                        arr.items.append(self._value(kid))
            return arr
        if tag == "String":
            value = "" if el.get("IsEmpty") == "true" else el.get("Value")
            text = Str(int(el.get("Id")), value or "")
            self.by_id[text.id] = text
            return text
        if tag == "ObjectRef":
            ref = int(el.get("Value"))
            return None if ref == 0 else Ref(ref)
        if tag == "Enum":
            self._type(el.find(NS + "Type"))
            return Prim("Enum", el.get("Value"))
        if tag == "NullableNull":
            return None
        if tag in ("TypeObject", "TypeRef"):
            return self._type(el)
        return Prim(tag, el.get("Value"))

    # -- navigation helpers -------------------------------------------------
    def r(self, value):
        while isinstance(value, Ref):
            value = self.by_id.get(value.id)
        return value

    def path(self, node, *names):
        cur = node
        for name in names:
            cur = self.r(cur)
            if not isinstance(cur, Node):
                return None
            cur = cur.get(name)
        return self.r(cur)

    def text(self, value):
        value = self.r(value)
        if isinstance(value, Str):
            return value.value
        if isinstance(value, Prim):
            return value.value
        return None

    def items(self, value):
        """Unwrap Spotfire collections (Items, Nodes, _items) to a list."""
        value = self.r(value)
        if isinstance(value, Arr):
            return [self.r(x) for x in value.items]
        if isinstance(value, Node):
            size = self.r(value.get("_size"))
            for name in ("Items", "Nodes", "_items", "Pages"):
                inner = value.get(name)
                if inner is None:
                    continue
                found = self.items(inner)
                if isinstance(size, Prim) and name == "_items":
                    found = found[:int(size.value)]
                return found
        return []

    def name(self, value):
        value = self.r(value)
        if isinstance(value, Node):
            for field in ("Name", "Title"):
                text = self.text(value.get(field))
                if text:
                    return text
        return None

    def walk(self, start, skip=()):
        """Every node defined under start (ObjectRefs are not followed).
        Fields named in skip are not entered."""
        stack = [start]
        while stack:
            value = stack.pop()
            if isinstance(value, Node):
                yield value
                stack.extend(v for k, v in value.fields
                             if isinstance(v, (Node, Arr)) and k not in skip)
            elif isinstance(value, Arr):
                stack.extend(v for v in value.items
                             if isinstance(v, (Node, Arr)))


def expression(graph, node):
    """Expression text of an axis, title or managed expression node."""
    node = graph.r(node)
    if not isinstance(node, Node):
        return None
    for path in (("ExpressionTexts", "Expression"), ("Expression",),
                 ("Expression", "Expression")):
        text = graph.text(graph.path(node, *path))
        if text is not None:
            return text
    return None


def argb_hex(value):
    try:
        argb = int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    alpha = argb >> 24
    rgb = "#%06X" % (argb & 0xFFFFFF)
    return rgb if alpha == 0xFF else "%s (alpha %d)" % (rgb, alpha)


def color_of(graph, node):
    node = graph.r(node)
    if not isinstance(node, Node) or node.type is None:
        return None
    if node.type.name == "Color":
        name = graph.text(node.get("name"))
        if name:
            return name
        return argb_hex(graph.text(node.get("value")))
    if node.type.name == "ColorInfo":
        return argb_hex(graph.text(node.get("argb")))
    return None


def decode_spotfire_text(text):
    """Spotfire writes control characters as _xHHHH_ in some strings."""
    if not text:
        return text or ""
    return re.sub(r"_x([0-9A-Fa-f]{4})_",
                  lambda m: chr(int(m.group(1), 16)), text)


def norm_newlines(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
# Fields that hold Spotfire's built-in palettes and defaults rather than
# colors an author chose.
DEFAULT_COLOR_FIELDS = {"Palette", "DefaultCategoricalRules",
                        "DefaultContinuousRules", "DefaultDefaultColor",
                        "AutomaticColorAssignment", "ColorScheme",
                        "EmptyColor", "ErrorBars"}
HEX_COLOR = re.compile(r"(?<![&\w])#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})"
                       r"(?![0-9A-Za-z])")
RGB_COLOR = re.compile(r"rgba?\([^)]{5,40}\)", re.I)


def css_colors(text):
    found = [c.upper() for c in HEX_COLOR.findall(text or "")]
    found += [re.sub(r"\s+", "", c.lower()) for c in RGB_COLOR.findall(text
                                                                     or "")]
    return found


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)
        self.names = self.zip.namelist()
        self.resources = {}
        if "EmbeddedResources.xml" in self.names:
            root = ET.fromstring(self.zip.read("EmbeddedResources.xml"))
            for res in root:
                self.resources[res.get("Id")] = (res.get("Name"),
                                                 res.get("ArchiveElementPath"))

    def read(self, name):
        return self.zip.read(name)

    def resource(self, resource_name):
        for name, entry in self.resources.values():
            if name == resource_name and entry in self.names:
                return self.zip.read(entry)
        return None

    def metadata(self):
        out = {"compatibility": None, "savedBy": None, "documents": []}
        if "Metadata.xml" not in self.names:
            return out
        root = ET.fromstring(self.zip.read("Metadata.xml"))
        out["compatibility"] = root.get("CompatibilityVersion")
        for prop in root.iter():
            if prop.get("ArchiveElementType") == "AnalysisDocument":
                out["documents"].append((prop.get("Version"),
                                         prop.get("ArchiveElementPath")))
            if prop.get("Key") == "SavedByAssemblyFileVersion":
                out["savedBy"] = prop.get("Value")
        return out


def read_scripts(archive):
    """IronPython and JavaScript definitions from EmbeddedScripts.xml."""
    data = archive.resource("EmbeddedScripts.xml")
    scripts = {}
    if not data:
        return scripts
    root = ET.fromstring(data.decode("utf-8-sig"))
    for item in root.iter("EmbeddedScript"):
        definition = item.find("ScriptDefinition")
        if definition is None:
            continue
        params = []
        for param in definition.iter("ScriptParameter"):
            params.append({"name": param.get("Name"),
                           "type": param.get("TypeName"),
                           "description": (param.findtext("Description")
                                           or "").strip()})
        language = definition.get("LanguageName") or ""
        version = definition.get("LanguageVersion") or ""
        stamp = (definition.findtext("ApprovalStamp") or "").strip()
        scripts[item.get("ManagedScriptId")] = {
            "name": definition.get("Name"),
            "language": (language + " " + version).strip(),
            "transaction": definition.get("WrapScript") == "true",
            "description": (definition.findtext("Description")
                            or "").strip(),
            "parameters": params,
            "code": norm_newlines(decode_spotfire_text(
                definition.findtext("ScriptCode") or "")),
            "trustStamp": stamp_digest(stamp),
        }
    return scripts


def stamp_digest(stamp):
    """Short digest of a trust stamp: shows a re-trust in a diff without
    copying the stamp itself."""
    if not stamp:
        return None
    return hashlib.sha256(stamp.encode("utf-8")).hexdigest()[:8]


def node_id_of(graph, node):
    return graph.text(graph.r(node).get("DocumentNodeId")) \
        if isinstance(graph.r(node), Node) else None


def script_name(graph, managed_script, scripts):
    """ManagedScript -> script name, through DocumentNodeId. Action mod
    scripts are named by their id in the mod manifest."""
    reference = graph.path(managed_script, "ScriptDefinitionReference")
    if isinstance(reference, Node) and reference.type is not None and \
            reference.type.name.startswith("ActionMod"):
        return "action mod script " + (graph.text(reference.get("Id"))
                                       or "?")
    definition = graph.path(reference, "ScriptReference")
    key = node_id_of(graph, definition)
    if key and key in scripts:
        return scripts[key]["name"]
    return None


def read_function_definition(xml_text):
    """Parse the FunctionDefinition XML a data function stores as a string."""
    out = {"script": "", "inputs": [], "outputs": [], "engine": None,
           "description": "", "displayName": None, "trustStamp": None}
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return out
    out["displayName"] = root.findtext("DisplayName")
    out["description"] = (root.findtext("Description") or "").strip()
    out["engine"] = root.findtext("ServiceType/Name")
    impl = root.find("ImplementationSpecificInformation")
    if impl is not None:
        out["script"] = norm_newlines(decode_spotfire_text(
            impl.findtext("script") or ""))
    for arg in root.findall("InputArguments/InputArgument"):
        out["inputs"].append({
            "name": arg.findtext("Name"),
            "type": arg.findtext("ArgumentType"),
            "optional": arg.findtext("IsOptional") == "true"})
    for res in root.findall("OutputResults/OutputResult"):
        out["outputs"].append({"name": res.findtext("Name"),
                               "type": res.findtext("ArgumentType")})
    stamp = None
    for el in root.iter("ApprovalStamp"):
        stamp = (el.text or "").strip() or stamp
    out["trustStamp"] = stamp_digest(stamp)
    return out


def keyed_items(graph, value):
    """KeyValuePair arrays -> list of (key, value)."""
    pairs = []
    for item in graph.items(value):
        if isinstance(item, Node):
            pairs.append((graph.text(item.get("key")),
                          graph.r(item.get("value"))))
    return pairs


def data_functions(graph, manager):
    out = []
    for fn in graph.items(graph.path(manager, "DataFunctions")):
        if not isinstance(fn, Node):
            continue
        impl = graph.r(fn.get("FunctionImpl"))
        data = graph.text(graph.path(impl, "FunctionDefinition", "Data"))
        info = read_function_definition(data or "")
        bindings = {}
        for key, value in keyed_items(graph, graph.path(impl, "Inputs",
                                                        "Inputs")):
            bindings[key] = expression(graph, value) or (
                value.type.name if isinstance(value, Node) else None)
        targets = {}
        for key, value in keyed_items(graph, graph.path(impl, "Outputs",
                                                        "Outputs")):
            if isinstance(value, Node):
                target = (graph.text(value.get("PropertyName"))
                          or graph.text(value.get("SuggestedName"))
                          or graph.name(graph.path(value, "TableReference")))
                targets[key] = ("%s %s" % (value.type.name,
                                           target or "")).strip()
        for item in info["inputs"]:
            item["binding"] = bindings.get(item["name"])
        for item in info["outputs"]:
            item["target"] = targets.get(item["name"])
        info["name"] = graph.text(fn.get("Name"))
        info["updateBehavior"] = graph.text(impl.get("UpdateBehavior")) \
            if isinstance(impl, Node) else None
        out.append(info)
    return out


def data_tables(graph, manager):
    out = []
    for table in graph.items(graph.path(manager, "Tables")):
        if not isinstance(table, Node):
            continue
        columns = []
        for col in graph.items(graph.path(table, "Columns")):
            if not isinstance(col, Node):
                continue
            source = graph.r(col.get("Source"))
            kind = source.type.name if isinstance(source, Node) else None
            expr = None
            if isinstance(source, Node):
                expr = expression(graph, graph.path(
                    source, "OwnedColumnProducer"))
            columns.append({
                "name": graph.text(col.get("Name")),
                "type": graph.text(graph.path(col, "DataType", "name")),
                "kind": (kind or "").replace("ColumnImpl", "") or None,
                "expression": expr})
        sources = []
        for producer in graph.items(table.get("ColumnProducers")):
            if not isinstance(producer, Node):
                continue
            entry = {"producer": producer.type.name}
            source = graph.path(producer, "DataFlow", "DataSource")
            if isinstance(source, Node):
                entry["source"] = source.type.name
                entry["path"] = graph.text(source.get("FilePath"))
            caching = graph.text(producer.get("CachingBehavior"))
            if caching:
                entry["caching"] = caching
            sources.append(entry)
        out.append({"name": graph.text(table.get("Name")),
                    "columns": columns, "sources": sources})
    return out


def document_properties(graph, manager):
    out = []
    props = graph.path(manager, "PropertyRegistry", "AnalysisProperties",
                       "Properties")
    for prop in graph.items(props):
        if not isinstance(prop, Node):
            continue
        attributes = graph.text(prop.get("Attributes")) or ""
        if "IsStandard" in attributes:
            continue
        value = graph.r(prop.get("Value"))
        if isinstance(value, Node) and value.get("m_value") is not None:
            value = graph.r(value.get("m_value"))
        if isinstance(value, (Str, Prim)):
            shown = value.value
        elif value is None:
            shown = None
        else:
            shown = "<%s>" % (value.type.name if getattr(value, "type", None)
                              else "value")
        out.append({"name": graph.text(prop.get("Name")),
                    "type": graph.text(graph.path(prop, "DataType", "name")),
                    "value": shown,
                    "description": graph.text(prop.get("Description"))})
    return sorted(out, key=lambda p: (p["name"] or "").lower())


def mod_axes(graph, collection):
    out = {}
    for key, axis in keyed_items(graph, graph.path(collection, "Axes")):
        text = expression(graph, axis)
        if text and text != "<>":
            out[key] = text
    return out


def visual_entry(graph, visual, bounds, scripts):
    content = graph.r(visual.get("InternalContent"))
    entry = {"title": expression(graph, visual.get("TitleExpression")),
             "showTitle": graph.text(visual.get("ShowTitle")) == "true",
             "type": None, "layout": bounds}
    if not isinstance(content, Node):
        return entry
    entry["type"] = graph.text(graph.path(content, "TypeId", "Name")) \
        or content.type.name
    data = graph.r(content.get("Data"))
    if isinstance(data, Node):
        entry["table"] = graph.name(data.get("DataTable"))
        entry["marking"] = graph.name(data.get("Marking"))
        limit = [graph.name(graph.path(f, "Reference"))
                 for f in graph.items(data.get("Filterings"))]
        entry["limitByMarkings"] = [x for x in limit if x]
        entry["whereClause"] = expression(graph,
                                          data.get("WhereClauseExpression"))
    axes = {}
    for key, value in content.fields:
        value = graph.r(value)
        if isinstance(value, Node) and value.type is not None and \
                value.type.name.endswith("Axis"):
            text = expression(graph, value)
            if text and text != "<>":
                axes[key] = text
        if key == "ScatterLayer" and isinstance(value, Node):
            for sub, axis in value.fields:
                text = expression(graph, axis)
                if isinstance(graph.r(axis), Node) and text and \
                        text != "<>" and \
                        graph.r(axis).type.name.endswith("Axis"):
                    axes[sub] = text
    trellis = graph.r(content.get("Trellis"))
    if isinstance(trellis, Node):
        for key, value in trellis.fields:
            text = expression(graph, value)
            if text and text != "<>":
                axes["Trellis." + key] = text
    entry["axes"] = axes
    if entry["type"] == "Spotfire.HtmlTextArea":
        entry["html"] = norm_newlines(graph.text(content.get("HtmlContent")))
        controls = []
        for control in graph.items(content.get("Controls")):
            if not isinstance(control, Node):
                continue
            kind = control.type.name
            label = graph.text(control.get("Label"))
            render = graph.text(control.get("RenderType")) or \
                graph.text(control.get("ViewMode"))
            prop = graph.name(graph.path(control, "DataProperty",
                                         "DataProperty"))
            action = script_name(graph, control.get("ScriptApplication"),
                                 scripts)
            function = graph.name(control.get("DataFunctionReference"))
            link = "page link" if graph.r(
                control.get("ActionLinkReference")) is not None else None
            controls.append({k: v for k, v in (
                ("kind", kind), ("render", render), ("label", label),
                ("property", prop), ("script", action),
                ("dataFunction", function), ("action", link)) if v})
        entry["controls"] = controls
        entry["javaScripts"] = [
            script_name(graph, graph.path(js, "ScriptApplication"), scripts)
            for js in graph.items(content.get("CustomJavaScripts"))]
    if entry["type"] == "Spotfire.Mod" or content.type.name == \
            "ModVisualization":
        meta = graph.text(content.get("Metadata"))
        try:
            meta = json.loads(meta) if meta else {}
        except ValueError:
            meta = {}
        entry["mod"] = {k: meta.get(k) for k in ("id", "name", "version")}
        entry["axes"].update(mod_axes(graph, content.get("AxisCollection")))
        layers = []
        for layer in graph.items(content.get("LayerCollection")):
            if not isinstance(layer, Node):
                continue
            inner = graph.r(layer.get("Layer"))
            layers.append({
                "title": expression(graph, layer.get("TitleExpression")),
                "table": graph.name(graph.path(inner, "Data", "DataTable")),
                "marking": graph.name(graph.path(inner, "Data", "Marking")),
                "axes": mod_axes(graph, graph.path(inner, "AxisCollection"))})
        entry["layers"] = layers
    colors = []
    for node in graph.walk(content, skip=DEFAULT_COLOR_FIELDS):
        if node is content:
            continue
        found = color_of(graph, node)
        if found:
            colors.append(found)
    entry["colors"] = sorted(set(colors))
    return entry


def pages(graph, document, scripts):
    out = []
    page_list = graph.items(graph.path(document, "Pages", "Pages"))
    for page in page_list:
        if not isinstance(page, Node):
            continue
        bounds = {}
        for panel in graph.items(page.get("VisualPanels")):
            rel = graph.r(panel.get("RelativeBounds")) \
                if isinstance(panel, Node) else None
            visual = graph.r(panel.get("Visual")) \
                if isinstance(panel, Node) else None
            if isinstance(rel, Node) and isinstance(visual, Node):
                bounds[visual.id] = {
                    k[0]: round(float(graph.text(rel.get(f)) or 0)
                                / LAYOUT_GRID * 100.0, 1)
                    for k, f in (("x", "x"), ("y", "y"), ("w", "width"),
                                 ("h", "height"))}
        visuals = []
        for visual in graph.items(page.get("Visuals")):
            if isinstance(visual, Node):
                visuals.append(visual_entry(graph, visual,
                                            bounds.get(visual.id), scripts))
        visuals.sort(key=lambda v: ((v["layout"] or {}).get("y", 999),
                                    (v["layout"] or {}).get("x", 999)))
        panels = {}
        for panel in graph.items(page.get("Panels")):
            if isinstance(panel, Node):
                panels[panel.type.name] = graph.text(
                    panel.get("Visible")) == "true"
        out.append({"title": expression(graph, page.get("TitleExpression")),
                    "visible": graph.text(page.get("Visible")) != "false",
                    "filterPanelVisible": panels.get("FilterPanel"),
                    "visuals": visuals})
    return out


def triggers(graph, document, scripts):
    out = []
    handlers = graph.path(document, "ScriptManager", "ScriptEventHandlers")
    for handler in graph.items(handlers):
        if not isinstance(handler, Node):
            continue
        prop = graph.name(graph.path(handler, "DataPropertyReference",
                                     "DataProperty"))
        script = script_name(graph, handler.get("ScriptReference"), scripts)
        out.append({"kind": handler.type.name, "property": prop,
                    "script": script})
    return out


def hygiene(archive):
    """Local paths and credential-like assignments in archive text.

    One finding per kind and example. The user folder name is replaced by
    <user> in the example, so the report does not repeat it."""
    user_path = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'<>&]+)"
                           r"[^\s\"'<>&]{0,60}", re.I)
    secret = re.compile(r"\b(password|passwd|pwd|secret|token|api_?key)"
                        r"\s*[=:]\s*['\"][^'\"]{4,}['\"]", re.I)
    grouped = {}
    for name in archive.names:
        if name.startswith("DataTables/") or name.endswith((".png", ".asice",
                                                           ".zip")):
            continue
        data = archive.read(name)
        if b"\x00" in data[:2048]:
            continue
        text = data.decode("utf-8", "replace")
        text = text.replace("&#xD;&#xA;", "\n").replace("&#xA;", "\n")
        for match in user_path.finditer(text):
            if match.group(1).lower() in ("public", "default"):
                continue
            example = match.group(0).replace(match.group(1), "<user>", 1)
            grouped.setdefault(("local path", example), []).append(name)
        for match in secret.finditer(text):
            grouped.setdefault(("credential-like",
                                match.group(1) + " = '...'"),
                               []).append(name)
    findings = []
    for (kind, example), entries in sorted(grouped.items()):
        findings.append({"entry": ", ".join(sorted(set(entries))),
                         "kind": kind, "text": example})
    return findings


def inventory(path):
    path = Path(path)
    archive = Archive(path)
    meta = archive.metadata()
    if "AnalysisDocument.xml" not in archive.names:
        raise ValueError("no AnalysisDocument.xml: not a Spotfire analysis")
    graph = Graph(archive.read("AnalysisDocument.xml"))
    document = graph.root
    manager = graph.r(document.get("DataManager"))
    scripts = read_scripts(archive)
    analysis_meta = {}
    if "AnalysisMetadata.json" in archive.names:
        try:
            analysis_meta = json.loads(
                archive.read("AnalysisMetadata.json").decode("utf-8-sig"))
        except ValueError:
            analysis_meta = {}
    keywords = []
    for prop in analysis_meta.get("Properties", []):
        if prop.get("Key") == "keywords":
            keywords = prop.get("Value") or []
    markings = []
    for marking in graph.items(graph.path(manager, "Markings")):
        if isinstance(marking, Node):
            markings.append({"name": graph.text(marking.get("Name")),
                             "color": color_of(graph, marking.get("Color"))})
    schemes = [graph.text(f.get("Name")) for f in
               graph.items(graph.path(manager, "Filterings"))
               if isinstance(f, Node)]
    relations = []
    for rel in graph.items(graph.path(manager, "Relations")):
        if isinstance(rel, Node):
            relations.append({
                "left": graph.text(rel.get("LeftTableName")),
                "right": graph.text(rel.get("RightTableName")),
                "expression": graph.text(rel.get("Expression"))})
    theme_json = archive.resource("CustomStyles.json") or b""
    page_list = pages(graph, document, scripts)
    active = graph.r(document.get("ActivePageReference"))
    inv = {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "document": {
            "savedBy": meta["savedBy"],
            "compatibility": meta["compatibility"],
            "description": analysis_meta.get("Description") or "",
            "keywords": keywords,
            "navigation": graph.text(graph.path(document, "Pages",
                                                "NavigationMode")),
            "activePage": expression(graph, active.get("TitleExpression"))
            if isinstance(active, Node) else None,
            "customTheme": graph.text(document.get("UseCustomStyles"))
            == "true",
        },
        "pages": page_list,
        "dataFunctions": data_functions(graph, manager),
        "scripts": sorted(scripts.values(),
                          key=lambda s: (s["name"] or "").lower()),
        "triggers": triggers(graph, document, scripts),
        "documentProperties": document_properties(graph, manager),
        "tables": data_tables(graph, manager),
        "markings": markings,
        "filteringSchemes": schemes,
        "relations": relations,
        "colors": {
            "markings": sorted({m["color"] for m in markings
                                if m["color"]}),
            "visuals": sorted({c for p in page_list for v in p["visuals"]
                               for c in v.get("colors", [])}),
            "textAreas": sorted({c for p in page_list for v in p["visuals"]
                                 for c in css_colors(v.get("html"))}),
            "theme": sorted(set(css_colors(
                theme_json.decode("utf-8-sig", "replace")))),
        },
        "archive": {
            "entries": len(archive.names),
            "documentVersions": [v for v, _p in meta["documents"]],
            "embeddedTables": sum(1 for n in archive.names
                                  if n.startswith("DataTables/")),
            "mods": sum(1 for n in archive.names if n.startswith("Mods/")),
            "bookmarks": sum(1 for n in archive.names
                             if n.startswith("Bookmarks/")),
        },
        "hygiene": hygiene(archive),
    }
    return inv


# --------------------------------------------------------------------------
# Text rendering (one section per object, keyed by name)
# --------------------------------------------------------------------------
def safe(name):
    return re.sub(r"[^\w.-]+", "_", name or "untitled").strip("_")[:60] \
        or "untitled"


def lines_kv(pairs):
    out = []
    for key, value in pairs:
        if value is None or value == [] or value == {}:
            continue
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        out.append("%s: %s" % (key, value))
    return "\n".join(out) + "\n"


def render_sections(inv):
    """Return {section name: text} for diffs and the text command."""
    sec = {}
    doc = inv["document"]
    sec["document"] = lines_kv([
        ("saved by", doc["savedBy"]), ("compatibility", doc["compatibility"]),
        ("description", doc["description"]), ("keywords", doc["keywords"]),
        ("navigation", doc["navigation"]), ("active page", doc["activePage"]),
        ("custom theme", doc["customTheme"]),
        ("pages", [p["title"] for p in inv["pages"]])])
    for index, page in enumerate(inv["pages"], 1):
        key = "pages/%02d_%s" % (index, safe(page["title"]))
        rows = [lines_kv([("title", page["title"]),
                          ("visible", page["visible"]),
                          ("filter panel visible",
                           page["filterPanelVisible"])])]
        for vi, vis in enumerate(page["visuals"], 1):
            layout = vis.get("layout") or {}
            rows.append("\n[visual %d] %s\n" % (vi, vis["title"]))
            rows.append(lines_kv([
                ("type", vis["type"]), ("show title", vis["showTitle"]),
                ("table", vis.get("table")), ("marking", vis.get("marking")),
                ("limit by markings", vis.get("limitByMarkings")),
                ("where clause", vis.get("whereClause")),
                ("layout %", "x %s, y %s, w %s, h %s" % (
                    layout.get("x"), layout.get("y"), layout.get("w"),
                    layout.get("h")) if layout else None),
                ("mod", vis.get("mod")),
                ("text area scripts", vis.get("javaScripts")),
                ("colors", vis.get("colors"))]))
            for axis in sorted(vis.get("axes", {})):
                rows.append("axis %s: %s\n" % (axis, vis["axes"][axis]))
            for control in vis.get("controls", []):
                rows.append("control %s\n" % ", ".join(
                    "%s %s" % (k, v) for k, v in control.items()))
            for layer in vis.get("layers", []):
                rows.append("mod layer %s: table %s, marking %s\n" % (
                    layer["title"], layer["table"], layer["marking"]))
                for axis in sorted(layer["axes"]):
                    rows.append("  layer axis %s: %s\n" % (
                        axis, layer["axes"][axis]))
            if vis.get("html") is not None:
                sec["text_areas/%02d_%s_%d.html" % (
                    index, safe(page["title"]), vi)] = vis["html"] + "\n"
        sec[key] = "".join(rows)
    for fn in inv["dataFunctions"]:
        base = "data_functions/%s/" % safe(fn["name"])
        sec[base + "definition"] = lines_kv([
            ("name", fn["name"]), ("display name", fn["displayName"]),
            ("engine", fn["engine"]), ("description", fn["description"]),
            ("update behavior", fn["updateBehavior"]),
            ("trust stamp", fn["trustStamp"] or "missing")]) + "".join(
            "input %s (%s%s): %s\n" % (i["name"], i["type"],
                                       ", optional" if i["optional"] else "",
                                       i.get("binding"))
            for i in fn["inputs"]) + "".join(
            "output %s (%s): %s\n" % (o["name"], o["type"], o.get("target"))
            for o in fn["outputs"])
        sec[base + "script"] = fn["script"] + "\n"
    for script in inv["scripts"]:
        ext = "js" if script["language"].lower().startswith("java") \
            else "py"
        base = "scripts/%s" % safe(script["name"])
        sec[base + ".definition"] = lines_kv([
            ("name", script["name"]), ("language", script["language"]),
            ("transaction", script["transaction"]),
            ("description", script["description"]),
            ("parameters", script["parameters"]),
            ("trust stamp", script["trustStamp"] or "missing")])
        sec[base + "." + ext] = script["code"] + "\n"
    if inv["triggers"]:
        sec["triggers"] = "".join("%s: property %s -> script %s\n" % (
            t["kind"], t["property"], t["script"]) for t in inv["triggers"])
    sec["document_properties"] = "".join(
        "%s (%s) = %r%s\n" % (p["name"], p["type"], p["value"],
                              ("  # " + p["description"])
                              if p["description"] else "")
        for p in inv["documentProperties"])
    for table in inv["tables"]:
        rows = [lines_kv([("name", table["name"]),
                          ("sources", table["sources"])])]
        for col in table["columns"]:
            rows.append("column %s (%s, %s)%s\n" % (
                col["name"], col["type"], col["kind"],
                (": " + col["expression"]) if col["expression"] else ""))
        sec["data_tables/%s" % safe(table["name"])] = "".join(rows)
    sec["markings_and_filtering"] = lines_kv([
        ("markings", inv["markings"]),
        ("filtering schemes", inv["filteringSchemes"]),
        ("relations", inv["relations"])])
    sec["colors"] = lines_kv(sorted(inv["colors"].items()))
    return sec


def render_text(inv):
    out = []
    sections = render_sections(inv)
    for name in sorted(sections):
        body = sections[name]
        out.append("=== %s ===\n" % name)
        out.append(body if body.endswith("\n") else body + "\n")
    return "".join(out)


def render_markdown(inv):
    doc = inv["document"]
    visuals = sum(len(p["visuals"]) for p in inv["pages"])
    out = ["# DXP inventory: %s" % inv["file"], "",
           "- Saved by Spotfire build %s, document versions %s" % (
               doc["savedBy"], doc["compatibility"]),
           "- %d pages, %d visuals, %d data functions, %d scripts, "
           "%d property triggers, %d document properties, %d data tables"
           % (len(inv["pages"]), visuals, len(inv["dataFunctions"]),
              len(inv["scripts"]), len(inv["triggers"]),
              len(inv["documentProperties"]), len(inv["tables"])),
           "- Description: %s" % (doc["description"] or "(none)"), "",
           "## Pages", "",
           "| page | visual | type | table | marking | layout (x, y, w, h %) |",
           "|---|---|---|---|---|---|"]
    for page in inv["pages"]:
        for vis in page["visuals"] or [{"title": "(no visuals)",
                                        "type": "", "layout": None}]:
            lay = vis.get("layout")
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                page["title"], vis["title"],
                (vis.get("type") or "").replace("Spotfire.", ""),
                vis.get("table") or "", vis.get("marking") or "",
                "%s, %s, %s, %s" % (lay["x"], lay["y"], lay["w"], lay["h"])
                if lay else ""))
    out += ["", "## Data functions", ""]
    for fn in inv["dataFunctions"]:
        out.append("- **%s** (%s, %s update, trust stamp %s): inputs %s; "
                   "outputs %s" % (
                       fn["name"], fn["engine"], fn["updateBehavior"],
                       "present" if fn["trustStamp"] else "missing",
                       ", ".join(i["name"] for i in fn["inputs"]) or "none",
                       ", ".join("%s -> %s" % (o["name"], o.get("target"))
                                 for o in fn["outputs"]) or "none"))
    out += ["", "## Scripts", ""]
    for script in inv["scripts"]:
        out.append("- **%s** (%s, %d lines, trust stamp %s)" % (
            script["name"], script["language"],
            len(script["code"].splitlines()),
            "present" if script["trustStamp"] else "missing"))
    for trig in inv["triggers"]:
        out.append("- trigger: property `%s` runs `%s`" % (trig["property"],
                                                           trig["script"]))
    out += ["", "## Data tables", ""]
    for table in inv["tables"]:
        calc = sum(1 for c in table["columns"]
                   if (c["kind"] or "").startswith("Calculated"))
        out.append("- **%s**: %d columns (%d calculated); %s" % (
            table["name"], len(table["columns"]), calc,
            ", ".join(s.get("source") or s["producer"]
                      for s in table["sources"]) or "no source"))
    out += ["", "## Document properties", ""]
    out += ["- `%s` (%s) = %r" % (p["name"], p["type"], p["value"])
            for p in inv["documentProperties"]] or ["- none"]
    out += ["", "## Colors", ""]
    for key, values in sorted(inv["colors"].items()):
        out.append("- %s: %s" % (key, ", ".join(values) or "none"))
    out += ["", "## Markings and filtering", "",
            "- markings: %s" % ", ".join("%s %s" % (m["name"], m["color"])
                                        for m in inv["markings"]),
            "- filtering schemes: %s" % ", ".join(inv["filteringSchemes"]),
            ""]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------
def diff_sections(old, new, stat=False):
    out = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        lines = list(difflib.unified_diff(
            (a or "").splitlines(keepends=True),
            (b or "").splitlines(keepends=True),
            "a/" + name if a is not None else "/dev/null",
            "b/" + name if b is not None else "/dev/null"))
        if stat:
            plus = sum(1 for x in lines if x.startswith("+")
                       and not x.startswith("+++"))
            minus = sum(1 for x in lines if x.startswith("-")
                        and not x.startswith("---"))
            out.append("%s | +%d -%d\n" % (name, plus, minus))
        else:
            out.extend(x if x.endswith("\n") else x + "\n" for x in lines)
    return "".join(out)


def change_summary(old, new):
    def keys(inv):
        return {
            "pages": {p["title"] for p in inv["pages"]},
            "visuals": {"%s / %s" % (p["title"], v["title"])
                        for p in inv["pages"] for v in p["visuals"]},
            "data functions": {f["name"] for f in inv["dataFunctions"]},
            "scripts": {s["name"] for s in inv["scripts"]},
            "data tables": {t["name"] for t in inv["tables"]},
            "document properties": {p["name"]
                                    for p in inv["documentProperties"]},
        }
    a, b = keys(old), keys(new)
    out = []
    for kind in a:
        added, removed = sorted(b[kind] - a[kind]), sorted(a[kind] - b[kind])
        for verb, names in (("added", added), ("removed", removed)):
            if names:
                shown = "; ".join(names[:12])
                if len(names) > 12:
                    shown += "; and %d more" % (len(names) - 12)
                out.append("%s %s: %s" % (verb, kind, shown))
    return out


# --------------------------------------------------------------------------
# Design-rule checks (references/design-rule-checks.md)
# --------------------------------------------------------------------------
NON_DATA_TYPES = {"Spotfire.HtmlTextArea", "Spotfire.Mod"}
DEFAULT_NAMES = re.compile(r"^(untitled|new script|script\d*|data function"
                           r"( \d+)?|text area( \d+)?|page( \d+)?)$", re.I)


def check(inv):
    found = []

    def add(level, rule, where, message):
        found.append({"level": level, "rule": rule, "where": where,
                      "message": message})

    for page in inv["pages"]:
        if not page["visuals"]:
            add("FAIL", "empty-page", page["title"], "page has no visuals")
        if DEFAULT_NAMES.match(page["title"] or ""):
            add("WARN", "default-name", page["title"],
                "page keeps a default title")
        by_table = {}
        for vis in page["visuals"]:
            where = "%s / %s" % (page["title"], vis["title"])
            vtype = vis.get("type") or ""
            if vtype == "Spotfire.KpiChart":
                add("WARN", "no-kpi-chart", where,
                    "Spotfire KPI chart: build KPI bands as HTML text areas")
            if DEFAULT_NAMES.match(vis["title"] or ""):
                add("WARN", "default-name", where,
                    "visual keeps a default title")
            if vtype in NON_DATA_TYPES or not vis.get("table"):
                continue
            layer_marks = [x.get("marking") for x in vis.get("layers", [])]
            if not vis.get("marking") and not any(layer_marks) and                     not vis.get("limitByMarkings"):
                add("WARN", "visual-without-marking", where,
                    "visual cannot be marked, so marking elsewhere cannot "
                    "start from it")
            by_table.setdefault(vis["table"], set()).add(vis.get("marking"))
        for table, marks in by_table.items():
            marks.discard(None)
            if len(marks) > 1:
                add("WARN", "mixed-markings", "%s / table %s" % (
                    page["title"], table),
                    "visuals on one table use different markings: %s"
                    % ", ".join(sorted(marks)))
    for fn in inv["dataFunctions"]:
        if DEFAULT_NAMES.match(fn["name"] or ""):
            add("WARN", "default-name", fn["name"],
                "data function keeps a default name")
        if not fn["trustStamp"]:
            add("INFO", "no-trust-stamp", fn["name"],
                "data function has no trust stamp: Spotfire asks every "
                "user to trust it")
        if not fn["description"]:
            add("WARN", "missing-description", fn["name"],
                "data function has no description")
    for script in inv["scripts"]:
        if DEFAULT_NAMES.match(script["name"] or ""):
            add("WARN", "default-name", script["name"],
                "script keeps a default name")
        if not script["trustStamp"]:
            add("INFO", "no-trust-stamp", script["name"],
                "script has no trust stamp")
    if not inv["document"]["description"]:
        add("WARN", "missing-description", inv["file"],
            "analysis has no description (File > Document Properties)")
    for item in inv["hygiene"]:
        add("FAIL", "hygiene", item["entry"], item["kind"] + ": "
            + item["text"])
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    return sorted(found, key=lambda f: (order[f["level"]], f["rule"],
                                        f["where"] or ""))


# --------------------------------------------------------------------------
# Library audit
# --------------------------------------------------------------------------
VERSION_PATTERNS = [
    re.compile(r"^(?P<base>.+?)[ _.-]+v(?:ersion)?[ _.-]?"
               r"(?P<num>\d+(?:\.\d+)*)$", re.I),
    re.compile(r"^(?P<base>.+?)\s*\((?P<num>\d+)\)$"),
    re.compile(r"^(?P<base>.+?)[ _.-]+(?P<num>\d{8}(?:[ _.-]?\d{4,6})?)$"),
]


def split_version(stem):
    for pattern in VERSION_PATTERNS:
        match = pattern.match(stem)
        if match:
            parts = [int(p) for p in re.split(r"\D+", match.group("num"))
                     if p]
            return match.group("base").strip(), tuple(parts)
    return stem.strip(), ()


def cmd_library(args):
    pattern = "**/*.dxp" if args.recursive else "*.dxp"
    paths = sorted(p for p in Path(args.folder).glob(pattern) if p.is_file())
    if not paths:
        print("no .dxp files in %s" % args.folder, file=sys.stderr)
        return EXIT_USAGE
    out = Path(args.out)
    for sub in ("text", "diffs", "checks"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    groups = {}
    for path in paths:
        base, version = split_version(path.stem)
        key = re.sub(r"[ _.-]+", " ", base).strip().lower()
        groups.setdefault(key, []).append((path, base, version))
    report = ["# DXP library audit", "",
              "- Folder: `%s`" % Path(args.folder).name,
              "- Files: %d, analyses: %d" % (len(paths), len(groups)),
              "- Generated: %s" % dt.datetime.now().strftime(
                  "%Y-%m-%d %H:%M"), ""]
    totals = {"FAIL": 0, "WARN": 0, "INFO": 0}
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda m: (
            m[2], m[0].stat().st_mtime))
        report += ["## %s" % members[0][1], "",
                   "| file | modified | pages | visuals | data functions | "
                   "scripts | tables | FAIL | WARN |",
                   "|---|---|---|---|---|---|---|---|---|"]
        previous = None
        changes = []
        for path, _base, _ver in members:
            try:
                inv = inventory(path)
            except (ValueError, zipfile.BadZipFile, ET.ParseError,
                    OSError) as exc:
                report.append("| %s | unreadable: %s | | | | | | | |"
                              % (path.name, exc))
                continue
            findings = check(inv)
            counts = {lvl: sum(1 for f in findings if f["level"] == lvl)
                      for lvl in totals}
            for lvl in totals:
                totals[lvl] += counts[lvl]
            (out / "text" / (path.stem + ".txt")).write_text(
                render_text(inv), encoding="utf-8", newline="\n")
            (out / "checks" / (path.stem + ".md")).write_text(
                "# Checks: %s\n\n" % path.name + "".join(
                    "- %s %s %s: %s\n" % (f["level"], f["rule"],
                                          f["where"], f["message"])
                    for f in findings) + ("" if findings else "- none\n"),
                encoding="utf-8", newline="\n")
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime)
            report.append("| %s | %s | %d | %d | %d | %d | %d | %d | %d |" % (
                path.name, modified.strftime("%Y-%m-%d %H:%M"),
                len(inv["pages"]),
                sum(len(p["visuals"]) for p in inv["pages"]),
                len(inv["dataFunctions"]), len(inv["scripts"]),
                len(inv["tables"]), counts["FAIL"], counts["WARN"]))
            if previous is not None:
                old_path, old_inv = previous
                sections_old = render_sections(old_inv)
                sections_new = render_sections(inv)
                diff = diff_sections(sections_old, sections_new)
                name = "%s__%s.diff" % (old_path.stem, path.stem)
                (out / "diffs" / name).write_text(diff, encoding="utf-8",
                                                  newline="\n")
                changes.append((old_path.name, path.name, name,
                                diff_sections(sections_old, sections_new,
                                              stat=True),
                                change_summary(old_inv, inv)))
            previous = (path, inv)
        report.append("")
        for old_name, new_name, name, stat, summary in changes:
            report.append("**%s -> %s** (`diffs/%s`)" % (old_name, new_name,
                                                         name))
            report.append("")
            if stat:
                report += ["```"] + stat.rstrip("\n").splitlines() + ["```"]
                report += ["- " + s for s in summary]
            else:
                report.append("No differences.")
            report.append("")
    report += ["## Totals", "",
               "FAIL %d, WARN %d, INFO %d. Per-file findings are in "
               "`checks/`." % (totals["FAIL"], totals["WARN"],
                               totals["INFO"]), ""]
    (out / "LIBRARY.md").write_text("\n".join(report), encoding="utf-8",
                                    newline="\n")
    print("audited %d DXP file(s) in %d analysis group(s); report: %s"
          % (len(paths), len(groups), out / "LIBRARY.md"))
    return EXIT_DIFF if totals["FAIL"] else EXIT_OK


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def write_or_print(text, out):
    if out:
        Path(out).write_text(text, encoding="utf-8", newline="\n")
        print("wrote %s" % out)
    else:
        sys.stdout.write(text)


def cmd_inventory(args):
    inv = inventory(args.dxp)
    if args.json:
        Path(args.json).write_text(json.dumps(inv, indent=1,
                                              ensure_ascii=False),
                                   encoding="utf-8")
        print("wrote %s" % args.json)
    if args.md:
        write_or_print(render_markdown(inv), args.md)
    if not args.json and not args.md:
        sys.stdout.write(render_markdown(inv))
    return EXIT_OK


def cmd_text(args):
    write_or_print(render_text(inventory(args.dxp)), args.out)
    return EXIT_OK


def cmd_compare(args):
    old, new = inventory(args.old), inventory(args.new)
    diff = diff_sections(render_sections(old), render_sections(new),
                         stat=args.stat)
    summary = change_summary(old, new)
    text = diff
    if args.stat and summary:
        text += "".join("# %s\n" % s for s in summary)
    write_or_print(text, args.out)
    return EXIT_DIFF if diff else EXIT_OK


def cmd_check(args):
    findings = check(inventory(args.dxp))
    if args.json:
        Path(args.json).write_text(json.dumps(findings, indent=1),
                                   encoding="utf-8")
    for f in findings:
        print("%-4s %-22s %s: %s" % (f["level"], f["rule"], f["where"],
                                     f["message"]))
    fails = sum(1 for f in findings if f["level"] == "FAIL")
    print("%d finding(s), %d FAIL" % (len(findings), fails))
    return EXIT_DIFF if fails else EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dxp_inventory",
        description="Read, compare and audit Spotfire DXP files without "
                    "Spotfire.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory", help="list what a DXP contains")
    p.add_argument("dxp")
    p.add_argument("--json")
    p.add_argument("--md")
    p.set_defaults(run=cmd_inventory)
    p = sub.add_parser("text", help="one readable text document")
    p.add_argument("dxp")
    p.add_argument("-o", "--out")
    p.set_defaults(run=cmd_text)
    p = sub.add_parser("compare", help="diff two DXPs")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--stat", action="store_true")
    p.add_argument("-o", "--out")
    p.set_defaults(run=cmd_compare)
    p = sub.add_parser("check", help="design-rule checks for one DXP")
    p.add_argument("dxp")
    p.add_argument("--json")
    p.set_defaults(run=cmd_check)
    p = sub.add_parser("library", help="audit every DXP in a folder")
    p.add_argument("folder")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--recursive", action="store_true")
    p.set_defaults(run=cmd_library)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        return args.run(args)
    except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError,
            KeyError) as exc:
        print("dxp_inventory: %s" % exc, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
