# Anomaly detection

## Data and split

- A time-ordered multivariate historian frame with a `Split` column (`train`, `test`) and
  per-row labels or event ids. The `generating-synthetic-process-data` skill produces this
  shape.
- Train on the training window only, and only on windows whose every step is normal.
- Calibrate the threshold on the training windows.
- Report holdout performance only. An in-sample anomaly count is not evidence.

## Primary detector: LSTM autoencoder in NumPy

`scripts/numpy_lstm_autoencoder.py`:

| Step | What it does | Default |
|---|---|---|
| Standardise | Mean and sd of normal rows per feature | sd below 1e-9 set to 1 |
| Window | Sliding windows of `seq_len` samples | `seq_len` 24, training stride 2, scoring stride 1 |
| Network | LSTM encoder, linear bottleneck, repeated latent, LSTM decoder, linear output | `hidden` 64, `latent` 16 |
| Train | Mean squared reconstruction error, adaptive moment estimation | lr 1e-3, batch 128, `epochs` 30, seed 42, float32 |
| Score | Mean absolute error per feature per window, then Mahalanobis D2 against the training error distribution | ridge 1e-6 on the covariance |
| Threshold | Chi-square inverse CDF with F degrees of freedom at `alpha`, or the `alpha` quantile of training D2 | `alpha` 0.995 |
| Attribute | `(e - mu) * sqrt(diag(Sigma^-1))` per feature | top feature per window |

Why Mahalanobis on the error vector rather than total reconstruction error: features
reconstruct with different accuracy, and their errors are correlated. D2 accounts for both,
and its per-feature decomposition tells the engineer which tag drove the flag.

The chi-square threshold assumes the error vectors are roughly Gaussian; when the training
D2 distribution has a heavy tail, use the quantile mode. Compare the flag rate on the
training windows with `1 - alpha` to see which one fits.

Proven facts behind this module (Spotfire Analyst 15.0):

- The bundled Python has no torch and no scipy, so the network, its backpropagation, the
  optimiser and the chi-square quantile are all NumPy or standard library.
- A data function built on this code ran in Spotfire, matched the torch original's
  window-level F1 (0.985 against 0.98 on one synthetic 10-feature dataset) and trained in
  about 5 seconds at the defaults above.

The extracted module is tested offline with a finite-difference gradient check, a
chi-square comparison against scipy, a planted-anomaly holdout test and determinism checks.

## Baselines

Run at least one classical baseline under the same split so the autoencoder has to earn its
complexity:

- **PCA**: fit on normal training rows; score by squared prediction error (Q) and Hotelling
  T2. NumPy only (`np.linalg.svd`).
- **Isolation Forest**: needs scikit-learn (not in the bundled Python) or a warehouse
  implementation; for in-warehouse scoring, a Snowpark version runs next to the data.

If a baseline matches the autoencoder on the holdout, ship the baseline.

## Evaluation

| Metric | How | Why |
|---|---|---|
| Event recall | Events with at least one flagged window ending inside them, over all events | Long events otherwise dominate sample-level recall |
| Latency | Samples from event start to the first flag, per event | A late detection may be useless |
| False-alarm runs | Runs of consecutive flags outside every event | Operators experience runs, not samples |
| Window precision, recall, F1 | A window is truly anomalous when any step in it is anomalous | Comparable with published autoencoder results |

`event_metrics` and `window_metrics` in the module compute these.

## Packaging

- **Spotfire data function**: inputs are the labelled historian table and the hyperparameters
  as document properties; outputs are a scores table (timestamp, D2, flag, top feature), a
  loss-per-epoch table, a feature attribution table and the threshold as a document
  property. Train behind a button (manual refresh) so moving a slider does not retrain.
  User problems (no normal rows, fewer than 2 features, too few windows) return empty tables
  and a status message rather than raising.
- **Prototype apps** (Shiny, Streamlit) use the same module and show holdout results only.
