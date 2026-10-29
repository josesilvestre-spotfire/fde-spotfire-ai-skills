# A readable git diff for .dxp files

Git can turn a binary file into text before it diffs it (a textconv driver). With a driver for
`.dxp`, `git diff` shows what changed inside the analysis.

## With dxpkit

```
echo '*.dxp diff=dxp' >> .gitattributes
git config diff.dxp.textconv "dxp textconv"
git config diff.dxp.cachetextconv true
```

- Commit `.gitattributes`. The `git config` lines are per clone (add `--global` to set them for
  every repository); every collaborator runs them once.
- `cachetextconv` stores the converted text in Git's notes, so repeated diffs of the same
  commits are fast.

Proven: in a clone with this setup, `git diff <commit-a> <commit-b> -- analyses/<analysis>.dxp`
showed the changed script lines and the changed trust stamp inside the DXP.

## Without dxpkit

The `auditing-and-comparing-dxps` skill's `scripts/dxp_inventory.py` has a `text` command that
works as a driver with the Python standard library only:

```
git config diff.dxp.textconv "python -I <path to the skill>/scripts/dxp_inventory.py text"
```

Its text lists pages, visuals, data functions (script, inputs, outputs, trust stamp digest),
scripts, document properties, tables, markings and colors. It was run as a driver in a scratch
repository over four versions of a test analysis: `git diff` and `git log -p` showed the script
and stamp changes.

## Where it applies

- Git runs textconv for `git diff` and the `git log` family (`git log -p`, `git show`).
- `git diff --stat` still reports the DXP as a binary file (`Bin <old> -> <new> bytes`).
- The GitHub web view (commits, pull requests) shows the DXP as binary. Put the readable change
  in the pull request description, or commit the extracted folder or a text form next to the
  DXP.
- IDE diff views: **Not yet tested.**
- Merges: textconv does not make DXPs mergeable. Git treats a conflicting DXP as a binary
  conflict.

## What a diff tells you

- A script change with no stamp change: the script was written into the DXP without Spotfire
  (`dxp push` or `dxp pack`). The function is untrusted until someone trusts it in Analyst.
- A script change with a new stamp: the change was made in Spotfire or applied through the
  Spotfire API.
- Trusting a pushed function in Analyst and saving did not change the stamp digest in the
  observed run (Analyst 15.0). A diff therefore cannot show whether a function has been
  trusted since; check in Analyst with File > Manage trust.
- No difference at all although the file bytes changed: a re-save with no change to the parts
  the driver shows (for example a new preview image or new embedded data).
