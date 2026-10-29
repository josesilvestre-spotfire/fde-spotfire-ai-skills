# ============================================================================
# 30_datafunctions.py - data functions: definition (Python or TERR script),
# registration under the spec name, input and output bindings, execution at
# build time and refresh behaviour.
#
#   df_build_all(dfspecs)  every spec data function, producers before consumers
#                          -> {spec name: DataFunction}
#   df_build(dspec)        one function; each part is its own B.step, in this order:
#                          register <fn> | input <fn>/<param> | output <fn>/<param> |
#                          execute <fn> | refresh <fn> | settings <fn>
#   df_find(name)          registered DataFunction by name (case-insensitive) or None;
#                          also used by 80_textareas (refreshDataFunction actions)
#
# 90_build runs this after properties, file tables, markings and filtering schemes,
# so B.prop, B.marking and B.filtering_scheme (00_core) resolve at bind time.
# IronPython 3.4 inside Spotfire Analyst 15.0 (Python 3.4 syntax: no f-strings, no
# walrus, no annotations, no print). Public API only, no reflection; members in
# lib/30_datafunctions.members.txt, assignments in lib/30_datafunctions.set.txt.
# Requires newer than 14.6: none (newest member used:
#   DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor [api 10.9]).
# Defaults (references/spec-format.md lists none for data functions): engine "python", refresh
#   "automatic", executeAtBuild true, description "", dataTypes = the 11 types of
#   Spotfire's registration dialog (TimeSpan only when listed).
# Optional beyond the references/spec-format.md v1 example: bind.columns as a list of column names;
#   limitByFiltering true = the active filtering scheme; limits on column and
#   expression binds; "description" on inputs and outputs; "settings" (escape
#   hatch relative to the DataFunction).
# Recipes, pitfalls, Not yet tested list: references/api-datafunctions.md
# ============================================================================
import re
from System import Array
from System.IO import File
from Spotfire.Dxp.Data import DataSelection, DataPropertyClass
from Spotfire.Dxp.Data.Expressions import ExpressionUtilities
from Spotfire.Dxp.Data.DataFunctions import (DataFunctionDefinitionBuilder,
                                             DataFunctionExecutorTypeIdentifiers,
                                             InputParameterBuilder, OutputParameterBuilder,
                                             ParameterType, DataFunctionUpdateBehavior)

# What Spotfire's registration dialog writes for "all types" (FunctionDefinitionModel.
# AvailableDataTypes, same order). TimeSpan is not offered there: list it in dataTypes.
_datafunctions_all_type_names = ("Integer", "Real", "SingleReal", "Currency", "String", "Date",
                                 "Time", "DateTime", "Boolean", "Binary", "LongInteger")
# Every name dataTypes may list (references/spec-format.md DataType names). Checked before data_type(): getattr on the
# DataType class would return an instance-property descriptor for a name such as "Name".
_datafunctions_known_types = _datafunctions_all_type_names + ("TimeSpan",)

# Python parameters become script globals: ASCII identifiers that are not reserved words of
# the data-function interpreter (CPython 3.14).
_datafunctions_identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_datafunctions_python_keywords = (
    "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in",
    "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield")

_datafunctions_error_hint = (" Analyst shows the script error in its notifications; Data > Data "
                             "function properties > select the function > Refresh repeats it.")


# ---- public ---------------------------------------------------------------------
def df_build_all(dfspecs):
    """Build every spec data function. A function that reads a table written by another spec
    function is built after it (stable otherwise). Returns {spec name: DataFunction}."""
    built = {}
    specs = [d for d in (dfspecs or []) if isinstance(d, dict)]
    if not specs:
        return built
    ordered = B.step("order", "dataFunctions", _datafunctions_order, (specs,))
    for dspec in (ordered if ordered is not None else specs):
        df = df_build(dspec)
        if df is not None:
            built[dspec.get("name")] = df
    return built


def df_build(dspec):
    """Register one data function, bind its inputs and outputs, run it when executeAtBuild, set
    its refresh behaviour, apply its settings. Returns the DataFunction or None."""
    name = str(dspec.get("name") or "")
    registered = B.step("register", name, _datafunctions_register, (dspec,))
    if registered is None:
        B.skip("bindings", name, "registration failed: inputs, outputs, execution and refresh skipped")
        return None
    df, record = registered
    state = {}          # input name -> binding parts (.NET objects stay out of the report)
    failed = 0
    for ispec in (dspec.get("inputs") or []):
        iname = str(ispec.get("name"))
        bound = B.step("input", name + "/" + iname, _datafunctions_bind_input, (df, dspec, ispec, state))
        if bound is None:
            failed += 1
        else:
            record["inputs"][iname] = bound
    for ospec in (dspec.get("outputs") or []):
        oname = str(ospec.get("name"))
        bound = B.step("output", name + "/" + oname, _datafunctions_bind_output, (df, dspec, ospec))
        if bound is None:
            failed += 1
        else:
            record["outputs"][oname] = bound
    if record["executeAtBuild"]:
        reason = _datafunctions_execute_blocker(dspec, failed)
        if reason:
            B.skip("execute", name, reason)
        else:
            B.step("execute", name, _datafunctions_execute, (df, dspec, record, state))
    else:
        _datafunctions_warn_unrun_outputs(name, record)
    B.step("refresh", name, _datafunctions_set_refresh, (df, dspec, record))
    if dspec.get("settings"):
        B.step("settings", name, apply_settings, (df, dspec["settings"]))
    return df


def df_find(name):
    """Data function by name (case-insensitive, like Spotfire's unique-name rule), or None.
    DataFunctionCollection has no name indexer, so this is the one place that iterates it."""
    wanted = str(name or "").lower()
    for f in B.doc.Data.DataFunctions:
        if f.Name.lower() == wanted:
            return f
    return None


# ---- build order ----------------------------------------------------------------------
def _datafunctions_order(specs):
    """Producers before consumers: a function whose input binds (or whose input expression
    names) a table written by another spec function comes after that function. Stable: spec
    order otherwise. Functions caught in a dependency cycle keep spec order (warning)."""
    n = len(specs)
    producers = {}
    for i in range(n):
        for t in _datafunctions_output_table_names(specs[i]):
            producers.setdefault(t, []).append(i)
    deps = []
    for i in range(n):
        need = set()
        for t in _datafunctions_read_tables(specs[i], list(producers.keys())):
            for j in producers.get(t, []):
                if j != i:
                    need.add(j)
        deps.append(need)
    order = []
    done = set()
    while len(order) < n:
        nxt = None
        for i in range(n):
            if i not in done and not (deps[i] - done):
                nxt = i
                break
        if nxt is None:
            rest = [i for i in range(n) if i not in done]
            B.warn("data functions in a table dependency cycle keep spec order: "
                   + ", ".join([str(specs[i].get("name")) for i in rest]))
            order.extend(rest)
            break
        order.append(nxt)
        done.add(nxt)
    if order != list(range(n)):
        B.warn("data functions are built in dependency order: "
               + " -> ".join([str(specs[i].get("name")) for i in order]))
    return [specs[i] for i in order]


def _datafunctions_output_table_names(dspec):
    names = []
    for ospec in (dspec.get("outputs") or []):
        t = (ospec.get("target") or {}).get("table")
        if t and _datafunctions_kind(ospec) == "table":
            names.append(t)
    return names


def _datafunctions_read_tables(dspec, candidates):
    """Tables a function reads: bind.table of its inputs, plus each candidate table whose escaped
    name appears in an input expression ("[T]." prefix)."""
    names = set()
    for ispec in (dspec.get("inputs") or []):
        bind = _datafunctions_bind_of(ispec)
        if bind.get("table"):
            names.add(bind["table"])
        expression = bind.get("expression")
        if expression:
            for t in candidates:
                if esc(t) + "." in str(expression):
                    names.add(t)
    return names


# ---- registration ------------------------------------------------------------------
def _datafunctions_register(dspec):
    """Definition -> AddNew under the spec name. Returns (DataFunction, report record)."""
    name = dspec.get("name")
    if not name:
        raise Exception("data function without a name")
    engine = _datafunctions_engine_name(dspec)
    _datafunctions_check_parameter_names(dspec, engine)
    definition = _datafunctions_definition(dspec, name, engine)
    old = df_find(name)
    if old is not None:
        # Rebuild in a document that already has it: its output tables stay and are reused through
        # replace outputs (Not yet tested #7: what Remove does to the old output tables).
        B.doc.Data.DataFunctions.Remove(old)
        B.warn("data function '" + name + "' already existed and was replaced")
    df = B.doc.Data.DataFunctions.AddNew(name, definition)
    if df.Name != name:
        df.Name = name          # AddNew makes the name unique ("X (2)"); the setter throws when taken
    registered = df.DataFunctionDefinition
    # One name everywhere: instance Name = DisplayName = FunctionName = spec name (the dialog
    # leaves FunctionName "Untitled").
    record = {"name": df.Name, "functionName": registered.FunctionName,
              "displayName": registered.DisplayName, "engine": engine,
              "executor": _datafunctions_safe(lambda: registered.ServiceType.Name),
              "approved": _datafunctions_safe(lambda: bool(registered.IsApprovedByCurrentUser)),
              "inputs": {}, "outputs": {},
              "executeAtBuild": _datafunctions_flag(dspec, "executeAtBuild", True),
              "executed": False, "updatedDocument": False, "needsRefresh": None, "refresh": None}
    B.created["dataFunctions"][name] = record
    return df, record


def _datafunctions_definition(dspec, name, engine):
    """Immutable DataFunctionDefinition with FunctionName and DisplayName = the spec name; AddNew
    sets the instance name. Build() marks it CreatedProgrammatically and stamps a current-user
    trust approval, so it runs here without a trust prompt."""
    b = DataFunctionDefinitionBuilder(name, _datafunctions_executor(engine))
    b.FunctionName = name
    b.DisplayName = name
    b.Description = dspec.get("description") or ""
    _datafunctions_put_setting(b.Settings, "script", _datafunctions_script_code(dspec))
    if engine == "python":
        _datafunctions_put_setting(b.Settings, "dataframe", "Pandas")
    # InputParameters / OutputParameters are IList over an internal ValidatingList:
    # Not yet tested #1 that Add binds through the public interface.
    for ispec in (dspec.get("inputs") or []):
        b.InputParameters.Add(_datafunctions_input_parameter(ispec))
    for ospec in (dspec.get("outputs") or []):
        b.OutputParameters.Add(_datafunctions_output_parameter(ospec))
    return b.Build()


def _datafunctions_put_setting(settings, key, value):
    """Settings is IDictionary<String,String> over an internal ValidatingDictionary that rejects
    null values. Each key persists as an element under <ImplementationSpecificInformation>.
    Not yet tested #1: the indexer binds; Add() is the fallback for a new key."""
    try:
        settings[key] = value
    except Exception:
        settings.Add(key, value)


def _datafunctions_script_code(dspec):
    code = dspec.get("scriptCode")
    if code is None and dspec.get("script"):
        code = File.ReadAllText(B.path(dspec["script"]))     # dxpgen normally inlines it
    if not code or not str(code).strip():
        raise Exception("data function '" + str(dspec.get("name")) + "' has no script code")
    return code


def _datafunctions_engine_name(dspec):
    engine = str(dspec.get("engine") or "python").lower()
    if engine not in ("python", "terr"):
        raise Exception("engine must be python or terr, not '" + engine + "'")
    return engine


def _datafunctions_executor(engine):
    """Persisted ServiceType names: Spotfire.SNextScript.Executor (TERR),
    Spotfire.PythonScript.Executor (Python)."""
    if engine == "terr":
        return DataFunctionExecutorTypeIdentifiers.TERRScriptExecutor
    return DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor


def _datafunctions_kind(pspec):
    return str(pspec.get("type") or "").lower()


def _datafunctions_parameter_type(kind):
    if kind == "table":
        return ParameterType.Table          # persisted ArgumentType Matrix
    if kind == "column":
        return ParameterType.Column         # Vector
    if kind == "value":
        return ParameterType.Value          # Scalar
    raise Exception("parameter type must be table, column or value, not '" + kind + "'")


def _datafunctions_explicit_types(ispec):
    names = ispec.get("dataTypes")
    if not names:
        return None
    if isinstance(names, str):
        names = [names]
    out = []
    for n in names:
        text = str(n)
        if text not in _datafunctions_known_types:
            raise Exception("input '" + str(ispec.get("name")) + "': unknown data type '" + text
                            + "' in dataTypes (use " + ", ".join(_datafunctions_known_types) + ")")
        out.append(text)
    return out


def _datafunctions_allowed_types(ispec):
    return _datafunctions_explicit_types(ispec) or list(_datafunctions_all_type_names)


def _datafunctions_input_parameter(ispec):
    name = ispec["name"]
    b = InputParameterBuilder(name, _datafunctions_parameter_type(_datafunctions_kind(ispec)))
    b.DisplayName = name
    b.Description = ispec.get("description") or ""
    for type_name in _datafunctions_allowed_types(ispec):
        b.AddAllowedDataType(data_type(type_name))       # unknown type name -> exception
    return b.Build()


def _datafunctions_output_parameter(ospec):
    name = ospec["name"]
    kind = _datafunctions_kind(ospec)
    if kind not in ("table", "value"):
        raise Exception("output '" + str(name) + "': type must be table or value "
                        "(column outputs are not in spec v1)")
    b = OutputParameterBuilder(name, _datafunctions_parameter_type(kind))
    b.DisplayName = name
    b.Description = ospec.get("description") or ""
    return b.Build()


def _datafunctions_check_parameter_names(dspec, engine):
    """Names are required and unique per direction. An input and an output may share a name
    (the shared-output pattern of the writing-spotfire-data-functions skill). Python parameters become script globals (warning only;
    TERR names may contain dots)."""
    for group in ("inputs", "outputs"):
        seen = set()
        for p in (dspec.get(group) or []):
            n = str(p.get("name") or "")
            if not n:
                raise Exception("every entry of " + group + " needs a name")
            if n in seen:
                raise Exception("duplicate " + group[:-1] + " name '" + n + "'")
            seen.add(n)
            if engine == "python" and (not _datafunctions_identifier.match(n)
                                       or n in _datafunctions_python_keywords):
                B.warn("data function '" + str(dspec.get("name")) + "': parameter '" + n + "' is not a "
                       "valid Python identifier, so the script cannot read or assign it")


def _datafunctions_parameter(params, name):
    """Registered InputParameter / OutputParameter by name (the definition has no indexer)."""
    for p in params:
        if p.Name == name:
            return p
    raise Exception("parameter '" + str(name) + "' is not registered on the definition")


# ---- inputs --------------------------------------------------------------------------
def _datafunctions_bind_input(df, dspec, ispec, state):
    """SetInput with the expression for the spec bind. Spotfire infers the input handler
    (persisted InputType) from the expression text and the parameter type; the report records
    the handler that the inference rules predict (expectedInputType)."""
    name = ispec["name"]
    kind = _datafunctions_kind(ispec)
    bind = _datafunctions_bind_of(ispec)
    if not bind:
        raise Exception("input '" + name + "' has no bind")
    param = _datafunctions_parameter(df.DataFunctionDefinition.InputParameters, name)
    allowed = _datafunctions_allowed_types(ispec)
    if kind == "table":
        expression, expected = _datafunctions_table_expression(bind, allowed)
    elif kind == "column":
        expression, expected = _datafunctions_column_expression(bind, allowed)
    elif kind == "value":
        expression, expected = _datafunctions_value_expression(dspec, ispec, bind, allowed)
    else:
        raise Exception("input '" + name + "': type must be table, column or value")
    active, selections = _datafunctions_limits(dspec, ispec, kind, bind)
    bound = _datafunctions_set_input(df, param, expression, active, selections)
    state[name] = {"param": param, "expression": expression, "active": active,
                   "selections": selections, "table": bind.get("table"), "allowed": allowed,
                   "wholeTable": expected == "Table"}
    return {"type": kind,
            "expression": bound.Expression if bound is not None else expression,
            "expectedInputType": expected,
            "activeFiltering": active,
            "limitBy": [s.Name for s in selections],
            "allowedTypes": allowed}


def _datafunctions_set_input(df, param, expression, active, selections):
    if active or selections:
        return df.Inputs.SetInput(param, expression, active, Array[DataSelection](selections))
    return df.Inputs.SetInput(param, expression)


def _datafunctions_table_expression(bind, allowed):
    """Whole table: Spotfire's own column-search template (InputType Table; columns added to the
    table later are passed too; Not yet tested #2). A list of columns: InputType Columns."""
    tname = bind.get("table")
    if not tname:
        raise Exception("table input needs bind.table")
    columns = bind.get("columns", "*")
    if columns is None or columns == "*":
        _datafunctions_check_table(tname, [], allowed)
        return _datafunctions_whole_table(tname), "Table"
    if isinstance(columns, str) or not isinstance(columns, (list, tuple)) or not columns:
        raise Exception("bind.columns must be \"*\" or a non-empty list of column names")
    _datafunctions_check_table(tname, columns, allowed)
    return _datafunctions_column_list(tname, columns), "Columns"


def _datafunctions_whole_table(tname):
    # The parser wants the same escaped table identifier in both places.
    return '$map("{0}.$esc($csearch({0},{1}))",",")'.format(
        esc(tname), ExpressionUtilities.EscapeStringLiteral("*"))


def _datafunctions_column_list(tname, columns):
    return ", ".join([esc(tname) + "." + esc(c) for c in columns])


def _datafunctions_column_expression(bind, allowed):
    tname = bind.get("table")
    cname = bind.get("column")
    if not tname or not cname:
        raise Exception("column input needs bind.table and bind.column")
    _datafunctions_check_table(tname, [cname], allowed)
    return esc(tname) + "." + esc(cname), "Column"     # always table-qualified


def _datafunctions_check_table(tname, columns, allowed):
    """Readable errors before binding. A table that does not exist yet is accepted only when a
    spec data function outputs it (one that is not executed at build)."""
    if not B.has_table(tname):
        if tname in _datafunctions_spec_output_tables():
            B.warn("binding to table '" + tname + "' before it exists (its data function has not "
                   "run); Not yet tested #18: the stored binding resolves once the table appears")
            return
        raise Exception("data table not found: " + tname)
    table = B.table(tname)
    allowed_names = _datafunctions_type_names(allowed)
    missing = []
    wrong = []
    for c in columns:
        found, col = table.Columns.TryGetValue(c)
        if not found:
            missing.append(c)
        elif col.DataType.Name not in allowed_names:
            wrong.append(c + " (" + col.DataType.Name + ")")
    if missing:
        raise Exception("column(s) not found in " + tname + ": " + ", ".join(missing))
    if wrong:
        B.warn("columns of " + tname + " with a type the parameter does not allow: " + ", ".join(wrong)
               + "; the run rejects them (add the type to dataTypes)")


def _datafunctions_type_names(type_names):
    return set([data_type(t).Name for t in type_names])


def _datafunctions_value_expression(dspec, ispec, bind, allowed):
    name = ispec["name"]
    if bind.get("property") is not None:
        pname = bind["property"]
        B.prop(pname)        # must exist now: the expression's name mapper resolves it at bind time
        if pname != name:
            B.warn("one name per binding: input '" + name + "' of '" + str(dspec.get("name"))
                   + "' is bound to property '" + pname + "'")
        _datafunctions_check_input_property_type(ispec, pname, allowed)
        expression = "DocumentProperty(" + ExpressionUtilities.EscapeStringLiteral(pname) + ")"
        return expression, "DocumentProperty"
    if bind.get("expression") is not None:
        # Spotfire expression, columns table-qualified, aggregated to one value
        return str(bind["expression"]), "Expression"
    if "value" in bind:
        return _datafunctions_literal(bind["value"], _datafunctions_explicit_types(ispec))
    raise Exception("value input '" + name + "' needs bind.property, bind.value or bind.expression")


def _datafunctions_check_input_property_type(ispec, pname, allowed):
    pspec = _datafunctions_spec_property(pname)
    if pspec is None:
        return
    ptype = pspec.get("type") or "String"
    if ptype not in allowed:
        B.warn("input '" + ispec["name"] + "' allows " + ", ".join(allowed) + " but property '"
               + pname + "' is " + ptype + ": the run rejects the value (add " + ptype
               + " to dataTypes)")


def _datafunctions_literal(value, type_names):
    """Constant as a Spotfire expression, culture-invariant. Returns (text, expected InputType).
    The literal type is the JSON value's own type when the parameter allows it, else the first
    listed dataType. String, Integer, Real and Boolean give literals (InputType Value; a negative
    number may parse as an expression, Not yet tested #17). Date, DateTime, Time and TimeSpan
    give constructor calls from integer parts (InputType Expression; Not yet tested #15)."""
    if value is None:
        raise Exception("bind.value null is not supported; bind a document property instead")
    if isinstance(value, (list, tuple, dict)):
        raise Exception("bind.value must be a single JSON value")
    natural = _datafunctions_natural_type(value)
    t = natural
    if type_names:
        t = natural if natural in type_names else type_names[0]
    if t == "String":
        return ExpressionUtilities.EscapeStringLiteral(str(value)), "Value"
    if t == "Boolean":
        return ("True" if _datafunctions_bool(value) else "False"), "Value"
    if t in ("Integer", "LongInteger"):
        # Not yet tested #16: an Integer literal accepted by a LongInteger-only parameter
        n = _datafunctions_integral(value)
        return str(n), ("Value|Expression" if n < 0 else "Value")
    if t in ("Real", "SingleReal", "Currency"):
        # Not yet tested #16: a Real literal accepted by a SingleReal- or Currency-only parameter
        text = _datafunctions_real_literal(value)
        return text, ("Value|Expression" if text.startswith("-") else "Value")
    if t == "Date":
        d = net_value("Date", value)
        return "Date(%d, %d, %d)" % (d.Year, d.Month, d.Day), "Expression"
    if t == "DateTime":
        d = net_value("DateTime", value)
        return ("DateTime(%d, %d, %d, %d, %d, %d, %d)" % (d.Year, d.Month, d.Day, d.Hour, d.Minute,
                                                          d.Second, d.Millisecond)), "Expression"
    if t == "Time":
        d = net_value("Time", value)
        return "Time(%d, %d, %d, %d)" % (d.Hour, d.Minute, d.Second, d.Millisecond), "Expression"
    if t == "TimeSpan":
        s = net_value("TimeSpan", value)
        return ("TimeSpan(%d, %d, %d, %d, %d)" % (s.Days, s.Hours, s.Minutes, s.Seconds,
                                                  s.Milliseconds)), "Expression"
    raise Exception("no literal form for data type " + str(t) + "; bind a document property instead")


def _datafunctions_natural_type(value):
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Integer" if -2147483648 <= value <= 2147483647 else "LongInteger"
    if isinstance(value, float):
        return "Real"
    return "String"


def _datafunctions_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise Exception("not a Boolean value: " + str(value))


def _datafunctions_integral(value):
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")) or value != int(value):
            raise Exception("not an integer value: " + repr(value))
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value).strip())


def _datafunctions_real_literal(value):
    """Plain decimal digits, '.' separator, never an exponent. repr() is culture-invariant
    (never the .NET locale format) and round-trips the double."""
    x = float(value)
    if x != x or x in (float("inf"), float("-inf")):
        raise Exception("not a finite number: " + str(value))
    s = repr(x)
    if "e" in s or "E" in s:
        s = _datafunctions_positional(s)
    if "." not in s:
        s += ".0"
    return s


def _datafunctions_positional(s):
    """Exponent form of a float repr as positional digits: '1.5e-05' -> '0.000015',
    '1e+16' -> '10000000000000000'."""
    sign = ""
    if s[:1] in ("-", "+"):
        sign = "-" if s[0] == "-" else ""
        s = s[1:]
    mantissa, exponent = s.lower().split("e")
    whole, _, frac = mantissa.partition(".")
    digits = whole + frac
    point = len(whole) + int(exponent)
    if point <= 0:
        text = "0." + "0" * (-point) + digits
    elif point >= len(digits):
        text = digits + "0" * (point - len(digits))
    else:
        text = digits[:point] + "." + digits[point:]
    if "." in text:
        ip, fp = text.split(".")
        ip = ip.lstrip("0") or "0"
        fp = fp.rstrip("0")
        text = ip + ("." + fp if fp else "")
    else:
        text = text.lstrip("0") or "0"
    return sign + text


def _datafunctions_limits(dspec, ispec, kind, bind):
    """(includeActiveFiltering, [DataSelection]) from limitByFiltering / limitByMarking.
    limitByFiltering: a filtering-scheme name, or true for the active filtering scheme.
    limitByMarking: a marking name. Property and literal binds cannot be limited. A scheme or
    marking that cannot be found becomes a manual step; the input is bound without it."""
    fn_name = str(dspec.get("name"))
    param_name = ispec["name"]
    target = fn_name + "/" + param_name
    flt = bind.get("limitByFiltering")
    mark = bind.get("limitByMarking")
    no_filter = flt is None or flt is False or flt == ""
    if no_filter and not mark:
        return False, []
    if kind == "value" and bind.get("expression") is None:
        B.warn("limits ignored on " + target + ": property and literal bindings cannot be limited")
        return False, []
    active = False
    selections = []
    if flt is True:
        active = True
    elif not no_filter:
        try:
            selections.append(_datafunctions_filtering_selection(str(flt)))
        except Exception as e:
            B.fallback("dataFunctions.limitByFiltering", target, exc_text(e),
                       _datafunctions_limit_manual(fn_name, param_name,
                                                   "Filtered rows, filtering scheme", str(flt)))
    if mark:
        if not isinstance(mark, str):
            raise Exception("limitByMarking must be a marking name")
        try:
            selections.append(B.marking(mark))
            if _datafunctions_flag(dspec, "executeAtBuild", True):
                B.warn(target + " receives only rows marked in '" + mark + "', and nothing is marked "
                       "during the build: the build-time run must cope with an empty input and still "
                       "return typed outputs")
        except Exception as e:
            B.fallback("dataFunctions.limitByMarking", target, exc_text(e),
                       _datafunctions_limit_manual(fn_name, param_name, "Marked rows, marking", mark))
    return active, selections


def _datafunctions_filtering_selection(name):
    """DataFilteringSelection of a spec filtering scheme (data_filtering_schemes ran before the data
    functions). SetInput takes the data-level selection; B.filtering_scheme (00_core) returns the
    document-level FilteringScheme, whose FilteringSelectionReference is that selection. Right after
    Filterings.Add the FilteringScheme may not exist yet (B.filtering_scheme raises; 20_data U2): the
    selection itself is then taken from Data.Filterings."""
    try:
        sel = B.filtering_scheme(name).FilteringSelectionReference
        if sel is not None:
            return sel
    except Exception:
        pass
    found, sel = B.doc.Data.Filterings.TryGetValue(name)
    if not found:
        raise Exception("filtering scheme not found: " + str(name))
    return sel


def _datafunctions_limit_manual(fn_name, param_name, what, name):
    return ("Data > Data function properties > select '" + fn_name + "' > Edit Parameters > Input > '"
            + param_name + "' > Limit by: " + what + " '" + name + "' > OK, then Refresh the function")


# ---- outputs -------------------------------------------------------------------------
def _datafunctions_bind_output(df, dspec, ospec):
    """Table output: replace the data of the existing table of that name (the name stays, never
    'X (2)'), otherwise a new table that the first run creates under the spec name.
    Value output: document property (created by the first run when it does not exist)."""
    name = ospec["name"]
    kind = _datafunctions_kind(ospec)
    target = ospec.get("target") or {}
    param = _datafunctions_parameter(df.DataFunctionDefinition.OutputParameters, name)
    if kind == "table":
        tname = target.get("table")
        if not tname:
            raise Exception("table output '" + name + "' needs target.table")
        if B.has_table(tname):
            if tname in _datafunctions_read_tables(dspec, [tname]):
                B.warn("'" + str(dspec.get("name")) + "' reads and replaces table '" + tname + "': a "
                       "circular dependency (Not yet tested #20: Spotfire may refuse it or loop on "
                       "automatic refresh)")
            df.Outputs.SetReplaceDataOutput(param, B.table(tname))
            return {"type": "table", "table": tname, "mode": "replace", "exists": True}
        df.Outputs.SetTableOutput(param, tname)    # suggested name; the first run creates the table
        return {"type": "table", "table": tname, "mode": "new", "exists": False}
    if kind == "value":
        pname = target.get("property")
        if not pname:
            raise Exception("value output '" + name + "' needs target.property")
        if pname != name:
            B.warn("one name per binding: output '" + name + "' of '" + str(dspec.get("name"))
                   + "' writes property '" + pname + "'")
        _datafunctions_check_output_property_type(dspec, pname)
        df.Outputs.SetDocumentPropertyOutput(param, pname)
        return {"type": "value", "property": pname, "exists": _datafunctions_has_property(pname)}
    raise Exception("output '" + name + "': type must be table or value")


def _datafunctions_check_output_property_type(dspec, pname):
    """A property output keeps one data type: a result whose type differs from the existing
    property's type is rejected. Python int exports as LongInteger, float as Real."""
    pspec = _datafunctions_spec_property(pname)
    if pspec is None or _datafunctions_engine_name(dspec) != "python":
        return
    fixes = {"Integer": ("int", "LongInteger", "numpy.int32"),
             "SingleReal": ("float", "Real", "numpy.float32")}
    t = pspec.get("type")
    if t in fixes:
        py_type, natural, numpy_type = fixes[t]
        B.warn("property '" + pname + "' is " + t + " but a Python " + py_type + " exports as "
               + natural + ": declare it " + natural + " or return " + numpy_type
               + " (Not yet tested #8)")


def _datafunctions_has_property(pname):
    return bool(B.doc.Data.Properties.ContainsProperty(DataPropertyClass.Document, pname))


# ---- execution and refresh ---------------------------------------------------------
def _datafunctions_execute_blocker(dspec, failed):
    """Reason not to run at build, or None. Never raises: df_build calls it outside B.step."""
    if failed:
        return str(failed) + " binding step(s) failed"
    try:
        for ispec in (dspec.get("inputs") or []):
            bind = _datafunctions_bind_of(ispec)
            if (_datafunctions_kind(ispec) in ("table", "column") and bind.get("table")
                    and not B.has_table(bind["table"])):
                return ("input table '" + str(bind["table"]) + "' does not exist (its data function is "
                        "not executed at build, or its build-time run failed)")
    except Exception as e:
        return "the input tables could not be checked: " + exc_text(e)
    return None


def _datafunctions_execute(df, dspec, record, state):
    """Run inline so output tables exist before visuals are built (Execute() would only queue the
    run until the script returns). If the run fails while whole-table inputs are bound, they are
    rebound once to explicit column lists and the run is repeated (aid for Not yet tested #2);
    if that fails too, the whole-table bindings are restored."""
    name = str(dspec.get("name"))
    problem = _datafunctions_run(df, dspec, record)
    if problem is None:
        return record["updatedDocument"]
    swapped = _datafunctions_rebind_explicit(df, dspec, record, state)
    if swapped:
        retry = _datafunctions_run(df, dspec, record)
        if retry is None:
            B.warn("'" + name + "' failed with whole-table inputs and ran after " + ", ".join(swapped)
                   + " were bound to explicit column lists (InputType Columns): Not yet tested #2 "
                   "failed, bind these inputs with bind.columns lists")
            return record["updatedDocument"]
        _datafunctions_restore_bindings(df, record, state, swapped)
        problem = retry + " (also failed with explicit column lists for " + ", ".join(swapped) + ")"
    raise Exception(problem)


def _datafunctions_run(df, dspec, record):
    """ExecuteSynchronously, then check every output. Returns None when the run worked, else the
    problem. ExecuteSynchronously never throws: it returns HasUpdatedDocument (False for a failed
    run and for a run that changed nothing). Not yet tested #3: a never-run function creates its
    new output table here."""
    name = str(dspec.get("name"))
    updated = bool(df.ExecuteSynchronously())
    stale = bool(df.NeedsRefresh)
    record["executed"] = True
    record["updatedDocument"] = updated
    record["needsRefresh"] = stale
    missing = []
    for ospec in (dspec.get("outputs") or []):
        out = record["outputs"].get(str(ospec.get("name")))
        if out is None:
            continue
        if out["type"] == "table":
            table = _datafunctions_output_table(df, ospec["name"], out["table"])
            out["exists"] = table is not None
            if table is None:
                missing.append("table " + out["table"])
            else:
                out["rows"] = table.RowCount
                out["columns"] = table.Columns.Count
                _datafunctions_record_table(name, ospec["name"], table, out["mode"])
        else:
            out["exists"] = _datafunctions_has_property(out["property"])
            if not out["exists"]:
                missing.append("property " + out["property"])
    if missing:
        return ("'" + name + "' did not produce " + ", ".join(missing) + " (ExecuteSynchronously "
                "returned " + str(updated) + ")." + _datafunctions_error_hint)
    if not updated and stale:
        # Pre-existing outputs (replaced tables, properties) exist even after a failed run.
        return ("'" + name + "': ExecuteSynchronously returned False and the function still needs a "
                "refresh, so the run most likely failed (Not yet tested #14: NeedsRefresh after a "
                "failed run)." + _datafunctions_error_hint)
    return None


def _datafunctions_rebind_explicit(df, dspec, record, state):
    """Whole-table inputs -> explicit lists of the table's columns whose type the parameter allows
    (spec hierarchies left out). Returns the input names that were rebound."""
    swapped = []
    for ispec in (dspec.get("inputs") or []):
        iname = str(ispec.get("name"))
        st = state.get(iname)
        if st is None or not st["wholeTable"] or not B.has_table(st["table"]):
            continue
        columns = _datafunctions_explicit_columns(st["table"], st["allowed"])
        if not columns:
            continue
        expression = _datafunctions_column_list(st["table"], columns)
        _datafunctions_set_input(df, st["param"], expression, st["active"], st["selections"])
        entry = record["inputs"].get(iname)
        if entry is not None:
            entry["expression"] = expression
            entry["expectedInputType"] = "Columns"
            entry["wholeTableRetry"] = True
        swapped.append(iname)
    return swapped


def _datafunctions_restore_bindings(df, record, state, names):
    for iname in names:
        st = state[iname]
        _datafunctions_set_input(df, st["param"], st["expression"], st["active"], st["selections"])
        entry = record["inputs"].get(iname)
        if entry is not None:
            entry["expression"] = st["expression"]
            entry["expectedInputType"] = "Table"
            entry.pop("wholeTableRetry", None)


def _datafunctions_explicit_columns(tname, allowed):
    table = B.table(tname)
    allowed_names = _datafunctions_type_names(allowed)
    hierarchies = set()
    for tspec in (B.spec.get("tables") or []):
        if tspec.get("name") == tname:
            for h in (tspec.get("hierarchies") or []):
                hierarchies.add(h.get("name"))
    names = []
    for col in table.Columns:
        if col.Name not in hierarchies and col.DataType.Name in allowed_names:
            names.append(col.Name)
    return names


def _datafunctions_output_table(df, param_name, tname):
    """Table behind a table output after the run, renamed to the spec name if Spotfire made the
    suggested name unique."""
    param = _datafunctions_parameter(df.DataFunctionDefinition.OutputParameters, param_name)
    found, mapping = df.Outputs.TryGetValue(param)
    table = None
    if found and mapping is not None:
        table = mapping.DataTableReference      # TableOutput / ReplaceDataOutput; None before a run
    if table is None and B.has_table(tname):
        table = B.table(tname)                  # Not yet tested #13: reference not refreshed yet
    if table is not None and table.Name != tname:
        try:
            table.Name = tname
        except Exception as e:
            B.warn("output '" + param_name + "' produced table '" + table.Name
                   + "', which could not be renamed to '" + tname + "': " + exc_text(e))
    return table


def _datafunctions_record_table(fn_name, param_name, table, mode):
    """created.tables entry. A replaced table (file table or earlier output) keeps its source."""
    entry = B.created["tables"].get(table.Name)
    if not isinstance(entry, dict):
        entry = {}
    if mode == "new":
        entry.update({"source": "dataFunction", "function": fn_name, "output": param_name,
                      "id": str(table.Id)})
    else:
        entry["replacedBy"] = fn_name + "/" + param_name
    entry["rows"] = table.RowCount
    entry["columns"] = table.Columns.Count
    B.created["tables"][table.Name] = entry


def _datafunctions_warn_unrun_outputs(fn_name, record):
    for pname in sorted(record["outputs"].keys()):
        out = record["outputs"][pname]
        if not out.get("exists"):
            if out["type"] == "table":
                what = "table '" + out["table"] + "'"
            else:
                what = "property '" + out["property"] + "'"
            B.warn("'" + fn_name + "' is not executed at build: " + what
                   + " exists only after its first run")


def _datafunctions_set_refresh(df, dspec, record):
    """automatic: Spotfire re-runs the function whenever an input changes (property value,
    filtering, marking, input data). Set after the build-time run: switching Manual (the default
    of a new function) to Automatic also queues one asynchronous Execute() that starts after the
    builder returns (Not yet tested #4: it may still run while the queued save starts)."""
    name = str(dspec.get("name"))
    mode = str(dspec.get("refresh") or "automatic").lower()
    if mode == "automatic":
        wanted = DataFunctionUpdateBehavior.Automatic
    elif mode == "manual":
        wanted = DataFunctionUpdateBehavior.Manual
    else:
        raise Exception("refresh must be automatic or manual, not '" + mode + "'")
    if df.UpdateBehavior != wanted:
        df.UpdateBehavior = wanted
        if mode == "automatic" and not record["executeAtBuild"]:
            B.warn("'" + name + "' is not executed at build but refreshes automatically: the switch to "
                   "automatic queues one run that starts after the builder script ends")
    record["refresh"] = mode
    return mode


# ---- spec helpers -------------------------------------------------------------------
def _datafunctions_bind_of(ispec):
    bind = ispec.get("bind")
    return bind if isinstance(bind, dict) else {}


def _datafunctions_flag(dspec, key, default):
    value = dspec.get(key)
    return default if value is None else bool(value)


def _datafunctions_safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _datafunctions_spec_property(pname):
    """Spec entry of a document property (case-insensitive like Spotfire), or None.
    DataProperty.DataType is internal, so the declared type is read from the spec."""
    low = str(pname).lower()
    for p in (B.spec.get("properties") or []):
        if str(p.get("name", "")).lower() == low:
            return p
    return None


def _datafunctions_spec_output_tables():
    names = set()
    for d in (B.spec.get("dataFunctions") or []):
        names.update(_datafunctions_output_table_names(d))
    return names
