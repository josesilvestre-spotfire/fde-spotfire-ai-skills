---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

I have a Python data function in Spotfire Analyst 15.0 that worked last month. Now when it runs,
the table `PUMP_SUMMARY` never shows up and the bar chart that uses it is empty. The scalar output
still updates. Nothing changed in the script. A colleague says I installed some packages for my
own Python 3.14 recently. Here is the script:

```python
import pandas as pd
import numpy as np

df = readings.copy()
df["Efficiency"] = df["Hydraulic_hp"] / df["Shaft_hp"] * 100
summary = df.groupby("Pump").agg(eff=("Efficiency", "mean"), n=("Efficiency", "count")).reset_index()
summary["status"] = np.where(summary["eff"] < target, "Below target", "On target")
summary.loc[summary["n"] < 10, "eff"] = None

PUMP_SUMMARY = summary
belowTarget = (summary["status"] == "Below target").sum()
```

`readings` is a table input, `target` is bound to a document property, `belowTarget` goes to a
LongInteger document property. Please explain why the table is missing, and write a fixed,
production-ready version of the data function to `calculate_pump_summary.py` that I can register
by hand.
