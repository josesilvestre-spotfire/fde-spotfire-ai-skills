---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

A colleague's analysis of one of our crude oil pipeline segments concludes that wax is
building up in the line. The evidence: the residual between measured and predicted pressure
drop (daily averages, 8 months) rose by about 4 psi per month. Their method was to z-score
the residual within 20,000 BPD flow bands, fit a straight line to the z-scores against time,
and report p < 0.001 from the ordinary regression standard error.

Throughput rose over the same 8 months. The viscosity the hydraulic model uses comes from a
weekly lab assay, and the drag reducer dose is logged as a tag.

Please review the conclusion. Tell me what is wrong or untested in the method, what you
would check in the data before trusting any trend, and what else could produce the same
rising residual. Then write a corrected trend calculation in Python that can run inside a
Spotfire data function (numpy and pandas only) and save it as `drift_check.py`. It should
take a DataFrame with a timestamp, the residual and the flow, and return the slope per month
with an honest confidence interval.
