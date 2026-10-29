# Standard engine, feature part "datafunctions": Python data
# functions inside the analysis (lib/30_datafunctions.py; recipes in
# references/api-datafunctions.md R1-R7), built in spec order: register
# (code read from HOME\datafunctions at build time), bind inputs and
# outputs, ExecuteSynchronously when "run" (output tables join T, so
# visuals, formats and controls use them), then the refresh mode. Every
# step is its own ok(...); the log gets one line per run (OK / FAILED).
# APP "dataFunctions": [{name, file | code, description, in, out,
# refresh "manual" (absent = automatic), run False (absent = true)}]
#   in:  [[name, "table"|"column"|"value", bind, dataTypes], ...]
#        bind {table, columns [..]} (no columns: the table's columns at
#        bind time, else Spotfire's $csearch template) | {table, column}
#        | {property} | {expression} | {value: "text"}; dataTypes absent =
#        the 11 types of Spotfire's registration dialog; a table or column
#        bind may add "marking": name (feature markedInputs: the input
#        gets only the rows marked in it - none during the build, so the
#        build-time run gets an empty table and must still return typed
#        outputs)
#   out: [[name, "table", table] | [name, "value", property], ...]
# @api DataFunctionDefinitionBuilder.ctor(String, TypeIdentifier)
# @api DataFunctionDefinitionBuilder.FunctionName
# @api DataFunctionDefinitionBuilder.DisplayName
# @api DataFunctionDefinitionBuilder.Description
# @api DataFunctionDefinitionBuilder.Settings
# @api DataFunctionDefinitionBuilder.InputParameters
# @api DataFunctionDefinitionBuilder.OutputParameters
# @api DataFunctionDefinitionBuilder.Build
# @api DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor
# @api InputParameterBuilder.ctor(String, ParameterType)
# @api InputParameterBuilder.DisplayName; InputParameterBuilder.Build
# @api InputParameterBuilder.AddAllowedDataType(DataType)
# @api OutputParameterBuilder.ctor(String, ParameterType)
# @api OutputParameterBuilder.DisplayName; OutputParameterBuilder.Build
# @api ParameterType.Table; ParameterType.Column; ParameterType.Value
# @api DataManager.DataFunctions
# @api DataFunctionCollection.AddNew(String, DataFunctionDefinition)
# @api DataFunction.Name; DataFunction.DataFunctionDefinition
# @api DataFunctionDefinition.InputParameters; InputParameter.Name
# @api DataFunctionDefinition.OutputParameters; OutputParameter.Name
# @api DataFunction.Inputs; DataFunction.Outputs
# @api DataFunctionInputCollection.SetInput(InputParameter, String)
# @api DataFunctionOutputCollection.SetDocumentPropertyOutput(OutputParameter, String)
# @api DataFunctionOutputCollection.SetReplaceDataOutput(OutputParameter, DataTable)
# @api DataFunctionOutputCollection.SetTableOutput(OutputParameter, String)
# @api DataFunction.ExecuteSynchronously; DataFunction.NeedsRefresh
# @api DataFunction.UpdateBehavior; DataFunctionUpdateBehavior.Automatic
# @api DataFunctionUpdateBehavior.Manual
# @api DataTableCollection.TryGetValue(String, out DataTable)
# @api DataTable.RowCount; DataTable.Columns; DataColumn.Name
# @api ExpressionUtilities.EscapeIdentifier(String)
# @api ExpressionUtilities.EscapeStringLiteral(String)
# @api DataType.Integer; DataType.Real; DataType.SingleReal
# @api DataType.Currency; DataType.String; DataType.Date; DataType.Time
# @api DataType.DateTime; DataType.Boolean; DataType.Binary
# @api DataType.LongInteger; DataType.TimeSpan
# @set DataFunctionDefinitionBuilder.FunctionName
# @set DataFunctionDefinitionBuilder.DisplayName
# @set DataFunctionDefinitionBuilder.Description
# @set InputParameterBuilder.DisplayName; OutputParameterBuilder.DisplayName
# @set DataFunction.Name; DataFunction.UpdateBehavior
from System import Array
from System.IO import File, Path
from Spotfire.Dxp.Data import DataType, DataSelection
from Spotfire.Dxp.Data.Expressions import ExpressionUtilities
from Spotfire.Dxp.Data.DataFunctions import DataFunctionDefinitionBuilder
from Spotfire.Dxp.Data.DataFunctions import (
    DataFunctionExecutorTypeIdentifiers, DataFunctionUpdateBehavior)
from Spotfire.Dxp.Data.DataFunctions import InputParameterBuilder
from Spotfire.Dxp.Data.DataFunctions import OutputParameterBuilder
from Spotfire.Dxp.Data.DataFunctions import ParameterType

# ------------------------------------------------------ data functions
DF_TYPES = ["Integer", "Real", "SingleReal", "Currency", "String", "Date",
            "Time", "DateTime", "Boolean", "Binary", "LongInteger"]


def ident(name):
    return ExpressionUtilities.EscapeIdentifier(name)


def lit(text):
    return ExpressionUtilities.EscapeStringLiteral(text)


def bind_expr(b):
    """APP bind -> input expression; Spotfire infers the input handler
    from its text (Table, Columns, Column, DocumentProperty, Value)."""
    if "property" in b:
        return "DocumentProperty(" + lit(b["property"]) + ")"
    if "expression" in b:
        return b["expression"]
    if "value" in b:
        return lit(b["value"])
    t = ident(b["table"])
    if "column" in b:
        return t + "." + ident(b["column"])
    cols = b.get("columns")
    if cols is None and b["table"] in T:
        cols = [c.Name for c in T[b["table"]].Columns]
    if cols is None:
        return '$map("%s.$esc($csearch(%s,%s))",",")' % (t, t, lit("*"))
    return ", ".join([t + "." + ident(c) for c in cols])


def parameter(params, name):
    for p in params:
        if p.Name == name:
            return p
    raise Exception("parameter not registered: " + name)


def put(settings, key, value):
    try:
        settings[key] = value
    except Exception:
        settings.Add(key, value)


def ptype(kind):
    return getattr(ParameterType, kind.capitalize())


def definition(d):
    b = DataFunctionDefinitionBuilder(
        d["name"], DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor)
    b.FunctionName = d["name"]
    b.DisplayName = d["name"]
    b.Description = d.get("description", "")
    code = d.get("code")
    if code is None:
        code = File.ReadAllText(
            Path.Combine(HOME, "datafunctions", d["file"]))
    put(b.Settings, "script", code)
    put(b.Settings, "dataframe", "Pandas")
    for i in d["in"]:
        p = InputParameterBuilder(i[0], ptype(i[1]))
        p.DisplayName = i[0]
        for name in (i[3] if len(i) > 3 else DF_TYPES):
            p.AddAllowedDataType(getattr(DataType, name))
        b.InputParameters.Add(p.Build())
    for o in d["out"]:
        p = OutputParameterBuilder(o[0], ptype(o[1]))
        p.DisplayName = o[0]
        b.OutputParameters.Add(p.Build())
    return b.Build()


# @feature markedInputs
# @api DataFunctionInputCollection.SetInput(InputParameter, String, Boolean, DataSelection[])
# @api DataManager.Markings; DataSelection
# @api DataMarkingSelectionCollection.TryGetValue(String, out DataMarkingSelection)
def marked_rows(name):
    """DataSelection[] of a marking (the markings are built before the
    data functions)."""
    found, m = Document.Data.Markings.TryGetValue(name)
    if not found:
        raise Exception("no marking " + name)
    return Array[DataSelection]([m])
# @endfeature


def bind_input(df, i):
    params = df.DataFunctionDefinition.InputParameters
    # @feature markedInputs
    if i[2].get("marking"):
        df.Inputs.SetInput(parameter(params, i[0]), bind_expr(i[2]), False,
                           marked_rows(i[2]["marking"]))
        LOG.append("NOTE input " + i[0] + ": only rows marked in "
                   + i[2]["marking"] + " (none during the build)")
        return True
    # @endfeature
    df.Inputs.SetInput(parameter(params, i[0]), bind_expr(i[2]))
    return True


def bind_output(df, o):
    param = parameter(df.DataFunctionDefinition.OutputParameters, o[0])
    if o[1] == "value":
        df.Outputs.SetDocumentPropertyOutput(param, o[2])
    elif o[2] in T:
        df.Outputs.SetReplaceDataOutput(param, T[o[2]])
    else:
        df.Outputs.SetTableOutput(param, o[2])
    return True


def run_function(df, d):
    """ExecuteSynchronously (Execute() only queues the run until the
    script ends); then every output table must exist."""
    updated = df.ExecuteSynchronously()
    done = []
    for o in d["out"]:
        if o[1] == "table":
            found, t = Document.Data.Tables.TryGetValue(o[2])
            if not found:
                raise Exception("no table " + o[2] + " after the run "
                                "(Analyst's notifications show why)")
            T[o[2]] = t
            done.append(o[2] + " " + str(t.RowCount) + " rows")
    if not updated and df.NeedsRefresh:
        raise Exception("the run failed (Analyst's notifications show "
                        "why)")
    LOG.append("OK data function " + d["name"] + ": ran"
               + (" - " + ", ".join(done) if done else ""))
    return True


def set_refresh(df, d):
    mode = d.get("refresh", "automatic").capitalize()
    df.UpdateBehavior = getattr(DataFunctionUpdateBehavior, mode)


def build_function(d):
    name = "data function " + d["name"]
    df = Document.Data.DataFunctions.AddNew(d["name"], definition(d))
    if df.Name != d["name"]:
        df.Name = d["name"]
    failed = 0
    for i in d["in"]:
        if not ok(name + ": input " + i[0], bind_input, df, i):
            failed += 1
    for o in d["out"]:
        if not ok(name + ": output " + o[0], bind_output, df, o):
            failed += 1
    if not d.get("run", True):
        LOG.append("NOTE " + name + ": not run at build (executeAtBuild "
                   "false)")
    elif failed:
        LOG.append("FAILED " + name + ": not run, " + str(failed)
                   + " binding(s) failed")
    else:
        ok(name + ": run", run_function, df, d)
    ok(name + ": refresh", set_refresh, df, d)
