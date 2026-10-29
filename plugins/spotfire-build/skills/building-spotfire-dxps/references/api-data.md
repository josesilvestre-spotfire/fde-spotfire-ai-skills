# API reference: document properties, data tables, metadata, relations, markings, filtering schemes

Owner: `scripts/lib/20_data.py` (the library of the slim and full tiers). The standard engine
(`scripts/engine/core.py` and the feature parts `properties`, `markings`, `pathfree`) uses the same
calls for properties, loading, embedding, column formats and markings.
Spotfire Analyst 15.0 (core build 71.0.22206.3863), IronPython 3.4. Public API only. Every member is
checked with `scripts/sfapi.py has` (`scripts/lib/20_data.members.txt`; setters with `has --set`,
`scripts/lib/20_data.set.txt`). Newest member used: `DataTableCollection.Add(String, DataSource,
Boolean)` [api 10.1]; nothing newer than 14.6.

The facts below are Spotfire Analyst 15.0 behaviour. Items not yet proven in a live build are marked
**Not yet tested** and listed at the end with their ids (the code comments cite them).

## Functions

| function | build group | does | on failure |
|---|---|---|---|
| `data_add_properties(list)` | `properties` | one `B.step("property", name)` per spec property; returns `{name: DataProperty}` | step `failed` |
| `data_load_tables(list)` | `tables` | per sbdf/csv table: `load`, `embed`, `columnTypes` (csv with `columns`), then its metadata steps (below) at once, so data-function inputs see calculated columns (build order in [architecture.md](architecture.md)); then `defaultTable`; dataFunction tables get a `skipped` entry | `failed`; `embed` is a `fallback` (manual step) |
| `data_table_metadata(list)` | `tables.metadata` (after `df_build_all`) | per existing table not handled yet (data-function outputs): `description`, `calculatedColumn`, `hierarchy`, `columnDescription`, `columnFormat`, `columnSettings`, `settings`; then `embedCheck` and `defaultTable` | `failed`; `columnFormat` and `embedCheck` are fallbacks; missing table = `skipped` |
| `data_relations(list)` | `relations` | one `B.step("relation", "L -> R")` each | `failed` |
| `data_markings(list)` | `markings` | one `B.step("marking", name)` each, default marking first | `failed` |
| `data_filtering_schemes(list)` | `filteringSchemes` | one `B.step("filteringScheme", name)` each | `failed` |
| `data_filtering_scheme(name)` | (helper for `50_pages` and `30_datafunctions`) | `FilteringScheme` for a name; `None`/`""` = default scheme (the lookup is `B.filtering_scheme` in `00_core`) | raises if missing or not created yet |

Report: `B.created["properties"][name] = {type, listValued, existed, defaultFilled}`;
`B.created["tables"][name] = {source, path, rows, columns, id, replaced, embedded, calculatedColumns, hierarchies, metadataStage}`;
`B.created["relations"] += {left, right, expression, existed}`; `B.created["markings"][name] = {color, default, reusedBuiltIn}`;
`B.created["filteringSchemes"][name] = {default, renamedDefault, schemeReady}`.

## R1 Document property

```python
NameString.ValidateCustomPropertyName(name)           # letters/digits per dot-separated segment; no "_", "-", spaces; not "spotfire."
found, prop = Document.Data.Properties.TryGetProperty(DataPropertyClass.Document, name)   # case-insensitive
if not found:
    attrs = DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated     # 14 | 64 = 78
    if list_valued: attrs = attrs | DataPropertyAttributes.IsListValued              # 94
    proto = DataProperty.CreateCustomPrototype(name, description, value, dtype, attrs)  # 5-arg overload
    Document.Data.Properties.AddProperty(DataPropertyClass.Document, proto)
```

- 78 is what Analyst's own New Property dialog gives a property (a saved DXP shows `IsPersistent,
  IsVisible, IsEditable, IsPropagated`).
- The value must already have the representation type; Spotfire does no numeric widening:
  String=String, Integer=Int32, LongInteger=Int64, Real=Double, SingleReal=Single, Currency=Decimal,
  Date/DateTime/Time=DateTime, TimeSpan=TimeSpan, Boolean=Boolean. `net_value` (00_core) converts JSON values.
  Only a `str` is parsed by Spotfire itself.
- A `Time` default given as text is passed as a string, so Spotfire parses it with its own Time format
  (the date part is Spotfire's base date). If Spotfire rejects the text, the builder stores
  `DateTime.Parse(text)` (today's date) with a warning (**Not yet tested**, U15).
- List-valued defaults are stored unconverted at creation, so the builder passes a typed `List[T]` of
  `net_value` items (the standard `Keywords` property persists as `List<String>`), not a Python list
  and not `net_list`'s `List[Object]`.
- No spec default: pass `dtype.DefaultValue` (what the 3-argument overload passes).
- `DataProperty.Description` has no setter: description is creation-time only. Arity picks the overload; the
  4-argument form treats argument 2 as the default value, not the description.
- Idempotent: an existing property keeps its value (only a `None` value receives the spec default); a different
  `listValued` flag or description is reported as a warning, never changed.

## R2 Load an SBDF or CSV table

```python
ds = SbdfFileDataSource(path)                                   # or TextFileDataSource(path, settings)
ds.IsPromptingAllowed = False
found, table = Document.Data.Tables.TryGetValue(name)
if found: table.ReplaceData(ds)                                 # re-run: keeps the table identity
else:     table = Document.Data.Tables.Add(name, ds, True)      # explicit autoCreateFilters
```

- `Tables.Add(name, ds)` (2 arguments) takes autoCreateFilters from a user preference; use the 3-argument
  overload.
- `ReplaceData` keeps the table identity on a re-run. Invalid or duplicate names raise `ArgumentException`.
  A stored name that differs from the spec name is a warning (later lookups by the spec name fail).
- A missing file raises `ImportException("File not found")` at data-source construction; the builder checks
  `File.Exists` first for a clearer message.
- `TextFileDataSource` has no `(String)` constructor; the 1-argument form takes a `Stream`.
- CSV settings: the `TextDataReaderSettings()` defaults are separator `";"`, no header row, culture guessed,
  `CodePage -1` (BOM, else ANSI). The builder always sets `Separator`, `AddColumnNameRow(0)` (unless
  `header: false`), `CultureName` (`"en-US"`) and `CodePage` (65001 for UTF-8; other names via
  `System.Text.Encoding.GetEncoding(name).CodePage`).
- Column types: `settings.DataTypesGivenName[name] = DataType.X`. The reader applies them by the detected
  unique header name after its type heuristics, as fixed types (heuristics never override them) while
  `TypesRow` stays below 0 (default -1). Names match exactly. With `header: false` the keys must be
  Spotfire's generated names (`Column 1`, ...; U10).
- After loading, `columnTypes` compares every listed column's `DataType.Name` with the spec and fails the step
  on a missing column or another type.

## R3 Embed the data (per-table save setting)

```python
ss = Document.Data.SaveSettings                         # live object held by the data manager
found, entry = ss.TryGetDataTableSettings(table.Id)
if found: entry.UseLinkedData = False                   # update the existing entry
else:     ss.DataTableSettings.Add(DataTableSaveSettings(table, False, False))
```

- Path-based file sources are not embedded by default: without a per-table entry a table is embedded only when
  `EmbedAllSourceData` is set or the table cannot link; otherwise a user preference decides.
- `Document.Data.SaveSettings` is created on first access with one entry per existing table, so an entry may
  already exist: update it, never add a duplicate. With duplicates the runtime lookup (first entry) and the
  save (last entry) disagree.
- Spotfire replaces the save-settings object while it saves: fetch `Document.Data.SaveSettings` again after a
  save instead of keeping a reference.
- `embedCheck` (after data functions) re-reads every entry and re-applies it if it changed (warning).
- `Document.Data.SaveSettings.EmbedAllSourceData = True` would embed every table and is persisted; not used.
- `embed: false` writes `UseLinkedData = True` and logs a warning (a shared app should embed its data).
- Manual step when the step fails: choose "Embedded in analysis" for the table in the embedded/linked data
  options of File > Save As, then save again.

## R4 Default table

`Document.Data.Tables.DefaultTableReference = table` (throws for a table not in the collection). New visuals get
it through `VisualizationData.AutoConfigure()`. Rule: `spec.defaultTable`, else the first loaded file table, else
the first existing table. Set in `data_load_tables` for file tables, re-checked in `data_table_metadata`
(data-function tables exist only then) and set again after the starter tables are removed (`90_build`).

## R5 Table and column descriptions

- Table: `table.Properties.SetProperty("Description", text)`: standard table property "Description" (attributes
  IsStandard, IsPersistent, IsVisible, IsEditable); there is no `DataTableProperties.Description` member.
- Column: `col.Properties.Description = text` (live wrapper, writes through).

## R6 Column number / date format

```python
f = col.DataType.CreateLocalizedFormatter()             # writable clone (Real -> RealNumberFormatter, ...)
f.FormatString = "#,##0.0"                              # NumberFormatter: Category becomes Custom
col.Properties.Formatter = f                            # stores a read-only clone; validated against the type
```

- Changing `col.Properties.Formatter` in place throws "Object is read only".
- Only `NumberFormatter` (Integer, LongInteger, Real, SingleReal, Currency) and `DateTimeFormatter` (Date,
  DateTime, Time) have `FormatString`; other types fail the step (fallback: Column properties > Formatting).
  A wrong formatter class raises "Invalid formatter".
- The localized formatter formats with the user's culture (separators follow the Analyst locale).
- **Not yet tested**: whether visuals that aggregate the column (cross-table measures, KPI values, chart axes
  and labels) show this format by default; the builder sets no visual-level formatters.

## R7 Calculated column

`table.Columns.AddCalculatedColumn(name, expression)`; existing: `col.As[CalculatedColumn]().Expression = expr`.
An invalid expression raises `ExpressionException("The calculated column is not valid.")`, a duplicate name
`NameArgumentException`. `DataColumn.As[T]()` raises for a column of another kind (unlike `Visual.As`).
Created in spec order (later columns may use earlier ones), before hierarchies and column metadata.

## R8 Hierarchy column

```python
levels = List[String](); levels.Add(esc("Station")); levels.Add(esc("Pump ID"))
table.Columns.AddHierarchyColumn(name, HierarchyDefinition(HierarchyNestingMode.Nested, levels))
```

Levels are column expressions (`[Pump ID]`); an invalid level raises `ArgumentException`. An existing
hierarchy is updated through `col.As[HierarchyColumn]().HierarchyDefinition = definition`.

## R9 Relation

```python
rel = Document.Data.Relations.FindRelation(left, right)     # None when unrelated
if rel is None:
    expr = " and ".join(left.NameEscapedForExpression + "." + esc(l) + "=" +
                        right.NameEscapedForExpression + "." + esc(r) for l, r in on)
    rel = Document.Data.Relations.Add(left, right, expr)
```

`Add` raises `ArgumentException` for tables already related or a cyclic relation, and `ExpressionException
("Invalid relation.")` for a bad expression (the relation is removed). Never hand-build brackets:
`esc` = `ExpressionUtilities.EscapeIdentifier` (doubles `]`, escapes `${`). An existing relation is kept (a
different expression is a warning).

## R10 Markings

- A new analysis has one marking, the default, named "Marking" in English (localized otherwise).
- The default spec marking (`default: true`, else the first one; a warning when there are several) is processed
  first: if it does not exist and the document holds only the built-in marking (whose name is not another spec
  marking), the built-in is renamed (`DataSelection.Name`); otherwise `Markings.Add(name)`. Then
  `mk.Color = color("#RRGGBB")` (`Color.Empty` is rejected; API-created markings start black) and
  `Markings.DefaultMarkingReference = mk`.
- No spec markings: the built-in marking is kept as default and renamed `Marking` (or found/added by that name).
- Markings and filtering schemes are built before the data functions, so inputs limited by a marking or scheme
  (`limitByMarking`/`limitByFiltering`) find them by their final names.
- `VisualizationData.AutoConfigure()` gives new visuals `DefaultMarkingReference`, so markings must exist before
  pages. A visual with `MarkingReference = None` cannot be marked.

## R11 Filtering schemes

- `Document.Data.Filterings.Add(name)` creates a `DataFilteringSelection`; Spotfire then creates the matching
  `FilteringScheme` itself. Look it up with `Document.FilteringSchemes[selection]` (fallback: iterate and compare
  `FilteringSelectionReference`). Whether it exists right after `Add` in the same script is **Not yet tested**
  (U2): the builder warns "has no FilteringScheme yet" when it does not.
- `DefaultFilteringReference` and `DefaultFilteringSchemeReference` are read-only: the default scheme cannot be
  switched. `default: true` therefore renames the built-in default scheme ("Filtering scheme" in English) to the
  spec name; a second default, or a default that already exists as a named scheme, is a warning.
- Pages: `page.FilterPanel.FilteringSchemeReference = data_filtering_scheme(name)` (50_pages).

## Pitfalls

1. Out parameters come back as tuples: `found, t = Tables.TryGetValue(name)`. Indexers (`Tables["x"]`,
   `Columns["x"]`, `Document.Properties["x"]`) throw when missing; use `TryGetValue`/`TryGetProperty`.
2. Get-only: `DataProperty.Description`, `DataFilteringSelectionCollection.DefaultFilteringReference`,
   `FilteringSchemeCollection.DefaultFilteringSchemeReference`, `DataColumnProperties.DataType` on real columns
   (throws). Settable defaults: `Tables.DefaultTableReference`, `Markings.DefaultMarkingReference`.
3. Missing members people assume: `AddNew` on tables/markings/filterings, `DataTable.SaveSettings`,
   `DataTable.UseLinkedData`, `DataColumn.Formatter`, `DataTableProperties.Description`, public Excel sources
   (convert Excel to SBDF/CSV upstream).
4. Property names are identifier segments and case-insensitive: Shiny ids such as `date_range` must become
   `DateRange`.
5. Python values into `Object` parameters are not converted: a Python `int` for a Real property is rejected;
   a Python list is not an `IList<T>`.
6. Order (`90_build`): properties -> file tables (+ their metadata) -> markings -> filtering schemes -> data
   functions -> data-function table metadata -> relations -> scripts -> pages -> triggers (manual steps) ->
   document finish -> starter tables removed. Markings and filtering schemes come before the data functions
   because an input limited by a spec marking or scheme needs them at binding time. Relations need the
   data-function tables; markings and the default table must exist before visuals.
7. Hygiene: a table's source `FilePath` is persisted even for an embedded table, and a local path carries the
   user name. A stream source (`SbdfFileDataSource(Stream)`) does not help: it persists the temporary file it
   spools to. Changing `FileDataSource.FilePath` after the load does not change the saved path either: the
   table keeps its own copy of the data source. What works without a server: open the file by its bare name
   with the current folder set to the file's folder (`SbdfFileDataSource("NAME.sbdf")`), so `FilePath`
   persists as `NAME.sbdf`. The standard engine does this in apps with features (feature `pathFree`,
   `scripts/engine/features/pathfree.py`): the folder is restored at once, the load falls back to the full
   path with a NOTE line when it fails or gives no columns, and a NOTE line names the path the DXP keeps.
   Analyst loads SBDF out of process by default, in a new process per load that inherits the current folder,
   so it finds the bare name too. The by-name load is **Not yet tested** (U16). Library SBDF
   (`SbdfLibraryDataSource`) and data-function output tables are path-free too.

## Not yet tested

| # | Unknown | Smallest test |
|---|---|---|
| U1 | `UseLinkedData = False` really embeds a path-based SBDF/CSV table (data in `EmbeddedDataTables`; opens without the file) | build, save, rename the data file, reopen, check row count; in the saved DXP: `useLinkedData: false` + `EmbeddedDataTables` entry |
| U2 | `Document.FilteringSchemes[sel]` is not None right after `Filterings.Add` inside the build script | builder warns "has no FilteringScheme yet" if not; page steps then fall back to the default scheme |
| U4 | `formatter.FormatString = ...` works through the public base class when the runtime formatter type is not public (`RealNumberFormatter`) | `columnFormat` steps ok; the saved DXP shows `FormatStringV40` |
| U5 | `Tables.Add` loads synchronously in a script (RowCount/Columns final at once) | report `rows`/`columns` > 0; `columnTypes` ok |
| U7 | typed `List<T>` list-property defaults round-trip through save/reopen and drive multi-select list boxes | saved DXP shows `Value: List<String>`; reopen, read `Document.Properties[name]` |
| U8 | `found, x = TryGetValue(...)` tuple convention under IronPython 3.4.2 (core-wide) | any build: lookups work |
| U10 | `DataTypesGivenName` + `en-US` parse ISO timestamps (`2025-01-31 08:00:00`); generated names without header (`Column 1` vs `Column 0`) | csv table with DateTime column: `columnTypes` ok, values not empty |
| U13 | relation expression with spaced table names via `NameEscapedForExpression` | relation between `A B` and `C`: step ok, `IsValid` |
| U14 | table/column descriptions, formats, calculated columns and hierarchies on a data-function output table survive the function's next run | change an input, let the function refresh, re-inspect the columns |
| U15 | a `Time` property default given as text persists with Spotfire's base date (fallback: today's date) | read the property `Value` in the saved DXP |
| U16 | an SBDF opened by its bare name (feature `pathFree`) loads in Analyst 15.0 and the DXP keeps `NAME.sbdf` | build an app with features and an sbdf table; the log's NOTE line names the kept path |

## What verify_dxp should check (persisted shape in the saved DXP)

| spec item | persisted path / fields |
|---|---|
| property | `DataManager > PropertyRegistry > AnalysisProperties > Properties[] DataProperty "<name>"`: `Attributes: IsPersistent, IsVisible, IsEditable, IsPropagated` (+ `IsListValued`), `DataType "<type>"`, `Value` (list: `List<T>`), `Description` |
| table | `DataManager > Tables > Items > Nodes[] DataTable "<name>"`: `Id`, `ColumnProducers[] SourceColumnProducer > DataFlow > DataSource: SbdfFileDataSource / TextFileDataSource { FilePath, DataOriginIsStream, Settings }`, `CachingBehavior` |
| csv settings | `TextDataReaderSettings { culture "en-US", separator, columnNameRows (_size 1, item 0), typesRow -1, dataTypesGivenName {name: DataType}, codePage 65001 }` |
| column types | `DataColumn "<name>" > DataType "<type>"` (authoritative; compare with `source.columns`) |
| embedding | `DataManager > PersistentData > SaveSettings: DataSaveSettings { embedAllSourceData, tableSettings[] { tableId (= DataTable.Id), useLinkedData, reuseSettingsWithoutPrompting } }` and `PersistentData > EmbeddedDataTables[]`. PASS: `useLinkedData: false`, or `CachingBehavior: DataCachingBehavior.Embedded`; FAIL: `Linked` for a file table with `embed: true` |
| default table | `DataManager > Tables > DefaultTable: -> DataTable "<name>"` |
| table description | `DataTable > DataPropertyContainer > ListenableProperties["description"] > AssignedValue` |
| column description | `DataColumn > Source > DataPropertyContainer > ListenableProperties["description"] > AssignedValue` |
| column format | same container, key `"formatter"` > `AssignedValue: RealNumberFormatter / IntNumberFormatter / DecimalNumberFormatter { Category: NumberFormatCategory.Custom, FormatStringV40: "<format>" }` (`FormatString` holds the version marker `__SPOTFIRE_NUMBERFORMATTER_VERSION_4_0__`); dates: `DateTimeFormatter { FormatString: "<format>" }` |
| calculated column | `DataColumn "<name>" > Source: CalculatedColumnImpl > OwnedColumnProducer: CalculatedColumnProducer > ExpressionTexts > Expression` |
| hierarchy | `DataColumn "<name>" > Source: HierarchyColumnImpl > OwnedColumnProducer: HierarchyColumnProducer > ExpressionTexts > Expression: "CREATE Nested Hierarchy [<name>] \r\n [L1] AS [L1],\r\n ..."` |
| relation | `DataManager > Relations > Items[] DataRelation { Expression "[L].[a]=[R].[b] and ...", LeftTableName, RightTableName }` |
| marking | `DataManager > Markings > Items > Nodes[] DataMarkingSelection "<name>" { Name, Color: Color(#AARRGGBB) }`, `DefaultMarking: -> "<default name>"`; no `Marking (2)` style names |
| filtering scheme | `DataManager > Filterings > Items > Nodes[] DataFilteringSelection "<name>"`, `DefaultFiltering: -> "<name of the default: true scheme>"` |
| hygiene | flag absolute `FilePath` values (user name) in data sources |
