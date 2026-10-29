# Data function patterns

## Shared outputs: several methods, one set of KPI properties

Sibling functions (for example three regression methods) often write the same KPI properties, and
a `Method` property says which one is active. Spotfire raises
`DataFunctionError: Output variable '<name>' was not defined` when a registered output is not
assigned, so every sibling must assign every shared output on every path.

Contract:

- Each sibling registers every shared property as an input and as an output, with the same name.
- The active sibling computes the values. An inactive one passes the incoming values through.
- Both paths cast at the staging boundary.

```python
# ============================== STAGING: OUTPUTS =============================
if Method == "PLS":
    ModelRSquared, ModelRmse, ModelRuns = fit_pls(data)
else:
    # Not the active method: pass the current values through unchanged.
    ModelRSquared, ModelRmse, ModelRuns = ModelRSquared, ModelRmse, ModelRuns
ModelRSquared = float(ModelRSquared)
ModelRmse = float(ModelRmse)
ModelRuns = int(float(ModelRuns))
```

The defaults in `STAGING: INPUTS` cover the first run, when the properties are still empty.

When the suite compares methods, add one join function that reads each method's output table and
writes a long comparison table (method, metric, value) for one chart.

## Customer staging function: map the user's columns onto the app's model

An app that ships with demo data should also run on the user's data. One staging function maps
the user's tables onto the canonical tables the rest of the app reads.

Contract:

- Inputs split into REQUIRED and OPTIONAL tables. Every one is handled defensively: an optional
  table that is not bound arrives as `None`.
- One String document property, `ColumnMapJson`, holds
  `{"<table>": {"<Canonical Column>": "<User Column>"}}`. Columns that already have the canonical
  name (any letter case) map themselves and can be left out.
- When an optional table is missing, fill the gap from first principles or documented defaults
  (for example pump curves from nameplate data with the affinity laws) instead of failing. Name
  every default and its source in the header.
- Write a validation table, one row per check: table, column, status (found, mapped, defaulted,
  missing), detail. Show it on a Data Staging page.
- Document the canonical model in the header as Required and Optional column tables with units,
  join keys and defaults.

```python
import json

def column_map(raw, table, frame, canonical):
    """{canonical: user column} for one table; canonical names match
    themselves without regard to case."""
    try:
        given = json.loads(raw or "{}").get(table, {})
    except ValueError:
        given = {}
    lower = {c.lower(): c for c in frame.columns}
    found = {}
    for name in canonical:
        if name in given and given[name] in frame.columns:
            found[name] = given[name]
        elif name.lower() in lower:
            found[name] = lower[name.lower()]
    return found
```

## Large engines: a catalog of outputs

A function that writes many tables documents them as a numbered catalog in the header: name, row
count of the demo run and the visual that shows it. The catalog is the contract between the
engine and the page builder.

```
#  1  PUMP_EFFICIENCY          216  Efficiency Trend (line chart)
#  2  PUMP_EFFICIENCY_SUMMARY    3  Pump Ranking (table)
#  3  EVENT_LOG                 11  Downtime Events (bar chart, Gantt style)
```

## Events and relations

An events table carries an `Event ID` key column (and the asset and time columns the time series
uses), so a table relation or a marking can connect each event to its readings.

## Determinism, packages and network

- Randomness goes through `np.random.default_rng(seed)`, with the seed as an input.
- List every package the function imports in the header. The Spotfire 15.0 data function Python
  bundles numpy and pandas; scipy, statsmodels and scikit-learn are not in it, so anything else is
  an install the user or the administrator must make.
- The default path works without a network. A function that fetches data (a weather API, a REST
  service) says so in the header and fails with a clear status message when offline.
- No credentials as constant inputs: they are stored in the DXP in clear text.

## Write real methods

Name the method in a comment (NIPALS for PLS1, Arps hyperbolic decline, Darcy-Weisbach friction)
and cite constants and their ranges. When the function relies on an assumption about the user's
data (units, sampling, sign conventions), state it in the header. If the App Brief and Logic Spec
exist, the function implements the Logic Spec IDs it names; do not change the Logic Spec without
telling the user.
