---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Our analysis `C:\ui-tests\production_review.dxp` (Spotfire Analyst 15.0) has one page with four
visuals: a "Wells" bar chart (left half), an "Oil Rate" line chart (top right), a "Well
Details" table (bottom right) and a KPI text area across the top. Users complained that marking
a well in the bar chart does not update the details table.

I want an automated UI test for this: mark a well in the bar chart, check that the line chart
and the details table update and that the KPI band stays as it is, then clear the marking. The
window will be placed at 40, 40 with size 1600 x 1000; I measured the visuals in a screenshot:
KPI band 0,60 to 1600,180; Wells 0,190 to 800,1000; Oil Rate 810,190 to 1600,590; Well Details
810,600 to 1600,1000.

Write the test plan to `ui-test/plan.json` and a short `ui-test/README.md` that says how you
will run it, what you need from me first, and how you decide pass or fail.
