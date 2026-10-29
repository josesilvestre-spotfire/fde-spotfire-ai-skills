# Mapping table: pipe_pressure_drop.xlsx to Line Pressure Profile

| Workbook element | Where | Spotfire element | Fidelity | Note |
|---|---|---|---|---|
| Input cells | Inputs!B3:B6, Inputs!B8 | Document properties `FlowRate`, `FluidDensity`, `Viscosity`, `PipeAge`, `InletPressure` with input controls in `inputsPanel` | EXACT | |
| Roughness lookup | Inputs!B7, Lookups!A3:B7 | Table `ROUGHNESS_BY_AGE`, lookup inside data function `Calculate Pressure Profile` | EXACT | Range lookup reproduced on the stored row order (C1) |
| Drop-down list | Inputs!B9 (pipe material) | Not carried | MANUAL | No calculation reads it; out of scope in the App Brief |
| Raw segment data | Segments!A2:D21 (Excel table SegmentData) | Table `SEGMENTS` from `data/SEGMENTS.csv` | EXACT | |
| Filled-down calculation columns | Calc!A5:K24 | Data function `Calculate Pressure Profile`, output table `SEGMENT_RESULTS` | EXACT | One data function so the DXP runs the reconciled code; the running outlet pressure (Calc!J) needs row order |
| Typed value over a formula | Calc!G14 | Override kept in the model (`Calc!G14` input) | EXACT | C4 |
| Unused column | Calc!M5:M24 | Not carried | MANUAL | C8 |
| Summary cells | Summary!B4:B7 | Value outputs `TotalPressureDrop`, `OutletPressure`, `MaxVelocity`, `AverageGradient` shown as labels | EXACT | |
| Conditional format | Calc!D5:D24, value above 10 | Color rule on `Velocity (ft/s)` in `segmentResults` | CLOSE | Cell color in the table instead of the workbook's font color |
| Line chart | Summary, "Outlet pressure profile" | `pressureProfile` line chart | EXACT | |
