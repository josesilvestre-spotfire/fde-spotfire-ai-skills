---
type: llm
weight: 1
---

Grade the agent's work on turning the Streamlit prototype into Spotfire hand-off files. Read the
files it wrote under `./workspace/apps/CompressorWatch/` and its final message.

Pass when all of the following hold:

1. **Hand-off files exist.** `app-brief.md`, `logic-spec.md` and `spec.json` are in
   `./workspace/apps/CompressorWatch/`, plus a mapping table (for example
   `ingest/mapping-table.md`) with one row per prototype element giving its Spotfire element and a
   fidelity (EXACT, CLOSE, SUBSTITUTE or MANUAL). `spec.json` is valid JSON.
2. **App Brief.** Starts with the business problem, lists users, KPIs (hours above limit, peak
   temperature) each tied to a Logic Spec ID, inputs, outputs with their page, data sources and
   open questions.
3. **Logic Spec.** Has entries for the rolling mean, the rolling standard deviation or the
   plus and minus two sigma band, the hours-above-limit count and the peak temperature, each with
   an equation and units (degF, h). Because the owner was not available, entries are marked
   inferred, not confirmed.
4. **Inputs become properties and controls.** Compressor, period, temperature limit and rolling
   window each become a document property in PascalCase (for example `CompressorId`,
   `PeriodStart` and `PeriodEnd`, `TemperatureLimit`, `RollingWindow`) with a control in a
   text-area `controls` block. Where a data function reads a property, the parameter has the same
   name as the property.
5. **Naming standard.** Tables are UPPER_SNAKE_CASE, columns are Title Case with units in
   parentheses (for example `Discharge Temperature (degF)`), visual ids are camelCase.
6. **The four gap constructs get named substitutes:**
   - `st.tabs` inside the page: separate pages or views stacked on one page (SUBSTITUTE);
   - the datetime range slider: two Date or DateTime properties with input controls, or a range
     filter on the time column (SUBSTITUTE);
   - `fill="tonexty"`: the lower and upper edges drawn as series of one color (G2 option 2),
     or a band reference layer that the mapping table marks as needing the build's slim
     tier (SUBSTITUTE or CLOSE);
   - `st.file_uploader`: no Spotfire control; data is loaded at build time and replaced through
     Spotfire's data menus (MANUAL).
   Each one is flagged for the owner to approve (an empty or pending owner decision, or an open
   question), not marked as approved.
7. **No build.** The agent does not write an IronPython builder, does not claim to have opened
   Spotfire or saved a DXP, and does not produce a `.dxp` file.
8. **Hand-off.** The final message names the `building-spotfire-dxps` skill as the next step and
   lists what the owner must still approve.

Fail when any item above is missing, when the agent invents owner approval or confirmation, or
when it builds or claims to build the DXP. Minor wording differences in names are acceptable when
they follow the naming standard.
