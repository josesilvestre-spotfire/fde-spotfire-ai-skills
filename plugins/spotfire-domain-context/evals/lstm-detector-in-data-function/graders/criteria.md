---
type: llm
weight: 1
---

Grade the response and `detector.py`. Pass when at least 6 of the 8 criteria hold and
criterion 1 holds.

1. **No unavailable packages.** Recognises that torch (and TensorFlow or Keras) is not
   available in Spotfire's bundled Python and cannot be installed, and implements the LSTM
   autoencoder with NumPy (and pandas) only: forward pass, backpropagation through time and
   an optimiser. `detector.py` imports no torch, tensorflow, keras, scikit-learn or scipy.
2. **Training data.** Trains only on windows from the training split whose steps are all
   labelled Normal, with standardisation statistics taken from those rows.
3. **Threshold from training.** The threshold is calibrated on training data (a quantile of
   training scores, or a distributional threshold fitted on training errors), never on the
   test split.
4. **Scoring output.** Scores every row or window and returns a table with the timestamp, a
   score and a flag, plus the threshold as a single native Python number.
5. **Spotfire-safe types.** Output columns have concrete dtypes (no `None` in numeric
   columns, `np.nan` for missing), and scalar outputs are cast to native `float` or `int`.
6. **Attribution.** Provides a way to see which tag drove a flag (per-feature
   reconstruction error or contribution, or a top-feature column).
7. **Evaluation advice.** Recommends evaluating on the held-out test split only, counting
   detections per event rather than per sample, and reporting detection latency and false
   alarms alongside precision and recall.
8. **Reproducible.** Uses a fixed random seed and states its default hyperparameters (window
   length, hidden size, epochs).
