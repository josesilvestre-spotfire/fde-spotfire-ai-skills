---
name: writing-spotfire-ironpython
description: Writes and reviews IronPython 3.4 scripts for Spotfire Analyst documents. Covers document properties (creating, reading, writing), button scripts with parameters, page navigation, property-change triggers, data function run chains, transactions and the compile-once pattern that makes trigger-driven pages fast, and ships a linter for IronPython 3.4 syntax and a stub generator. Use when writing, fixing, speeding up or reviewing any script that uses the Spotfire.Dxp API inside an analysis, including scripts behind text-area buttons and property triggers.
compatibility: Spotfire Analyst 15.0 (IronPython 3.4). The bundled tools need Python 3.10+ and no packages.
metadata:
  maturity: Assembled from proven parts, not run as a whole
  spotfire: "15.0"
---

# Writing Spotfire IronPython scripts

Document scripts run inside Analyst (and Web Player) in IronPython 3.4, with the analysis as the
global `Document` and the application as `Application`. Script parameters arrive as globals too.
Errors inside the client are opaque and every wrong guess costs a round trip, so the rules below
favour checking before running.

## Rules

1. **Python 3.4 syntax.** IronPython 3.4 targets the Python 3.4 language: no f-strings, walrus,
   annotations, `async`, `{**x}`, `[*a, *b]` or `f(*a, *b)`. CPython packages (numpy, pandas)
   cannot be imported; numeric work belongs in a data function (the
   `writing-spotfire-data-functions` skill).
2. **Verify every Spotfire member before you use it.** Check it against the API index generated
   from the user's own install (the `spotfire-reference` skill) or the public API reference.
   Never guess an overload. If you cannot verify a member, mark the line `# UNVERIFIED` and list
   it for the user; the linter warns about leftovers.
3. **No `print`.** Write status to a String document property that a label shows.
4. **Spaces, never tabs.** Spotfire stores a tab as `_x09` in the script text.
5. **Idempotent.** A script can run twice without harm: check before you create (properties,
   scripts, columns), set a value only when it differs.
6. **Look up by name.** Pages and visuals by title (and type), tables, columns and markings by
   name. Never by index.
7. **Do not change a collection while you iterate it** (`Document.Data.Tables`, `page.Visuals`).
8. **Handle read-only contexts.** Wrap a change that can hit a read-only member or context in
   `try`/`except` and report the problem in the status property instead of swallowing it.
9. **Name by the naming standard** ([references/naming-standard.md](references/naming-standard.md)):
   scripts Title Case verb + object (`Reset Filters And Marking`), document properties
   PascalCase, script parameters camelCase unless they carry a property's value. Keep one name per
   binding across properties, data function parameters, controls and scripts: a mismatch fails
   without an error.

## Where scripts run

| Host | How it is wired | Notes |
|---|---|---|
| Setup script | Edit > Document Properties > Scripts, run once | creates properties and other one-time structure |
| Text-area button or link | the action control's script, with values for its parameters | the most common host |
| Property trigger | Edit > Document Properties > Properties > select the property > Script... > run the script when the value changes | one script per property; set it up by hand (below) |
| Visual title-bar or floating button, context menu | action-mod scripts only | title-bar buttons render only for action-mod scripts, never for IronPython (live, 15.0); use the `building-action-mods` skill |

### Running a script from the editor

In the script editor, IronPython 3 is the language and "Execute in transaction" is on by default
(one undo step, faster display updates). Closing the editor with **Cancel** undoes the changes the
script made to the open document; use **OK** to keep them. A builder that saves its own DXP can
be closed with Cancel on purpose, so the builder script is not stored in the analysis.

### Property triggers

- The trigger runs when the transaction that changed the property completes. A control, a script
  or a data function output that writes the property all fire it.
- Spotfire 15.0 has no public API to create a trigger, so set it up in the dialog above (dialog
  labels can differ slightly between versions) and list it in the setup guide. The
  `building-spotfire-dxps` skill reports triggers as manual steps for the same reason.
- Give trigger scripts no parameters, and design cascades so they end (see
  [references/performance.md](references/performance.md)).
- Trigger scripts are outside the data function dependency graph, so a trigger that writes a
  property a data function reads is not a cyclic dependency.

## The standard script set

| Script | Asset | What it does |
|---|---|---|
| `Create Document Properties` | `assets/scripts/Create Document Properties.py` | creates every property with type, default and description; the list is the app's state contract |
| `Run All Data Functions` | `assets/scripts/Run All Data Functions.py` | runs the data functions in dependency order with `ExecuteSynchronously()` |
| `Go To Page` | `assets/scripts/Go To Page.py` | opens a page by title (parameter `pageTitle`) |
| `Reset Filters And Marking` | `assets/scripts/Reset Filters And Marking.py` | resets every filtering scheme and clears one marking (parameter `markingName`) |

Every member these scripts use is in the public 15.0 API index, and the patterns are the ones used
in live builds. The four files as written have not run in Analyst: **Not yet tested**.

The file stem is the script name, so each file maps to one document script. A new data
function is done when it is in its file, in the run chain and in the setup guide.

## Document properties

```python
from Spotfire.Dxp.Data import DataProperty, DataPropertyAttributes, DataPropertyClass, DataType
from System import Double

registry = Document.Data.Properties
if not registry.ContainsProperty(DataPropertyClass.Document, "TargetEfficiencyPct"):
    prototype = DataProperty.CreateCustomPrototype(
        "TargetEfficiencyPct", "Efficiency target in percent", Double(65.0), DataType.Real,
        DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated)
    registry.AddProperty(DataPropertyClass.Document, prototype)

Document.Properties["TargetEfficiencyPct"] = 70.0     # write (fires its trigger)
value = Document.Properties["TargetEfficiencyPct"]    # read
```

- `DataProperty.Description` is read-only after creation: the description is the second argument
  of `CreateCustomPrototype`.
- Pass the default as the exact .NET type (`Int32` Integer, `Int64` LongInteger, `Double` Real).
- In an analysis built from a spec, the spec creates the properties and app scripts only set
  values.

More patterns (pages, visuals, markings, filters, data functions, script upserts, transactions,
expression pitfalls): [references/api-patterns.md](references/api-patterns.md).

## Buttons and navigation

- Prefer native actions: a link or button with a go-to-page action, or a data function refresh
  action, needs no script.
- A button script takes its inputs as script parameters (String, Integer, Real, Boolean, Page,
  Visualization, DataTable, ...). Set the values on the control, so one script serves several
  buttons.
- Open a page with `Document.ActivePageReference = page`, where `page` was found by title.

## Speed

Pages driven by many triggers feel slow mostly because Spotfire prepares each stored script again
on every run. Measured in Analyst 15.0: 0.65 to 1.3 s per run for a large script, about 50 ms with
a compile-once stub.

```bash
python scripts/make_compile_once_stub.py "Update Pump Page" "scripts/Update Pump Page.py" > stub.py
```

Also: batch changes in one transaction, set reference layers and colors only when they changed,
avoid schema changes, and prefer one trellised chart over many charts. Numbers and details:
[references/performance.md](references/performance.md).

## Check before you deliver

```bash
python scripts/lint_ironpython.py --self-test
python scripts/lint_ironpython.py scripts/             # every .py file in the folder
python scripts/make_compile_once_stub.py --self-test
```

The linter reports syntax newer than Python 3.4, `print`, tabs, CPython-only imports, lookups by
index, `.Description` assignments, `# UNVERIFIED` leftovers and non-ASCII characters. It does not
know the Spotfire API: member checks stay with rule 2.

Deliver each script with a wiring table: script, host (button, link, trigger, setup), parameters
and their values, properties read and written, data functions run.
