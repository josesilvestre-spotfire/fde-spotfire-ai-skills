# Logic Spec: Line Pressure Profile

## Conventions
- Unit system: field units (bbl/d, lb/ft3, cP, in, ft, psi). L06 is in kPa as in the workbook
  until change C3 is approved.
- Time zone and time grain: none (steady state, one row per pipe segment).
- Sign conventions: elevation change is positive uphill; a positive segment drop lowers the
  pressure.
- Rounding and tolerance for reconciliation: default abs=1e-6 rel=1e-9

## Calculations

### L01 Pipe roughness
- Equation: `eps = VLOOKUP(age, ROUGHNESS_BY_AGE, 2)` (range lookup: the last age not above the
  pipe age, read in table order)
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | age | Pipe age | years | document property `PipeAge` |
  | ROUGHNESS_BY_AGE | Roughness by age | years, in | table `ROUGHNESS_BY_AGE` |
- Output: `eps` (in)
- Grain: scalar
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Inputs!B7 `=VLOOKUP(B6,Lookups!$A$3:$B$7,2)`
- Valid range and edge cases: the table is not sorted (issue I01); the lookup reproduces
  Excel's binary search on the stored order. Ages below 0 give #N/A.
- Reference: owner-confirmed
- Status: confirmed

### L02 Velocity
- Equation: `v = Q * 5.615 / 86400 / (pi * (D / 12)^2 / 4)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | Q | Flow rate | bbl/d | document property `FlowRate` |
  | D | Inner diameter | in | column `Inner Diameter (in)` of `SEGMENTS` |
  | 5.615 | Cubic feet per barrel | ft3/bbl | constant |
  | 86400 | Seconds per day | s/d | constant |
- Output: `Velocity (ft/s)` (ft/s)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!D5:D24
- Valid range and edge cases: D > 0
- Reference: continuity equation
- Status: confirmed

### L03 Reynolds number
- Equation: `Re = 1488 * rho * v * (D / 12) / mu`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | rho | Fluid density | lb/ft3 | document property `FluidDensity` |
  | v | Velocity | ft/s | L02 |
  | D | Inner diameter | in | column `Inner Diameter (in)` |
  | mu | Viscosity | cP | document property `Viscosity` |
- Output: `Re` (dimensionless)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!E5:E24
- Valid range and edge cases: mu > 0
- Reference: Reynolds number in field units (1488 converts cP to lb/(ft s))
- Status: confirmed

### L04 Friction factor
- Equation: `f = 0.25 / log10(eps / (3.7 * D) + 5.74 / Re^0.9)^2`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | eps | Roughness | in | L01 |
  | D | Inner diameter | in | column `Inner Diameter (in)`; segment 15 uses segment 1's diameter (change C2) |
  | Re | Reynolds number | dimensionless | L03 |
- Output: `f` (dimensionless)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!F5:F24, exception Calc!F19
- Valid range and edge cases: turbulent flow (Re above about 4000)
- Reference: Swamee-Jain explicit approximation of the Colebrook equation
- Status: confirmed

### L05 Friction loss
- Equation: `dPf = f * (L / (D / 12)) * rho * v^2 / (2 * 32.174) / 144`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | f | Friction factor | dimensionless | L04 |
  | L | Segment length | ft | column `Length (ft)` |
  | v | Velocity | ft/s | L02 |
  | 32.174 | Gravitational acceleration | ft/s2 | constant |
  | 144 | Square inches per square foot | in2/ft2 | constant |
- Output: `Friction Loss (psi)` (psi)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!G5:G24; segment 10 holds the typed value 0.35 (change C4)
- Valid range and edge cases: L = 0 gives 0
- Reference: Darcy-Weisbach equation
- Status: confirmed

### L06 Elevation loss
- Equation: `dPe = rho * dz / 144 * 6.894757`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | dz | Elevation change | ft | column `Elevation Change (ft)` |
  | 6.894757 | kPa per psi | kPa/psi | constant |
- Output: `Elevation Loss (kPa)` (kPa)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!H5:H24
- Valid range and edge cases: negative downhill
- Reference: hydrostatic head
- Status: confirmed

### L07 Segment drop
- Equation: `dP = dPf + dPe` (adds psi and kPa as the workbook does, change C3)
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | dPf | Friction loss | psi | L05 |
  | dPe | Elevation loss | kPa | L06 |
- Output: `Segment Drop (psi)` (psi)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!I5:I24
- Valid range and edge cases: none
- Reference: owner-confirmed
- Status: confirmed

### L08 Outlet pressure
- Equation: `P(n) = P(n-1) - dP(n)`, `P(0) = Pin`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | Pin | Inlet pressure | psi | document property `InletPressure` |
  | dP | Segment drop | psi | L07 |
- Output: `Outlet Pressure (psi)` (psi); the last segment's value also as `OutletPressure`
- Grain: per row, running in segment order
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!J5, Calc!J6:J24, Summary!B5
- Valid range and edge cases: segments in ascending order
- Reference: owner-confirmed
- Status: confirmed

### L09 Pressure gradient
- Equation: `G = dP / L`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | dP | Segment drop | psi | L07 |
  | L | Segment length | ft | column `Length (ft)` |
- Output: `Pressure Gradient (psi/ft)` (psi/ft)
- Grain: per row
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Calc!K5:K24
- Valid range and edge cases: L = 0 (segment 9) gives #DIV/0! in Excel and an empty value in
  the data table (change C5)
- Reference: owner-confirmed
- Status: confirmed

### L10 Total pressure drop
- Equation: `sum(dP)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | dP | Segment drop | psi | L07 |
- Output: `TotalPressureDrop` (psi)
- Grain: scalar
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Summary!B4
- Valid range and edge cases: none
- Reference: owner-confirmed
- Status: confirmed

### L11 Maximum velocity
- Equation: `max(v)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | v | Velocity | ft/s | L02 |
- Output: `MaxVelocity` (ft/s)
- Grain: scalar
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Summary!B6
- Valid range and edge cases: none
- Reference: owner-confirmed
- Status: confirmed

### L12 Average gradient
- Equation: `IFERROR(average(G), 0)`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
  | G | Pressure gradient | psi/ft | L09 |
- Output: `AverageGradient` (psi/ft)
- Grain: scalar
- Implemented as: data function `Calculate Pressure Profile`
- Source in the original work: Summary!B7
- Valid range and edge cases: any #DIV/0! in G makes the average 0, as in the workbook; the
  data function reports the hidden error (change C6)
- Reference: owner-confirmed
- Status: confirmed
