# Object-graph reader used by scripts/verify_dxp.py (vendored unchanged from the dxp-toolkit project).
"""
sfgraph - reader for Spotfire's AnalysisDocument.xml object-graph serialization.

The document is a single-line XML stream written by Spotfire's persistence layer:

    <Object Id="1"><Type><TypeObject Id="2" FullTypeName="..."/></Type>
      <Fields><Field Name="X"><String Id="6" Value="..."/></Field>...</Fields>
    </Object>

Every Object / Struct / Array / String / TypeObject gets a document-unique Id.
A value that was already written is emitted again as <ObjectRef Value="Id"/>;
<ObjectRef Value="0"/> is null. Types are declared once (TypeObject) and then
referenced (TypeRef). Primitive arrays are written inline as comma-separated text.

This module only READS. Edits are applied by splicing new attribute values into
the original text at the exact byte span of a <String> element (see dxp.py), so
everything that is not edited stays byte-identical.
"""
import re
from lxml import etree

NS = "{http://www.spotfire.com/schemas/Document1.0.xsd}"

PRIMS = {"Bool", "Int", "Long", "Short", "Byte", "Float", "Double", "DateTime",
         "Char", "SByte", "UShort", "UInt", "ULong", "Decimal", "TimeSpan", "Guid"}


class TypeInfo:
    __slots__ = ("id", "full", "assembly", "base", "generic_args", "version")

    def __init__(self, id, full, assembly):
        self.id, self.full, self.assembly = id, full, assembly
        self.base, self.generic_args, self.version = None, [], None

    @property
    def short(self):
        return short_type(self.full)

    def is_a(self, name):
        """True if this type or any base type's full name ends with `name`."""
        t = self
        while t is not None:
            if t.full == name or t.full.endswith("." + name) or t.full.split("`")[0].endswith("." + name):
                return True
            t = t.base
        return False

    def __repr__(self):
        return "<Type %s>" % self.short


def short_type(full):
    """Spotfire.Dxp.Application.Visuals.LineChart -> LineChart; generics simplified."""
    if full is None:
        return "?"
    s = re.sub(r", [A-Za-z0-9_.]+, Version=[^\]]*", "", full)  # strip assembly qualifiers
    s = re.sub(r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)+([A-Za-z_][A-Za-z0-9_+]*)", r"\1", s)
    s = s.replace("[[", "<").replace("]]", ">").replace("],[", ", ")
    s = re.sub(r"`\d+", "", s)
    return s


class Node:
    """An Object or Struct: typed, with ordered fields."""
    __slots__ = ("kind", "id", "type", "fields", "parent", "pfield")

    def __init__(self, kind, id, type):
        self.kind, self.id, self.type = kind, id, type
        self.fields = []          # list of (name, value)
        self.parent = None        # owning Node/Arr (first/defining occurrence)
        self.pfield = None        # field name or array index in parent

    def get(self, name, default=None):
        for n, v in self.fields:
            if n == name:
                return v
        return default

    def getall(self, name):
        return [v for n, v in self.fields if n == name]

    def __repr__(self):
        return "<%s #%s %s>" % (self.kind, self.id, self.type.short if self.type else "?")


class Arr:
    __slots__ = ("id", "type", "items", "inline", "length", "parent", "pfield")

    def __init__(self, id, type, length):
        self.id, self.type, self.length = id, type, length
        self.items = []
        self.inline = None        # raw text for primitive arrays
        self.parent = None
        self.pfield = None

    def __repr__(self):
        return "<Array #%s %s[%s]>" % (self.id, self.type.short if self.type else "?", self.length)


class MdArr(Arr):
    """A rectangular .NET array (e.g. double[3,3] in map transforms).

    Written as <MultiDimensionalArray> with <Dimensions> and one <IndexedElement Index="i,j">
    per cell. Items are kept in document order; index[k] holds the tuple for items[k].
    """
    __slots__ = ("dims", "index")

    def __init__(self, id, type, dims):
        length = 1
        for _, n in dims:
            length *= n
        Arr.__init__(self, id, type, length)
        self.dims = dims          # list of (lower_bound, length)
        self.index = []

    def __repr__(self):
        return "<MdArray #%s %s[%s]>" % (self.id, self.type.short if self.type else "?",
                                         ",".join(str(n) for _, n in self.dims))


class Str:
    __slots__ = ("id", "value", "interned", "parent", "pfield", "refcount")

    def __init__(self, id, value, interned):
        self.id, self.value, self.interned = id, value, interned
        self.parent = None
        self.pfield = None
        self.refcount = 0         # number of ObjectRef pointing here (besides the definition)

    def __repr__(self):
        v = self.value if len(self.value) < 40 else self.value[:37] + "..."
        return "<Str #%s %r>" % (self.id, v)


class Prim:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind, self.value = kind, value

    def __repr__(self):
        return "%s(%s)" % (self.kind, self.value)


class EnumVal:
    __slots__ = ("value", "type")

    def __init__(self, value, type):
        self.value, self.type = value, type

    def __repr__(self):
        return "%s.%s" % (self.type.short if self.type else "Enum", self.value)


class Ref:
    __slots__ = ("id", "graph")

    def __init__(self, id, graph):
        self.id, self.graph = id, graph

    @property
    def target(self):
        return self.graph.by_id.get(self.id)

    def __repr__(self):
        return "<Ref #%s>" % self.id


class NullVal:
    __slots__ = ()

    def __repr__(self):
        return "null"


NULL = NullVal()


class Graph:
    def __init__(self, xml_bytes):
        self.by_id = {}
        self.types = {}
        self.refs_to = {}         # id -> list of (holder, field) that ObjectRef it
        root = etree.fromstring(xml_bytes, parser=etree.XMLParser(huge_tree=True, remove_blank_text=False))
        self.root_el = root
        children = [c for c in root if isinstance(c.tag, str)]
        self.root = self._value(children[0], None, None)
        # second pass: count references to strings
        for id_, lst in self.refs_to.items():
            t = self.by_id.get(id_)
            if isinstance(t, Str):
                t.refcount = len(lst)

    # -- parsing ---------------------------------------------------------
    def _type(self, type_el):
        """type_el is the <Type> wrapper or a TypeObject/TypeRef element."""
        if type_el is None:
            return None
        if type_el.tag == NS + "Type" or type_el.tag == NS + "GenericArgument" or type_el.tag == NS + "BaseType":
            kids = [c for c in type_el if isinstance(c.tag, str)]
            return self._type(kids[0]) if kids else None
        if type_el.tag == NS + "TypeRef":
            return self.types[int(type_el.get("Value"))]
        if type_el.tag == NS + "TypeObject":
            tid = int(type_el.get("Id"))
            ti = TypeInfo(tid, type_el.get("FullTypeName"), type_el.get("AssemblyName"))
            self.types[tid] = ti
            self.by_id[tid] = ti
            nsti = type_el.find(NS + "NonSystemTypeInfo")
            if nsti is not None:
                pv = nsti.find(NS + "PersistenceVersion")
                if pv is not None:
                    ti.version = (pv.get("Major"), pv.get("Minor"))
                b = nsti.find(NS + "BaseType")
                if b is not None:
                    ti.base = self._type(b)
            gti = type_el.find(NS + "GenericTypeInfo")
            if gti is not None:
                ga = gti.find(NS + "GenericArguments")
                if ga is not None:
                    ti.generic_args = [self._type(g) for g in ga if isinstance(g.tag, str)]
            return ti
        raise ValueError("unexpected type element %s" % type_el.tag)

    def _value(self, el, parent, pfield):
        tag = el.tag[len(NS):] if el.tag.startswith(NS) else el.tag
        if tag in ("Object", "Struct"):
            n = Node(tag, int(el.get("Id")), self._type(el.find(NS + "Type")))
            self.by_id[n.id] = n
            n.parent, n.pfield = parent, pfield
            fs = el.find(NS + "Fields")
            if fs is not None:
                for f in fs:
                    if not isinstance(f.tag, str):
                        continue
                    name = f.get("Name")
                    kids = [c for c in f if isinstance(c.tag, str)]
                    v = self._value(kids[0], n, name) if kids else NULL
                    n.fields.append((name, v))
            return n
        if tag == "Array":
            a = Arr(int(el.get("Id")), self._type(el.find(NS + "Type")), int(el.get("Length")))
            self.by_id[a.id] = a
            a.parent, a.pfield = parent, pfield
            es = el.find(NS + "Elements")
            if es is not None:
                kids = [c for c in es if isinstance(c.tag, str)]
                if kids:
                    for i, c in enumerate(kids):
                        a.items.append(self._value(c, a, i))
                elif es.text:
                    a.inline = es.text
            return a
        if tag == "MultiDimensionalArray":
            ds = el.find(NS + "Dimensions")
            dims = [(int(d.get("LowerBound", "0")), int(d.get("Length"))) for d in ds] if ds is not None else []
            a = MdArr(int(el.get("Id")), self._type(el.find(NS + "Type")), dims)
            self.by_id[a.id] = a
            a.parent, a.pfield = parent, pfield
            es = el.find(NS + "Elements")
            if es is not None:
                for ie in es:
                    if not isinstance(ie.tag, str):
                        continue
                    kids = [c for c in ie if isinstance(c.tag, str)]
                    k = len(a.items)
                    a.items.append(self._value(kids[0], a, k) if kids else NULL)
                    a.index.append(tuple(int(x) for x in ie.get("Index", "").split(",") if x != ""))
            return a
        if tag == "String":
            # String.Empty is written once as IsEmpty="true" and then shared by reference
            val = "" if el.get("IsEmpty") == "true" else el.get("Value")
            s = Str(int(el.get("Id")), val, el.get("IsInterned") == "true")
            self.by_id[s.id] = s
            s.parent, s.pfield = parent, pfield
            return s
        if tag == "ObjectRef":
            rid = int(el.get("Value"))
            if rid == 0:
                return NULL
            self.refs_to.setdefault(rid, []).append((parent, pfield))
            return Ref(rid, self)
        if tag == "Enum":
            return EnumVal(el.get("Value"), self._type(el.find(NS + "Type")))
        if tag == "NullableNull":
            return NULL
        if tag in PRIMS:
            return Prim(tag, el.get("Value"))
        if tag == "TypeObject" or tag == "TypeRef":
            return self._type(el)
        raise ValueError("unexpected element <%s>" % tag)

    # -- helpers ---------------------------------------------------------
    def resolve(self, v):
        """Follow an ObjectRef to its target (one hop is all that's ever needed)."""
        while isinstance(v, Ref):
            v = v.target
        return v

    def walk(self, start=None):
        """Yield every Node/Arr/Str reachable from start through DEFINING edges (no refs)."""
        stack = [start or self.root]
        while stack:
            v = stack.pop()
            yield v
            if isinstance(v, Node):
                for _, c in reversed(v.fields):
                    if isinstance(c, (Node, Arr, Str)):
                        stack.append(c)
            elif isinstance(v, Arr):
                for c in reversed(v.items):
                    if isinstance(c, (Node, Arr, Str)):
                        stack.append(c)

    def nodes_of(self, type_suffix, exact=False):
        out = []
        for v in self.by_id.values():
            if isinstance(v, Node) and v.type is not None:
                if exact:
                    if v.type.full == type_suffix or v.type.full.endswith("." + type_suffix):
                        out.append(v)
                elif v.type.is_a(type_suffix):
                    out.append(v)
        return sorted(out, key=lambda n: n.id)

    def path(self, v):
        """Human-readable defining path from the root to v."""
        parts = []
        cur = v
        while cur is not None and getattr(cur, "parent", None) is not None:
            pf = cur.pfield
            parts.append("[%d]" % pf if isinstance(pf, int) else "." + str(pf))
            cur = cur.parent
        return "Document" + "".join(reversed(parts))

    def owner(self, v, type_suffix):
        """Nearest defining ancestor whose type is_a(type_suffix)."""
        cur = getattr(v, "parent", None)
        while cur is not None:
            if isinstance(cur, Node) and cur.type is not None and cur.type.is_a(type_suffix):
                return cur
            cur = getattr(cur, "parent", None)
        return None

    def sval(self, v):
        """String value of a field value (resolving refs); None if not a string."""
        v = self.resolve(v)
        return v.value if isinstance(v, Str) else None

    def field_path(self, node, *names):
        """node.names[0].names[1]... resolving refs; returns final value or None."""
        cur = node
        for nm in names:
            cur = self.resolve(cur)
            if isinstance(cur, Node):
                cur = cur.get(nm)
            elif isinstance(cur, Arr) and isinstance(nm, int):
                cur = cur.items[nm] if nm < len(cur.items) else None
            else:
                return None
            if cur is None:
                return None
        return self.resolve(cur)

    def list_items(self, v):
        """Unwrap Spotfire collection wrappers to a python list of resolved items."""
        v = self.resolve(v)
        if isinstance(v, Arr):
            return [self.resolve(x) for x in v.items]
        if isinstance(v, Node):
            for nm in ("Items", "Nodes", "_items", "items", "Values", "List"):
                inner = v.get(nm)
                if inner is not None:
                    inner = self.resolve(inner)
                    if isinstance(inner, Arr):
                        size = self.resolve(v.get("_size"))
                        items = [self.resolve(x) for x in inner.items]
                        if isinstance(size, Prim):
                            items = items[: int(size.value)]
                        return items
                    if isinstance(inner, Node):
                        return self.list_items(inner)
        return []


# -- XML attribute escaping that matches Spotfire's (.NET XmlWriter) output -----
def xml_attr_escape(s):
    """Escape exactly as Spotfire writes attribute values.

    Observed in real documents: & < > " are entity-escaped, CR and LF are written
    as &#xD; &#xA;, apostrophes are left alone. TAB must be &#x9; (a raw tab in an
    attribute would be normalized to a space by every XML reader).
    """
    out = []
    for ch in s:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif ch == "\r":
            out.append("&#xD;")
        elif ch == "\n":
            out.append("&#xA;")
        elif ch == "\t":
            out.append("&#x9;")
        else:
            o = ord(ch)
            if o < 0x20:
                raise ValueError("control character U+%04X is not allowed in XML 1.0" % o)
            out.append(ch)
    return "".join(out)


_ENT = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def xml_attr_unescape(s):
    def rep(m):
        e = m.group(1)
        if e.startswith("#x") or e.startswith("#X"):
            return chr(int(e[2:], 16))
        if e.startswith("#"):
            return chr(int(e[1:]))
        return _ENT[e]
    return re.sub(r"&(#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);", rep, s)


STRING_EL_RE = re.compile(r'<String Id="(\d+)"( IsInterned="true")? Value="([^"]*)" />')
EMPTY_STRING_EL_RE = re.compile(r'<String Id="(\d+)" IsEmpty="true" />')


def string_spans(text):
    """Map String Id -> (start, end, raw_value_start, raw_value_end) in the raw XML text.

    The IsEmpty singleton is deliberately absent: it is never editable in place.
    """
    spans = {}
    for m in STRING_EL_RE.finditer(text):
        spans[int(m.group(1))] = (m.start(), m.end(), m.start(3), m.end(3))
    return spans


# -- outline rendering ---------------------------------------------------------
def guid_from_struct(g, n):
    """System.Guid is serialized as a Struct with fields _a.._k."""
    try:
        f = {k: g.resolve(v) for k, v in n.fields}
        a = int(f["_a"].value) & 0xFFFFFFFF
        b = int(f["_b"].value) & 0xFFFF
        c = int(f["_c"].value) & 0xFFFF
        rest = [int(f[k].value) & 0xFF for k in ("_d", "_e", "_f", "_g", "_h", "_i", "_j", "_k")]
        return "%08x-%04x-%04x-%02x%02x-%s" % (a, b, c, rest[0], rest[1], "".join("%02x" % x for x in rest[2:]))
    except Exception:
        return None


def color_from_struct(g, n):
    f = {k: g.resolve(v) for k, v in n.fields}
    name = f.get("name")
    val = f.get("value")
    if isinstance(name, Str) and name.value:
        return "Color(%s)" % name.value
    if isinstance(val, Prim):
        return "Color(#%08X)" % (int(val.value) & 0xFFFFFFFF)
    return "Color(?)"


def label_of(g, n):
    """Best human label for a Node: Title / Name / DisplayName field if present."""
    if not isinstance(n, Node):
        return None
    for nm in ("Title", "Name", "DisplayName", "name", "ExternalName", "PropertyName", "Key"):
        v = n.get(nm)
        if v is not None:
            s = g.sval(v)
            if s:
                return s
    return None


def render_outline(g, max_str=200):
    """Readable indented dump of the whole object graph (defining edges only)."""
    out = []
    w = out.append

    def short_val(v, depth):
        if isinstance(v, Str):
            s = v.value
            extra = ""
            if len(s) > max_str:
                extra = " ...(+%d chars)" % (len(s) - max_str)
                s = s[:max_str]
            flags = []
            if v.interned:
                flags.append("interned")
            if v.refcount:
                flags.append("shared x%d" % v.refcount)
            return '%s%s  [Str #%d%s]' % (_q(s), extra, v.id, (", " + ", ".join(flags)) if flags else "")
        if isinstance(v, Ref):
            t = v.target
            if isinstance(t, Str):
                s = t.value if len(t.value) <= 60 else t.value[:57] + "..."
                return "-> Str #%d %s" % (t.id, _q(s))
            lab = label_of(g, t) if isinstance(t, Node) else None
            tt = t.type.short if getattr(t, "type", None) is not None else type(t).__name__
            return "-> #%d %s%s" % (v.id, tt, (' "%s"' % lab) if lab else "")
        if isinstance(v, Prim):
            return "%s" % v.value if v.kind != "DateTime" else v.value
        if isinstance(v, EnumVal):
            return "%s.%s" % (v.type.short if v.type else "Enum", v.value)
        if v is NULL:
            return "null"
        if isinstance(v, TypeInfo):
            return "typeof(%s)" % v.short
        return None

    def rec(v, depth, label):
        ind = "  " * depth
        sv = short_val(v, depth)
        if sv is not None:
            w("%s%s: %s" % (ind, label, sv))
            return
        if isinstance(v, Node):
            tfull = v.type.full if v.type else ""
            if v.kind == "Struct" and tfull == "System.Guid":
                w("%s%s: Guid(%s)" % (ind, label, guid_from_struct(g, v)))
                return
            if v.kind == "Struct" and tfull.startswith("System.Drawing.Color"):
                w("%s%s: %s" % (ind, label, color_from_struct(g, v)))
                return
            lab = label_of(g, v)
            w("%s%s: #%d %s%s" % (ind, label, v.id, v.type.short if v.type else "?", (' "%s"' % lab) if lab else ""))
            for name, c in v.fields:
                if name == "DocumentNodeId":
                    continue
                rec(c, depth + 1, name)
            return
        if isinstance(v, MdArr):
            shape = ",".join(str(n) for _, n in v.dims)
            cells = []
            for idx, c in zip(v.index, v.items):
                cv = short_val(c, depth)
                cells.append("%s=%s" % (",".join(str(i) for i in idx), cv if cv is not None else repr(c)))
            txt = "; ".join(cells)
            if len(txt) > 160:
                txt = txt[:157] + "..."
            w("%s%s: #%d %s[%s] = {%s}" % (ind, label, v.id, v.type.short if v.type else "?", shape, txt))
            return
        if isinstance(v, Arr):
            if v.inline is not None:
                txt = v.inline if len(v.inline) <= 120 else v.inline[:117] + "..."
                w("%s%s: #%d %s[%d] = {%s}" % (ind, label, v.id, v.type.short if v.type else "?", v.length, txt))
                return
            if not v.items:
                w("%s%s: #%d %s[%d] = []" % (ind, label, v.id, v.type.short if v.type else "?", v.length))
                return
            w("%s%s: #%d %s[%d]" % (ind, label, v.id, v.type.short if v.type else "?", v.length))
            for i, c in enumerate(v.items):
                rec(c, depth + 1, "[%d]" % i)
            return
        w("%s%s: %r" % (ind, label, v))

    rec(g.root, 0, "Document")
    return "\n".join(out) + "\n"


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"') + '"'
