"""Tests for the simulator skeleton. Plain asserts with a built-in runner, so they run
without pytest: `python scripts/tests/test_simulator_skeleton.py`. pytest collects them too.
"""

from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulator_skeleton as sim  # noqa: E402


def test_every_event_meets_its_verification_contract_across_seeds():
    for seed in range(1, 11):
        hist, events = sim.generate(seed)
        failed = [r for r in sim.validate(hist, events) if not r["ok"]]
        assert not failed, (seed, failed)


def test_generation_is_deterministic_for_a_seed():
    a, ea = sim.generate(3)
    b, eb = sim.generate(3)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(ea, eb)
    c, _ = sim.generate(4)
    assert not a["flow_bpd"].equals(c["flow_bpd"])


def test_train_and_holdout_each_carry_their_own_events():
    hist, events = sim.generate(5)
    assert set(hist["Split"]) == {"train", "test"}
    assert (hist["Split"] == "test").mean() > 0.2
    for part, count in sim.EVENTS_PER_WINDOW.items():
        assert (events["Split"] == part).sum() == count, events
    stamped = hist.loc[hist["__Event_ID"] != "", "__Event_ID"].unique()
    assert set(stamped) == set(events["Event ID"]), "an event left no stamp in the historian"


def test_noise_is_coloured_not_white():
    """Lag-1 autocorrelation of the noise on a constant-setpoint stretch must be high.
    White noise would give a value near zero."""
    rng = np.random.default_rng(0)
    x = sim.ou(5000, dt=1 / 24, theta=12.0, sigma=1.0, rng=rng)
    r1 = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert r1 > 0.5, r1


def test_spectral_check_catches_a_synthetic_daily_rhythm():
    """Negative control: add a clock-driven sine to flow and the check must fail."""
    hist, events = sim.generate(2)
    t = (hist["Timestamp"] - hist["Timestamp"].iloc[0]).dt.total_seconds() / 86400.0
    hist["flow_bpd"] = hist["flow_bpd"] + 1500.0 * np.sin(2 * np.pi * t)
    spectral = [r for r in sim.validate(hist, events)
                if r["check"] == "spectral_24h" and r["tag"] == "flow_bpd"]
    assert spectral and not spectral[0]["ok"], spectral


def test_an_unregistered_event_subtype_is_an_error():
    hist, events = sim.generate(1)
    events.loc[0, "Subtype"] = "Something Nobody Registered"
    try:
        sim.validate(hist, events)
    except KeyError:
        return
    raise AssertionError("an unregistered subtype was validated without a contract")


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
