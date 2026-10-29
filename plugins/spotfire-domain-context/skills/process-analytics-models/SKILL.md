---
name: process-analytics-models
description: Builds and reviews analytics models for process and production data that are delivered as Spotfire data functions, including interpretable regression suites (OLS with VIF, PLS1 by NIPALS with VIP, gradient boosted trees with permutation importance and ICE), anomaly detection (an LSTM autoencoder written in NumPy so it runs without torch, Isolation Forest and PCA baselines), forecasting with simulated paths, operation libraries over time series and events, and backtesting with strict holdout and event-level scoring. Use when writing or checking a model, a detector or its evaluation for an app, especially when it must run inside Spotfire's bundled Python.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Process analytics models

**Pending SME review:** the modelling rules and defaults below have not yet been reviewed by an independent data science or process SME.

Models for process apps have to be explainable to an engineer and honest about how they
were evaluated. Every model here ships with its interpretability artifact, is scored on a
held-out future window, and is written so it can run inside a Spotfire Python data function.

`scripts/numpy_lstm_autoencoder.py` is a NumPy LSTM autoencoder anomaly detector with
Mahalanobis scoring, a scipy-free chi-square threshold, and window-level and event-level
metrics.

```bash
python scripts/tests/test_numpy_lstm_autoencoder.py     # 6 tests incl. a gradient check
```

```python
from numpy_lstm_autoencoder import fit_detector, score_detector, event_metrics
model = fit_detector(X_train, normal_mask, seq_len=24, hidden=64, latent=16, epochs=30)
scores = score_detector(model, X_holdout)          # end_idx, d2, flags, contrib
report = event_metrics(scores["end_idx"], scores["flags"], event_id_holdout)
```

## The Python inside Spotfire

Observed on Spotfire Analyst 15.0: the bundled Python (3.14) carries numpy, pandas and the
`spotfire` package, without torch, scipy or scikit-learn. A user-level site-packages folder
can load before the bundled packages, so code must run on pandas 2.x and 3.x.

- An LSTM autoencoder that must run inside a data function is written in NumPy. A NumPy
  port with the same architecture, initialisation, optimiser and seed as a torch original
  ran as a data function on Spotfire Analyst 15.0, reached a window-level F1 of 0.985
  against 0.98 for the torch model on the same synthetic dataset, and trained in about 5
  seconds. `scripts/numpy_lstm_autoencoder.py` is that core, extracted and tested offline.
- Anything else from scipy or scikit-learn (p-values, gradient boosting, Isolation Forest)
  either gets installed through Spotfire's Python package management, where the deployment
  allows it, or is written in NumPy. Decide which before you write the model.
- Use the `writing-spotfire-data-functions` skill for staging blocks, registration tables
  and SBDF-safe outputs.

## Rules for every model

1. **Holdout first.** Evaluate on a held-out future window with its own labelled events,
   never in-sample and never on a random row split of a time series.
2. **Count events, not samples**, when scoring a detector: an event is detected if the
   detector fires inside it. Sample counting inflates recall on long events. Report
   detection latency per event and false-alarm runs alongside precision and recall.
3. **Calibrate thresholds on training data only.**
4. **Interpretability ships with the model**: coefficients with SE, t, p and VIF for OLS;
   VIP for PLS; permutation importance and ICE curves for boosted trees; per-feature
   contribution for the autoencoder.
5. **Deterministic**: fixed seeds, an explicit split column, metrics reported per split.
6. **No black-box-only delivery.** If a model's output cannot be explained to the engineer
   who acts on it, pair it with one that can.

## Regression suites

Three joint models over one design matrix, one train/test split and one output contract:
OLS, PLS1 (NIPALS, cross-validated component count) and gradient boosted trees, plus a
comparison function writing long, wide and metrics tables of predicted against actual for
every method. A method selector document property switches the active model. Details:
[references/regression-suites.md](references/regression-suites.md).

## Anomaly detection

LSTM autoencoder as the primary detector, Isolation Forest and PCA as fast classical
baselines, all under the same split discipline. Details, threshold choices and packaging:
[references/anomaly-detection.md](references/anomaly-detection.md).

## Forecasting, operation libraries and backtesting

Stochastic forecast paths (simulated trajectories, not only a mean and an interval),
composable time series and event operations with `__Event_ID` stamps for Spotfire data
relations, and walk-forward backtests with no lookahead:
[references/forecasting-and-backtesting.md](references/forecasting-and-backtesting.md).

## Reviewing someone else's model

- Was it scored on a future holdout, and per event?
- Was the threshold set on training data?
- Does a significance claim on time series use a naive standard error? (See the
  `analyzing-process-time-series` skill for the autocorrelation correction.)
- Does the training window contain the anomalies the model is later asked to find?
- Is there any feature computed with future data (a centred rolling window, a full-series
  normalisation)?
- Is there an interpretability artifact an engineer can check?

## Status

The NumPy autoencoder core ran inside Spotfire Analyst 15.0 as part of an app; the module
here is that core extracted, with tests run offline (Python 3.14, numpy 2.5). The regression
suite, baselines and backtesting rules come from builds on one machine; their code is not
shipped and is **Not yet tested** in this library.

## References

- [references/regression-suites.md](references/regression-suites.md): OLS, PLS1, GBT,
  comparison tables, agent-recommendation validation, economics layer.
- [references/anomaly-detection.md](references/anomaly-detection.md): the NumPy LSTM
  autoencoder, baselines, thresholds, event-level evaluation, packaging.
- [references/forecasting-and-backtesting.md](references/forecasting-and-backtesting.md):
  forecast paths, operation library design, test bench, backtesting.
- [references/build-briefs.md](references/build-briefs.md): fill-in briefs for a regression
  suite, an anomaly detection stack and an operation library extension.
