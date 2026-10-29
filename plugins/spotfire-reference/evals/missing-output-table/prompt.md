---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill, Write]
---
I have a Python data function in Spotfire Analyst 15.0 that returns a pandas DataFrame with a few
text columns (well name, status, comment) and some numbers. It runs without any error, but the
output table never shows up in the analysis. My colleague opens the same DXP and the table appears
fine on her machine. I also use Python 3.14 on my laptop for other work.

What is going on, and how do I fix the data function so it works on both machines?
