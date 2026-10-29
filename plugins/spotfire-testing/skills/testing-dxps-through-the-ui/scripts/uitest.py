"""uitest.py: run a UI test plan against a Spotfire Analyst window.

    python uitest.py run plan.json [--keep-open]
    python uitest.py validate plan.json

The plan (references/test-plan-format.md) names the analysis, the window
size, named boxes (one per visual, in window pixels read off a first
screenshot) and the steps. For each step the tool sends the input, waits,
takes a window-only screenshot and compares it with the previous one: every
box listed under "changed" must change, every box under "unchanged" must
not. It writes NN-<step>.png, report.json and REPORT.md to the output
folder. Read the screenshots as well: the region check proves that
something changed, not that it changed correctly.

"run" sends real mouse and keyboard input: run it unsandboxed, and only
when the user has agreed that the mouse and keyboard are taken over for
the test. Needs Pillow. Windows only.
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ACTIONS = {"click", "dclick", "rclick", "drag", "wheel", "keys", "type",
           "wait", "shot"}
MIN_CHANGED = 0.005
MAX_UNCHANGED = 0.002


def load(path):
    with open(path, encoding="utf-8") as handle:
        plan = json.load(handle)
    problems = []
    if not plan.get("analysis") and not plan.get("hwnd"):
        problems.append("plan needs 'analysis' (a .dxp path) or 'hwnd'")
    boxes = plan.get("boxes", {})
    for name, box in boxes.items():
        if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
            problems.append("box %s must be [left, top, right, bottom]"
                            % name)
    for index, step in enumerate(plan.get("steps", []), 1):
        action = step.get("do")
        if action not in ACTIONS:
            problems.append("step %d: unknown action %r" % (index, action))
        if action in ("click", "dclick", "rclick", "wheel") and \
                len(step.get("at", [])) != 2:
            problems.append("step %d: %s needs 'at': [x, y]" % (index,
                                                                 action))
        if action == "drag" and (len(step.get("from", [])) != 2
                                 or len(step.get("to", [])) != 2):
            problems.append("step %d: drag needs 'from' and 'to'" % index)
        for key in ("changed", "unchanged"):
            for name in step.get("expect", {}).get(key, []):
                if name not in boxes:
                    problems.append("step %d: unknown box %r" % (index,
                                                                  name))
    if not plan.get("steps"):
        problems.append("plan has no steps")
    return plan, problems


def act(deskctl, hwnd, step):
    action = step["do"]
    if action in ("click", "dclick", "rclick"):
        deskctl.click(hwnd, *step["at"],
                      button="right" if action == "rclick" else "left",
                      double=action == "dclick")
    elif action == "drag":
        deskctl.drag(hwnd, *(step["from"] + step["to"]))
    elif action == "wheel":
        deskctl.wheel(hwnd, *step["at"], step.get("clicks", -3))
    elif action == "keys":
        deskctl.keys(hwnd, step["keys"])
    elif action == "type":
        deskctl.type_text(hwnd, step["text"])
    elif action == "wait":
        time.sleep(float(step.get("seconds", 2)))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "step"


def run(plan, keep_open=False):
    import deskctl
    import shotdiff
    out = os.path.abspath(plan.get("out", "ui-test-out"))
    os.makedirs(out, exist_ok=True)
    settle = float(plan.get("settle", 2.0))
    started_pid = None
    if plan.get("hwnd"):
        hwnd = int(plan["hwnd"])
    else:
        started_pid, hwnd = deskctl.spotfire(plan["analysis"])
    win = plan.get("window", {"x": 40, "y": 40, "w": 1600, "h": 1000})
    deskctl.place(hwnd, win["x"], win["y"], win["w"], win["h"])
    time.sleep(settle)
    boxes = {k: tuple(v) for k, v in plan.get("boxes", {}).items()}
    previous = os.path.join(out, "00-start.png")
    deskctl.shot(hwnd, previous)
    results = []
    try:
        for index, step in enumerate(plan["steps"], 1):
            name = step.get("name", step["do"])
            act(deskctl, hwnd, step)
            time.sleep(float(step.get("settle", settle)))
            current = os.path.join(out, "%02d-%s.png" % (index, slug(name)))
            deskctl.shot(hwnd, current)
            _mask, shares = shotdiff.compare(previous, current,
                                             list(boxes.items()))
            checks = []
            expect = step.get("expect", {})
            for box in expect.get("changed", []):
                ok = shares[box] >= step.get("minChanged", MIN_CHANGED)
                checks.append({"box": box, "expect": "changed",
                               "share": round(shares[box], 4), "ok": ok})
            for box in expect.get("unchanged", []):
                ok = shares[box] <= step.get("maxUnchanged", MAX_UNCHANGED)
                checks.append({"box": box, "expect": "unchanged",
                               "share": round(shares[box], 4), "ok": ok})
            results.append({"step": index, "name": name,
                            "screenshot": os.path.basename(current),
                            "checks": checks,
                            "ok": all(c["ok"] for c in checks)})
            print("%s %02d %s" % ("PASS" if results[-1]["ok"] else "FAIL",
                                  index, name), flush=True)
            previous = current
    finally:
        if started_pid and not keep_open:
            deskctl.close(started_pid)
    write_report(out, plan, results)
    return all(r["ok"] for r in results)


def write_report(out, plan, results):
    with open(os.path.join(out, "report.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"plan": plan, "results": results}, handle, indent=1)
    lines = ["# UI test: %s" % os.path.basename(plan.get("analysis", "")),
             "", "| step | result | checks | screenshot |",
             "|---|---|---|---|"]
    for item in results:
        checks = "; ".join("%s %s (%.1f%%)" % (c["box"], c["expect"],
                                              c["share"] * 100)
                           for c in item["checks"]) or "screenshot only"
        lines.append("| %02d %s | %s | %s | %s |" % (
            item["step"], item["name"], "PASS" if item["ok"] else "FAIL",
            checks, item["screenshot"]))
    with open(os.path.join(out, "REPORT.md"), "w", encoding="utf-8") as h:
        h.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run", "validate"])
    parser.add_argument("plan")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args(argv)
    plan, problems = load(args.plan)
    for problem in problems:
        print("plan: " + problem)
    if problems:
        return 2
    if args.command == "validate":
        print("plan OK: %d step(s), %d box(es)" % (len(plan["steps"]),
                                                  len(plan.get("boxes",
                                                               {}))))
        return 0
    return 0 if run(plan, args.keep_open) else 1


if __name__ == "__main__":
    sys.exit(main())
