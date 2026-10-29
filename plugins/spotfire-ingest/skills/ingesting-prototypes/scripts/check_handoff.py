"""Check the hand-off files of an app folder before the build skill reads them.

Reads app-brief.md, logic-spec.md and spec.json in an app folder and reports what
the build would trip over: missing sections, KPIs that point at no calculation,
names that break the naming standard, bindings whose names differ, layout entries
that point at no visual, data files that do not exist, spec fields the standard
engine of the building-spotfire-dxps skill does not build, and open questions that
block the build.

Usage:
    python check_handoff.py <app folder> [--build-skill <folder>]

--build-skill names the folder of the building-spotfire-dxps skill; the check then
also runs its "dxpgen.py validate" on the draft and reports its errors and warnings.

Exit code 1 when an error is found. Warnings do not fail the check.
Standard library only.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BRIEF_SECTIONS = ["Business problem", "Users", "Decisions the app supports", "KPIs",
                  "Inputs", "Outputs", "Data sources", "Refresh cadence",
                  "Out of scope", "Open questions"]
ENTRY_FIELDS = ["Equation", "Output", "Implemented as", "Status"]
PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*(\.[A-Za-z0-9]+)*$")
UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*$")
BUILTIN_PROPS = {"Description", "Keywords", "MaxMissingTimeParts", "FiscalYearOffset",
                 "AllowWebPlayerResume", "PublicBookmarkCreation",
                 "PrivateBookmarkCreation"}

# What the standard engine of the building-spotfire-dxps skill builds (see
# references/spec-draft.md). Anything else needs its slim tier.
VISUAL_COMMON = {"id", "type", "title", "showTitle", "description", "table", "marking",
                 "legend", "limitByMarkings", "emptyMarkingBehavior", "useFiltering",
                 "settings", "actionTriggers"}
CHART_KEYS = {"colorBy", "coloring", "fittingModels", "limitExpression", "referenceLayers",
              "trellis", "x", "xScale", "y", "yScale", "yFormat", "axisFont",
              "axisTitleFont", "legendFont"}
VISUAL_KEYS = {
    "lineChart": CHART_KEYS | {"lineWidth"},
    "barChart": CHART_KEYS | {"orientation", "sort", "stack"},
    "scatterPlot": CHART_KEYS | {"labelBy", "labels", "lineBy", "markerSize", "shape",
                                 "shapeBy", "sizeBy"},
    "table": {"coloring", "columns", "limitExpression", "widths", "negatives", "font",
              "headerFont", "headerBold"},
    "crossTable": {"coloring", "columns", "measures", "rows", "totals", "negatives", "font",
                   "headerFont", "headerBold", "cellWidth", "rowHeaderWidth"},
    "kpiChart": {"coloring", "kpis", "limitExpression", "baseFont", "minTilesPerRow",
                 "minVisibleTiles", "emptyText", "tile"},
    "map": {"autoZoom", "coloring", "extent", "interactiveLayer", "layers",
            "limitExpression"},
    "mod": {"axes", "layers", "limitExpression", "modId", "properties"},
    "textArea": {"controls", "html", "js"},
}
REFERENCE_KINDS = {"horizontalLine", "verticalLine"}
SLIM_ONLY = "is not built by the standard engine of building-spotfire-dxps (slim tier only)"


def blank(value):
    return value is None or value == "" or value == [] or value == {}


def norm(text):
    """Lower-case letters and digits only, for loose name matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sections(markdown):
    """Return {heading text: body} for the '## ' headings of a markdown file."""
    found, current, lines = {}, None, []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None:
                found[current] = "\n".join(lines)
            current, lines = line[3:].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        found[current] = "\n".join(lines)
    return found


def table_rows(body):
    """Return the data rows of the first markdown table in a section body."""
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, text):
        self.errors.append(text)

    def warn(self, text):
        self.warnings.append(text)


def check_brief(path, report, logic_ids):
    text = path.read_text(encoding="utf-8")
    found = sections(text)
    for name in BRIEF_SECTIONS:
        if name not in found:
            report.error(f"app-brief.md: section '## {name}' is missing")
    if not re.search(r"^Status:", text, re.M):
        report.warn("app-brief.md: no 'Status:' line")
    for row in table_rows(found.get("KPIs", "")):
        if len(row) < 2 or not row[0]:
            continue
        ids = re.findall(r"L\d+", row[1])
        if not ids:
            report.error(f"app-brief.md: KPI '{row[0]}' names no Logic Spec ID")
        for lid in ids:
            if lid not in logic_ids:
                report.error(f"app-brief.md: KPI '{row[0]}' refers to {lid}, "
                             "which logic-spec.md does not define")
    for row in table_rows(found.get("Open questions", "")):
        if len(row) >= 5 and row[2].lower().startswith(("yes", "blocking", "true")) \
                and not row[4]:
            report.warn(f"app-brief.md: blocking question {row[0]} has no answer; "
                        "the build waits for it")
    inputs = [row[0] for row in table_rows(found.get("Inputs", "")) if row and row[0]]
    outputs = table_rows(found.get("Outputs", ""))
    for row in outputs:
        if len(row) >= 3 and row[0] and not row[2]:
            report.error(f"app-brief.md: output '{row[0]}' names no page")
    return inputs, [row[2] for row in outputs if len(row) >= 3 and row[2]]


def check_logic(path, report):
    text = path.read_text(encoding="utf-8")
    if "## Conventions" not in text:
        report.error("logic-spec.md: section '## Conventions' is missing")
    if not re.search(r"tolerance", text, re.I):
        report.warn("logic-spec.md: no reconciliation tolerance stated in Conventions")
    entries = re.split(r"^### ", text, flags=re.M)[1:]
    ids, functions = [], []
    for entry in entries:
        head = entry.splitlines()[0].strip()
        match = re.match(r"(L\d+)\b", head)
        if not match:
            report.error(f"logic-spec.md: heading '### {head}' does not start with an ID")
            continue
        lid = match.group(1)
        if lid in ids:
            report.error(f"logic-spec.md: {lid} is used twice")
        ids.append(lid)
        for field in ENTRY_FIELDS:
            if not re.search(rf"^- {field}:", entry, re.M):
                report.error(f"logic-spec.md: {lid} has no '- {field}:' line")
        status = re.search(r"^- Status:\s*(\w+)", entry, re.M)
        if status and status.group(1).lower() == "inferred":
            report.warn(f"logic-spec.md: {lid} is inferred; the owner confirms it "
                        "before the build")
        impl = re.search(r"^- Implemented as:\s*data function\s*`([^`]+)`", entry, re.M)
        if impl:
            functions.append((lid, impl.group(1)))
    if not ids:
        report.error("logic-spec.md: no calculation entries ('### L01 ...')")
    return set(ids), functions


def walk_layout(node, out):
    if isinstance(node, dict):
        if "visual" in node:
            out.append(node["visual"])
        for key in ("row", "column"):
            for item in node.get(key, []) or []:
                walk_layout(item, out)


def check_data_and_engine(spec, report, folder):
    """Data files, data function table columns, filter layouts, value output types and
    the fields the standard engine of building-spotfire-dxps builds."""
    for key in ("relations", "filteringSchemes"):
        if not blank(spec.get(key)):
            report.error(f"spec.json: {key} {SLIM_ONLY}")
    declared = {}
    for n, table in enumerate(spec.get("tables", [])):
        where = f"spec.json: tables[{n}] ({table.get('name')})"
        source = table.get("source") or {}
        kind = source.get("type")
        if kind in ("csv", "sbdf"):
            path = source.get("path")
            if not path or not (folder / path).exists():
                report.error(f"{where}: data file {path} does not exist; ship it in data/")
        elif kind != "dataFunction":
            report.error(f"{where}: source type '{kind}' {SLIM_ONLY}")
        for key in ("calculatedColumns", "hierarchies", "settings"):
            if not blank(table.get(key)):
                report.error(f"{where}: {key} {SLIM_ONLY}; compute such columns in the "
                             "data function that writes the table")
        if table.get("embed") is False:
            report.error(f"{where}: a linked table {SLIM_ONLY}")
        for cname, cspec in (table.get("columns") or {}).items():
            if isinstance(cspec, dict) and not blank(cspec.get("settings")):
                report.error(f"{where}: column settings of '{cname}' {SLIM_ONLY}")
        if kind == "dataFunction":
            declared[table.get("name")] = set(table.get("columns") or {})
    layouts = [("filterPanelLayout", spec.get("filterPanelLayout"))]
    layouts += [(f"pages[{n}].filters", page.get("filters"))
                for n, page in enumerate(spec.get("pages", []))]
    for where, layout in layouts:
        if not isinstance(layout, dict):
            continue
        for item in layout.get("tables", []):
            name = item.get("table")
            columns = item.get("columns")
            listed = [] if columns in (None, "*") else list(columns)
            for group in item.get("subGroups") or []:
                listed += list(group.get("columns") or [])
            if not listed and columns != "*":
                report.error(f"spec.json: {where}: table {name} shows no filter; list its "
                             "columns or leave the table out")
            if name in declared:
                for column in listed:
                    if column not in declared[name]:
                        report.error(f"spec.json: {where}: column '{column}' of data function "
                                     f"table {name} is not declared in its tables[] columns")
    props = {p.get("name"): p for p in spec.get("properties", [])}
    for func in spec.get("dataFunctions", []):
        name = func.get("name")
        if func.get("engine", "python") != "python":
            report.error(f"spec.json: data function '{name}': engine "
                         f"'{func.get('engine')}' {SLIM_ONLY}")
        for item in func.get("inputs", []):
            if (item.get("bind") or {}).get("limitByFiltering"):
                report.error(f"spec.json: data function '{name}': limitByFiltering {SLIM_ONLY}")
        for item in func.get("outputs", []):
            target = (item.get("target") or {}).get("property")
            if target in props and props[target].get("type") == "Integer":
                report.warn(f"spec.json: property '{target}' is Integer, but a Python int "
                            "exports as LongInteger; declare it LongInteger")
    for n, page in enumerate(spec.get("pages", [])):
        if page.get("filteringScheme"):
            report.error(f"spec.json: pages[{n}].filteringScheme {SLIM_ONLY}")
        for k, visual in enumerate(page.get("visuals", [])):
            where = f"spec.json: pages[{n}].visuals[{k}] ({visual.get('id')})"
            vtype = visual.get("type")
            allowed = VISUAL_KEYS.get(vtype)
            if allowed is None:
                report.error(f"{where}: visual type '{vtype}' {SLIM_ONLY}; use the substitute "
                             "in the mapping reference")
                continue
            for key, value in visual.items():
                if key in VISUAL_COMMON or key in allowed or blank(value):
                    continue
                if key == "emptyMarkingBehavior" or (key == "useFiltering" and value is True):
                    continue
                report.error(f"{where}: '{key}' on a {vtype} {SLIM_ONLY}")
            if visual.get("useFiltering") is False and vtype != "mod":
                report.error(f"{where}: useFiltering false {SLIM_ONLY}")
            for layer in visual.get("referenceLayers") or []:
                if layer.get("kind") not in REFERENCE_KINDS:
                    report.error(f"{where}: a '{layer.get('kind')}' reference layer {SLIM_ONLY}; "
                                 "draw a band as two series or two reference lines")
                elif layer.get("table") is not None or not blank(layer.get("settings")):
                    report.error(f"{where}: reference-line table or settings {SLIM_ONLY}")


def run_build_validate(folder, build_skill, report):
    """Run dxpgen.py validate of the building-spotfire-dxps skill on the app folder."""
    script = (Path(build_skill) / "scripts" / "dxpgen.py").resolve()
    if not script.exists():
        report.error(f"--build-skill: {script} does not exist")
        return
    proc = subprocess.run([sys.executable, "-B", str(script), "validate", str(folder)],
                          capture_output=True, text=True, cwd=str(script.parent.parent))
    found = False
    for line in (proc.stdout + proc.stderr).splitlines():
        match = re.match(r"\s+([EW])\d+\.\s+(.*)$", line)
        if match:
            found = True
            text = f"dxpgen validate: {match.group(2)}"
            (report.error if match.group(1) == "E" else report.warn)(text)
        elif line.startswith("Result:"):
            print(f"dxpgen validate: {line[len('Result:'):].strip()}")
    if proc.returncode not in (0, 1) or (proc.returncode == 1 and not found):
        report.error(f"dxpgen validate exited with code {proc.returncode}: "
                     f"{(proc.stderr or proc.stdout).strip()[:300]}")


def check_spec(path, report, folder, brief_inputs, brief_pages, logic_functions):
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        report.error(f"spec.json: not valid JSON ({exc})")
        return
    if spec.get("specVersion") != 1:
        report.error("spec.json: specVersion must be 1")
    if not (spec.get("app") or {}).get("name"):
        report.error("spec.json: app.name is missing")
    props = {}
    for prop in spec.get("properties", []):
        name = prop.get("name", "")
        if name.lower() in {p.lower() for p in props}:
            report.error(f"spec.json: property '{name}' differs from another only in case")
        props[name] = prop
        if name not in BUILTIN_PROPS and not PASCAL.match(name):
            report.error(f"spec.json: property '{name}' is not PascalCase")
        if prop.get("type") == "Real" and isinstance(prop.get("default"), int) \
                and not isinstance(prop.get("default"), bool):
            report.error(f"spec.json: Real property '{name}' has an integer default "
                         "(write 72.0, not 72)")
    check_data_and_engine(spec, report, folder)
    tables = {t.get("name", "") for t in spec.get("tables", [])}
    for name in tables:
        if not UPPER_SNAKE.match(name):
            report.error(f"spec.json: table '{name}' is not UPPER_SNAKE_CASE")
    functions = {f.get("name", ""): f for f in spec.get("dataFunctions", [])}
    for name, func in functions.items():
        script = func.get("script")
        if script and not (folder / script).exists():
            report.warn(f"spec.json: data function '{name}': {script} does not exist yet")
        for item in func.get("inputs", []):
            bound = (item.get("bind") or {}).get("property")
            if bound and item.get("name") != bound:
                report.error(f"spec.json: data function '{name}': input '{item.get('name')}'"
                             f" is bound to property '{bound}'; the names must be equal")
            if bound and bound not in props:
                report.error(f"spec.json: data function '{name}' reads property "
                             f"'{bound}', which is not in properties")
        for item in func.get("outputs", []):
            target = (item.get("target") or {}).get("property")
            if target and target not in props:
                report.error(f"spec.json: data function '{name}' writes property "
                             f"'{target}', which is not in properties")
            if target and item.get("name") != target:
                report.error(f"spec.json: data function '{name}': output "
                             f"'{item.get('name')}' targets '{target}'; the names must be equal")
    for lid, fname in logic_functions:
        if fname not in functions:
            report.warn(f"logic-spec.md: {lid} is implemented as data function '{fname}', "
                        "which spec.json does not define")
    titles, visual_ids = set(), set()
    for page in spec.get("pages", []):
        title = page.get("title", "")
        if title.lower() in titles:
            report.error(f"spec.json: page title '{title}' is used twice")
        titles.add(title.lower())
        ids = []
        for visual in page.get("visuals", []):
            vid = visual.get("id", "")
            if vid in visual_ids:
                report.error(f"spec.json: visual id '{vid}' is used twice")
            visual_ids.add(vid)
            ids.append(vid)
            if not CAMEL.match(vid):
                report.error(f"spec.json: visual id '{vid}' is not camelCase")
            for cid, control in (visual.get("controls") or {}).items():
                prop = control.get("property")
                if prop and prop not in props and prop not in BUILTIN_PROPS:
                    report.error(f"spec.json: control '{cid}' is bound to property "
                                 f"'{prop}', which is not in properties")
            html = visual.get("html")
            if html and not html.lstrip().startswith("<"):
                html_path = folder / html
                if html_path.exists():
                    text = html_path.read_text(encoding="utf-8")
                    for cid in visual.get("controls") or {}:
                        if text.count("{{control:%s}}" % cid) != 1:
                            report.error(f"spec.json: control '{cid}' must be placed exactly "
                                         f"once in {html}")
                else:
                    report.warn(f"spec.json: {html} does not exist yet")
        placed = []
        walk_layout(page.get("layout") or {}, placed)
        if len(ids) > 1 or placed:
            for vid in ids:
                if placed.count(vid) != 1:
                    report.error(f"spec.json: page '{title}': visual '{vid}' must appear "
                                 "exactly once in the layout")
            for vid in placed:
                if vid not in ids:
                    report.error(f"spec.json: page '{title}': layout names unknown "
                                 f"visual '{vid}'")
    known = {norm(p) for p in props} | {norm(p.get("description", "")) for p in
                                         props.values()}
    for name in brief_inputs:
        key = norm(re.sub(r"\(.*?\)", "", name))
        if key and key not in known and not any(key in k for k in known if k):
            report.warn(f"app-brief.md: input '{name}' has no matching property in spec.json")
    for page in brief_pages:
        if page.lower() not in titles and not page.lower().startswith(("n/a", "none")):
            report.warn(f"app-brief.md: output page '{page}' is not a page in spec.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", help="app folder ($DXP_WORKSPACE/apps/<AppSlug>)")
    parser.add_argument("--build-skill", help="folder of the building-spotfire-dxps skill: "
                        "also run its dxpgen.py validate on the draft")
    args = parser.parse_args()
    folder = Path(args.folder).resolve()
    report = Report()
    logic_ids, logic_functions = set(), []
    brief_inputs, brief_pages = [], []
    logic = folder / "logic-spec.md"
    brief = folder / "app-brief.md"
    spec = folder / "spec.json"
    if logic.exists():
        logic_ids, logic_functions = check_logic(logic, report)
    else:
        report.error("logic-spec.md is missing")
    if brief.exists():
        brief_inputs, brief_pages = check_brief(brief, report, logic_ids)
    else:
        report.error("app-brief.md is missing")
    if spec.exists():
        check_spec(spec, report, folder, brief_inputs, brief_pages, logic_functions)
    else:
        report.error("spec.json is missing")
    if not (folder / "ingest" / "mapping-table.md").exists():
        report.warn("ingest/mapping-table.md is missing")
    if args.build_skill and spec.exists():
        run_build_validate(folder, args.build_skill, report)
    for text in report.warnings:
        print(f"WARNING {text}")
    for text in report.errors:
        print(f"ERROR {text}")
    print(f"{len(report.errors)} errors, {len(report.warnings)} warnings")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
