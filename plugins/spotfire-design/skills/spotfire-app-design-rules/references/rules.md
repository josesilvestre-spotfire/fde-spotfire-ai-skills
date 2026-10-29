# Design rules in detail

Each rule has the rule, why it exists, how to check it, and notes for building it. Spotfire
behaviour cited here was proven on Spotfire Analyst 15.0 unless marked **Not yet tested**.

Contents: D01 KPI bands, D02 Marking, D03 No empty visuals, D04 Filter panel content, D05 No
styling of the Filters panel and data canvas, D06 Controls next to their visuals, D07 Data
Generation page, D08 Operator scenarios, D09 Short steps and popups, D10 Method page, D11
Customer-ready text, D12 Spotfire look, D13 Units and colors, D14 HTML that survives the sanitizer.

## D01 KPI bands are HTML, never KPI charts

**Rule.** Show the page's KPIs as a band at the top of the page, built in an HTML text area. Each
card shows a caption and a value, nothing else. The value is a label control bound to a String
document property that a data function or script writes already formatted, unit included
(`0.34 m2 K/kW`, `12.5 %`). Do not use Spotfire's KPI chart for single values.

**Why.** A KPI chart lays out and styles its tiles by its own rules, separately from the page's
HTML, so the band does not match the page and tile sizes shift with the window. A formatted string
property shows exactly the caption, value and unit the App Brief defines.

**How to check.**
- List the visuals on every page. A KPI chart that shows single values is a finding.
- Every card traces to a KPI row of the App Brief and its Logic Spec ID.
- Cards show caption and value only; context sits in a tooltip or popup (D09).
- Values carry units and sensible rounding (no `0.3499999`).
- Open the page with nothing marked: no card is empty or shows a stale value.

**Build notes.**
- `${Property}` is not substituted in text-area HTML; use label controls.
- Spotfire 15.0 has no public API for text-area controls. When a build cannot add the label
  controls, add them in the text area's edit mode and record it as a manual step.
- When a band value should react to marking, let a data function limited by the marking write the
  property (see D02).

## D02 Marking drives every relevant visual

**Rule.** Every marking on a page reaches every visual a user expects to react, and every
interactive KPI or area drives the components it describes.
- Visuals that show the same items share one table and one marking.
- Across tables, relate the tables, or use the pattern: marking, then an automatic data function
  whose input is limited by the marking, then a document property it writes, then a trigger script
  on that property.
- Use buttons for deliberate actions (run a scenario, export), not to pass a selection along.

**Why.** Users judge an analysis by whether a click updates the page. A marking that reaches one
visual and leaves the rest unchanged reads as a defect.

**How to check.**
1. Write a marking matrix per page: one row per visual, one column per marking, each cell one of
   *highlights*, *limited by*, *feeds data function*, *nothing*.
2. Flag: a marking used by one visual that nothing else reads; a marking used on visuals of
   different tables without a relation; one table shown with two different markings on one page
   (they do not highlight each other); a visual a user would expect to react that shows *nothing*.
3. In Analyst, mark items in each visual and confirm that every visual in the matrix reacts. The
   `testing-dxps-through-the-ui` skill can do this and screenshot each step.

**Build notes.** No action runs on a marking change in Spotfire 15.0; the data function pattern
above is the proven route. A document property cannot be both input and output of one automatic
data function (Spotfire then switches it to manual refresh).

## D03 No empty visuals

**Rule.** Every visual shows content when its page opens with nothing marked and every filter
reset.
- A visual limited by a marking sets its empty behaviour on purpose: ShowAll, or ShowMessage with
  an instruction ("Mark a well on the map to see its history"). Never a blank canvas.
- Never limit the base layers of a map (routes, sites, outlines) by a marking that can be empty
  with ShowEmpty.
- On scatter plots and map marker layers, label, size, line order, rotation and tooltip
  expressions aggregate (`First(...)`, `Avg(...)`, `UniqueConcatenate(...)`) unless the marker-by
  contains `baserowid()`.
- Data function output tables exist before a visual uses them (the function runs at build or on
  open).

**Why.** A blank visual reads as broken. On a map, one layer with an invalid configuration blanks
the whole map, tile layer included, with only "Please specify an aggregation method." on the
canvas.

**How to check.**
- Open each page fresh: clear every marking, reset all filters, look at every visual.
- Look for the red issue icon next to a visual title; its tooltip names the failing layer.
- Render every page to an image (the `running-spotfire-unattended` skill renders pages) and look
  for empty canvases.
- For every visual limited by a marking, read its empty behaviour.

## D04 Filter panel shows only the user's columns

**Rule.** On every page, the Filters panel lists only the tables and columns that page's users
slice by: asset, region, status, date, a few key measures, the page's main table first.
- Hide ids, internal keys, coordinates, geometry, sort helpers, columns that only feed
  calculations, helper tables and data function outputs that only feed visuals.
- Hide the Data Generation tables on the working pages.
- A page with nothing to filter hides every table.
- Hide filters; do not delete the columns.

**Why.** A panel that lists every helper column hides the useful filters, and a user who filters a
helper column changes calculations without noticing.

**How to check.** Open the Filters panel on each page. Every visible table and column must be one a
user of that page would filter by (compare with the App Brief's users, decisions and inputs).
Anything else is a finding.

## D05 The Filters panel and the data canvas keep Spotfire's look

**Rule.** No CSS, theme rule or custom style targets the Filters panel or the data canvas. Scope
every injected CSS rule under the panel class of its text area.

**Why.** Styling them adds work and no value for users. CSS injected by text-area JavaScript is
global to the page, so an unscoped rule also restyles the Filters panel (seen on Spotfire 15.0).

**How to check.**
- With a styled page active, open the Filters panel and the data canvas; they look like those of
  an unstyled analysis.
- Every selector in the app's CSS files starts with the app's panel class.

## D06 Controls sit next to the visual they drive

**Rule.** A control that changes one visual sits in a thin strip directly above or beside that
visual (a map's color choice above the map). The sidebar holds only page-wide items: navigation,
the page's steps, controls that change every visual on the page.

**Why.** Users look for a control where its effect shows. A sidebar of mixed controls hides which
visual each one changes.

**How to check.** For every control, name the visuals it changes (follow its document property into
expressions, data functions and scripts). One visual: the control must be adjacent to it. Several
visuals across the page: the sidebar or the page header is right.

## D07 Data generation lives on its own page

Applies when the analysis ships a generator, a simulator or demo data.

**Rule.** A Data Generation page, always the last page, holds the Build or Simulate buttons, every
generator setting (seed, noise, event types, injected anomalies, period, time step), any model
calibration settings and a small readout that checks the generated dataset. Its header says it is
for advanced users. It ships in every copy. The working pages read the generated tables and never
bind a generator or calibration property.

**Why.** Users should explore operating decisions. Generator settings overwhelm them and invite
changes that make the demo data unrealistic.

**How to check.**
- List the document properties that each working page's controls bind. Any generator or
  calibration property there is a finding.
- The page is last and its header names its audience.
- The App Brief marks these inputs "advanced user (Data Generation page)".

## D08 What-if means operator scenarios

**Rule.** User-facing inputs are decisions an operator, engineer or planner could make: a
setpoint, a dose, a price, a maintenance interval, a capacity change, a blend. A Scenarios page (or
section) offers a few named scenarios.
- Each scenario has its inputs next to its charts and its own Run button.
- A run reuses the same history and shows baseline against scenario on the same axes (a long table
  with a `Series` column: Baseline, Scenario).
- A scenario that changes only a price recomputes cost without rerunning the model.
- For an expensive model, bind the scenario inputs to their own properties. The Run button copies
  them into the properties the data function reads, and that function refreshes manually, so it
  runs once per press.

**Why.** The what-if questions users ask are about operating choices. A scenario that changes
generator settings says nothing about what to do in the plant or the business.

**How to check.** For each scenario input, ask "could a user change this in operation?". Check that
outputs show Baseline and Scenario together and that the Run button runs the function once.

## D09 Short steps; explanations in popups

**Rule.**
- A sidebar or panel shows a few steps of one line each.
- Longer explanations sit behind an info icon (a tooltip) or a Details popup, or on the Method
  page (D10).
- KPI cards show caption and value; each card's definition sits in its own tooltip.

**Why.** Text on the page competes with the visuals. Users who need the explanation open it.

**How to check.** Steps are one line (about 12 words or fewer). KPI cards carry no extra lines.
Every KPI's definition is one hover or click away and matches its Logic Spec entry in plain words.

**Build notes.** The sanitizer removes `<details>`, `<button>` and `<script>`. Tooltips need CSS
injected by text-area JavaScript; popups need text-area JavaScript. The `styling-spotfire-dxps`
skill has sanitizer-safe patterns for both.

## D10 The Method page explains the model; it does not tune it

**Rule.** A model ships calibrated. A Method page explains each calculation behind a KPI in plain
words: a simplified formula, inputs, outputs, units, assumptions and limits, taken from the Logic
Spec. End users get no tuning page and no training-metrics page; calibration settings, if any,
live on the Data Generation page.

**Why.** Users need to understand and trust the numbers. Tuning controls on a working page let
anyone change the model without noticing what it does to every result.

**How to check.** Every Logic Spec entry behind a KPI appears on the Method page. No calibration
control or model metric table appears on a working page.

## D11 Customer-ready text, code comments included

**Rule.** Everything the DXP carries is written for the people who will receive it: titles,
descriptions, text-area HTML, property, data function and script descriptions, control labels,
messages, and the comments, docstrings and strings of data functions, IronPython scripts,
text-area JavaScript and mods. None of it carries internal project or person names, release or
version tags, design history ("ported from the prototype", "legacy"), development notes (TODO,
FIXME), tool or assistant names, or internal property names in prose. The version number appears
in file names and release notes only.

**Why.** Analyses are often built by one team and given to others or to customers, and every
Spotfire editor shows the code.

**How to check.**
```bash
python scripts/check_customer_text.py "$DXP_WORKSPACE/apps/<AppSlug>" --terms <your-terms.txt>
```
Visible text findings are errors; code findings are warnings, and a string literal may still be a
message users see. Keep `your-terms.txt` (names, code names) outside shared repositories. For a
built DXP, also open the script and data function editors and read the descriptions.

## D12 It looks like Spotfire

**Rule.** Use native visuals first. Use a visualization mod only where no native visual can show
the view, and state the reason in the design. Style HTML panels to sit inside Spotfire: inherit the
theme's font and text color, neutral greys, thin borders, one accent color, and make them read
correctly in the light and dark themes.

**Why.** Native visuals support marking, filtering, details-on-demand and export with no extra code,
and users already know how to use them.

**How to check.** List every mod visual with its reason. Switch the analysis between the light and
dark themes and look at every text area.

## D13 Units and colors are consistent

**Rule.** Every value shown carries its unit: column names (`Flow Rate (bbl/d)`), axis titles, KPI
values, tooltips, table headers. A category has the same color on every page.

**Why.** A number without a unit is misread, and a category that changes color between pages is
taken for a different category.

**How to check.** Read every axis, column header and KPI. Compare the colors of each category
across pages.

## D14 Text-area HTML survives the sanitizer

**Rule.** Text-area HTML renders as designed with HTML sanitation on, the Spotfire 15.0 default. No
`<style>`, `<script>`, `<details>`, `<button>`, `<input>`, `<select>`, `<svg>` or `<section>`;
inline styles with plain values only (no `var()`, `calc()`, `url()`, gradients); controls only in
allowed containers (`div`, `span`, `p`, `td`, `li`).

**Why.** The HTML is stored unchanged and sanitized when it renders. A page built with sanitation
off loses its styling and controls on every machine that keeps the default.

**How to check.** Open the analysis on a machine with sanitation on and compare every text area
with the design. The `styling-spotfire-dxps` skill covers the sanitizer's allowlist and safe HTML
patterns; the `spotfire-reference` skill lists what the sanitizer removes.
