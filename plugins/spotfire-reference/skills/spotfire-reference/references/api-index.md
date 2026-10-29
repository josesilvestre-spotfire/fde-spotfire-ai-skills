# Spotfire API index

An index of the public Spotfire Analyst API, generated from your own Analyst install, so that every
Spotfire member a script uses is checked against the version you run. No index ships with this
library: you generate it once per Analyst version.

Status: the query script (`scripts/sfapi.py`) was tested on an index of Spotfire Analyst 15.0 (core
build 71.0.22206.3863). The generator (`scripts/dump_api.ps1`) is the generator that produced that
index, with the non-public parts removed; this version of it is **Not yet tested** as a whole.

## Why check members

IronPython resolves .NET members at run time. A misspelled or missing member fails only when that
line runs, and a member set on the wrong object can fail without a message. Check every Spotfire
type and member against the index before you write it into a script, a builder or a data function
wrapper. Never write a member from memory.

## Generate the index

Requirements: Windows, Windows PowerShell 5.1 (`powershell.exe`), a Spotfire Analyst install.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\dump_api.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\dump_api.ps1 -SpotfireHome "<folder that holds Spotfire.Dxp.exe>" -OutDir "<folder>"
```

| Argument | Default |
|---|---|
| `-SpotfireHome` | `$env:SPOTFIRE_HOME`, else the newest `%LOCALAPPDATA%\Spotfire\<version>` folder that holds `Spotfire.Dxp.exe` |
| `-OutDir` | `$env:DXP_WORKSPACE\api`; the script stops and asks for `-OutDir` when `DXP_WORKSPACE` is not set |
| `-ProductVersion` | read from the install folder name (`15.0.0` gives `15.0`) |
| `-ExtraAssembly` | extra assembly files to index, for example an extension of your own |

What it does:

- Loads the `Spotfire.Dxp.*.dll` assemblies of the newest `Modules\Core_<build>` folder into the
  PowerShell process by static reflection. Spotfire is not started, no running Spotfire process is
  touched and nothing is sent over the network.
- Writes `spotfire-api-<coreBuild>.json` (about 3 to 4 MB for 15.0): every public type with its
  constructors, properties, methods, fields, events and enum values, base types and interfaces,
  the Spotfire version that introduced each member (`apiVersion`) and obsolete markers.
- Leaves out every type and member that Spotfire marks for internal use. The index holds the
  supported public API only.
- Copies the XML documentation files Spotfire ships next to its assemblies (for example
  `Spotfire.Dxp.Data.Formats.Sbdf.xml`), when present.

The index is derived from licensed Spotfire assemblies. Keep it in your workspace and out of shared
repositories (add `api/` to `.gitignore`).

Regenerate the index after every Analyst upgrade, then run `python scripts\sfapi.py selftest`.

## Query the index

`scripts/sfapi.py` needs Python 3.8 or later and the standard library only. It finds the index in
this order: `--index FILE`, the `SFAPI_INDEX` environment variable, the newest
`$DXP_WORKSPACE/api/spotfire-api-*.json`.

| Command | Use it to |
|---|---|
| `has Type.Member [...]` | confirm members exist (inherited members and interfaces included). Exit code 0 when every spec exists. `--set` also requires a public setter; `--stdin` reads one spec per line; `--quiet` prints only misses |
| `has "Type.Method(String, Int32)"` | confirm one overload (`*` matches any one parameter) |
| `chain "<expression>"` | resolve an IronPython expression step by step from the script globals `Document` and `Application`, with indexers, calls, generic calls (`As[LineChart]()`) and out parameters returned as tuples |
| `type Name [--inherited]` | print a type: import line, base chain, constructors, properties, methods, fields, events, nested types, XML doc summaries |
| `enum Name` | list enum values (or the static members of a pseudo-enum class such as `ScriptLanguage`) |
| `search <regex> [--members]` | find type names, or `Type.Member` names with `--members`; filter with `--kind` and `--ns` |
| `ns [<namespace>]` | list namespaces, or the types in one |
| `info`, `stats` | index metadata, counts per assembly and namespace |
| `selftest` | run spot checks recorded on Spotfire 15.0 against the current index |

Examples:

```bash
python scripts/sfapi.py has LineChart.XAxis.Expression ScriptDefinition.Create
python scripts/sfapi.py has "HtmlTextArea.HtmlContent" --set
python scripts/sfapi.py chain 'Document.Data.Tables["PUMP_DATA"].Columns'
python scripts/sfapi.py chain 'Document.ActivePageReference.Visuals.AddNew[LineChart]().XAxis.Expression'
python scripts/sfapi.py type DataFunctionDefinitionBuilder
python scripts/sfapi.py enum PageNavigationMode
```

Reading the output:

- `[api 14.6.0]` is the Spotfire version that introduced the member. When your analysis must open
  in an older Analyst, use only members at or below that version.
- `OBSOLETE: ...` carries Spotfire's replacement advice.
- `extension: needs clr.ImportExtensions` marks an extension method: call
  `clr.ImportExtensions(<namespace>)` in IronPython before you use it.
- `exists, but not settable` from `has --set` means the property is read-only. Example:
  `DataProperty.Description` (set it when the property is created).
- A step marked DYNAMIC in `chain` follows an `Object` result; the index cannot check what comes
  after it.

## Use it in a workflow

1. While writing a script, run `has` (or `chain` for whole expressions) on every Spotfire member.
2. For a long script, collect the members in a text file and run
   `python scripts/sfapi.py has --stdin --quiet < members.txt`. Fix every line it prints.
3. Record the index's `coreBuild` (from `info`) next to the script or build spec, so a later
   reader knows which version it was checked against.

The index says what exists, not how it behaves. For behaviour, read `proven-behaviour.md`.
