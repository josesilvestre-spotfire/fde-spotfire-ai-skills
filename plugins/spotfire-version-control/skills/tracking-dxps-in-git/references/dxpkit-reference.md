# dxpkit reference

dxpkit is a separate tool, installed from its own source; it is not part of this library. This
page summarizes its documented behaviour (version 0.1.0) for use with the skills.

## Commands

| Command | What it does |
|---|---|
| `dxp extract A.dxp -o folder/` | writes the DXP as readable files; re-extracting into the same folder replaces those files and leaves `.git` and other dot files alone |
| `dxp diff A.dxp B.dxp [--stat]` | unified diff of the two extracted forms; `--stat` lists `file \| +n -m` |
| `dxp textconv A.dxp` | prints the DXP as one text document (the git diff driver) |
| `dxp pack A.dxp folder/ -o B.dxp [--overwrite]` | writes edited data function scripts into a new DXP; refuses any other change in the folder; never modifies `A.dxp` |
| `dxp add NAME --dxp PATH --source PATH [--function F]` | adds a tracked function to `dxpkit.yaml`, creates a missing `.py` source from the DXP, records the lock; refuses when the function is not in the DXP |
| `dxp status [NAME...]` | one line per (function, target): state, name, target; read-only |
| `dxp push [NAME...] [--dry-run] [--force]` | Git to DXPs: writes the source script into each `git ahead` target |
| `dxp pull [NAME...] [--from DXP] [--dry-run] [--force]` | DXPs to Git: writes a `spotfire ahead` target's script into the source |
| `dxp validate` | checks `dxpkit.yaml`, parses `.sfd` sources, checks the Python syntax of every source |
| `dxp init-ci [--force]` | writes `.github/workflows/dxpkit.yml` (see the `setting-up-dxp-ci` skill) |

The sync commands accept `--config PATH`; otherwise `dxpkit.yaml` is searched from the current
folder upward.

Exit codes: 0 success; 1 refused or out of sync (a refusal, `status` not clean, `diff` found
differences, `validate` found problems); 2 unreadable or invalid input, a locked DXP or a bad
config.

## dxpkit.yaml

```yaml
functions:
  column_statistics:                          # key; also the default function name
    source: functions/calculate_column_statistics.py   # .py, or an .sfd exported from Spotfire
    targets:
      - dxp: ${ANALYSES}/example_analysis.dxp  # ${VARS} come from the environment
        function: Calculate Column Statistics  # data function name in the DXP
      - dxp: ${ANALYSES}/example_analysis_copy.dxp
```

- Relative paths resolve against the folder that holds `dxpkit.yaml`.
- An undefined `${VAR}` is an error (exit 2).
- Each key is unique, each entry has one `source`, at least one target, and no (DXP, function)
  pair appears twice.
- One source can feed the same function in several DXPs.

## dxpkit.lock

JSON, committed, sorted keys:

```json
{"functions": {"column_statistics": {"targets": {"${ANALYSES}/example_analysis.dxp":
  {"function": "Calculate Column Statistics", "script_sha256": "..."}}}}, "version": 1}
```

`script_sha256` is the SHA-256 of the script with CRLF converted to LF and trailing newlines
removed, so newlines an editor adds never count as a change.

## Status states

dxpkit compares three hashes per (function, target): source `S`, target `T`, lock `L`.

| Condition | State |
|---|---|
| target file or function missing | `missing` |
| no lock entry, S = T | `in sync` |
| no lock entry, S differs from T | `untracked-diff` |
| S = T | `in sync` |
| S differs from L, T = L | `git ahead` |
| S = L, T differs from L | `spotfire ahead` |
| S, T and L all differ | `conflict` |

What push and pull do per state:

| State | `push` | `pull` |
|---|---|---|
| `in sync` | writes nothing, records the lock | writes nothing, records the lock |
| `git ahead` | writes the DXP | refuses (`--force` overrides) |
| `spotfire ahead` | refuses and prints the DXP-side diff (`--force` overrides) | writes the source |
| `conflict`, `untracked-diff` | refuses (`--force` overrides) | refuses (`--force` overrides) |
| `missing` | refuses | refuses |

Because an `in sync` push or pull records the lock, `dxp pull NAME` after promoting a DXP that
already carries the Git script updates `dxpkit.lock` without writing any other file. Without
that, the next Git edit would show as `conflict` instead of `git ahead`.

## How push writes

- Only data function script bodies are written. The function must already exist with the
  inputs and outputs the script expects.
- The script is replaced in every copy of the analysis inside the archive (Spotfire stores the
  current format and two older ones). Every other archive entry keeps its bytes. This was
  checked on Analyst 15.0 files.
- The result is written to a temporary file, re-read and verified, then moved over the target.
  A failure leaves the target untouched.
- The trust stamp is not changed: see `script-trust.md`.

## Extracted folder

```
data_functions/<name>/script.py         the script
data_functions/<name>/definition.yaml   name, engine, inputs, outputs, trust stamp digest
data_functions/<name>/bindings.yaml     input expressions, output targets, update behaviour
scripts/                                IronPython and JavaScript scripts
document_properties.yaml
data_tables/<table>.yaml                columns, sources, transformations
pages/NN_<page>.yaml                    visuals: title, type, table, axes, marking, layout (% of page)
text_areas/NN_<page>_<k>.html
manifest.json
```

## Known gaps (dxpkit 0.1.0)

- Calculated column expressions are not extracted (calculated columns appear with their kind
  only).
- Document-level script triggers are not extracted.
- TERR (R) data functions are extracted generically and untested.
- Mod visualization axes are best effort.
- Extraction reads the newest analysis copy only.
- Stray files in an extracted folder (for example `__pycache__/`) make `pack` refuse.
- Spotfire library targets are not supported; targets are local files.
