# Change list: Line Pressure Profile

Every difference between the workbook and the DXP. The DXP first reproduces the workbook's
numbers (reconciliation PASS on the stored values). A change marked **proposed** goes in only
after the owner approves it; the model is then changed, reconciled again, and the difference is
recorded in the explanations file.

| # | Issue | Workbook today | Proposed change | Effect on outputs | Status |
|---|---|---|---|---|---|
| C1 | I01 | Inputs!B7 looks up roughness with a range VLOOKUP on an unsorted table (age 10 above age 5) | Sort the table by age, or use an exact lookup on age bands | None at age 25; wrong roughness for ages 10 to 19 today | proposed |
| C2 | I02 | Calc!F19 (segment 15) uses the diameter of segment 1 | Use the segment's own diameter | Friction factor of segment 15 changes; outlet pressures from segment 15 on change | proposed |
| C3 | I04 | Calc!I adds friction loss in psi and elevation loss in kPa | Convert the elevation loss to psi (drop the 6.894757 factor) | Every segment drop and outlet pressure changes | proposed |
| C4 | I05 | Calc!G14 (segment 10) holds the typed value 0.35 instead of the formula | Use the formula, or keep a named override input that the user sees | Friction loss of segment 10 changes | proposed |
| C5 | I03 | Segment 9 has length 0, so its gradient is #DIV/0! | Leave the gradient empty for zero-length segments, or remove the segment from the data | Gradient of segment 9 | proposed |
| C6 | I06 | Summary!B7 IFERROR turns the #DIV/0! into an average of 0 | Average the gradients that exist and report the skipped segment | Average gradient becomes a real value | proposed |
| C7 | I07 to I12 | Unit factors and correlation constants are typed into the formulas | Name them in the data function (no change in value) | None | proposed |
| C8 | I13 | Calc!M (Blasius friction factor) is not used | Leave it out of the DXP | None | proposed |

Changes that the DXP makes without changing a number (reported, no approval needed):

- Workbook ranges become data tables: Segments!A2:D21 is `SEGMENTS`, Lookups!A3:B7 is
  `ROUGHNESS_BY_AGE`.
- Input cells become document properties with input controls; summary cells become labels in
  the input panel.
- The conditional format on Calc!D5:D24 (velocity above 10) becomes a color rule on the segment
  table.
- The chart "Outlet pressure profile" becomes a line chart on `SEGMENT_RESULTS`.
