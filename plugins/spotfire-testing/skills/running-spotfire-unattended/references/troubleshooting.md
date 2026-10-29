# Troubleshooting the runner

## Analyst waits at its login dialog

`sfrun.py` stops after two minutes when a window of the job process has "Login" in its title.
Start Analyst by hand once, sign in with "remember me" (or set up single sign-on), close it and
run the job again. The runner never types credentials.

## The runner does not pick up the job

`sfrun.py` stops when `job.json` still says `pending` four minutes after start
(`--start-timeout`). Open `runner.dxp` by hand and check:

- A trust prompt: choose **File > Manage trust > Trust all**, then save.
- The **Run Pending Job** button exists and has exactly that text (see `setup.md`, step 3).
- The text area carries the JavaScript **Runner Auto Click** (Edit text area > the scripts
  list).

Run the job with `--visible` to watch the window.

## "Unable to load the file"

A relative path reached Analyst. `sfrun.py` resolves its own paths; check paths you put in
`--set` values or in your own job scripts.

## The lock is held

```
python scripts/sfrun.py lock status
```

It shows the owner, the wrapper's process id, the job's Analyst process id and the job folder.

- A lock whose wrapper process is gone and which is older than 45 minutes is taken over by the
  next job.
- To free it at once: `python scripts/sfrun.py lock recover`. It refuses while the wrapper is
  still running (add `--force` only when you know it is stuck), ends the Analyst process the
  lock records (and only when that process is `Spotfire.Dxp.exe`) and frees the lock.

## A background command was stopped, for example for low memory

When Claude Code stops a background command, only the outer shell ends. The Analyst job and
any Python steps it started can keep running and can finish on their own. Before you report the
run as failed:

1. `python scripts/sfrun.py instances` lists every Analyst process and tags the runner's.
2. Look in the job folder for `result.json` and the renders.
3. Do not restart the chain on your own, and never close Analyst windows the user opened.
4. If the job's Analyst process is still running and nothing waits for it, use
   `sfrun.py lock recover`.

## Memory

Every Analyst process holds its own copy of the analysis and data. One measured job instance
used about 2 GB next to several user sessions, which pushed the machine into memory pressure.
Run one job at a time (the lock does this), let `sfrun.py` end each job process, and avoid long
unattended chains while the user has many Analyst windows open.

## Claude Code asks for every command

On a machine with managed settings, project allow rules can be ignored, and a fresh session can
run without the sandbox. Start unattended sessions with `claude --permission-mode auto`. Keep
the steps that need a person in `CLAUDE.md`, where Claude asks before it continues.
