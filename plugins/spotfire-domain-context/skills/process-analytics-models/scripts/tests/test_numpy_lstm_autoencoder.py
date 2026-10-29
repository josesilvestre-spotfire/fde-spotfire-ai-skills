"""Tests for the NumPy LSTM autoencoder. Plain asserts with a built-in runner, so they run
without pytest: `python scripts/tests/test_numpy_lstm_autoencoder.py`. pytest collects them
too. numpy only; scipy is used for one comparison when it is installed.
"""

from __future__ import annotations

import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy_lstm_autoencoder as ae  # noqa: E402


def test_backpropagation_matches_finite_differences():
    """Every parameter gradient against a central finite difference, in float64."""
    rng = np.random.default_rng(0)
    p = ae.init_params(n_features=3, hidden=4, latent=2, rng=rng, dtype=np.float64)
    x = rng.normal(size=(2, 5, 3))
    _, grads = ae.ae_loss_and_grads(p, x)
    eps = 1e-6
    for name in ae.PARAM_ORDER:
        flat = p[name].reshape(-1)
        for j in rng.choice(flat.size, size=min(6, flat.size), replace=False):
            keep = flat[j]
            flat[j] = keep + eps
            up, _ = ae.ae_loss_and_grads(p, x)
            flat[j] = keep - eps
            down, _ = ae.ae_loss_and_grads(p, x)
            flat[j] = keep
            numeric = (up - down) / (2 * eps)
            analytic = grads[name].reshape(-1)[j]
            err = abs(numeric - analytic) / max(1e-8, abs(numeric) + abs(analytic))
            assert err < 1e-5 or abs(numeric - analytic) < 1e-9, (name, j, numeric, analytic)


def test_chi_square_quantile_without_scipy():
    assert abs(ae.chi2_ppf(0.95, 1) - 3.841458820694124) < 1e-8
    try:
        from scipy import stats
    except ImportError:
        return
    for alpha, dof in [(0.9, 2), (0.99, 5), (0.995, 10), (0.999, 30)]:
        assert abs(ae.chi2_ppf(alpha, dof) - stats.chi2.ppf(alpha, dof)) < 1e-6


def _synthetic(n=900, seed=1):
    """Five coupled features driven by two shared AR(1) drivers; an anomaly from row 700
    to 760 offsets feature 2 and so breaks its coupling to the drivers."""
    rng = np.random.default_rng(seed)
    drivers = np.zeros((n, 2))
    for i in range(1, n):
        drivers[i] = 0.95 * drivers[i - 1] + rng.normal(0, 0.3, 2)
    mix = np.array([[1.0, 0.2], [0.5, 0.8], [0.9, -0.4], [0.1, 1.0], [0.7, 0.7]])
    X = drivers @ mix.T + rng.normal(0, 0.05, (n, 5))
    event = np.full(n, "", dtype=object)
    X[700:760, 2] += 2.0
    event[700:760] = "EV1"
    return X, event


def test_detector_finds_a_planted_anomaly_on_holdout():
    X, event = _synthetic()
    train = np.arange(len(X)) < 600
    model = ae.fit_detector(X[train], np.ones(int(train.sum()), dtype=bool), seq_len=12,
                            hidden=16, latent=4, epochs=15, threshold_mode="quantile",
                            alpha=0.995, seed=7)
    assert model["losses"][-1] < model["losses"][0], model["losses"]
    hold = ~train
    scores = ae.score_detector(model, X[hold])
    ev = ae.event_metrics(scores["end_idx"], scores["flags"], event[hold])
    assert ev["events"] == 1 and ev["detected"] == 1, ev
    assert ev["per_event"]["EV1"]["latency_samples"] <= 12, ev
    assert ev["false_alarm_runs"] <= 6, ev
    wm = ae.window_metrics(scores["end_idx"], scores["flags"], event[hold] != "", 12)
    assert wm["recall"] > 0.5 and wm["precision"] > 0.5, wm


def test_training_is_deterministic_for_a_seed():
    X, _ = _synthetic(n=300)
    normal = np.ones(len(X), dtype=bool)
    a = ae.fit_detector(X, normal, seq_len=8, hidden=8, latent=2, epochs=2, seed=3)
    b = ae.fit_detector(X, normal, seq_len=8, hidden=8, latent=2, epochs=2, seed=3)
    assert a["losses"] == b["losses"]
    assert a["threshold"] == b["threshold"]


def test_too_little_normal_data_is_refused():
    X, _ = _synthetic(n=300)
    normal = np.zeros(len(X), dtype=bool)
    normal[:30] = True
    try:
        ae.fit_detector(X, normal, seq_len=12, epochs=1)
    except ValueError as exc:
        assert "normal rows" in str(exc)
        return
    raise AssertionError("trained on almost no normal data")


def test_event_scoring_counts_events_not_samples():
    end_idx = np.arange(10, 100)
    flags = np.zeros(90, dtype=bool)
    event = np.full(100, "", dtype=object)
    event[40:80] = "LONG"
    event[90:95] = "SHORT"
    flags[(end_idx >= 45) & (end_idx < 80)] = True        # long event hit, many samples
    flags[(end_idx >= 20) & (end_idx < 23)] = True        # one false-alarm run
    m = ae.event_metrics(end_idx, flags, event)
    assert m["events"] == 2 and m["detected"] == 1 and m["event_recall"] == 0.5, m
    assert m["per_event"]["LONG"]["latency_samples"] == 5
    assert m["false_alarm_runs"] == 1, m


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed.append(name)
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
