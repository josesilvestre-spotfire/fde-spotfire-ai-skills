# Runner setup

You do this once per Windows account. Afterwards every job runs without anyone working in
Analyst.

## What you need

- Windows with Spotfire Analyst 15.0. Analyst must start without a login prompt: sign in once
  with "remember me", or use single sign-on.
- Python 3.10 or newer on the PATH.
- `DXP_WORKSPACE` set to a folder you own, for example a `Spotfire` folder under your
  documents. The runner uses `$DXP_WORKSPACE/runner/` and `$DXP_WORKSPACE/jobs/`.
- `SPOTFIRE_HOME` only when Analyst is not installed under `%LOCALAPPDATA%\Spotfire\<version>`
  or `%ProgramFiles%\Spotfire\<version>`.

## Steps

1. Copy the runner sources:

   ```
   python scripts/sfrun.py install
   ```

   It writes `runner_job.py`, `runner_autoclick.js`, `build_runner.py`, `build_job.py` and
   `build_runner_ready.py` (the builder with your runner folder filled in) to
   `$DXP_WORKSPACE/runner/`.

2. Build the runner in Analyst:
   1. Start Analyst and create a new, blank analysis (no data).
   2. Open **File > Document properties > Scripts**, click **New**, choose **IronPython 3** and
      untick **Execute in transaction**. Saving from a script fails inside a transaction.
   3. Paste the contents of `build_runner_ready.py` and click **Run Script**.
   4. Close the script dialogs with **Cancel**. Cancel undoes the script's changes in the open
      analysis (Analyst 15.0 behaviour), but the two files the script saved stay on disk:
      `blank.dxp` (the empty base for build jobs) and `runner.dxp`.

3. Add the button by hand. The public Spotfire API has no call that adds an action control to
   a text area, so this step stays manual. **Not yet tested** in this exact form; the proven
   runner had the same button.
   1. Open `$DXP_WORKSPACE/runner/runner.dxp` in Analyst.
   2. Right-click the Runner text area and choose **Edit text area**.
   3. Click **Insert action control**. Choose the control type **Button**, type the display
      text `Run Pending Job` (the JavaScript looks for this exact text), select the action
      **Script** and the script **Run Pending Job**. Click **OK**.
   4. Close the editor and choose **File > Save**.
   5. If Analyst shows a trust prompt for the scripts, choose **File > Manage trust > Trust
      all** and save again. Scripts you created through the API in your own session are already
      approved for your account.

4. Check:

   ```
   python scripts/sfrun.py check
   python scripts/sfrun.py render "%DXP_WORKSPACE%\runner\blank.dxp"
   ```

   `check` must list every file as present. The render job must end with `job status: done` and
   one page image.

## Why a button and a JavaScript

Analyst has no command line switch that runs a script. A text area can run JavaScript when it
renders, and JavaScript can click an action control, which runs its IronPython script. The
script reads `job.json` next to `runner.dxp`; with no pending job it does nothing, so you can
open `runner.dxp` by hand at any time.

## Moving or sharing the runner

`runner.dxp` finds `job.json` through the path it was loaded from, so you can move the runner
folder. Do not copy `runner.dxp` to another Windows account: script approval belongs to the
account that created or trusted the scripts. Each account builds its own runner.
