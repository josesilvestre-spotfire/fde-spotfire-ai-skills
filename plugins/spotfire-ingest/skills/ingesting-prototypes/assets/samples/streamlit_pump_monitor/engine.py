"""Synthetic pump readings and the vibration calculations used by the sample app.

The data is simulated: hourly readings for four pumps with slow bearing wear on one
of them. Nothing here comes from a real site.
"""

import numpy as np
import pandas as pd

PUMPS = ["P-101", "P-102", "P-103", "P-104"]
START = pd.Timestamp("2026-01-01 00:00")


def simulate_readings(days=60, seed=7):
    """Hourly flow, discharge pressure and vibration per pump."""
    rng = np.random.default_rng(seed)
    hours = days * 24
    stamps = pd.date_range(START, periods=hours, freq="h")
    frames = []
    for number, pump in enumerate(PUMPS):
        wear = np.linspace(0.0, 2.5 if pump == "P-103" else 0.3, hours)
        flow = 1800 + 120 * np.sin(np.arange(hours) / 24 * 2 * np.pi) + rng.normal(0, 25, hours)
        pressure = 410 - 0.04 * (flow - 1800) + rng.normal(0, 3, hours)
        vibration = 2.8 + 0.2 * number + wear + rng.normal(0, 0.15, hours)
        frames.append(pd.DataFrame({
            "timestamp": stamps, "pump_id": pump, "flow_bpd": flow,
            "discharge_psi": pressure, "vibration_mms": vibration}))
    return pd.concat(frames, ignore_index=True)


def smooth(series, span):
    """Exponentially weighted moving average of a reading."""
    return series.ewm(span=span, adjust=False).mean()


def forecast(series, hours, fit_window=168):
    """Straight-line projection of the last fit_window hours, with a 2 sigma band."""
    tail = series.iloc[-fit_window:]
    x = np.arange(len(tail))
    slope, intercept = np.polyfit(x, tail.to_numpy(), 1)
    resid = tail.to_numpy() - (slope * x + intercept)
    sigma = resid.std(ddof=1)
    future = np.arange(len(tail), len(tail) + hours)
    centre = slope * future + intercept
    return centre, centre - 2 * sigma, centre + 2 * sigma


def alarm_hours(frame, level):
    """Hours with vibration at or above the alarm level, per pump."""
    over = frame[frame["vibration_mms"] >= level]
    return over.groupby("pump_id").size().reindex(PUMPS, fill_value=0)
