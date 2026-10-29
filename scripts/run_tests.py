"""Run every test in the library that does not need Spotfire.

Runs, each in its own process with the skill folder as working directory:
  - every tests/test_*.py file under a skill (unittest or plain asserts)
  - every script under a skill's scripts/ folder that accepts --self-test
  - every Node test entry point (tests/run.mjs) when node is on PATH

Usage:
  python scripts/run_tests.py [--filter TEXT] [--verbose]

Exit code 1 when any test fails. Standard library only; the tests
themselves need numpy, pandas, scipy, pyyaml and openpyxl.
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 900


def skill_dir(path):
    for parent in path.parents:
        if (parent / "SKILL.md").exists():
            return parent
    return path.parent


def discover():
    jobs = []
    for test in sorted(ROOT.glob("plugins/*/skills/**/tests/test_*.py")):
        if "__pycache__" in test.parts:
            continue
        jobs.append(("unit", test, [sys.executable, "-B", str(test)]))
    for script in sorted(ROOT.glob("plugins/*/skills/*/scripts/**/*.py")):
        if "tests" in script.parts or "__pycache__" in script.parts:
            continue
        text = script.read_text(encoding="utf-8", errors="replace")
        if '"--self-test"' in text or "'--self-test'" in text:
            jobs.append(("self-test", script,
                         [sys.executable, "-B", str(script),
                          "--self-test"]))
    node = shutil.which("node")
    for entry in sorted(ROOT.glob("plugins/*/skills/**/tests/run.mjs")):
        if "node_modules" in entry.parts:
            continue
        cmd = [node, str(entry)] if node else None
        jobs.append(("node", entry, cmd))
    return jobs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="",
                        help="run only paths containing this text")
    parser.add_argument("--verbose", action="store_true",
                        help="print the output of passing tests too")
    args = parser.parse_args()

    failed, skipped, passed = [], [], 0
    for kind, path, cmd in discover():
        rel = path.relative_to(ROOT).as_posix()
        if args.filter and args.filter not in rel:
            continue
        if cmd is None:
            skipped.append(f"{rel} (node not on PATH)")
            print(f"SKIP  {kind:9} {rel}")
            continue
        start = time.time()
        try:
            result = subprocess.run(cmd, cwd=skill_dir(path),
                                    capture_output=True, text=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=TIMEOUT)
            ok, output = result.returncode == 0, \
                result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            ok, output = False, f"timed out after {TIMEOUT} s"
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {kind:9} {rel}  ({time.time() - start:.1f} s)")
        if ok:
            passed += 1
            if args.verbose:
                print(output)
        else:
            failed.append(rel)
            print(output[-4000:])

    print(f"\n{passed} passed, {len(failed)} failed, "
          f"{len(skipped)} skipped")
    for rel in failed:
        print(f"FAILED {rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
