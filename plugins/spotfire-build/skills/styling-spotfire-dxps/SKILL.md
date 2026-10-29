---
name: styling-spotfire-dxps
description: Styles Spotfire analyses (DXP files) without touching the filter panel or the data canvas. Ships a small stylesheet injector attached to one host text area per page, a matching theme JSON for visual titles and canvas, sanitizer-safe HTML snippets (side panel, KPI band, settings card, tabs, status legend, method panel), a palette with measured contrast and layout weights, plus offline checks for Spotfire's HTML sanitizer, a browser preview builder and a contrast checker. Use when styling or restyling a DXP, writing HTML for Spotfire text areas, building a KPI band, or when text areas look unstyled or lose controls on another machine.
compatibility: Spotfire Analyst 15.0. The bundled tools need Python 3.10+ and no packages.
metadata:
  maturity: New, not yet tested
  spotfire: "15.0"
---

# Styling Spotfire DXPs

Spotfire removes `<style>` from text-area HTML, so CSS with selectors has to arrive another way.
The mechanism this skill uses is proven on Spotfire Analyst 15.0: a JavaScript attached to one
text area per page writes a stylesheet into the page each time that text area renders, and the
stylesheet then applies to every text area on the page. Native chrome (visual titles, canvas,
page tabs, axes) comes from a theme JSON. The injector and stylesheet in this skill are written
for this library and have not yet run in Analyst: **Not yet tested**.

## Rules

1. **Never style the filter panel or the data canvas.** Their look is Spotfire's. A stylesheet
   with page-wide selectors (`.sf-element-list-box-item`, `.sf-element-range`, `.cell-text`)
   reaches the Filters panel, its sliders and list boxes, and table cells (seen in Analyst 15.0).
   Every rule of this skill's stylesheet is scoped under `.app-ta`, and the theme JSON names only
   visualization-area nodes. Organize each page's filter panel instead (only the tables and
   columns users need), which is a build task, not styling.
2. **One host text area per page.** The host's HTML starts with
   `<div id="style-container"></div><div id="styleDivSF"></div>` and the host has the injector
   attached. No other text area on the page has the two divs or the script. Every page needs its
   own host, because only the active page renders.
3. **Wrap every styled text area in `<div class="app-ta">`.** Nothing outside the wrapper is
   styled.
4. **Write for the sanitizer.** Spotfire 15.0 sanitizes text-area HTML by default when it renders
   it, and keeps the stored HTML as written, so an area can look right where sanitizing is off and
   break everywhere else. Run `scripts/check_textarea_html.py` on every HTML file.
5. **No KPI charts for scalar KPIs.** Show KPIs in an HTML KPI band: label controls bound to
   String properties that a data function formats, caption and value only, one tooltip per card,
   6 to 8 cards.
6. **Native visuals first, Spotfire look.** Panels sit in the analysis: system and Spotfire fonts
   (Roboto is bundled), neutral greys, one accent, thin borders. No web fonts and no CDN files:
   offline clients and Web Player content policies block them.
7. **Change the look in one place.** Colors and fonts live in the injector's `THEME` object and
   in the theme JSON; HTML carries classes, not colors (except an alert value's color).

## Files

| File | What |
|---|---|
| `assets/Apply App Styles.js` | the injector: scoped stylesheet, idempotent, plus tab switching |
| [assets/app-theme.json](assets/app-theme.json) | theme JSON in the same palette (LightSfx base) |
| `assets/snippets/host-panel.html` | host side panel: the two divs, title, getting started, steps, status line |
| `assets/snippets/kpi-band.html` | six KPI cards with tooltips and an alert value |
| `assets/snippets/settings-card.html` | parameter card: input, drop-down, slider, four button kinds |
| `assets/snippets/tabbed-panel.html` | Steps, Settings and Method tabs |
| `assets/snippets/status-legend.html` | status chips with live limits from label controls |
| `assets/snippets/methodology-panel.html` | method text, a formula block, a definitions table |
| `scripts/check_textarea_html.py` | offline sanitizer check |
| `scripts/make_preview.py` | browser preview of HTML files with the injector |
| `scripts/palette_check.py` | WCAG contrast of the THEME colors and chips |

Snippets mark each Spotfire control with `{{control:<id>}}`. By hand, delete the placeholder and
insert the control at that spot in the text area editor. The `building-spotfire-dxps` skill
replaces the placeholders from the spec's `controls`.

## Workflow

1. Copy the snippets you need into the app folder (`$DXP_WORKSPACE/apps/<AppSlug>/html/`) and
   rename ids and texts. HTML element ids are camelCase and unique per page
   ([references/naming-standard.md](references/naming-standard.md)).
2. Make the first text area of each page (usually the side panel) the host: start its HTML with
   the two divs.
3. Check and preview:

   ```bash
   python scripts/check_textarea_html.py html/
   python scripts/make_preview.py html/ --out html/preview.html
   python scripts/palette_check.py            # after any THEME change
   ```

   Open `preview.html` in a browser. It runs the injector the way Spotfire does and shows
   stand-ins for the controls.
4. In Analyst, for each page: paste the HTML into the host text area (edit the HTML source), insert
   the controls, then attach `Apply App Styles.js` to the host as JavaScript (the text area
   editor's insert JavaScript action). Paste the other text areas of the page, each wrapped in
   `.app-ta`, without the divs and without the script. Through the API the script is attached with
   `HtmlTextArea.Scripts.Add(HtmlTextAreaScript(definition, values))` (the
   `writing-spotfire-ironpython` skill shows the upsert).
5. Apply `app-theme.json` in the theme editor ([references/theme-json.md](references/theme-json.md)).
6. Check every page on a machine with HTML sanitizing on (the default), in Analyst and, if used,
   Web Player: styled panels, controls present, buttons wired, tabs switching, filter panel
   unchanged.

## How the injector works

- Spotfire runs text-area JavaScript after every full render of that text area, with jQuery as
  `$`; it does not run again when a control value changes. The injector removes any earlier copy
  of its `<style id="app-styles">` and appends a new one to `#style-container` (or `#styleDivSF`),
  so a re-render never stacks stylesheets.
- The style element lives in the host's DOM but applies to the whole page document: every text
  area on the page shares that document.
- Tab links are switched by one click handler bound once per page, because the sanitizer removes
  inline event handlers.
- `THEME` holds every color and font. `palette_check.py` reads it back and fails when a text color
  or chip drops below 4.5:1.

## Text areas: patterns

- **Side panel (host):** title, a two-sentence "getting started" that names the business problem,
  one-line steps that name the visual each step works on, a status line (a label bound to a
  String property the scripts and data functions write).
- **KPI band:** a flat table with `table-layout: fixed`, one `kpi-cell` per KPI: value
  (`dashboard-value`) over caption (`dashboard-label`, unit in brackets) and a tooltip.
- **Settings card:** `table1`, label cell and control cell per row, tooltips on field labels, one
  primary button (`key-btn`) per card.
- **Explanations:** one or two sentences in a CSS tooltip at the point of reading; anything longer
  goes in a Method tab or a methodology panel.
- **Data-driven lists** (wells, events): a native table or cross table with cell coloring, never
  an HTML table.
- **No toggle switches:** they need `<input type="checkbox">`, which the sanitizer removes. Use a
  checkbox control, a radio list box or two buttons.

Class catalogue and control markup: [references/classes.md](references/classes.md). Sanitizer
results and the DOM of each control: [references/sanitizer.md](references/sanitizer.md).

## Visual conventions

| Item | Convention |
|---|---|
| visual titles | the prototype's or workbook's header, with units where a value is shown |
| descriptions | one sentence per chart that says what to look at (the visual's description, shown under the title) |
| axis names | display-name aliases with units on aggregated axes: `Avg([Flow Rate (bbl/d)]) as [Flow (bbl/d)]` |
| legends | only the color item, docked right; none when the title, a chip row or the axis already explains the color |
| empty states | a sentence where a visual waits for a marking ("Mark pumps in the ranking"), never a blank visual |
| marking color | the accent `#3050EF` |
| backgrounds | from the theme; leave visual backgrounds alone |
| page titles | Title Case, short, no number prefix |

Palette, status scale, chips, sequences and page layout weights:
[references/palette-and-layout.md](references/palette-and-layout.md).
