# API reference: visualization mods

Owners: `scripts/engine/builders/mod.py` (kind `mod`: the main view and its layers) and
`scripts/engine/features/modload.py` (finds each mod) in the standard engine, converter
`scripts/t3/mod.py`; `scripts/lib/85_mods.py` (`vis_mod(page, vspec)`) in the slim tier. Spotfire
Analyst 15.0, IronPython 3.4. Public API only. The library's members are checked with
`scripts/sfapi.py has` (`scripts/lib/85_mods.members.txt`, setters in `scripts/lib/85_mods.set.txt`); the
engine parts declare theirs in `# @api` and `# @set` lines, which dxpgen checks at each build.

The `building-visualization-mods` skill writes visualization mods. Action mods are not built by this
skill: their buttons and visual action triggers are manual steps (see "Action mods" at the end), and the
`building-action-mods` skill writes action mods.

Evidence tags: [API] in the public API index; [DXP] seen in DXPs saved by Analyst; **Not yet tested**
marks what has not run in a live Spotfire.

## Version

The builder needs Analyst 14.8 or later for these members. The saved DXP still opens in 14.6, because
15.0 also writes the 14.6 and 14.8 serializations [DXP: `FormatVersion 15.0;14.8;14.6`].

| member | [api] |
|---|---|
| `ModVisualization.Axis(String)`, `.AxesNames`, `.Axes`, `.ColorAxis`, `.HasColorAxis` (declared on `ModDataViewVisualization`) | 14.7.0 |
| `ModVisualization.Property<T>(String)`, `.Properties` (declared on `ModVisualizationBase`) | 14.8.0 |
| `ModVisualization.Layers`, `ModLayerCollection.AddLayer(String layerType, String title)`, `.Clear()`, `ModLayer` | 14.8.0 |
| `Document.ModManager`, `ModManager.GetVisualizationModsIncludingPinned()`, `.TryLoadVisualizationModFromLibrary(...)`, `VisualCollection.AddNew(ModIdentifier)`, `ModIdentifier.Id/Name/Version`, `ModProperty<T>.Value` | 14.5.0 |
| `LibraryItemType.VisualizationMod` | 14.4.0 |

## Steps

Standard engine: each item runs in `ok()`, which logs `FAILED <item>: <why>` when it fails and goes on.

| item | does |
|---|---|
| `viz mod <id>` | feature `modload`, before the pages: the listed mod (see "Find the mod"). Logs `OK viz mod <id> <version> (embedded or pinned)`, or a NOTE when the version differs from the project manifest's; not listed: FAILED plus `TODO viz mod <id>: <how to make it available>` |
| `<vid>: add mod <id>` | `page.Visuals.AddNew(ModIdentifier)`; when the mod is not listed or Spotfire refuses it: a placeholder text area and a TODO line |
| `<vid>: data` | main view: table, limiting expression (`WhereClauseExpression`), `UseActiveFiltering` |
| `<vid>: axis <name>`, `<vid>: property <name>` | the main view's axes (manifest order, then `Color`) and typed properties |
| `<vid>: legend` | only when the spec gives `legend` (absent keeps the manifest's default) |
| `<vid>: layers`, `<vid>: layer <title> ...` | when the spec gives `layers`: `Layers.Clear()`, then per layer its data, marking, axes and properties |
| `<vid>: check` | a NOTE when Spotfire reports a view as not valid (`IsConfigurationValid()`) |

Slim tier (`vis_mod`, group `visuals:<page>`, in order):

| step | target | on failure |
|---|---|---|
| `mod.find` | `<id>` | fallback: make the mod available and run again. The visual becomes a placeholder text area showing `[mod: <modId>]`, so the layout keeps its slot |
| `mod.add` | `<id>` | fallback: add the mod by hand. Placeholder as above |
| `mod.placeholder` | `<id>` | failed (the visual is missing; the page layout places the rest) |
| `mod.table` | `<id>` | failed (a missing table is a spec error) |
| `mod.axis` | `<id>/axis:<name>` | fallback naming the axis and expression. A null value is `skipped` |
| `mod.property` | `<id>/property:<name>` | fallback naming the property and value. A null value is `skipped` |
| `mod.common` | `<id>` | `vis_common(visual, content, vspec)` from `scripts/lib/60_charts.py` |
| `mod.check` | `<id>` | `IsConfigurationValid()` False becomes a warning, not a failure |

The library records `B.created["mods"][<id>] = {modId, name, version, source: "available" | "library",
libraryPath, placeholder}`. A `coloring` field on a mod visual becomes a fallback that carries the
coloring JSON (there is no coloring contract for mods). `referenceLayers` and `fittingModels` are
`skipped`: mods have none. The slim tier builds no layers: `--tier slim` stops on a mod visual with
`layers`.

## Find the mod [API]

```python
for mid in Document.ModManager.GetVisualizationModsIncludingPinned():
    if mid.Id == mod_id:          # manifest id, exact ordinal match
        break
```

- `GetVisualizationModsIncludingPinned()` [api 14.5] lists the mods embedded in the document first, then
  the installed and pinned mods whose ids are not listed yet, so an id appears once.
- The standard engine takes the listed mod with the version of the project's `mod-manifest.json`, else a
  listed mod of another version with a NOTE line. Nothing listed: a FAILED and a TODO line, and each
  visual of that mod becomes the placeholder text area `[mod: <id>]`. The build goes on.
- There is no public member that loads a `.mod` file or a `mod-manifest.json`. Spotfire signs embedded
  mods when it saves (`Mods/mod-<n>.asice`, ASiC-E, signed with the user's code-trust certificate) [DXP],
  so a mod container cannot be made by hand.

Make the mod available before you run the builder, by one of these routes:

1. Pin or install the mod in your Spotfire library.
2. In the new analysis with starter data, add the mod once (Tools > Development > Mods development >
   Connect to file and pick its `mod-manifest.json`, or drag its `.mod` file onto the page), keep the
   visual it adds on the starter page, then run the builder in that analysis. An app with mod visuals
   removes the starter pages only after its own visuals exist, so the mod stays in use. **Not yet tested**
   as a builder route.
3. Slim tier only: save the mod to the Spotfire library (next section).

## Library route (slim tier) [API]

```python
library = Application.GetService[LibraryManager]()
items = library.Search("type:visualizationmod", LibraryItemRetrievalOption.IncludePath)
cands = [i for i in items if i.ItemType == LibraryItemType.VisualizationMod and norm(i.Title) == norm(mod_id)]
ok, mid, error = Document.ModManager.TryLoadVisualizationModFromLibrary(newest(cands))   # tuple
assert ok and mid.Id == mod_id
```

- Library items carry no mod id, so matching goes by title. `norm` lowercases the text, keeps the
  alphanumeric words and drops generic words such as `mod`, `mods` and `spotfire`: `text-card-mod` matches
  a library item titled "Text Card", `pump-fleet-monitor-mod` matches "Pump Fleet Monitor". At most 3
  candidates are loaded, newest `LastModified` first, and each loaded mod's id must equal `modId`.
- The search keyword `type:visualizationmod` follows the pattern of Spotfire's other library type
  keywords (`type:dxp`, `type:sbdf`). **Not yet tested**.
- `TryLoadVisualizationModFromLibrary(LibraryItem, out ModIdentifier, out Exception)` [api 14.5] returns
  `(Boolean, ModIdentifier, Exception)` in IronPython. It embeds the mod in the document at once, so
  loading a candidate whose id does not match can leave an unused embedded mod; the library warns when
  that happens.
- `GetService[LibraryManager]()` is None, or `Search` raises, when no server is connected. The library
  reports "library: not available" or "search failed".

## Add the visual, data table, axes [API]

```python
mv = page.Visuals.AddNew(mid)                # ModVisualization (content); embeds the mod
mv.Data.DataTableReference = table           # before the axes: expressions resolve against it
axis = mv.Axis("Tile")                       # ModAxis, or None for an unknown name
axis.Expression = "<[Pump ID]>"
mv.ColorAxis.Expression = "<[Status]>"       # spec axis name "Color" (only when mv.HasColorAxis)
layout_visual = mv.Visual                    # Visual wrapper: title, layout
```

- `AddNew(ModIdentifier)` returns the content, not a `Visual`; IronPython picks the overload from the
  argument type. Use `.Visual` for the title and the layout. Proven on Analyst 15.0.
- The color axis is a regular `ColorAxis "Color"` and is not in `AxesNames` [DXP]. The spec key `Color`
  maps to it unless the manifest also has a normal axis named `Color`.
- An unknown axis name fails with the mod's axis list (`AxesNames` plus `Color`). The slim tier adds a
  case-insensitive "did you mean"; the standard engine accepts a case-insensitive match on `Axes`.
- Spec values: a string is one expression. A list is several expressions on one axis, joined with
  `", "`, and only works when the manifest axis allows multiple measures. `""` clears a continuous axis
  and `"<>"` a categorical one; the standard engine tries the other form when Spotfire refuses one.
  `null` leaves the axis as the mod configures it. Clearing with `""` or `"<>"` is proven on Analyst 15.0.
- The standard engine sets the axes in the mod's own order (`AxesNames`), then `Color`, and reads each
  expression back: a value that differs (whitespace and case aside) is a FAILED line.
- Expression style [DXP]: categorical `<[Status]>`, hierarchy `<[Station] NEST [Pump ID]>`, row level
  `<baserowid()>`, series names `<[Axis.Default.Names]>`. Continuous axes stay non-aggregated
  (`[Flow Rate (bbl/d)]`, not `Sum(...)`) when the manifest axis has `allowNonAggregatingMeasures: true`.
  Spotfire defaults dropped columns to `Sum()`: aggregate only where the mod expects it.
- `Axes`, `AxesNames` and `Properties` return array copies. Change the element nodes (`axis.Expression`,
  `prop.Value`), never the arrays.

## Typed mod properties [API]

```python
prop = mv.Property[String]("theme")          # None when missing OR the stored type is not String
prop.Value = "light"
mv.Property[Boolean]("showKpis").Value = True
mv.Property[Int32]("decimals").Value = 1
mv.Property[Double]("alarmLevel").Value = 1450.0
```

- Pass the `System` types `String`, `Boolean`, `Int32` and `Double` as the generic argument. The generic
  call works from IronPython 3.4 on the main view and on layers (proven on Analyst 15.0). The standard
  engine falls back to `MethodInfo.MakeGenericMethod` on the public `Property` method when IronPython
  refuses the generic call.
- `ModProperty<T>` is tagged DoNotUseOutsideAssembly, but `Value` carries ApiVersion 14.5 and is the
  documented setter [API].
- Standard engine: the type comes from the manifest (`string` String, `integer` Int32, `double` Double,
  `boolean` Boolean); a None property is a FAILED line (no property of that name and type), and every
  value is read back after the set.
- Slim tier: the type comes from the JSON value:

| JSON value | tried in order | saved as [DXP] |
|---|---|---|
| `true` / `false` | Boolean | `BoolModProperty` |
| integer | Int32 (when in range), then Double | `IntModProperty` / `DoubleModProperty` |
| number with a fraction | Double, then Int32 when integral (`5.0`) | |
| string | String (at most 102400 characters) | `StringModProperty` |
| object / array | compact JSON text (`sort_keys`) into a String property | `StringModProperty` |
| `null` | skipped (the manifest default stays) | |

- A wrong type fails with the stored type, for example "property 'theme' is String but the spec value
  true is Boolean". A missing name fails with the list of property names.
- Mods keep UI state in string properties (`slicerState`, `zoomState`, ...) [DXP]. Set them only for a
  deliberate initial state.

## Layers (standard engine) [API]

```python
mv.Layers.Clear()                                      # the spec gives "layers": exactly these
layer = mv.Layers.AddLayer("Series", "Readings")       # ModLayer [api 14.8]
if str(layer.Title) != "Readings":
    layer.Title = "Readings"                           # AddLayer does not always keep the title
layer.Data.DataTableReference = readings
layer.Data.WhereClauseExpression = '[Asset] = "${ViewAsset}"'
layer.Data.MarkingReference = marking                  # AddLayer leaves a layer unmarked
layer.Axis("X").Expression = "[Timestamp]"
layer.Property[String]("role").Value = "raw"
```

- A layer is a data view of its own: table, limiting expression, filtering, marking, limiting markings,
  empty behavior, axes and properties. `ModLayer` has the same axis and property members as the main
  view (`Axis`, `Axes`, `AxesNames`, `HasColorAxis`, `ColorAxis`, `Property<T>`, `IsConfigurationValid`).
- The layer type is a manifest `layers[].type`; its axes and properties come from that layer entry of the
  manifest.
- Spec `layers` absent: the mod's own layers stay as Spotfire makes them. Given: `Layers.Clear()`, then
  one `AddLayer(type, title)` per layer, in order (`[]` removes every layer).
- The marking is always set, because a new layer has no marking: absent in the spec = the default
  marking; `null` = the layer cannot be marked. Limiting markings are added with
  `Data.Filterings.Add(marking)` when not already there; `LimitingMarkingsEmptyBehavior` follows
  `emptyMarkingBehavior`. A layer does not take the visual's limits.
- A limiting expression with `${...}` is read back; when it comes back without `${...}` the log gets a
  NOTE line.
- Proven on Analyst 15.0 in live builds: `AddNew(ModIdentifier)`, `Layers.Clear()`, seven
  `AddLayer(type, title)` layers on six tables, limiting expressions with `${...}` and
  `DocumentProperty(...)`, multi-measure axes with aliases, `<[Axis.Default.Names]>`, `BinByDateTime`, a
  layer marking, String layer properties, the title set again after `AddLayer`, and the legend off.

## Pitfalls

1. **Availability is the prerequisite.** Routes: embedded in the starting analysis, installed or pinned,
   in the library (slim tier), or none (placeholder plus a manual step that tells you to make the mod
   available and run the builder again).
2. **Local paths leak through mod origins.** `ModOrigin.Value` holds the `.mod` path (`File`) or the
   `mod-manifest.json` path (`ManifestFile`, from Connect to file) [DXP]. `verify_dxp` warns. Before you
   publish, embed the mod from the library (`Origin: Library`, `Value` is the library path) or through the
   development server (Connect to project, then Disconnect), and rebuild.
3. **Title.** A new mod visual is titled `${AutoTitle}`, which resolves to the mod name [DXP]. The builder
   writes the spec `title` over it.
4. **Marking.** A mod that marks (`dataView.mark` in its code) needs `Data.MarkingReference`, which comes
   from the spec `marking`. Limit-by-marking and `emptyMarkingBehavior` are the common fields.
5. **Mod colors.** Some mods paint with their own theme colors and ignore Spotfire colors; others read
   `row.color()`, so the Color axis expression matters.

## Not yet tested

| # | question | smallest test |
|---|---|---|
| M1 | `Axis(name)` returns None (not an exception) for an unknown name | `mv.Axis("nope") is None` |
| M2 | `AxesNames` leaves out the `Color` axis of a mod with a colorAxis | print `AxesNames` of such a mod |
| M3 | `type:visualizationmod` is the library search keyword, and an offline Analyst raises instead of prompting | `Application.GetService[LibraryManager]().Search("type:visualizationmod", LibraryItemRetrievalOption.IncludePath).Count` |
| M4 | A library-loaded mod that ends up unused stays embedded after save | TryLoad without AddNew, save, look at `ModManager.ManagedMods` in the DXP |
| M5 | A mod you have not trusted yet can be added without a blocking trust prompt | run the builder with a mod from another author |
| M6 | What `IsConfigurationValid()` checks for mods | configure only some required axes |
| M7 | A mod added to the starter page before the build is found and stays embedded after the starter pages are removed | route 2 above, then open the saved DXP |
| M8 | The standard engine's mod builder as a whole: the version check, the placeholder path, integer properties, layer `useFiltering: false` and limiting markings, `legend.hide` on a mod | build `assets/examples/mod-layers-demo` |

## Saved fields (for verify_dxp)

Visual (in `AnalysisDocument.xml` and the 14.8 and 14.6 copies):

- `Visual.InternalContent` is `ModVisualization "main"`, `TypeId "Spotfire.Mod"`.
- `Metadata`: a JSON string `{"id", "name", "type": "Visualization", "version", "apiVersion",
  "hash": "sha512=..."}`. Compare `id` with `modId`; the hash identifies the build of the mod the visual
  uses.
- `ModReference` points to a `ManagedVisualizationMod { ModId, ModOrigin { Origin, Value } }`.
- `Data.DataTable`, `Data.Marking`, `Data.Filterings[].Reference`, `Data.LimitingMarkingsEmptyBehavior`
  and `Data.WhereClauseExpression` (the common fields).
- `AxisCollection.Axes[]` (`KeyValuePair<String, ModAxis>`): `ModAxis { Name, ExpressionTexts.Expression,
  CategoryMode, Placement, ShowAxisSelector, IsOptional }`. Each spec axis is compared exactly (list
  values joined with `", "`).
- `ColorAxis "Color"`: `ExpressionTexts.Expression` (spec key `Color`).
- `Properties[]` (`KeyValuePair<String, ModProperty>`): `StringModProperty`, `BoolModProperty`,
  `IntModProperty` or `DoubleModProperty` `{ Name, Value }`. Object and array spec values are compared as
  parsed JSON.
- Layers: `LayerCollection.Items[]` -> `ModLayerContent { TitleExpression, Layer -> ModLayer { Type, Data,
  AxisCollection, Properties, ColorAxis } }`, in order. The verifier checks that the spec layers are
  exactly these (type and title, in order) and, per layer matched by title: table, marking, limiting
  markings and empty behavior, filtering, limiting expression, axes and properties.
- Placeholder case: the visual is an `HtmlTextArea` whose HTML contains `[mod: <modId>]`. The verifier
  reports FAIL for that visual and points to the manual step.

Document:

- `ModManager.ManagedMods[]`: `ManagedVisualizationMod { ModId, ModOrigin { Origin: File | ManifestFile |
  Library | Upload, Value, LibraryId, LibraryUri } }`. A `File` or `ManifestFile` origin `Value` is a local
  path (warned).
- Archive: `Mods/mod-<n>.asice`, one per embedded mod. The verifier FAILs a mod visual whose mod is not
  embedded (the DXP opens only where the mod is installed or pinned) or whose embedded build differs
  from the visual's hash, and compares every file the manifest lists with the project folder.
- `AnalysisMetadata.json`: `Properties[{Key: "Spotfire.EmbeddedMod", Value: ["<id>;<version>;<name>;sha512=<hash>", ...]}]`.
- An `EmbeddedMod` that no `ModVisualization` references is an orphan (M4 decides whether this happens).

## Action mods (manual steps)

The public API cannot add an action mod to an analysis or wire one to a host, so the builder does not
build them. The spec keeps `actionMods`, a control's `actionMod` and a visual's `actionTriggers`: dxpgen
validates them (against the project's `mod-manifest.json` when it exists) and writes one step each to
`build/MANUAL-STEPS-<tier>.md`; the builder logs each as a `TODO <what>: <how>` line.

- Action mod: "Action mod '<id>': add it to the analysis (pin or install it in your library, or Tools >
  Development > Mods development > Connect to file > `<project>/mod-manifest.json`), then wire the
  buttons and action triggers listed here to it."
- Visual action trigger: "Page '<page>', visual '<title>': Visualization properties > Action triggers >
  add a FloatingButton that runs the action '<script>' of the action mod '<mod>' with arguments ...,
  named '<label>'." (`display`: `FloatingButton`, `TitleBarButton` or `ContextMenuItem`.)
- Button or link with `actionMod`: the text-area control step names the IronPython `script` and adds
  that you can use the action-mod script instead once the mod is in the analysis
  ([api-textareas.md](api-textareas.md)).
- `verify_dxp check`: an action trigger the spec asks for and that is not added yet is a WARN; one added
  by hand is a PASS or a FAIL; triggers the spec does not ask for are warned.
