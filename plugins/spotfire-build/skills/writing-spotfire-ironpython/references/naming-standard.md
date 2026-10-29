# Naming standard

Every skill in this library names Spotfire objects the same way. The build skills check these
rules before a build and the verification step reads them back from the saved DXP.

| Object | Rule | Example |
|---|---|---|
| Document properties | PascalCase, no spaces, no type prefix | `SelectedPumpId`, `AnalysisStartDate` |
| Data function parameter bound to a document property | Exactly the property name | `SelectedPumpId` |
| Other data function parameters | camelCase, valid in the engine language | `flowRate`, `minPoints` |
| Data functions | Title Case, verb + object | `Calculate Pump Curves` |
| IronPython scripts | Title Case, verb + object | `Reset All Filters` |
| JavaScript in text areas (script name = file stem) | Title Case, verb + object | `Show Render Time.js` |
| Data tables, including data function output tables | UPPER_SNAKE_CASE | `PUMP_DATA`, `EVENT_LOG` |
| Columns and calculated columns | Title Case, unit in parentheses | `Flow Rate (bbl/d)`, `Head (ft)` |
| Primary time column | `Timestamp (UTC)`; local time as `Timestamp (Local)` | |
| Hierarchies | Title Case | `Asset` |
| Pages | Title Case, no number prefix | `Fleet Overview` |
| Markings | Title Case, says what is marked; with no custom marking the built-in `Marking` stays | `Selected Pump` |
| Filtering schemes | Title Case, matches the page group it serves | `Fleet Filters` |
| Visual titles | The prototype's or workbook's own header, with units where a value is shown | `Daily Flow (bbl/d)` |
| Spec IDs for visuals and controls | camelCase; never shown to users | `flowTrend` |
| HTML element IDs in text areas | camelCase | `kpiBand` |

## Rules

- One name per binding. Document property, data function parameter, control binding, script
  lookup key and mod property use the same name. A mismatch raises no error: the control does
  nothing or the KPI goes stale.
- Spotfire matches document property names and page titles without regard to case. Two names
  that differ only in case are an error.
- One name for the app everywhere: the app name in the spec, the cover page and any article.
- No auto-generated names in a delivered DXP: a ` (<n>)` suffix (`Marking (2)`,
  `Data table (1)`), `Untitled` data functions, default titles (`Page`, `Text Area`), generated
  column names (`Column 1`).
- Units use the symbols the users' field uses (`bbl/d`, `psi`, `degF`, `m3/h`). Dimensionless
  columns carry no unit suffix.
- Built-in document properties keep their Spotfire names and are exempt: `Description`,
  `Keywords`, `MaxMissingTimeParts`, `FiscalYearOffset`, `AllowWebPlayerResume`,
  `PublicBookmarkCreation`, `PrivateBookmarkCreation`.
- A project may switch to all-camelCase for internal prototypes. The build skills accept
  `"namingPolicy": "camelCase"` in the spec; delivered DXPs use the standard above.
