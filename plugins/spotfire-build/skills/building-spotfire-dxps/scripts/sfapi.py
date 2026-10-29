#!/usr/bin/env python3
"""sfapi - query the Spotfire API index that scripts/dump_api.ps1 writes from your installed Analyst.

The index is not shipped: generate it once per Spotfire version on your own machine. sfapi reads the file
named by SFAPI_INDEX, else the newest spotfire-api-*.json in $DXP_WORKSPACE/api/:
  spotfire-api-<coreBuild>.json   public API (declared members per type; inheritance merged here)
  spotfire-property-docs.json     doc text embedded in Spotfire.Dxp.ExtensionBridge.dll (optional, same folder)
  *.xml                           shipped XML doc files, e.g. Spotfire.Dxp.Data.Formats.Sbdf.xml (optional)
Without an index, "has" and "chain" print a warning and exit 0 (the member check is skipped); the other
commands exit 2.

Commands
  info                                   index metadata
  stats                                  counts per assembly / namespace / member kind
  type   <name> [--inherited] [--all]    kind, base chain, ctors, properties, methods, fields, events (+docs)
  search <regex> [--members]             type names (or Type.Member names) matching the regex
  enum   <name|Type.Property>            enum values (Flags marker); for pseudo-enum classes lists static members
  has    <spec> ... [--set] [--stdin]    exit 0 if every spec exists (inherited members + interfaces included), else 1
  ns     [<namespace>] [--recursive]     list namespaces, or the types in one namespace
  chain  <expr> ...                      resolve an IronPython expression step by step; exit 0 if every step resolves
  selftest                               re-run the Spotfire 15.0 spot checks against the current index

Common options: --index FILE (or env SFAPI_INDEX), --full (fully-qualified type names), --json (has/type)

Name resolution: a type may be given as short name (LineChart), CLR full name (Spotfire.Dxp.Application.Visuals.LineChart),
nested (CalculationResults.PropertyNames / Outer+Inner) or generic (ModProperty<T> / ModProperty`1 / IList<DataColumn>).
"has" specs: Type.Member | Type.Member(String, Int32) (one overload; '*' = any one parameter; out/ref prefixes and
str/int/float/bool aliases accepted) | Type.ctor(...) (also ..ctor/#ctor) | Type (existence) | Expr.Member where Expr is
a chain such as Document.Data or Document.Pages[0].Visuals. --set requires a public setter (property) or writable field.
"chain" understands the script globals Document and Application, indexers x[...], calls f(...), generic calls
As[LineChart](), and omitted out-parameters (IronPython returns a tuple). Steps after an Object result are DYNAMIC.
"""
import argparse
import difflib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
import sfenv  # noqa: E402  (SFAPI_INDEX, $DXP_WORKSPACE/api)

QUAL_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
IDENT_RE = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?![\w.])")
ALIASES = {
    "string": "String", "str": "String", "int": "Int32", "long": "Int64", "short": "Int16", "float": "Double",
    "double": "Double", "single": "Single", "bool": "Boolean", "object": "Object", "void": "Void",
    "decimal": "Decimal", "byte": "Byte", "char": "Char", "uint": "UInt32", "ulong": "UInt64",
}
CTOR_NAMES = {"ctor", ".ctor", "#ctor", "new", "__new__", "__init__"}


# ----------------------------------------------------------------------------------------- loading
def _build_key(p):
    m = re.search(r"spotfire-api-([\d.]+)\.json$", p.name)
    return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()


def find_index(explicit):
    """--index, else SFAPI_INDEX, else the newest spotfire-api-*.json in $DXP_WORKSPACE/api/; None when
    there is none."""
    if explicit:
        return Path(explicit)
    return sfenv.api_index()


def pyname(full):
    """CLR full name -> dotted name without generic arity: A.B`1+C -> A.B.C"""
    return re.sub(r"`\d+", "", full or "").replace("+", ".")


def strip_generics(s):
    out, depth = [], 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def split_top(s, sep):
    """split on sep at angle/paren depth 0"""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def apply_subst(s, subst):
    if not subst or not s:
        return s
    return IDENT_RE.sub(lambda m: subst.get(m.group(0), m.group(0)), s)


class Index:
    def __init__(self, path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8") as fh:
            self.data = json.load(fh)
        self.types = self.data["types"]
        self.by_full = {}
        self.keys = defaultdict(list)        # exact keys: fullName, csName, dotted, pyname
        self.short = defaultdict(list)       # short name (no namespace, no arity), nested short path
        self.nested = defaultdict(list)      # declaringType fullName -> nested type entries
        self.short_disp = {}                 # pyname -> short display (keeps Outer.Inner)
        for t in self.types:
            full = t["fullName"]
            self.by_full[full] = t
            for k in {full, t["csName"], full.replace("+", "."), pyname(full), strip_generics(t["csName"])}:
                self.keys[k].append(t)
            pn = pyname(full)
            ns = t.get("namespace") or ""
            rel = pn[len(ns) + 1:] if ns and pn.startswith(ns + ".") else pn
            self.short_disp[pn] = rel
            parts = rel.split(".")
            for i in range(len(parts)):
                self.short[".".join(parts[i:])].append(t)
            clr_rel = full[len(ns) + 1:] if ns and full.startswith(ns + ".") else full
            if clr_rel != rel:
                self.short[clr_rel].append(t)
                self.short[clr_rel.replace("+", ".")].append(t)
            if t.get("declaringType"):
                self.nested[t["declaringType"]].append(t)
        self._docs = None
        self._xmldocs = None

    # --- docs
    def docs(self):
        if self._docs is None:
            self._docs = {"members": {}, "enumValues": {}}
            p = self.path.parent / "spotfire-property-docs.json"
            if p.exists():
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
                self._docs["members"] = d.get("members", {})
                self._docs["enumValues"] = d.get("enumValues", {})
        return self._docs

    def xmldocs(self):
        if self._xmldocs is None:
            self._xmldocs = {}
            import xml.etree.ElementTree as ET
            for p in sorted(self.path.parent.glob("*.xml")):
                try:
                    root = ET.parse(p).getroot()
                except ET.ParseError:
                    continue
                for m in root.iter("member"):
                    name = m.get("name", "")
                    if len(name) < 3 or name[1] != ":":
                        continue
                    full = name[2:].split("(")[0].replace(".#ctor", ".ctor")
                    full = re.sub(r"``?\d+", "", full)
                    summ = m.find("summary")
                    text = " ".join("".join(summ.itertext()).split()) if summ is not None else ""
                    if text:
                        self._xmldocs.setdefault(full, (text, p.name))
        return self._xmldocs

    def doc_for(self, types, member):
        """first doc found for member on any of the given type entries (most specific first)"""
        mdocs = self.docs()["members"]
        for t in types:
            if t is None:
                continue
            key = pyname(t["fullName"]) + "." + member
            if key in mdocs:
                return mdocs[key], self.docs()["enumValues"].get(key)
        for t in types:
            if t is None:
                continue
            if t["fullName"].startswith("Spotfire.Dxp.Data.Formats.Sbdf"):
                key = pyname(t["fullName"]) + "." + member
                hit = self.xmldocs().get(key)
                if hit:
                    return hit[0] + "  [" + hit[1] + "]", None
        return None, None

    def type_doc(self, t):
        if t["fullName"].startswith("Spotfire.Dxp.Data.Formats.Sbdf"):
            hit = self.xmldocs().get(pyname(t["fullName"]))
            if hit:
                return hit[0] + "  [" + hit[1] + "]"
        return None

    # --- lookup
    def resolve(self, name):
        """return list of matching type entries (deterministic order)"""
        name = name.strip()
        if not name:
            return []
        cands = self.keys.get(name) or self.keys.get(name.replace(" ", ""))
        if not cands:
            n2 = re.sub(r"\s+", "", name)
            if "<" in n2:
                base = strip_generics(n2)
                arity = len(split_top(n2[n2.index("<") + 1:n2.rindex(">")], ","))
                pool = self.keys.get(base) or self.short.get(base) or []
                cands = [t for t in pool if len(t.get("genericParameters", [])) == arity] or pool
            elif "`" in n2:
                cands = self.keys.get(pyname(n2)) or self.short.get(pyname(n2)) or []
                cands = [t for t in cands if t["fullName"].endswith(n2) or t["fullName"].replace("+", ".").endswith(n2)] or cands
            else:
                cands = self.short.get(n2, [])
        if not cands:
            low = name.lower()
            cands = [t for k, v in self.short.items() if k.lower() == low for t in v]
        uniq, seen = [], set()
        for t in cands:
            if t["fullName"] not in seen:
                seen.add(t["fullName"])
                uniq.append(t)
        uniq.sort(key=lambda t: (bool(t.get("external")), t["fullName"]))
        return uniq

    def declared_on(self, member, near=None, limit=8):
        """types (non-external) that declare a member with this exact name; same namespace first"""
        hits = []
        for t in self.types:
            if t.get("external"):
                continue
            for _, key in SECTIONS:
                if any(m["name"] == member for m in t.get(key, [])):
                    hits.append(t)
                    break
        ns = (near or {}).get("namespace", "")
        hits.sort(key=lambda t: (t["namespace"] != ns, t["fullName"].count("+"), t["fullName"]))
        shorts = [self.short_disp.get(pyname(t["fullName"]), t["name"]) for t in hits]
        dup = {s for s in shorts if shorts.count(s) > 1}
        names = [pyname(t["fullName"]) if s in dup else s for t, s in zip(hits, shorts)]
        return {"count": len(hits), "types": names[:limit]}

    def suggest_types(self, name, n=6):
        base = strip_generics(name).split(".")[-1]
        return difflib.get_close_matches(base, list(self.short.keys()), n=n, cutoff=0.75)

    # --- inheritance
    def class_chain(self, t):
        """[(entry, subst)] most-derived first; entry None + baseType ref when the chain leaves the index"""
        out, cur, subst, seen = [], t, {}, set()
        while cur is not None and cur["fullName"] not in seen:
            seen.add(cur["fullName"])
            out.append((cur, subst))
            b = cur.get("baseType")
            if not b:
                break
            nxt = self.by_full.get(b.get("id"))
            if nxt is None:
                out.append((None, {"__ref__": apply_subst(b.get("cs"), subst)}))
                break
            gps = [g["name"] for g in nxt.get("genericParameters", [])]
            args = [apply_subst(a, subst) for a in b.get("args", [])]
            subst = dict(zip(gps, args)) if gps and args else {}
            cur = nxt
        return out

    def interface_chain(self, t):
        out = []
        for i in t.get("interfaces", []):
            it = self.by_full.get(i.get("id"))
            gps = [g["name"] for g in it.get("genericParameters", [])] if it else []
            subst = dict(zip(gps, i.get("args", []))) if gps else {}
            out.append((it, subst, i.get("cs")))
        return out


# ----------------------------------------------------------------------------------------- formatting
class Fmt:
    def __init__(self, ix, full=False):
        self.ix, self.full = ix, full

    def t(self, s, subst=None):
        if s is None:
            return ""
        s = apply_subst(s, subst)
        if self.full:
            return s
        s = QUAL_RE.sub(lambda m: self.ix.short_disp.get(m.group(0), m.group(0).rsplit(".", 1)[1]), s)
        return s

    def ret(self, s, subst=None):
        r = self.t(s, subst)
        return "void" if r in ("Void", "System.Void") else r

    def params(self, ps, subst=None):
        out = []
        for p in ps or []:
            s = ""
            if p.get("isParams"):
                s += "params "
            if p.get("isOut"):
                s += "out "
            elif p.get("isRef"):
                s += "ref "
            s += self.t(p["type"], subst) + " " + p["name"]
            if "default" in p:
                s += " = " + p["default"]
            elif p.get("isOptional"):
                s += " = [optional]"
            out.append(s)
        return ", ".join(out)

    @staticmethod
    def gparams(gps):
        return "<" + ", ".join(g["name"] for g in gps) + ">" if gps else ""

    @staticmethod
    def flags(m, kind=None):
        f = []
        vis = m.get("visibility")
        if vis and vis != "public":
            f.append(vis.upper())
        for acc in ("getVisibility", "setVisibility"):
            if m.get(acc) and m[acc] != "public":
                f.append(acc[:3] + " " + m[acc])
        if m.get("apiVersion") is not None:
            f.append("api " + (m["apiVersion"] or "?"))
        if m.get("setApiVersion"):
            f.append("set api " + m["setApiVersion"])
        if "obsolete" in m:
            f.append("OBSOLETE" + (": " + m["obsolete"] if m["obsolete"] else ""))
        if m.get("spotfireInternal"):
            f.append("SpotfireInternal")
        if m.get("editorBrowsableNever"):
            f.append("EditorBrowsable(Never)")
        if m.get("doNotUseOutsideAssembly"):
            f.append("DoNotUseOutsideAssembly")
        if m.get("isExtension"):
            f.append("extension: needs clr.ImportExtensions")
        return ("  [" + "; ".join(f) + "]") if f else ""

    def prop(self, p, subst=None):
        idx = "[" + self.params(p.get("indexParams"), subst) + "]" if p.get("indexParams") else ""
        acc = "get; " if p.get("canRead") else ""
        acc += "set; " if (p.get("hasPublicSetter") or p.get("setVisibility")) else ""
        mods = ("static " if p.get("isStatic") else "") + ("abstract " if p.get("isAbstract") else "")
        return "%s%s %s%s { %s}" % (mods, self.t(p["type"], subst), p["name"], idx, acc)

    def method(self, m, subst=None):
        mods = ""
        if m.get("isStatic"):
            mods += "static "
        if m.get("isAbstract"):
            mods += "abstract "
        elif m.get("isOverride"):
            mods += "override "
        elif m.get("isVirtual"):
            mods += "virtual "
        return "%s%s %s%s(%s)" % (mods, self.ret(m["returnType"], subst), m["name"],
                                  self.gparams(m.get("genericParameters")), self.params(m.get("params"), subst))

    def ctor(self, t, c):
        nm = t["name"].split("`")[0]
        return "%s(%s)" % (nm, self.params(c.get("params")))

    def field(self, f, subst=None):
        mods = ""
        if f.get("isLiteral"):
            mods += "const "
        elif f.get("isStatic"):
            mods += "static "
        if f.get("isInitOnly"):
            mods += "readonly "
        val = " = " + json.dumps(f["value"]) if "value" in f else ""
        return "%s%s %s%s" % (mods, self.t(f["type"], subst), f["name"], val)

    def event(self, e, subst=None):
        return "%sevent %s %s" % ("static " if e.get("isStatic") else "", self.t(e["type"], subst), e["name"])

    def tname(self, t):
        return t["csName"] if self.full else (self.ix.short_disp.get(pyname(t["fullName"]), t["name"]))


def trunc(s, n=220):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 3] + "..."


# ----------------------------------------------------------------------------------------- member collection
def sig_key(kind, m, subst):
    """identity used to hide base/interface members that a more-derived type re-declares (C# hiding/overriding)"""
    if kind in ("method", "operator"):
        return (m["name"], tuple(apply_subst(p["type"], subst) + ("&" if p.get("isOut") or p.get("isRef") else "")
                                 for p in m.get("params", [])), len(m.get("genericParameters", [])))
    if kind == "property":
        return (m["name"], tuple(apply_subst(p["type"], subst) for p in m.get("indexParams", [])))
    return (m["name"],)


SECTIONS = (("property", "properties"), ("method", "methods"), ("field", "fields"),
            ("event", "events"), ("operator", "operators"))


def collect(ix, t, inherited=True, interfaces=True):
    """list of dicts: kind, name, m (raw), decl (entry), subst, via (iface cs or None), explicit"""
    out, seen = [], set()
    chain = ix.class_chain(t) if inherited else [(t, {})]
    expl_names = set()          # "Iface.Member" implemented explicitly somewhere in the class chain
    for entry, _ in chain:
        if entry is not None:
            expl_names.update(entry.get("explicitImplementations", []))

    def add_from(entry, subst, via=None):
        for kind, key in SECTIONS:
            for m in entry.get(key, []):
                k = (kind,) + sig_key(kind, m, subst)
                if k in seen:
                    continue
                seen.add(k)
                expl = bool(via) and (via + "." + m["name"]) in expl_names
                out.append(dict(kind=kind, name=m["name"], m=m, decl=entry, subst=subst, via=via, explicit=expl))

    for entry, subst in chain:
        if entry is None:
            continue
        add_from(entry, subst)
        if entry is t:
            for c in t.get("ctors", []):
                out.append(dict(kind="ctor", name="ctor", m=c, decl=t, subst={}, via=None, explicit=False))
            for v in (t.get("enum") or {}).get("values", []):
                out.append(dict(kind="enumValue", name=v["name"], m=v, decl=t, subst={}, via=None, explicit=False))
        for nt in ix.nested.get(entry["fullName"], []):
            nm = nt["name"].split("`")[0]
            if ("nested", nm) not in seen:
                seen.add(("nested", nm))
                out.append(dict(kind="nestedType", name=nm, m=nt, decl=entry, subst={}, via=None, explicit=False))
    if interfaces and inherited:
        for it, subst, cs in ix.interface_chain(t):
            if it is not None:
                add_from(it, subst, via=cs)
    return out


def describe(fmt, rec, ctx_type):
    kind, m, subst = rec["kind"], rec["m"], rec["subst"]
    if rec.get("decl") is not None and rec["decl"].get("kind") == "interface" and ctx_type.get("kind") != "interface":
        m = dict(m, isAbstract=False, isVirtual=False)   # implemented by the class; 'abstract' is noise here
    if kind == "property":
        s = fmt.prop(m, subst)
    elif kind in ("method", "operator"):
        s = fmt.method(m, subst)
    elif kind == "field":
        s = fmt.field(m, subst)
    elif kind == "event":
        s = fmt.event(m, subst)
    elif kind == "ctor":
        s = fmt.ctor(ctx_type, m)
    elif kind == "enumValue":
        s = "%s = %s" % (m["name"], m["value"])
    elif kind == "nestedType":
        s = "%s %s" % (m["kind"], fmt.tname(m))
    else:
        s = m.get("name", "?")
    return s


def origin(fmt, rec, ctx_type):
    """inner text (no parentheses) describing where an inherited member comes from"""
    notes = []
    if rec["decl"] is not ctx_type and rec["decl"] is not None:
        notes.append(("via interface " + fmt.t(rec["via"])) if rec["via"] else ("inherited from " + fmt.tname(rec["decl"])))
    if rec.get("explicit"):
        notes.append("explicit interface impl: IronPython exposes it by simple name unless ambiguous, else call Iface.%s(obj)" % rec["name"])
    return "; ".join(notes)


# ----------------------------------------------------------------------------------------- commands
def cmd_info(ix, args):
    d = ix.data
    print("index      : %s" % ix.path)
    if d.get("scope"):
        print("scope      : %s" % d["scope"])
    for k in ("product", "productVersion", "productVersionFull", "coreBuild", "coreModule", "sourceVersion", "sourceRevision", "generated", "host"):
        print("%-11s: %s" % (k, d.get(k)))
    print("assemblies :")
    for a in d.get("assemblies", []):
        print("  %-34s %5d types  v%s%s" % (a["name"], a.get("dumpedTypes", 0), a.get("version"), "  load errors: %d" % len(a["loadErrors"]) if a.get("loadErrors") else ""))
    for a in d.get("externalAssemblies", []):
        print("  %-34s %5d types  (external, inherited base types/interfaces only)" % (a["name"], a["types"]))
    for s in d.get("skipped", []):
        print("  skipped %-26s %s" % (s["file"], s["reason"]))
    for n in d.get("notes", []):
        print("note: " + n)
    docs = ix.path.parent / "spotfire-property-docs.json"
    print("docs       : %s" % (docs if docs.exists() else "(none)"))
    return 0


def cmd_stats(ix, args):
    by_asm = defaultdict(lambda: defaultdict(int))
    by_ns = defaultdict(int)
    kinds = defaultdict(int)
    api = defaultdict(int)
    for t in ix.types:
        if t.get("external"):
            continue
        a = by_asm[t["assembly"]]
        a["types"] += 1
        a[t["kind"]] += 1
        by_ns[t["namespace"]] += 1
        for kind, key in SECTIONS + (("ctor", "ctors"),):
            for m in t.get(key, []):
                a[kind] += 1
                kinds[kind] += 1
                api["members"] += 1
                if m.get("apiVersion") is not None:
                    api["withApiVersion"] += 1
                if "obsolete" in m:
                    api["obsolete"] += 1
                if m.get("spotfireInternal"):
                    api["spotfireInternal"] += 1
                if m.get("isExtension"):
                    api["extensionMethods"] += 1
        for v in (t.get("enum") or {}).get("values", []):
            a["enumValue"] += 1
            kinds["enumValue"] += 1
        if t.get("apiVersion") is not None:
            api["typesWithApiVersion"] += 1
        if "obsolete" in t:
            api["typesObsolete"] += 1
        if t.get("spotfireInternal"):
            api["typesSpotfireInternal"] += 1
        api["types"] += 1
    cols = ["types", "class", "interface", "enum", "struct", "delegate", "ctor", "property", "method", "field", "event", "operator", "enumValue"]
    print("%-32s " % "assembly" + " ".join("%9s" % c for c in cols))
    tot = defaultdict(int)
    for name in sorted(by_asm):
        print("%-32s " % name + " ".join("%9d" % by_asm[name][c] for c in cols))
        for c in cols:
            tot[c] += by_asm[name][c]
    print("%-32s " % "TOTAL" + " ".join("%9d" % tot[c] for c in cols))
    print()
    print("api: " + ", ".join("%s=%d" % (k, api[k]) for k in sorted(api)))
    print()
    print("namespaces (%d):" % len(by_ns))
    for ns in sorted(by_ns):
        print("  %5d  %s" % (by_ns[ns], ns))
    return 0


def pick_types(ix, name, allow_many):
    cands = ix.resolve(name)
    if not cands:
        print("no type named '%s'" % name)
        sug = ix.suggest_types(name)
        if sug:
            print("did you mean: " + ", ".join(sug))
        return None, 1
    if len(cands) > 1 and not allow_many:
        print("ambiguous type name '%s' (%d matches); use a qualified name or --all:" % (name, len(cands)))
        for t in cands:
            print("  %-9s %s" % (t["kind"], t["csName"]))
        return None, 2
    return cands, 0


def print_type(ix, fmt, t, inherited, show_docs):
    head = "%s %s" % (t["kind"], t["csName"])
    mods = []
    if t["kind"] == "class":
        if t.get("isStatic"):
            mods.append("static")
        elif t.get("isAbstract"):
            mods.append("abstract")
        elif t.get("isSealed"):
            mods.append("sealed")
    mods.append(t["assembly"] + (" (external)" if t.get("external") else ""))
    print(head + "  [" + "; ".join(mods) + "]" + Fmt.flags(t))
    if t.get("genericParameters"):
        gp = []
        for g in t["genericParameters"]:
            gp.append(g["name"] + (" : " + ", ".join(fmt.t(c) for c in g["constraints"]) if g.get("constraints") else ""))
        print("  generic: " + "; ".join(gp))
    ns = t.get("namespace") or ""
    top = t
    while top.get("declaringType") and top["declaringType"] in ix.by_full:
        top = ix.by_full[top["declaringType"]]
    if t.get("visibility") and t["visibility"] != "public":
        print("  NON-PUBLIC type (%s): not part of the public API; builders and scripts cannot use it" % t["visibility"])
    elif ns and not t.get("external"):
        imp = "from %s import %s" % (ns, top["name"].split("`")[0])
        if top is not t:
            imp += "   # then %s" % pyname(t["fullName"])[len(ns) + 1:]
        print("  import: " + imp)
    td = ix.type_doc(t) if show_docs else None
    if td:
        print("  // " + trunc(td))
    chain = ix.class_chain(t)
    if len(chain) > 1:
        names = []
        for (prev, psubst), (entry, subst) in zip(chain, chain[1:]):
            if entry is None:
                names.append(fmt.t(subst.get("__ref__")) + " (not indexed)")
            else:
                names.append(fmt.t(prev["baseType"]["cs"], psubst))
        print("  base: " + " -> ".join(names))
    if t.get("interfaces"):
        print("  interfaces: " + ", ".join(fmt.t(i["cs"]) for i in t["interfaces"]))
    if t.get("explicitImplementations"):
        print("  explicit impl: " + ", ".join(fmt.t(e.rsplit(".", 1)[0]) + "." + e.rsplit(".", 1)[1]
                                              for e in t["explicitImplementations"]))
    if t.get("declaringType"):
        print("  declared in: " + t["declaringType"].replace("+", "."))
    if t["kind"] == "delegate" and t.get("invoke"):
        inv = t["invoke"]
        print("  invoke: %s (%s)" % (fmt.ret(inv["returnType"]), fmt.params(inv.get("params"))))
    if t.get("enum"):
        e = t["enum"]
        print("  underlying: %s%s" % (fmt.t(e["underlyingType"]), "   [Flags]" if e.get("isFlags") else ""))
        print("  values (%d):" % len(e["values"]))
        for v in e["values"]:
            print("    %s = %s%s" % (v["name"], v["value"], Fmt.flags(v)))
    if t["kind"] not in ("enum", "delegate"):
        cs = t.get("ctors", [])
        if cs:
            print("  ctors (%d):" % len(cs))
            for c in cs:
                print("    " + fmt.ctor(t, c) + Fmt.flags(c))
        elif t["kind"] == "class":
            print("  ctors: none public" + (" (static class)" if t.get("isStatic") else ""))
    recs = collect(ix, t, inherited=inherited, interfaces=(inherited and t["kind"] == "interface"))
    groups = []
    order = [t] + [e for e, _ in ix.class_chain(t)[1:] if e is not None] if inherited else [t]
    if inherited and t["kind"] == "interface":
        order += [it for it, _, _ in ix.interface_chain(t) if it is not None]
    for owner in order:
        own = [r for r in recs if r["decl"] is owner and r["kind"] in ("property", "method", "field", "event", "operator")]
        groups.append((owner, own))
    nested = ix.nested.get(t["fullName"], [])
    for owner, own in groups:
        if owner is not t:
            if not own:
                continue
            print("  --- inherited from %s:" % fmt.tname(owner))
        for kind, key in SECTIONS:
            items = [r for r in own if r["kind"] == kind]
            if not items:
                continue
            print("  %s (%d):" % (key, len(items)))
            for r in items:
                print("    " + describe(fmt, r, t) + Fmt.flags(r["m"]))
                if show_docs and kind in ("property", "method", "field", "event"):
                    doc, ev = ix.doc_for([t, owner], r["name"])
                    if doc:
                        print("        // " + trunc(doc))
                    if ev:
                        print("        // values: " + ", ".join(ev))
    if nested:
        print("  nested types (%d): %s" % (len(nested), ", ".join(n["name"].split("`")[0] for n in nested)))
    return 0


def cmd_type(ix, args):
    cands, rc = pick_types(ix, args.name, args.all)
    if cands is None:
        return rc
    fmt = Fmt(ix, args.full)
    if args.json:
        out = []
        for t in cands:
            if args.inherited:
                recs = collect(ix, t, inherited=True, interfaces=(t["kind"] == "interface"))
                merged = {k: [] for _, k in SECTIONS}
                for r in recs:
                    if r["kind"] in dict(SECTIONS):
                        m = dict(r["m"])
                        m["declaringType"] = r["decl"]["fullName"]
                        merged[dict(SECTIONS)[r["kind"]]].append(m)
                tt = dict(t)
                tt.update({k: v for k, v in merged.items() if v})
                out.append(tt)
            else:
                out.append(t)
        print(json.dumps(out if len(out) > 1 else out[0], indent=1))
        return 0
    for i, t in enumerate(cands):
        if i:
            print()
        print_type(ix, fmt, t, args.inherited, not args.no_docs)
    return 0


def cmd_enum(ix, args):
    cands = [t for t in ix.resolve(args.name) if t["kind"] == "enum"]
    if not cands and "." in args.name:
        tpart, member = args.name.rsplit(".", 1)
        for t in ix.resolve(tpart):
            for r in collect(ix, t):
                if r["name"] == member and r["kind"] in ("property", "field"):
                    et = ix.resolve(strip_generics(apply_subst(r["m"]["type"], r["subst"])).rstrip("?"))
                    cands += [e for e in et if e["kind"] == "enum"]
    if not cands:
        fmt = Fmt(ix, args.full)
        others = ix.resolve(args.name)
        if others:
            # Spotfire often models "enums" as classes with static properties (ScriptLanguage, VisualTypeIdentifiers, ...)
            rc = 1
            for t in others:
                stat = [("property", p) for p in t.get("properties", []) if p.get("isStatic") and p.get("canRead")]
                stat += [("field", f) for f in t.get("fields", []) if f.get("isStatic")]
                print("%s %s is not an enum; static members usable as values (%d):" % (t["kind"], t["csName"], len(stat)))
                for kind, m in stat:
                    print("  " + (fmt.prop(m) if kind == "property" else fmt.field(m)) + Fmt.flags(m))
                if stat:
                    rc = 0
            return rc
        print("no enum named '%s'" % args.name)
        sug = ix.suggest_types(args.name)
        if sug:
            print("did you mean: " + ", ".join(sug))
        return 1
    seen = set()
    first = True
    for t in cands:
        if t["fullName"] in seen:
            continue
        seen.add(t["fullName"])
        if not first:
            print()
        first = False
        e = t["enum"]
        print("enum %s : %s%s%s" % (t["csName"], e["underlyingType"].split(".")[-1], "  [Flags]" if e.get("isFlags") else "", Fmt.flags(t)))
        for v in e["values"]:
            print("  %s = %s%s" % (v["name"], v["value"], Fmt.flags(v)))
    return 0


def norm_param(s):
    s = s.strip()
    s = re.sub(r"^(out|ref|params|in)\s+", "", s)
    s = re.sub(r"\s+", "", s)
    if s in ALIASES:
        s = ALIASES[s]
    return QUAL_RE.sub(lambda m: m.group(0).rsplit(".", 1)[1], s)


def params_match(want, have_params, subst):
    if want is None:
        return True
    want_list = [w for w in split_top(want, ",")] if want.strip() else []
    if len(want_list) != len(have_params):
        return False
    for w, p in zip(want_list, have_params):
        w = norm_param(w)
        if w == "*":
            continue
        h = norm_param(apply_subst(p["type"], subst))
        if w != h and w != norm_param(p["type"]):
            return False
    return True


def parse_spec(spec):
    spec = spec.strip().replace("..ctor", ".ctor")
    want = None
    m = re.match(r"^(.*?)\((.*)\)\s*$", spec)
    if m:
        spec, want = m.group(1).strip(), m.group(2)
    parts = split_top(spec, ".")
    if len(parts) == 1:
        return spec, None, want
    return ".".join(parts[:-1]), parts[-1], want


def check_spec(ix, fmt, spec, need_set):
    """resolve one 'has' spec -> result dict (found, matches, suggestions, ...)"""
    tpart, member, want = parse_spec(spec)
    res = {"spec": spec, "found": False, "matches": [], "suggestions": []}
    # whole spec as a type (Type, Namespace.Type, Outer.Inner)?
    if member is None or (member and not ix.resolve(tpart) and ix.resolve(spec.split("(")[0])):
        types = ix.resolve(spec.split("(")[0] if member else tpart)
        if types and (member is None or want is None):
            for t in types:
                res["matches"].append({"kind": "type", "name": t["name"], "declaringType": t.get("declaringType"),
                                       "signature": "%s %s" % (t["kind"], t["csName"]), "fullName": t["fullName"]})
            res["found"] = True
            return res
    types = ix.resolve(tpart)
    if not types:
        # maybe an expression: Document.Data.Properties / Document.Pages[0].Visuals
        try:
            rows, ok, cur = _resolve_chain(ix, fmt, tpart)
        except ValueError:
            rows, ok, cur = [], False, None
        entry = _entry_for(ix, cur)[0] if ok and cur else None
        if entry is not None and len(rows) > 1:
            types = [entry]
            res["resolvedVia"] = "%s -> %s" % (tpart, fmt.t(cur))
        else:
            res["error"] = "no type named '%s'" % tpart + (
                " (as an expression: %s)" % rows[-1][1] if rows and len(rows) > 1 else "")
            res["suggestions"] = ix.suggest_types(tpart)
            return res
    is_ctor = member in CTOR_NAMES
    readonly = []
    for t in types:
        recs = collect(ix, t)
        names = sorted({r["name"] for r in recs if r["kind"] != "ctor"})
        for r in recs:
            if is_ctor:
                if r["kind"] != "ctor":
                    continue
            elif r["name"] != member or r["kind"] == "ctor":
                continue
            if want is not None:
                if r["kind"] in ("method", "operator", "ctor"):
                    if not params_match(want, r["m"].get("params", []), r["subst"]):
                        continue
                elif r["kind"] == "property" and r["m"].get("indexParams"):
                    if not params_match(want, r["m"]["indexParams"], r["subst"]):
                        continue
                else:
                    continue
            if need_set:
                settable = ((r["kind"] == "property" and r["m"].get("hasPublicSetter")) or
                            (r["kind"] == "field" and not (r["m"].get("isLiteral") or r["m"].get("isInitOnly"))))
                if not settable:
                    readonly.append(describe(fmt, r, t) + ("  (" + origin(fmt, r, t) + ")" if origin(fmt, r, t) else ""))
                    continue
            m = r["m"]
            res["matches"].append({
                "kind": r["kind"], "name": r["name"], "type": t["fullName"], "declaringType": r["decl"]["fullName"],
                "via": r["via"], "explicit": r["explicit"], "signature": describe(fmt, r, t),
                "origin": origin(fmt, r, t), "flags": Fmt.flags(m).strip()[1:-1] if Fmt.flags(m) else "",
                "apiVersion": m.get("apiVersion"), "obsolete": m.get("obsolete"),
                "settable": bool(m.get("hasPublicSetter")) if r["kind"] == "property" else (
                    not (m.get("isLiteral") or m.get("isInitOnly")) if r["kind"] == "field" else None),
                "static": m.get("isStatic"),
            })
        if not res["matches"] and not is_ctor and not readonly:
            sug = difflib.get_close_matches(member, names, n=6, cutoff=0.6)
            ci = [n for n in names if n.lower() == (member or "").lower() and n not in sug]
            res["suggestions"] += [x for x in ci + sug if x not in res["suggestions"]]
        if not res["matches"] and want is not None and not readonly:
            for r in recs:
                if (is_ctor and r["kind"] == "ctor") or (not is_ctor and r["name"] == member):
                    res.setdefault("overloads", []).append(describe(fmt, r, t))
    res["found"] = bool(res["matches"])
    if len(types) > 1:
        res["ambiguousType"] = [t["fullName"] for t in types]
    if not res["found"] and is_ctor and not any(t.get("ctors") for t in types):
        res["error"] = "%s has no public constructors (obtain instances from a collection/factory member)" % (
            ", ".join(t["csName"] for t in types))
    if not res["found"] and readonly:
        res["readOnly"] = readonly
    elif not res["found"] and member and not is_ctor and "overloads" not in res:
        res["declaredOn"] = ix.declared_on(member, types[0])
    return res


def cmd_has(ix, args):
    fmt = Fmt(ix, args.full)
    specs = list(args.specs)
    if args.stdin:
        specs += [l.strip() for l in sys.stdin if l.strip() and not l.lstrip().startswith("#")]
    if not specs:
        print("has: no spec given")
        return 2
    results = [check_spec(ix, fmt, s, args.set) for s in specs]
    all_ok = all(r["found"] for r in results)
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=1))
        return 0 if all_ok else 1
    for r in results:
        if args.quiet:
            if not r["found"]:
                print("NO  " + r["spec"])
            continue
        print(("OK  " if r["found"] else "NO  ") + r["spec"])
        if r.get("ambiguousType"):
            print("    (type name matches %d types: %s)" % (len(r["ambiguousType"]), ", ".join(r["ambiguousType"])))
        if r.get("resolvedVia"):
            print("    (expression %s)" % r["resolvedVia"])
        for m in r["matches"]:
            line = "    %-10s %s" % (m["kind"], m["signature"])
            if m.get("origin"):
                line += "  (" + m["origin"] + ")"
            if m.get("flags"):
                line += "  [" + m["flags"] + "]"
            if len(r.get("ambiguousType", [])) > 1 and m.get("type"):
                line += "  {" + m["type"] + "}"
            print(line)
        if not r["found"]:
            if r.get("error"):
                print("    " + r["error"])
            if r.get("readOnly"):
                print("    exists, but not settable (--set needs a property with a public setter or a writable field):")
                for o in r["readOnly"]:
                    print("      " + o)
            if r.get("overloads"):
                print("    available overloads:")
                for o in r["overloads"]:
                    print("      " + o)
            if r.get("suggestions"):
                print("    did you mean: " + ", ".join(r["suggestions"]))
            if not any(r.get(k) for k in ("error", "readOnly", "overloads", "suggestions")) and not (
                    r.get("declaredOn") and r["declaredOn"]["count"]):
                print("    no such member on %s (inherited members and interfaces included)" % (
                    r.get("resolvedVia", "").split(" -> ")[-1] or r["spec"].split("(")[0].rsplit(".", 1)[0]))
            if r.get("declaredOn") and r["declaredOn"]["count"]:
                d = r["declaredOn"]
                print("    '%s' is declared on %d other type(s): %s%s" % (
                    r["spec"].split("(")[0].rsplit(".", 1)[-1], d["count"], ", ".join(d["types"]),
                    ", ..." if d["count"] > len(d["types"]) else ""))
    return 0 if all_ok else 1


# ----------------------------------------------------------------------------------------- chain
SCRIPT_GLOBALS = {"Document": "Spotfire.Dxp.Application.Document",
                  "Application": "Spotfire.Dxp.Application.AnalysisApplication"}


def _read_balanced(s, i, open_ch, close_ch):
    depth, j = 0, i
    while j < len(s):
        if s[j] == open_ch:
            depth += 1
        elif s[j] == close_ch:
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        elif s[j] in "\"'":
            q = s[j]
            j += 1
            while j < len(s) and s[j] != q:
                j += 2 if s[j] == "\\" else 1
        j += 1
    raise ValueError("unbalanced %s in %r" % (open_ch, s))


def parse_chain(expr):
    """Document.Data.Tables["x"].Columns / vis.As[LineChart]() -> list of steps"""
    steps, i, s = [], 0, expr.strip()
    while i < len(s):
        m = re.match(r"\s*\.?\s*([A-Za-z_]\w*)", s[i:])
        if not m:
            raise ValueError("cannot parse %r at %d" % (s, i))
        steps.append(("member", m.group(1)))
        i += m.end()
        while i < len(s) and s[i] in "[(":
            if s[i] == "[":
                inner, j = _read_balanced(s, i, "[", "]")
                if j < len(s) and s[j] == "(":
                    steps.append(("generic", [x.strip() for x in split_top(inner, ",")]))
                else:
                    steps.append(("index", inner))
                i = j
            else:
                inner, i = _read_balanced(s, i, "(", ")")
                steps.append(("call", inner))
    return steps


def _entry_for(ix, cs):
    """type string -> (entry, subst) using generic args of a constructed type"""
    if not cs:
        return None, {}
    cs = cs.rstrip("?")
    if cs.endswith("[]"):
        return None, {}
    base = strip_generics(cs)
    cands = ix.keys.get(base) or ix.resolve(base)
    if not cands:
        return None, {}
    e = cands[0]
    subst = {}
    if "<" in cs and e.get("genericParameters"):
        args = [a.strip() for a in split_top(cs[cs.index("<") + 1:cs.rindex(">")], ",")]
        subst = dict(zip([g["name"] for g in e["genericParameters"]], args))
    return e, subst


def _generics_inferable(m):
    gps = [g["name"] for g in m.get("genericParameters", [])]
    if not gps:
        return True
    ptxt = " ".join(p["type"] for p in m.get("params", []))
    return all(re.search(r"(?<![\w.])%s(?![\w.])" % re.escape(g), ptxt) for g in gps)


NUMERIC_WIDEN = {"System.Int32": {"System.Int64", "System.Double", "System.Single", "System.Decimal"},
                 "System.Double": {"System.Single", "System.Decimal"}}


def _arg_type(ix, fmt, arg):
    """best-effort static type of an argument expression (None = unknown)"""
    a = arg.strip()
    if not a or "=" in a.split("(")[0]:          # empty or keyword argument
        return None
    if re.match(r"""^[rRuUbBfF]{0,2}["']""", a):
        return "System.String"
    if re.match(r"^-?\d+$", a):
        return "System.Int32"
    if re.match(r"^-?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?$", a):
        return "System.Double"
    if a in ("True", "False"):
        return "System.Boolean"
    if a == "None":
        return "null"
    if re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$", a):   # dotted static chain, e.g. VisualTypeIdentifiers.LineChart
        try:
            rows, ok, cur = _resolve_chain(ix, fmt, a)
        except ValueError:
            return None
        if ok and cur and not cur.startswith("tuple("):
            return cur
    return None


def _args_fit(ix, atypes, params, substs):
    for at, p in zip(atypes, params):
        if at is None:
            continue
        pt = p["type"]
        for sm in substs:
            pt = apply_subst(pt, sm)
        if at == "null":
            continue
        if pt == "System.Object" or IDENT_RE.fullmatch(pt or ""):   # object or an open generic parameter
            continue
        if strip_generics(at) == strip_generics(pt) or pt in NUMERIC_WIDEN.get(at, ()):
            continue
        e, _ = _entry_for(ix, at)
        if e is None:
            continue                                  # unknown argument type: do not reject
        want = strip_generics(pt)
        anc = {strip_generics(x["csName"]) for x, _ in ix.class_chain(e) if x is not None}
        anc |= {strip_generics(i["cs"]) for i in e.get("interfaces", [])}
        if want not in anc:
            return False
    return True


def resolve_chain(ix, fmt, expr):
    """walk an attribute/call/index chain; returns (rows, ok)"""
    rows, ok, _ = _resolve_chain(ix, fmt, expr)
    return rows, ok


def _resolve_chain(ix, fmt, expr):
    """returns (rows, ok, final_type_cs_or_None)"""
    steps = parse_chain(expr)
    first = steps[0][1]
    types = ix.resolve(SCRIPT_GLOBALS.get(first, first))
    if not types:
        return [(first, "NO TYPE (not a script global or type name)")], False, None
    cur = types[0]["csName"]
    rows = [(first, fmt.t(cur) + ("   (script global)" if first in SCRIPT_GLOBALS else "   (type)"))]
    is_type_ref = first not in SCRIPT_GLOBALS       # cur names a type (static access / constructor call)
    methods, generic = None, None                   # pending method group / explicit generic args
    ok = True

    def sub(text, *substs):
        for sm in substs:
            text = apply_subst(text, sm)
        return text

    k = 1
    while k < len(steps):
        kind, val = steps[k]
        if kind == "generic":
            generic = val
            rows[-1] = (rows[-1][0] + "[" + ", ".join(val) + "]", rows[-1][1])
            k += 1
            continue
        if kind == "call" and methods is not None:
            argc = 0 if not val.strip() else len(split_top(val, ","))

            def fits(m):
                """'' = exact arity, 'outs' = IronPython call with the out params omitted, None = no fit"""
                ps = m.get("params", [])
                if len(ps) == argc:
                    return ""
                if ps and ps[-1].get("isParams") and argc >= len(ps) - 1:
                    return ""
                if argc < len(ps) and all(p.get("isOptional") for p in ps[argc:]):
                    return ""
                ins = [p for p in ps if not p.get("isOut")]
                if len(ins) != len(ps) and len(ins) == argc:
                    return "outs"
                return None
            cands = [(r, ss, fits(r["m"])) for r, ss in methods]
            cands = [c for c in cands if c[2] is not None]
            if generic is not None:
                cands = [c for c in cands if len(c[0]["m"].get("genericParameters", [])) == len(generic)]
            else:
                # without [T] IronPython can only call a generic method whose type parameters appear in its parameters
                cands = [c for c in cands if _generics_inferable(c[0]["m"])]
            typed_note = ""
            if len(cands) > 1 and argc:
                atypes = [_arg_type(ix, fmt, a) for a in split_top(val, ",")]
                typed = [c for c in cands if _args_fit(ix, atypes, c[0]["m"].get("params", []), c[1])]
                if typed:
                    cands = typed
                elif any(atypes):
                    typed_note = "; argument types unverified"
            if not cands:
                rows.append(("(%s)" % val, "NO overload with %d arg(s)%s; available: %s" % (
                    argc, (" and %d type arg(s)" % len(generic)) if generic else "",
                    " | ".join(describe(fmt, r, r["decl"]) for r, _ in methods))))
                ok = False
                break
            rets = []
            for r, ss, how in cands:
                gsub = {}
                if generic is not None:
                    gnames = [g["name"] for g in r["m"].get("genericParameters", [])]
                    gargs = [(ix.resolve(g)[0]["csName"] if ix.resolve(g) else g) for g in generic]
                    gsub = dict(zip(gnames, gargs))
                ret = sub(r["m"]["returnType"], *(ss + [gsub]))
                if how == "outs":
                    # IronPython returns (result, out1, ...) - or just the out value for a void method with one out
                    outs = [sub(p["type"], *(ss + [gsub])) for p in r["m"]["params"] if p.get("isOut")]
                    parts = ([] if ret == "System.Void" else [ret]) + outs
                    ret = parts[0] if len(parts) == 1 else "tuple(" + ", ".join(fmt.t(x) for x in parts) + ")"
                rets.append(ret)
            uniq = sorted(set(rets))
            cur = uniq[0] if len(uniq) == 1 else None
            note = "; out params omitted -> IronPython returns a tuple" if any(c[2] == "outs" for c in cands) else ""
            note += typed_note
            rows.append(("(%s)" % val, ("%s   (%d matching overload%s%s)" % (fmt.ret(cur), len(cands), "s" if len(cands) > 1 else "", note))
                         if cur else "AMBIGUOUS return type: " + " | ".join(fmt.t(u) for u in uniq)))
            methods, generic, is_type_ref = None, None, False
            if cur is None or cur.startswith("tuple("):
                break
            k += 1
            continue
        if cur in ("System.Object", "System.Void"):
            rows.append((("." + val) if kind == "member" else ("[%s]" % val if kind == "index" else "(%s)" % val),
                         "DYNAMIC (previous step returns %s; not checkable)" % fmt.t(cur)))
            break
        entry, csub = _entry_for(ix, cur)
        if entry is None:
            rows.append((("." + val) if kind == "member" else val, "NOT INDEXED type %s" % fmt.t(cur)))
            ok = False
            break
        if kind == "call":
            argc = 0 if not val.strip() else len(split_top(val, ","))
            if is_type_ref:
                ctors = [c for c in entry.get("ctors", []) if len(c.get("params", [])) == argc]
                if ctors:
                    rows.append(("(%s)" % val, "%s   (constructor, %d arg(s))" % (fmt.t(cur), argc)))
                    is_type_ref = False
                    k += 1
                    continue
                rows.append(("(%s)" % val, "NO public constructor with %d arg(s) on %s" % (argc, fmt.t(cur))))
            else:
                rows.append(("(%s)" % val, "NOT CALLABLE (%s)" % fmt.t(cur)))
            ok = False
            break
        recs = collect(ix, entry)
        if kind == "index":
            argc = len(split_top(val, ","))
            idx = [r for r in recs if r["kind"] == "property" and len(r["m"].get("indexParams", [])) == argc]
            if not idx:
                rows.append(("[%s]" % val, "NO indexer with %d arg(s) on %s" % (argc, fmt.t(cur))))
                ok = False
                break
            outs = sorted({sub(r["m"]["type"], r["subst"], csub) for r in idx})
            sigs = " | ".join(fmt.prop(r["m"], r["subst"]) for r in idx)
            cur = outs[0] if len(outs) == 1 else None
            rows.append(("[%s]" % val, "%s   (indexer: %s)" % (fmt.t(cur) if cur else "AMBIGUOUS", sigs)))
            is_type_ref = False
            if cur is None:
                break
            k += 1
            continue
        # member
        hits = [r for r in recs if r["name"] == val and r["kind"] != "ctor"]
        if not hits:
            sug = difflib.get_close_matches(val, sorted({r["name"] for r in recs if r["kind"] != "ctor"}), n=5, cutoff=0.6)
            rows.append(("." + val, "NOT FOUND on %s%s" % (fmt.t(cur), ("  did you mean: " + ", ".join(sug)) if sug else "")))
            ok = False
            break
        r0 = hits[0]
        where = origin_short(fmt, r0, entry)
        if r0["kind"] in ("method", "operator"):
            methods = [(r, [r["subst"], csub]) for r in hits if r["kind"] in ("method", "operator")]
            nxt = steps[k + 1][0] if k + 1 < len(steps) else None
            if nxt not in ("call", "generic"):
                rows.append(("." + val, "method group (%d overload%s), not called" % (len(methods), "s" if len(methods) > 1 else "")))
                cur, methods = None, None
                break
            rows.append(("." + val, "method%s" % where))
        elif r0["kind"] in ("property", "field", "event"):
            cur = sub(r0["m"]["type"], r0["subst"], csub)
            stat = " static" if r0["m"].get("isStatic") else ""
            rows.append(("." + val, "%s   (%s%s%s)" % (fmt.t(cur), r0["kind"], stat, where)))
            is_type_ref = False
        elif r0["kind"] == "enumValue":
            rows.append(("." + val, "%s   (enum value = %s)" % (fmt.t(cur), r0["m"]["value"])))
            is_type_ref = False
        elif r0["kind"] == "nestedType":
            cur = r0["m"]["csName"]
            rows.append(("." + val, "%s   (nested type)" % fmt.t(cur)))
            is_type_ref = True
        k += 1
    return rows, ok, (cur if ok else None)


def origin_short(fmt, rec, ctx):
    if rec["decl"] is not ctx and rec["decl"] is not None:
        return ", via " + fmt.t(rec["via"]) if rec["via"] else ", from " + fmt.tname(rec["decl"])
    return ""


def cmd_chain(ix, args):
    fmt = Fmt(ix, args.full)
    all_ok = True
    for expr in args.exprs:
        try:
            rows, ok = resolve_chain(ix, fmt, expr)
        except ValueError as e:
            rows, ok = [(expr, "PARSE ERROR: %s" % e)], False
        all_ok &= ok
        partial = ok and rows and rows[-1][1].startswith(("AMBIGUOUS", "DYNAMIC"))
        print(("OK? " if partial else "OK  " if ok else "NO  ") + expr
              + ("   (partially checked: the rest is not statically resolvable)" if partial else ""))
        w = max(len(r[0]) for r in rows)
        for a, b in rows:
            print("    %-*s  %s" % (w, a, b))
    return 0 if all_ok else 1


def member_rows(ix, fmt, t):
    for kind, key in SECTIONS + (("ctor", "ctors"),):
        for m in t.get(key, []):
            if kind == "ctor":
                yield "ctor", "ctor", fmt.ctor(t, m), m
            elif kind == "property":
                yield kind, m["name"], fmt.prop(m), m
            elif kind in ("method", "operator"):
                yield kind, m["name"], fmt.method(m), m
            elif kind == "field":
                yield kind, m["name"], fmt.field(m), m
            else:
                yield kind, m["name"], fmt.event(m), m
    for v in (t.get("enum") or {}).get("values", []):
        yield "enumValue", v["name"], "%s = %s" % (v["name"], v["value"]), v


def cmd_search(ix, args):
    flags = 0 if args.case else re.IGNORECASE
    try:
        rx = re.compile(args.regex, flags)
    except re.error as e:
        print("bad regex: %s" % e)
        return 2
    fmt = Fmt(ix, args.full)
    rows = []
    for t in ix.types:
        if t.get("external") and not args.external:
            continue
        if args.ns and not (t["namespace"] == args.ns or t["namespace"].startswith(args.ns + ".")):
            continue
        if args.members:
            short = ix.short_disp.get(pyname(t["fullName"]), t["name"])
            for kind, name, sig, m in member_rows(ix, fmt, t):
                if args.kind and kind != args.kind:
                    continue
                if rx.search(short + "." + name):
                    rows.append("%-24s %-9s %s%s" % (short, kind, sig, Fmt.flags(m)))
        else:
            if args.kind and t["kind"] != args.kind:
                continue
            if rx.search(pyname(t["fullName"])) or rx.search(t["csName"]):
                rows.append("%-9s %s%s" % (t["kind"], t["csName"], "  (external)" if t.get("external") else ""))
    limit = args.limit
    for r in rows[: limit if limit > 0 else None]:
        print(r)
    if limit > 0 and len(rows) > limit:
        print("... %d more (use --limit 0 for all)" % (len(rows) - limit))
    if not rows:
        print("no matches")
        return 1
    return 0


def cmd_ns(ix, args):
    types = [t for t in ix.types if args.external or not t.get("external")]
    if not args.namespace:
        counts = defaultdict(int)
        for t in types:
            counts[t["namespace"]] += 1
        for ns in sorted(counts):
            print("%5d  %s" % (counts[ns], ns))
        return 0
    ns = args.namespace.rstrip(".")
    sel = [t for t in types if t["namespace"] == ns or (args.recursive and t["namespace"].startswith(ns + "."))]
    if not sel:
        cands = sorted({t["namespace"] for t in types if ns.lower() in t["namespace"].lower()})
        print("no types in namespace '%s'" % ns)
        if cands:
            print("namespaces containing it: " + ", ".join(cands[:15]))
        return 1
    for t in sel:
        nm = t["csName"][len(t["namespace"]) + 1:] if not args.recursive else t["csName"]
        print("%-9s %s%s" % (t["kind"], nm, Fmt.flags(t)))
    return 0


# ----------------------------------------------------------------------------------------- selftest
# (spec, need_set, expected match count or None for ">=1", expected signature substring or None); 0 = must NOT exist.
# Values verified against Spotfire 15.0 (core 71.0.22206.3863); after a version upgrade, review failures by hand.
SELFTEST_HAS = [
    ("AnalysisApplication.SaveAs(String, DocumentSaveSettings)", False, 1, "void SaveAs(String fileName, DocumentSaveSettings settings)"),
    ("ScriptManager.ExecuteScript", False, 6, None),
    ("ScriptManager.ExecuteScript(String, ScriptLanguage, IDictionary<String, Object>)", False, 1, None),
    ("ScriptDefinition.Create", False, 1, "static ScriptDefinition Create(String name, String description, String scriptCode, "
                                          "ScriptLanguage language, ScriptParameterCollection parameters, Boolean wrapInTransaction)"),
    ("DocumentSaveSettings.ConfigurationBlockText", True, 1, "String ConfigurationBlockText { get; set; }"),
    ("ScriptLanguage.IronPython3", False, 1, "static ScriptLanguage IronPython3 { get; }"),
    ("Page.Visuals", False, 1, "VisualCollection Visuals { get; }"),
    ("VisualCollection.AddNew", False, 4, None),
    ("LineChart.XAxis", False, 1, "ScaleAxis XAxis { get; }"),
    ("HtmlTextArea.HtmlContent", True, 1, None),
    ("DataTableCollection.Add", False, 2, None),
    ("DataFunctionDefinitionBuilder.ctor", False, 2, None),
    ("DataProperty.CreateCustomPrototype", False, 3, None),
    ("LayoutDefinition.Add", False, 2, None),
    ("PageCollection.NavigationMode", True, 1, "PageNavigationMode NavigationMode { get; set; }"),
    ("LineChart.Title", True, 1, None),            # inherited from VisualContent
    ("PageCollection.Item(Int32)", False, 1, "Page Item[Int32 index] { get; }"),   # generic base substitution
    ("Visual.As", False, 1, "T As<T>()"),
    ("LineChart.Id", False, 0, None),              # Id lives on Visual, not on the VisualContent
    ("VisualContent.Visual", True, 0, None),       # read-only
]
SELFTEST_ENUMS = [("PageNavigationMode", ["Tabs=0", "Links=1", "None=2", "Off=3"])]
SELFTEST_CHAINS = [('Document.Pages[0].Visuals.AddNew[LineChart]().XAxis.Expression', "String"),
                   ('Document.Data.Tables.TryGetValue("x")', "tuple(Boolean, DataTable)")]


def cmd_selftest(ix, args):
    fmt = Fmt(ix, False)
    fails, total = [], 0
    for spec, need_set, count, sig in SELFTEST_HAS:
        total += 1
        r = check_spec(ix, fmt, spec, need_set)
        n = len(r["matches"])
        good = (n == 0) if count == 0 else (n >= 1 if count is None else n == count)
        if good and sig:
            good = any(m["signature"] == sig for m in r["matches"])
        print("%s  has %s%s -> %d match(es)" % ("PASS" if good else "FAIL", spec, " --set" if need_set else "", n))
        if not good:
            fails.append(spec)
    for name, want in SELFTEST_ENUMS:
        total += 1
        e = [t for t in ix.resolve(name) if t["kind"] == "enum"]
        got = ["%s=%s" % (v["name"], v["value"]) for v in e[0]["enum"]["values"]] if e else []
        good = got == want
        print("%s  enum %s -> %s" % ("PASS" if good else "FAIL", name, ", ".join(got)))
        if not good:
            fails.append(name)
    for expr, want in SELFTEST_CHAINS:
        total += 1
        rows, ok, cur = _resolve_chain(ix, fmt, expr)
        last = rows[-1][1].split("   ")[0]
        good = ok and last == want
        print("%s  chain %s -> %s" % ("PASS" if good else "FAIL", expr, last))
        if not good:
            fails.append(expr)
    print("selftest: %d/%d passed (index %s, core %s)" % (total - len(fails), total, ix.path.name, ix.data.get("coreBuild")))
    return 0 if not fails else 1


# ----------------------------------------------------------------------------------------- main
VALUE_FLAGS = {"--index", "--limit", "--kind", "--ns"}


def _hoist_flags(argv, commands):
    """argparse cannot interleave flags with a nargs='*' positional list ('has A --set B');
    move every flag that follows the sub-command in front of its positionals."""
    for i, tok in enumerate(argv):
        if tok in commands:
            head, rest = argv[: i + 1], argv[i + 1:]
            flags, pos, j = [], [], 0
            while j < len(rest):
                t = rest[j]
                if t == "--":
                    pos += rest[j + 1:]
                    break
                if t.startswith("--"):
                    flags.append(t)
                    if t in VALUE_FLAGS and "=" not in t and j + 1 < len(rest):
                        flags.append(rest[j + 1])
                        j += 1
                elif t in ("-h",):
                    flags.append(t)
                else:
                    pos.append(t)
                j += 1
            return head + flags + (["--"] + pos if pos and any(p.startswith("-") for p in pos) else pos)
    return argv


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    top = argparse.ArgumentParser(add_help=False)
    top.add_argument("--index", help="index JSON (default: $SFAPI_INDEX, else the newest "
                     "$DXP_WORKSPACE/api/spotfire-api-*.json)")
    top.add_argument("--full", action="store_true", help="fully-qualified type names")
    # same options accepted after the sub-command; SUPPRESS keeps a value given before it
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--index", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--full", action="store_true", default=argparse.SUPPRESS, help="fully-qualified type names")
    ap = argparse.ArgumentParser(prog="sfapi", description=__doc__.split("\n")[0], parents=[top],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("info", parents=[common])
    sub.add_parser("stats", parents=[common])
    p = sub.add_parser("type", parents=[common])
    p.add_argument("name")
    p.add_argument("--inherited", action="store_true", help="merge members of base types (and base interfaces)")
    p.add_argument("--all", action="store_true", help="show every type matching an ambiguous short name")
    p.add_argument("--no-docs", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search", parents=[common])
    p.add_argument("regex")
    p.add_argument("--members", action="store_true", help="match 'Type.Member' instead of type names")
    p.add_argument("--kind", help="type kind (class/enum/interface/struct/delegate) or member kind (property/method/field/event/ctor/enumValue)")
    p.add_argument("--ns", help="restrict to a namespace (and its sub-namespaces)")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--case", action="store_true", help="case-sensitive")
    p.add_argument("--external", action="store_true", help="include inherited System types")
    p = sub.add_parser("enum", parents=[common])
    p.add_argument("name")
    p = sub.add_parser("has", parents=[common])
    p.add_argument("specs", nargs="*")
    p.add_argument("--set", action="store_true", help="require a public setter / writable field")
    p.add_argument("--stdin", action="store_true", help="read more specs from stdin, one per line")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true", help="print only the specs that were not found")
    p = sub.add_parser("ns", parents=[common])
    p.add_argument("namespace", nargs="?")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--external", action="store_true")
    p = sub.add_parser("chain", parents=[common],
                       help="resolve an expression step by step, e.g. Document.Data.Tables[\"T\"].Columns or vis.As[LineChart]().XAxis")
    p.add_argument("exprs", nargs="+")
    sub.add_parser("selftest", parents=[common], help="re-run the Spotfire 15.0 spot checks against the index")
    args = ap.parse_args(_hoist_flags(sys.argv[1:] if argv is None else list(argv), set(sub.choices)))
    if not args.cmd:
        ap.print_help()
        return 2
    path = find_index(args.index)
    if path is None or not Path(path).is_file():
        sys.stderr.write("sfapi: WARNING %s\n" % sfenv.NO_INDEX_HINT)
        if args.cmd in ("has", "chain"):
            # the member check is skipped, not failed: a machine without the index can still build
            sys.stderr.write("sfapi: member check skipped\n")
            return 0
        return 2
    ix = Index(path)
    return {"info": cmd_info, "stats": cmd_stats, "type": cmd_type, "search": cmd_search,
            "enum": cmd_enum, "has": cmd_has, "ns": cmd_ns, "chain": cmd_chain,
            "selftest": cmd_selftest}[args.cmd](ix, args)


if __name__ == "__main__":
    sys.exit(main())
