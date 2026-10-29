# Mapping table: Pump Vibration Monitor

Prototype: `streamlit_pump_monitor/app.py` and `engine.py`. Element numbers E01 to E32 come from
`scan_prototype.py`; E33 to E35 were added from reading the engine code. Fidelity: EXACT, CLOSE,
SUBSTITUTE, MANUAL. Every SUBSTITUTE and MANUAL row has the owner's decision.

| # | Prototype element | Where | Spotfire element | Fidelity | Substitute and reason | Owner decision |
|---|---|---|---|---|---|---|
| E01 | `import engine` (local module) | app.py:9 | Inlined into data function `Calculate Vibration Trend` | EXACT | A data function cannot import sibling files | |
| E02 | `st.set_page_config(layout="wide")` | app.py:11 | `app.theme.base: LightSfx`, page layouts fill the canvas | CLOSE | | |
| E03 | `st.title("Pump Vibration Monitor")` | app.py:12 | `app.name`; the page tabs carry the page names | SUBSTITUTE | No header band: the KPI band takes the top of the Trend page | Approved |
| E04 | `@st.cache_data load(days, seed)` | app.py:16 | Precomputed table `PUMP_READINGS` (embedded CSV) | EXACT | No input drives it: `load(60, 7)` is fixed | |
| E05 | `st.sidebar` | app.py:20 | Text areas `trendPanel` and `fleetPanel`, first item of each page row (weight 18) | SUBSTITUTE | Spotfire has no sidebar; one panel per page holds that page's controls | Approved |
| E06 | `st.selectbox` `pump` "Pump" (index 2 of PUMPS) | app.py:21 | `dropdown` on property `PumpId` (String), values from column `Pump ID` | EXACT | Renamed `pump` to `PumpId` for a clearer property name | Approved |
| E07 | `st.date_input` `window` "Date range" (tuple default) | app.py:22 | `input` controls on DateTime properties `WindowStart` and `WindowEnd` | SUBSTITUTE | G10: no date range control; two typed dates feed the data function and the Fleet limit expression | Approved |
| E08 | `st.number_input` `alarm` "Alarm level (mm/s)" (7.1, 1.0 to 15.0, step 0.1) | app.py:23 | `input` on property `AlarmLevel` (Real); also on the Fleet panel | EXACT | Renamed `alarm` to `AlarmLevel`; Spotfire does not enforce the 1.0 to 15.0 range | Approved |
| E09 | `st.slider` `span` "Smoothing span (h)" (6 to 168, step 6, default 48) | app.py:24 | `slider` on property `SmoothingSpan` (Integer) | EXACT | Renamed `span` to `SmoothingSpan` | Approved |
| E10 | `st.slider` `horizon` "Forecast horizon (h)" (24 to 336, step 24, default 72) | app.py:25 | `slider` on property `ForecastHours` (Integer) | EXACT | Renamed `horizon` to `ForecastHours` | Approved |
| E11 | `st.checkbox` `show_raw` "Show raw readings" | app.py:26 | `checkbox` on property `ShowRaw` (Boolean); the data function leaves the raw column empty when it is No | SUBSTITUTE | A Yes/No drop-down; the series disappears because its values are empty | Approved |
| E12 | `st.file_uploader` "Replace readings (CSV)" | app.py:27 | None: data is embedded at build time; users replace the `PUMP_READINGS` table through Spotfire's data menus | MANUAL | G11: no file upload control | Approved, listed under Out of scope |
| E13 | `pd.read_csv(upload)` | app.py:29 | Not built (only used by E12) | MANUAL | Follows E12 | Approved |
| E14 | `st.columns(3)` for the metrics | app.py:34 | Three cards in the HTML KPI band `kpiBand` | EXACT | | |
| E15 | `st.metric` "Latest vibration (mm/s)" | app.py:35 | KPI band label bound to `LatestVibration` (L05) | CLOSE | | |
| E16 | `st.metric` "Hours over alarm" | app.py:36 | KPI band label bound to `HoursOverAlarm` (L04) | CLOSE | | |
| E17 | `st.metric` "Mean flow (bbl/d)" | app.py:37 | KPI band label bound to `MeanFlow` (L06) | CLOSE | | |
| E18 | `st.tabs(["Trend", "Fleet"])` | app.py:39 | Pages `Trend` and `Fleet` | SUBSTITUTE | G11: no in-page tabs; the two tabs are independent views, so they become pages | Approved |
| E19 | `go.Scatter` "Raw" | app.py:47 | Series `Raw` of line chart `vibrationTrend` | EXACT | | |
| E20 | `go.Scatter` "Smoothed" | app.py:49 | Series `Smoothed` of `vibrationTrend` (L01) | EXACT | | |
| E21 | `go.Scatter` upper band edge (no legend) | app.py:50 | Series `Forecast Upper` of `vibrationTrend` (L03) | EXACT | Edge of the G2 ribbon | |
| E22 | `go.Scatter` lower band edge "Forecast band" | app.py:52 | Series `Forecast Lower` of `vibrationTrend` (L03) | EXACT | Edge of the G2 ribbon | |
| E23 | `fill="tonexty"` | app.py:52 | No fill: the two edges are series of one light violet (`#D8CCFD`) on `vibrationTrend` | SUBSTITUTE | G2 option 2. A filled band (G2 option 1, a band reference layer) needs the build skill's slim tier | Pending |
| E24 | `go.Scatter` "Forecast" | app.py:55 | Series `Forecast` of `vibrationTrend` (L02) | EXACT | | |
| E25 | `line=dict(dash="dot")` on the forecast | app.py:55 | Solid violet series named `Forecast` | CLOSE | G3 option 1: distinct solid color and a clear legend name | Approved |
| E26 | `add_hline(y=alarm, line_dash="dash")` "Alarm" | app.py:57 | Horizontal reference line `[$AlarmLevel]`, dashed, label `Alarm` | EXACT | | |
| E27 | `st.plotly_chart(fig)` | app.py:60 | Line chart `vibrationTrend` on page `Trend`, title `${PumpId} vibration and ${ForecastHours} h forecast (mm/s)` | EXACT | | |
| E28 | `st.bar_chart` hours over alarm per pump | app.py:64 | Bar chart `alarmHours` on `PUMP_READINGS` with a visual expression (L07) and a window limit expression | EXACT | | |
| E29 | `st.dataframe(latest)` | app.py:66 | Table `latestReadings` on `FLEET_LATEST` (L09) | EXACT | | |
| E30 | `on_select="rerun"`, single row | app.py:66 | Marking `Selected Pump` on `latestReadings` | EXACT | Prototype quirk: the selection is never used. Kept as a marking with no limited visual (open question 1) | Approved |
| E31 | `st.markdown(f"Rows in view: ...")` | app.py:67 | `label` control bound to `RowsInView` (L08) in `fleetPanel` | CLOSE | G6 option 1: static text plus a label | Approved |
| E32 | `np.random.default_rng(seed)` in `simulate_readings` | engine.py:16 | Used once to write `data/PUMP_READINGS.csv` (seed 7, start 2026-01-01) | EXACT | | |
| E33 | `smooth()` | engine.py:31 | L01 in data function `Calculate Vibration Trend` | EXACT | | |
| E34 | `forecast()` | engine.py:36 | L02 and L03 in data function `Calculate Vibration Trend` | EXACT | | |
| E35 | `alarm_hours()` | engine.py:48 | L04 (selected pump, data function) and L07 (per pump, visual expression) | EXACT | | |
