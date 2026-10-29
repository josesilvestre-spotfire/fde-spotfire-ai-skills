---
type: llm
weight: 1
---

Grade `audit-plan.md` and the response. Pass when all of these hold; list every criterion that
fails.

1. The plan uses a read-only tool that works without dxpkit and without Spotfire (the skill's
   `dxp_inventory.py`, standard library only) and runs the library audit recursively over the
   export folder (`library C:\exports\analyses -o <report> --recursive` or equivalent).
2. It explains that versions are grouped by file name patterns (`_v2`, `(3)`, a date suffix),
   ordered, and diffed one after the other, and that the report holds `LIBRARY.md`, per-file
   text, diffs and check results.
3. It separates blocking findings (local paths with a user folder, credential-like strings,
   empty pages) from warnings for the owner (KPI charts instead of HTML KPI bands, visuals that
   cannot be marked, mixed markings, default names, missing descriptions).
4. It states which design rules a file audit cannot check (for example empty visuals or whether
   marking updates every visual, which need the analysis running) and does not claim row counts
   or rendered results.
5. It tells the reader how to interpret a script change: a script change with no trust stamp
   change means the script was written without Spotfire, so the function is untrusted until
   someone trusts it.
6. It never modifies the exported DXPs and does not propose installing or copying dxpkit code to
   do the audit.
