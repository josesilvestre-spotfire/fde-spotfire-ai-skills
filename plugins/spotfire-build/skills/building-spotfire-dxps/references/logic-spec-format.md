# Logic Spec format

The Logic Spec lists every calculation the analysis performs, with its equation and units. The
ingest and design skills write it; the build skills implement it; the reconciliation step checks
the built DXP against it. Save it as `logic-spec.md` in the app folder
(`$DXP_WORKSPACE/apps/<AppSlug>/`).

## Rules

- One entry per calculation, with a stable ID (`L01`, `L02`, ...). IDs are never reused after a
  calculation is removed.
- Every symbol has a unit. Dimensionless values say "dimensionless".
- Every KPI and output in the App Brief maps to at least one ID.
- "Implemented as" names exactly one Spotfire element. Change it only with a note in the change
  list.
- Entries with status **inferred** are confirmed by the owner before the build. When the source is
  a workbook, the DXP first reproduces the workbook's numbers within tolerance; corrections to the
  workbook's logic go in only after the owner approves them.

## Template

```markdown
# Logic Spec: <App name>

## Conventions
- Unit system: <SI, field units, mixed (list)>
- Time zone and time grain: <...>
- Sign conventions: <...>
- Rounding and tolerance for reconciliation: <absolute and relative tolerance per output type>

## Calculations

### L01 <Name>
- Equation: `<symbolic equation>`
- Inputs:
  | Symbol | Meaning | Unit | Source (column, document property, constant, L-ID) |
  |---|---|---|---|
- Output: `<column or property name>` (<unit>)
- Grain: per row | per group (<keys>) | scalar
- Implemented as: calculated column | data function `<name>` | document property | visual expression
- Source in the original work: <Sheet!A1:A100, prototype file and function, or DXP element>
- Valid range and edge cases: <division by zero, missing values, extrapolation limits>
- Reference: <correlation, standard, textbook, or "owner-confirmed">
- Status: confirmed | inferred
```
