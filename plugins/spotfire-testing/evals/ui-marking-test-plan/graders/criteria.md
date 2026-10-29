---
type: llm
weight: 1
---

Grade `ui-test/plan.json`, `ui-test/README.md` and the response. Pass when all of these hold;
list every criterion that fails.

1. `plan.json` is valid JSON in the skill's plan format: `analysis` (or `hwnd`), `window`
   (40, 40, 1600, 1000), `out`, named `boxes` matching the four measured regions as
   `[left, top, right, bottom]`, and `steps` with `do` actions.
2. The marking step (a click or drag on a bar inside the Wells box) expects `changed` for the
   Oil Rate and Well Details boxes (and may include Wells) and `unchanged` for the KPI box.
3. There is a step that clears the marking (for example a click on empty plot area) with its
   own expectation, and the plan starts with a harmless click on an empty part of the page
   because the first click after opening can be absorbed.
4. The test runs on a copy of the DXP, opened in a new Analyst process that the test starts and
   closes; it never uses or closes an Analyst window the user opened.
5. The README says the input commands must run unsandboxed (the sandbox drops input silently),
   that the user must agree before the mouse and keyboard are taken over, and that it will not
   run during a meeting or screen share.
6. Screenshots are window-only captures (PrintWindow), never full-screen or screen-region grabs.
7. Pass or fail combines the region-change numbers with reading the screenshots themselves; a
   region that changes is not taken as proof the change is correct. A failing Well Details box
   is reported with the before and after screenshots.
8. Nothing claims that Web Player or Playwright testing has been proven.
