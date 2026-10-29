---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

I need demo data for a Spotfire anomaly-detection app on a crude oil pump station: 180 days
at 15-minute samples with suction pressure, discharge pressure, flow, motor power, crude
temperature and line pressure drop. Include a handful of labelled events of different kinds
and a holdout period at the end so we can test a detector on data it never saw.

Write the generator as `gen_pump_data.py` using numpy and pandas only, run it, and tell me
how you checked that the data looks like a real plant historian rather than a textbook
signal.
