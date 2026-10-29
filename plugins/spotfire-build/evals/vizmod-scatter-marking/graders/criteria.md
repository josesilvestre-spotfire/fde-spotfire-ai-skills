---
type: llm
weight: 1
---

Grade the response and the files under `scatter-mod/`. Pass when all of these hold; list every
criterion that fails.

1. The manifest declares `"apiVersion": "1.3"` and has no top-level `"type"` field; any
   `allowNonAggregatingMeasures` is the boolean `true` (not `"prefer"`); `legendItem` uses only
   `defaultVisibility`.
2. Every axis has a `propertyControl` title, and the manifest lists every file the mod needs in
   `files`.
3. `index.html` keeps the official `spotfire-loader` script (copied from an official example, or
   clearly marked as to be copied unchanged), not a retyped version.
4. `main.js` calls `signalRenderComplete()` on every exit path (normal render, early returns,
   errors), which the response links to the export and print hang.
5. `main.js` returns without drawing when `allRows()` is `null` (expired data view), shows data
   errors through `mod.controls.errorOverlay`, and shows a placeholder naming missing axes.
6. Dots use `row.color().hexCode`; click calls mark with `"Replace"`, Ctrl+click with `"Toggle"`;
   a click on the empty background clears the marking.
7. Any `window` or document listener added during a render removes itself or is added once, so
   renders do not leak listeners.
8. The README tells users to set the continuous axes' aggregation to None (Spotfire puts `Sum()`
   on a dropped column, which collapsed the dots), describes connecting the mod (development
   server or Connect to file) and the Reload manifest step after manifest changes.
9. A headless test (jsdom or similar) mocks the mod API and checks drawing, marking calls and the
   `signalRenderComplete` count, and the response says that real pointer input should be tested
   once in a browser because `dispatchEvent` skips hit testing.
10. Fonts come from the Spotfire render context or system fonts; no web font import.
