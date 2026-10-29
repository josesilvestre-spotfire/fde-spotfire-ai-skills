# DXP anatomy: what is inside a .dxp and where the builder's objects are persisted

How Spotfire stores an analysis, and where each object the builder creates (or you add by hand)
ends up. This is the reference `scripts/verify_dxp.py` relies on: it reads the saved file with
`scripts/sfgraph.py` (the object-graph reader) and compares the persisted fields named here with
the spec. Everything here describes what you READ in a saved file; the builder never writes these
fields directly.

Evidence: analyses saved by Spotfire 6.5 to 15.0, read with `verify_dxp.py dump`, and live builds
on Analyst 15.0. Field names are written exactly as `sfgraph.render_outline` prints them.
Tags: [SAVED] seen in a file saved by Spotfire; INFERRED; **Not yet tested** (not seen in a saved
file yet). The public API calls that write these fields are in the `api-*.md` references next to
this file; the app rules they must satisfy are in the `spotfire-app-design-rules` skill.

## 1. The archive

A .dxp is a ZIP. Entries written by Analyst 15.0 (build 71.0.22206.3863):

| entry | content | what verify does with it |
|---|---|---|
| `Metadata.xml` | `<FileMetadata DocumentType="Analysis" SchemaVersion="1.0" CompatibilityVersion="15.0;14.8;14.6">`; one `<Property ArchiveElementType="AnalysisDocument" Version=".." ArchiveElementPath=".."/>` per document version and one for `EmbeddedResources`; properties `SavedByAssemblyFileVersion` (`71.0.22206.3863`) and `EmbeddedDataFormatVersion` (`2`) | saved by 15.0; the versions cover `app.minimumSpotfireVersion` |
| `AnalysisDocument.xml` | the newest document: one line of serialized objects (section 3) | the document compared with the spec |
| `14.8-AnalysisDocument.xml`, `14.6-AnalysisDocument.xml` | the same analysis downgraded (section 2) | present; included in the hygiene scan |
| `AnalysisMetadata.json` | summary for the library: `Description`, `FormatVersion` (`"15.0;14.8;14.6"`), `Properties: [{Key, Value: [...]}]` with `keywords`, `AllowWebPlayerResume`, `EmbedAllSourceData`, `Spotfire.Connector`, `Spotfire.TableCount`, `Spotfire.ColumnCount`, `Spotfire.PageCount`, `Spotfire.EmbeddedMod` (`id;version;name;sha512=...`), `Spotfire.SavedByAssemblyFileVersion`, ... | description, keywords, counts, no connector |
| `EmbeddedResources.xml` | `<EmbeddedResource Id="N" ArchiveElementPath="EmbeddedResources/N.emb" Name=".."/>` per resource | resolves `ObjectReference<EmbeddedResource>` |
| `EmbeddedResources/N.emb` | the resources (1.1) | |
| `EmbeddedResources/<SHA-1>.zip` | per-visual states of bookmarks; not listed in `EmbeddedResources.xml` | none expected |
| `DataTables/<guid>` | the rows of each embedded table, in Spotfire's own binary format (`EmbeddedDataFormatVersion` 2), not SBDF: `spotfire.sbdf` cannot read it, so row counts are not recoverable statically. The name is a `PersistentDataTable2.TableId` (section 11), not the `DataTable.Id` | one per embedded table |
| `DataArchive/DataAccessPlan.xml` | `<DataAccessPlan Version="1"><DataConnections /></DataAccessPlan>` for file and embedded data; data connections otherwise | no connections |
| `Mods/mod-N.asice` | one per embedded mod: an ASiC-E container holding `mimetype` (`application/vnd.etsi.asic-e+zip`), `mod.zip` (manifest and files), `META-INF/ASiCManifest.xml` (sha512 of mod.zip = the `hash` in the mod metadata) and `META-INF/signature.p7s` | one per mod used |
| `Bookmarks/<guid>.xml` | one per bookmark (`<Bookmark Name Id IsPublic Author>` with page, visual and filter state) | none from the builder |
| `Preview.png`, `Preview.txt` | thumbnail written at save | |

Entry order as written: the documents (newest first), the `.emb` resources,
`EmbeddedResources.xml`, `Metadata.xml`, `AnalysisMetadata.json`, bookmarks, `DataArchive/`,
`Preview.*`, `Mods/`, `DataTables/` (stored uncompressed).

### 1.1 Embedded resources, by `Name`

| name | content | written by |
|---|---|---|
| `EmbeddedScripts.xml` | every IronPython and JavaScript definition (section 9). UTF-8 with BOM; `<EmbeddedScripts />` when there are none | `ScriptManager`; always present |
| `CustomStyles.json` | the theme-editor JSON, verbatim (section 14); 0 bytes when never set | Analyst, when you apply custom styles |
| one per marking, named after it (`Marking`, `Selected Pump`, ...) | the marked rows; 0 bytes when nothing is marked | each `DataMarkingSelection` |
| `<32 hex>.png` / `.jpg` | a text-area image, raw bytes; `HtmlTextArea.Images` refers to it by Id (the Name usually repeats the key and may be empty) | `ImageCollection.Add` (not in spec v1) |
| `EmbeddedBinaryData` | binary property values, for example `Preview.Thumb` | Spotfire |
| `DataBufferCache`, `MarkerShapeImage`, `Map Chart Image Layer - Image File` | caches, custom marker shapes, map image layers | never by the builder |

## 2. Document versions

- Spotfire writes the current format plus the two previous ones: 15.0 -> 14.8 and 14.6; 14.8 ->
  14.7 and 14.6; 14.6 -> 14.5 and 14.0; 12.5 -> 12.4 and 12.0 [SAVED]. `DocumentSaveSettings()`
  writes them by default. An older client opens the newest version it understands.
- A copy is the same object graph serialized at the older `PersistenceVersion` of each type
  (LineChart 69 in 15.0 and 14.8, 68 in 14.6; ReferenceLayer 71, 70, 68 [SAVED]).
  Fields an older version does not know are dropped or degraded:

| feature | 15.0 | 14.8 copy | 14.6 copy |
|---|---|---|---|
| reference layer | `ElementByAxis`, `ReferenceLayerXAxis`, `ColorAxis "RefLayerColor"`, `Data: ReferenceLayerData { ..., VisualizationData }` (a band from another table, with its own where clause) | `Details` and `ReferenceLayerData`, no table | the band, box, label, line and marker blocks, `Value` / `SecondaryValue`, evaluation fields; `ValueAxis` on the layer; another table only in the `QualifiedNameMapper` |
| fitting model | an automatic `FittingModelLayer` in `InternalLayers` | none | none |
| scale | `AdaptiveTimeLabels` | none | none |

- verify compares the spec with `AnalysisDocument.xml`, checks that `CompatibilityVersion` lists
  `app.minimumSpotfireVersion` (or an older version), and warns when the spec uses a feature whose
  fields are missing from that copy (a reference layer with `table` against 14.6).
- Text-area controls, property triggers and the theme have no public API: you add them by hand,
  and the verifier reads the shapes Analyst writes for them (sections 8, 9 and 14). Files saved by
  14.6 and the 14.6 copies show the same shapes.

## 3. Object-graph conventions

```xml
<?xml version="1.0" encoding="utf-8"?><Root xmlns="http://www.spotfire.com/schemas/Document1.0.xsd" SchemaVersion="1.0">
<Object Id="1"><Type><TypeObject Id="2" AssemblyName="Spotfire.Dxp.Application, Version=71.0.22206.3863, Culture=neutral, PublicKeyToken=789861576bd64dc5" FullTypeName="Spotfire.Dxp.Application.Document">
<NonSystemTypeInfo><PersistenceVersion Major="64" Minor="0" /><BaseType>...</BaseType></NonSystemTypeInfo></TypeObject></Type>
<Fields><Field Name="DocumentNodeId"><String Id="6" Value="2c4d36ef-3672-4f8d-9c1f-86f41807a169" /></Field><Field Name="DataManager"><Object Id="7">...
```

| construct | serialization | reading rule |
|---|---|---|
| ids | every `Object`, `Struct`, `Array`, `MultiDimensionalArray`, `String` and `TypeObject` carries a document-wide `Id` | index by Id |
| references | a value written before is `<ObjectRef Value="Id"/>`; `Value="0"` is null | resolve before comparing; the first occurrence defines the value |
| types | `TypeObject` once (`FullTypeName`, `AssemblyName` with version, `NonSystemTypeInfo { PersistenceVersion, BaseType }`, `GenericTypeInfo`), then `<TypeRef Value="Id"/>` | match on `FullTypeName` or the base chain |
| fields | `<Fields><Field Name="X">value</Field>...` | serialization names, often different from the API names: sections 5 to 15 map them |
| primitives | `Bool`, `Int`, `Long`, `Short`, `Byte`, `Float`, `Double`, `Decimal`, `DateTime`, `TimeSpan`, `Char`, ... with `Value` | |
| enums | `<Enum Value="Tabs"><Type>..</Type></Enum>`; flags as a list: `Value="IsPersistent, IsVisible, IsEditable, IsPropagated"` | compare member names |
| nullable null | `<NullableNull />` | |
| strings | `<String Id Value>`, `IsInterned="true"` when interned; the empty string is written once (`IsEmpty="true"`) and referenced everywhere; one `String` element can feed many fields | never assume one string per field |
| text escaping | XML attribute escaping (`&amp; &lt; &gt; &quot;`; CR and LF as `&#xD;&#xA;`), and Spotfire encodes control characters as `_xHH` (a tab is `_x09`) | XML-unescape, decode `_xHH`, normalize newlines |
| arrays | `<Array Id LowerBound Length><Type/><Elements>...</Elements></Array>`; primitive arrays inline: `<Elements>0,0,0,0</Elements>` | |
| rectangular arrays | `<MultiDimensionalArray>` with `Dimensions` and `IndexedElement Index="i,j"` (map transforms) | read by sfgraph |
| lists and dictionaries | `List<T>` = `_items` + `_size` (only the first `_size` items count; the rest is null padding) + `_version`; `Dictionary` = `Version`, `Comparer`, `HashSize`, `KeyValuePairs`; `KeyValuePair` = `key`, `value` | `Graph.list_items` |
| Guid | `Struct System.Guid { _a ... _k }`; the outline prints `Guid(xxxxxxxx-xxxx-...)` | |
| Color | `Struct System.Drawing.Color { name, value (Long ARGB), knownColor, state }`; the outline prints `Color(#AARRGGBB)`. A known color (a marking can be stored as `KnownColor.Black`) prints `#00000000`: read `knownColor` and `name` too. Spotfire's `ColorInfo { argb }` (reference layers, fitting-model curves) is a signed Int32 | spec `#RRGGBB` = `#FFRRGGBB`; ARGB int: `"%08X" % (argb & 0xFFFFFFFF)` |
| node identity | every document node has a hidden `DocumentNodeId` (a Guid string) | the only link from a `ManagedScriptDefinition` to its code (section 9) |
| resources | `ObjectReference<EmbeddedResource> { Id: N }` | `EmbeddedResources.xml` entry with `Id="N"` |
| collections | `PersistedZombieCollection<T> { Nodes: T[], Zombies }` (tables, columns, markings); `...Collection { Items: T[] }` elsewhere | |
| expressions | `PreprocessorNode { Expression (as set), PreProcessedExpression (evaluated), PreProcessorNameMapper }`; expressions over columns also carry a `NameMapper` / `QualifiedNameMapper` (`Columns`, `Tables`, `DocumentProperties2`, ...) | compare `Expression`; never edit expressions as text |
| assemblies | types come from `Spotfire.Dxp.Application`, `Spotfire.Dxp.Data`, `Spotfire.Dxp.Framework`, `mscorlib` and `System.Drawing` | any other assembly is an extension the client must have installed |

Outline notation (`sfgraph.render_outline`): `Field: #id Type "label"` defines a node,
`Field: -> #id Type "label"` references one, `[Str #n, interned, shared xK]` marks a string shared
K more times.

## 4. Where things live

| spec item | persisted under | section |
|---|---|---|
| pages, layout, navigation, canvas, active page | `Document.Pages: PageManager` | 5 |
| visuals | `Page.Visuals.Items[] Visual`, content in `InternalContent` | 6, 7 |
| text areas and their controls | `HtmlTextArea` (`Controls`, `ActionLinks`, `CustomJavaScripts`) | 8 |
| scripts, JavaScript, triggers | `Document.ScriptManager` and resource `EmbeddedScripts.xml` | 9 |
| data functions | `Document.DataManager.DataFunctions` | 10 |
| tables, columns, embedding, default table | `DataManager.Tables`, `DataManager.PersistentData`, archive `DataTables/` | 11 |
| document properties, description, keywords | `DataManager.PropertyRegistry.AnalysisProperties`, `Document.DataPropertyContainer` | 12 |
| markings, filtering schemes, relations | `DataManager.Markings`, `DataManager.Filterings`, `Document.FilteringSchemes`, `DataManager.Relations` | 13 |
| theme | `Document.UseCustomStyles`, `.CustomStylesJson`, `.KnownTheme`, `.StyleManager` | 14 |
| mods | `Document.ModManager`, `ModVisualization`, archive `Mods/` | 15 |

Other `Document` fields Spotfire writes by itself: `DetailsOnDemandPlots`, `BookmarkManager`,
`Properties`, `ColoringTemplates`, `LoadInfo`, `ActiveVisualReference`,
`ActiveFilteringSelectionReference`, `ActiveMarkingSelectionReference`, `ActiveDataTableReference`,
`AutoHideTableScrollbars`, `WebAuthorModeAllowed`, `MultipleViewsEnabled`, `DataPanel`,
`DataCanvasDataPanel`, `Compatibility`, `ExternalActions`, `MarkerShapeDefinitions`, `CustomNodes`.
`DataManager` also holds `Highlight`, `AllRows`, `NoRows`, `ColumnRelations`,
`ExpressionFunctions`, `DataOnDemand` and `ManagedDataAccessPlan`.

## 5. Pages and layout

```
Document.Pages: PageManager
  NavigationMode: PageNavigationMode.Tabs                     <- Document.Pages.NavigationMode (Tabs, Links, None, Off)
  Pages: PageCollection
    Items: Page[n]                                            spec order = tab order
    ActivePage: -> Page                                       same page as Document.ActivePageReference
    VisualizationAreaSize { Size {width, height}, FitToWindow }   <- Pages.VisualizationAreaSize (default 0 x 0, true)
  StatusBarOnTop, NavBarOnTop
Page
  TitleExpression: PreprocessorNode { Expression }            <- Page.Title, raw text (${...} is live)
  Id: Guid(...)                                               build report created.pages[title]
  Visible                                                     <- Page.Visible
  Panels.Items[]
    FilterPanel { TypeId "Spotfire.FilterPanel", Visible, DockingPlacement {Region, Index}, PanelState, FilteringScheme -> FilteringScheme, TableGroups }
    DetailsOnDemandPanel { Visible, DockingPlacement, PanelState }       (also TagPanel, BookmarkPanel2)
  Visuals: VisualCollection { Items: Visual[] }               not the screen order (positions are in VisualPanels)
  VisualPanels: VisualPanelCollection { Items: VisualPanel[] { RelativeBounds {x, y, width, height}, Visual -> Visual } }
  Splitters: SplitterCollection { Items: SplitterModel[] { RelativeBounds, Orientation, ControlsOne, ControlsTwo, CrossOne, CrossTwo, FixedPosition } }
  Crosses: CrossCollection { Items: CrossModel[] { H1, H2, V1, V2 } }    where four panels meet
  ActiveMarkingSelectionReference, ActiveFilteringSelectionReference, HasDynamicLayout, DynamicLayoutWidth,
  PanelRegionSpanBottom/Left/Right, HasMinimumWidth/Height, ShowActiveVisualMaximized                 (not asserted)
```

| API | persisted |
|---|---|
| `Page.FilterPanel.Visible`, `Page.DetailsOnDemandPanel.Visible` | `Panels.Items[]` of type `FilterPanel` / `DetailsOnDemandPanel` -> `Visible` |
| `Page.FilterPanel.FilteringSchemeReference` | `FilterPanel.FilteringScheme -> FilteringScheme`; its `DataSelection -> DataFilteringSelection "<name>"` gives the scheme name (section 13) |
| `Page.ApplyLayout(LayoutDefinition)` | `VisualPanels`, `Splitters`, `Crosses` (no public setter for bounds) |
| `Page.GetVisualBounds(visual, Rectangle(0, 0, 100000, 100000))` | returns `VisualPanel.RelativeBounds` exactly |

Layout facts:

- Position and size exist only in `VisualPanel.RelativeBounds`: integers on a 0..100000 grid over
  the visualization area, on both axes. Splitters are 3 units thick; a panel starts 3 units after
  the previous splitter.
- The builder applies one `LayoutDefinition` per page: spec `row` = `BeginSideBySideSection`,
  `column` = `BeginStackedSection`, weights relative to their siblings. Each splitter sits at
  `int(share * 100000)`. Worked example: row[text 20, column 80[trend 60, row 40[a, b]]] gives
  text `0,0,20000,100000`, trend `20003,0,79997,60000`, a `20003,60003,39997,39997`,
  b `60003,60003,39997,39997`.
- The build report records `created.layouts[page][visual id] = {actual, expected}`; verify compares
  the decompiled bounds with `actual` exactly and with `expected` within 3 units.
- Not asserted: `HasDynamicLayout`, `DynamicLayoutWidth` and `PanelRegionSpan*` (user preferences),
  crosses, panel docking.
- API-made pages start with hidden panels and no filtering scheme. The builder assigns the default
  or the named scheme and docks the filter panel right (index 0) and details-on-demand right
  (index 1), as Analyst does; a built page never has `FilterPanel.FilteringScheme: null`.

## 6. Visuals: the common part

```
Visual
  Id: Guid(...)                                               build report created.visuals[id].guid
  TitleExpression: PreprocessorNode { Expression }            <- Visual.Title (raw; PreProcessedExpression = shown text)
  ShowTitle                                                   <- Visual.ShowTitle
  InternalContent: <content class>                            sections 7 and 8
    TypeId: TypeIdentifier "Spotfire.<Name>" { Name, DisplayName }
    DescriptionExpression { Expression }, ShowDescription     <- Visualization.Description, .ShowDescription
    Data: VisualizationData                                   <- Visualization.Data
      DataTable: -> DataTable "<name>"                        <- Data.DataTableReference
      Marking: -> DataMarkingSelection "<name>" | null        <- Data.MarkingReference (null = cannot be marked)
      Filterings.Items[].Reference -> DataMarkingSelection    <- Data.Filterings.Add(marking)   (limit by markings)
      ActiveFiltering: -> DataFilteringSelection | null       follows the page's scheme; no setter
      UseActiveFiltering                                      <- Data.UseActiveFiltering
      WhereClauseExpression: ManagedExpression { Expression } | null   <- Data.WhereClauseExpression
      LimitingMarkingsEmptyBehavior, LimitingMarkingsEmptyMessage, MarkingCombinationMethod   (same names)
    Legend { Visible, Dock, Width }                           <- Visualization.Legend.Visible, ...
    HorizontalLegend, Transparency, UseSeparateColorForMarkedItems
    Trellis { Panels, Rows, Columns, Pages: TrellisAxis { ExpressionTexts.Expression }, TrellisMode, ManualLayout, ManualRowCount, ManualColumnCount }
                                                              <- Trellis.PanelAxis / RowAxis / ColumnAxis / PageAxis .Expression, ...
    Details.Items[] ExpressionDetailItem { DetailColumn }     tooltip lines
  ShowTitleExpression, ShowPlotIssues, StyleOverrides (empty)
  ActionTriggers.Items[] ActionTrigger { AccessPoint.Display, Target }    empty unless you add a visual action trigger by hand
    Target: ManagedScriptActionTriggerTarget { ManagedScriptReference: ManagedScript }   the script it runs (sections 9 and 15)
```

### 6.1 Axes

| persisted | API | note |
|---|---|---|
| `X: ScaleAxis "X"`, `Y: ScaleAxis "Y"`, `Color: ColorAxis "Color"` | `XAxis`, `YAxis`, `ColorAxis` | scatter plots and map marker layers nest them under `ScatterLayer` (section 7) |
| `<axis>.ExpressionTexts.Expression` | `Axis.Expression` | compare byte-exact; `KeptOldExpression` and `AxisConfiguration` are Spotfire's own |
| `CategoryMode` | `Axis.CategoryMode` | |
| `Range`, `Reversed`, `TransformType`, `IncludeZeroInAutoZoom`: each a `KeyValuePair<CategoryKey, ...>[n]` | `ScaleAxisBase.Range = AxisRange(low, high)`, `.Reversed`, `.TransformType`, `.IncludeZeroInAutoZoom` | the entry whose key is the root `CategoryKey` (`Parts: Object[0]`) is the plain value; other keys are per measure (`Indexed*`) |
| `IndividualScaling`, `IndividualScalingMode`, `ManualZoom`, `ZoomRange`, `ShowAxisSelector` | same names on `ScaleAxisBase` | `ManualZoom true` = a visible zoom slider |
| `Scale { ShowGridlines, ShowLabels, LabelOrientation, MaximumNumberOfTicks, LabelLayout, UserSetScaleDock, Visible }` (indexed dictionaries) | `ScaleAxis.Scale.<same>` (`ScaleBase`; `Scale.Dock` for the dock) | gridlines and tick labels live on the scale, not on the axis |
| `Scale.Formatting.RealFormatter { Category: NumberFormatCategory.Custom, FormatStringV40 }` | `Scale.Formatting.RealFormatter = formatter` | `FormatString` holds the marker `__SPOTFIRE_NUMBERFORMATTER_VERSION_4_0__` |
| `ColorAxis.Rules: Coloring` | `ColorAxis.Coloring` | 6.2 |

There is no axis title property: the title shown is the display name, set with `as [Name (unit)]`
in the expression.

### 6.2 Coloring

| persisted | meaning |
|---|---|
| `Coloring { DefaultColor, EmptyColor, Items: ColorRule[] }` | rules in order: conditional rules first, the background rule last. Ignore `DefaultCategoricalRules`, `DefaultContinuousRules`, `DefaultDefaultColor`, `AutomaticColorAssignment` |
| `CategoricalColorRule { UserSetColors: KeyValuePair<CategoryKey, Color>[], UserAddedCategories, Palette }` | key `Parts[0]` = the category text |
| `ContinuousColorRule { Breakpoints: ColorBreakpoint[] { ValueKeeper.InnerValue { Value, ValueType, DataType }, Color }, IntervalMode: IntervalMode.Gradient }` | `ValueType`: `ConditionValueType.MinValue`, `MaxValue`, `AverageValue`, `MedianValue`, `Literal`, `Percent`, `Expression` |
| `ThresholdColorRule`, `RangeColorRule`, `StringColorRule`, `TopBottomColorRule`, `ExpressionColorRule` | rule classes; their fields were not seen in a saved file (**Not yet tested**): check class and order |
| `Coloring: ColoringCollection { Mappings: KeyValuePair<CategoryKey, Guid>[], Items: KeyValuePair<Guid, Coloring>[], DefaultNumericReference -> Coloring }` | cell colorings of tables, cross tables and heat maps (`Colorings.AddNew(name)`, `AddMapping`, `DefaultNumericReference`); key = table column name or cross-table measure alias |
| `KpiVisualization.ColorAxis` | tile color: expression `THEN [Y.FinalValue]` plus `Rules` |

### 6.3 Reference layers and fitting models

Line charts, bar charts, scatter plots, combination charts, box plots and waterfall charts:

```
InternalLayers: LayerCollection { Items: Layer[] }                       <- content.Layers
  ReferenceLayer "<Name>"                                                <- Layers.AddNewReferenceLayer()
    Name, Enabled
    Value / SecondaryValue: ReferenceValueColumn { ExpressionTexts.Expression, IncludeValueInAxisRange }   <- Expression / SecondaryExpression
    Line { Enabled, Stroke { style: LineStyle.<X>, color.color.argb, type: ColorType.Specific, width } }
    Band { FillEnabled, Fill.attributes { color.argb, type, transform }, StrokeEnabled, Stroke }
    Label { Enabled, Style { showDisplayName, showValue, textAlign, verticalTextAlign } }
    IsBackground, Transparency, Marker { Enabled }
    Data: ReferenceLayerData { ValueAxis, EvaluationModes, Width, LimitByMarking, ApplyParentDataLimiting,
                               VisualizationData { DataTable, WhereClauseExpression, UseActiveFiltering } }
          (14.8 copy: no VisualizationData; 14.6 copy: no Data, ValueAxis on the layer)
    15.0 only: ElementByAxis "ElementBy", ColorAxis "RefLayerColor"
  FittingModelLayer { FittingModel -> }                                  15.0; Spotfire adds one per fitting model
FittingModels.Items[]: StraightLineFittingModel | ReferenceCurveFittingModel
  Enabled
  Curves: ReferenceCurve "line" | "curve" { Expression, Color: ColorInfo { argb }, LineStyle, Width, Visible, CustomDisplayName, IsBackground,
                                            Details -> CurveNameReferenceItemDetail "Name" { ShowInLabel } }
```

The builder names a layer after its spec `label`, else `Horizontal line`, `Vertical line`, `Band`
(then ` 2`, ...). Spec `[$Prop]` is written as `DocumentProperty("Prop")`. A color with alpha below
255 becomes `Transparency = 1 - A/255` with an opaque color. Details: [api-coloring.md](api-coloring.md).

## 7. Visual types

| spec `type` | `TypeId` | content class (API) | key persisted fields -> API | evidence |
|---|---|---|---|---|
| `lineChart` | `Spotfire.LineChart` | `LineChart` | `X`, `Y`, `Color`, `Line: GroupByAxis "Line"` -> `XAxis`, `YAxis`, `ColorAxis`, `LineByAxis`; `LineWidth`, `ShowMarkers`, `MarkerSize`, `SteppedLines`, `BreakOnEmpty`, `Orientation`, `LabelVisibility`, `ShowLineLabels`, `ShowMarkerLabels`; `FillTimeSeriesGaps` -> `CompensateForMissingTimeSeriesValues` (INFERRED) | SAVED |
| `barChart` | `Spotfire.BarChart` | `BarChart` | `X`, `Y`, `Color`; `Orientation` (`BarChartOrientation`), `StackMode` (`None`, `Stack`, `Stack100Percent`), `SortedBars`, `SortBy`, `BarWidth`, `LabelVisibility`, `LabelOrientation`, `LabelCompleteBar`, `LabelSegments`, `SegmentLabelInformationType`; persisted `SortSegementsBySize` (sic) -> `SortSegmentsBySize`. Horizontal bars made in Analyst also persist `X.Reversed true` | SAVED |
| `histogram` | `Spotfire.BarChart` | `BarChart` | X `BinByEvenIntervals([<col>], <bins>)` (no angle brackets), Y `Count()` | SAVED (binned X) |
| `combinationChart` | `Spotfire.CombinationChart` | `CombinationChart` | API: `XAxis`, `YAxis`, `ColorAxis` (categorical only), `SeriesType`, `IndexedSeriesType[CategoryKey(<measure display name>)]`, `Bars`, `Lines`; a right-hand scale through `YAxis.IndividualScaling`, `IndividualScalingMode` and `Scale.IndexedDock`. Persisted field names not seen | **Not yet tested** |
| `scatterPlot` | `Spotfire.ScatterPlot` | `ScatterPlot` | under `ScatterLayer`: `X`, `Y`, `Color`, `Size`, `Shape { DefaultShape, ShapeMap }`, `Marker` (-> `MarkerByAxis`), `LabelColumn`, `LineConnection { Line (-> ConnectionAxis), Order (-> OrderAxis), Width, UseMarkerColor, IsBackground }`, `MarkerSize`, `MarkerClass`, `LabelVisibility`, `DrawingOrder` (-> `DrawingOrderAxis`), `MarkerRotation` (-> `RotationAxis`); `FittingModels`, `Details` and `InternalLayers` sit directly under the plot. GUI `MarkerSize` values look squared (1.9881, 3.8416): compare with a tolerance (**Not yet tested**) | SAVED |
| `scatterPlot3D` | `Spotfire.ScatterPlot3D` | `ScatterPlot3D` | `X`, `Y`, `Z: ScaleAxis3D`, `Color`, `Marker`, `Size`, `Shape.DefaultShape: Shape3D { Type }`, `Camera { Position, Direction, UpDirection, FieldOfView }`, `MarkerSize`, `LabelVisibility`, `ShowNavigationControls` | SAVED (14.6) |
| `pieChart` | `Spotfire.PieChart` | `PieChart` | under `ScatterLayer` with `MarkerClass: MarkerClass.Chart`: `MarkerSize` (pie size) and `PieMarker { Enabled, Color (-> ColorAxis: the sectors), SectorSize (-> SectorSizeAxis), VisualAttributes, Details }` | SAVED by 11.3 only; 15.0 **Not yet tested** |
| `boxPlot` | `Spotfire.BoxPlot` | `BoxPlot` | `X`, `Y` (a raw column: the Y axis does not aggregate), `Color`; `TableArea: BoxPlotStatisticsTable { Statistics.Items[].Expression, Visible, SortMode }` -> `Table.Statistics`; `BoxWidth`, `MarkerSize`, `VisibleMarkers`, `Violin`, `ComparisonCirclesArea` | SAVED |
| `heatMap` | `Spotfire.HeatMap` | `HeatMap` | `X`, `Y`, `Measures: HeatMapMeasureAxis` -> `MeasureAxis`; cell colors `Coloring: ColoringCollection` (`Coloring "Numeric"` as `DefaultNumericReference`) -> `Colorings`; `SortBy`, `SortOrder`, `RowDendrogram`, `ColumnDendrogram`; there is no color axis | SAVED |
| `treemap` | `Spotfire.Treemap` | `Treemap` | `Hierarchy: TreemapHierarchyAxis`, `Size: TreemapSizeAxis`, `Color` -> `HierarchyAxis`, `SizeAxis`, `ColorAxis` (continuous only); `ShowHierarchyHeaders`, `ShowLabels` | SAVED |
| `waterfallChart` | `Spotfire.WaterfallChart` | `WaterfallChart` | API: `XAxis`, `YAxis`, `ColorAxis`, `TotalBarVisibility`, `TotalBarColor` (`ColorInfo`), `ShowConnectingLines`, `Orientation`. Persisted field names not seen | **Not yet tested** |
| `table` | `Spotfire.Table` | `TablePlot` | `TableColumns { Items: DataColumn refs in display order, Widths: KeyValuePair<Guid, Int32>[] }` (key = the `Id` of the DataColumn node, not public) -> `TableColumns.Add`, `TryGetTableColumn(column).Width`; `SortInfos { Items, SortModes }` -> `SortInfos.Add(column, mode)`; `AutoAddNewColumns`; `Coloring` -> `Colorings`; `Rules` (show/hide); `RowHeight`, `HeaderHeight`, `FrozenCount`, `CellBorderStyle`, `WrapHeaderText`, `WrapCellText`, `ExportDataEnabled` | SAVED |
| `crossTable` | `Spotfire.CrossTable` | `CrossTablePlot` | `RowAxis: CategoricalAxis "Rows"`, `ColumnAxis "Columns"`, `MeasureAxis: ColorAxis "Measures"` -> same names; `ShowRowGrandTotal`, `ShowColumnGrandTotal`, `ColumnSubtotals.Subtotals[] { LevelName, Visible }`, `Totals`, `Formatting` and `Coloring` keyed by measure alias, `CellWidth` 100, `CellHeight` 13, `EmptyCellText "-"`; persisted `ColumnWidths` has no API | SAVED |
| `summaryTable` | `Spotfire.SummaryTable` | `SummaryTable` | API: `Columns`, `Aggregations` (the statistics), `CategoryAxis`. Persisted field names not seen | **Not yet tested** |
| `graphicalTable` | `Spotfire.GraphicalTable` | `Miniatures.GraphicalTable` | API: `RowAxis`, `Columns` (sparkline, calculated value, icon and bullet graph columns; miniature type ids `Spotfire.<Name>`), `SortInfos`. Persisted field names not seen | **Not yet tested** |
| `kpiChart` | `Spotfire.KpiChart` | `KpiChart` | `KpiCollection.Items[] KpiContent { TitleExpression (-> Title; default ${AutoTitle}), MiniatureVisualization: KpiVisualization { TypeId "Spotfire.KpiVisualization", Data, TileAxis, XAxis, YAxis "Y" (KpiYAxis), ComparativeAxis, ColorAxis, SortColumn, ShowSparkline, EmptyTileText } }` -> `KpiContent.Visualization.*`; chart `PreferredTileWidth` (a double, written by `PreferredRelativeTileWidth`, INFERRED), `MinTilesPerRow`, `MinVisibleTiles`, `NewRowPerKpi`, `SortMode`. Each KPI's `Data` repeats the chart's | SAVED |
| `map` | `Spotfire.WebMapChart` | `Maps.MapChart` | `Layers: MapChartLayerCollection { Items: MapChartLayer[] }`, index 0 = back: `StandardTileLayer { Title, Enabled, Transparency, ServiceName, IncludeInAutoZoom false }`; `MapChartDataLayer { Title, Enabled, Projection "EPSG:4326", IncludeInAutoZoom true, Visualization }` with `MarkerLayerVisualization` (`TypeId "Spotfire.WebMarkerLayerVisualization"`, axes under `ScatterLayer`, `PositioningMethod`) or `FeatureLayerVisualization` (`TypeId "Spotfire.WebFeatureLayerVisualization"`, `GeometryByAxis`, `ColorAxis`, `ActiveGeocodingTableReference`); map `InteractiveLayerReference`, `TrellisLayerReference`, `AutoZoom`, `ViewExtent`, `Projection`, `Data` (the trellis layer's table, no filterings) | SAVED |
| `textArea` | `Spotfire.HtmlTextArea` | `HtmlTextArea` | section 8 | SAVED |
| `mod` | `Spotfire.Mod` | `ModVisualization "main"` | section 15 | SAVED |

Never use `VisualTypeIdentifiers.MapChart` (the legacy `Spotfire.MapChart`). The
`Spotfire.DetailsOnDemandTable` plots under `Document.DetailsOnDemandPlots` are created by Spotfire,
not by the builder. Map details: [api-maps.md](api-maps.md); table and KPI details:
[api-tables.md](api-tables.md).

## 8. Text areas and controls

```
InternalContent: HtmlTextArea                                 TypeId "Spotfire.HtmlTextArea"
  IncludeInBookmark: false
  HtmlContent: "..."                                          <- HtmlTextArea.HtmlContent, stored verbatim (sanitized only at render)
  BackgroundColor: "#ffffff"                                  no public API; the builder leaves Spotfire's default
  Controls: HtmlTextAreaControlCollection { Items: HtmlTextAreaControl[] }     added by hand (Edit Text Area > Insert ... Control)
  ActionLinks: ActionLinkCollection { Items: ActionLink[] }                     written with action controls that link
  CustomJavaScripts: ManagedJavaScriptCollection { Items: ManagedJavaScript[] { ScriptApplication: ManagedScript } }   <- HtmlTextArea.Scripts
  Images: ImageCollection { Items: KeyValuePair<String, ImmutableEmbeddedResource { Hash, EmbeddedResource: ObjectReference Id }>[] }   <- HtmlTextArea.Images
```

A text area has no `Data`, `Legend` or `Description`.

**Tokens.** A control appears in `HtmlContent` as `<SpotfireControl id="<32 lower-case hex>" />`
(one space before `/>`): the control's `Id: Guid(...)` without dashes. Spotfire replaces tokens
ordinally, so case, attribute order and spacing must match. Setting `HtmlContent` deletes every
control whose token is missing and every action link no remaining control references; the same
cleanup runs when the file is opened. Keep the tokens when you edit the HTML of a text area that
already has controls.

**Markers.** The builder does not create controls (no public API). It sets the HTML once, with a
visible marker where each `{{control:<id>}}` placeholder was:
`<span style="color: #B3261E; border: 1px dashed #B3261E; padding: 0 4px">[Drop-down list: SelectedPumpId]</span>`
(`[<UI kind>: <property>]` for property controls, `[Button: <label>]` or `[Link: <label>]` for
action controls). The slim tier's library writes `[control: <id>]` in the same kind of span (color
`#E94165`). You replace each marker with the control by hand (`build/MANUAL-STEPS-<tier>.md`); the
control then persists as below.

**Controls** (classes in `Spotfire.Dxp.Application.HtmlTextAreaControls`, as Analyst writes them;
[api-textareas.md](api-textareas.md)):

| persisted | fields |
|---|---|
| `PropertyControl` | `Id`, `Size {width, height}` (0 x 0 = automatic), `RenderType: RenderType.<X>`, `DataProperty -> SingleInstanceDataPropertyContainer+SingleInstanceManagedDataProperty<Document>`, `Formatter` (null), `ValueProvider`, `InputError {Value, Message}` |
| `ActionControl` | `Id`, `Size`, `Color` (`#FF26A2ED`, set together with the view mode), `Label`, `ViewMode` (a string: `"Button"`, `"Link"` or `"Image"`), one action: `ScriptApplication: ManagedScript`, `ActionLinkReference -> ActionLink` or `DataFunctionReference -> DataFunction`; `Image` and `ReportReference` null |
| `FilterControl` | `Id`, `Size`, `Font`, `Color`, `Filter -> Filter` (not in spec v1) |

**Value providers:**

| persisted | fields | spec |
|---|---|---|
| `FixedValuesProvider` | `IncludeNoneAlternative`, `SelectionConstraints`, `Values: FixedValuesProvider+FixedValueItem[] { Name, Value }` (Value typed as the property), `HasExpressionValues: false` | `values.fixed`: `text` -> `Name`, `value` -> `Value`; the checkbox substitute is `Yes = True`, `No = False` |
| `ColumnValuesProvider` | `DataColumnReference -> DataColumn` | `values.column` (the column's unique values) |
| `ColumnNamesValueProvider` | `ColumnDataTableReference -> DataTable`, `SearchPattern` | not in spec v1 (column pickers) |
| `NumericalRangeValueProvider` | `Min`, `Max`, `Interval` (Decimal), `ShowLabels`, `IncludeNoneAlternative`, `SelectionConstraints` | `slider` (`ShowLabels true`) |
| null | | `label`, `input`, `multilineInput` |

Spec kind -> `RenderType`: `label` Label, `input` TextBox, `multilineInput` MultiLineTextBox,
`dropdown` DropDown, `listbox` ListBox, `multiSelectListbox` MultiSelectListBox (list-valued
property), `slider` Slider, `checkbox` DropDown (substitute: Spotfire has no check-box property
control), `radio` ListBox (substitute).

**Resolving references:**

- Property: the control's `DataProperty` node is the value of
  `Document.DataPropertyContainer.ListenableProperties["<lower-case name>"]`, whose
  `DataProperty -> DataProperty "<Name>"` gives the exact name (section 12).
- Script: `ScriptApplication: ManagedScript { ScriptDefinitionReference: ManagedScriptDefinitionReference { ScriptReference -> ManagedScriptDefinition, ScriptArguments: KeyValuePair<String, ManagedScriptArgumentValue>[] } }`.
  The `ManagedScriptDefinition`'s hidden `DocumentNodeId` equals the `ManagedScriptId` in
  `EmbeddedScripts.xml`, which holds the name and code (section 9). Arguments:
  `ManagedScriptArgumentLiteralValue { Prompt, LiteralValue }` for String and numeric parameters;
  `ManagedScriptArgumentNodeValue { Prompt, NodeReference -> Visual | Page | DataTable, CachedNodeData { Name, ParentId, ParentName } }`
  for `Page`, `Visualization` and `DataTable` parameters.
- Link: `ActionLink { Id (a Guid string), Actions: ActionCollection { Items: DocumentOperation[] } }`
  with `GotoPageDocumentOperation { Page -> Page }` or
  `ApplyBookmarkDocumentOperation { BookmarkId, Components: BookmarkComponentFlags.All, FilterApplyMode }`.
- Data function: `DataFunctionReference -> DataFunction "<name>"`.
- On click Spotfire runs the first one set: `ScriptApplication`, else `ActionLinkReference`, else
  `DataFunctionReference`.

**Checks.**

- No `{{control:` placeholder left (FAIL); every `<SpotfireControl>` token resolves to a control
  (FAIL); a control without a token is a WARN (Spotfire removes it on open).
- Each spec control is matched to a saved control by the build report id when there is one, else
  by bound property and render type (property controls) or by label, script or target page
  (action controls). Matched: kind, bound property, fixed values, column values, slider range,
  label, script and arguments, page, bookmark or data function are PASS or FAIL. Not matched but
  its marker is in the HTML: WARN (the manual step is not done yet). Neither: FAIL.
- A marker for a control the spec does not describe is a FAIL; a saved control the spec does not
  describe is a WARN.
- The HTML equals the spec once tokens and markers are mapped back to placeholders (PASS or WARN).
- Safe mode with css: `HtmlContent` starts with
  `<div id="style-container" class="sfdxb-style-<vid>"></div>` (unless the HTML brought its own
  container) and `CustomJavaScripts` lists the injector first, then each `js` entry in order. Rich
  mode with css: `HtmlContent` starts with `<style>`.

## 9. Scripts, JavaScript and triggers

The resource `EmbeddedScripts.xml` (`ScriptManager.EmbeddedScripts: ObjectReference<EmbeddedResource> Id: k`):

```xml
<EmbeddedScripts>
  <EmbeddedScript ManagedScriptId="<guid = DocumentNodeId of the ManagedScriptDefinition>">
    <ScriptDefinition Name="Reset All Filters" LanguageName="IronPython" LanguageVersion="3" WrapScript="true">
      <Description>Clears every filter on the page.</Description>
      <Parameters><ScriptParameter Name="page" TypeName="Page"><Description>Page to reset</Description></ScriptParameter></Parameters>
      <ScriptCode>...</ScriptCode>
      <ApprovalStamp>AQAAANCMnd8BFdERjHoAwE/Cl+sB...</ApprovalStamp>
      <AdditionalApprovalStamps />
    </ScriptDefinition>
  </EmbeddedScript>
</EmbeddedScripts>
```

- `LanguageName="IronPython" LanguageVersion="3"` = `ScriptLanguage.IronPython3`. JavaScript:
  `LanguageName="JavaScript" LanguageVersion=""`, every parameter `TypeName="String"` (**Not yet
  tested**). `WrapScript` = the spec `transaction` flag. The `ScriptParameter` element names are
  **Not yet tested** (no saved script with parameters was read yet).
- `ApprovalStamp` is a Windows DPAPI blob that trusts the script for the user who created it in
  Analyst; other users get the trust prompt; an edit outside Analyst drops it.
- Object graph: `ScriptManager { ManagedScripts: ManagedScriptDefinition[] (each only a hidden DocumentNodeId), ScriptEventHandlers, EmbeddedScripts }`.
- Code comparison: XML-unescape, decode `_xHH`, normalize CR LF.
- Property trigger (no public API; you add it in Edit > Document Properties > Properties, select
  the property, Script...):
  ```
  ScriptManager.ScriptEventHandlers: PropertyChangedScriptEventHandler[n]
    DataPropertyReference -> SingleInstanceDataPropertyContainer+SingleInstanceManagedDataProperty<Document>   (resolve through ListenableProperties)
    ScriptReference: ManagedScript { ScriptDefinitionReference { ScriptReference -> ManagedScriptDefinition, ScriptArguments: [] } }
  ```
  One handler per property; no arguments [SAVED, 14.6 and 15.0].
- Text-area JavaScript: `HtmlTextArea.CustomJavaScripts` items point to JavaScript definitions in
  `EmbeddedScripts.xml`; parameter values are literal arguments (**Not yet tested**).
- Checks: each spec script exists once by name, with language, `WrapScript`, parameters (order,
  name, type, description), description and code as specified, and a stamp; no scripts outside the
  spec except the JavaScript definitions the builder attached. Each spec trigger: no handler yet is
  a WARN (the manual step is not done); a handler is PASS when its property matches
  case-insensitively and its script name matches exactly, else FAIL; a second handler on the same
  property and a handler the spec does not list are WARNs.

## 10. Data functions

```
DataManager.DataFunctions.Items[]: DataFunction "<Name>"           <- DataFunctionCollection.AddNew(name, definition), name read back
  FunctionImpl: DataFunctionImpl
    FunctionDefinition: DataFunctionDefinition { Data: "<?xml ...><FunctionDefinition>..." }    the definition XML as one string
    Inputs: DataFunctionInputCollectionImpl -> DataFunctionInputExpressionImpl {
              Expression: ManagedExpression, IncludeActiveFiltering, RowCountLimit: 0, Distinct: false,
              Selections: DataSelection[], GroupingExpression, NameMapper }
    Outputs: DataFunctionOutputCollectionImpl ->
              TableOutputImpl { CreateFilters, SuggestedName, Reference -> ExternalColumnProducer }      <- Outputs.SetTableOutput
            | PropertyOutputImpl "<prop>" { PropertyName, PropertyClass: DataPropertyClass.Document, Reference }   <- SetDocumentPropertyOutput
            | ReplaceDataOutputImpl { TableReference } | ColumnsOutputImpl | JoinOutputImpl
    UpdateBehavior: DataFunctionUpdateBehavior.Automatic | Manual   <- DataFunction.UpdateBehavior
    Visible: true
    AdditionalSettings: {}           Analyst's dialog writes runlocation=defaultengine; the API cannot (not asserted)
  Inputs: KeyValuePair<String, DataFunctionInput { InputType: DataFunctionInputType.<X> }>[]   public mirror
```

The definition XML (the `Data` string, parsed as XML):

| element | API | the builder writes |
|---|---|---|
| `FunctionName` | `DataFunctionDefinitionBuilder.FunctionName` | the spec name |
| `DisplayName` | `.DisplayName` | the spec name |
| `Description` | `.Description` | the spec description |
| `OutputsOnlyDependsOnInputs` | `.AllowCaching` | |
| `ImplementationSpecificInformation/script`, `/dataframe` | `.Settings["script"]`, `.Settings["dataframe"]` | the code; `Pandas` for Python (key names **Not yet tested**) |
| `InputArguments/InputArgument { Name, Description, DisplayName, IsOptional, ArgumentType, AllowedTypes/DataType[] }` | `InputParameterBuilder(name, ParameterType)` (`Value` = `Scalar`, `Column` = `Vector`, `Table` = `Matrix`), `.AddAllowedDataType` | spec inputs; "all types" = `Integer, Real, SingleReal, Currency, String, Date, Time, DateTime, Boolean, Binary, LongInteger` in that order (no TimeSpan), as Analyst's dialog writes them |
| `OutputResults/OutputResult { Name, Description, DisplayName, ArgumentType }` | `OutputParameterBuilder(name, ParameterType)` | spec outputs |
| `ServiceType/Name` | `DataFunctionExecutorTypeIdentifiers.PythonScriptExecutor` = `Spotfire.PythonScript.Executor`; `TERRScriptExecutor` = `Spotfire.SNextScript.Executor` | from `engine` |
| `TrustApproval/ApprovalStamp` | stamped by `Build()` for the current user | present |
| `Category` | | `default` |

The persisted `InputType` follows from the binding expression (INFERRED):

| spec `bind` | expression the builder writes | `InputType` |
|---|---|---|
| `{"property": "P"}` | `DocumentProperty("P")` | `DocumentProperty` |
| `{"value": 20}` on a `value` input | a literal: `20`, `"text"`, `True` | `Value` (a negative number may persist as `Expression`, **Not yet tested**; a literal on a column or table input persists as `Expression`) |
| `{"value": "2024-01-31"}` on a Date, DateTime, Time or TimeSpan input | a constructor call: `Date(2024, 1, 31)` | `Expression` |
| `{"expression": "..."}` | as given | `Expression` |
| `{"table": "T", "column": "C"}` | `[T].[C]` | `Column` |
| `{"table": "T", "columns": "*"}` | `$map("[T].$esc($csearch([T],"*"))",",")` | `Table` |
| `{"table": "T", "columns": ["A", "B"]}` | `[T].[A], [T].[B]` | `Columns` |
| `limitByMarking`, `limitByFiltering` | `Selections` (markings, filtering selections) and `IncludeActiveFiltering` | |

An output table has `ColumnProducers: ExternalColumnProducer { ProducerKey, NeedsRefreshComputer ->
DataFunctionImpl, Context }`; its rows are embedded with the document (section 11).

Checks: the three names equal the spec name (none is `Untitled`); every property-bound input's
expression is `DocumentProperty("<the parameter's own name>")`; parameter kinds and allowed types;
output kinds and targets; `UpdateBehavior` = `refresh`; the code; the stamp; no credential-like
constants.

## 11. Tables, columns and embedding

```
DataManager.Tables: DataTableCollection { Items.Nodes[] DataTable "<name>", DefaultTable -> DataTable }   <- Tables.DefaultTableReference
DataTable
  Id: Guid, Name
  Columns.Items.Nodes[] DataColumn "<name>" { DataType -> DataType "<Type>", Source: SourceColumnImpl | CalculatedColumnImpl | HierarchyColumnImpl | TagsColumnImpl }
  DataPropertyContainer.ListenableProperties["description"].AssignedValue       <- table.Properties.SetProperty("Description", text)
  ColumnProducers[]:
    SourceColumnProducer { DataFlow { DataSource: SbdfFileDataSource | TextFileDataSource { FilePath, DataOriginIsStream, Settings: TextDataReaderSettings }, DocumentTitle, Transformations },
                           ProducerKey, CachingBehavior: DataCachingBehavior.Linked | Cached | Embedded }
    ExternalColumnProducer                                                       data-function output
  AutoCreateFilters, IncludeInAxisControls, PreferredSorting
DataColumn
  Source.DataPropertyContainer.ListenableProperties["description"].AssignedValue <- DataColumnProperties.Description
  Source.DataPropertyContainer.ListenableProperties["formatter"].AssignedValue: RealNumberFormatter | IntNumberFormatter | DecimalNumberFormatter { Category: Custom, FormatStringV40 } | DateTimeFormatter { FormatString }
                                                                                 <- DataColumnProperties.Formatter
  calculated: Source: CalculatedColumnImpl { OwnedColumnProducer: CalculatedColumnProducer { ExpressionTexts.Expression } }   <- table.Columns.AddCalculatedColumn(name, expression)
  hierarchy:  Source: HierarchyColumnImpl { OwnedColumnProducer: HierarchyColumnProducer { ExpressionTexts.Expression: "CREATE Nested Hierarchy [<name>] ..." } }   <- table.Columns.AddHierarchyColumn(name, definition)
DataManager.PersistentData
  SaveSettings: DataSaveSettings { embedAllSourceData, tableSettings: List<DataTableSaveSettings> { tableId, useLinkedData, reuseSettingsWithoutPrompting, CacheCalculatedColumns } }
                                                                                 <- Document.Data.SaveSettings.DataTableSettings
  EmbeddedDataTables: PersistentDataTable2[] { Columns: PersistentDataColumn2[] { Name, DataType, Properties, ColumnId }, ResultProperties, TableId }
  EmbeddedCacheItems { ProducerItems: PersistentProducerItem[] { Key (= a ProducerKey), Index }, DataItems }
```

- **Embedded**: PASS when the table's save entry (`tableId` = `DataTable.Id`) has
  `useLinkedData: false`, or its source producer has `CachingBehavior: DataCachingBehavior.Embedded`
  (persisted values: Linked 0, Cached 1, Embedded 2); FAIL on `Linked` for a file table with
  `embed: true`. Each embedded table's rows are the archive entry `DataTables/<TableId>`; the
  producer is linked to them through `EmbeddedCacheItems.ProducerItems` (`Key` = its `ProducerKey`,
  `Index` into `EmbeddedDataTables`, INFERRED). Data-function output rows travel this way even
  when the save entry says linked.
- **CSV settings** persist as `culture`, `separator` (a tab is `_x09`), `columnNameRows`,
  `typesRow -1`, `dataTypesGivenName {name: DataType}`, `codePage`.
- **Paths**: `FilePath` keeps the absolute source path even for an embedded table; a stream source
  keeps a temp spool path (`DataImport-<n>\*.tmp` under the user's temp folder) with
  `DataOriginIsStream: true`. Both contain the user's name, and the hygiene scan reports them.
- **Column types**: `DataColumn.DataType` is authoritative; column order is the `Nodes` order.

## 12. Document properties

```
DataManager.PropertyRegistry.AnalysisProperties: Properties[] DataProperty "<Name>"
  ValueType -> TypeInfo
  DataType -> DataType "<Type>"
  Attributes: DataPropertyAttributes.IsPersistent, IsVisible, IsEditable, IsPropagated      (+ IsListValued)
  Name, LowerCaseName
  Value                     the current value (no separate default); list-valued: List<T>
  Description
Document.DataPropertyContainer: SingleInstanceDataPropertyContainer<Document>
  ListenableProperties: KeyValuePair<String, ManagedDataProperty>[]
    key "<lower-case name>" -> value: SingleInstanceDataPropertyContainer+SingleInstanceManagedDataProperty<Document> { DataProperty -> DataProperty "<Name>", Dependencies }
```

- Created by `DataProperty.CreateCustomPrototype(name, description, value, dataType, attributes)`
  and `Document.Data.Properties.AddProperty(DataPropertyClass.Document, prototype)`. Every custom
  property in saved files lives in `AnalysisProperties`; that API-created ones land there too is
  INFERRED (`DataPropertyClass.Analysis` is obsolete).
- Attribute values: IsStandard 1, IsPersistent 2, IsVisible 4, IsEditable 8, IsListValued 16,
  IsPropagated 64. Custom properties have 78 (`DataProperty.DefaultAttributes` 14 | IsPropagated),
  list-valued 94; built-ins carry `IsStandard`.
- `ListenableProperties` holds an entry only for a property something references (a control, a
  trigger, a binding), keyed by the lower-case name: controls and triggers point at that managed
  node. Do not require one for every property.
- Built-ins in every analysis: `Description`, `Keywords` (`List<String>`), `AllowWebPlayerResume`,
  `PublicBookmarkCreation`, `PrivateBookmarkCreation`, `spotfire.Comments`,
  `spotfire.versioning.enabled`, `Spotfire.Versioning.Pruning.MaxVersions`, `MaxMissingTimeParts`
  (500000), `FiscalYearOffset` (0), `Preview.Thumb` (binary, resource `EmbeddedBinaryData`),
  `Preview.Mode`. `Document.Properties.Description` and `.Keywords` write the first two, which
  `AnalysisMetadata.json` repeats.
- Checks: each spec property exists once (case-insensitive) with `DataType`, value type and value
  (Real `72.0` persists as a Double), `Attributes` and `Description`; each `PropertyOutputImpl`
  names an existing property.

## 13. Markings, filtering schemes, relations

```
DataManager.Markings: DataMarkingSelectionCollection
  Items.Nodes[] DataMarkingSelection "<name>" { Name, EmbeddedSelections: ObjectReference<EmbeddedResource> Id, EmbeddedSelectionsCount,
                                                PartialSelections, Color: Color(#AARRGGBB), MarkingType: MarkingType.Standard }
  DefaultMarking: -> DataMarkingSelection                    <- Markings.DefaultMarkingReference
DataManager.Filterings: DataFilteringSelectionCollection
  Items.Nodes[] DataFilteringSelection "<name>" { Name, PartialSelections (one per table), FilterRelationConfigurations }   <- Filterings.Add(name)
  DefaultFiltering: -> DataFilteringSelection                read-only in the API: the builder renames the built-in scheme
Document.FilteringSchemes: FilteringSchemeCollection
  Items[] FilteringScheme { Items: FilterCollection[] (one per table, auto-created filters), DataSelection -> DataFilteringSelection "<name>", AutoConfigureFilterCollections }
DataManager.Relations: DataRelationCollection
  Items[] DataRelation { Expression, LeftTableName, RightTableName, LeftMapper, RightMapper }   <- Relations.Add(left, right, expression)
```

- A page's scheme: `FilterPanel.FilteringScheme -> FilteringScheme`, then
  `DataSelection -> DataFilteringSelection.Name`.
- Marking colors: spec `#E94165` persists as `Color(#FFE94165)`; a marking added through the API
  starts black.
- Each marking also owns an archive resource named after it with its marked rows (0 bytes when
  nothing is marked). A non-empty one, `PartialSelections` or `EmbeddedSelectionsCount > 0` is
  saved state: warn, do not fail.
- Relations: Analyst writes `([L].[a]=[R].[a]) And (...)`, the builder `[L].[a]=[R].[b] and ...`:
  compare the column pairs, not the text.
- Filters are created per table automatically; filter states are runtime state (not asserted).

## 14. Theme

```
Document
  UseCustomStyles: true | false                                   true once custom styles are applied
  CustomStylesJson: ObjectReference<EmbeddedResource> Id: k       resource "CustomStyles.json": the JSON verbatim (0 bytes when never set)
  KnownTheme: KnownTheme.LightSfx | DarkSfx | Light | Dark | None computed at save by comparing the style sheet with the built-in themes
  StyleManager { TooltipStyle "DarkTextOnWhite", StyleSheetText, ShowRelatedDataTablesIndicators }
```

- The theme has no public API. `dxpgen.py build` writes the `app.theme` custom styles to
  `build/theme.json` (with `general.baseTheme` and `general.baseThemeSfx` set to `app.theme.base`)
  and lists the theme as a manual step; you apply it in Analyst (the `styling-spotfire-dxps` skill
  covers themes).
- Checks: custom styles given but `UseCustomStyles` false is a WARN (the manual step is not done).
  Once applied, `UseCustomStyles` equals "custom styles given" and the parsed resource equals the
  parsed `app.theme.customStyles` with the base theme set (PASS or FAIL); a difference from the
  parsed `build/theme.json` is a WARN. Spotfire may store `general.baseTheme` under a normalized
  name while `baseThemeSfx` keeps the spec value. `KnownTheme` is informational (a custom theme may
  persist any value). Never compare `StyleSheetText`: it is the built-in sheet of the saving build
  (about 127 KB; one hash for every 15.0 file, another for 14.8).
- JSON shape: `{"general": {...}, "rules": [{"containmentNode": "<element>", "box": {...}}]}`; the
  `styling-spotfire-dxps` skill lists the keys.

## 15. Mods

```
InternalContent: ModVisualization "main"                          TypeId "Spotfire.Mod"
  Data (section 6), Legend
  ColorAxis "Color" { ExpressionTexts.Expression }                <- ModDataViewVisualization.ColorAxis (spec axis "Color")
  AxisCollection.Axes: KeyValuePair<String, ModAxis>[] { ModAxis { Name, ExpressionTexts.Expression, CategoryMode, Placement, ShowAxisSelector, IsOptional } }
                                                                  <- ModVisualization.Axis(name).Expression
  Properties: KeyValuePair<String, ModProperty>[] { StringModProperty | BoolModProperty | IntModProperty | DoubleModProperty { Name, Value } }
                                                                  <- ModVisualizationBase.Property[T](name).Value
  Metadata: "{\"id\":..,\"name\":..,\"type\":\"Visualization\",\"version\":..,\"apiVersion\":..,\"hash\":\"sha512=..\"}"
  ModReference -> ManagedVisualizationMod
Document.ModManager.ManagedMods[]: ManagedVisualizationMod | ManagedActionMod { ModId, ModOrigin { Origin: ModOrigin+OriginValue.File | ManifestFile | Library | Upload, Value, LibraryId, LibraryUri } }
```

- Archive `Mods/mod-<n>.asice` per embedded mod; `AnalysisMetadata.json` lists it under
  `Spotfire.EmbeddedMod`. The persisted metadata adds `"type":"Visualization"`, which is not part of
  the author's manifest.
- The builder adds a mod visual only when the mod is embedded, installed or pinned; otherwise it
  puts a text area showing `[mod: <modId>]` where the visual goes.
- Action mods are added by hand. A button or visual action trigger that runs an action-mod script
  persists its `ManagedScript.ScriptDefinitionReference` as
  `ActionModScriptDefinitionReference { ScriptModReference -> ManagedActionMod, Id (the manifest script id), Configuration { Name, ScriptArguments } }`;
  an IronPython or JavaScript script has a `ManagedScriptDefinitionReference` there (section 8).
- Checks: `Metadata.id` = spec `modId`; axes (a list is joined with `", "`) and properties as in
  the spec; an embedded mod that no visual uses is an orphan; a placeholder text area showing
  `[mod: <modId>]` is a FAIL that points to the manual step. A mod loaded from its project folder
  or a `.mod` file (`ModOrigin` `ManifestFile` or `File`) keeps that local path in `Value`: the
  hygiene check WARNs and names the fix. Each spec action trigger without a matching trigger on the
  visual is a WARN (manual step not done); a matching one is checked with its arguments (PASS or
  FAIL). Details: [api-mods.md](api-mods.md).

## 16. Reading a built DXP

1. Open the ZIP and read `Metadata.xml`: `CompatibilityVersion`, the version-to-entry map,
   `SavedByAssemblyFileVersion`.
2. Parse `AnalysisDocument.xml` with `scripts/sfgraph.py` (`Graph`); resolve every `ObjectRef`
   before comparing. Read `EmbeddedResources.xml` (Id -> entry) and `EmbeddedScripts.xml` (strip
   the BOM; `ManagedScriptId` -> definition); parse each `DataFunctionDefinition.Data` string as XML.
3. Map spec ids to persisted objects with the `created` block of `build/build-report.json` (slim
   and full tiers): `pages[title]` = Page Guid, `visuals[id].guid` = Visual Guid, `layouts`,
   `tables`, `properties`, `scripts`, `dataFunctions`, `markings`, `filteringSchemes`, `relations`
   (a list), `mods`. Without a report, match pages by title and visuals by page, title and
   `TypeId`. Controls and triggers you added by hand are matched by their content (sections 8, 9).
4. Compare the fields of sections 5 to 15: expressions byte-exact after decoding, colors as ARGB,
   Single values with a tolerance.
5. Run the hygiene checks over every archive entry, all document versions included: local paths,
   user names, credential-like strings, auto names and the naming policy.
6. Ignore what Spotfire adds by itself: `DetailsOnDemandPlots`, auto-created filters and their
   states, `AxisConfiguration`, `KeptOldExpression`, `PreProcessedExpression`, `ScaleLabels`,
   `AutomaticColorAssignment`, `LoadInfo`, `DataPanel`, `StyleSheetText`, `HasDynamicLayout`,
   `PanelRegionSpan*`, `AdditionalSettings`, `DataTableGroupCollection`, `Highlight`, `AllRows`,
   `NoRows` and the built-in document properties.
