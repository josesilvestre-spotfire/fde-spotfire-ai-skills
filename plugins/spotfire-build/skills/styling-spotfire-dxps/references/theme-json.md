# Theme JSON

The document theme styles what text-area CSS must not touch: page tabs, the visualization area,
visual frames and titles, axes and table rows. `assets/app-theme.json` matches the injector's
palette and fonts.

## Format

The format is what Spotfire's theme editor writes and stores in the DXP as `CustomStyles.json`.

```json
{
  "general": {"baseTheme": "LightSfx", "baseThemeSfx": "LightSfx", "font-family": "Roboto", "...": "..."},
  "rules": [{"containmentNode": "visual-title", "box": {"font-size": 12, "font-weight": "Bold"}}]
}
```

- `general`: `baseTheme`, `baseThemeSfx`, `baseColor`, `accentColor`,
  `activeVisualizationBorderColor`, `visualizationMargin` (integer), `font-family`, `color`,
  `activePageTabBackgroundColor`.
- `box`: `font-family`, `font-size`, `color`, `font-weight`, `font-style`, `text-align`,
  `background-color`, `padding` and `padding-<side>`, `margin` and `margin-<side>`, `border-style`,
  `border-width`, `border-radius`, `border-<corner>-radius`, `border-color`, and `stroke` for
  scale lines and ticks. Pixel values are integers. Other keys are ignored.
- `containmentNode` values seen in saved analyses: `page-navigation-bar`, `visualization-area`,
  `visual`, `visual-title`, `scale-area`, `scale-line`, `scale-tick`, `axis-tray`, `annotation`,
  `table-cell:odd-row`. Also accepted: `page`, `page-tab`, `visual-content`, `legend`,
  `legend-item`, `axis-title`, `grid-line`, `trellis-panel`, `table-cell`, `panel`.
- Colors are CSS strings as the editor writes them (`"rgb(35, 35, 35)"`, `"transparent"`);
  keywords as the editor writes them (`"Bold"`, `"Normal"`).
- Spotfire reads `baseTheme` and copies `baseThemeSfx` over it, so give both the same value.
- Text areas are visuals: a `visual` rule (background, border) also applies to them.

Rules name only visualization-area nodes, so the theme never reaches the filter panel or the data
canvas.

## Fonts

Spotfire's web view bundles Roboto and Roboto Light. Other fonts render only where they are
installed, so every stack ends in system fonts: `Roboto, 'Segoe UI', 'Helvetica Neue', Arial,
sans-serif` for text and `Consolas, 'Cascadia Mono', 'Courier New', monospace` for code. Web fonts
are not loaded: an offline client or a Web Player content policy would block them.

## Applying the theme

Spotfire 15.0 has no public API for the document theme, so apply it by hand in Analyst's theme
editor: start from the Light theme, then import or paste `app-theme.json` and save it with the
analysis. Where the editor sits in the menus differs between versions; this manual route is
**Not yet tested** with this file. The `building-spotfire-dxps` skill lists the theme as a manual
step for the same reason.

After applying, check: page tabs and canvas in the theme colors, visual titles in Roboto bold,
the filter panel unchanged.
