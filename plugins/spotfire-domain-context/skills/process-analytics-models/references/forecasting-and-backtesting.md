# Forecasting, operation libraries and backtesting

**Not yet tested** as code in this library. These are design rules from an operation library
and a backtesting platform built on one machine.

## Forecasts as simulated paths

- Report a forecast as a set of simulated trajectories, not only a mean and an interval. A
  path shows when a threshold might be crossed and how often; an interval does not.
- Seasonal ARIMA is the reference method for stochastic paths. It needs statsmodels, which
  is not in the Python bundled with Spotfire Analyst 15.0 (observed); without it, fit a
  simpler model in NumPy (for example an AR model by least squares on the deseasonalised
  series) and simulate from its residual distribution.
- For a monotonic risk score (an anomaly score, a fouling index), a smoothed trend
  (exponentially weighted) extrapolated to a threshold gives a time-to-threshold estimate.
  State the fit window and smoothing span with the estimate.
- Seed every simulation and report the seed.

## Operation library design

An operation library is a set of functions over time series and events that an app composes
into calculations.

- **Composable ops** over a long frame of (time, value, group). Each op is a documented
  function with typed parameters and one output contract.
- **Calculation ops** return series (rolling statistics, rates of change, resampling,
  differences against a baseline). **Event ops** return an events table (start, end,
  duration, peak, group).
- **Event outputs carry `__Event_ID`** stamped back onto the series rows, so Spotfire data
  relations can join the series table and the events table and marking flows between them.
- **Ops register themselves** in a registry (a decorator), so adding one needs no change to
  the user interface.
- **Every op has a synthetic-data unit test** with a known answer.

## A test bench that mirrors Spotfire

A companion app (for example Streamlit) for the library works like Spotfire's reactive
engine: every control feeds a single computation module, outputs re-render automatically, and
the registry is the only integration point. A new op appears in the bench with no interface
change. This keeps the bench honest about what the data function will do.

## Backtesting

Applies to forecasts, detectors and decision rules alike.

- **Walk-forward evaluation**: fit on data up to t, evaluate on (t, t + h], advance t. Never
  evaluate on data the fit could see.
- **Pluggable model or strategy classes** with a declared parameter grid. A grid search
  produces a tidy results frame: one row per parameter combination per metric per fold.
- **No lookahead**, asserted by tests rather than by review:
  - Truncation test: compute every feature on the data up to t and on the full data; the
    values at t must be identical. Any difference means the feature uses future data (a
    centred window, a full-series normalisation, a backfilled value).
  - Shifted-signal test: lag every signal by one extra step. A large drop in performance
    means the original result depended on information from the step it acts on.
- **Out-of-sample split honoured** in the grid search itself: choose parameters on the
  validation folds, report on a final holdout that the search never saw.
- **Deterministic seeds**, and metrics reported per fold and per split.
