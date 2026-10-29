# demo-layers: a visualization mod with layers

A small visualization mod (API 2.4, plain JavaScript, no build step) that draws one card per layer
of its visual: the layer's title and type, its row count, how many rows are marked and with which
marking, and the layer's own settings. Series layers draw their values as lines; Records layers
list their rows, and a click marks a row (Ctrl+click adds or removes it).

| Path | What |
|---|---|
| `src/mod-manifest.json` | mod id `demo-layers`, two layer types (Series, Records), typed properties |
| `src/index.html` | the page Spotfire loads; the `spotfire-loader` script is copied unchanged from an official spotfire-mods example |
| `src/main.js`, `src/main.css`, `src/icon.svg` | the mod |
| `test-harness.js` | headless test against a mock of the mod API (jsdom) |
| `data/make_demo_csv.py` | writes the synthetic tables READINGS (144 rows) and EVENTS (6 rows) |
| `Configure Demo Layers.py` | IronPython 3 script that sets up the visual and its three layers |

## Run the test

```bash
npm install        # Node 22 or later; use npm.cmd if PowerShell blocks npm.ps1
npm test           # ends with ALL CHECKS PASSED
```

## Try it in Spotfire (Analyst 15.0)

1. `python data/make_demo_csv.py`, then load `data/csv/READINGS.csv` as READINGS and
   `data/csv/EVENTS.csv` as EVENTS (types are listed in the script header).
2. Connect the mod: Tools > Development > Mods development > Connect to file, and pick
   `src/mod-manifest.json`. Or run `npm run server` and connect to the development server
   (port 8090).
3. Edit > Document Properties > Scripts > New, IronPython 3, paste `Configure Demo Layers.py`,
   run it.
4. The visual shows "Pump readings" and three cards: Readings (pressure and flow of Pump A),
   Daily range (daily minimum and maximum pressure), Events (E01 to E03).
5. Set the document property ViewAsset to Pump B: every card follows. Set BinLevel to 4: Daily
   range shows hourly bins. Click an event: it turns coral and its marking count changes.

The layer setup through IronPython uses the public API that ran in live builds on Analyst 15.0.
This script as a whole is **Not yet tested**.

## Axes

| Layer | Axis | Expression | Aggregation |
|---|---|---|---|
| Readings (Series) | X | `[Timestamp (UTC)]` | None |
| | Values | `[Pressure (psig)], [Flow (bbl/d)]` | None |
| | Series | `<[Axis.Default.Names]>` | |
| Daily range (Series) | X | `Min([Timestamp (UTC)])` | Min |
| | Values | `Min([Pressure (psig)]) as [Pressure min], Max([Pressure (psig)]) as [Pressure max]` | Min, Max |
| | Bin | `<BinByDateTime([Timestamp (UTC)],"Year.Quarter.Month.Day.Hour",${BinLevel})>` | |
| Events (Records) | Key | `<[Event ID]>` | |
| | Attributes | `<[Asset] NEST [Start] NEST [End]>` | |
| | Values | `Max([Severity])` | Max |

When you drop a column on a continuous axis by hand, Spotfire puts `Sum()` on it: set the
aggregation to None wherever the table says None, or point-per-row data is lost.
