# Worked example: App Brief and reserved Logic Spec entries

A synthetic example. The plant, exchangers, numbers and roles are invented to show a complete
brief that passes every check in `SKILL.md`. It would be saved as
`$DXP_WORKSPACE/apps/HeatExchangerFoulingReview/app-brief.md`.

## How the interview went

The request was "an anomaly detection app for our heat exchangers". The first round of questions
(business problem group) turned up the real problem: fouling is found late, and a late find forces
a feed cut. The owner agreed with this summary before the brief was written:

> Process engineers find out that an inlet heat exchanger has fouled only when the outlet
> temperature limit forces a feed rate cut. That happened five times last year at about $40,000
> each. Today one engineer estimates fouling by hand from a monthly historian export.

Anomaly detection stayed as a possible method for one calculation (L02), not as the app's purpose.

## The brief

```markdown
# App Brief: Heat Exchanger Fouling Review

Status: draft
Source: interview with the process engineering lead; historian export sample (synthetic)

## Business problem
Process engineers at a gas processing plant find out that one of the four inlet heat exchangers
has fouled only when the outlet temperature limit forces a feed rate cut. Each cut costs about
6 hours of reduced throughput, around $40,000 at current margins, and there were five last year.
Today one engineer exports historian data once a month and estimates fouling by hand, so cleanings
are booked late or on a fixed calendar.

## Users
| Role | What they do with the app | How often |
|---|---|---|
| Process engineer | Reviews the fouling trend per exchanger, sets the cleaning threshold, recommends cleanings | Weekly |
| Maintenance planner | Reads forecast cleaning dates to plan crews and parts | Monthly, and when a cleaning is recommended |
| Operations supervisor | Checks which exchanger limits throughput today | Daily |

## Decisions the app supports
1. Which exchanger to clean next, and when: the fouling resistance trend per exchanger and the
   forecast date it crosses the cleaning threshold.
2. Whether to clean now or wait for the planned shutdown: the extra fuel cost per day of running
   fouled, against the cleaning cost.
3. Whether a falling outlet temperature is fouling or an instrument fault: the heat balance
   residual between the hot side and cold side duty.

## KPIs
| KPI | Logic Spec ID | Unit | Threshold or target | Shown on |
|---|---|---|---|---|
| Fouling resistance | L03 | m2 K/kW | cleaning threshold input, default 0.35 | Exchanger Review |
| Heat duty loss | L04 | % of clean duty | warn above 10 % | Fleet Overview |
| Extra fuel cost | L05 | USD/d | compare with cleaning cost per exchanger | Fleet Overview |
| Days to cleaning threshold | L06 | d | plan a cleaning below 30 d | Fleet Overview, Cleaning Plan |
| Heat balance residual | L02 | % | investigate above 5 % | Exchanger Review |

## Inputs
| Input | Type (number, choice, date, text, file) | Default | Range or choices | Set by |
|---|---|---|---|---|
| Exchanger | choice | E-101 | E-101, E-102, E-103, E-104 | All users |
| Review window start | date | 90 days before the latest data | within the loaded data | Process engineer |
| Review window end | date | latest data | within the loaded data, after the start | Process engineer |
| Cleaning threshold | number | 0.35 m2 K/kW | 0.10 to 1.00 | Process engineer |
| Fuel price | number | 3.50 USD/MMBtu | 1.00 to 15.00 | Process engineer |
| Cleaning cost per exchanger | number | 25000 USD | 5000 to 100000 | Maintenance planner |
| Plant data file | file | demo dataset | historian export with the required columns (see Data sources) | Process engineer |
| Demo data seed | number | 42 | 1 to 9999 | advanced user (Data Generation page) |
| Demo fouling rate | number | 0.004 m2 K/kW per day | 0.000 to 0.020 | advanced user (Data Generation page) |

## Outputs
| Output | Type (visual, table, export, alert) | Page | Used by |
|---|---|---|---|
| KPI band and exchanger ranking by days to threshold | visual | Fleet Overview | Operations supervisor |
| Fouling resistance trend with threshold line and forecast | visual | Exchanger Review | Process engineer |
| Heat balance residual trend | visual | Exchanger Review | Process engineer |
| Cleaning plan (exchanger, forecast date, extra fuel cost to date) | table, export | Cleaning Plan | Maintenance planner |

## Data sources
| Source | Connection (file, database, API, SBDF) | Grain | Rows (approx.) | Owner |
|---|---|---|---|---|
| Historian export: inlet and outlet temperatures and flows on both sides of each exchanger (required columns: Timestamp (UTC), Exchanger, Hot Inlet Temp (degC), Hot Outlet Temp (degC), Cold Inlet Temp (degC), Cold Outlet Temp (degC), Hot Flow (kg/s), Cold Flow (kg/s)) | file (CSV) | 1 hour per exchanger | 35000 (4 exchangers, 1 year) | Plant data team |
| Exchanger design data (area, clean overall coefficient, design duty) | file (CSV) | one row per exchanger | 4 | Process engineering |
| Cleaning log | file (CSV) | one row per cleaning | 20 | Maintenance |

## Refresh cadence
On demand. The process engineer loads a new historian export each week and presses Refresh. The
fouling calculations rerun when the data, the exchanger or the threshold changes.

## Out of scope
- Alarms during operation (the control system raises them).
- Exchangers other than the four inlet exchangers.
- Crew scheduling for cleanings.
- Pressure-drop indicators of fouling (candidate for the next release).

## Open questions
| # | Question | Blocking | Owner | Answer |
|---|---|---|---|---|
| 1 | Which clean overall heat transfer coefficient applies to E-104 after its retube? | **Blocking** | Process engineering lead | |
| 2 | Is the fuel price the monthly average or the contract price? Assumed: monthly average. | No | Process engineer | |
| 3 | Must the app also run in Web Player? Assumed: Analyst only. | No | Operations supervisor | |
| 4 | Is $40,000 per feed cut the right figure for the cover page? | No | Process engineering lead | |
```

## The reserved Logic Spec entries

`logic-spec.md` did not exist, so the skill created it with one entry per KPI, all
`Status: inferred`. One entry in full:

```markdown
### L03 Fouling resistance
- Equation: `Rf = 1/U_actual - 1/U_clean`, with `U_actual = Q / (A * LMTD)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | Q | Heat duty, hot side | kW | L01 |
  | A | Heat transfer area | m2 | design data column Area (m2) |
  | LMTD | Log mean temperature difference | K | the four temperature columns |
  | U_clean | Clean overall coefficient | kW/(m2 K) | design data column Clean U (kW/m2 K) |
- Output: `Fouling Resistance (m2 K/kW)` (m2 K/kW)
- Grain: per row
- Implemented as: data function `Calculate Fouling Resistance`
- Source in the original work: interview; owner's monthly spreadsheet not yet seen
- Valid range and edge cases: LMTD near zero at low load (drop rows with LMTD below 2 K); negative
  Rf right after a cleaning is measurement noise and is kept
- Reference: owner-confirmed method still to come
- Status: inferred
```

The other reserved entries: L01 Heat duty, L02 Heat balance residual, L04 Heat duty loss, L05 Extra
fuel cost, L06 Days to cleaning threshold.

## How the checks came out

| # | Result |
|---|---|
| 1 | Pass: the first sentence names process engineers and late detection of fouling. |
| 2 | Pass: five cuts a year at about $40,000, monthly manual estimate. |
| 3 to 8 | Pass. The two demo data settings are marked for the Data Generation page. |
| 9 | Pass: required columns of the historian export listed. |
| 10, 11 | Pass. |
| 12 | Pass with one blocking question (E-104 clean coefficient); status stays draft. |
| 13, 14 | Pass. |
