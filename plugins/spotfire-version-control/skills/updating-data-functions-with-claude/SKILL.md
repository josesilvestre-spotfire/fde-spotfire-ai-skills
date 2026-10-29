---
name: updating-data-functions-with-claude
description: Updates the Python script of a Spotfire data function from a Git project. Edits the function file, applies it through the Spotfire API in a staging copy of the DXP inside an unattended Analyst instance, runs it, renders every page and writes a report; a person approves the promotion, then the change is committed and pushed. Use when a user asks to change, fix or extend a data function in a DXP, or to set up a project where Claude Code or an IDE changes data functions without opening Analyst.
compatibility: Windows with Spotfire Analyst 15.0 (signed in through a saved login or single sign-on), Python 3.10 or newer, Claude Code. Git and dxpkit are optional. Proven on one machine.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Updating data functions with Claude

The analysis users open is never edited in place. A change goes through four stages:

1. **Edit** the script file in `functions/`.
2. **Apply and validate** in staging: `tools/update_data_function.py` starts its own Analyst
   process, replaces the script through the Spotfire API, runs the function, renders every page,
   saves `staging/<analysis>.dxp` and writes `reports/<run>/REPORT.md`.
3. **Approve:** a person reads the report and approves the promotion.
4. **Promote, commit, push:** `tools/promote.py` replaces the analysis with the validated copy,
   keeps a backup and records the script in `dxpkit.lock`; then commit and push.

## Rules

- **A person approves every promotion.** Ask with the AskUserQuestion tool and give the report
  path, the checks, the new output values and the script diff. Run `promote.py` only after the
  approval. A request that already says "promote" does not replace it. Without approval, leave
  the change in staging.
- **Apply through the Spotfire API, never by rewriting bytes.** A script set through the API in
  your session is approved for your account and runs at once. A byte replacement (`dxp push`,
  manual ZIP edits) keeps the old approval, so the function opens untrusted and API execution
  silently does nothing. Details: [references/script-trust.md](references/script-trust.md).
- **Leave the user's Analyst session alone.** The update tool starts and ends its own Analyst
  process. Never click into or close an Analyst window the user opened.
- **Keep the outputs.** Visuals are bound to the output parameters and their columns. Change
  them only when the request asks for it, and say which visuals are affected.
- **Text output columns use the object dtype** (`.astype(object)`). With pandas 3 in Spotfire's
  Python, a `str` dtype text column makes Spotfire skip the output table without an error.
- **Unattended sessions** on a managed machine need `claude --permission-mode auto`; project
  allow and ask rules can be ignored there, so the approval step lives in `CLAUDE.md`.

## Setup

Once per project and once per Windows account for the runner:
[references/setup.md](references/setup.md). In short: copy `scripts/` into the project's
`tools/`, copy `assets/project-CLAUDE.md` to `CLAUDE.md`, build the runner analysis once in
Analyst, and set `DXP_WORKSPACE`.

## The procedure

1. Read the analysis: `python tools/dxp_inventory.py text analyses/<analysis>.dxp` (from the
   `auditing-and-comparing-dxps` skill) or `dxp extract`. Note the function's inputs, outputs
   and the visuals bound to the output tables. If `dxp status` reports `spotfire ahead`, run
   `dxp pull` first and show the user the Spotfire-side change.
2. Edit `functions/<function>.py`. Keep the staging block that defines the inputs when the
   script runs outside Spotfire.
3. Apply and validate:

   ```
   python tools/update_data_function.py analyses/<analysis>.dxp "<Function Name>" functions/<function>.py
   ```

   PASS needs three things: the function is approved for this account, it executed, and the
   staging DXP was saved. Exit code 1 means FAIL; read the traceback or the report.
4. Read `REPORT.md` and open every page render. Check the output rows against the request (new
   statistic present, row count as expected, no empty visual). Fix and rerun step 3 until it is
   right.
5. Ask for approval (see Rules). Then:

   ```
   python tools/promote.py staging/<analysis>.dxp analyses/<analysis>.dxp
   ```

   `promote.py` refuses a staging copy without a passing validation record, and refuses when
   the analysis changed after the staging copy was built. It keeps the previous version in
   `analyses/.backup/`. When dxpkit tracks the analysis, it runs `dxp pull` for the promoted
   function, which writes only `dxpkit.lock`, so the next Git edit shows as `git ahead`.
6. Commit `functions/`, `reports/<run>/`, `analyses/` and `dxpkit.lock` with a message that
   states the change, and push. In the summary to the user, list the checks, the new output
   values and the commit.

## The report

`reports/<run>/REPORT.md` holds: source and staging paths with the source hash, PASS or FAIL,
a checks table (syntax, approved for this account, executed, row count per table), the script
diff, every output table of 50 rows or fewer, the page renders and, with dxpkit installed, the
`dxp diff --stat` of the two DXPs. `result.json` holds the same data as JSON.

## Without Claude Code

The tools are plain commands, so the same steps run from an IDE terminal or a pipeline. The CI
side (a check that fails while the analysis does not carry the merged script) is in the
`setting-up-dxp-ci` skill. Git tracking and readable DXP diffs are in the
`tracking-dxps-in-git` skill.

## A full run

[references/walkthrough.md](references/walkthrough.md) follows one recorded run: the project,
the IDE and CI side, the Claude Code request, the tool output, the approval, and where a person
is needed.

## Proven and not yet tested

Proven on one Windows account with Spotfire Analyst 15.0: the apply job (`apply_job.py`), the
API replacement and its approval for the running account, the report, promotion with backup and
hash checks, the commit and push, the approval asked through `CLAUDE.md` in auto permission
mode. Refreshing `dxpkit.lock` with `dxp pull` after promotion was run on copies of a test DXP
(the proven run updated the lock through dxpkit's Python API instead).

**Not yet tested:** this library's runner build (`build_runner.py` plus the button added by
hand); `update_data_function.py` and `sfrun.py` as shipped here on a live Analyst (they reuse
the proven job, launcher and lock code; their offline steps were run). Analyses stored in the
Spotfire library are not covered. New parameters or bindings need more API work.
