---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

On our Spotfire 15.0 "Pump Ranking" bar chart I want two small buttons in the visual's title bar:
one that clears the "Selected Pump" marking, and one that opens the "Pump Detail" page. Right now
both are IronPython scripts behind text-area buttons, and when I tried to add them to the title
bar the IronPython scripts were not offered.

Please build what I need under `ranking-actions/`, with icons, and tell me how to test it before
I touch Spotfire and how to hook the buttons up.
