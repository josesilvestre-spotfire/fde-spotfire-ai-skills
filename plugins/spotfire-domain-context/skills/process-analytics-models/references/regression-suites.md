# Regression suites

Use a regression suite when the goal is to explain or validate a decision (which wells to
recomplete, which equipment to overhaul), not only to predict. **Not yet tested** as code in
this library; the design comes from a three-model suite delivered as Spotfire data functions
over a synthetic dataset of about 4,000 wells and 12 completion and geology variables.

## Three joint models

One design matrix, one train/test split, one output contract.

| Model | Method | Interpretability artifact |
|---|---|---|
| OLS | Least squares via `np.linalg.lstsq` | Coefficients with standard errors, t statistics, p-values, and the variance inflation factor (VIF) per predictor |
| PLS1 | NIPALS, number of components chosen by cross-validation | VIP scores (variable importance in projection) |
| Gradient boosted trees | Shallow regression trees fitted to residuals | Permutation importance on the test split, ICE (individual conditional expectation) curves |

Notes:

- VIF_j = 1 / (1 - R2_j), where R2_j regresses predictor j on the others. Report it with the
  coefficients: a coefficient on a predictor with a high VIF is not interpretable on its own.
- p-values need the t distribution. Without scipy, compute it from the regularised
  incomplete beta function (a short continued fraction), or install scipy.
- PLS1 by NIPALS needs only NumPy. Choose the component count by k-fold cross-validation on
  the training split and report the curve, not just the choice.
- Gradient boosting needs scikit-learn or a hand-written booster. scikit-learn is not in the
  Python bundled with Spotfire Analyst 15.0 (observed).
- Permutation importance is computed on the test split, by the drop in score when one column
  is shuffled.

## Comparison tables

A comparison function joins the three models' outputs:

- `modelComparisonLong`: one row per (record, method) with actual and predicted.
- `modelComparisonWide`: one row per record, one predicted column per method.
- `modelComparisonMetrics`: one row per (method, split) with R2, RMSE, MAE and adjusted R2.

## Spotfire wiring

- A `method` document property selects the active model. Every function maps the shared
  output KPI properties (for example `outR2`, `outRmse`, `outAdjR2`) as both inputs and
  outputs, and an inactive function passes its inputs through unchanged, cast to the
  property type. A function that leaves a registered output unset fails with
  `DataFunctionError: Output variable was not defined`.
- Scalars written to document properties are cast to native Python types
  (`int(float(x))`, `float(x)`), in the pass-through branch too.
- Each output table names the visual it feeds; the run chain that executes the functions is
  documented next to them.
- The `writing-spotfire-data-functions` skill covers staging blocks, registration tables and
  SBDF-safe dtypes.

## Validating an agent's recommendations

When an LLM agent recommends a set of items (wells, assets), decompress its output into
classical statistics to show whether the picks are defensible:

- An **oriented decile heatmap**: for each variable, which decile of the full distribution
  each selected item falls in, oriented so "better" is always the same direction.
- A **scorecard**: the share of picks in the top decile or top quintile per variable.
- An **ID bridge**: a key (for example a well id) joining the agent's output to the analytical
  tables, so every pick can be marked and inspected in the same analysis.

The claim to test is that the agent's picks land in the top deciles of the variables that
drive the outcome. If they do not, the heatmap shows where they diverge.

## Economics layer

Pair a model with an economics function when the decision is financial: payback months, IRR
and NPV at a 10 percent discount rate under the applicable fiscal regime (royalty, severance
and production taxes). Price decks and the discount rate are document properties so the user
can run scenarios.
