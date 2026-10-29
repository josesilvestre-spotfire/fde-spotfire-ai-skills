# Registration, bindings and run chains

Spotfire Analyst 15.0. The API code below is the public API that the `building-spotfire-dxps`
builders use in their live builds; the dialog steps are the manual route.

## Register by hand

Work line by line from the two registration tables in the script header.

1. Data > Data function properties > Register New. Type: Python script.
2. Name: the Title Case verb + object name from the header (`Calculate Pump Efficiency`). Set it
   in the name field: a function left as `Untitled` breaks the naming standard and is hard to find
   in a run chain.
3. Script: paste the whole file.
4. Input parameters: one entry per line of `STAGING: INPUT PARAMETERS`, with the exact name, the
   type (Table, Column, Value) and the allowed data types.
5. Output parameters: one entry per line of `STAGING: OUTPUT PARAMETERS`.
6. Run, then map each parameter:
   - Table input: the table, all columns (new columns are picked up), or a column list.
   - Column input: one column, table-qualified.
   - Value input bound to a document property: the property with the same name.
   - Value input that is a constant: a value.
   - Table output: Data table, a new table with the UPPER_SNAKE name, replaced on refresh.
   - Value output: Document property, the property with the same name.
7. Limit a Table or Column input by a marking or a filtering scheme when the function should see
   only the marked or filtered rows. Property and literal inputs cannot be limited.
8. Refresh: automatic for functions driven by controls, so they rerun when a bound property,
   filtering, marking or input table changes. Manual for expensive runs, behind a button.

Dialog labels can differ slightly between Spotfire versions.

## How Spotfire reads an input binding

Spotfire infers the input handler from the expression text:

| Binding | Expression | Handler |
|---|---|---|
| whole table | `$map("[T].$esc($csearch([T],"*"))",",")` | Table (all columns) |
| column list | `[T].[A], [T].[B]` | Columns |
| one column | `[T].[C]` | Column |
| document property | `DocumentProperty("P")` | Document property |
| expression | any expression, aggregated to one value for a Value input | Expression |
| literal | `20`, `"text"` | Value |

Qualify columns with their table (`[T].[C]`). A `${...}` in the expression makes it an Expression
input.

## Register through the API (IronPython 3)

```python
from Spotfire.Dxp.Data import DataType
from Spotfire.Dxp.Data.DataFunctions import (
    DataFunctionDefinitionBuilder, DataFunctionExecutorTypeIdentifiers,
    DataFunctionUpdateBehavior, InputParameterBuilder,
    OutputParameterBuilder, ParameterType)

NAME = "Calculate Pump Efficiency"


def put(settings, key, value):
    try:
        settings[key] = value
    except Exception:
        settings.Add(key, value)


def param(params, name):
    for p in params:
        if p.Name == name:
            return p
    raise Exception("parameter not registered: " + name)


b = DataFunctionDefinitionBuilder(
    NAME, DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor)
b.FunctionName = NAME
b.DisplayName = NAME
b.Description = "Hydraulic power and efficiency of every pump reading."
put(b.Settings, "script", code)      # the file content, read by the caller
put(b.Settings, "dataframe", "Pandas")
for name, kind, types in (("readings", ParameterType.Table, []),
                          ("MinPoints", ParameterType.Value, [DataType.Integer])):
    p = InputParameterBuilder(name, kind)
    p.DisplayName = name
    for t in types:
        p.AddAllowedDataType(t)
    b.InputParameters.Add(p.Build())
for name, kind in (("PUMP_EFFICIENCY", ParameterType.Table),
                   ("PumpsBelowTarget", ParameterType.Value)):
    p = OutputParameterBuilder(name, kind)
    p.DisplayName = name
    b.OutputParameters.Add(p.Build())

df = Document.Data.DataFunctions.AddNew(NAME, b.Build())
ins = df.DataFunctionDefinition.InputParameters
outs = df.DataFunctionDefinition.OutputParameters
df.Inputs.SetInput(param(ins, "readings"),
                   '$map("[PUMP_READINGS].$esc($csearch([PUMP_READINGS],"*"))",",")')
df.Inputs.SetInput(param(ins, "MinPoints"), 'DocumentProperty("MinPoints")')
df.Outputs.SetTableOutput(param(outs, "PUMP_EFFICIENCY"), "PUMP_EFFICIENCY")
df.Outputs.SetDocumentPropertyOutput(param(outs, "PumpsBelowTarget"), "PumpsBelowTarget")
df.ExecuteSynchronously()
df.UpdateBehavior = DataFunctionUpdateBehavior.Automatic
```

- `Build()` approves the definition for the Windows user who runs the script, so it runs for that
  user without a trust prompt. Other users, Web Player and Automation Services ask for trust.
- `AddNew` and `SetTableOutput` take suggested names and append ` (2)` when a name is taken.
  Remove the old function or table first, and read the real names back.
- Definitions are immutable. To change the code, build a new definition.
- Escape table and column names with `ExpressionUtilities.EscapeIdentifier` and text with
  `EscapeStringLiteral` (`Spotfire.Dxp.Data.Expressions`) instead of concatenating them.
- Python and the bundled `spotfire` package set the output types on the first run. A property
  output keeps its type afterwards ("Changing datatype of existing property ... is not allowed").

For a whole analysis built from a spec, use the `building-spotfire-dxps` skill.

## Run chains

One IronPython script owns the order in which data functions run. A new data function is done
when it is (1) in its file, (2) in the run chain and (3) in the setup guide.

```python
# Run All Data Functions: runs the analysis's data functions in dependency
# order (generator first, then the functions that read its tables).
ORDER = ["Generate Pump Readings", "Calculate Pump Efficiency",
         "Rank Pumps"]

functions = {}
for df in Document.Data.DataFunctions:
    functions[df.Name] = df

missing = [name for name in ORDER if name not in functions]
for name in ORDER:
    if name in functions:
        functions[name].ExecuteSynchronously()
Document.Properties["StatusMessage"] = (
    "Ran %d data functions" % (len(ORDER) - len(missing))
    + ("; not found: " + ", ".join(missing) if missing else ""))
```

- `ExecuteSynchronously()` runs the function before the next line; `Execute()` only queues it until
  the script ends. Use `ExecuteSynchronously` whenever a later step reads the output.
- It never raises. It returns False both for a failed run and for a run that changed nothing, so
  check the output tables or a status property the function writes.
- A data function the user has not trusted does not run, and `ExecuteSynchronously` does nothing.
  The user reviews and trusts it in Analyst (File > Manage trust). For the update and trust
  workflow of a function edited outside Spotfire, use the `updating-data-functions-with-claude`
  skill.
- Status text goes to a document property that a label shows; scripts never `print`.

## One master table

A generator function that is expensive or random runs once and writes the table every sibling
reads. Ship the same table as a CSV or SBDF file so a user can skip the generator, and say so in
the setup guide.
