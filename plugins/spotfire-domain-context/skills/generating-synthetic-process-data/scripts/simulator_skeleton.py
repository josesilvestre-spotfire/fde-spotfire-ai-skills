"""Synthetic historian skeleton: a centrifugal pump station in three layers.

    python simulator_skeleton.py --check          # generate, validate, print the report
    python simulator_skeleton.py --out folder     # also write historian.csv and events.csv

A starting point for a first-principles simulator, small enough to read in one sitting:

  1. Environment   ambient temperature: annual and diurnal cycles plus Ornstein-Uhlenbeck
                   (OU) weather fronts, integrated once over the whole horizon.
  2. Operations    an aperiodic rate state machine: setpoints held for a random number of
                   days, first-order ramps that fall fast and recover slowly, and trips
                   driven by the event schedule.
  3. Physics       every tag derived from rate, ambient and equipment health: a quadratic
                   pump curve, line friction scaling with flow^1.8, crude temperature
                   lagging ambient, motor power from hydraulic power and efficiency.

Noise on every tag is coloured (OU), never white. Tags correlate only through the shared
rate and ambient drivers. Events are a contract: every subtype the scheduler can emit is
registered in EVENT_CATALOG, and VERIFY declares the direction and magnitude band each one
must leave on each tag, which `validate()` asserts after generation.

Every constant below is illustrative and marked as such. Replace them with values sourced
for your domain before you present the data as realistic.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ configuration
# Illustrative values for a demo dataset, not sourced plant data.
SEED = 7
SAMPLE_MINUTES = 60
TRAIN_DAYS = 150
HOLDOUT_DAYS = 45
DESIGN_FLOW_BPD = 120_000.0       # illustrative station design rate
SHUTOFF_HEAD_FT = 2600.0          # illustrative pump curve
CURVE_K = 0.35                    # head falls by this fraction at design flow
SPECIFIC_GRAVITY = 0.85           # illustrative crude
SUCTION_PSIG = 60.0
LINE_DP_AT_DESIGN_PSI = 650.0     # illustrative segment friction at design flow
FRICTION_EXPONENT = 1.8           # turbulent friction, between 1.75 (smooth) and 2.0 (rough)
PUMP_EFFICIENCY = 0.80
EVENTS_PER_WINDOW = {"train": 5, "test": 2}


# ------------------------------------------------------------------ OU noise

def ou(n: int, dt: float, theta: float, sigma: float, rng: np.random.Generator,
       x0: float = 0.0) -> np.ndarray:
    """Ornstein-Uhlenbeck path by exact discretisation.

    dx = -theta * x dt + sigma dW. `theta` is the mean-reversion rate (1/time), so the
    correlation time is 1/theta; `sigma` sets the stationary sd, sigma / sqrt(2 theta).
    """
    a = np.exp(-theta * dt)
    s = sigma * np.sqrt((1.0 - a * a) / (2.0 * theta))
    x = np.empty(n)
    x[0] = x0
    eps = rng.standard_normal(n)
    for i in range(1, n):
        x[i] = a * x[i - 1] + s * eps[i]
    return x


# ------------------------------------------------------------------ layer 1: environment

def environment(t_days: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Ambient temperature, degF. The annual and diurnal cycles are real; the fronts are
    OU with a correlation time of a few days."""
    dt = t_days[1] - t_days[0]
    annual = 55.0 + 25.0 * np.sin(2 * np.pi * (t_days - 110.0) / 365.25)
    diurnal = 8.0 * np.sin(2 * np.pi * (t_days % 1.0 - 0.375))
    fronts = ou(len(t_days), dt, theta=1 / 3.0, sigma=6.0, rng=rng)
    return annual + diurnal + fronts


# ------------------------------------------------------------------ layer 2: operations

def rate_setpoints(t_days: np.ndarray, rng: np.random.Generator,
                   protected: np.ndarray) -> np.ndarray:
    """Aperiodic setpoints: each held 6 to 30 days at 60 to 100 percent of design.
    Hold lengths are random, so there is no synthetic rhythm in the rate. A change that
    falls inside a protected window (an event and its verification baseline) waits until
    the window ends, so an operating move never masquerades as an event signature."""
    sp = np.empty(len(t_days))
    next_change = 0.0
    level = rng.uniform(0.8, 1.0)
    for i, t in enumerate(t_days):
        if t >= next_change and not protected[i]:
            next_change = t + rng.uniform(6.0, 30.0)
            level = rng.uniform(0.6, 1.0)
        sp[i] = level
    return sp


def operate(setpoint: np.ndarray, trips: np.ndarray, dt_days: float) -> np.ndarray:
    """First-order response toward the setpoint, falling fast and recovering slowly.
    A trip drives the target to zero for its duration."""
    tau_down, tau_up = 0.05, 0.6        # days; illustrative asymmetric time constants
    rate = np.empty(len(setpoint))
    r = setpoint[0]
    for i, target in enumerate(np.where(trips, 0.0, setpoint)):
        tau = tau_down if target < r else tau_up
        r += (target - r) * (1.0 - np.exp(-dt_days / tau))
        rate[i] = r
    return rate


# ------------------------------------------------------------------ events: the contract

# Every subtype the scheduler can emit. Missing one is a KeyError at generation time,
# which is the point: an unregistered event has no verification contract.
EVENT_CATALOG = {
    "Partial Restriction - High Line Pressure Drop": {
        "family": "Process", "days": (1.0, 3.0)},
    "Impeller Damage - Low Discharge Pressure": {
        "family": "Mechanical", "days": (1.0, 3.0)},
    "Transmitter Freeze - Flat Discharge Pressure": {
        "family": "Instrumentation", "days": (1.0, 2.0)},
    "Power Loss Trip - Station Shutdown": {
        "family": "Electrical", "days": (0.2, 0.5)},
}

# Expected effect of each subtype, as (direction, min, max) percent change of the event
# window mean against the 3 days before it. "flat" means the tag's sd collapses.
VERIFY = {
    "Partial Restriction - High Line Pressure Drop": {
        "line_dp_psi": ("up", 3.0, 25.0), "flow_bpd": ("down", 0.5, 15.0)},
    "Impeller Damage - Low Discharge Pressure": {
        "discharge_psig": ("down", 3.0, 25.0), "motor_power_hp": ("down", 1.0, 25.0)},
    "Transmitter Freeze - Flat Discharge Pressure": {
        "discharge_psig": ("flat", 0.0, 0.0)},
    "Power Loss Trip - Station Shutdown": {
        "flow_bpd": ("down", 50.0, 100.0), "motor_power_hp": ("down", 50.0, 100.0)},
}


def schedule_events(t_days: np.ndarray, split: np.ndarray,
                    rng: np.random.Generator) -> pd.DataFrame:
    """Place non-overlapping events inside each split, with a clear gap before each one
    so the verification baseline is clean."""
    rows = []
    subtypes = list(EVENT_CATALOG)
    for part, count in EVENTS_PER_WINDOW.items():
        t_part = t_days[split == part]
        lo, hi = t_part.min() + 4.0, t_part.max() - 4.0
        placed: list[tuple[float, float]] = []
        tries = 0
        while len(placed) < count and tries < 1000:
            tries += 1
            subtype = subtypes[len(rows) % len(subtypes)]
            d_lo, d_hi = EVENT_CATALOG[subtype]["days"]
            start = rng.uniform(lo, hi)
            end = start + rng.uniform(d_lo, d_hi)
            if any(start < e + 6.0 and end > s - 6.0 for s, e in placed):
                continue
            placed.append((start, end))
            rows.append({"Event ID": f"EV{len(rows) + 1:04d}", "Subtype": subtype,
                         "Family": EVENT_CATALOG[subtype]["family"], "Split": part,
                         "Start Day": start, "End Day": end})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ layer 3: physics

def generate(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dt = SAMPLE_MINUTES / 1440.0
    n = int((TRAIN_DAYS + HOLDOUT_DAYS) / dt)
    t_days = np.arange(n) * dt
    split = np.where(t_days < TRAIN_DAYS, "train", "test")

    ambient = environment(t_days, rng)
    events = schedule_events(t_days, split, rng)

    in_event = {sub: np.zeros(n, dtype=bool) for sub in EVENT_CATALOG}
    event_id = np.full(n, "", dtype=object)
    protected = np.zeros(n, dtype=bool)
    for ev in events.itertuples(index=False):
        mask = (t_days >= ev[4]) & (t_days < ev[5])
        in_event[ev[1]] |= mask       # KeyError here means an unregistered subtype
        event_id[mask] = ev[0]
        protected |= (t_days >= ev[4] - 4.5) & (t_days < ev[5] + 0.5)

    trips = in_event["Power Loss Trip - Station Shutdown"]
    rate = operate(rate_setpoints(t_days, rng, protected), trips, dt)

    # Equipment health: slow impeller wear plus the damage event.
    wear = 1.0 - 0.02 * t_days / t_days.max()
    damage = np.where(in_event["Impeller Damage - Low Discharge Pressure"], 0.88, 1.0)
    restriction = np.where(in_event["Partial Restriction - High Line Pressure Drop"],
                           1.25, 1.0)

    # A restriction raises system resistance, so the operating point moves left on the
    # pump curve: somewhat less flow at the same speed (illustrative partial response).
    flow = DESIGN_FLOW_BPD * rate * restriction ** (-0.5 / FRICTION_EXPONENT)
    q = flow / DESIGN_FLOW_BPD
    head_ft = SHUTOFF_HEAD_FT * (1.0 - CURVE_K * q ** 2) * wear * damage
    head_ft = np.where(rate < 0.02, 0.0, head_ft)
    crude_temp = 40.0 + 0.6 * (pd.Series(ambient).ewm(halflife=1.5 / dt).mean().to_numpy()
                               - 40.0)
    visc_factor = np.exp(-0.01 * (crude_temp - 60.0))   # colder crude, more friction
    line_dp = LINE_DP_AT_DESIGN_PSI * q ** FRICTION_EXPONENT * visc_factor * restriction

    discharge = SUCTION_PSIG + head_ft * SPECIFIC_GRAVITY / 2.31
    hyd_hp = flow * 42.0 / 1440.0 * head_ft * SPECIFIC_GRAVITY / 3960.0
    motor_hp = np.where(rate < 0.02, 0.0, hyd_hp / PUMP_EFFICIENCY)

    def noisy(x, rel_sd, corr_hours):
        theta = 24.0 / corr_hours
        scale = np.maximum(np.abs(np.nanmean(x)), 1e-9) * rel_sd
        return x + ou(n, dt, theta, scale * np.sqrt(2 * theta), rng)

    hist = pd.DataFrame({
        "Timestamp": pd.date_range("2026-01-01", periods=n, freq=f"{SAMPLE_MINUTES}min"),
        "ambient_degf": ambient,
        "crude_temp_degf": noisy(crude_temp, 0.005, 6),
        "flow_bpd": np.maximum(noisy(flow, 0.004, 2), 0.0),
        "suction_psig": noisy(np.full(n, SUCTION_PSIG), 0.01, 2),
        "discharge_psig": noisy(discharge, 0.003, 2),
        "line_dp_psi": np.maximum(noisy(line_dp, 0.004, 2), 0.0),
        "motor_power_hp": np.maximum(noisy(motor_hp, 0.004, 2), 0.0),
    })

    # Instrumentation freeze: the transmitter holds its last value for the event window.
    frozen = in_event["Transmitter Freeze - Flat Discharge Pressure"]
    if frozen.any():
        held = hist["discharge_psig"].where(~frozen).ffill()
        hist.loc[frozen, "discharge_psig"] = held[frozen]

    hist["__Event_ID"] = event_id
    hist["Split"] = split
    return hist, events


# ------------------------------------------------------------------ validation

def validate(hist: pd.DataFrame, events: pd.DataFrame) -> list[dict]:
    """Assert every event's signature against VERIFY, and that process tags carry no
    synthetic 24-hour rhythm beyond what the ambient driver puts there."""
    t = (hist["Timestamp"] - hist["Timestamp"].iloc[0]).dt.total_seconds() / 86400.0
    report = []
    for ev in events.itertuples(index=False):
        win = (t >= ev[4]) & (t < ev[5])
        base = (t >= ev[4] - 3.0) & (t < ev[4])
        for tag, (direction, lo, hi) in VERIFY[ev[1]].items():
            w, b = hist.loc[win, tag], hist.loc[base, tag]
            if direction == "flat":
                ok = float(w.std()) < 1e-9
                change = float(w.std())
            else:
                change = 100.0 * (w.mean() - b.mean()) / abs(b.mean())
                signed = change if direction == "up" else -change
                ok = lo <= signed <= hi
            report.append({"check": "verify", "event": ev[0], "subtype": ev[1],
                           "tag": tag, "expected": f"{direction} {lo}-{hi}%",
                           "observed": round(float(change), 2), "ok": bool(ok)})
    # Spectral check: no peak at one cycle per day on the process tags. After removing the
    # setpoint moves (a 3-day rolling median), the power density in the 24-hour band is
    # compared with the neighbouring bands. Coloured noise gives a ratio near 1 whatever
    # its correlation time; a synthetic daily rhythm gives a peak. The limit of 3 is an
    # illustrative choice, not a sourced value.
    samples_per_day = int(round(1440 / SAMPLE_MINUTES))
    freq = np.fft.rfftfreq(len(hist), d=SAMPLE_MINUTES / 1440.0)
    band = (freq > 0.95) & (freq < 1.05)
    side = ((freq > 0.7) & (freq < 0.9)) | ((freq > 1.1) & (freq < 1.3))
    for tag in ("flow_bpd", "discharge_psig", "line_dp_psi"):
        s = hist[tag]
        x = s - s.rolling(3 * samples_per_day, center=True, min_periods=1).median()
        x = (x - x.mean()).to_numpy()
        power = np.abs(np.fft.rfft(x)) ** 2
        ratio = float(power[band].mean() / power[side].mean())
        report.append({"check": "spectral_24h", "event": "", "subtype": "", "tag": tag,
                       "expected": "24 h band / neighbours < 3", "observed": round(ratio, 2),
                       "ok": ratio < 3.0})
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="validate and print the report")
    ap.add_argument("--out", help="folder for historian.csv and events.csv")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)

    hist, events = generate(a.seed)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        hist.to_csv(os.path.join(a.out, "historian.csv"), index=False)
        events.to_csv(os.path.join(a.out, "events.csv"), index=False)
    report = pd.DataFrame(validate(hist, events))
    failed = report[~report["ok"]]
    if a.check or not failed.empty:
        print(report.to_string(index=False))
    print(f"{len(hist)} rows, {len(events)} events, {len(failed)} failed checks")
    return 1 if len(failed) else 0


if __name__ == "__main__":
    sys.exit(main())
