"""Run stages 1 to 3 and a draft dossier in one command.

    python ingest_workbook.py <workbook.xlsx|.xlsm> --out <ingest folder> [--crosscheck]

Writes inventory.json, snapshots/, structure.json, dependencies.mmd, issues.json,
issues.csv and dossier.html into the ingest folder, then prints a summary. Run
dossier.py again after you write meaning.json.
"""

import argparse
import json
import sys
from pathlib import Path

import dossier
import inventory
import issues as I
import structure as S


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("workbook")
    parser.add_argument("--out", required=True, help="ingest folder for the results")
    parser.add_argument("--crosscheck", action="store_true",
                        help="compare formula counts with openpyxl")
    args = parser.parse_args()
    out = Path(args.out)
    wb, inv = inventory.run(args.workbook, out, cross=args.crosscheck)
    st = S.analyze(wb)
    (out / "structure.json").write_text(json.dumps(S.to_json(st), indent=1, default=str),
                                        encoding="utf-8")
    (out / "dependencies.mmd").write_text(S.mermaid(st), encoding="utf-8")
    items, _ = I.scan(wb, st)
    counts = I.write(items, wb, out)
    (out / "dossier.html").write_text(dossier.render(out), encoding="utf-8")
    t = inv["totals"]
    print(f"Workbook: {Path(args.workbook).name}")
    print(f"  {t['sheets']} sheets, {t['formulas']} formula cells in {len(st.blocks)} blocks, "
          f"{len(st.cycles)} circular groups, {len(st.families)} template families")
    print(f"  issues: {', '.join(f'{v} {k}' for k, v in counts.items())}")
    for item in items:
        if item["severity"] == "high":
            print(f"  {item['id']} {item['type']}: {item['message'][:110]}")
    if inv.get("vba") and not inv["vba"].get("available"):
        print("  " + inv["vba"]["message"])
    print(f"  files in {out}: inventory.json, structure.json, dependencies.mmd, "
          "issues.json, issues.csv, dossier.html, snapshots/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
