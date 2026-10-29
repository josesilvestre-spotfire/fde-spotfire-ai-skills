# Rendering and interaction

## The render loop

```js
Spotfire.initialize(async (mod) => {
    const reader = mod.createReader(mod.visualization.data(), mod.windowSize(),
        mod.property("mode"), mod.visualization.axis("X"));
    reader.subscribe(async (dataView, size, mode, xAxis) => {
        const context = mod.getRenderContext();
        try {
            const errors = await dataView.getErrors();
            if (errors.length) {
                mod.controls.errorOverlay.show(errors, "data");
                return;
            }
            mod.controls.errorOverlay.hide("data");
            const missing = await missingAxes(dataView, ["X", "Y"]);
            if (missing.length) {
                showPlaceholder("Set the axes: " + missing.join(", "));
                return;
            }
            const rows = await dataView.allRows();
            if (rows === null) {
                return;            // a newer data view is on its way
            }
            draw(rows, size, mode.value(), context);
        } catch (e) {
            mod.controls.errorOverlay.show(String(e), "render");
        } finally {
            context.signalRenderComplete();
        }
    });
});
```

- Call `context.signalRenderComplete()` on every exit path. Export and print wait for it and
  break silently without it.
- `allRows()` returns `null` when the data view expired because a newer one is coming: return and
  keep what is on screen.
- Missing required axes get a friendly placeholder that names them, not an error.
- Probe axes with `await dataView.continuousAxis(name)` or `categoricalAxis(name)`: they reject
  (or resolve empty) when the axis has no expression.
- With layers, the reader reads `mod.visualization.layers()`; each `layer.data()` is a data view
  with the same rules.

## Colors and marking

- Use `row.color().hexCode` for marks, so Spotfire's coloring and the dimming of unmarked rows
  flow through.
- Click: `row.mark("Replace")`; Ctrl+click: `row.mark("Toggle")`. Rectangle selection:
  `dataView.mark(rows, mode)` with the rows deduplicated by `row.elementId()`. A click on the
  empty background: `dataView.clearMarking()`.
- A visual or layer can only mark when it has a marking. A layer added through the API has none
  until you set it.
- Drill-downs driven by marking get a signature guard (remember what you set), so a programmatic
  change never overwrites a user's manual choice.

## Tooltips and hit testing

Keep a hit list per panel, `{sx, sy, row, metric, series}`, and on mouse move show
`mod.controls.tooltip.show(text)` for the nearest point within about 12 px; hide it on leave.

## Pointer events and listeners

- A full-size wrapper placed over an interactive canvas (`position: absolute; inset: 0`) swallowed
  every hover, drag, click and wheel in Analyst, while a harness that dispatched events on the
  canvas itself passed. Wrappers over an interactive area get `pointer-events: none`, and only
  their controls get `pointer-events: auto`.
- A `mouseup` listener on `window` must remove itself when its element is gone
  (`if (!host.isConnected) { window.removeEventListener(...); return; }`). Otherwise every render
  leaks a listener that holds a stale data view.

## Date bins

Read a `BinByDateTime` path by level position, in the order of the expression
(Year.Quarter.Month.Day.Hour), never by matching level names. Spotfire names the day level
`DayOfMonth(...)`, so a name match on "month" turned every day into a month and stacked all bins
on the first of a month. Test mocks use the live level names (`Year(Timestamp)` ...
`DayOfMonth(Timestamp)`).

## Popouts (the Format menu)

Three behaviours seen in the field:

1. The section factory sits in different places across versions: resolve
   `popout.section || popout.components.section`.
2. `ModProperty.value()` is stale right after `.set()`, and the popout does not call its content
   function again on a click. Keep a local state object seeded when the popout opens, update it in
   `onChange`, and call `popout.show(options, content)` again so the new choice shows at once.
3. Property instances go stale across renders. `.set()` on an instance captured when the popout
   opened silently does nothing after the first change ("only one change works per popout"). Keep
   a module-level map that every render reassigns, and write through it:
   `liveProps[e.name].set(value)`.

Mode buttons are always visible (users treat them as navigation). The Format button shows on
hover and only when `context.isEditing`. Wrap every `.set()` in `try`/`catch`: some contexts are
read-only.

## An in-visual slicer ribbon

For a mod that shows one condition at a time:

- One selector per level of a hierarchy axis (`row.categorical("Info").value()` gives the levels
  in order); options cascade from the levels before; a level with one option renders as a static
  cell.
- The selection persists as JSON in a string property (`slicerState`), keyed by the axis part's
  `displayName`, falling back to the first option.
- Slice the rows before any row cap (about 20,000 rows, with a "(truncated)" note), so the cap
  applies to the chosen condition.
- The level order is the ribbon order, so users reshape the ribbon by editing the axis
  expression.

## Theme

Read `mod.getRenderContext().styling`: `general.backgroundColor`, `general.font.color` and
`fontFamily`, `scales.line.stroke`. Push the resolved colors and a label scale onto the root
element as CSS variables on every render, and derive grid and muted tints from them, so dark
themes work. Use system and Spotfire fonts (Roboto is bundled); a web font fetch can be blocked.

## Data shape

- Mods cannot read Binary columns. Pass geometry as text: `First(Base64Encode([geometry]))` on a
  categorical or continuous axis was accepted in Analyst 15.0.
- Derive status from the latest valid sample window, not from the literal last row.
- Fix physics or data problems upstream (data function), never in the view.
