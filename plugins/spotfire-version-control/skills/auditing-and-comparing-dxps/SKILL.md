---
name: auditing-and-comparing-dxps
description: Audits Spotfire DXP files without opening Spotfire. Inventories pages, visuals, data functions, scripts, triggers, document properties, tables, markings and colors; compares two versions of an analysis; and checks a whole library folder against design and hygiene rules, grouping file versions and diffing consecutive ones. Use when a user asks what is in a DXP, what changed between two versions, whether analyses follow the design rules, or to review a folder of analyses before a release or a rebuild.
compatibility: Python 3.10 or newer, standard library only, any OS. dxpkit (installed separately) is optional for its extract and diff commands.
metadata:
  maturity: Proven on one machine
---

# Auditing and comparing DXPs

`scripts/dxp_inventory.py` reads the DXP archive directly (read-only) and needs only the Python
standard library. It never modifies a file and never starts Spotfire.

## Commands

```
python scripts/dxp_inventory.py inventory analysis.dxp [--json out.json] [--md out.md]
python scripts/dxp_inventory.py text analysis.dxp [-o analysis.txt]
python scripts/dxp_inventory.py compare old.dxp new.dxp [--stat] [-o changes.diff]
python scripts/dxp_inventory.py check analysis.dxp [--json findings.json]
python scripts/dxp_inventory.py library <folder> -o <report folder> [--recursive]
```

| Command | Output | Exit code |
|---|---|---|
| `inventory` | Markdown summary: pages and visuals (type, table, marking, layout), data functions, scripts and triggers, tables, document properties, colors, markings | 0 |
| `text` | one readable document, one section per page, data function, script and table; also a git diff driver | 0 |
| `compare` | unified diff of the two text documents, section by section; `--stat` adds a summary of added and removed pages, visuals, functions, scripts, tables and properties | 1 when they differ, 0 when not |
| `check` | design-rule and hygiene findings, FAIL, WARN or INFO | 1 when any FAIL |
| `library` | `LIBRARY.md`, plus `text/`, `diffs/` and `checks/` per file | 1 when any FAIL |

Exit code 2 means the input is not a readable DXP.

## Inventory one analysis

Run `inventory` first; it answers most "what is in this DXP" questions. Use `text` when you need
the scripts, axis expressions, controls or text-area HTML. What each field means and where it
is stored in the archive: [references/inventory-format.md](references/inventory-format.md).

## Compare two versions

```
python scripts/dxp_inventory.py compare v3.dxp v4.dxp --stat
python scripts/dxp_inventory.py compare v3.dxp v4.dxp -o v3-v4.diff
```

Read the diff by section:

- `data_functions/<name>/script`: code changes.
- `data_functions/<name>/definition`: inputs, outputs, bindings, update behaviour and the trust
  stamp digest. A script change without a stamp change means the script was written without
  Spotfire, so the function is untrusted until someone trusts it in Analyst.
- `pages/NN_<title>`: visuals added, removed, moved (layout in % of the page), retyped,
  rebound to another table or marking, axis expressions.
- `scripts/`, `triggers`, `document_properties`, `data_tables/`, `colors`.

Objects are keyed by name, not by internal id, so a plain re-save gives no difference. A file
saved again with only a new preview image or new embedded data shows no difference either.

## Check against the design rules

`check` runs the rules that can be read from the file. The rule list, with the reason behind
each and the fix: [references/design-rule-checks.md](references/design-rule-checks.md). The full
design rules (including those that need a person or a running analysis, such as "no empty
visuals") are in the `spotfire-app-design-rules` skill.

Treat FAIL findings as blockers for publishing: local paths with a user folder and
credential-like strings inside the archive, and pages without visuals. Report WARN findings to
the owner with the fix.

## Audit a library folder

```
python scripts/dxp_inventory.py library C:/library-export -o C:/audit/2026-q4 --recursive
```

The command groups files that are versions of one analysis by name (`name_v1.dxp`,
`name_v2.dxp`, `Name (3).dxp`, `name_20261026.dxp`), orders them by version number then file
time, and diffs each version against the previous one. `LIBRARY.md` lists per analysis: every
file with page, visual, function, script and table counts and its FAIL and WARN counts, then a
`--stat` summary of each change. Read `LIBRARY.md` first, then the diffs it names.

For analyses stored in the Spotfire library, export them to a folder first; this skill reads
local files only.

## With dxpkit

When dxpkit is installed (a separate tool, not distributed with this library; see the
`tracking-dxps-in-git` skill), `dxp extract` writes a folder of files per DXP and `dxp diff`
compares two DXPs in its own format. Both routes agree on the changes: on the same four
versions of a test analysis, `dxp diff --stat` and `dxp_inventory.py compare --stat` reported
the same changed scripts with the same line counts and the same unchanged pair. Use
`dxp_inventory.py` when dxpkit is not installed, for colors, controls, triggers and hygiene
checks, and for library audits.

## Use as a git diff driver

```
echo '*.dxp diff=dxp' >> .gitattributes
git config diff.dxp.textconv "python -I <path to this skill>/scripts/dxp_inventory.py text"
```

`git diff` and `git log -p` then show DXP changes as text. The GitHub web view still shows the
file as binary.

## Proven and not yet tested

Tested on DXPs saved by Spotfire Analyst 15.0: four versions of a one-page test analysis with a
Python data function (results match dxpkit), two synthetic example builds (a two-page tear sheet
with a KPI chart and nine tables; a mod with three layers), and nine larger analyses with up to
11 pages, 77 visuals, 17 data functions, 32 scripts, 23 property triggers and 179 text-area
controls (all read without error, 1 to 12 seconds each). Used as a textconv driver in a scratch
Git repository.

**Not yet tested:** DXPs saved by Spotfire versions before 14.6; TERR data functions; analyses
with bookmarks, map charts with many layers or information links.
