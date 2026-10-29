# Spotfire data function updates

<!-- Template from the updating-data-functions-with-claude skill. Copy it to the project root as
CLAUDE.md and replace <analysis> and <approver> with your values. -->

This project holds the Spotfire analysis `analyses/<analysis>.dxp` and the tools that change its
Python data functions without anyone opening Spotfire Analyst. The script of each data function
is kept in `functions/`, and `dxpkit.yaml` maps each script to its data function in the analysis.

## How to change a data function

1. Read the current state of the analysis:
   `python tools/dxp_inventory.py text analyses/<analysis>.dxp -o .extract/<analysis>.txt`
   (or `dxp extract analyses/<analysis>.dxp -o .extract/<analysis>` when dxpkit is installed).
   It shows each data function's script, inputs, outputs and bindings, the data tables, and the
   visuals on each page.
2. Edit the script in `functions/`. Keep the output parameters and their columns unless the
   request says otherwise, because the visuals are bound to them. Text output columns must have
   the object dtype (`.astype(object)`): with pandas 3, a text column of the `str` dtype makes
   Spotfire skip the output table without an error.
3. Apply and validate the change in staging:
   `python tools/update_data_function.py analyses/<analysis>.dxp "<Function Name>" functions/<file>.py`
   The tool runs Spotfire Analyst unattended in its own process, replaces the script through the
   Spotfire API, runs the function, renders every page and saves `staging/<analysis>.dxp`. It
   writes `reports/<run>/REPORT.md` with the checks, the output rows and the page renders.
4. Read the report and look at every page render. If the function did not run or the output is
   wrong, fix the script and run step 3 again.
5. Promotion policy: <approver> approves every promotion. Ask the user with the AskUserQuestion
   tool, giving the report path, the checks, the new output values and the script diff, and run
   the next command only after they approve:
   `python tools/promote.py staging/<analysis>.dxp analyses/<analysis>.dxp`
   A request that already says "promote" does not replace this approval. If the user does not
   approve, leave the change in staging and stop.
6. Run `dxp status`; it must report `in sync`. Commit `functions/`, `reports/`, `analyses/` and
   `dxpkit.lock` with a message that states the change, and push.

## Rules

- Never edit `.dxp` files directly, and never use `dxp push` for a change made here. Only
  `tools/update_data_function.py` writes analyses, through Spotfire. A byte replacement keeps the
  old trust approval, so the function opens untrusted and does not run.
- Never close or click into Spotfire Analyst windows that the user opened. The update tool
  starts and ends its own Analyst process.
- If `dxp status` reports `spotfire ahead`, someone changed the function in Spotfire: run
  `dxp pull` to copy that version into `functions/` and show the user the diff before editing.
- No other Python commands are needed: the update tool checks the syntax and runs the script in
  Spotfire.
- In the final summary, list the checks from the report, the new output values and the commit.
