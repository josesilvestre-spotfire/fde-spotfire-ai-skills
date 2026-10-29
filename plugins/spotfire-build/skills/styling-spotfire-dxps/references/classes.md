# Class reference of the injector stylesheet

Every rule is scoped under `.app-ta`. Wrap the content of each styled text area in
`<div class="app-ta">...</div>`. The class names follow the vocabulary common in Spotfire
accelerator text areas, so HTML written for that vocabulary keeps working.

## Structure

| Class | Element | Use |
|---|---|---|
| `app-ta` | the wrapper `div` | required; nothing outside it is styled |
| `heading` | `h2` | panel or page title, once per text area |
| `subheading-lg` | `h2` | card title |
| `subheading-md` | `h2` | sub-card title |
| `subheading` | `h2` (section), `h3` (field label) | small uppercase label |
| `table1` | `table` | raised card: the main settings card of a page |
| `table2` | `table` | muted card: methodology, results |
| `table3` | `table` | flat layout: sidebars, control strips, KPI band |
| `sectiontd` | `td` | cell with a rule under it |
| `sectionbreak` | `div` | horizontal rule |
| `leftAlignedInputField` | `td` | left-aligns a text box control |
| `sf-row` | `div` | flex row with 8 px gaps, wraps |
| `sf-label` | `span` | small uppercase caption |
| `sf-hint` | `span`, `p` | italic hint ("Default 65, range 40 to 90") |
| `body-text` / `body-text2` | any | muted / dark body text |
| `numeric-text` | `td`, `span` | tabular figures, right-aligned |

`pre` inside a styled area renders as a formula block (monospace, accent rule on the left).

## KPI band

| Class | Use |
|---|---|
| `kpi-cell` | one card per `td`, rule on the right |
| `dashboard-value` | the value: a label control bound to a String property the data function formats |
| `dashboard-numeric` | a monospace value that updates in place |
| `dashboard-label` | the caption, with the unit in brackets |

Alert value: put a second label in a `span style="color: #B42318"` inside the same
`dashboard-value`; the data function fills either the normal or the alert property and leaves the
other empty. A declared color beats the inherited accent.

## Buttons

Wrap each button control in a cell with one of these classes:

| Class | Look | Use |
|---|---|---|
| none | accent outline, tint on hover | ordinary actions |
| `key-btn` | filled accent | the one primary action of a card (Run Analysis) |
| `iso-btn` | accent outline | secondary actions, navigation |
| `sav-btn` | outline, green on hover | confirm: Apply, Save, Export |
| `del-btn` | neutral outline, red on hover | destructive: Reset, Clear, Delete |

Button labels: verb first (Run Analysis, Reset Filters).

## Tooltips

```html
<span class="tooltip-container"><i class="info-icon">i</i><span class="tooltip">One or two sentences.</span></span>
```

CSS only: the tip shows on hover, to the right of the mark. Add `flip` to the container
(`class="tooltip-container flip"`) for a mark near the right edge. Keep tips to two sentences;
longer explanations go to a Method tab or a methodology panel.

## Tabs

```html
<div class="tabbed-content">
  <div class="tabs"><ul>
    <li><a href="#tabOverviewSteps" class="active">Steps</a></li>
    <li><a href="#tabOverviewMethod">Method</a></li>
  </ul></div>
  <div id="tabOverviewSteps" class="item active">...</div>
  <div id="tabOverviewMethod" class="item">...</div>
</div>
```

- The injector switches tabs with one click handler on the page. **Not yet tested** in Analyst;
  tested in a browser DOM.
- Ids are unique per page, because every text area on a page shares one document: prefix them
  with the page (`tabOverviewSteps`, camelCase by the naming standard).
- The active tab resets to the one marked `active` in the HTML whenever the text area renders
  again.
- Put tabs in the host text area when you can: the host renders whenever the page does.

## Chips

`sf-badge` plus one of `chip-normal`, `chip-warning`, `chip-alarm`, `chip-critical`,
`chip-offline`, `chip-info`. Live limits come from label controls inside the chip, bound to the
threshold properties, so the legend always matches the coloring:

```html
<span class="sf-badge chip-alarm">Below {{control:legendAlarm}} %</span>
```
