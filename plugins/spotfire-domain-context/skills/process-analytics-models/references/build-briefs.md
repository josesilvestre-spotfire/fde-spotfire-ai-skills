# Build briefs

Fill-in briefs for asking an agent to build a complete model stack in one pass. Fill in the
bracketed fields and send one brief as one message.

## A: Interpretable regression suite as Spotfire data functions

Build a three-model regression suite over **[dataset and target, for example "4,000 wells,
recompletion uplift on 12 completion and geology variables"]** as Spotfire data functions.

1. Three joint models over one design matrix, one train/test split and one output contract:
   OLS (coefficients, SE, t, p, VIF), PLS1 by NIPALS (cross-validated component count, VIP),
   gradient boosted trees (permutation importance, ICE curves).
2. Follow the `writing-spotfire-data-functions` skill: staging blocks, registration tables,
   SBDF-safe outputs (`np.nan` never `None`, native scalar casts in every branch, a dtype
   coercion block).
3. A `method` document property selects the active model; every function maps the shared
   output KPI properties **[list them]** as both inputs and outputs and passes them through,
   cast, when inactive.
4. A comparison function writing `modelComparisonLong`, `modelComparisonWide` and
   `modelComparisonMetrics`.
5. **[If economics]** An economics function: payback months, IRR, NPV10 under **[fiscal
   regime]**, with the price deck and discount rate as document properties.
6. **[If validating an agent]** An oriented decile heatmap, a scorecard and an ID bridge
   (**[key column]**) joining the agent's picks to the analytical tables.
7. State which packages each function needs and whether they exist in the target Spotfire
   Python; write in NumPy what is missing.
8. Real statistics only: name the algorithm in comments, deterministic seeds, metrics per
   split. State every assumption at the end.

## B: Anomaly detection stack

Build an anomaly detection stack for **[asset]** over **[dataset with a Split column and
labelled events]**.

1. Primary detector: the NumPy LSTM autoencoder from this skill, trained on the training
   window's fully normal windows only, threshold calibrated on training, scored on the
   holdout.
2. Baselines: PCA (Q and T2) and **[Isolation Forest if scikit-learn is available]**, same
   split.
3. Report holdout performance only: events detected, latency per event, false-alarm runs,
   window precision, recall and F1.
4. Package as **[a Spotfire data function | a prototype app | both]**.
5. No in-sample numbers anywhere. State every assumption at the end.

## C: Operation library extension

Extend the operation library with **[ops and signatures]**:

1. Each op is a documented function over (time, value, group) frames with one output
   contract; event ops return an events table and stamp `__Event_ID` onto the series rows.
2. Each op registers itself; no user interface change is needed.
3. Each op has a synthetic-data unit test with a known answer.
4. Forecasting ops return simulated paths with a reported seed.
