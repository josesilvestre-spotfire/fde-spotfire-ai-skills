---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

I need a simple Spotfire visualization mod: a scatter plot of pump flow (x) against head (y),
one dot per row, coloured by Spotfire's own colour axis, where clicking a dot marks it and
Ctrl+click adds it to the marking. Some of our field sites still run an older Spotfire client
that only understands mods API 1.3, so it must load there too.

Last time our mod worked in the dev server but printing and PDF export just hung, and users
complained that the dots collapsed into one point when they dragged a column onto the X axis.

Write the mod project (manifest, index.html, main.js, main.css) under `scatter-mod/` plus a
headless test, and a short README for the people who install it.
