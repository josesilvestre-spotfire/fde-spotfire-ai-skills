"""Apply a new script to a Spotfire data function and validate it, unattended.

    python tools/update_data_function.py <analysis.dxp> "<Function Name>" <script.py>
                                         [--out staging/<analysis>.dxp]
                                         [--report reports/<run>]

Steps:
  1. checks the Python syntax of the script,
  2. checks that the analysis holds data functions and names the definitions,
  3. starts a separate Spotfire Analyst process through the runner
     (sfrun.py): the job opens the DXP, replaces the script through the
     Spotfire API, runs the function, renders every page and saves the
     result as a new DXP in staging/ (the source file is never written),
  4. checks that the function is approved for this account and ran,
  5. writes REPORT.md with the checks, the script diff, the output rows, the
     page renders and, when the dxp command (dxpkit) is installed, a
     summary of the DXP change.

Needs DXP_WORKSPACE (the runner lives in $DXP_WORKSPACE/runner) and a
signed-in Spotfire Analyst. Exit code 0 when the function ran and the new
DXP was saved, 1 otherwise, 2 for bad input.
"""
import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from sfrun import RunnerError, run_job  # noqa: E402

APPLY_JOB = TOOLS / "apply_job.py"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    try:
        return Path(path).resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return str(path)


def definition_names(dxp):
    """Names of the data function definitions stored in the DXP (read
    directly from the ZIP; the full check happens in Spotfire)."""
    with zipfile.ZipFile(dxp) as archive:
        text = archive.read("AnalysisDocument.xml").decode("utf-8-sig")
    names = set()
    for match in re.finditer(r"&lt;FunctionName&gt;(.*?)&lt;/FunctionName&gt;",
                             text):
        names.add(match.group(1).replace("&amp;amp;", "&")
                  .replace("&amp;", "&"))
    return names


def dxp_diff_stat(old, new):
    """'dxp diff --stat' when dxpkit is installed, else None."""
    dxp = shutil.which("dxp")
    if not dxp:
        return None
    out = subprocess.run([dxp, "diff", "--stat", str(old), str(new)],
                         capture_output=True, text=True, encoding="utf-8")
    return out.stdout if out.returncode in (0, 1) else None


def markdown_table(columns, rows):
    out = ["| " + " | ".join(columns) + " |",
           "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dxp", type=Path)
    p.add_argument("function")
    p.add_argument("script", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--timeout", type=int, default=900)
    a = p.parse_args(argv)
    if not a.dxp.is_file() or not a.script.is_file():
        print("not found: %s" % (a.dxp if not a.dxp.is_file() else a.script))
        return 2
    stamp = dt.datetime.now()
    out = a.out or Path("staging") / a.dxp.name
    report = a.report or Path("reports") / (
        stamp.strftime("%Y%m%d-%H%M%S") + "-"
        + re.sub(r"[^a-z0-9]+", "-", a.function.lower()).strip("-"))
    new_script = a.script.read_text(encoding="utf-8")

    print("1/5 Python syntax of %s: " % rel(a.script), end="")
    try:
        compile(new_script, str(a.script), "exec")
    except SyntaxError as e:
        print("line %s: %s" % (e.lineno, e.msg))
        return 1
    print("OK")

    names = definition_names(a.dxp)
    if not names:
        print("2/5 %s holds no data functions" % rel(a.dxp))
        return 1
    if a.function in names:
        print("2/5 data function %r found in %s" % (a.function, rel(a.dxp)))
    else:
        # The definition name can differ from the name shown in Analyst
        # when the data function was renamed; Spotfire checks the latter.
        print("2/5 no definition named %r (definitions: %s); Spotfire "
              "checks the data function names" % (
                  a.function, ", ".join(sorted(names))))

    out.parent.mkdir(parents=True, exist_ok=True)
    print("3/5 applying in an unattended Spotfire Analyst session ...",
          flush=True)
    started = dt.datetime.now()
    try:
        run_job(APPLY_JOB, {"source": str(a.dxp.resolve()),
                            "target": str(out.resolve()),
                            "function": a.function,
                            "functionScript": str(a.script.resolve()),
                            "reportDir": str(report.resolve())},
                owner="update-data-function", timeout_s=a.timeout,
                label="update")
    except RunnerError as exc:
        print("    %s" % exc)
        return 1
    seconds = (dt.datetime.now() - started).total_seconds()
    result_file = report / "spotfire_result.json"
    if not result_file.exists():
        print("    the Spotfire job wrote no result")
        return 1
    res = json.loads(result_file.read_text(encoding="utf-8-sig"))
    if res.get("error"):
        print(res["error"])
        return 1
    print("    done in %.0f s: script replaced, function run, %d page(s) "
          "rendered, new DXP saved" % (seconds, len(res["renders"])))

    ok = bool(res.get("approvedAfter")) and bool(res.get("executed")) \
        and bool(res.get("saved"))
    print("4/5 validation:")
    print("    approved for this account  %s" % res["approvedAfter"])
    print("    function executed          %s" % res["executed"])
    for t in res["tables"]:
        print("    table %-20s %s rows, %d columns" % (t["name"], t["rows"],
                                                      len(t["columns"])))

    old_script = (res.get("oldScript") or "").replace("\r\n", "\n")
    change = list(difflib.unified_diff(
        old_script.splitlines(keepends=True),
        new_script.replace("\r\n", "\n").splitlines(keepends=True),
        "current script", "new script"))
    stat = dxp_diff_stat(a.dxp, out) if ok else None
    print("5/5 DXP change (dxp diff --stat):")
    for line in (stat or "    (dxp command not installed; skipped)\n") \
            .splitlines():
        print("    " + line)

    lines = ["# Data function update: %s" % a.function, "",
             "- Source: `%s` (sha256 %s)" % (rel(a.dxp), sha256(a.dxp)[:12]),
             "- New DXP: `%s`" % rel(out),
             "- Script: `%s`" % rel(a.script),
             "- Run: %s, unattended Spotfire Analyst session, %.0f s"
             % (stamp.strftime("%Y-%m-%d %H:%M"), seconds),
             "- Result: **%s**" % ("PASS" if ok else "FAIL"), "",
             "## Checks", "", "| Check | Result |", "|---|---|",
             "| Python syntax | OK |",
             "| Approved for this account | %s |" % res["approvedAfter"],
             "| Function executed | %s |" % res["executed"]]
    lines += ["| Table %s | %s rows |" % (t["name"], t["rows"])
              for t in res["tables"]]
    lines += ["", "## Script change", "", "```diff"]
    lines += [x.rstrip("\n") for x in change] + ["```", ""]
    for t in res["tables"]:
        if "values" in t:
            lines += ["## Output: %s" % t["name"], ""]
            lines += markdown_table(t["columns"], t["values"]) + [""]
    lines += ["## Pages", ""]
    lines += ["![%s](%s)" % (r["page"], r["file"]) for r in res["renders"]]
    if stat:
        lines += ["", "## DXP change (dxp diff --stat)", "", "```"]
        lines += stat.splitlines() + ["```"]
    (report / "REPORT.md").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8")
    result_file.unlink()
    (report / "result.json").write_text(json.dumps(
        {k: v for k, v in res.items() if k != "oldScript"}, indent=1),
        encoding="utf-8")
    Path(str(out) + ".source.json").write_text(json.dumps(
        {"source": rel(a.dxp), "sourceSha256": sha256(a.dxp),
         "function": a.function, "script": rel(a.script),
         "report": rel(report), "pass": ok}, indent=1), encoding="utf-8")
    print("report: %s" % rel(report / "REPORT.md"))
    for r in res["renders"]:
        print("page render: %s" % rel(report / r["file"]))
    print("new DXP: %s  %s" % (rel(out), "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
