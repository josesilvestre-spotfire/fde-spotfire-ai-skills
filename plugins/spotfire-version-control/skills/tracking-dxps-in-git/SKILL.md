---
name: tracking-dxps-in-git
description: Tracks Spotfire DXP files and their data function scripts in Git with dxpkit. Extracts a DXP into readable files, sets up a readable git diff for .dxp files, maps scripts to data functions in dxpkit.yaml, and keeps Git and the DXPs in sync with dxp status, push and pull, where the dxpkit.lock file catches edits made inside Spotfire. Use when a user wants DXPs or data function scripts under version control, wants to see what changed inside a DXP, or finds that Git and an analysis disagree.
compatibility: dxpkit (installed separately, Python 3.10 or newer), Git. Readable diffs also work without dxpkit through the auditing-and-comparing-dxps skill. Windows, macOS or Linux for these commands; trusting changed scripts needs Spotfire Analyst.
metadata:
  maturity: Proven on one machine
---

# Tracking DXPs in Git

A DXP is a ZIP archive, so Git stores it as a binary file. This skill keeps the parts people
edit (data function scripts) as plain files in Git, and makes every DXP change readable.

## Prerequisite: dxpkit

dxpkit is a command-line tool (`dxp`) that extracts, diffs and syncs DXP files without
Spotfire. **It is not distributed with this library.** Install it from its own source into the
Python environment you use for the project:

```
python -m pip install <path or URL of the dxpkit source>
dxp --help
```

Do not copy dxpkit's code into a project or into this library. When dxpkit is not available,
the `auditing-and-comparing-dxps` skill gives a read-only text form, comparison and git diff
driver from the standard library alone; syncing scripts (`status`, `push`, `pull`) needs dxpkit.

## Rules

- **Commit `dxpkit.lock`** with every sync. It records each target's script at the last sync;
  without it, dxpkit cannot tell an edit in Git from an edit in Spotfire.
- **Never overwrite a Spotfire-side edit.** When `dxp status` reports `spotfire ahead` or
  `conflict`, pull and review before anything else. Use `--force` only after a person has
  compared both versions and decided.
- **`dxp push` leaves the function untrusted.** It rewrites the script bytes and keeps the old
  approval stamp, so Spotfire does not run the function until someone trusts it in Analyst
  (File > Manage trust > Review > Trust, refresh, save). To apply a change that must run at
  once, use the `updating-data-functions-with-claude` skill, which applies it through the
  Spotfire API. See [references/script-trust.md](references/script-trust.md).
- **A DXP open in Analyst cannot be replaced.** `dxp push` reports an error for it and leaves
  it untouched. Ask the user to close it; never close their Analyst windows yourself.
- A person reviews every change that reaches a shared analysis, through a pull request or an
  explicit approval.

## Start tracking a data function

```
dxp add <name> --dxp '${ANALYSES}/example_analysis.dxp' --source functions/<name>.py
        --function "<Function Name>"
dxp status                       # in sync
git add dxpkit.yaml dxpkit.lock functions/
```

`dxp add` writes the entry to `dxpkit.yaml`, creates the `.py` source from the script in the DXP
when the file does not exist, and records the lock. `${VARS}` come from the environment, so the
same file works on every machine. The format is in
[references/dxpkit-reference.md](references/dxpkit-reference.md).

## Daily loop

| `dxp status` says | Meaning | Do this |
|---|---|---|
| `in sync` | Git, DXP and lock agree | nothing |
| `git ahead` | the script changed in Git | apply it: `updating-data-functions-with-claude`, or `dxp push` and trust in Analyst |
| `spotfire ahead` | someone saved a change in Spotfire | `dxp pull`, review `git diff`, commit |
| `conflict` | both sides changed | compare both (`dxp push --dry-run` shows the DXP side), merge by hand in the source file, then apply |
| `untracked-diff` | no lock entry and the two differ | decide which side is right with the user, then `pull` or `push --force` |
| `missing` | DXP or function not found | check the path, the `${VARS}` and the function name |

`dxp status` exits 0 only when every pair is `in sync`, so it works as a CI check.

Proven sequence (Analyst 15.0): a change made in Spotfire showed `spotfire ahead`; `dxp push`
refused and printed the Spotfire-side diff; `dxp pull` wrote the script into Git and updated the
lock; `dxp status` then reported `in sync`.

## Readable diffs of .dxp files

```
echo '*.dxp diff=dxp' >> .gitattributes
git config diff.dxp.textconv "dxp textconv"
git config diff.dxp.cachetextconv true
```

`git diff` and the `git log` family (`git log -p`, `git show`) then show the scripts, bindings,
pages and trust stamps inside the DXP as text. Limits and the no-dxpkit alternative are in
[references/git-diff-driver.md](references/git-diff-driver.md). The GitHub web view still shows
a DXP as a binary file.

## Look inside a DXP

```
dxp extract analysis.dxp -o analysis/     # readable files, safe to commit
dxp diff old.dxp new.dxp [--stat]         # what changed between two files
```

`dxp extract` writes data function scripts, definitions and bindings, IronPython and JavaScript
scripts, document properties, data tables, one file per page with each visual's type, table,
axes, marking and layout, and the text-area HTML. Objects are keyed by name, so a plain re-save
in Spotfire gives an empty diff.

## Edits without a dxpkit.yaml

For a one-off script change: extract, edit `data_functions/<name>/script.py`, then
`dxp pack analysis.dxp analysis/ -o analysis_v2.dxp`. `pack` writes data function scripts only
and refuses any other edit in the folder. The packed function needs trust in Analyst, like a
push.

## Merging

Git cannot merge two DXP files. When two branches change the same analysis, keep one DXP, then
apply the other branch's script change to it (through the update tool or `dxp push` and trust).
Keeping scripts in `functions/` means the script itself merges like any other code.

## Proven and not yet tested

Proven with Spotfire Analyst 15.0 on one machine: `dxp add`, `status`, `push`, `pull`,
`validate`, `diff`, `extract`; the `spotfire ahead` refusal; `dxp push` changing only the three
AnalysisDocument copies in the archive and leaving every other entry identical; the untrusted
function after a push and its fix in Manage trust; the textconv driver with `git diff`.

**Not yet tested:** `dxp pack` within these workflows (dxpkit's own notes report that a packed
DXP opens in Analyst); IDE diff views of .dxp files; Git LFS for large DXPs; analyses stored in
the Spotfire library (dxpkit works on local files only).
