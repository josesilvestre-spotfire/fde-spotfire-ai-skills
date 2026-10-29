---
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

Our pipeline group calculates the pressure profile of a liquid line in an Excel workbook,
`pipe_pressure_drop.xlsx`. We want to move it into Spotfire eventually, but first we need to know
what the workbook does and whether we can trust it.

A copy of the workbook ships with the `ingesting-excel-workbooks` skill as a synthetic test file
(`assets/fixtures/pipe_pressure_drop.xlsx`); if you cannot find it, generate it with the skill's
`scripts/make_fixtures.py`. Use `./workspace` as the DXP workspace (DXP_WORKSPACE) and
`LinePressureProfile` as the app folder name.

Document the workbook for its owner: how it is structured, what each calculation does, what is
wrong with it, and what you need to ask the owner. The owner is not available in this session.
Do not open Excel.
