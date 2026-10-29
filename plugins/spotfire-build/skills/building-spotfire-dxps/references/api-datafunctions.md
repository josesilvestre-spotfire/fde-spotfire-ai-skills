# API reference: data functions (registration, bindings, execution, refresh)

Owner: `scripts/lib/30_datafunctions.py` (the library of the slim and full tiers). The standard engine's
feature part `datafunctions` (`scripts/engine/features/datafunctions.py`) follows R1 to R7 with fewer options
(Python only, no `settings`, no `limitByFiltering`).
Spotfire Analyst 15.0 (core build 71.0.22206.3863), IronPython 3.4. Public API only. Every member is
checked with `scripts/sfapi.py has` (`scripts/lib/30_datafunctions.members.txt`; setters with `has --set`,
`scripts/lib/30_datafunctions.set.txt`). Newest member used:
`DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor` [api 10.9]; nothing newer than 14.6.

The facts below are Spotfire Analyst 15.0 behaviour. Items not yet proven in a live build are marked
**Not yet tested** with the number `#n` the code comments cite, and listed at the end.

## Functions

| function | build group | does | on failure |
|---|---|---|---|
| `df_build_all(list)` | `dataFunctions` (after properties, file tables, markings, filtering schemes) | step `order` (target `dataFunctions`): producers before consumers, then `df_build` per function | `order` failed = spec order |
| `df_build(dspec)` | same | steps `register <fn>`, `input <fn>/<param>`, `output <fn>/<param>`, `execute <fn>` (only `executeAtBuild`), `refresh <fn>`, `settings <fn>` (only with `settings`) | failed register = `bindings` skipped; a failed binding = `execute` skipped |
| `df_find(name)` | helper (the rebuild check in `register`) | `DataFunction` by name, case-insensitive, or `None` | |

Defaults applied by the module ([spec-format.md](spec-format.md) lists none): `engine` python, `refresh`
automatic, `executeAtBuild` true, `description` "", `dataTypes` = the 11 types of the registration dialog.
Accepted beyond the spec-format.md example: `bind.columns` as a list; `limitByFiltering: true` (active
filtering scheme); limits on `column` binds and on value `expression` binds; `description` on inputs/outputs;
`settings` (relative to the `DataFunction`, for example `{"Visible": true}`).

Report `B.created["dataFunctions"][name]`:
`{name, functionName, displayName, engine, executor, approved, executeAtBuild, executed, updatedDocument,
needsRefresh, refresh, inputs: {param: {type, expression, expectedInputType, activeFiltering, limitBy,
allowedTypes[, wholeTableRetry]}}, outputs: {param: {type, table, mode: new|replace, exists, rows, columns} |
{type, property, exists}}}`.
`B.created["tables"][T]` for a new output table: `{source: "dataFunction", function, output, id, rows, columns}`;
a replaced table keeps its entry and gains `replacedBy: "<fn>/<param>"`, `rows`, `columns`.

## Spec to API

| spec | API | persisted |
|---|---|---|
| `name` | `DataFunctionDefinitionBuilder(name, executor)`, `.FunctionName = .DisplayName = name`; `DataFunctions.AddNew(name, def)` | `<FunctionName>`, `<DisplayName>`, `DataFunction "<name>"` (the dialog leaves FunctionName `Untitled`) |
| `description` | `builder.Description` | `<Description>` |
| `engine` | `DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor` / `.TERRScriptExecutor` (static fields) | `ServiceType/Name` `Spotfire.PythonScript.Executor` / `Spotfire.SNextScript.Executor` |
| `scriptCode` | `builder.Settings["script"]` | `ImplementationSpecificInformation/script` |
| python | `builder.Settings["dataframe"] = "Pandas"` | `ImplementationSpecificInformation/dataframe` |
| input `type` | `InputParameterBuilder(name, ParameterType.Table / .Column / .Value)` | `ArgumentType` `Matrix` / `Vector` / `Scalar` |
| `dataTypes` | `AddAllowedDataType(DataType.X)` per name, in order | `AllowedTypes/DataType` |
| output `type` | `OutputParameterBuilder(name, ParameterType.Table / .Value)` | `OutputResult/ArgumentType` |
| `bind` | `df.Inputs.SetInput(param, expression[, includeActiveFiltering, DataSelection[]])` | input expression + inferred `InputType` |
| `target.table` | `df.Outputs.SetTableOutput(param, name)` (new) or `SetReplaceDataOutput(param, table)` (exists) | `TableOutputImpl{SuggestedName}` / `ReplaceDataOutputImpl{TableReference}` |
| `target.property` | `df.Outputs.SetDocumentPropertyOutput(param, name)` | `PropertyOutputImpl{PropertyName, PropertyClass: Document}` |
| `refresh` | `df.UpdateBehavior = DataFunctionUpdateBehavior.Automatic / .Manual` | `UpdateBehavior` |
| `executeAtBuild` | `df.ExecuteSynchronously()` | output tables and property values in the file |

## R1 Definition and registration

```python
b = DataFunctionDefinitionBuilder(name, DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor)
b.FunctionName = name; b.DisplayName = name; b.Description = description
b.Settings["script"] = code              # Not yet tested #1: the indexer; fallback b.Settings.Add(k, v)
b.Settings["dataframe"] = "Pandas"       # Python only; Pandas is also Spotfire's default
p = InputParameterBuilder("flowRate", ParameterType.Column)
p.DisplayName = "flowRate"; p.Description = "..."; p.AddAllowedDataType(DataType.Real)
b.InputParameters.Add(p.Build())         # Not yet tested #1: Add through the public IList
b.OutputParameters.Add(OutputParameterBuilder("PUMP_CURVES", ParameterType.Table).Build())
old = df_find(name)                      # no name indexer on DataFunctionCollection: iterate
if old is not None: Document.Data.DataFunctions.Remove(old)     # Not yet tested #7
df = Document.Data.DataFunctions.AddNew(name, b.Build())        # name made unique ("X (2)") if taken
```

- `Build()` throws unless FunctionName and DisplayName are non-empty. It stamps a trust approval for the
  current Windows user, so the building user runs the function without a trust prompt (#21). Another Windows
  user, Web Player or Automation Services is asked to trust it (pitfall 9).
- Builder constructor defaults: `AllowCaching` true (`<OutputsOnlyDependsOnInputs>true`), `Category` default.
- Parameter names: required, unique per direction. An input and an output may share a name (the shared-output
  pattern of the `writing-spotfire-data-functions` skill). Python parameters become script globals: ASCII
  identifiers, not keywords (warning). TERR names may contain dots. Parameters come back from
  `df.DataFunctionDefinition.InputParameters` / `OutputParameters` by iterating (no indexer).

## R2 Input bindings: the expression decides the handler

`SetInput` takes no handler argument and does not validate. Spotfire infers the persisted `InputType` from the
expression text and the parameter type. The report records the prediction as `expectedInputType`.

| bind | expression built | InputType |
|---|---|---|
| `{"table": T, "columns": "*"}` | `$map("[T].$esc($csearch([T],"*"))",",")` (Spotfire's own template; same escaped table name twice) | `Table` (**Not yet tested** #2) |
| `{"table": T, "columns": [A, B]}` | `[T].[A], [T].[B]` | `Columns` |
| `{"table": T, "column": C}` | `[T].[C]` | `Column` |
| `{"property": P}` | `DocumentProperty("P")` | `DocumentProperty` |
| `{"expression": E}` | `E` verbatim (columns table-qualified, aggregated to one value) | `Expression` |
| `{"value": V}` | literal (R4) | `Value` for a plain literal; `Expression` for constructor calls |

Rules: a single literal is `Value` on a Value parameter and `Expression` elsewhere. One `[T].[C]` is
`Expression` on a Value parameter (fails at run time unless aggregated), `Columns` on a Table parameter and
`Column` on a Column parameter. Column lists must come from one table. `${...}` flips the handler to
`Expression`. Names go through `ExpressionUtilities.EscapeIdentifier` / `EscapeStringLiteral`, never by
concatenation. Checked before binding: the table and named columns exist; named columns and the bound
property have a type the parameter allows (warning); the property exists (failure).

## R3 Limits: filtering scheme, active filtering, marking

```python
sel_scheme = B.filtering_scheme("Fleet Filters").FilteringSelectionReference   # 00_core; fallback below
# right after Filterings.Add the FilteringScheme may not exist yet (B.filtering_scheme raises; api-data.md U2):
found, sel_scheme = Document.Data.Filterings.TryGetValue("Fleet Filters")
marking = B.marking("Selected Pump")
df.Inputs.SetInput(param, expression, includeActiveFiltering, Array[DataSelection]([sel_scheme, marking]))
```

- `limitByFiltering: "<scheme>"` puts that `DataFilteringSelection` in `Selections` with
  `IncludeActiveFiltering: false`. `true` sets `IncludeActiveFiltering: true`: the filtering scheme of the active
  page, whatever it is. `limitByMarking: "<marking>"` puts the `DataMarkingSelection` in `Selections`.
- Property and literal binds cannot be limited (warning, limits ignored). Table, column and value-expression
  binds can.
- A scheme or marking that cannot be found becomes a fallback (manual step: Data > Data function properties >
  Edit Parameters > Input > Limit by), and the input is bound without that limit.
- Markings and filtering schemes exist before `df_build_all` (`90_build` order), so lookups by name succeed.
- Nothing is marked during the build: an input limited by a marking gets no marked rows in the build-time run
  (warning when `executeAtBuild`). The script must return typed outputs from an empty input.

## R4 Literals

The literal type is the JSON value's own type when the parameter allows it, otherwise the first listed
`dataTypes` entry.

| type | form | notes |
|---|---|---|
| String | `"text"` (`""` doubles quotes) | `Value` |
| Boolean | `True` / `False` (JSON bool, or "true"/"false"/"yes"/"no"/1/0) | `Value` |
| Integer, LongInteger | `20`; a non-integral number is an error | negative: `Value` or `Expression` (**Not yet tested** #17) |
| Real, SingleReal, Currency | `repr()` digits, `.0` added, exponents expanded (`1e-05` -> `0.00001`) | culture-invariant; never .NET `ToString()` |
| Date | `Date(2026, 6, 30)` | `Expression` (**Not yet tested** #15) |
| DateTime | `DateTime(2026, 1, 1, 8, 30, 0, 0)` | `Expression` (**Not yet tested** #15) |
| Time | `Time(8, 15, 0, 0)` | `Expression` (**Not yet tested** #15) |
| TimeSpan | `TimeSpan(7, 0, 0, 0, 0)` (days, h, min, s, ms; JSON `"7.00:00:00"`) | `Expression` (**Not yet tested** #15) |

`null`, lists and Binary have no literal form: bind a document property instead. For date/time constants a
property binding is the safer route.

## R5 Outputs

- Table, target missing: `SetTableOutput(param, "T")` records a suggested name. The table appears at the first
  successful run, with `CreateFilters: true`. If Spotfire had to make the name unique, the module renames it
  back to `T`.
- Table, target exists (a file table such as PUMP_EVENTS, or the output of an earlier build):
  `SetReplaceDataOutput(param, table)`. Each run replaces the rows and the table keeps its name and identity.
  A function that reads and replaces the same table gets a warning (**Not yet tested** #20).
- Value: `SetDocumentPropertyOutput(param, "P")`. The first run creates a missing property, typed from the
  result. An existing property must match the result type exactly (pitfall 6).
- Unmapped outputs are allowed by the API, but the Python script must assign every registered output
  (`DataFunctionError: Output variable '<name>' was not defined`).

## R6 Execute at build and verify

```python
updated = df.ExecuteSynchronously()      # inline; never throws; returns HasUpdatedDocument
stale = df.NeedsRefresh
found, out = df.Outputs.TryGetValue(param); table = out.DataTableReference    # TableOutput / ReplaceDataOutput
```

- `Execute()` and `Execute(callback)` only queue work until the script returns. Only `ExecuteSynchronously`
  makes output tables exist before visuals are built. Failures show as an Analyst notification. The Boolean is
  False both for a failed run and for a run that changed nothing (inputs unchanged since the last run).
- Checks after the run:
  1. Every new output table and every output property exists. A missing one fails the `execute` step.
  2. Pre-existing outputs (replaced tables, properties) exist even after a failure, so
     `updated == False and NeedsRefresh == True` also fails the step (**Not yet tested** #14).
- Retry aid for #2: if the run fails while whole-table (`$csearch`) inputs are bound, those inputs are rebound
  to explicit column lists and the function runs once more. The lists hold the columns whose type the
  parameter allows, minus spec hierarchies. Success gives a warning ("Not yet tested #2 failed, bind these
  inputs with bind.columns lists") and `wholeTableRetry: true`. If it fails again, the whole-table bindings are
  restored and the step fails.
- `execute` is skipped when a binding step failed or an input table does not exist (it comes from a function
  that is not run at build).

## R7 Refresh

`df.UpdateBehavior = DataFunctionUpdateBehavior.Automatic` is set after the build-time run. A new function
starts Manual. Switching to Automatic queues one asynchronous `Execute()` that starts after the builder script
returns (**Not yet tested** #4). For `executeAtBuild: false` this means the function still runs once after the
build (warning). Automatic functions re-run whenever a bound property, filtering, marking or input data changes.

## Build order inside `df_build_all`

Functions are built in an order where a function whose input binds a table, or whose input expression names
`[T].`, comes after the spec function that outputs `T`. Otherwise spec order. A dependency cycle keeps spec
order (warning). A reorder is reported as a warning listing the order. A consumer can then bind and run
against its producer's output in the same build, provided the producer has `executeAtBuild: true`.

## Type traps

| Python result | Spotfire type |
|---|---|
| `int` | LongInteger (never Integer; `numpy.int32` gives Integer) |
| `float` | Real (`numpy.float32` gives SingleReal) |
| `str` / `bool` | String / Boolean |
| `datetime` / `date` / `time` / `timedelta` | DateTime / Date / Time / TimeSpan |
| `Decimal` | Currency |
| `bytes`, matplotlib/PIL image | Binary |

Inputs arrive as globals: a DataFrame (Table), a Series (Column), a Python scalar (Value), or `None` for an
unmapped optional input. Output column types and property types are fixed by the first run. Missing numerics
must be `np.nan`, never `None`. Integer columns should be `int64`, not pandas `Int64`. A `None` scalar output
fails ("cannot determine type").

## Pitfalls

1. Get-only: `Inputs`, `Outputs`, `Settings`, `InputParameters`, `OutputParameters`, `AllowedDataTypes`,
   `DataFunctionInput.Expression`, `TableOutput.DataTableReference`, `NeedsRefresh`. Change the collections, or
   call `SetInput` / `Set*Output` again (that replaces the binding). Definitions are immutable.
2. Factories, not constructors: `DataFunctionDefinition`, parameters and `*Output` objects only come from
   builders and `Set*` calls. Executor ids are static fields, not an enum.
3. Names: `AddNew` and `SetTableOutput` take suggested names and may append ` (2)`. Re-read the real names.
   The `DataFunction.Name` setter throws when the name is taken.
4. Handler follows the expression (R2). Always qualify columns `[T].[C]`. Aggregate anything bound to a Value
   parameter.
5. IronPython binding: out parameters return tuples (`found, x = coll.TryGetValue(p)`). Pass the limit list as
   `Array[DataSelection](list)`. The 4-argument `SetInput(param, expr, bool, DataSelection[])` is used whenever
   a limit exists, otherwise the 2-argument form.
6. Property outputs keep one type (exact `DataType` match, "Changing datatype of existing property ... is not
   allowed"). A spec property typed Integer or SingleReal written by Python gets a warning: declare it
   LongInteger/Real or return `numpy.int32`/`numpy.float32` (**Not yet tested** #8).
7. TimeSpan is not in the dialog's "all types" list: list it in `dataTypes` explicitly.
8. Run location: there is no public setting for it. API-created functions persist an empty
   `AdditionalSettings` and follow the user or administrator engine preference.
9. Trust beyond the building user: an untrusted Python function fails at run time for other users until they
   trust it (Analyst prompt), or it comes from a trusted library or `IgnoreDataFunctionTrustCheck` is set.
10. `.sfd` files have no public loader. Library definitions: `DataFunctionDefinition.Load(item, LibraryManager)`
    (not used by the builder).
11. Python environment: the bundled interpreter has numpy, pandas 2.3.x, spotfire 2.4.x. Anything else is an
    environment dependency to list in the script header (see the `writing-spotfire-data-functions` skill).

## Not yet tested

| # | Unknown | Smallest test / what the build shows |
|---|---|---|
| 1 | `builder.Settings["script"] = s` and `builder.InputParameters.Add(p)` work through the public `IDictionary` / `IList` interfaces | a `register` step `ok`; a failure names the member |
| 2 | `$map("[T].$esc($csearch([T],"*"))",",")` gives InputType `Table` and passes every column (and later-added ones) | saved DXP shows `InputType: DataFunctionInputType.Table`; the retry warning appears only if it fails |
| 3 | `ExecuteSynchronously()` on a never-run function creates its new output table inside the script | `execute` ok and `outputs[T].exists` true in the report |
| 4 | Manual->Automatic after the sync run queues a second run; does it overlap the queued save? | compare a `time.time()` output before and after; `saved` true in the report |
| 5 | Reopen: outputs restored without a re-run and without a trust prompt for the same user | save, close, reopen; compare a `time.time()` output |
| 7 | `DataFunctions.Remove(df)` effect on its output tables (rebuild in the same document) | re-run the builder in the built document; table still present and replaced |
| 8 | A Python `int` into a pre-created Integer property: converted or rejected | run with `OpenEventCount` (Integer) and `int(...)`; expect a failed `execute` |
| 13 | `TableOutput.DataTableReference` is None before the first run and set right after it | the module falls back to `B.table(T)` when it is None |
| 14 | `NeedsRefresh` is True after a failed `ExecuteSynchronously` and False after a successful one | a deliberately failing script must give a failed `execute` step |
| 15 | `Date(...)`, `DateTime(...)`, `Time(...)`, `TimeSpan(...)` constants on a Value parameter (InputType Expression, no table) evaluate | inputs `asOfDate`, `reviewWindow`, `historyStart` of `assets/examples/fragments/datafunctions.json` |
| 16 | An Integer literal accepted by a LongInteger-only parameter; a Real literal by SingleReal- or Currency-only parameters | run with such a parameter |
| 17 | A negative numeric literal persists as InputType `Value` or `Expression` | InputType in the saved DXP |
| 18 | A binding to a table that does not exist yet resolves once its producer runs | consumer of an output of a function with `executeAtBuild: false`, refreshed by hand |
| 19 | `$csearch("*")` on a table with hierarchy columns: passed, skipped or rejected | `Summarize Pump Events` in `assets/examples/fragments/data.json` (PUMP_DATA has a hierarchy) |
| 20 | A function that reads and replaces the same table: refused, or loops on automatic refresh | avoid; warning in the report |
| 21 | `IsApprovedByCurrentUser` is true right after `Build()` in Analyst | `approved` in the report; `TrustApproval/ApprovalStamp` non-empty |

## What verify_dxp should check

`verify_dxp.py` reads the saved DXP directly: the definition XML each `DataFunction` stores
(`FunctionImpl > FunctionDefinition > Data`), its input and output bindings, and `build/build-report.json`.

- Definition XML per spec function:
  - `FunctionName` = `DisplayName` = the instance name = spec `name`; `Description` = spec description.
  - `ServiceType/Name` `Spotfire.PythonScript.Executor` (python) or `Spotfire.SNextScript.Executor` (terr).
  - `ImplementationSpecificInformation/script` equals `scriptCode`, compared with line endings normalized
    (CRLF vs LF). `ImplementationSpecificInformation/dataframe` = `Pandas` for Python and absent for TERR.
  - One `InputArgument` per spec input: `Name`, `DisplayName` = name, `Description`,
    `ArgumentType` (table `Matrix`, column `Vector`, value `Scalar`), `AllowedTypes` = spec `dataTypes` in order,
    or exactly `Integer, Real, SingleReal, Currency, String, Date, Time, DateTime, Boolean, Binary, LongInteger`.
  - One `OutputResult` per spec output: `Name`, `ArgumentType`. `OutputsOnlyDependsOnInputs` true.
  - `TrustApproval/ApprovalStamp` non-empty.
- Inputs (`DataFunctionInputExpressionImpl`):
  - `Expression` equals the report's `inputs[p].expression`.
  - `InputType: DataFunctionInputType.<expectedInputType>`; `Value|Expression` accepts either.
  - `IncludeActiveFiltering` equals `activeFiltering`.
  - `Selections` names equal `limitBy` (`DataFilteringSelection "<scheme>"`, `DataMarkingSelection "<marking>"`).
    GenericNameMapper keys: the selection names, plus `activeFiltering` when it is set.
- Outputs: new table `TableOutputImpl { SuggestedName: "<target>", CreateFilters: true }`; existing table
  `ReplaceDataOutputImpl { TableReference -> DataTable "<target>" }`; property
  `PropertyOutputImpl "<prop>" { PropertyClass: DataPropertyClass.Document }`.
- `UpdateBehavior: DataFunctionUpdateBehavior.Automatic | Manual` as in the spec; `Visible` per `settings`.
  `AdditionalSettings` empty is expected for API-created functions.
- `executeAtBuild: true`: the output table exists under exactly the target name, with an `ExternalColumnProducer`
  column producer, and the report shows `executed: true`, `outputs[*].exists: true`, `execute` step `ok`.
  No table named `<target> (2)` and no `Untitled` FunctionName anywhere.
- One name per binding: every value input/output bound to a property has the property's name (dxpgen
  enforces it; the builder warns).

## Marking-limited inputs in the standard engine

Feature `markedInputs` of `scripts/engine/features/datafunctions.py` (spec `bind.limitByMarking` on a table
or column input):

```python
found, m = Document.Data.Markings.TryGetValue(name)       # markings are built before the functions
df.Inputs.SetInput(param, expression, False, Array[DataSelection]([m]))
```

- `SetInput(InputParameter, String, Boolean includeActiveFiltering, params DataSelection[])` [api 3.1];
  a `DataMarkingSelection` is a `DataSelection`. Persisted as `Selections: [marking]` plus a
  `SelectionMapperReference`.
- There is no input-level "when nothing is marked" option (`LimitingMarkingsEmptyBehavior` exists on
  visuals and reference layers only): with nothing marked the function gets zero rows. At build nothing is
  marked, so the build-time run gets an empty table (log: `NOTE input <name>: only rows marked in
  <marking> (none during the build)`) and must return typed outputs (a String `""` works; a `None` scalar
  output fails with "cannot determine type").
- An automatic function re-runs on every change of the marking. A property that is an input and an
  output of automatic functions (directly or through a chain) is a cycle: after the run Spotfire reports
  "Automatic updates cannot be performed due to cyclic dependencies." and sets `UpdateBehavior = Manual`.
  To fill properties the user can also type (for example a window start and end), write one String property
  from the function and copy it on with a property trigger script: trigger scripts are outside the dependency
  graph. Property triggers are a manual step (see [api-scripts.md](api-scripts.md)).
- `limitByFiltering` and marking limits on property, expression or literal binds stop the standard engine
  ("use --tier slim").
- **Not yet tested**: the empty build-time run reports success (`ExecuteSynchronously` True or
  `NeedsRefresh` False), and the function re-runs on each drag.
