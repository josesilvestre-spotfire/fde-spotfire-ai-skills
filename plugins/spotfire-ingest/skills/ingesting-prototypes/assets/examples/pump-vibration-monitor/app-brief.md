# App Brief: Pump Vibration Monitor

Status: confirmed by reliability engineer on 2026-10-15
Source: Streamlit prototype `streamlit_pump_monitor/app.py` and `engine.py` (synthetic sample)

## Business problem
Bearing wear on transfer pumps shows up as a slow rise in vibration weeks before a trip. Today
reliability engineers export historian readings to spreadsheets once a week and look for pumps
near the alarm level by eye, so a fast-rising pump can be missed between reviews. A missed
bearing failure costs an unplanned outage and a repair that a planned intervention avoids.

## Users
| Role | What they do with the app | How often |
|---|---|---|
| Reliability engineer | Reviews each pump's vibration trend and forecast, plans bearing work | Weekly |
| Operations supervisor | Checks which pumps spent hours over the alarm level | Daily |

## Decisions the app supports
1. Plan bearing inspection for a pump: the smoothed trend, the forecast and when it crosses the
   alarm level.
2. Prioritize pumps across the fleet: hours over the alarm level per pump in the window.

## KPIs
| KPI | Logic Spec ID | Unit | Threshold or target | Shown on |
|---|---|---|---|---|
| Latest vibration | L05 | mm/s | Alarm level (default 7.1) | Trend |
| Hours over alarm | L04 | h | 0 | Trend |
| Mean flow | L06 | bbl/d | none | Trend |

## Inputs
| Input | Type (number, choice, date, text, file) | Default | Range or choices | Set by |
|---|---|---|---|---|
| Pump | choice | P-103 | Pump IDs in the data | User |
| Window start | date | 2026-01-01 00:00 | Data range | User |
| Window end | date | 2026-03-01 00:00 | Data range | User |
| Alarm level (mm/s) | number | 7.1 | 1.0 to 15.0 | User |
| Smoothing span (h) | number | 48 | 6 to 168, step 6 | User |
| Forecast horizon (h) | number | 72 | 24 to 336, step 24 | User |
| Show raw readings | choice | Yes | Yes, No | User |

## Outputs
| Output | Type (visual, table, export, alert) | Page | Used by |
|---|---|---|---|
| Vibration trend and forecast | visual | Trend | Reliability engineer |
| KPI band | visual | Trend | Both roles |
| Hours over alarm per pump | visual | Fleet | Operations supervisor |
| Latest reading per pump | table | Fleet | Operations supervisor |

## Data sources
| Source | Connection (file, database, API, SBDF) | Grain | Rows (approx.) | Owner |
|---|---|---|---|---|
| Pump readings | file (`data/PUMP_READINGS.csv`, written from the prototype's `simulate_readings(days=60, seed=7)` with Title Case column names) | One row per pump per hour | 5,760 | Reliability engineer |

## Refresh cadence
On open. The readings are embedded; a new extract is loaded by replacing the data table.

## Out of scope
- Uploading a CSV from inside the analysis (the prototype's file uploader).
- Writing work orders.

## Open questions
| # | Question | Blocking | Owner | Answer |
|---|---|---|---|---|
| 1 | In the prototype, selecting a row in the fleet table changes nothing. Should the marking drive another visual? | No | Reliability engineer | Keep the marking; no visual is limited by it in this version. |
| 2 | The fit window of the forecast is fixed at 168 h. Should users change it? | No | Reliability engineer | Keep it fixed. |
