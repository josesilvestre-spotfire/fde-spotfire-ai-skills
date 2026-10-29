# Runner job script (IronPython 3, Spotfire Analyst 15.0).
#
# Stored in runner.dxp as the script "Run Pending Job", with "Execute in
# transaction" off so that a job can open and save analyses. When runner.dxp
# opens, the JavaScript in its text area clicks the Run Pending Job button,
# which runs this script. With a pending job in job.json, next to runner.dxp,
# it runs the job script named in job.json with the variable JOB set to the
# job, and writes result.json in the job folder. With no pending job it does
# nothing, so runner.dxp can be opened by hand.
import sys
import traceback

import System
from System.IO import Directory, File, Path


def add_python_library():
    # The IronPython standard library ships with Spotfire as Lib.zip.
    base = System.AppDomain.CurrentDomain.BaseDirectory
    modules = Path.Combine(base, "Modules")
    if Directory.Exists(modules):
        for folder in Directory.GetDirectories(modules, "Script Support*"):
            lib = Path.Combine(folder, "IronPython-3", "Lib.zip")
            if File.Exists(lib) and lib not in sys.path:
                sys.path.append(lib)


try:
    import json
except ImportError:
    add_python_library()
    import json


def run_pending_job():
    loaded = Application.DocumentMetadata.LoadedFromFileName
    if not loaded:
        return
    job_file = Path.Combine(Path.GetDirectoryName(loaded), "job.json")
    if not File.Exists(job_file):
        return
    job = json.loads(File.ReadAllText(job_file))
    if job.get("status") != "pending":
        return
    job["status"] = "running"
    File.WriteAllText(job_file, json.dumps(job, indent=1))
    result = {"status": "running"}
    try:
        code = File.ReadAllText(job["script"])
        scope = dict(globals())
        scope["JOB"] = job
        scope["__name__"] = "__job__"
        exec(compile(code, job["script"], "exec"), scope)
        result["status"] = "done"
    except Exception:
        result["status"] = "error"
        result["traceback"] = traceback.format_exc()
    Directory.CreateDirectory(job["jobDir"])
    File.WriteAllText(Path.Combine(job["jobDir"], "result.json"),
                      json.dumps(result, indent=1))
    job["status"] = "done"
    File.WriteAllText(job_file, json.dumps(job, indent=1))


run_pending_job()
