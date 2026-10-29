"""sfrun.py: run IronPython jobs in an unattended Spotfire Analyst instance.

The runner is one analysis, runner.dxp, kept in $DXP_WORKSPACE/runner/. When
Analyst opens it, a JavaScript in its text area clicks the "Run Pending Job"
button, and the IronPython script behind the button runs the job described
in job.json next to runner.dxp. This script writes job.json, starts a NEW
Analyst process on runner.dxp, moves that process's windows past the right
edge of the desktop, waits for result.json in the job folder and then ends
that process. It sends no clicks or keys and never touches another Spotfire
window, so an analysis you have open stays as it is.

Commands:
  install                 copy the runner sources to $DXP_WORKSPACE/runner and
                          write build_runner_ready.py (paste it into Analyst once)
  check                   show the Analyst it will use, the runner files and the lock
  build BUILDER --out OUT [--base BASE] [--page TITLE] [--no-render]
                          open BASE (default runner/blank.dxp), run the IronPython
                          BUILDER in it, save as OUT, render every page
  render ANALYSIS         open ANALYSIS, render every page, save nothing
  job SCRIPT [--json FILE]
                          run any IronPython job script; it receives JOB (a dict)
  lock [status | release OWNER | recover]
                          show or free the runner lock; recover ends the Analyst
                          process the lock records and frees the lock
  instances               list running Spotfire processes and their window titles

Options for build, render and job:
  --set KEY=VALUE         extra JOB entries (repeatable)
  --owner NAME            label recorded in the lock (default: the command)
  --timeout SECONDS       whole run (default 900)
  --start-timeout SECONDS time for the runner to pick up the job (default 240)
  --keep-open             leave the Analyst process running when the job ends
  --visible               do not move the Analyst window off screen
  --dry-run               write nothing, start nothing; print the job

Environment:
  DXP_WORKSPACE   folder that holds runner/ and jobs/ (required)
  SPOTFIRE_HOME   Analyst folder with Spotfire.Dxp.exe (searched when unset)

Windows only. Standard library only. Exit code 0 when the job finished with
status done, 1 when it failed or timed out, 2 for bad input or setup.
"""
import argparse
import ctypes
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER_SOURCES = ("runner_job.py", "runner_autoclick.js", "build_runner.py",
                  "build_job.py")
STALE_LOCK_S = 45 * 60
LOGIN_WAIT_S = 120
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


class RunnerError(Exception):
    """A job could not run; the message says what to do."""


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def workspace():
    value = os.environ.get("DXP_WORKSPACE")
    if not value:
        raise RunnerError("Set DXP_WORKSPACE to the folder that holds "
                          "runner/ and jobs/ (for example a folder named "
                          "Spotfire under your documents).")
    return Path(value).resolve()


def runner_dir():
    return workspace() / "runner"


def find_spotfire():
    home = os.environ.get("SPOTFIRE_HOME")
    if home:
        exe = Path(home) / "Spotfire.Dxp.exe"
        if exe.is_file():
            return str(exe)
        raise RunnerError("SPOTFIRE_HOME is set, but %s does not exist"
                          % exe)
    roots = [os.environ.get("LOCALAPPDATA", ""),
             os.environ.get("ProgramFiles", ""),
             os.environ.get("ProgramFiles(x86)", "")]
    found = []
    for root in roots:
        if root:
            found += glob.glob(os.path.join(root, "Spotfire", "*",
                                            "Spotfire.Dxp.exe"))
    if not found:
        raise RunnerError("Spotfire Analyst not found. Set SPOTFIRE_HOME to "
                          "the folder that holds Spotfire.Dxp.exe.")
    return sorted(found)[-1]


# --------------------------------------------------------------------------
# Windows of one process (user32 through ctypes)
# --------------------------------------------------------------------------
def _user32():
    if os.name != "nt":
        raise RunnerError("the runner needs Windows")
    return ctypes.windll.user32


def windows_of(pid):
    from ctypes import wintypes
    user32 = _user32()
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _param):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, title.value, rect.left))
        return True

    user32.EnumWindows(proc(callback), 0)
    return found


def park_windows(pid):
    """Move the job's windows past the right edge of the virtual desktop,
    so the job does not cover your work and you cannot click into it."""
    user32 = _user32()
    right = user32.GetSystemMetrics(76) + user32.GetSystemMetrics(78)
    for hwnd, _title, left in windows_of(pid):
        if left < right:
            # SWP_NOZORDER | SWP_NOACTIVATE: no focus change.
            user32.SetWindowPos(hwnd, 0, right + 100, 40, 1600, 1000, 0x14)


def process_alive(pid):
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV",
                          "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def process_image(pid):
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV",
                          "/NH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1] == str(pid):
            return parts[0]
    return None


def end_process(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True)


# --------------------------------------------------------------------------
# Lock: one job at a time per workspace
# --------------------------------------------------------------------------
def lock_path():
    return runner_dir() / "RUNNER.lock"


def lock_info():
    try:
        return json.loads((lock_path() / "owner.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_lock_info(info):
    (lock_path() / "owner.json").write_text(json.dumps(info, indent=1),
                                            encoding="utf-8")


def acquire_lock(owner, wait_s=3600):
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    while True:
        try:
            path.mkdir()
            write_lock_info({"owner": owner, "pid": os.getpid(),
                             "started": time.strftime("%Y-%m-%d %H:%M:%S")})
            return
        except FileExistsError:
            age = time.time() - path.stat().st_mtime
            info = lock_info()
            holder_alive = info.get("pid") and process_alive(info["pid"])
            if age > STALE_LOCK_S and not holder_alive:
                release_lock(force=True)
                continue
            if time.time() - start > wait_s:
                raise RunnerError("the runner is busy: lock held by %s since "
                                  "%s" % (info.get("owner", "?"),
                                          info.get("started", "?")))
            time.sleep(10)


def release_lock(owner=None, force=False):
    path = lock_path()
    if not path.is_dir():
        return "free"
    info = lock_info()
    if not force and owner is not None and info.get("owner") != owner:
        return "held by %s, not released" % info.get("owner")
    shutil.rmtree(path, ignore_errors=True)
    return "released"


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
def job_folder(label):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = workspace() / "jobs" / ("%s-%s" % (stamp, label))
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = workspace() / "jobs" / ("%s-%s-%d" % (stamp, label, suffix))
    return folder


def job_status():
    try:
        return json.loads((runner_dir() / "job.json").read_text(
            encoding="utf-8-sig")).get("status")
    except (OSError, ValueError):
        return None


def set_job_status(status):
    job_file = runner_dir() / "job.json"
    try:
        job = json.loads(job_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if job.get("status") in ("pending", "running"):
        job["status"] = status
        job_file.write_text(json.dumps(job, indent=1), encoding="utf-8")
    return job.get("status")


def run_job(script, payload=None, owner="job", timeout_s=900,
            start_timeout_s=240, keep_open=False, visible=False,
            dry_run=False, label=None):
    """Run one IronPython job script in a new Analyst process.

    Returns (job folder, result dict). result["status"] is "done" when the
    job script ran to the end; a job script records its own outcome in
    files in the job folder."""
    script = Path(script).resolve()
    if not script.is_file():
        raise RunnerError("job script not found: %s" % script)
    runner = runner_dir() / "runner.dxp"
    folder = job_folder(label or script.stem)
    job = dict(payload or {})
    job.update({"id": folder.name, "status": "pending",
                "script": str(script), "jobDir": str(folder)})
    exe = find_spotfire()
    if dry_run:
        print(json.dumps({"spotfire": exe, "runner": str(runner),
                          "job": job}, indent=1))
        return folder, {"status": "dry-run"}
    if not runner.is_file():
        raise RunnerError("%s is missing. Run 'sfrun.py install' and build "
                          "it once (references/setup.md)." % runner)
    acquire_lock(owner)
    process = None
    try:
        folder.mkdir(parents=True)
        (runner_dir() / "job.json").write_text(json.dumps(job, indent=1),
                                               encoding="utf-8")
        # An absolute path: Analyst resolves a relative one against its own
        # install folder and stops with "Unable to load the file".
        process = subprocess.Popen([exe, str(runner)])
        info = lock_info()
        info["spotfirePid"] = process.pid
        info["jobDir"] = str(folder)
        write_lock_info(info)
        print("job %s: Analyst process %d started on %s"
              % (folder.name, process.pid, runner.name), flush=True)
        result_file = folder / "result.json"
        start = time.time()
        while not result_file.exists():
            elapsed = time.time() - start
            titles = [t for _h, t, _l in windows_of(process.pid)]
            if process.poll() is not None:
                time.sleep(5.0)
                if result_file.exists():
                    break
                raise RunnerError("Analyst closed before the job finished "
                                  "(exit code %s)" % process.returncode)
            if elapsed > LOGIN_WAIT_S and any("login" in t.lower()
                                              for t in titles):
                raise RunnerError(
                    "Analyst is waiting at its login dialog. Sign in once "
                    "with 'remember me' or single sign-on, then run again.")
            if elapsed > start_timeout_s and job_status() == "pending":
                raise RunnerError(
                    "the runner did not pick up the job in %d s. Open "
                    "runner.dxp by hand: if it shows a trust prompt, use "
                    "File > Manage trust > Trust all and save; check that "
                    "the Run Pending Job button exists." % start_timeout_s)
            if elapsed > timeout_s:
                raise RunnerError("the job did not finish in %d s; see %s"
                                  % (timeout_s, folder))
            if not visible:
                park_windows(process.pid)
            time.sleep(1.0)
        time.sleep(1.0)
        result = json.loads(result_file.read_text(encoding="utf-8-sig"))
        return folder, result
    finally:
        set_job_status("cancelled")
        if process is not None and not keep_open:
            end_process(process.pid)
        elif process is not None:
            print("Analyst process %d left open" % process.pid)
        release_lock(owner)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def parse_sets(pairs):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise RunnerError("--set needs KEY=VALUE, got %r" % pair)
        key, value = pair.split("=", 1)
        out[key] = value
    return out


def report(folder, result):
    status = result.get("status")
    print("job status: %s" % status)
    if result.get("traceback"):
        print(result["traceback"])
    extra = folder / "build_result.json"
    if extra.exists():
        build = json.loads(extra.read_text(encoding="utf-8-sig"))
        for line in build.get("log", []):
            print("  " + line)
        if build.get("builderError"):
            print(build["builderError"])
        for item in build.get("renders", []):
            print("render: %s" % (folder / item["file"]))
        if build.get("saved"):
            print("saved: %s" % build["saved"])
        if not build.get("ok", True):
            status = "failed"
    print("job folder: %s" % folder)
    return EXIT_OK if status == "done" else EXIT_FAIL


def run_build_job(args, payload, label):
    payload.update(parse_sets(args.set))
    folder, result = run_job(runner_dir() / "build_job.py", payload,
                             owner=args.owner or label,
                             timeout_s=args.timeout,
                             start_timeout_s=args.start_timeout,
                             keep_open=args.keep_open, visible=args.visible,
                             dry_run=args.dry_run, label=label)
    return EXIT_OK if args.dry_run else report(folder, result)


def cmd_build(args):
    base = Path(args.base) if args.base else runner_dir() / "blank.dxp"
    if not args.dry_run and not base.is_file():
        raise RunnerError("base analysis not found: %s" % base)
    return run_build_job(args, {
        "analysis": str(base.resolve()),
        "builder": str(Path(args.builder).resolve()),
        "output": str(Path(args.out).resolve()),
        "activePage": args.page, "render": not args.no_render}, "build")


def cmd_render(args):
    analysis = Path(args.analysis)
    if not args.dry_run and not analysis.is_file():
        raise RunnerError("analysis not found: %s" % analysis)
    return run_build_job(args, {"analysis": str(analysis.resolve()),
                                "render": True}, "render")


def cmd_job(args):
    payload = {}
    if args.json:
        payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    payload.update(parse_sets(args.set))
    folder, result = run_job(args.script, payload,
                             owner=args.owner or "job",
                             timeout_s=args.timeout,
                             start_timeout_s=args.start_timeout,
                             keep_open=args.keep_open, visible=args.visible,
                             dry_run=args.dry_run)
    return EXIT_OK if args.dry_run else report(folder, result)


def cmd_install(_args):
    target = runner_dir()
    target.mkdir(parents=True, exist_ok=True)
    (workspace() / "jobs").mkdir(exist_ok=True)
    for name in RUNNER_SOURCES:
        shutil.copy2(HERE / name, target / name)
        print("copied %s" % (target / name))
    code = (HERE / "build_runner.py").read_text(encoding="utf-8")
    code = code.replace("__RUNNER_DIR__", str(target))
    ready = target / "build_runner_ready.py"
    ready.write_text(code, encoding="utf-8")
    print("wrote %s: paste it into a new blank analysis in Analyst "
          "(references/setup.md)" % ready)
    return EXIT_OK


def cmd_check(_args):
    ok = True
    try:
        print("Analyst:   %s" % find_spotfire())
    except RunnerError as exc:
        print("Analyst:   NOT FOUND (%s)" % exc)
        ok = False
    folder = runner_dir()
    print("runner:    %s" % folder)
    for name in RUNNER_SOURCES + ("runner.dxp", "blank.dxp"):
        exists = (folder / name).is_file()
        ok = ok and exists
        print("  %-22s %s" % (name, "present" if exists else "MISSING"))
    info = lock_info()
    print("lock:      %s" % ("held by %s since %s" % (
        info.get("owner"), info.get("started")) if lock_path().is_dir()
        else "free"))
    return EXIT_OK if ok else EXIT_FAIL


def cmd_lock(args):
    action = args.action or "status"
    if action == "status":
        if lock_path().is_dir():
            print(json.dumps(lock_info(), indent=1))
        else:
            print("free")
        return EXIT_OK
    if action == "release":
        print(release_lock(args.owner))
        return EXIT_OK
    if action == "recover":
        info = lock_info()
        pid = info.get("spotfirePid")
        if info.get("pid") and process_alive(info["pid"]) and not args.force:
            print("the job wrapper (pid %s) is still running; wait for it or "
                  "use --force" % info["pid"])
            return EXIT_FAIL
        if pid and (process_image(pid) or "").lower() == "spotfire.dxp.exe":
            end_process(pid)
            print("ended the job's Analyst process %d" % pid)
        print(release_lock(force=True))
        set_job_status("cancelled")
        return EXIT_OK
    raise RunnerError("lock action must be status, release or recover")


def cmd_instances(_args):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Spotfire.Dxp.exe",
                          "/FO", "CSV", "/NH"], capture_output=True,
                         text=True).stdout
    job_pid = lock_info().get("spotfirePid") if lock_path().is_dir() \
        else None
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 5 or not parts[1].isdigit():
            continue
        pid = int(parts[1])
        titles = [t for _h, t, _l in windows_of(pid) if t]
        print("%6d  %-10s %s %s" % (pid, parts[4],
                                    "[runner job]" if pid == job_pid else "",
                                    " | ".join(titles)))
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sfrun", description=__doc__
                                     .splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def job_options(p):
        p.add_argument("--set", action="append", metavar="KEY=VALUE")
        p.add_argument("--owner")
        p.add_argument("--timeout", type=int, default=900)
        p.add_argument("--start-timeout", type=int, default=240)
        p.add_argument("--keep-open", action="store_true")
        p.add_argument("--visible", action="store_true")
        p.add_argument("--dry-run", action="store_true")

    sub.add_parser("install").set_defaults(run=cmd_install)
    sub.add_parser("check").set_defaults(run=cmd_check)
    p = sub.add_parser("build")
    p.add_argument("builder")
    p.add_argument("--out", required=True)
    p.add_argument("--base")
    p.add_argument("--page")
    p.add_argument("--no-render", action="store_true")
    job_options(p)
    p.set_defaults(run=cmd_build)
    p = sub.add_parser("render")
    p.add_argument("analysis")
    job_options(p)
    p.set_defaults(run=cmd_render)
    p = sub.add_parser("job")
    p.add_argument("script")
    p.add_argument("--json")
    job_options(p)
    p.set_defaults(run=cmd_job)
    p = sub.add_parser("lock")
    p.add_argument("action", nargs="?",
                   choices=["status", "release", "recover"])
    p.add_argument("owner", nargs="?")
    p.add_argument("--force", action="store_true")
    p.set_defaults(run=cmd_lock)
    sub.add_parser("instances").set_defaults(run=cmd_instances)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        return args.run(args)
    except RunnerError as exc:
        print("sfrun: %s" % exc, file=sys.stderr)
        return EXIT_USAGE if "not found" in str(exc) or "Set " in str(exc) \
            else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
