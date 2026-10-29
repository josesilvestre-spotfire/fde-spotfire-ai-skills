---
name: running-spotfire-unattended
description: Runs IronPython builders and job scripts in a separate, unattended Spotfire Analyst instance on Windows, saves the resulting DXP and renders every page to PNG, with a lock so that runs do not collide. Use when a DXP must be built, rebuilt, re-rendered or changed through the Spotfire API without anyone clicking in Analyst, while the user's own open Analyst session stays untouched.
compatibility: Windows with Spotfire Analyst 15.0 signed in through a saved login or single sign-on, and Python 3.10 or newer. Proven on one machine.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Running Spotfire unattended

The runner starts its own Spotfire Analyst process, runs one IronPython job in it, collects the
result and ends that process. Your Analyst windows are never clicked, read or closed.

How it works:

1. `scripts/sfrun.py` writes the job to `job.json` in `$DXP_WORKSPACE/runner/` and starts a new
   Analyst process on `runner.dxp` in that folder.
2. When `runner.dxp` opens, a JavaScript in its text area clicks the **Run Pending Job** button.
   The IronPython script behind the button (`runner_job.py`) runs the job script named in
   `job.json` with the variable `JOB` set to the job.
3. The job script works through the public Spotfire API: it opens an analysis, runs a builder,
   saves, renders pages. It writes its output to a job folder under `$DXP_WORKSPACE/jobs/`.
4. `sfrun.py` waits for `result.json`, ends the Analyst process it started and frees the lock.

While the job runs, `sfrun.py` moves the job's windows past the right edge of the desktop, so
they do not cover your work and you cannot click into them by accident.

## Rules

- **Windows only.** The runner uses Win32 calls through `ctypes`.
- **Own instance only.** Every run starts a new `Spotfire.Dxp.exe` process. Never attach to,
  click into or close an Analyst window the user opened. `sfrun.py` ends only the process it
  started.
- **No input.** The runner sends no clicks or keys. UI tests that do click and type belong to
  the `testing-dxps-through-the-ui` skill: such input needs an unsandboxed run, because the
  sandbox drops mouse and keyboard input without an error.
- **No screen grabs.** Page images come from Spotfire's own `Visual.Render`, not from the
  screen, so no other application ever appears in them. When you do need a screenshot, take
  a window-only capture (see `testing-dxps-through-the-ui`).
- **One job at a time.** `sfrun.py` takes the lock `runner/RUNNER.lock` before it writes
  `job.json`. A second run waits for the lock. A lock older than 45 minutes whose owner process
  is gone is taken over.
- **Unattended Claude Code on a managed machine** needs `claude --permission-mode auto`. Managed
  settings can make Claude Code ignore a project's allow and ask rules, so a step that needs a
  person goes in `CLAUDE.md`, where Claude asks the user before it continues.
- **Absolute paths.** Pass absolute paths to Analyst. Analyst 15.0 resolves a relative path
  against its own install folder and stops with "Unable to load the file". `sfrun.py` resolves
  every path it passes.

## Setup (once per Windows account)

1. Set `DXP_WORKSPACE` to a folder for the runner and job output. Set `SPOTFIRE_HOME` only when
   Analyst is not in `%LOCALAPPDATA%\Spotfire\<version>` or `%ProgramFiles%\Spotfire\<version>`.
2. Run `python scripts/sfrun.py install`. It copies the runner sources to
   `$DXP_WORKSPACE/runner/` and writes `build_runner_ready.py` there.
3. Build `runner.dxp` and `blank.dxp` in Analyst, then add the button by hand. Follow
   [references/setup.md](references/setup.md). The button step is manual because the public
   Spotfire API cannot add an action control to a text area.
4. Run `python scripts/sfrun.py check`. Every file must show `present`.

Ask the user to do step 3: it is the only time a person works in Analyst for the runner.

## Build a DXP from an IronPython builder

```
python scripts/sfrun.py build path/to/builder.py --out path/to/output.dxp
                       [--base path/to/base.dxp] [--page "Overview"] [--set KEY=VALUE]
```

- The job opens `--base` (default `runner/blank.dxp`), runs the builder in it, makes `--page`
  active, saves the analysis as `--out` and renders every page.
- The builder runs as if pasted into the script editor without a transaction: `Document`,
  `Application` and `JOB` are defined. `--set` values arrive in `JOB`.
- The base file is never written, unless `--out` names the same file.

## Render an existing analysis

```
python scripts/sfrun.py render path/to/analysis.dxp
```

The job opens the analysis, renders every page to `renders/page_NN.png` in the job folder and
saves nothing. Read the PNGs to check the pages. The analysis may be open in your own Analyst
session at the same time: the job only reads the file.

## Run your own job script

```
python scripts/sfrun.py job path/to/my_job.py --set source=C:/analyses/example_analysis.dxp
```

A job script is IronPython 3. It gets `JOB` (the job as a dict, including `jobDir`), works
through the Spotfire API and writes its results as files in `JOB["jobDir"]`. The contract and an
example are in [references/job-scripts.md](references/job-scripts.md).

## Read the result

`sfrun.py` prints the job status and the job folder. In the folder:

| File | Content |
|---|---|
| `result.json` | `status` `done` or `error`, and the traceback of an error |
| `build_result.json` | build and render jobs: log, `ok`, `saved`, pages, tables with row counts, renders |
| `builder_output.txt` | everything the builder printed |
| `renders/page_NN.png` | one image per page, 1600 x 900 by default (`--set width=... height=...`) |

Exit code 0 means the job ran to the end and, for a build, the builder raised no error and the
DXP was saved. Always open the renders before you report a build as done: a builder can finish
without error and still produce an empty visual.

## When something goes wrong

[references/troubleshooting.md](references/troubleshooting.md) covers the login dialog, a
runner that never picks up the job, a held lock, Analyst processes left running after a
stopped background command, and memory.

Useful commands:

```
python scripts/sfrun.py instances      # every Analyst process; the job's is tagged [runner job]
python scripts/sfrun.py lock status
python scripts/sfrun.py lock recover   # ends only the job's Analyst process, frees the lock
```

## Proven and not yet tested

Proven on one Windows machine with Spotfire Analyst 15.0: the job file and auto-clicked button
design, `runner_job.py`, opening another analysis from a job, replacing a data function script
and running it, rendering pages while the window is off screen, saving with `SaveAs`, ending the
process, the lock.

**Not yet tested:** building `runner.dxp` with `build_runner.py` plus the button added by hand
(the proven runner added its button through non-public API calls, which this library does not
ship); `build_job.py` as a whole (it combines the proven open, run, save and render steps);
`sfrun.py` itself on a live Analyst (its job, lock and window code is taken from the proven
launcher; its `install`, `check`, `lock` and `--dry-run` paths were run).
