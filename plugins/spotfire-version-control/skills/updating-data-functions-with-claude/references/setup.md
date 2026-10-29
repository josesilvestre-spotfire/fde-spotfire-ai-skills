# Setup: project and runner

## What you need

- Windows with Spotfire Analyst 15.0, signed in through a saved login ("remember me") or single
  sign-on, so that it starts without a login prompt.
- Python 3.10 or newer.
- Claude Code. On a machine with managed settings, auto permission mode must be allowed by the
  organization: start sessions with `claude --permission-mode auto`.
- Optional: Git, a remote repository, an IDE, and dxpkit (`dxp` command) for `dxp status`,
  `dxp pull` and readable DXP diffs. dxpkit is a separate tool, not distributed with this
  library: install it from its own source (see the `tracking-dxps-in-git` skill).
- `DXP_WORKSPACE` set to a folder you own. The runner lives in `$DXP_WORKSPACE/runner/` and is
  shared with the `running-spotfire-unattended` skill.

## Project layout

```
<your-project>/
  CLAUDE.md                     from assets/project-CLAUDE.md, placeholders filled in
  start-claude.cmd              from assets/start-claude.cmd
  .gitignore                    from assets/gitignore.txt
  dxpkit.yaml, dxpkit.lock      optional, when dxpkit tracks the scripts
  analyses/<analysis>.dxp       the analysis users open
  functions/<function>.py       one file per data function script
  staging/                      validated copies waiting for approval (not committed)
  reports/<run>/                REPORT.md, page renders and result.json per run (committed)
  tools/                        the scripts below
```

## Steps

1. Create the folders and copy into `tools/` every file in this skill's `scripts/` folder:
   `update_data_function.py`, `promote.py`, `apply_job.py`, `sfrun.py`, `runner_job.py`,
   `runner_autoclick.js`, `build_runner.py` and `build_job.py`. Also copy `dxp_inventory.py`
   from the `auditing-and-comparing-dxps` skill (same plugin): `CLAUDE.md` uses it to read the
   analysis when dxpkit is not installed.
2. Copy the analysis to `analyses/` and save each data function's script to `functions/`. With
   dxpkit: `dxp add <name> --dxp analyses/<analysis>.dxp --source functions/<file>.py --function
   "<Function Name>"` creates the source file from the DXP and records the lock. Without
   dxpkit: copy the script from `dxp_inventory.py text` output.
3. Copy `assets/project-CLAUDE.md` to `CLAUDE.md` and replace `<analysis>` and `<approver>`.
4. Build the runner once, unless the `running-spotfire-unattended` skill already did on this
   account:

   ```
   python tools/sfrun.py install
   ```

   Then, in Analyst: new blank analysis, **File > Document properties > Scripts > New**,
   IronPython 3, untick **Execute in transaction**, paste `$DXP_WORKSPACE/runner/
   build_runner_ready.py`, **Run Script**, close with **Cancel**. Open
   `$DXP_WORKSPACE/runner/runner.dxp`, right-click its text area > **Edit text area** >
   **Insert action control**: type Button, display text `Run Pending Job`, action **Script >
   Run Pending Job**, OK, and **File > Save**. The button step is manual because the public
   Spotfire API cannot add an action control. **Not yet tested** in this form.

   Check with `python tools/sfrun.py check`.
5. Optional: `git init`, commit, push, and add the CI workflow from the `setting-up-dxp-ci`
   skill.

## First run on an analysis saved by someone else

The data function shows as untrusted when you first open such an analysis, because its approval
belongs to the other account. The first run of `update_data_function.py` applies the script
through the Spotfire API and approves it for your account. You can also trust it in **File >
Manage trust**.
