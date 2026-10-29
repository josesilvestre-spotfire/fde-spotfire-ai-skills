# Mod Layers Demo: example app for visualization mods with layers

The smallest app that uses every part of the standard engine's visualization-mod support
(references/spec-format.md "Visualization mods"). The data is synthetic.

What it builds, on one page "Layers":

- one visual of the visualization mod `demo-layers`, "Readings and events", on READINGS, legend
  hidden, with typed mod properties (`heading` string, `showGrid` boolean, `lineWidth` double,
  `maxRows` integer) and three layers on two tables (below);
- a table "Marked events" on EVENTS that shows the events marked with Event Pick.

The spec also names a FloatingButton action trigger that runs `next-asset` of the action mod
`demo-layers-actions`. No public API adds an action trigger, so it is a manual step: the build log
lists it as a TODO line and `build/MANUAL-STEPS-standard.md` says how to add it.

| layer | type | table | marking | what it exercises |
|---|---|---|---|---|
| Readings | Series | READINGS | none | where clause with `${ViewAsset}`; X a bare column (`[Timestamp]`); Values two measures (`[Pressure (psig)], [Flow (bbl/d)]`); Series `<[Axis.Default.Names]>`; layer properties string and double |
| Daily range | Series | READINGS | none | aggregated X; Values with aliases; Bin `<BinByDateTime(...,${BinLevel})>`; `useFiltering` false; boolean layer property |
| Events | Records | EVENTS | Event Pick | Key `<[Event ID]>`; Attributes from a list (`<[Asset] NEST [Start] NEST [End]>`); Values `Max([Severity])`; the only markable layer |

## Files

| path | what |
|---|---|
| `spec.json` | the app spec (`vizMods`, `actionMods`, the mod visual with its layers and action trigger) |
| `data/make_demo_csv.py` | writes `data/csv/READINGS.csv` (144 rows: Pump A and Pump B, hourly over three days) and `data/csv/EVENTS.csv` (6 events, three per pump); standard library only, same output on every run |
| `data/READINGS.sbdf`, `data/EVENTS.sbdf` | the tables, written by `scripts/sbdf_export.py` with Spotfire's Python (commands in `make_demo_csv.py`) |
| `mods/demo-layers/` | the visualization mod (API 2.4, plain JavaScript, no build step): `mod-manifest.json`, `index.html`, `main.css`, `main.js`, `icon.svg`. It draws one card per layer: title, type, rows, marked rows and marking, the layer's properties; a line chart for Series layers; a clickable row list for Records layers (click marks, Ctrl+click toggles) |
| `actionmod/` | the action mod (API 2.5, no build step): `mod-manifest.json`, `build/next-asset.js` (reads ViewAsset, writes the next asset of its `Assets` argument), `icon.svg`, `icons/next-asset.svg` |

Document properties: `ViewAsset` (String, "Pump A": the asset every layer shows) and `BinLevel`
(LongInteger, 3: the time bin of the Daily range layer; 3 = day, 4 = hour).

`dxpgen validate` warns that the page has no filter layout (two tables, no `filters`). The example
keeps Spotfire's default filter panel on purpose, so the build does not depend on the filter-layout
feature.

## Build, run, verify

The builder uses a mod that the analysis already lists (embedded, installed or pinned). Before you run
it, either pin or install `demo-layers` in your library, or, in the new analysis with starter data,
add the mod once (Tools > Development > Mods development > Connect to file > `mods/demo-layers/mod-manifest.json`)
and keep the visual it adds on the starter page. The second route is **Not yet tested** as a builder
route. When the mod is not listed, the builder puts a placeholder text area `[mod: demo-layers]` where
the visual goes and logs a TODO line.

Copy the folder to `$DXP_WORKSPACE/apps/ModLayersDemo`, then from the skill folder:

```
python scripts\dxpgen.py validate ModLayersDemo
python scripts\dxpgen.py release ModLayersDemo --version v0.1 --notes "Visualization mod with layers"
```

Run `apps\ModLayersDemo\versions\v0.1\build\build_ModLayersDemo_v0.1_standard.py` unattended with the
`running-spotfire-unattended` skill, or paste it in Analyst 15.0: new analysis with starter data,
Edit > Document Properties > Scripts > New, IronPython 3, untick "Execute in transaction", paste,
Run Script, close with Cancel. Trust the mod when asked. Then File > Open the saved
`Mod Layers Demo standard.dxp` (answer No to saving the open one).

What to look at:

1. Build log: `OK viz mod demo-layers 1.0.0 (embedded or pinned)`, no FAILED lines, and one TODO line
   per manual step (the action trigger and the action mod). The saved DXP has one page, "Layers": the
   starter page is renamed "... (starter)" during the build and removed after "Layers" is built.
2. The mod shows "Pump readings" and three cards: Readings (pressure and flow of Pump A, two
   lines), Daily range (daily minimum and maximum pressure of Pump A) and Events (E01, E02, E03,
   marking Event Pick). The visual shows its title and no legend.
3. Click an event row: it is marked and "Marked events" lists it.
4. Set BinLevel to 4 (Edit > Document Properties > Properties): Daily range shows hourly bins.
5. Add the floating button by hand (MANUAL-STEPS), save, then verify:

```
python scripts\verify_dxp.py check "$DXP_WORKSPACE\apps\ModLayersDemo\versions\v0.1" --dxp "$DXP_WORKSPACE\apps\ModLayersDemo\versions\v0.1\build\Mod Layers Demo standard.dxp"
```

Every mod line should PASS: mod id and version, "mod embedded in the DXP", "embedded mod is the one
the visual uses", one "embedded file" line per file of `mods\demo-layers`, the mod properties and
their types, "mod layers (type, title, in order)", and per layer its type, table, marking,
filtering, where clause, axes and properties. "action trigger" is a WARN until you add the button.
