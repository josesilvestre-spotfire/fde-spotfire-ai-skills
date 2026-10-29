"""Generate the synthetic example export.

    python assets/examples/make_data.py

Writes `assets/examples/example-profile/data.csv`: a wide frame with a timestamp index and N
columns of sensors and conditions. That is the whole of the engine's input contract, and
this file exists so that contract has a concrete, reproducible instance to test against
without using anyone's real data.

The column names use an ISA instrument-tag convention with no asset suffix, on purpose:
naming is a tag map's business, and an example that matched one particular export's
convention would hide an engine that had started assuming it.

Faults are planted deliberately so the check battery has something true to find, and each
is listed in references/example-walkthrough.md so a failure to detect one is visible as a regression
rather than as a quiet absence.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "example-profile", "data.csv")

SEED = 20260916
N = 400                       # hourly samples
FREQ = "1h"
START = "2026-01-01 00:00:00"


def build() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    idx = pd.date_range(START, periods=N, freq=FREQ)
    t = np.arange(N, dtype=float)

    # Throughput: a slow campaign structure plus noise, so regimes are real rather than
    # an artifact of binning white noise.
    flow = 120.0 + 35.0 * np.sin(2 * np.pi * t / 190.0) + rng.normal(0, 4.0, N)
    flow = np.clip(flow, 40.0, None)

    # Temperature: seasonal-ish drift plus a handful of genuine excursions. The excursions
    # get clipped further down, so dq_rail_saturation has a real clamp to find and
    # phys_range has a reason not to calibrate a band from the observed min and max.
    temperature = 28.0 + 4.0 * np.sin(2 * np.pi * t / 260.0) + rng.normal(0, 1.0, N)
    excursions = rng.choice(N, size=12, replace=False)
    temperature[excursions[:6]] -= 14.0
    temperature[excursions[6:]] += 14.0

    # Density: sampled weekly and held. 168 hourly samples per week.
    true_density = 845.0 - 0.45 * (temperature - 28.0)
    sample_at = np.arange(0, N, 168)
    density = pd.Series(np.nan, index=idx)
    density.iloc[sample_at] = true_density[sample_at] + rng.normal(0, 0.6, len(sample_at))
    density = density.ffill().bfill()

    additive = np.full(N, 12.0)          # a fixed dose: constant, so dq_flatline fires

    # Friction model: quadratic in rate, corrected for density.
    predicted_dp = 0.0016 * flow**2 * (density.to_numpy() / 845.0) + 0.8

    # Planted fault: a ramp restriction starting at sample 240, reaching ~7 percent.
    ramp = np.clip((t - 240.0) / 160.0, 0.0, 1.0) * 0.07
    # Planted fault: a step at sample 120 of ~3 percent, a discrete cause.
    step = np.where(t >= 120.0, 0.03, 0.0)

    measured_dp = predicted_dp * (1.0 + ramp + step) + rng.normal(0, 0.09, N)

    inlet_pressure = 620.0 + rng.normal(0, 1.5, N)
    outlet_pressure = inlet_pressure - measured_dp
    residual = measured_dp - predicted_dp

    # A rate-of-change detector thresholded on sign, which by construction fires on about
    # half of all samples. stat_detector_firing_rate exists to call this out.
    roc = np.diff(measured_dp, prepend=measured_dp[0])
    detector = (roc > 0).astype(int)

    df = pd.DataFrame({
        "Timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "PI-1001.PV": np.round(inlet_pressure, 3),
        "PI-1002.PV": np.round(outlet_pressure, 3),
        "PDI-1003.PV": np.round(measured_dp, 3),
        "PDI-1003.CALC": np.round(predicted_dp, 3),
        "PDI-1003.RESID": np.round(residual, 4),
        "FI-1004.PV": np.round(flow, 2),
        "TI-1005.PV": np.round(temperature, 2),
        "AI-1006.PV": np.round(additive, 1),
        "LAB.DENSITY": np.round(density.to_numpy(), 2),
        "Events - Positive Rate of Change": detector,
    })

    # A join duplicate: the same column repeated under a counter suffix. Fully general --
    # this is what SQL joins, data relations and pandas merges produce, in any domain.
    df["FI-1004.PV (2)"] = df["FI-1004.PV"]

    # Clamp temperature at both ends so the values pin at an exact min and max. These are
    # clamps, not measurements, and must be excluded when calibrating a band.
    df["TI-1005.PV"] = df["TI-1005.PV"].clip(lower=20.0, upper=36.0)

    # A near-empty trailing row: the classic snapshot/append export artifact.
    tail = {c: "" for c in df.columns}
    tail["Timestamp"] = (idx[-1] + pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    df = pd.concat([df, pd.DataFrame([tail])], ignore_index=True)

    return df


def main() -> None:
    df = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8")
    print(f"wrote {OUT}  ({len(df)} rows x {len(df.columns)} columns)")


if __name__ == "__main__":
    main()
