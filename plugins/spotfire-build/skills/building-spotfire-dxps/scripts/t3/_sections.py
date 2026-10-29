"""Spec sections -> APP keys of the standard engine's feature parts (engine/features/*.py).

    properties     -> APP "properties"     [[name, type, default, listValued, description], ...]
    markings       -> APP "markings"       [[name, color], ...] (the default marking stays APP "marking")
    dataFunctions  -> APP "dataFunctions"  [{name, file|code, description, in, out, refresh, run}]
                      and APP "dfTables"   [[table, {format: [columns]}], ...] (every output table)
    scripts        -> APP "scripts"        [{name, file|code, description, params, transaction}]
    vizMods        -> APP "vizMods"        [[id, project folder relative to HOME, manifest version], ...]
                      (the mods a mod visual uses; scripts/t3/mod.py converts the visuals)
    text controls  -> APP visual "controls" {id: marker text} (the controls themselves are manual
                      steps: t3/_manual.py)

Property triggers, action mods, visual action triggers and the theme have no public API: they become
APP "manual" entries (t3/_manual.py), not APP keys of their own. A data-function input limited by a
marking keeps its bind and adds "marking": <name> (table and column binds only).

Files stay files the builder reads at run time (data-function code from HOME\\datafunctions, scripts
from HOME\\scripts, like the HTML), so the builder stays small. references/engine.md documents the keys.
"""
import datetime
import decimal
import json
import os
import re

from . import _manual
from ._common import blank

LIST_TYPES = ("String", "Integer", "LongInteger", "Real", "SingleReal", "Currency", "Boolean", "Date",
              "DateTime", "Time", "TimeSpan")
TIMESPAN_RE = re.compile(r"^(-)?(?:(\d+)\.)?(\d+):(\d+)(?::(\d+)(?:\.(\d+))?)?$")


def _rel(app_dir, value, folder):
    """A spec file path (relative to the app folder) -> relative to HOME\\<folder>."""
    app_dir = str(app_dir)
    full = os.path.normpath(os.path.join(app_dir, value.strip()))
    return os.path.relpath(full, os.path.join(app_dir, folder)).replace("/", "\\")


def _raw_list(raw, key):
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if isinstance(value, list) else []


def _at(items, n):
    return items[n] if n < len(items) and isinstance(items[n], dict) else {}


# ---------------------------------------------------------------------------------------------
# properties, markings
# ---------------------------------------------------------------------------------------------
def properties(resolved, ctx):
    out = []
    for n, p in enumerate(resolved.get("properties") or []):
        if not isinstance(p, dict):
            continue
        path = "properties[%d]" % n
        ptype = p.get("type") or "String"
        listed = bool(p.get("listValued"))
        if ptype == "Binary" and (listed or p.get("default") is not None):
            ctx.unsupported(path, "a Binary property with a default or a list")
        elif listed and ptype not in LIST_TYPES:
            ctx.unsupported(path + ".listValued", "a list-valued %s property" % ptype)
        entry = [p.get("name"), ptype, p.get("default")]
        desc = p.get("description") or ""
        if listed or desc:
            entry.append(listed)
        if desc:
            entry.append(desc)
        out.append(entry)
    return out


def markings(resolved, default, ctx):
    out = []
    for n, m in enumerate(resolved.get("markings") or []):
        if not isinstance(m, dict) or m is default:
            continue
        out.append([m.get("name"), ctx.color(m.get("color"), "markings[%d].color" % n)])
    return out


def property_type(resolved, name):
    for p in resolved.get("properties") or []:
        if isinstance(p, dict) and str(p.get("name") or "").lower() == str(name or "").lower():
            return p.get("type") or "String"
    return None


# ---------------------------------------------------------------------------------------------
# data functions
# ---------------------------------------------------------------------------------------------
def declared_columns(resolved, table):
    """Column names a dataFunction table declares in tables[].columns (spec order), or None."""
    for t in resolved.get("tables") or []:
        if isinstance(t, dict) and t.get("name") == table:
            src = t.get("source") if isinstance(t.get("source"), dict) else {}
            cols = t.get("columns") if isinstance(t.get("columns"), dict) else {}
            if src.get("type") == "dataFunction" and cols:
                return list(cols)
    return None


def real_text(value):
    """Culture-invariant Real literal: repr digits, exponent expanded, '.0' added."""
    text = format(decimal.Decimal(repr(float(value))), "f")
    return text if "." in text else text + ".0"


def literal(value, types, path, ctx):
    """A bind.value -> {"value": text} (String, escaped by the engine) or {"expression": literal}
    (references/api-datafunctions.md R4)."""
    if value is None or isinstance(value, (list, dict)):
        ctx.unsupported(path, "bind.value %r (bind a document property instead)" % (value,))
        return {"value": ""}
    natural = ("Boolean" if isinstance(value, bool) else "Integer" if isinstance(value, int)
               else "Real" if isinstance(value, float) else "String")
    t = natural if not types or natural in types else types[0]
    try:
        if t == "String":
            return {"value": str(value)}
        if t == "Boolean":
            truth = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
            return {"expression": "True" if truth else "False"}
        if t in ("Integer", "LongInteger"):
            if float(value) != int(float(value)):
                raise ValueError("not a whole number")
            return {"expression": str(int(float(value)))}
        if t in ("Real", "SingleReal", "Currency"):
            return {"expression": real_text(value)}
        if t in ("Date", "DateTime", "Time"):
            text = str(value)
            if t == "Time" and "T" not in text and "-" not in text:
                d = datetime.datetime.combine(datetime.date(2000, 1, 1), datetime.time.fromisoformat(text))
            else:
                d = datetime.datetime.fromisoformat(text)
            ms = d.microsecond // 1000
            if t == "Date":
                return {"expression": "Date(%d, %d, %d)" % (d.year, d.month, d.day)}
            if t == "Time":
                return {"expression": "Time(%d, %d, %d, %d)" % (d.hour, d.minute, d.second, ms)}
            return {"expression": "DateTime(%d, %d, %d, %d, %d, %d, %d)"
                    % (d.year, d.month, d.day, d.hour, d.minute, d.second, ms)}
        if t == "TimeSpan":
            m = TIMESPAN_RE.match(str(value))
            if not m:
                raise ValueError("not d.hh:mm:ss")
            parts = [int(x or 0) for x in m.groups()[1:5]]
            ms = int(((m.group(6) or "0") + "00")[:3])
            sign = "-" if m.group(1) else ""
            return {"expression": "TimeSpan(%s%d, %s%d, %s%d, %s%d, %s%d)"
                    % (sign, parts[0], sign, parts[1], sign, parts[2], sign, parts[3], sign, ms)}
    except (ValueError, TypeError) as e:
        ctx.unsupported(path, "bind.value %r as %s (%s)" % (value, t, e))
        return {"value": str(value)}
    ctx.unsupported(path, "a %s literal (bind a document property instead)" % t)
    return {"value": str(value)}


def bind(kind, b, types, resolved, path, ctx, ready=()):
    """APP bind of one input. A whole table ("*") gets the column list its tables[] entry declares,
    unless an earlier function that runs at build produces it: then the engine lists the table's own
    columns at bind time (both are explicit lists, InputType Columns)."""
    if b.get("property") is not None:
        return {"property": b["property"]}
    if b.get("expression") is not None:
        return {"expression": str(b["expression"])}
    if "value" in b:
        return literal(b["value"], types, path + ".value", ctx)
    out = {"table": b.get("table")}
    if kind == "column":
        out["column"] = b.get("column")
        return out
    cols = b.get("columns", "*")
    if isinstance(cols, list) and cols:
        out["columns"] = list(cols)
    elif cols in (None, "*") and b.get("table") not in ready:
        declared = declared_columns(resolved, b.get("table"))
        if declared:
            out["columns"] = declared
    return out


def data_functions(resolved, raw, app_dir, ctx):
    out = []
    ready = set()                     # tables produced by earlier functions that run at build
    raws = _raw_list(raw, "dataFunctions")
    for n, d in enumerate(resolved.get("dataFunctions") or []):
        if not isinstance(d, dict):
            continue
        path = "dataFunctions[%d]" % n
        rd = _at(raws, n)
        engine = d.get("engine") or "python"
        if engine != "python":
            ctx.unsupported(path + ".engine", "a '%s' data function" % engine)
        if not blank(d.get("settings")):
            ctx.unsupported(path + ".settings", "data-function settings")
        entry = {"name": d.get("name")}
        if isinstance(rd.get("script"), str) and rd["script"].strip():
            entry["file"] = _rel(app_dir, rd["script"], "datafunctions")
        else:
            entry["code"] = d.get("scriptCode") or ""
        if d.get("description"):
            entry["description"] = d["description"]
        inputs = []
        for k, i in enumerate(d.get("inputs") or []):
            ip = "%s.inputs[%d]" % (path, k)
            b = i.get("bind") if isinstance(i.get("bind"), dict) else {}
            if b.get("limitByFiltering"):
                ctx.unsupported(ip + ".bind.limitByFiltering", "a data-function input limited by filtering")
            if i.get("description"):
                ctx.note("data-function parameter descriptions")
            types = i.get("dataTypes")
            types = [types] if isinstance(types, str) else list(types or [])
            app_bind = bind(i.get("type"), b, types, resolved, ip + ".bind", ctx, ready)
            if b.get("limitByMarking"):
                if "table" in app_bind:
                    app_bind["marking"] = b["limitByMarking"]      # engine feature markedInputs
                else:
                    ctx.unsupported(ip + ".bind.limitByMarking", "a marking limit on a property, "
                                    "expression or literal bind")
            item = [i.get("name"), i.get("type"), app_bind]
            if types:
                item.append(types)
            inputs.append(item)
        entry["in"] = inputs
        outputs = []
        for k, o in enumerate(d.get("outputs") or []):
            target = o.get("target") if isinstance(o.get("target"), dict) else {}
            if o.get("description"):
                ctx.note("data-function parameter descriptions")
            if o.get("type") == "table":
                outputs.append([o.get("name"), "table", target.get("table")])
            elif o.get("type") == "value":
                outputs.append([o.get("name"), "value", target.get("property")])
            else:
                ctx.unsupported("%s.outputs[%d].type" % (path, k), "a '%s' output" % o.get("type"))
        entry["out"] = outputs
        if (d.get("refresh") or "automatic") == "manual":
            entry["refresh"] = "manual"
        if d.get("executeAtBuild") is False:
            entry["run"] = False
        else:
            ready.update(o[2] for o in outputs if o[1] == "table")
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------------------------
def scripts(resolved, raw, app_dir, ctx):
    out = []
    raws = _raw_list(raw, "scripts")
    for n, s in enumerate(resolved.get("scripts") or []):
        if not isinstance(s, dict):
            continue
        rs = _at(raws, n)
        entry = {"name": s.get("name")}
        if isinstance(rs.get("file"), str) and rs["file"].strip():
            entry["file"] = _rel(app_dir, rs["file"], "scripts")
        else:
            entry["code"] = s.get("code") or ""
        if s.get("description"):
            entry["description"] = s["description"]
        params = []
        for p in s.get("parameters") or []:
            item = [p.get("name"), p.get("type") or "String"]
            if p.get("description"):
                item.append(p["description"])
            params.append(item)
        if params:
            entry["params"] = params
        if s.get("transaction") is False:
            entry["transaction"] = False
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------------------
# visualization mods
# ---------------------------------------------------------------------------------------------
def read_manifest(app_dir, project):
    """The parsed mod-manifest.json of a mod project folder (relative to the app), or None."""
    if not isinstance(project, str) or not project.strip():
        return None
    path = os.path.join(str(app_dir), project.strip(), "mod-manifest.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def viz_mods(resolved, app_dir, ctx):
    """APP "vizMods" [[id, project, manifest version], ...]: the listed visualization mods that a mod
    visual uses, in spec order (the version is left out when the manifest has none). Fills
    ctx.viz_manifests {id: parsed mod-manifest.json} for every listed mod whose manifest reads."""
    used = set()
    for page in resolved.get("pages") or []:
        for v in (page.get("visuals") or []) if isinstance(page, dict) else []:
            if isinstance(v, dict) and v.get("type") == "mod":
                used.add(v.get("modId"))
    out = []
    for m in resolved.get("vizMods") or []:
        if not isinstance(m, dict) or not m.get("id") or m["id"] in ctx.viz_manifests:
            continue
        project = m.get("project")
        manifest = read_manifest(app_dir, project)
        if manifest is None:
            continue                     # dxpgen validate reports it; its visuals become unsupported
        ctx.viz_manifests[m["id"]] = manifest
        if m["id"] not in used:
            continue
        entry = [m["id"], _win_rel(project)]
        if isinstance(manifest.get("version"), str) and manifest["version"].strip():
            entry.append(manifest["version"].strip())
        out.append(entry)
    return out


def manifest_files(manifest):
    """The files a mod manifest lists (files, then the icon), each once, as written."""
    out = []
    for name in list((manifest or {}).get("files") or []) + [(manifest or {}).get("icon")]:
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())
    return out


def _win_rel(value):
    return os.path.normpath(value.strip()).replace("/", "\\")


# ---------------------------------------------------------------------------------------------
# text-area controls
# ---------------------------------------------------------------------------------------------
def controls(v, path, ctx):
    """APP visual "controls": {id: marker text}. The builder puts the marker where {{control:<id>}}
    stands; MANUAL-STEPS says which control to insert there by hand."""
    out = {}
    for cid, c in (v.get("controls") or {}).items():
        if isinstance(c, dict):
            out[cid] = _manual.control_marker(cid, c)
    return out
