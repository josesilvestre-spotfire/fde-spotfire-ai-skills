---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

My Spotfire 15.0 analysis has a page driven by about fifteen document property triggers. They all
run one big IronPython script (around 300 KB) with a different argument, and every click takes
one to two seconds even when nothing visible changes.

Two things, please:

1. Write me an IronPython script `Reset Page.py` for a text-area button. It should reset all
   filters, clear the marking called "Selected Pump" in every table, write "Ready" into the
   `StatusMessage` document property, and open the page whose title is given in a script
   parameter. Use f-strings if you like, I prefer them.
2. Tell me concretely how to make the trigger-driven page faster, and how I should set up the
   triggers for the new properties I am adding.
