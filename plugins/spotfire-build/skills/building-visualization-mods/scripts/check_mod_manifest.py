"""Check a visualization mod project before you connect it to Spotfire.

Checks the rules that make Spotfire refuse a mod or misread its data:

  errors    apiVersion missing; for apiVersion 1.x: a top-level "type"
            ("Could not read mod" in clients that only know 1.x), a string
            allowNonAggregatingMeasures (1.x takes true or false), legendItem
            keys other than defaultVisibility; for 2.x: type other than
            "visualization"; files or the icon listed but missing; property
            types other than string, integer, double, boolean; duplicate
            axis, property or layer names; index.html without the
            spotfire-loader script
  warnings  axes without a propertyControl title, continuous axes that
            allow non-aggregating measures (tell users to set the
            aggregation to None), files in the folder that the manifest does
            not list

With --schema (the visualization-mods/schema.json of the @spotfire/mods-api
version that matches your apiVersion) and the jsonschema package, the
manifest is also validated against the official schema.

Usage:
  python check_mod_manifest.py PROJECT_FOLDER [--schema schema.json]
  python check_mod_manifest.py --self-test
Exit code 1 when any error is found.
"""

import json
import os
import shutil
import sys
import tempfile

PROPERTY_TYPES = {"string", "integer", "double", "boolean"}
SKIP = {"node_modules", ".git", "test-harness.js", "package.json",
        "package-lock.json", "README.md", "tsconfig.json"}


def iter_axes(manifest):
    """(where, axis) for the main view and every layer type."""
    view = manifest.get("dataViewDefinition", {}) or {}
    for axis in view.get("axes", []) or []:
        yield "dataViewDefinition", axis
    if view.get("colorAxis"):
        yield "dataViewDefinition.colorAxis", dict(view["colorAxis"],
                                                   name="Color")
    for layer in manifest.get("layers", []) or []:
        lview = layer.get("dataViewDefinition", {}) or {}
        for axis in lview.get("axes", []) or []:
            yield "layer " + str(layer.get("type")), axis


def check_project(folder, schema_path=None):
    errors, warnings = [], []
    path = os.path.join(folder, "mod-manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as exc:
        return ["mod-manifest.json: %s" % exc], []
    api = str(manifest.get("apiVersion", ""))
    if not api:
        errors.append("apiVersion is missing")
    major = api.split(".")[0]
    if major == "1":
        if "type" in manifest:
            errors.append("apiVersion %s with a top-level \"type\": clients "
                          "that only read 1.x refuse the mod; remove it" % api)
    elif major and manifest.get("type", "visualization") != "visualization":
        errors.append("type is %r; a visualization mod has type "
                      "\"visualization\"" % manifest.get("type"))
    for key in ("id", "name", "version"):
        if not manifest.get(key):
            errors.append("%s is missing" % key)

    seen = {}
    for where, axis in iter_axes(manifest):
        name = axis.get("name")
        key = (where, name)
        if key in seen:
            errors.append("%s: axis %s declared twice" % (where, name))
        seen[key] = True
        anm = axis.get("allowNonAggregatingMeasures")
        if major == "1" and anm is not None and not isinstance(anm, bool):
            errors.append("%s axis %s: allowNonAggregatingMeasures %r; 1.x "
                          "takes true or false" % (where, name, anm))
        if anm not in (None, False):
            warnings.append("%s axis %s allows non-aggregating measures: "
                            "tell users to set its aggregation to None, "
                            "Spotfire puts Sum() on a dropped column"
                            % (where, name))
        legend = axis.get("legendItem") or {}
        extra = set(legend) - {"defaultVisibility"}
        if major == "1" and extra:
            errors.append("%s axis %s: legendItem keys %s are not in 1.x"
                          % (where, name, ", ".join(sorted(extra))))
        if not (axis.get("propertyControl") or {}).get("title") and \
                where != "dataViewDefinition.colorAxis":
            warnings.append("%s axis %s has no propertyControl title"
                            % (where, name))

    def check_props(where, props):
        names = set()
        for p in props or []:
            if p.get("type") not in PROPERTY_TYPES:
                errors.append("%s property %s: type %r" % (
                    where, p.get("name"), p.get("type")))
            if p.get("name") in names:
                errors.append("%s property %s declared twice"
                              % (where, p.get("name")))
            names.add(p.get("name"))

    check_props("mod", manifest.get("properties"))
    layer_types = set()
    for layer in manifest.get("layers", []) or []:
        if layer.get("type") in layer_types:
            errors.append("layer type %s declared twice" % layer.get("type"))
        layer_types.add(layer.get("type"))
        check_props("layer " + str(layer.get("type")), layer.get("properties"))

    listed = list(manifest.get("files", []) or [])
    for name in listed + ([manifest["icon"]] if manifest.get("icon") else []):
        if not os.path.exists(os.path.join(folder, name)):
            errors.append("%s is listed but not in the folder" % name)
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full) and name not in SKIP and \
                name != "mod-manifest.json" and name not in listed and \
                name != manifest.get("icon"):
            warnings.append("%s is in the folder but not in \"files\": "
                            "Spotfire does not store it with the mod" % name)
    index = os.path.join(folder, "index.html")
    if os.path.exists(index):
        with open(index, encoding="utf-8") as f:
            if 'id="spotfire-loader"' not in f.read():
                errors.append("index.html has no <script id=\"spotfire-"
                              "loader\">: copy it from an official example")

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
                where = "/".join(str(p) for p in err.absolute_path)
                errors.append("schema: %s: %s" % (where, err.message))
    return errors, warnings


def self_test():
    here = os.path.dirname(os.path.abspath(__file__))
    demo = os.path.join(here, "..", "assets", "demo-layers", "src")
    errors, warnings = check_project(demo)
    assert not errors, errors
    assert any("aggregation to None" in w for w in warnings), warnings
    with tempfile.TemporaryDirectory() as folder:
        for name in os.listdir(demo):
            shutil.copy(os.path.join(demo, name), folder)
        path = os.path.join(folder, "mod-manifest.json")
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["apiVersion"] = "1.3"
        manifest["properties"].append({"name": "heading", "type": "text"})
        manifest["files"].append("missing.js")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        errors, _ = check_project(folder)
        text = " | ".join(errors)
        for expected in ("top-level \"type\"", "takes true or false",
                         "type 'text'", "declared twice",
                         "missing.js is listed"):
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
