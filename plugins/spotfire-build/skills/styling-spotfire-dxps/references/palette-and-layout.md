# Palette and layout

Contrast values are WCAG 2 ratios against the canvas `#FAFAF8`, computed with
`scripts/palette_check.py`. Text needs 4.5:1 (3:1 at 18 px and larger); lines and markers need
3:1.

## Interface colors (the injector's THEME)

| Role | Hex | Contrast |
|---|---|---|
| text | `#1F2328` | 15.1 |
| captions, hints | `#5B6370` | 5.8 |
| accent: buttons, active tab, KPI values, default marking color | `#3050EF` | 5.7 |
| accent hover / pressed | `#2440D6` / `#1B32AB` | 7.2 / 9.6 |
| confirm hover | `#1E7A47` | 5.1 |
| destructive hover, alert value | `#B42318` | 6.3 |
| borders and rules | `#D0D5DD` | decoration only |
| canvas (theme base color) | `#FAFAF8` | |

Use the accent as the marking color too, so a marked item reads the same in charts and panels.

## Status scale

| Level | Fill | Contrast | Chip text / background / border |
|---|---|---|---|
| Normal | `#2E9E5B` | 3.3 | `#1E6B3D` / `#E3F3E9` / `#93D1AC` (5.7) |
| Warning | `#F2C12E` | 1.6 | `#6E5200` / `#FFF5D1` / `#F2D46B` (6.7) |
| Alarm | `#F07C1F` | 2.6 | `#8A4100` / `#FDEAD8` / `#F5B27A` (6.3) |
| Critical | `#D93A2B` | 4.4 | `#9C1F16` / `#FBE4E1` / `#EFA39B` (6.6) |
| Offline, no data | `#A0A0A0` | 2.5 | `#4D4D4D` / `#EFEFEF` / `#BDBDBD` (7.4) |

- Yellow and orange stay below 3:1 on a light canvas in any shade: use them for fills (markers,
  bars, cell backgrounds, chips), never for text or thin lines. A Warning or Alarm limit line uses
  the chip text color (`#6E5200`, `#8A4100`).
- Status must also be readable without color: position against a limit line, a label or a chip.
  Normal green and Critical red are hard to tell apart with red-green color vision deficiency.
- One color meaning per chart: never put status colors, stream or category colors on the same
  chart.
- Limits on a chart are horizontal reference lines in the level color (dashed, width 1).

## Sequences

| Use | Colors |
|---|---|
| categories (assets, wells, stages) | a categorical palette of 8 distinct hues, in a fixed order; list the categories in the coloring so each keeps its color |
| one-sided magnitude on cell backgrounds | `#E3E6F2` to `#333D66`; on markers and lines start at `#9AA1C2`, because the light end disappears on the canvas |
| deviation from plan (residuals) on cell backgrounds | `#088BCE` / `#F7F7F2` / `#D93A2B` at min / 0 / max; on markers use `#BDBDBD` as the midpoint |

Spotfire ignores a prototype's automatic colorway: write each category's color into the visual's
coloring.

## Layout weights

Measured on a published, styled analysis (panel bounds as shares of the page) and used as the
default page skeleton since. Values are relative weights.

| Part | Weight |
|---|---|
| sidebar (host text area) | 15 to 19; 20 to 24 when it holds tabs (three tabs need about 360 px) |
| KPI band across the top of the main area | 12 (about 11.6 % of the page height) |
| control strip above a chart | 8 to 10 |
| main row of charts | about 45 of the main column, split 60 / 40 |
| detail row | about 34 of the main column, split 50 / 50 |

```json
"layout": {"row": [
  {"visual": "overviewPanel", "weight": 16},
  {"column": [
    {"visual": "kpiBand", "weight": 12},
    {"visual": "controlStrip", "weight": 9},
    {"row": [{"visual": "efficiencyTrend", "weight": 60}, {"visual": "pumpRanking", "weight": 40}], "weight": 45},
    {"row": [{"visual": "detailA", "weight": 50}, {"visual": "detailB", "weight": 50}], "weight": 34}
  ], "weight": 84}
]}
```

The layout shape is the one the `building-spotfire-dxps` spec uses. Panel sizes are proportional
only: Spotfire has no API to lock a splitter at a pixel width.

A top-band variant without a sidebar: controls 46, KPI band over a chart 43, a narrow chart 11 in
a top row of weight 38, and the main charts in a bottom row of weight 62.
