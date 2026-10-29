# App Brief: Line Pressure Profile

Status: draft; checkpoint 3 (change list) waits for the owner
Source: pipe_pressure_drop.xlsx (synthetic test workbook of this skill)

## Business problem
Pipeline engineers check whether a liquid line can deliver a planned flow rate with enough
pressure at the outlet. Today one engineer keeps the calculation in a workbook: segment data is
pasted in, inputs are typed on one sheet and the result is read from a summary sheet. Other
engineers cannot see how a change in flow, fluid or pipe age moves the pressure profile without
asking for a copy of the workbook, and the workbook holds several silent errors (see the change
list).

## Users
| Role | What they do with the app | How often |
|---|---|---|
| Pipeline engineer | Sets flow and fluid properties, reads the outlet pressure and the profile | Weekly |
| Operations planner | Checks whether a planned rate keeps the outlet pressure above the delivery minimum | Before each nomination |

## Decisions the app supports
1. Can the line carry the planned flow rate: outlet pressure at the line end and the profile per
   segment.
2. Which segments cause most of the loss: segment drop and pressure gradient per segment.

## KPIs
| KPI | Logic Spec ID | Unit | Threshold or target | Shown on |
|---|---|---|---|---|
| Total pressure drop | L10 | psi | none | Pressure Profile |
| Outlet pressure at the line end | L08 | psi | above the delivery minimum (owner to state) | Pressure Profile |
| Maximum velocity | L11 | ft/s | 10 ft/s (the workbook's highlight rule) | Pressure Profile |

## Inputs
| Input | Type (number, choice, date, text, file) | Default | Range or choices | Set by |
|---|---|---|---|---|
| Flow rate (bbl/d) | number | 12000.0 | 1000 to 50000 | Pipeline engineer |
| Fluid density (lb/ft3) | number | 53.0 | 40 to 65 | Pipeline engineer |
| Viscosity (cP) | number | 4.5 | 0.5 to 50 | Pipeline engineer |
| Pipe age (years) | number | 25.0 | 0 to 40 | Pipeline engineer |
| Inlet pressure (psi) | number | 950.0 | 100 to 1440 | Pipeline engineer |

## Outputs
| Output | Type (visual, table, export, alert) | Page | Used by |
|---|---|---|---|
| Outlet pressure profile by segment | visual | Pressure Profile | Pipeline engineer |
| Segment results (velocity, losses, gradient) | table | Pressure Profile | Pipeline engineer |
| KPI values | visual | Pressure Profile | Operations planner |

## Data sources
| Source | Connection (file, database, API, SBDF) | Grain | Rows (approx.) | Owner |
|---|---|---|---|---|
| SEGMENTS (workbook sheet Segments) | file (CSV from the workbook) | one row per pipe segment | 20 | Pipeline engineer |
| ROUGHNESS_BY_AGE (workbook sheet Lookups) | file (CSV from the workbook) | one row per age step | 5 | Pipeline engineer |

## Refresh cadence
On demand: the data function runs when an input changes. Segment data changes when the line is
re-surveyed; the owner replaces the CSV file then.

## Out of scope
- The pipe material drop-down (Inputs!B9): no calculation reads it.
- The Blasius friction factor column (Calc!M): no formula, chart or name reads it.

## Open questions
| # | Question | Blocking | Owner | Answer |
|---|---|---|---|---|
| 1 | Approve or reject each change in ingest/change-list.md (C1 to C8). | no | Workbook owner | |
| 2 | What is the minimum delivery pressure at the line end? | no | Operations planner | |
| 3 | Should segment 9 (zero length) stay in the segment data? | no | Workbook owner | |
