---
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

The Excel ingest step is done for our line pressure workbook. The app folder is
`apps/line-pressure-profile/` in my workspace: it has `app-brief.md`, `logic-spec.md`, a draft
`spec.json`, `data/SEGMENTS.csv`, `data/ROUGHNESS_BY_AGE.csv`,
`datafunctions/calculate_pressure_profile.py` and an `ingest/` folder with the calculation model,
`expected.csv` and `reconcile.py`.

Take it from here: get it ready to build as a Spotfire 15.0 DXP, and write me the plan for building
it and for proving the DXP gives the same numbers as the workbook. Our engineers will only trust it
if the numbers match. If anything in the hand-off needs to change, tell me before you change it.
Write the plan to `apps/line-pressure-profile/BUILD-PLAN.md`.
