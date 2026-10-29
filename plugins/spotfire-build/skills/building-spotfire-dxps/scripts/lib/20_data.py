# ============================================================================
# 20_data.py - document properties, file-based data tables (SBDF / CSV) with
# forced embedding, table and column metadata (descriptions, number formats,
# calculated columns, hierarchies), relations, markings and filtering schemes.
# IronPython 3.4 inside Spotfire Analyst 15.0. Public API only: no reflection,
# no internal members. Every Spotfire member used is listed in
# lib/20_data.members.txt (assigned ones in lib/20_data.set.txt) and was checked
# with scripts/sfapi.py. Facts, pitfalls and Not yet tested items:
# references/api-data.md.
# Requires newer than 14.6: none (newest member used:
#   DataTableCollection.Add(String, DataSource, Boolean) [api 10.1.0]).
# ============================================================================
from System import String, Int32, Int64, Double, Single, Decimal, Boolean, DateTime, TimeSpan
from System.IO import File
from System.Text import Encoding
from System.Collections.Generic import List
from Spotfire.Dxp.Data import (DataProperty, DataPropertyAttributes, DataPropertyClass, NameString,
                               DataTableSaveSettings, CalculatedColumn, HierarchyColumn,
                               HierarchyDefinition, HierarchyNestingMode)
from Spotfire.Dxp.Data.Import import SbdfFileDataSource, TextFileDataSource, TextDataReaderSettings
from Spotfire.Dxp.Data.Formatters import NumberFormatter, DateTimeFormatter

_data_file_sources = ("sbdf", "csv")

# .NET element type of a list-valued property per Spotfire DataType (DataType.RepresentationType).
_data_list_element = {
    "String": String, "Integer": Int32, "LongInteger": Int64, "Real": Double,
    "SingleReal": Single, "Currency": Decimal, "Boolean": Boolean,
    "Date": DateTime, "DateTime": DateTime, "Time": DateTime, "TimeSpan": TimeSpan,
}

# CSV encodings by name -> code page (other names go through System.Text.Encoding).
_data_code_pages = {
    "utf-8": 65001, "utf8": 65001, "utf-8-sig": 65001,
    "utf-16": 1200, "utf-16le": 1200, "unicode": 1200, "utf-16be": 1201,
    "latin-1": 28591, "latin1": 28591, "iso-8859-1": 28591,
    "cp1252": 1252, "windows-1252": 1252, "ascii": 20127, "us-ascii": 20127,
}


# ---- shared lookups -------------------------------------------------------------
def _data_column(table, column_name):
    found, col = table.Columns.TryGetValue(column_name)
    if not found:
        raise Exception("column '" + str(column_name) + "' not found in table " + table.Name)
    return col


def _data_table_record(name):
    """The report entry B.created["tables"][name] (created on demand)."""
    rec = B.created["tables"].get(name)
    if rec is None:
        rec = {}
        B.created["tables"][name] = rec
    if not isinstance(rec, dict):
        return {}
    return rec


def _data_is_embedded(tspec):
    return tspec.get("embed", True) is not False


def _data_file_tables(tables):
    """Spec entries whose source is a file (sbdf / csv)."""
    return [t for t in tables or [] if (t.get("source") or {}).get("type") in _data_file_sources]


# ============================================================================
# Document properties
# ============================================================================
def data_add_properties(properties):
    """Create every document property of spec "properties" (one step each).

    Created like Analyst's own UI: CreateCustomPrototype(name, description, value, type,
    DefaultAttributes | IsPropagated [| IsListValued]) = attributes 78 (94 for list properties).
    Idempotent: an existing property (names are case-insensitive) keeps its value.
    """
    made = {}
    for pspec in properties or []:
        name = pspec.get("name")
        prop = B.step("property", name, _data_add_property, (pspec,))
        if prop is not None:
            made[name] = prop
    return made


def _data_typed_list(type_name, values):
    # CreateCustomPrototype stores a list-valued default as given (no conversion), so pass the
    # typed List<T> Spotfire itself stores (the standard Keywords property persists as
    # List<String>). Elements come from net_value, so each has the exact representation type.
    element = _data_list_element.get(type_name)
    if element is None:
        raise Exception("list-valued properties of type " + str(type_name) + " are not supported")
    if not isinstance(values, (list, tuple)):
        values = [values]
    items = List[element]()
    for v in values:
        items.Add(net_value(type_name, v))
    return items


def _data_property_value(type_name, value, list_valued):
    """Spec default -> the exact .NET value (None when the spec gives no default)."""
    if value is None:
        return None
    if list_valued:
        return _data_typed_list(type_name, value)
    if type_name == "Time" and isinstance(value, str):
        # Spotfire parses a String value with the Time type's own formatter (IL TryConvertValue), so
        # the stored DateTime gets Spotfire's date part instead of the build date that
        # DateTime.Parse("06:00:00") would give. _data_create_property falls back to net_value.
        # Not yet tested: the property persists the time with Spotfire's base date (data U15).
        return value
    return net_value(type_name, value)   # Real 72 -> Double 72.0; no numeric widening in Spotfire


def _data_create_property(name, description, value, dtype, attrs, type_name, default):
    try:
        return DataProperty.CreateCustomPrototype(name, description, value, dtype, attrs)
    except Exception:
        if not (type_name == "Time" and isinstance(value, str)):
            raise
        B.warn("property " + name + ": Spotfire did not parse the Time text " + repr(value)
               + "; stored it with today's date instead")
        return DataProperty.CreateCustomPrototype(name, description, net_value(type_name, default),
                                                  dtype, attrs)


def _data_add_property(pspec):
    name = pspec["name"]
    type_name = pspec.get("type") or "String"
    list_valued = bool(pspec.get("listValued", False))
    default = pspec.get("default")
    NameString.ValidateCustomPropertyName(name)   # letters/digits, dot-separated, not "spotfire."
    registry = B.doc.Data.Properties
    found, prop = registry.TryGetProperty(DataPropertyClass.Document, name)
    if found:
        # Never clobber a value the document already holds; only an empty one gets the default.
        if bool(prop.IsListValued) != list_valued:
            B.warn("property " + name + " already exists with listValued=" + str(bool(prop.IsListValued))
                   + "; left unchanged (remove it and rebuild to apply the spec)")
        if (prop.Description or "") != (pspec.get("description") or ""):
            B.warn("property " + name + " already exists with another description; descriptions are "
                   "creation-time only (remove the property and rebuild to change it)")
        filled = False
        if prop.Value is None and default is not None:
            value = _data_property_value(type_name, default, bool(prop.IsListValued))
            try:
                prop.Value = value
            except Exception:
                if not (type_name == "Time" and isinstance(value, str)):
                    raise
                prop.Value = net_value(type_name, default)
            filled = True
        B.created["properties"][name] = {"type": type_name, "listValued": bool(prop.IsListValued),
                                         "existed": True, "defaultFilled": filled}
        return prop
    dtype = data_type(type_name)
    attrs = DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated
    if list_valued:
        attrs = attrs | DataPropertyAttributes.IsListValued
    value = _data_property_value(type_name, default, list_valued)
    if value is None:
        value = dtype.DefaultValue   # exactly what the 3-argument CreateCustomPrototype passes
    # Description is creation-time only (DataProperty.Description has no setter).
    proto = _data_create_property(name, pspec.get("description") or "", value, dtype, attrs, type_name, default)
    registry.AddProperty(DataPropertyClass.Document, proto)
    prop = B.prop(name)
    B.created["properties"][name] = {"type": type_name, "listValued": list_valued, "existed": False,
                                     "defaultFilled": default is not None}
    return prop


# ============================================================================
# File-based tables: load, embed, default table
# ============================================================================
def data_load_tables(tables):
    """Load every sbdf/csv table of spec "tables", force embedding, apply its metadata, set the
    default table.

    Metadata (description, calculated columns, hierarchies, column descriptions/formats) of a file
    table is applied right after it loads (ARCHITECTURE build order step 3), so data-function inputs
    bound later see its calculated columns. dataFunction-sourced entries are skipped here: their
    function creates the table and data_table_metadata applies their metadata after df_build_all.
    """
    loaded = {}
    first = None
    for tspec in tables or []:
        name = tspec.get("name")
        source = tspec.get("source") or {}
        stype = source.get("type")
        if stype == "dataFunction":
            B.skip("load", name, "created by data function '" + str(source.get("function"))
                   + "'; metadata is applied after it runs")
            continue
        table = B.step("load", name, _data_load_table, (tspec,))
        if table is None:
            continue
        loaded[name] = table
        if first is None:
            first = name
        embed = _data_is_embedded(tspec)
        B.step("embed", name, _data_set_embedding, (table, embed), fallback=_data_embed_manual(name, embed))
        if stype == "csv" and source.get("columns"):
            B.step("columnTypes", name, _data_check_column_types, (table, source.get("columns")))
        _data_apply_metadata(table, tspec)
    wanted = B.spec.get("defaultTable") or first
    if wanted and B.has_table(wanted):
        # A data-function table named as defaultTable does not exist yet: data_table_metadata sets it.
        B.step("defaultTable", wanted, _data_set_default_table, (wanted,))
    return loaded


def _data_load_table(tspec):
    name = tspec["name"]
    source = tspec.get("source") or {}
    stype = source.get("type")
    if stype not in _data_file_sources:
        raise Exception("unsupported table source type: " + str(stype))
    path = B.path(source.get("path"))
    if not path or not File.Exists(path):
        raise Exception("data file not found: " + str(path))
    if stype == "sbdf":
        ds = SbdfFileDataSource(path)
    else:
        ds = TextFileDataSource(path, _data_csv_settings(source))   # there is no (String) overload
    ds.IsPromptingAllowed = False   # never open an import dialog during the build
    found, table = B.doc.Data.Tables.TryGetValue(name)
    if found:
        table.ReplaceData(ds)   # re-run: keeps the table identity (Id, bindings)
    else:
        # 3-argument overload: the 2-argument one takes autoCreateFilters from a user preference.
        table = B.doc.Data.Tables.Add(name, ds, True)
    if table.Name != name:
        B.warn("table '" + name + "' was stored as '" + table.Name + "'; later lookups by the spec name fail")
    # Not yet tested: Tables.Add loads synchronously inside a script (RowCount and Columns are
    # final right after Add); existing analysis scripts rely on it.
    rec = _data_table_record(name)
    rec["source"] = stype
    rec["path"] = path
    rec["rows"] = table.RowCount
    rec["columns"] = table.Columns.Count
    rec["id"] = str(table.Id)
    rec["replaced"] = found
    return table


def _data_code_page(encoding):
    key = str(encoding or "utf-8").strip().lower().replace("_", "-")
    if key in _data_code_pages:
        return _data_code_pages[key]
    return Encoding.GetEncoding(key).CodePage


def _data_csv_settings(source):
    """TextDataReaderSettings with every heuristic pinned (the defaults are ';', no header row,
    guessed culture and BOM-or-ANSI encoding)."""
    settings = TextDataReaderSettings()
    settings.Separator = source.get("separator") or ","
    if source.get("header", True) is not False:
        settings.AddColumnNameRow(0)
    settings.CultureName = source.get("culture") or "en-US"
    settings.CodePage = _data_code_page(source.get("encoding"))
    columns = source.get("columns") or {}
    for column_name in columns:
        # The TextDataReader applies these by detected (unique) header name after its type
        # heuristics, through SetDataType(i, type) - i.e. as persisted types (IL, TypesRow < 0).
        # With header false the keys must be Spotfire's generated names ("Column {0}" pattern).
        settings.DataTypesGivenName[column_name] = data_type(columns[column_name])
    return settings


def _data_check_column_types(table, columns):
    """CSV: every column listed in source.columns must exist with exactly that type."""
    problems = []
    for column_name in sorted(columns.keys()):
        found, col = table.Columns.TryGetValue(column_name)
        if not found:
            problems.append(column_name + ": not in the file")
            continue
        expected = data_type(columns[column_name]).Name
        if col.DataType.Name != expected:
            problems.append(column_name + ": " + col.DataType.Name + " instead of " + expected)
    if problems:
        raise Exception("CSV column types differ from the spec: " + "; ".join(problems))
    return len(columns)


def _data_set_embedding(table, embed):
    """Per-table save setting. embed=True stores the data inside the DXP (no link to the file)."""
    use_linked = not embed
    settings = B.doc.Data.SaveSettings   # the live object held by the data manager
    found, entry = settings.TryGetDataTableSettings(table.Id)
    if found:
        # Update in place: with a duplicate entry the runtime lookup (first match) and the save
        # merge (last match) disagree.
        entry.UseLinkedData = use_linked
    else:
        settings.DataTableSettings.Add(DataTableSaveSettings(table, use_linked, False))
    found, entry = B.doc.Data.SaveSettings.TryGetDataTableSettings(table.Id)
    if not found or bool(entry.UseLinkedData) != use_linked:
        raise Exception("the save setting of table " + table.Name + " did not stick")
    if not embed:
        B.warn("table " + table.Name + " is linked to its source file (embed: false); "
               "linked tables are not allowed in a delivered analysis")
    _data_table_record(table.Name)["embedded"] = embed
    return entry


def _data_embed_manual(name, embed):
    if embed:
        return ("Store table '" + name + "' embedded in the analysis, not linked to its source file: "
                "choose 'Embedded in analysis' for it in the embedded/linked data options when saving "
                "(File > Save As), then save again")
    return "Keep table '" + name + "' linked to its source file in the embedded/linked data options when saving"


def _data_set_default_table(name):
    table = B.table(name)
    B.doc.Data.Tables.DefaultTableReference = table   # new visuals bind to it (AutoConfigure)
    return table


def _data_wanted_default_table(tables):
    """spec.defaultTable, else the first file table that exists, else the first table that exists."""
    named = B.spec.get("defaultTable")
    if named:
        return named
    fallback = None
    for tspec in tables or []:
        name = tspec.get("name")
        if not name or not B.has_table(name):
            continue
        if (tspec.get("source") or {}).get("type") in _data_file_sources:
            return name
        if fallback is None:
            fallback = name
    return fallback


# ============================================================================
# Table metadata (file and data-function tables), after df_build_all
# ============================================================================
def data_table_metadata(tables):
    """Description, calculated columns, hierarchies and column descriptions/formats/settings of
    every table in spec "tables" not handled yet (data-function tables; file tables whose metadata
    data_load_tables already applied are skipped), then the embedding re-check and the default table."""
    for tspec in tables or []:
        name = tspec.get("name")
        if not name or not B.has_table(name):
            B.skip("metadata", name, "table does not exist (its load or data function failed, "
                   "or the function does not run at build)")
            continue
        table = B.table(name)
        rec = _data_table_record(name)
        if rec.get("metadataStage"):
            continue   # file table: applied right after loading
        if "source" not in rec:
            rec["source"] = (tspec.get("source") or {}).get("type")
            rec["id"] = str(table.Id)
        # Not yet tested: on a data-function output table, the description, calculated columns,
        # hierarchies and column descriptions/formats survive the function's next run.
        _data_apply_metadata(table, tspec)
    if [t for t in _data_file_tables(tables) if B.has_table(t.get("name"))]:
        B.step("embedCheck", "tables", _data_recheck_embedding, (tables,),
               fallback="Check the embedded/linked data options when saving (File > Save As): every "
                        "table loaded from a file must be embedded in the analysis")
    wanted = _data_wanted_default_table(tables)
    if wanted:
        current = B.doc.Data.Tables.DefaultTableReference
        if current is None or current.Name != wanted:
            B.step("defaultTable", wanted, _data_set_default_table, (wanted,))


def _data_apply_metadata(table, tspec):
    """One step per item, in dependency order: description, calculated columns (spec order, later
    ones may use earlier ones), hierarchies, column metadata (may target calculated or hierarchy
    columns), table settings."""
    name = tspec.get("name")
    if tspec.get("description"):
        B.step("description", name, _data_table_description, (table, tspec["description"]))
    for cspec in tspec.get("calculatedColumns") or []:
        B.step("calculatedColumn", name + "/" + str(cspec.get("name")), _data_calculated_column,
               (table, cspec))
    for hspec in tspec.get("hierarchies") or []:
        B.step("hierarchy", name + "/" + str(hspec.get("name")), _data_hierarchy, (table, hspec))
    columns = tspec.get("columns") or {}
    for column_name in sorted(columns.keys()):
        _data_column_metadata(table, column_name, columns[column_name] or {})
    if tspec.get("settings"):
        B.step("settings", name, apply_settings, (table, tspec["settings"]))
    _data_table_record(name)["metadataStage"] = B.group


def _data_table_description(table, text):
    # Standard table property "Description" (no public constant for tables); persisted as
    # DataTable > DataPropertyContainer > ListenableProperties["description"].AssignedValue.
    table.Properties.SetProperty("Description", text)
    return text


def _data_calculated_column(table, cspec):
    name = cspec["name"]
    expression = cspec["expression"]
    found, col = table.Columns.TryGetValue(name)
    if found:
        try:
            calc = col.As[CalculatedColumn]()
        except Exception:
            raise Exception("column '" + name + "' already exists in " + table.Name
                            + " and is not a calculated column")
        if calc.Expression != expression:
            calc.Expression = expression
    else:
        # Invalid expression -> ExpressionException; duplicate/invalid name -> ArgumentException.
        col = table.Columns.AddCalculatedColumn(name, expression)
    if not col.IsValid:
        raise Exception("calculated column '" + name + "' is not valid: " + expression)
    if cspec.get("description"):
        col.Properties.Description = cspec["description"]
    rec = _data_table_record(table.Name)
    if name not in rec.setdefault("calculatedColumns", []):
        rec["calculatedColumns"].append(name)
    return col


def _data_hierarchy(table, hspec):
    name = hspec["name"]
    levels = List[String]()
    for level in hspec.get("levels") or []:
        levels.Add(esc(level))   # each level is a column expression: [Pump ID]
    if levels.Count == 0:
        raise Exception("hierarchy '" + name + "' has no levels")
    definition = HierarchyDefinition(HierarchyNestingMode.Nested, levels)   # bad level -> ArgumentException
    found, col = table.Columns.TryGetValue(name)
    if found:
        try:
            hcol = col.As[HierarchyColumn]()
        except Exception:
            raise Exception("column '" + name + "' already exists in " + table.Name + " and is not a hierarchy")
        hcol.HierarchyDefinition = definition
    else:
        col = table.Columns.AddHierarchyColumn(name, definition)
    rec = _data_table_record(table.Name)
    if name not in rec.setdefault("hierarchies", []):
        rec["hierarchies"].append(name)
    return col


def _data_column_metadata(table, column_name, cspec):
    target = table.Name + "/" + column_name
    if cspec.get("description"):
        B.step("columnDescription", target, _data_column_description, (table, column_name, cspec["description"]))
    if cspec.get("format"):
        B.step("columnFormat", target, _data_column_format, (table, column_name, cspec["format"]),
               fallback="Set the format of column '" + column_name + "' in table '" + table.Name
                        + "' to the custom format '" + cspec["format"] + "' (Column properties > Formatting)")
    if cspec.get("settings"):
        B.step("columnSettings", target, _data_column_settings, (table, column_name, cspec["settings"]))


def _data_column_description(table, column_name, text):
    _data_column(table, column_name).Properties.Description = text
    return text


def _data_column_format(table, column_name, format_string):
    """Custom .NET format string on a numeric or date/time column (a new formatter is assigned;
    the formatter returned by Properties.Formatter is read-only)."""
    col = _data_column(table, column_name)
    formatter = col.DataType.CreateLocalizedFormatter()   # writable clone of the type's formatter
    if not (isinstance(formatter, NumberFormatter) or isinstance(formatter, DateTimeFormatter)):
        raise Exception("a format string is not supported for " + col.DataType.Name + " columns")
    # Not yet tested: assigning a member declared on the public base class works although the
    # runtime type is internal (RealNumberFormatter, IntNumberFormatter, ...).
    # NumberFormatter: the setter switches Category to Custom; persisted as FormatStringV40.
    formatter.FormatString = format_string
    col.Properties.Formatter = formatter   # stores a read-only clone; type-checked against the column
    # Not yet tested: visuals that aggregate the column (Sum/Avg measures of cross tables, KPI values,
    # chart axes and labels) show this format by default; the builder sets no visual-level formatters.
    return format_string


def _data_column_settings(table, column_name, settings):
    apply_settings(_data_column(table, column_name), settings)
    return settings


def _data_recheck_embedding(tables):
    """Safety net: re-apply any per-table embedding entry that changed while data functions ran."""
    reapplied = []
    for tspec in _data_file_tables(tables):
        name = tspec.get("name")
        if not B.has_table(name):
            continue
        embed = _data_is_embedded(tspec)
        table = B.table(name)
        found, entry = B.doc.Data.SaveSettings.TryGetDataTableSettings(table.Id)
        if not found or bool(entry.UseLinkedData) == embed:
            _data_set_embedding(table, embed)
            reapplied.append(name)
    if reapplied:
        B.warn("embedding save settings were missing or changed after loading and were re-applied for: "
               + ", ".join(reapplied))
    return reapplied


# ============================================================================
# Relations
# ============================================================================
def data_relations(relations):
    """Relate tables (spec "relations"): one relation per table pair, keys joined with 'and'."""
    made = []
    for rspec in relations or []:
        target = str(rspec.get("left")) + " -> " + str(rspec.get("right"))
        rel = B.step("relation", target, _data_add_relation, (rspec,))
        if rel is not None:
            made.append(rel)
    return made


def _data_relation_expression(left, right, pairs):
    parts = []
    for pair in pairs:
        if len(pair) != 2:
            raise Exception("relation 'on' items must be [leftColumn, rightColumn] pairs")
        _data_column(left, pair[0])    # clear error instead of Spotfire's "Invalid relation."
        _data_column(right, pair[1])
        parts.append(left.NameEscapedForExpression + "." + esc(pair[0]) + "="
                     + right.NameEscapedForExpression + "." + esc(pair[1]))
    return " and ".join(parts)


def _data_add_relation(rspec):
    left = B.table(rspec["left"])
    right = B.table(rspec["right"])
    pairs = rspec.get("on") or []
    if not pairs:
        raise Exception("relation needs at least one [leftColumn, rightColumn] pair in 'on'")
    expression = _data_relation_expression(left, right, pairs)
    relations = B.doc.Data.Relations
    rel = relations.FindRelation(left, right)   # None when the two tables are not related
    existed = rel is not None
    if existed:
        if rel.Expression != expression:
            B.warn("tables " + left.Name + " and " + right.Name + " are already related by "
                   + rel.Expression + "; left unchanged")
    else:
        # Invalid expression -> ExpressionException; already related / cyclic -> ArgumentException.
        rel = relations.Add(left, right, expression)
    if not rel.IsValid:
        raise Exception("relation is not valid: " + rel.Expression)
    B.created["relations"].append({"left": left.Name, "right": right.Name, "expression": rel.Expression,
                                   "existed": existed})
    return rel


# ============================================================================
# Markings
# ============================================================================
def data_markings(markings):
    """Markings of spec "markings". The default marking reuses (renames) the document's built-in
    marking when the document has only that one; it becomes Markings.DefaultMarkingReference,
    which new visuals pick up. With no markings the built-in one is kept, named "Marking"."""
    made = {}
    if not markings:
        mk = B.step("marking", "Marking", _data_builtin_marking, ())
        if mk is not None:
            made["Marking"] = mk
        return made
    primary = None
    for mspec in markings:
        if mspec.get("default"):
            if primary is None:
                primary = mspec
            else:
                B.warn("more than one marking has default: true; '" + str(primary.get("name"))
                       + "' is the default")
    if primary is None:
        primary = markings[0]
        if len(markings) > 1:
            B.warn("no marking has default: true; '" + str(primary.get("name")) + "' becomes the default marking")
    names = [m.get("name") for m in markings]
    ordered = [primary] + [m for m in markings if m is not primary]   # default first: it may rename the built-in
    for mspec in ordered:
        mk = B.step("marking", mspec.get("name"), _data_add_marking, (mspec, mspec is primary, names))
        if mk is not None:
            made[mspec.get("name")] = mk
    return made


def _data_add_marking(mspec, is_default, spec_names):
    markings = B.doc.Data.Markings
    name = mspec["name"]
    hex_color = mspec.get("color")
    found, mk = markings.TryGetValue(name)
    reused = False
    if not found:
        builtin = markings.DefaultMarkingReference
        if (is_default and builtin is not None and markings.Count == 1
                and builtin.Name not in spec_names):
            builtin.Name = name   # fresh document: rename the built-in (localized) default marking
            mk = builtin
            reused = True
        else:
            mk = markings.Add(name)   # API-created markings start black
            if not hex_color:
                B.warn("marking " + name + " has no color; Spotfire gives API-created markings black")
    if hex_color:
        mk.Color = color(hex_color)
    if is_default:
        markings.DefaultMarkingReference = mk
    B.created["markings"][name] = {"color": hex_color, "default": is_default, "reusedBuiltIn": reused}
    return mk


def _data_builtin_marking():
    markings = B.doc.Data.Markings
    found, mk = markings.TryGetValue("Marking")
    if not found:
        mk = markings.DefaultMarkingReference
        if mk is not None and markings.Count == 1:
            mk.Name = "Marking"   # the built-in name is localized ("Marking" only in English)
        else:
            mk = markings.Add("Marking")
    markings.DefaultMarkingReference = mk
    B.created["markings"]["Marking"] = {"color": None, "default": True, "reusedBuiltIn": True}
    return mk


# ============================================================================
# Filtering schemes
# ============================================================================
def data_filtering_schemes(schemes):
    """Named filtering schemes (spec "filteringSchemes"). The document's default scheme always
    exists and cannot be switched (DefaultFilteringReference is read-only), so default: true
    renames the built-in default scheme to that name."""
    made = {}
    names = [s.get("name") for s in schemes or []]
    default_taken = False
    for sspec in schemes or []:
        is_default = bool(sspec.get("default"))
        if is_default and default_taken:
            B.warn("more than one filtering scheme has default: true; '" + str(sspec.get("name"))
                   + "' is added as a named scheme")
            is_default = False
        if is_default:
            default_taken = True
        sel = B.step("filteringScheme", sspec.get("name"), _data_add_filtering_scheme, (sspec, is_default, names))
        if sel is not None:
            made[sspec.get("name")] = sel
    return made


def _data_add_filtering_scheme(sspec, is_default, spec_names):
    filterings = B.doc.Data.Filterings
    name = sspec["name"]
    builtin = filterings.DefaultFilteringReference
    found, sel = filterings.TryGetValue(name)
    renamed = False
    if not found:
        if is_default and builtin is not None and builtin.Name not in spec_names:
            builtin.Name = name   # the default scheme carries the spec name
            sel = builtin
            renamed = True
        else:
            if is_default:
                B.warn("filtering scheme " + name + " cannot become the default: the default scheme is named "
                       + str(builtin.Name if builtin is not None else None) + ", another spec scheme")
            sel = filterings.Add(name)   # its FilteringScheme is created by an internal event handler
    elif is_default and not sel.Equals(builtin):
        B.warn("filtering scheme " + name + " already exists and is not the default scheme; "
               "the default cannot be switched through the API")
    scheme = _core_scheme_for(sel)
    if scheme is None:
        # Not yet tested: Document.FilteringSchemes[selection] may stay None until the script's
        # transaction ends; pages assigning this scheme would then fail.
        B.warn("filtering scheme " + name + " has no FilteringScheme yet; pages using it may fail")
    B.created["filteringSchemes"][name] = {"default": bool(builtin is not None and sel.Equals(builtin)),
                                           "renamedDefault": renamed, "schemeReady": scheme is not None}
    return sel


def data_filtering_scheme(name):
    """FilteringScheme for a spec filtering-scheme name; None or "" = the document's default scheme.
    Kept for 30_datafunctions; the lookup itself is B.filtering_scheme (00_core)."""
    return B.filtering_scheme(name)
