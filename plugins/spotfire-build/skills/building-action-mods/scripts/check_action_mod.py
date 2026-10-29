"""Check an action mod project before you connect it to Spotfire.

Checks the manifest and the files it names:

  errors    type is not "action"; apiVersion, id, name, version or icon
            missing; script ids or entry points that are not unique or not
            valid; a script file that is missing or does not call
            RegisterEntryPoint(<entryPoint>); an async entry point (Spotfire
            needs a synchronous function); parameter names that are not
            JavaScript identifiers or are reserved (document, application,
            resources); unknown parameter types; enum on a non-String
            parameter; icons that are missing, not well-formed SVG or not
            16 x 16; non-ASCII characters in the manifest or an icon
  warnings  scripts without description or icon (a visual button shows the
            script's icon, so two buttons that must look different need two
            scripts); wrapInTransaction false; optional parameters (an empty
            optional argument stopped an action without an error in Analyst
            15.0, so leave such arguments out of the button instead)

With --schema (action-mods/schema.json of @spotfire/mods-api ~2.5) and the
jsonschema package, the manifest is also validated against the official
schema.

Usage:
  python check_action_mod.py PROJECT_FOLDER [--schema schema.json]
  python check_action_mod.py --self-test
Exit code 1 when any error is found. Standard library only (jsonschema
optional).
"""

import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

PARAM_TYPES = {"Boolean", "Currency", "DataTable", "DataColumn", "Date",
               "DateTime", "Integer", "LongInteger", "Real", "SingleReal",
               "String", "Time", "TimeSpan", "Page", "Visualization",
               "DataViewDefinition"}
RESERVED = {"document", "application", "resources"}
ID_RE = re.compile(r"^[a-zA-Z0-9]+[a-zA-Z0-9-._]*(?<=[a-zA-Z0-9])$")
IDENT_RE = re.compile(r"^[A-Za-z_][0-9A-Za-z_]*$")
ENTRY_RE = re.compile(r"^[$A-Za-z_][0-9A-Za-z_$]*$")
SVG_NS = "{http://www.w3.org/2000/svg}"


def check_icon(folder, icon, errors):
    path = os.path.join(folder, icon)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        svg = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        errors.append("icon %s: %s" % (icon, exc))
        return
    if any(b > 0x7E for b in raw):
        errors.append("icon %s is not ASCII" % icon)
    if svg.tag != SVG_NS + "svg":
        errors.append("icon %s: root element is %s" % (icon, svg.tag))
    if svg.get("viewBox") != "0 0 16 16":
        errors.append("icon %s: viewBox %r, use \"0 0 16 16\""
                      % (icon, svg.get("viewBox")))


def check_project(folder, schema_path=None):
    errors, warnings = [], []
    path = os.path.join(folder, "mod-manifest.json")
    try:
        with open(path, "rb") as f:
            raw = f.read()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        return ["mod-manifest.json: %s" % exc], []
    if any(b > 0x7E for b in raw):
        errors.append("mod-manifest.json is not ASCII")
    if manifest.get("type") != "action":
        errors.append("type is %r; an action mod has type \"action\""
                      % manifest.get("type"))
    for key in ("apiVersion", "version", "name", "id", "icon"):
        if not manifest.get(key):
            errors.append("%s is missing" % key)
    if manifest.get("id") and not ID_RE.match(manifest["id"]):
        errors.append("id %r has characters the schema does not allow"
                      % manifest["id"])
    if manifest.get("icon"):
        check_icon(folder, manifest["icon"], errors)

    ids, entries = set(), set()
    scripts = manifest.get("scripts", []) or []
    if not scripts:
        errors.append("the manifest has no scripts")
    for s in scripts:
        sid = s.get("id", "")
        where = "script %s" % sid
        if not sid or not ID_RE.match(sid):
            errors.append("%s: invalid id" % where)
        if sid in ids:
            errors.append("%s: id used twice" % where)
        ids.add(sid)
        entry = s.get("entryPoint", "")
        if not ENTRY_RE.match(entry):
            errors.append("%s: entryPoint %r is not a JavaScript name"
                          % (where, entry))
        if entry in entries:
            errors.append("%s: entryPoint %s is used by another script"
                          % (where, entry))
        entries.add(entry)
        if not s.get("description"):
            warnings.append("%s has no description" % where)
        if s.get("icon"):
            check_icon(folder, s["icon"], errors)
        else:
            warnings.append("%s has no icon: a visual button shows the "
                            "script's icon" % where)
        if s.get("wrapInTransaction") is False:
            warnings.append("%s: wrapInTransaction false, so one click is "
                            "not one undo step" % where)
        code_path = os.path.join(folder, s.get("file", ""))
        if not s.get("file") or not os.path.isfile(code_path):
            errors.append("%s: file %r is missing" % (where, s.get("file")))
        else:
            with open(code_path, encoding="utf-8") as f:
                code = f.read()
            if not re.search(r"RegisterEntryPoint\(\s*%s\s*\)"
                             % re.escape(entry), code):
                errors.append("%s: %s does not call RegisterEntryPoint(%s)"
                              % (where, s["file"], entry))
            if re.search(r"async\s+function\s+%s\b" % re.escape(entry), code) \
                    or re.search(r"\b%s\s*=\s*async\b" % re.escape(entry),
                                 code):
                errors.append("%s: the entry point is async; Spotfire needs "
                              "a synchronous function" % where)
        names = set()
        for p in s.get("parameters", []) or []:
            name = p.get("name", "")
            pwhere = "%s parameter %s" % (where, name)
            if not IDENT_RE.match(name):
                errors.append("%s: not a JavaScript identifier" % pwhere)
            if name.lower() in RESERVED:
                errors.append("%s: the name is reserved" % pwhere)
            if name in names:
                errors.append("%s: declared twice" % pwhere)
            names.add(name)
            if p.get("type") not in PARAM_TYPES:
                errors.append("%s: type %r" % (pwhere, p.get("type")))
            if "enum" in p and p.get("type") != "String":
                errors.append("%s: enum is for String parameters" % pwhere)
            if p.get("optional"):
                warnings.append("%s is optional: leave it out of a button "
                                "rather than passing an empty value" % pwhere)

    if schema_path:
        try:
            import jsonschema
        except ImportError:
            warnings.append("jsonschema is not installed: schema check "
                            "skipped")
        else:
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)
            for err in sorted(jsonschema.Draft7Validator(schema)
                              .iter_errors(manifest), key=str):
                where = "/".join(str(x) for x in err.absolute_path)
                errors.append("schema: %s: %s" % (where, err.message))
    return errors, warnings


def self_test():
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(here, "..", "assets", "pump-actions")
    errors, warnings = check_project(example)
    assert not errors, errors
    with tempfile.TemporaryDirectory() as folder:
        work = os.path.join(folder, "mod")
        shutil.copytree(example, work)
        path = os.path.join(work, "mod-manifest.json")
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["scripts"][1]["entryPoint"] = "nextAsset"
        manifest["scripts"][2]["parameters"].append(
            {"name": "document", "type": "Number"})
        manifest["scripts"][3]["parameters"][0]["enum"] = ["a"]
        manifest["scripts"][3]["parameters"][0]["type"] = "Integer"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        with open(os.path.join(work, "icons", "go-to-page.svg"), "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" '
                    'viewBox="0 0 24 24"/>')
        errors, _ = check_project(work)
        text = " | ".join(errors)
        for expected in ("entryPoint nextAsset is used by another script",
                         "does not call RegisterEntryPoint(nextAsset)",
                         "the name is reserved", "type 'Number'",
                         "enum is for String", "viewBox '0 0 24 24'"):
            assert expected in text, (expected, text)
    print("self-test passed")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--self-test":
        return self_test()
    schema = None
    if "--schema" in argv:
        i = argv.index("--schema")
        schema = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    errors, warnings = check_project(argv[0], schema)
    for w in warnings:
        print("  WARNING " + w)
    for e in errors:
        print("  ERROR " + e)
    print("%d error(s), %d warning(s)" % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
