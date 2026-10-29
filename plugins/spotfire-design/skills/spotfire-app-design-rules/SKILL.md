---
name: spotfire-app-design-rules
description: Applies the design rules for how a Spotfire analysis behaves for its users. KPI bands built in HTML instead of KPI charts, marking that drives every relevant visual, no empty visuals, a filter panel limited to each page's user columns and never styled, controls next to the visuals they drive, a separate Data Generation page, operator what-if scenarios, short steps with Details and KPI popups, a Method page that explains the model, customer-ready text including code comments, a native Spotfire look, consistent units and colors, sanitizer-safe HTML. Each rule comes with why and how to check it; a script checks customer-ready text. Use it when designing the pages of a new analysis from its App Brief, reviewing a build spec or a built DXP before hand-over, or when a user reports that marking, filters, controls or text behave or read wrongly.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Spotfire app design rules

Rules for how a Spotfire analysis behaves and reads, so that users can explore it on their own
data without help. Use them twice: when you design the pages from the App Brief, and when you
review a build spec or a built DXP.

Detail for every rule (rule, why, how to check, build notes):
[references/rules.md](references/rules.md). The App Brief format:
[references/app-brief-format.md](references/app-brief-format.md).

## The rules

| ID | Rule | Quick check |
|---|---|---|
| D01 | KPIs are an HTML band of caption + value; no KPI chart for single values | No KPI chart on any page; every card maps to an App Brief KPI |
| D02 | Every marking reaches every visual a user expects to react | Marking matrix per page; mark items in Analyst and watch every visual |
| D03 | No visual is empty when its page opens with nothing marked | Open each page fresh; no blank canvas, no red issue icon |
| D04 | The Filters panel shows only the columns each page's users slice by | Open the panel per page; no ids, keys, coordinates or helper columns |
| D05 | The Filters panel and the data canvas are never styled | They look like an unstyled analysis; every CSS selector is scoped |
| D06 | A control sits next to the visual it drives | Each control's visuals named; single-visual controls are adjacent |
| D07 | Generator and calibration settings live on a last Data Generation page | No working page binds a generator property |
| D08 | What-if inputs are operator decisions, run as named scenarios | Each input is changeable in operation; Baseline vs Scenario shown |
| D09 | Steps are one line; explanations sit in tooltips, popups or the Method page | Step length; KPI cards carry no extra text |
| D10 | A Method page explains the model; no tuning page for users | Every KPI's Logic Spec entry is on the Method page |
| D11 | All text, code comments included, is customer-ready | `scripts/check_customer_text.py` is clean |
| D12 | Native visuals first; HTML panels look like Spotfire | Each mod has a reason; light and dark themes both read well |
| D13 | Every value has its unit; a category keeps its color on every page | Axes, headers, KPIs; category colors across pages |
| D14 | Text-area HTML survives the sanitizer (on by default) | Open with sanitation on; every control and style is there |

## Design an analysis from its App Brief

Read `app-brief.md` (users, decisions, KPIs, inputs, outputs) and decide, before anything is built:

1. **Pages.** One page per group of decisions, in the order users work; the Method page; the Data
   Generation page last when the app generates data. The `packaging-spotfire-apps` skill adds the
   cover page and the page order for delivery.
2. **KPI band per page** (D01): which App Brief KPIs, in which order, with the tooltip text.
3. **Marking plan** (D02, D03): which visuals share a table and a marking, which visuals are
   limited by it and what they show when nothing is marked, which cross-table effects use a
   relation or the data function pattern.
4. **Filter panel per page** (D04): the tables and columns to show, everything else hidden.
5. **Control placement** (D06): each App Brief input, the visual it drives, where it sits.
6. **Data Generation page** (D07) and **scenarios** (D08) when the brief has generator settings or
   what-if inputs.
7. **Method page outline** (D10) from the Logic Spec.

Put these decisions into the draft build spec in the form the `building-spotfire-dxps` skill reads.
When no spec exists yet, give them to the user as a list per page to confirm.

## Review a build spec or a built DXP

1. **Inventory.** Pages, visuals (type, table, marking, limits), text areas and their controls with
   the bound document properties, the Filters panel per page, data functions with their inputs and
   outputs, scripts. Read it from the build spec, or for a built DXP from the
   `auditing-and-comparing-dxps` skill, or walk the analysis with the user.
2. **Apply every rule** in [references/rules.md](references/rules.md), using its "How to check".
3. **Run the text check** on the app folder (D11):
   ```bash
   python scripts/check_customer_text.py "$DXP_WORKSPACE/apps/<AppSlug>" --terms <your-terms.txt>
   ```
   Add `--allow <rule>` for a default rule that does not fit the app (for example `builder` in an
   app about a query builder). Exit code 1 means visible-text findings; `--strict` also fails on
   code findings.
4. **Check behaviour live** for D02, D03, D04 and D14: open the analysis with sanitation on, clear
   markings, reset filters, then mark items visual by visual. The `testing-dxps-through-the-ui`
   skill automates the clicks and screenshots.
5. **Report** one row per finding:

   | Rule | Page / visual | Finding | Fix | Severity |
   |---|---|---|---|---|

   Severity: **Blocker** (users see broken or wrong behaviour: an empty visual, a marking that
   reaches nothing, lost controls, internal text on a page), **Major** (works but misleads or slows
   users: helper columns in the Filters panel, generator settings on a working page), **Minor**
   (polish: a control placed away from its visual, a missing unit in a tooltip).

A rule may not apply (no generator, no scenarios): say so in the report instead of skipping it.

## Related skills

- `framing-spotfire-apps` writes the App Brief these rules start from.
- `building-spotfire-dxps` builds the design; `styling-spotfire-dxps` styles it within D05, D12
  and D14.
- `packaging-spotfire-apps` adds the cover page, page order and publishing checklist.
- `spotfire-reference` holds the proven Spotfire behaviour behind D02, D03, D05 and D14.
