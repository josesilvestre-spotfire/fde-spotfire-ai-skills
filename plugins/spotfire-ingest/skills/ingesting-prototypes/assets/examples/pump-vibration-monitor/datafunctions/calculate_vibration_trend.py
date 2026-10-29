"""Calculate Vibration Trend.

Smooths the vibration readings of the selected pump, projects them forward with a
straight-line fit and a two-sigma band, and returns the KPI values and the latest
reading of every pump in the selected window.

Inputs (Spotfire data function parameters):
    PUMP_READINGS   table: Timestamp (UTC), Pump ID, Flow Rate (bbl/d),
                    Discharge Pressure (psi), Vibration (mm/s)
    PumpId          String   pump shown on the Trend page
    WindowStart     DateTime first hour of the window
    WindowEnd       DateTime end of the window (exclusive)
    AlarmLevel      Real     vibration alarm level (mm/s)
    SmoothingSpan   Integer  span of the exponential moving average (h)
    ForecastHours   Integer  forecast horizon (h)
    ShowRaw         Boolean  include the raw readings in the trend table

Outputs:
    VIBRATION_TREND  table: history and forecast of the selected pump
    FLEET_LATEST     table: latest reading per pump in the window
    LatestVibration, HoursOverAlarm, MeanFlow, RowsInView  values for the KPI band
"""

import numpy as np
import pandas as pd

FIT_WINDOW_HOURS = 168
TIME = "Timestamp (UTC)"
VIB = "Vibration (mm/s)"


def smooth(series, span):
    """L01: exponentially weighted moving average, alpha = 2 / (span + 1)."""
    return series.ewm(span=span, adjust=False).mean()


def forecast(series, hours, fit_window=FIT_WINDOW_HOURS):
    """L02 and L03: straight-line projection of the last fit_window hours with a 2 sigma band."""
    tail = series.iloc[-fit_window:]
    if len(tail) < 3:
        empty = np.full(hours, np.nan)
        return empty, empty, empty
    x = np.arange(len(tail))
    slope, intercept = np.polyfit(x, tail.to_numpy(dtype=float), 1)
    resid = tail.to_numpy(dtype=float) - (slope * x + intercept)
    sigma = resid.std(ddof=1)
    future = np.arange(len(tail), len(tail) + hours)
    centre = slope * future + intercept
    return centre, centre - 2 * sigma, centre + 2 * sigma


readings = PUMP_READINGS.copy()
readings[TIME] = pd.to_datetime(readings[TIME])
window = readings[(readings[TIME] >= pd.Timestamp(WindowStart)) &
                  (readings[TIME] < pd.Timestamp(WindowEnd))]
one = window[window["Pump ID"] == PumpId].sort_values(TIME)

if len(one):
    smoothed = smooth(one[VIB], int(SmoothingSpan))
    centre, lower, upper = forecast(smoothed, int(ForecastHours))
    future = pd.date_range(one[TIME].iloc[-1], periods=int(ForecastHours) + 1, freq="h")[1:]
    history = pd.DataFrame({
        TIME: one[TIME].to_numpy(),
        VIB: one[VIB].to_numpy(dtype=float) if ShowRaw else np.nan,
        "Vibration Smoothed (mm/s)": smoothed.to_numpy(dtype=float),
        "Vibration Forecast (mm/s)": np.nan,
        "Forecast Lower (mm/s)": np.nan,
        "Forecast Upper (mm/s)": np.nan})
    ahead = pd.DataFrame({
        TIME: future, VIB: np.nan, "Vibration Smoothed (mm/s)": np.nan,
        "Vibration Forecast (mm/s)": centre, "Forecast Lower (mm/s)": lower,
        "Forecast Upper (mm/s)": upper})
    VIBRATION_TREND = pd.concat([history, ahead], ignore_index=True)
    LatestVibration = float(one[VIB].iloc[-1])
    HoursOverAlarm = int((one[VIB] >= float(AlarmLevel)).sum())
    MeanFlow = float(one["Flow Rate (bbl/d)"].mean())
else:
    VIBRATION_TREND = pd.DataFrame({
        TIME: pd.Series(dtype="datetime64[ns]"), VIB: pd.Series(dtype=float),
        "Vibration Smoothed (mm/s)": pd.Series(dtype=float),
        "Vibration Forecast (mm/s)": pd.Series(dtype=float),
        "Forecast Lower (mm/s)": pd.Series(dtype=float),
        "Forecast Upper (mm/s)": pd.Series(dtype=float)})
    LatestVibration = 0.0
    HoursOverAlarm = 0
    MeanFlow = 0.0

FLEET_LATEST = window.sort_values(TIME).groupby("Pump ID", as_index=False).tail(1)
FLEET_LATEST = FLEET_LATEST.reset_index(drop=True)
RowsInView = int(len(window))
