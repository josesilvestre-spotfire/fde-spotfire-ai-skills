---
type: llm
weight: 1
---

Grade the response and the files it writes under `html/`. Pass when all of these hold; list every
criterion that fails.

1. One host text area per page: each page's left text area starts with
   `<div id="style-container"></div><div id="styleDivSF"></div>`, and only the host carries the
   stylesheet-injector JavaScript. The KPI band text area has neither the two divs nor the script.
2. The styling comes from a JavaScript that injects a stylesheet at render time (the skill's
   `Apply App Styles.js` or an equivalent), because Spotfire removes `<style>` from text-area
   HTML. No HTML file contains `<style>`, `<script>`, `<svg>`, `<input>`, `<details>` or a
   `<form>`.
3. Every stylesheet rule is scoped to the text areas (for example under `.app-ta`, with every
   styled text area wrapped in that class), and the response states that the filter panel and the
   data canvas are not styled.
4. The KPI band shows each value through a Spotfire label control bound to its String property
   (a placeholder such as `{{control:...}}` or an explicit instruction to insert a label control),
   not through `${PropertyName}` in the HTML, and uses no KPI chart visual.
5. Each KPI card has a caption with the unit in brackets and a one or two sentence tooltip.
6. Inline styles, if any, use plain values only: no `var()`, `calc()`, `url()` or gradients; no
   `data-*` attributes or `on*` handlers; no `style` or `rel` on links.
7. No web fonts, CDN files or external images: font stacks end in system fonts, because the
   customers are offline.
8. The response covers the native chrome with a theme JSON (or explains the theme step) and says
   that applying the theme is a manual step in Analyst.
9. The response tells the user to check the HTML with the skill's sanitizer check
   (`check_textarea_html.py`) and, ideally, to preview it with `make_preview.py`, and to test on a
   machine with HTML sanitizing on.
10. HTML element ids are camelCase and unique per page; the response names the paste and attach
    steps per page.
