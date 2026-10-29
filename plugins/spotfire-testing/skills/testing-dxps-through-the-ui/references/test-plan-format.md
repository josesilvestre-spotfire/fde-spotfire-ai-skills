# Test plan format

`uitest.py` reads a JSON plan. Write it after you have read a first screenshot of the placed
window, because every coordinate comes from that screenshot.

```json
{
  "analysis": "C:/ui-tests/example_analysis.dxp",
  "window": {"x": 40, "y": 40, "w": 1600, "h": 1000},
  "out": "C:/ui-tests/run-01",
  "settle": 2.0,
  "boxes": {
    "rate-chart": [10, 150, 880, 960],
    "stats-table": [890, 150, 1590, 470],
    "stats-bars": [890, 480, 1590, 960]
  },
  "steps": [
    {"name": "first click on the page background", "do": "click", "at": [800, 120]},
    {"name": "mark one bar", "do": "click", "at": [1010, 700],
     "expect": {"changed": ["stats-table", "stats-bars"], "unchanged": ["rate-chart"]}}
  ]
}
```

| Key | Meaning |
|---|---|
| `analysis` | the test copy of the DXP; `uitest.py` opens it in a new Analyst process and closes that process at the end (`--keep-open` keeps it) |
| `hwnd` | instead of `analysis`: a window you opened with `deskctl.py spotfire` |
| `window` | position and size; keep it the same between runs so the coordinates hold |
| `out` | output folder for screenshots, `report.json` and `REPORT.md` |
| `settle` | seconds to wait after each action before the screenshot (default 2) |
| `boxes` | named regions `[left, top, right, bottom]` in window pixels, usually one per visual |
| `steps` | the actions, in order |

## Steps

| `do` | Keys | Action |
|---|---|---|
| `click`, `dclick`, `rclick` | `at: [x, y]` | left, double or right click |
| `drag` | `from: [x, y]`, `to: [x, y]` | press, move, release: marks a rectangle |
| `wheel` | `at: [x, y]`, `clicks` | mouse wheel, negative scrolls down |
| `keys` | `keys` | key chords, for example `"ctrl+a"` or `"enter"` |
| `type` | `text` | types text into the focused control |
| `wait` | `seconds` | waits, for example for a data function to finish |
| `shot` | none | screenshot only |

Optional per step: `settle` (seconds), `expect` with `changed` and `unchanged` lists of box
names, `minChanged` (share of pixels, default 0.005) and `maxUnchanged` (default 0.002).

## Choosing expectations

- After a marking: every visual on the marked table and on related tables, plus details
  visuals limited by that marking, are `changed`. Visuals on unrelated tables are `unchanged`.
- After a page tab click: every box is `changed`; check the screenshot for the page title.
- After a button that runs a data function: the visuals bound to its outputs are `changed`.
  Add a `wait` step when the function takes longer than `settle`.
- Text that updates (a KPI band, a label) changes few pixels. Give that step a lower
  `minChanged`, for example `0.001`.

## Report

`REPORT.md` has one row per step: PASS or FAIL, the changed share of every expected box and the
screenshot file. A FAIL means a box did not change when it should, or changed when it should
not. Open the screenshot of that step and the previous one before you report a defect.
