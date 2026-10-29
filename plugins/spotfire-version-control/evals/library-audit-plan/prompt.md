---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

We exported our team's Spotfire analyses to `C:\exports\analyses`: about forty DXP files in
subfolders, with several versions of most analyses (for example `Line Pack_v2.dxp`,
`Line Pack (3).dxp`, `compressor_trips_20261012.dxp`). Before we publish to the new library we
need to know what changed between versions of each analysis and which files break our design
rules or contain anything that must not be shared.

dxpkit is not installed here and this machine has no Spotfire. Write `audit-plan.md` with the
commands you will run, the files they produce, and how we should read the results.
