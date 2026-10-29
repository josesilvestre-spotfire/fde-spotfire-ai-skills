---
name: spotfire-reference
description: Lookups for Spotfire Analyst work. Holds proven Analyst behaviour with the version each fact was proven on and the symptom of getting it wrong, a generator that writes an index of the public Spotfire API from the user's own Analyst install plus a query script that checks members against it, the library's naming standard, and the canonical App Brief and Logic Spec formats. Use it before writing anything Spotfire runs (IronPython, data functions, text-area HTML), when a member or behaviour is in doubt, when naming Spotfire objects, or when writing or reading an App Brief or Logic Spec.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Spotfire reference

Reference files that the other skills of this library load when they need them. Load only the
file the current step needs.

## Reference files

| File | Load it when |
|---|---|
| [references/proven-behaviour.md](references/proven-behaviour.md) | You write or debug a data function, IronPython script, text-area HTML, visual configuration, mod or save step, or a symptom looks like Spotfire behaving unexpectedly (a missing output table, a blank map, a control that vanished, an untrusted function, a slow click). Each fact gives the version it was proven on and the symptom of getting it wrong. |
| [references/api-index.md](references/api-index.md) | You need to know whether a Spotfire type or member exists in the user's Analyst version, or you are about to generate or query the API index. |
| [references/naming-standard.md](references/naming-standard.md) | You name document properties, data functions and their parameters, scripts, tables, columns, pages, markings, filtering schemes or visual titles, or you check names before delivery. |
| [references/app-brief-format.md](references/app-brief-format.md) | You write, read or check an App Brief (`app-brief.md`). |
| [references/logic-spec-format.md](references/logic-spec-format.md) | You write, read or check a Logic Spec (`logic-spec.md`), or reconcile built outputs against it. |

The naming standard and the two formats are the library's canonical copies. Skills that use them
carry byte-identical copies; change them here and copy the change to every skill that carries one.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `scripts/dump_api.ps1` | Reads the public Spotfire API from the user's Analyst install by static reflection (Spotfire is not started) and writes the index. Types and members Spotfire marks for internal use are left out. | `spotfire-api-<coreBuild>.json` and shipped XML doc files in `-OutDir` (default `$DXP_WORKSPACE\api`) |
| `scripts/sfapi.py` | Queries the index: `has`, `chain`, `type`, `enum`, `search`, `ns`, `info`, `stats`, `selftest`. Standard library only. | Nothing |

Generate the index once per Analyst version:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\dump_api.ps1
python scripts\sfapi.py selftest
```

Then check members before you write them:

```bash
python scripts/sfapi.py has LineChart.XAxis.Expression "HtmlTextArea.HtmlContent" --set
python scripts/sfapi.py chain 'Document.Data.Tables["PUMP_DATA"].Columns'
```

`api-index.md` has every argument, the output format and how to read the version flags.

## Environment

| Variable | Used for |
|---|---|
| `SPOTFIRE_HOME` | The Analyst install folder that `dump_api.ps1` reads (the folder that holds `Spotfire.Dxp.exe`) |
| `DXP_WORKSPACE` | Where the index is written and found (`$DXP_WORKSPACE/api/`) |

When a variable is not set, ask the user for the folder instead of guessing a path.

## Rules

- Check every Spotfire member against the index before you write it. The index says what exists;
  `proven-behaviour.md` says how it behaves.
- Use only the public API. The index leaves out non-public types and members on purpose.
- State the Spotfire version when you rely on a fact, and mark anything you have not seen on a
  live Analyst as **Not yet tested**.
- Do not commit the generated index to a shared repository; it is derived from licensed
  Spotfire assemblies.
