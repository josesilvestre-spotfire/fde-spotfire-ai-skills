---
name: building-visualization-mods
description: Builds and reviews Spotfire visualization mods in plain JavaScript. Covers choosing the mod API version, manifest rules that field clients enforce, the render loop and signalRenderComplete, marking, tooltips, popout pitfalls, theming from the Spotfire canvas, layers (API 2.4) and configuring mod visuals and layers from IronPython, plus a headless jsdom test harness and a manifest checker. Ships a working mod with three layers, synthetic data and its test. Use when creating, fixing, testing or packaging a Spotfire visualization mod, or when a mod renders wrongly, stops exporting, loses marking or is refused by a client.
compatibility: Spotfire Analyst 15.0 (layers need 14.8 or later). Node 22+ with jsdom for the harness; Python 3.10+ for the manifest checker.
metadata:
  maturity: Assembled from proven parts, not run as a whole
  spotfire: "15.0"
---

# Building Spotfire visualization mods

A visualization mod is a small web page that Spotfire hosts as a visual. Spotfire hands it data
views, properties and the theme through the mod API; the mod draws and calls back to mark rows.
The rules below come from mods used on Analyst 15.0 and on older field clients.

## Start here

1. Decide the oldest Spotfire the mod must run on and set the lowest `apiVersion` that has the
   features you need: `1.3` for older field clients, `2.4` for layers on 15.0. The manifest's
   allowed fields depend on it ([references/manifest.md](references/manifest.md)).
2. Copy `assets/demo-layers/` as a starting point, or start from an official example (the
   plain JavaScript ones in the spotfire-mods repository). Copy the `<script id="spotfire-loader">`
   block from an official `index.html` unchanged.
3. Write the harness test with the first render, not at the end.
4. Name mod properties and the document properties they bind to by
   [references/naming-standard.md](references/naming-standard.md): one name per binding.

## Rules

1. **`signalRenderComplete()` on every exit path**, including early returns and errors. Export
   and print wait for it and break without an error.
2. **`allRows()` null means expired**: return and keep what is on screen.
3. **Errors go to `mod.controls.errorOverlay`**; missing axes get a friendly placeholder that
   names them.
4. **Native color and marking:** draw with `row.color().hexCode`; click marks `Replace`,
   Ctrl+click `Toggle`; rectangle selections are deduplicated by `row.elementId()`; a background
   click clears the marking.
5. **Pointer events reach the interactive element.** A full-size wrapper over a canvas swallowed
   every hover, drag, click and wheel in Analyst while the jsdom test passed: wrappers get
   `pointer-events: none`, their controls `auto`.
6. **Listeners clean up:** a `window` listener removes itself when its element is gone, or every
   render leaks one.
7. **Date bins by position:** read `BinByDateTime` levels in expression order; Spotfire names the
   day level `DayOfMonth(...)`, so name matching on "month" breaks.
8. **Popouts:** resolve `popout.section || popout.components.section`; keep a local state and
   call `popout.show` again on change; write through property instances refreshed on every render
   (a captured instance silently stops working after one change).
9. **Theme from Spotfire:** colors and fonts from `getRenderContext().styling`, applied as CSS
   variables each render. No web fonts.
10. **Continuous axes stay unaggregated** for point-per-row data: Spotfire puts `Sum()` on a
    dropped column, so the README tells users to set aggregation to None.
11. **Manifest edits need Reload manifest.** Code and CSS sync from the development server; the
    manifest does not.

Code for each rule: [references/rendering-and-interaction.md](references/rendering-and-interaction.md).

## The demo: a mod with layers

`assets/demo-layers/` is a complete, tested project:

| Path | What |
|---|---|
| `src/` | the mod (apiVersion 2.4, type visualization): one card per layer with title, type, row and marking counts, settings; lines for Series layers; clickable rows for Records layers |
| `test-harness.js` | 24 checks against a mock of the API: cards and titles, lines per series, layer versus visual settings, grid, row cap, marking calls, expired view, error path, export (non-interactive), theme, `signalRenderComplete` counts |
| `data/make_demo_csv.py` | synthetic READINGS (two pumps, hourly, three days) and EVENTS (six events) |
| `Configure Demo Layers.py` | IronPython 3: adds the visual and three layers on two tables with limiting expressions, a marking and typed properties |
| `README.md` | test, connect, configure, and the axis wiring table |

The harness passes (`npm test`, jsdom 24 and 29) and the manifest passes the official 2.5 schema.
The demo was built in Analyst 15.0 from a build spec: no failed build step, and the saved DXP
passed the checks of the mod, its layers and its floating action button. The rendered cards were
not recorded, and `Configure Demo Layers.py` as written is **Not yet tested** (it uses the same
public members as that build).

## Layers (apiVersion 2.4)

- In the mod, read `mod.visualization.layers()`; each item has `type`, `title()` (a value with
  `.value`), `data()` (a data view) and `property(name)`.
- From IronPython (public API, 14.8 or later): `mv.Layers.Clear()`, then
  `mv.Layers.AddLayer(type, title)` and set the layer's table, limiting expression, marking, axes
  and properties. A new layer has no marking until you set it, and does not inherit the visual's
  limits.
- Layer titles are unique within the visual; the mod finds layers by title.

Details and code: [references/layers-and-scripting.md](references/layers-and-scripting.md).

## Develop and test

```bash
npm install                       # Node 22+, npm.cmd if PowerShell blocks npm.ps1
npm test                          # the jsdom harness
npm run server                    # development server on port 8090
python scripts/check_mod_manifest.py src --schema node_modules/@spotfire/mods-api/visualization-mods/schema.json
python scripts/check_mod_manifest.py --self-test
```

In Analyst: Tools > Development > Mods development > Connect to development server (or Connect to
file with `src/mod-manifest.json`). Disconnect embeds and signs the mod with your code-trust
certificate.

The checker reports what clients refuse (`type` or a string `allowNonAggregatingMeasures` under
1.x, unknown property types, missing files, a missing loader script) and warns about axes without
a property-control title or with non-aggregating measures. Use `@spotfire/mods-api` at the version
that matches your apiVersion for the schema.

Test with real pointer input at least once (a headless browser, not `dispatchEvent`), because
jsdom skips hit testing. Layout, harness contents and delivery:
[references/develop-and-deliver.md](references/develop-and-deliver.md).

## Deliver

- A zip without `node_modules`, with a README: setup, connection, Reload manifest, an axis wiring
  table with exact expressions, aggregation None per continuous axis.
- A mod connected from a folder stores the folder path in the DXP. For a customer package, save
  the mod as a library item, pin it, and use the library mod.
- Mods cannot read Binary columns; pass geometry as `First(Base64Encode([geometry]))` (accepted
  in Analyst 15.0).
- For buttons on the visual (floating, title bar, context menu), use the `building-action-mods`
  skill. For a whole DXP built from a spec, the `building-spotfire-dxps` skill.
