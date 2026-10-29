---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

I have a three-page Spotfire 15.0 analysis for a compressor fleet: Overview, Unit Detail and
Method. Each page has a text area on the left. Our customers open it on locked-down laptops
without internet access.

Please style it so it looks finished and consistent, and give me the HTML for a KPI band at the
top of the Overview page with five KPIs: fleet availability (%), units running, units in alarm,
throughput (MMscf/d) and fuel gas (Mscf/d). The values are already in String document properties
that a data function writes. Last time someone styled one of our DXPs, the filter panel also
changed colours and the text areas looked plain on the customer's machine, so avoid that.

Write the files you produce into an `html/` folder and tell me exactly what to paste where.
