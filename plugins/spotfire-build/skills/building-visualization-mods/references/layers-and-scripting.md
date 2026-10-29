# Layers and configuring mod visuals from IronPython

Spotfire Analyst 15.0. The IronPython members below are public (layers need 14.8 or later) and ran
in two live builds: one with seven layers on six tables, one with typed properties on the main view
and on layers.

## Layers in the mod (JavaScript, apiVersion 2.4)

```js
const reader = mod.createReader(mod.visualization.layers(), mod.windowSize(),
                                mod.property("heading"));
reader.subscribe(async (layers, size, heading) => {
    for (const layer of layers.items) {
        const [view, title, width] = await Promise.all(
            [layer.data(), layer.title(), layer.property("lineWidth")]);
        // layer.type: the manifest type; title.value: the layer's title;
        // width.value(): the property value
    }
});
```

- `layers(mode)`: `"EagerData"` (default) fetches every layer's data view with the collection;
  `"LazyData"` fetches when awaited; `"CollectionOnly"` invalidates only when layers are added,
  removed or reordered (use it with one reader per layer).
- `reader.hasReadableChanged(...)` tells which layer's data changed, to skip redrawing the rest.
- Find layers by title (unique within the visual), never by position.

## Find or add the mod visual

```python
from Spotfire.Dxp.Application.Mods import ModVisualization

def mod_visual(page, mod_id):
    for visual in page.Visuals:
        content = visual.As[ModVisualization]()
        if content is not None and content.ModIdentifier.Id == mod_id:
            return content
    for mid in Document.ModManager.GetVisualizationModsIncludingPinned():
        if mid.Id == mod_id:                 # embedded mods first, then installed or pinned
            return page.Visuals.AddNew(mid)  # returns the ModVisualization (content)
    return None
```

- A mod must be in the analysis (embedded), installed, or pinned before a script can add it.
  There is no public member that loads a `.mod` file or a `mod-manifest.json`: connect it in
  Mods development first, or load it from the library with
  `Document.ModManager.TryLoadVisualizationModFromLibrary(item)` (returns a tuple in IronPython).
- `AddNew(ModIdentifier)` returns the content. Use `.Visual` for the title and the layout.

## Table, axes and properties

```python
from System import Boolean, Double, Int32, String

mv.Data.DataTableReference = table          # first: expressions resolve against it
mv.Axis("Tile").Expression = "<[Pump ID]>"  # None for an unknown axis name
mv.ColorAxis.Expression = "<[Status]>"      # the color axis is not in AxesNames
mv.Property[String]("theme").Value = "light"
mv.Property[Int32]("decimals").Value = 1    # None when the name or the type does not match
```

- `Axes`, `AxesNames` and `Properties` return copies: change the axis or property objects, not
  the arrays.
- Pass the .NET type that matches the manifest type: `String`, `Int32`, `Double`, `Boolean`.
- Clear an axis with `""`; some categorical axes take `"<>"` instead.
- `${PropertyName}` in an axis or limiting expression stays live: the view is evaluated again
  when the property changes. An unknown property name leaves the view unable to evaluate.

## Layers

```python
mv.Layers.Clear()
layer = mv.Layers.AddLayer("Records", "Events")   # type from the manifest, title
if layer.Title != "Events":
    layer.Title = "Events"                        # AddLayer did not always keep the title
layer.Data.DataTableReference = events
layer.Data.WhereClauseExpression = '[Asset] = "${ViewAsset}"'
layer.Data.MarkingReference = event_pick          # a new layer has no marking
layer.Axis("Key").Expression = "<[Event ID]>"
layer.Property[String]("role").Value = "events"
layer.Data.UseActiveFiltering = False             # when the layer must ignore filters
```

- A layer does not take the visual's limits: set its table, limiting expression, filtering and
  marking itself.
- `IsConfigurationValid()` on the visual and on each layer reports a view Spotfire cannot
  evaluate (an axis without expression, a column the table does not have).
- A full example: `assets/demo-layers/Configure Demo Layers.py` (**Not yet tested** as a whole).

## Mod origin and delivery

A mod connected from a project folder stores that folder's path in the DXP (its origin). That is
fine for development; for a customer package, publish the mod to the library (Save as library
item in Mods development), pin it, and use the library mod in the analysis, so the DXP refers to a
library item and updates reach every analysis that uses it.
