"""Stage 4: write the workbook dossier as plain HTML for the owner's review.

Reads inventory.json, structure.json and issues.json from an ingest folder, plus
meaning.json when it exists (goal, users, decisions, manual steps, the meaning
and equation of each block, extra questions; written during stage 4). Writes
dossier.html: summary, goal and users, sheets and their flow, inputs, every
calculation block with its formula and meaning, outputs, issues, questions for
the owner, workbook features, and the checkpoint the owner signs.

Usage:
    python dossier.py --ingest <ingest folder> [--out dossier.html]

Standard library only.
"""

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

CSS = """
body{font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#000;margin:24px;max-width:1200px}
h1{font-size:22px}h2{font-size:18px;border-bottom:1px solid #000;margin-top:28px}
h3{font-size:15px;margin-top:18px}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#eee}code{font-family:Consolas,monospace;font-size:12px}
.high{font-weight:bold}.muted{color:#555}.box{border:2px solid #000;padding:10px}
"""


def e(value):
    return html.escape("" if value is None else str(value))


def code(value):
    return f"<code>{e(value)}</code>" if value else ""


def table(headers, rows):
    out = ["<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in headers) + "</tr>"]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def load(folder, name):
    path = Path(folder) / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fmt(value):
    if isinstance(value, float):
        return f"{value:.6g}"
    return value


def questions(issues, meaning):
    out = []
    for q in meaning.get("questions", []):
        out.append((q.get("question", ""), q.get("blocking", False), q.get("about", "")))
    seen = set()
    for item in issues:
        if item["severity"] == "info":
            continue
        key = (item["type"], item.get("block") or item["range"])
        if key in seen:
            continue
        seen.add(key)
        where = f"{item['sheet']}!{item['range']}"
        out.append((f"{item['id']} ({where}): {item['question']}",
                    item["severity"] == "high", where))
    return out


def render(folder):
    inv = load(folder, "inventory.json")
    st = load(folder, "structure.json")
    iss = load(folder, "issues.json")
    meaning = load(folder, "meaning.json")
    blocks = st.get("blocks", [])
    bmeaning = meaning.get("blocks", {})
    issues = iss.get("issues", [])
    name = inv.get("file", {}).get("name") or st.get("workbook", "workbook")
    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Workbook dossier: "
             f"{e(name)}</title><style>{CSS}</style></head><body>",
             f"<h1>Workbook dossier: {e(meaning.get('app') or name)}</h1>",
             f"<p class='muted'>Source: {e(name)} (sha256 "
             f"{e(inv.get('file', {}).get('sha256', '')[:12])}). Written "
             f"{dt.date.today().isoformat()}. Status: "
             f"{e(meaning.get('status', 'draft for owner review'))}.</p>"]

    totals = inv.get("totals", {})
    roles = st.get("summary", {}).get("roles", {})
    counts = iss.get("counts", {})
    parts.append("<h2>1. Summary</h2>")
    parts.append(table(["Item", "Count"], [
        ["Sheets", totals.get("sheets", "")], ["Formula cells", totals.get("formulas", "")],
        ["Blocks (filled-down formulas count once)", st.get("summary", {}).get("blocks", "")],
        ["Blocks by role", e(", ".join(f"{k} {v}" for k, v in sorted(roles.items())))],
        ["Issues", e(", ".join(f"{v} {k}" for k, v in counts.items()))],
        ["Charts, pivots, tables", f"{totals.get('charts', 0)}, {totals.get('pivots', 0)}, "
                                   f"{totals.get('tables', 0)}"],
        ["External links", len(inv.get("externalLinks", []))],
        ["VBA", "yes" if inv.get("vbaPresent") else "no"],
        ["Calculation", e(f"{inv.get('calculation', {}).get('mode', 'auto')}, iterative "
                          f"{'on' if inv.get('calculation', {}).get('iterative') else 'off'}")]]))

    parts.append("<h2>2. Goal, users and decisions</h2>")
    if meaning.get("goal"):
        parts.append(f"<p>{e(meaning['goal'])}</p>")
    else:
        parts.append("<p class='muted'>To be written from the owner interview "
                     "(meaning.json).</p>")
    if meaning.get("users"):
        parts.append(table(["Role", "What they do with the workbook"],
                           [[e(u.get("role")), e(u.get("use"))] for u in meaning["users"]]))
    if meaning.get("decisions"):
        parts.append("<ol>" + "".join(f"<li>{e(d)}</li>" for d in meaning["decisions"])
                     + "</ol>")
    if meaning.get("manualSteps"):
        parts.append("<h3>Manual steps today</h3><ol>" +
                     "".join(f"<li>{e(s)}</li>" for s in meaning["manualSteps"]) + "</ol>")

    parts.append("<h2>3. Sheets</h2>")
    parts.append(table(["Sheet", "State", "Used range", "Formulas", "Values", "Blocks"], [
        [e(s["name"]), e(s["state"]), e(s.get("usedRange")), s.get("formulas", ""),
         s.get("numbers", ""), next((x["blocks"] for x in st.get("sheets", [])
                                     if x["name"] == s["name"]), "")]
        for s in inv.get("sheets", [])]))
    if st.get("sheetFlow"):
        parts.append("<h3>How the sheets feed each other</h3>")
        parts.append(table(["From", "To", "Block links"],
                           [[e(f["from"]), e(f["to"]), f["links"]] for f in st["sheetFlow"]]))
    for fam in st.get("templateFamilies", []):
        parts.append(f"<p>Sheets copied from one template: {e(', '.join(fam['sheets']))} "
                     f"(similarity {fam['similarity']}). Differences are listed under "
                     "issues.</p>")

    parts.append("<h2>4. Inputs and parameters</h2>")
    rows = []
    for b in blocks:
        listed = ("input", "parameter", "lookup", "raw data", "override")
        if b["role"] not in listed and not b.get("externalOnly"):
            continue
        m = bmeaning.get(b["id"], {})
        role = "input (external link)" if b.get("externalOnly") else b["role"]
        if b.get("inputCells"):
            for item in b["inputCells"]:
                cm = bmeaning.get(f"{b['sheet']}!{item['cell']}", {})
                rows.append([b["id"], e(f"{b['sheet']}!{item['cell']}"), e(role),
                             e(cm.get("name") or item.get("label")),
                             e(cm.get("unit") or item.get("unit")), e(fmt(item.get("value"))),
                             e(cm.get("meaning") or m.get("meaning"))])
        else:
            rows.append([b["id"], e(f"{b['sheet']}!{b['range']}"), e(role),
                         e(m.get("name") or b.get("label")), e(m.get("unit") or b.get("unit")),
                         e(fmt(b.get("value", f"{b['cells']} cells"))), e(m.get("meaning"))])
    parts.append(table(["Block", "Where", "Role", "Label", "Unit", "Stored value",
                        "Meaning"], rows) if rows else "<p>None found.</p>")

    parts.append("<h2>5. Calculation blocks</h2>")
    parts.append("<p class='muted'>One row per block: a block is a range whose cells hold "
                 "the same formula in R1C1 form (a filled-down column counts once).</p>")
    for sheet in st.get("sheets", []):
        rows = []
        for b in blocks:
            if b["sheet"] != sheet["name"] or b["kind"] != "formula":
                continue
            m = bmeaning.get(b["id"], {})
            exc = "; ".join(f"{x['cell']} ({x['kind']})" for x in b.get("exceptions", []))
            rows.append([b["id"], e(b["range"]), b["cells"], e(b["role"]),
                         e(m.get("name") or b.get("label")), e(m.get("unit") or b.get("unit")),
                         code(b.get("formula")) + "<br>" + code(b.get("r1c1")),
                         e(m.get("equation")) + ("<br>" + e(m.get("meaning"))
                                                 if m.get("meaning") else ""),
                         e(", ".join(b.get("precedents", [])[:12])),
                         e(exc) + e("; ".join(b.get("dynamic", [])[:2]))])
        if rows:
            parts.append(f"<h3>{e(sheet['name'])}</h3>")
            parts.append(table(["Block", "Range", "Cells", "Role", "Label", "Unit",
                                "Formula (first cell, R1C1)", "Equation and meaning",
                                "Reads", "Exceptions and notes"], rows))

    parts.append("<h2>6. Outputs</h2>")
    rows = [[b["id"], e(f"{b['sheet']}!{b['range']}"), e(b.get("label")), e(b.get("unit")),
             code(b.get("formula"))] for b in blocks if b["role"] == "output"]
    parts.append(table(["Block", "Where", "Label", "Unit", "Formula"], rows)
                 if rows else "<p>None found.</p>")

    parts.append("<h2>7. Issues</h2>")
    parts.append(table(["ID", "Severity", "Type", "Where", "Finding"], [
        [i["id"], f"<span class='{e(i['severity'])}'>{e(i['severity'])}</span>", e(i["type"]),
         e(f"{i['sheet']}!{i['range']}"), e(i["message"])] for i in issues])
        if issues else "<p>No issues found.</p>")

    parts.append("<h2>8. Questions for the owner</h2>")
    qs = questions(issues, meaning)
    parts.append(table(["#", "Question", "Blocking", "Answer"],
                       [[f"Q{n}", e(q), "yes" if b else "no", ""]
                        for n, (q, b, _) in enumerate(qs, 1)]) if qs else "<p>None.</p>")

    parts.append("<h2>9. Workbook features</h2>")
    names = [n for n in inv.get("definedNames", []) if n["kind"] != "builtin"]
    if names:
        parts.append("<h3>Named ranges</h3>" + table(
            ["Name", "Scope", "Refers to", "Kind", "Hidden"],
            [[e(n["name"]), e(n["scope"] or "workbook"), code(n["refersTo"]), e(n["kind"]),
              "yes" if n["hidden"] else ""] for n in names]))
    dv, cf, charts, pivots, controls = [], [], [], [], []
    for s in inv.get("sheets", []):
        for v in s.get("dataValidations", []):
            dv.append([e(s["name"]), e(v["sqref"]), e(v["type"]), code(v["formula1"])])
        for c in s.get("conditionalFormats", []):
            cf.append([e(s["name"]), e(c["sqref"]), e(c["type"]), e(c.get("operator")),
                       code(", ".join(c.get("formulas", [])))])
        for c in s.get("charts", []):
            charts.append([e(s["name"]), e(c.get("title")), e(", ".join(c.get("types", []))),
                           code("; ".join(v for ser in c.get("series", [])
                                          for v in ser.values()))])
        for p in s.get("pivots", []):
            pivots.append([e(s["name"]), e(p.get("name")), e(p.get("location"))])
        for c in s.get("formControls", []):
            controls.append([e(s["name"]), e(c.get("type")), code(c.get("link")),
                             code(c.get("range")), e(c.get("macro"))])
    for title, headers, rows in (
            ("Drop-down lists and data validation", ["Sheet", "Cells", "Type", "Source"], dv),
            ("Conditional formats", ["Sheet", "Cells", "Rule", "Operator", "Formula"], cf),
            ("Charts", ["Sheet", "Title", "Type", "Series"], charts),
            ("Pivot tables", ["Sheet", "Name", "Location"], pivots),
            ("Form controls", ["Sheet", "Type", "Linked cell", "List range", "Macro"],
             controls)):
        if rows:
            parts.append(f"<h3>{e(title)}</h3>" + table(headers, rows))
    if inv.get("externalLinks"):
        parts.append("<h3>External links</h3>" + table(
            ["#", "File", "Sheets"], [[l["index"], e(l["target"]), e(", ".join(l["sheets"]))]
                                      for l in inv["externalLinks"]]))
    if inv.get("dataTables"):
        parts.append("<h3>What-if data tables</h3>" + table(
            ["Sheet", "Range", "Formula", "Input cell"],
            [[e(t["sheet"]), e(t["ref"]), code(t["formula"]), e(t["r1"])]
             for t in inv["dataTables"]]))
    if inv.get("solver"):
        parts.append("<h3>Solver settings</h3>" + table(
            ["Setting", "Value"], [[e(k), code(v)] for k, v in inv["solver"].items()]))
    if inv.get("connections") or inv.get("powerQuery"):
        parts.append("<h3>Connections and Power Query</h3>" + table(
            ["Name", "Power Query", "Command"],
            [[e(c["name"]), "yes" if c["powerQuery"] else "", code(c["command"])]
             for c in inv.get("connections", [])]))
    if inv.get("vbaPresent"):
        vba = inv.get("vba", {})
        if vba.get("available"):
            parts.append("<h3>VBA</h3>" + table(
                ["Module", "Procedures"],
                [[e(m["module"]), e(", ".join(p["name"] for p in m["procedures"]))]
                 for m in vba["modules"]]))
        else:
            parts.append(f"<h3>VBA</h3><p>{e(vba.get('message', 'VBA is present.'))}</p>")

    parts.append("<h2>10. Checkpoint 1</h2><div class='box'>")
    parts.append("<p>The owner confirms the goal, the users and decisions, the meaning of "
                 "each calculation block, and answers every blocking question. Logic changes "
                 "are not made at this stage: the Python model first reproduces the "
                 "workbook's numbers.</p><p>Confirmed by: ________________ "
                 "Date: ____________</p></div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ingest", required=True, help="ingest folder with the JSON files")
    parser.add_argument("--out", help="output file (default: <ingest>/dossier.html)")
    args = parser.parse_args()
    out = Path(args.out or Path(args.ingest) / "dossier.html")
    out.write_text(render(args.ingest), encoding="utf-8")
    print(f"dossier -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
