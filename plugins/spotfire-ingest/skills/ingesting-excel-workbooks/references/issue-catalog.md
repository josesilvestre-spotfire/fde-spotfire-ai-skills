# Issue catalog

What `issues.py` reports, why it matters, how the Python model treats it while it reproduces the
workbook, and the change you propose to the owner. Proposed changes go into
`ingest/change-list.md`; none is applied before the owner approves it.

| Type | Severity | What it means | Model while reproducing | Change to propose |
|---|---|---|---|---|
| `typed-over-formula` | high | A number typed in a cell where its neighbours hold a formula (a manual override or a pasted value) | Carry the typed value as an explicit override input (`INPUTS["Calc!G14"]`) | Restore the formula, or keep a named override the user can see |
| `broken-pattern` | high | One cell in a filled-down or filled-right range uses a different formula (often a lost `$` or a reference one row off) | Reproduce the odd cell exactly, with a comment naming the issue | Use the pattern of its neighbours |
| `error-value` | high | Stored `#DIV/0!`, `#N/A`, `#VALUE!`, `#REF!`, `#NUM!` | Return the same error code (`div()` raises `ExcelError`; write the code as the value) | Decide what the result should be (empty, 0, a warning) |
| `broken-reference` | high | `#REF!` inside a formula: a deleted row, column or sheet | Reproduce the error | Ask which range was meant |
| `circular-reference` | high | Cells that depend on themselves; Excel iterates when iterative calculation is on | Iterate in the data function to the Logic Spec tolerance; reconcile with a tolerance at least the workbook's iteration delta | Keep the iteration, or solve the equation directly |
| `approximate-lookup` | high | `VLOOKUP`/`HLOOKUP`/`MATCH`/`LOOKUP` as a range lookup on a table that is not sorted: Excel can return a wrong row without an error | Reproduce Excel's binary search (`vlookup()`); if a case differs from Excel, take Excel's result as an input and explain it | Sort the table, or use an exact match on bands |
| `iferror-masks` | high when an error is hidden now, low otherwise | `IFERROR`, `IFNA` or `ISERROR` turns an error into a fallback value | Return the fallback through `iferror()`, which records the hidden error | Report the error, or handle the case explicitly |
| `mixed-units` | high | `+` or `-` between cells whose labels carry different units | Reproduce the arithmetic exactly | Convert one operand |
| `template-drift` | high | Sheets copied from one template no longer hold the same formulas | Reproduce each copy as it is (a per-asset branch) | One formula for every copy |
| `manual-calculation` | high | Saved in manual calculation mode: stored values may be stale | Ask for a recalculated copy before reconciling | |
| `constant-equals-input` | medium | A formula repeats the value of an input cell instead of reading it | Use the constant, as the workbook does | Read the input |
| `volatile-reference` | medium | `OFFSET` or `INDIRECT`: the cells read are chosen at calculation time; the scan resolves `INDIRECT` from stored values where it can | Reference the resolved cells explicitly | Replace with a direct reference or a lookup |
| `volatile-function` | medium | `NOW`, `TODAY`, `RAND`: the result changes each recalculation | Use the stored value as a fixed input | A date property, a fixed seed |
| `external-link` | medium | A formula reads another workbook; links are not updated during ingest | Use the stored value as an input | Load the source as a data table |
| `vba-function` | medium | A function that is not an Excel function: a VBA user-defined function | Port the VBA code after reading it; until then take the stored values as inputs | |
| `vba-macros` | medium | The file contains VBA or Excel 4 macros | Macros never run; list what they do from the code or the owner | Scripts or data functions behind buttons |
| `hidden-content` | low or medium | Hidden or very hidden sheets, hidden rows or columns with formulas | Carry only what feeds an output | Leave out what nothing reads |
| `hardcoded-constant` | low | Numbers typed into formulas; known unit factors are named in the message | Keep the numbers | Named constants in the data function, or document properties |
| `unused-calculation` | low | A formula block that no formula, chart or name reads | Leave it out of the model unless the owner reads it | Leave it out of the DXP |
| `approximate-lookup-sorted` | info | A range lookup on a sorted table | Reproduce | Confirm the intent; keep the table sorted |
| `npv-timing` | info | `NPV()` discounts the first value by one period | Use `npv()` | Confirm the cash flow timing |
| `data-table` | info | A what-if data table | Run the sweep in a loop | A sweep table output |

## Questions

Each issue carries a question for the owner. The dossier lists them with the issue IDs; high
severity questions are marked as blocking for checkpoint 1 (the owner must confirm the meaning)
but not for the build: the DXP reproduces the workbook first, so the build can go ahead while
the change list waits.

## Limits of the scan

- Units come from labels in parentheses or brackets (`Pressure (psi)`) next to or above a
  block. Unlabelled cells have no unit, so mixed units there are not found.
- `OFFSET`, and `INDIRECT` built from anything other than literals and single cells, leave the
  dependency graph incomplete; unused-calculation findings near them may be wrong.
- Sortedness is checked on stored values; a table sorted today can be pasted unsorted later.
- The scan reads one workbook at a time; external workbooks are not opened.
