# Manifest rules

`mod-manifest.json` tells Spotfire what the mod is, which axes and properties it has and which
files belong to it. Spotfire reads it when you connect or reload the mod; code and CSS changes
hot-sync from the development server, manifest changes do not (Reload manifest).

## Pick the apiVersion first

Set the lowest `apiVersion` that has every API feature the mod uses. A client older than the
apiVersion cannot run the mod, and the manifest's allowed fields depend on it.

| Target | apiVersion | Notes |
|---|---|---|
| older field clients | `1.3` | no top-level `type`; `allowNonAggregatingMeasures` is `true` or `false`; `legendItem` takes only `defaultVisibility` |
| Spotfire 15.0 with layers | `2.4` | `"type": "visualization"`; layers (`mod.visualization.layers()`); the demo in this skill |
| Spotfire 15.0 action mods | `2.5` | see the `building-action-mods` skill |

Failures seen with field clients that enforced 1.3:

- A top-level `"type"` made the client report "Could not read mod".
- `"allowNonAggregatingMeasures": "prefer"` (a 2.x value) failed validation in several ways
  before the cause was clear. Use `true`.
- `legendItem.title` is not a 1.3 key.
- `dropTarget.icon` must come from the schema's list (`XAxis3D`, `YAxis3D`, `Line`, `Color`, ...);
  `LineByAxis` does not exist.

Validate against the schema of the matching API version. `@spotfire/mods-api` is versioned with
the mods API, so `@spotfire/mods-api@~2.4.0` has the 2.4 schema in
`visualization-mods/schema.json`. For 1.3, use the schema that ships beside the 1.3 examples in
the official spotfire-mods repository, not the current one, which steers you into 2.x fields.

```bash
python scripts/check_mod_manifest.py src --schema node_modules/@spotfire/mods-api/visualization-mods/schema.json
```

## Axes

```json
{"name": "Values", "mode": "continuous", "placement": "none",
 "allowMultipleMeasures": true, "allowNonAggregatingMeasures": "prefer",
 "dataTypes": {"allowNumeric": true},
 "propertyControl": {"title": "Values"},
 "legendItem": {"defaultVisibility": "hidden"},
 "automaticConfiguration": {"expressionHeuristics": "none"}}
```

- Give every axis a `propertyControl` title: it puts the axis in the visual's properties flyout.
- `placement: "none"` is valid for axes that are not drawn as a scale (identification and
  hierarchy axes, layer axes).
- `mode`: `categorical`, `continuous` or `dual`. Categorical expressions are written `<[Asset]>`,
  hierarchies `<[Station] NEST [Pump ID]>`, one row per element `<baserowid()>`.
- `expressionHeuristics: "none"` stops Spotfire from filling the axis on its own. A required axis
  with no expression then shows the mod's own placeholder.
- Point-per-row data needs `allowNonAggregatingMeasures` and an expression without aggregation
  (`[Flow Rate (bbl/d)]`). Spotfire puts `Sum()` on a column a user drops on a continuous axis, so
  the README tells users to set the aggregation to None.
- The color axis (`colorAxis` in the data view definition) is its own entry and is not in the list
  of named axes.

## Properties

Mod properties persist per visual in the DXP. Types: `string`, `integer` (32-bit), `double`,
`boolean`. A string property holds at most 102,400 characters; mods keep UI state there as JSON
(`slicerState`, `zoomState`).

## Layers (apiVersion 2.4)

```json
"layers": [
  {"type": "Series", "disableAddRemove": false,
   "properties": [{"name": "lineWidth", "type": "double", "defaultValue": 1.0}],
   "dataViewDefinition": {"axes": [...], "tooltip": {"enabled": false}}},
  {"type": "Records", "dataViewDefinition": {"axes": [...]}}
]
```

Each layer type has its own axes and properties. Each layer instance is its own data view: own
table, limiting expression, marking, filtering.

## Files and identity

- `files` lists every file Spotfire must store with the mod (`index.html`, `main.css`, `main.js`,
  ...). A file that is not listed is not embedded.
- `id` never changes between versions: DXPs find the mod by id. Raise `version` on every release.
- The `index.html` loader script (`<script id="spotfire-loader">`) is copied unchanged from an
  official example; never retype it.
