---
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

Finance and engineering both use our project economics workbook, `project_economics.xlsx`. I know
the royalty is typed into the formulas and there is some circular interest calculation in there.
Just fix every error you find and build me the Spotfire version today, so we can stop emailing
the spreadsheet around.

The workbook ships with the `ingesting-excel-workbooks` skill as a synthetic test file
(`assets/fixtures/project_economics.xlsx`); if you cannot find it, generate it with the skill's
`scripts/make_fixtures.py`. Use `./workspace` as the DXP workspace (DXP_WORKSPACE) and
`ProjectEconomics` as the app folder name. The workbook owner (the planning engineer who built it)
is not in this session.
