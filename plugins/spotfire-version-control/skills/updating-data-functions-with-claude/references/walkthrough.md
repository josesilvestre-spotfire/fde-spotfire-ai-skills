# Walkthrough: a data function update with Git, CI and Claude Code

This walkthrough follows one recorded run of the workflow on Spotfire Analyst 15.0. It shows what
each step prints and where a person is needed. The example analysis and its data are synthetic.

## 1. The problem

Python data functions often hold the engineering logic of a Spotfire analysis, and their code
lives inside the DXP file. When two people change the same DXP, the later save becomes the
current version and nothing merges their changes. No review step sits between editing and
saving, and comparing two library versions of a script means opening each one in Analyst.

The workflow keeps each script in Git and moves scripts between Git and the DXP:

- A change made in Git is reviewed, checked in CI and applied to the DXP by a pipeline or by
  Claude Code.
- A change saved in Spotfire is pulled out of the DXP, compared with the code in Git and
  merged.

Applying a script runs through the Spotfire API in an unattended Analyst session. Claude Code
runs the whole update from one request, and a person steps in only where a policy requires it.

## 2. The project

`analyses/example_analysis.dxp` holds 90 days of oil rate for five wells and one Python data
function, Calculate Column Statistics. It returns one row per well and statistic, shown in a
cross table and a bar chart. Version 1 calculates the mean.

The project holds the analysis, the scripts in `functions/`, a GitHub Actions workflow and three
tools:

- dxpkit (installed separately) reads, compares and syncs DXP files without Spotfire.
- `tools/update_data_function.py` applies and validates a script in an unattended Analyst
  session and saves a staging copy.
- `tools/promote.py` replaces the analysis with the validated staging copy and records the
  script in `dxpkit.lock`.

`dxpkit.yaml` maps each script to its data function:

```yaml
functions:
  column_statistics:
    source: functions/calculate_column_statistics.py
    targets:
      - dxp: analyses/example_analysis.dxp
        function: Calculate Column Statistics
```

## 3. Working from an IDE and CI

`dxp status` compares three things: the script in Git, the script in the analysis and the last
sync recorded in `dxpkit.lock`. It reports `in sync`, `git ahead`, `spotfire ahead` or
`conflict`.

A coefficient of variation was added to the script on a branch in an IDE. `dxp status` showed
`git ahead`. The update tool applied the change in 34 seconds and, after promotion, `dxp status`
reported `in sync`:

```
$ dxp status
git ahead       column_statistics -> analyses/example_analysis.dxp
$ python tools/update_data_function.py analyses/example_analysis.dxp "Calculate Column Statistics" functions/calculate_column_statistics.py
...
new DXP: staging/example_analysis.dxp  PASS
$ python tools/promote.py staging/example_analysis.dxp analyses/example_analysis.dxp
kept the previous version as analyses/.backup/example_analysis.<time>.dxp
promoted staging/example_analysis.dxp to analyses/example_analysis.dxp (validated in reports/<run>)
recorded column_statistics in dxpkit.lock
$ dxp status
in sync         column_statistics -> analyses/example_analysis.dxp
```

With the dxpkit diff driver configured, `git diff` on the analysis file shows the script lines
and the trust stamp that changed inside the DXP.

A GitHub Actions job runs `dxp validate` and `dxp status` on every push, with no Spotfire
needed. A commit that changed only the script failed the check (`git ahead`, exit code 1). The
commit that also carried the applied and promoted analysis passed. Made a required check, this
blocks a merge until the analysis carries the script. The apply step itself needs Analyst, on a
workstation or a self-hosted Windows runner.

A change saved in Spotfire shows as `spotfire ahead`. `dxp push` refuses to overwrite it and
prints the Spotfire-side diff; `dxp pull` copies it into Git for review and merge:

```
$ dxp status
spotfire ahead  column_statistics -> analyses/example_analysis.dxp
$ dxp push
refused      column_statistics -> analyses/example_analysis.dxp  (spotfire ahead): the DXP copy changed outside Git; pull it, or push with --force
$ dxp pull
wrote        column_statistics -> analyses/example_analysis.dxp  (spotfire ahead)
$ dxp status
in sync         column_statistics -> analyses/example_analysis.dxp
```

## 4. Automating the update with Claude Code

Claude Code runs the edit, apply, validate, promote and push steps from one request.
`CLAUDE.md` in the project gives it the procedure (the template is `assets/project-CLAUDE.md`):

1. Read the analysis.
2. Edit the script in `functions/`. Keep the output columns the visuals use.
3. Apply and validate with `tools/update_data_function.py`.
4. Read the report and the page render. Fix and repeat if needed.
5. A person approves every promotion. Ask with the report, the checks and the new values, then
   run `tools/promote.py`.
6. Commit and push.

The session ran in auto permission mode, where a classifier reviews each action within the
organization's managed permission rules. The request:

```
In analyses/example_analysis.dxp, add the sample standard deviation of each well column to
the Calculate Column Statistics data function. Validate the change, promote it and push it to
GitHub.
```

Claude read the analysis and noted that the visuals pick up a new statistic without changes,
because the output is a long table (Column, Statistic, Value). It added two lines for the
standard deviation and started the update tool.

## 5. Applying and validating through the Spotfire API

The update tool started a separate Analyst process on the runner analysis. The runner's job
replaced the script through the Spotfire API, ran the function, rendered every page and saved a
staging copy, in 70 seconds. The output of that run, with step 2 worded as the current tool
prints it:

```
1/5 Python syntax of functions/calculate_column_statistics.py: OK
2/5 data function 'Calculate Column Statistics' found in analyses/example_analysis.dxp
3/5 applying in an unattended Spotfire Analyst session ...
    done in 70 s: script replaced, function run, 1 page(s) rendered, new DXP saved
4/5 validation:
    approved for this account  True
    function executed          True
    table DAILY_PRODUCTION     90 rows, 6 columns
    table COLUMN_STATISTICS    10 rows, 3 columns
5/5 DXP change (dxp diff --stat):
    data_functions/Calculate_Column_Statistics/definition.yaml | +1 -1
    data_functions/Calculate_Column_Statistics/script.py | +5 -2
report: reports/<run>/REPORT.md
page render: reports/<run>/page_01.png
new DXP: staging/example_analysis.dxp  PASS
```

A script applied through the API is approved for the account that ran it, so it ran at once.
`COLUMN_STATISTICS` held 10 rows (5 before the change). Claude read the report and the page render, and
checked the one extra line in the DXP diff: the trust stamp of the changed script.

## 6. Approval required by policy

`CLAUDE.md` requires a person to approve every promotion. Claude asked with the report path,
the checks, the new values and the DXP diff. "Don't promote" leaves the change in staging. This
was the only wait in the run. The request already said "promote", and Claude still asked:
the request does not replace the approval.

## 7. Promote, commit and push

After the approval, Claude promoted, committed and pushed in 18 seconds. The commit holds the
script change, the updated DXP and the report folder (`REPORT.md`, the page render and
`result.json`). The promoted analysis opens without a trust prompt for the account that ran the
update, and shows a Standard Deviation column in the cross table and a Standard Deviation panel
in the bar chart.

## 8. Where a person is needed

| Point | Who | Why |
|---|---|---|
| The request | the requester | names the analysis, the function and the change |
| First session in a folder | the Claude Code user | a one-time folder trust prompt |
| Commands during the run | nobody in auto mode | without auto mode, commands outside the organization's rules ask for approval |
| Promotion | the named approver | `CLAUDE.md`; in a pipeline, the pull request review |
| Trust for other users | each user, or a Script Author | the approval belongs to the account that ran the update; data functions cannot be signed |

## 9. Limitations

- Needs Spotfire Analyst on Windows. The trust approval belongs to the account that ran the
  update.
- Replaces the script of an existing data function. New parameters or bindings need more API
  work.
- The readable DXP diff works with `git diff` and `git log` in a local clone. The GitHub web view
  shows the DXP as a binary file.
- Analyses stored in the Spotfire library are not covered.
- Auto permission mode depends on the organization's settings and does not guarantee safety.
- Tested on one Windows account with Spotfire Analyst 15.0.
