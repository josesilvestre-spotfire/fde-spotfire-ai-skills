---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill, Write]
---
We want to publish our "Tank Inventory Review" DXP to the Spotfire library this week so the other
sites can use it with their own tank data. Below is what is in it. Review it against your design
rules and publishing checklist and tell me what must change before we publish, most important
first.

Pages, in this order:

1. `Page (2)`: an empty scratch page.
2. `Overview`: a KPI chart with four tiles (Total Inventory, Days of Cover, Tanks Below Minimum,
   Fill Rate); a bar chart of inventory by tank on table `TANK_LEVELS` with marking `Marking`; a
   line chart of level history on table `LEVEL_HISTORY` with marking `Marking (2)`, limited by
   `Marking` with empty behaviour ShowEmpty.
3. `Tank Detail`: a left sidebar with drop-downs for Tank, Noise Level, Random Seed and Map Color
   By, and a map on the right.
4. `Simulator Settings`: buttons to regenerate the demo data.
5. `About`: two paragraphs on how the data function works.

Other facts:

- The Filters panel on every page shows all five tables, including `Row ID`, `Latitude`,
  `Longitude` and `Sim Seed`.
- The data function is called `Untitled`. Its first comment line is
  `# TODO: remove hack from the v0.3 prototype before release`.
- A table `tmp_join` is not used by any visual or data function.
- `LEVEL_HISTORY` is a linked CSV file at `D:\work\tanks.csv`.
- The cover text we planned to use starts with "This Spotfire dashboard uses advanced analytics".
- Nobody except the author has opened it yet.
