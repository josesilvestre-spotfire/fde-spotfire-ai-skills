"""Replace the analysis users open with a validated staging copy.

    python tools/promote.py staging/<analysis>.dxp analyses/<analysis>.dxp

Run it only after a person has approved the change (see CLAUDE.md).

Refuses when the staging copy has no passing validation record from
update_data_function.py, or when the target changed after the staging copy
was built from it. Keeps the replaced file in <target folder>/.backup/.

When the project tracks the analysis with dxpkit (dxpkit.yaml) and the dxp
command is installed, runs "dxp pull <name>" for every tracked function of
the target that dxp status reports "in sync". With script and DXP in
agreement, dxp pull writes no file except dxpkit.lock, where it records the
promoted script, so the next edit in Git shows as "git ahead" and not as a
conflict.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STATUS_LINE = re.compile(r"^(in sync|git ahead|spotfire ahead|conflict|"
                         r"untracked-diff|missing)\s+(\S+) -> (.+?)\s*$")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_config(start):
    for folder in [start] + list(start.parents):
        if (folder / "dxpkit.yaml").exists():
            return folder / "dxpkit.yaml"
    return None


def record_in_lock(target):
    config = find_config(Path.cwd().resolve())
    if config is None:
        return
    dxp = shutil.which("dxp")
    if not dxp:
        print("dxpkit.yaml found but the dxp command is not installed: run "
              "'dxp pull <name>' later to record the promoted script")
        return
    status = subprocess.run([dxp, "status"], capture_output=True,
                            text=True, encoding="utf-8",
                            cwd=str(config.parent))
    for line in status.stdout.splitlines():
        match = STATUS_LINE.match(line.strip())
        if not match:
            continue
        state, name, raw = match.groups()
        path = Path(os.path.expandvars(raw))
        if not path.is_absolute():
            path = config.parent / path
        if path.resolve() != target.resolve():
            continue
        if state != "in sync":
            print("dxp status reports %s for %s: the promoted script and "
                  "the Git source differ, so dxpkit.lock was not updated"
                  % (state, name))
            continue
        pull = subprocess.run([dxp, "pull", name], capture_output=True,
                              text=True, encoding="utf-8",
                              cwd=str(config.parent))
        print((pull.stdout or pull.stderr).strip())
        if pull.returncode == 0:
            print("recorded %s in dxpkit.lock" % name)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    staging, target = Path(argv[0]), Path(argv[1])
    meta_file = Path(str(staging) + ".source.json")
    if not staging.exists() or not meta_file.exists():
        print("refused: %s has no validation record" % staging)
        return 1
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    if not meta.get("pass"):
        print("refused: validation of %s did not pass (see %s)"
              % (staging, meta.get("report")))
        return 1
    if target.exists() and sha256(target) != meta["sourceSha256"]:
        print("refused: %s changed after %s was built from it"
              % (target, staging))
        return 1
    if target.exists():
        backup = target.parent / ".backup"
        backup.mkdir(exist_ok=True)
        kept = backup / ("%s.%s.dxp" % (
            target.stem, dt.datetime.now().strftime("%Y%m%d-%H%M%S")))
        shutil.copy2(target, kept)
        print("kept the previous version as %s" % kept.as_posix())
    shutil.copy2(staging, target)
    if sha256(target) != sha256(staging):
        print("error: the copy does not match the staging file")
        return 2
    print("promoted %s to %s (validated in %s)"
          % (staging.as_posix(), target.as_posix(), meta.get("report")))
    record_in_lock(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
