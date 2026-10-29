## Headless runs

<!-- Add this section to the project's CLAUDE.md (template from the setting-up-dxp-ci skill).
It extends the procedure from the updating-data-functions-with-claude skill. -->

A run is headless when the environment variable `CLAUDE_HEADLESS` is `1` (a CI job or another
unattended start). Nobody can answer a question during such a run, so:

1. Create a branch named `data-function/<short description>` before you change anything.
2. Follow "How to change a data function" up to and including step 4 (edit, apply and validate
   in staging, read the report and the page renders).
3. Do not run `tools/promote.py` and do not change anything in `analyses/`. Promotion needs a
   person's approval, and in a headless run that approval is the pull request review.
4. Commit the script in `functions/` and the folder `reports/<run>/`, push the branch, and open
   a pull request with `gh pr create`. Put in the description: the request, PASS or FAIL, the
   checks table and the output values from `REPORT.md`, and the line "Promotion pending: a
   reviewer approves this pull request, then promotes with tools/promote.py".
5. If validation fails twice, stop: push the branch with the report and open the pull request as
   a draft that states the failure.
6. Never push to the default branch, never merge, never use `--force` with git or dxp.
