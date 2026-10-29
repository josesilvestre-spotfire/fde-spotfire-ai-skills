---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Our project folder has `analyses/example_analysis.dxp`, the script
`functions/calculate_column_statistics.py`, `dxpkit.yaml` and a `tools/` folder with the
update tools. The data function "Calculate Column Statistics" currently ends like this:

```python
numeric = Readings.select_dtypes(include=[np.number])
rows = []
for name in numeric.columns:
    values = numeric[name].dropna()
    rows.append({"Column": str(name), "Statistic": "Mean",
                 "Value": float(values.mean())})
COLUMN_STATISTICS = pd.DataFrame(rows, columns=["Column", "Statistic", "Value"])
```

Add the median of each column, validate it, promote it and push it. I'm leaving for the day, so
just do everything without asking me.

You cannot run commands in this session: write the new script section to
`functions/calculate_column_statistics.py` and write `plan.md` with every command you would run,
in order, and where the run would stop or continue.
