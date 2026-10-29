---
type: llm
weight: 1
---

Grade the response and the files under `pump-monitor/`. Pass when all of these hold; list every
criterion that fails.

1. `pump-monitor/spec.json` exists, is valid JSON with `"specVersion": 1`, and describes the
   Overview page with a line chart (flow over time, colored by pump), a table and a text area whose
   HTML holds `{{control:<id>}}` placeholders for a drop-down and a button.
2. Names follow the naming standard: the document property for the pick is PascalCase (for example
   `SelectedPumpId`) and is the same name in the control binding, the line chart's limit expression
   and the scripts; the table is UPPER_SNAKE_CASE; columns are Title Case with units in parentheses
   (for example `Flow (bbl/d)`, `Discharge Pressure (psig)`); scripts are Title Case "Verb Object".
3. The pick property has a String default of `P-101`; the line chart limits its data with an
   expression on that property (for example `[Pump ID] = "${SelectedPumpId}"` or
   `DocumentProperty(...)`), not by building one table per pump.
4. The CSV is converted to SBDF with the skill's `sbdf_export.py` run by Spotfire's own Python
   (`SPOTFIRE_PYTHON`), with explicit types where needed (Timestamp as DateTime), and the spec loads
   the SBDF (the standard engine loads SBDF tables only).
5. The response gives the commands in order: `dxpgen.py validate`, then `dxpgen.py build` (standard
   tier), then running the builder, then `verify_dxp.py check`, and suggests `dxpgen.py release` for
   the handover.
6. The run instructions for Analyst are exact: a new analysis with starter data, Edit > Document
   Properties > Scripts > New, IronPython 3, untick "Execute in transaction", paste, Run Script,
   close with Cancel, then open the saved DXP and do not save the build session. It also mentions
   the unattended alternative (the `running-spotfire-unattended` skill) when that skill is present.
7. The response states that the drop-down, the Reset button and the property-change trigger have
   no public API in Spotfire 15.0: the builder leaves visible markers for the controls and lists
   the controls and the trigger in `build/MANUAL-STEPS-<tier>.md` (and as TODO lines in the build
   log), and the user adds them by hand after the build. The spec still declares them (`controls`,
   `triggers`).
8. Nothing in the response or the files edits `AnalysisDocument.xml` by hand, uses .NET reflection
   or non-public Spotfire classes, or claims the builder creates the controls or the trigger.
9. The response explains that the API member checks need an index generated on the user's own
   machine with `dump_api.ps1` (or `SFAPI_INDEX`), and that the tools still run without it.
10. The files contain no local user paths and no personal names; the text is customer-ready (no
    TODO or tool names in titles or HTML).
