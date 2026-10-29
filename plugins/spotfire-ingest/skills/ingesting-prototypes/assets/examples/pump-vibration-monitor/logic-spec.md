# Logic Spec: Pump Vibration Monitor

## Conventions
- Unit system: field units (bbl/d, psi); vibration in mm/s; time in hours.
- Time zone and time grain: UTC, hourly readings.
- Sign conventions: none.
- Rounding and tolerance for reconciliation: vibration values abs 0.001 mm/s against the
  prototype engine; counts exact.

## Calculations

### L01 Smoothed vibration
- Equation: `s[0] = v[0]; s[t] = a * v[t] + (1 - a) * s[t-1]; a = 2 / (n + 1)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | v | Vibration of the selected pump, in time order within the window | mm/s | column `Vibration (mm/s)` |
  | n | Smoothing span | h | document property `SmoothingSpan` |
- Output: `Vibration Smoothed (mm/s)` (mm/s)
- Grain: per row (selected pump, window)
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `engine.py` `smooth()`, called on the Trend tab of `app.py`
- Valid range and edge cases: empty window returns an empty table
- Reference: exponential moving average (pandas `ewm(span=n, adjust=False)`)
- Status: confirmed

### L02 Forecast centre line
- Equation: `f(h) = b0 + b1 * (N + h - 1), h = 1..H`, with `b0, b1` the least-squares line through
  the last `N = min(168, count)` smoothed values against their index
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | s | Smoothed vibration | mm/s | L01 |
  | H | Forecast horizon | h | document property `ForecastHours` |
  | 168 | Fit window | h | constant |
- Output: `Vibration Forecast (mm/s)` (mm/s)
- Grain: per row (forecast hours of the selected pump)
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `engine.py` `forecast()`
- Valid range and edge cases: fewer than 3 points in the window gives no forecast
- Reference: ordinary least squares
- Status: confirmed

### L03 Forecast band
- Equation: `lower = f - 2 * sigma; upper = f + 2 * sigma`; `sigma` is the sample standard
  deviation (ddof 1) of the fit residuals
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | f | Forecast centre line | mm/s | L02 |
  | sigma | Residual standard deviation over the fit window | mm/s | L02 fit |
- Output: `Forecast Lower (mm/s)`, `Forecast Upper (mm/s)` (mm/s)
- Grain: per row (forecast hours of the selected pump)
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `engine.py` `forecast()`; drawn with `fill="tonexty"` in `app.py`
- Valid range and edge cases: as L02
- Reference: owner-confirmed
- Status: confirmed

### L04 Hours over alarm (selected pump)
- Equation: `count(v >= A)` over the hourly readings of the selected pump in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | v | Vibration | mm/s | column `Vibration (mm/s)` |
  | A | Alarm level | mm/s | document property `AlarmLevel` |
- Output: `HoursOverAlarm` (h)
- Grain: scalar
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `engine.py` `alarm_hours()`, KPI "Hours over alarm" in `app.py`
- Valid range and edge cases: one reading per hour is assumed; gaps count as zero hours
- Reference: owner-confirmed
- Status: confirmed

### L05 Latest vibration
- Equation: `v` at the last timestamp of the selected pump in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | v | Vibration | mm/s | column `Vibration (mm/s)` |
- Output: `LatestVibration` (mm/s)
- Grain: scalar
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: KPI "Latest vibration (mm/s)" in `app.py`
- Valid range and edge cases: empty window gives 0.0
- Reference: owner-confirmed
- Status: confirmed

### L06 Mean flow
- Equation: `mean(Q)` over the selected pump's readings in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | Q | Flow rate | bbl/d | column `Flow Rate (bbl/d)` |
- Output: `MeanFlow` (bbl/d)
- Grain: scalar
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: KPI "Mean flow (bbl/d)" in `app.py`
- Valid range and edge cases: empty window gives 0.0
- Reference: owner-confirmed
- Status: confirmed

### L07 Hours over alarm per pump
- Equation: `Sum(If([Vibration (mm/s)] >= A, 1, 0))` per pump, readings in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | A | Alarm level | mm/s | document property `AlarmLevel` |
  | window | WindowStart to WindowEnd | DateTime | document properties `WindowStart`, `WindowEnd` |
- Output: `Hours over alarm` (h)
- Grain: per group (Pump ID)
- Implemented as: visual expression
- Source in the original work: `engine.py` `alarm_hours()`, bar chart on the Fleet tab
- Valid range and edge cases: as L04
- Reference: owner-confirmed
- Status: confirmed

### L08 Readings in view
- Equation: `count(rows)` of all pumps in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | window | WindowStart to WindowEnd | DateTime | document properties `WindowStart`, `WindowEnd` |
- Output: `RowsInView` (dimensionless)
- Grain: scalar
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `st.markdown` on the Fleet tab
- Valid range and edge cases: none
- Reference: owner-confirmed
- Status: confirmed

### L09 Latest reading per pump
- Equation: the row with the largest timestamp per pump in the window
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | readings | All columns of the readings | mixed | table `PUMP_READINGS` |
- Output: table `FLEET_LATEST`
- Grain: per group (Pump ID)
- Implemented as: data function `Calculate Vibration Trend`
- Source in the original work: `st.dataframe(latest)` on the Fleet tab
- Valid range and edge cases: a pump with no readings in the window has no row
- Reference: owner-confirmed
- Status: confirmed
