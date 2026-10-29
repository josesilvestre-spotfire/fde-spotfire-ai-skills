# Manifest and script files

Spotfire Analyst 15.0, action-mod API 2.5. The official schema and typings are in the npm package
`@spotfire/mods-api` at `~2.5.0`: `action-mods/schema.json` and `action-mods/api.d.ts`.

## Manifest

```json
{
    "apiVersion": "2.5",
    "version": "1.0.0",
    "type": "action",
    "name": "Pump Actions",
    "id": "pump-actions",
    "description": "Buttons and menu items for a pump analysis.",
    "capabilities": [],
    "icon": "icon.svg",
    "scripts": [
        {
            "id": "go-to-page",
            "name": "Open page",
            "description": "Opens the page with the given title.",
            "icon": "icons/go-to-page.svg",
            "file": "build/go-to-page.js",
            "entryPoint": "goToPage",
            "wrapInTransaction": true,
            "parameters": [
                {"name": "pageTitle", "displayName": "Page",
                 "description": "Title of the page to open.", "type": "String"}
            ]
        }
    ]
}
```

| Field | Rule |
|---|---|
| `type` | `"action"` |
| `id` (mod and script) | letters, digits, `-`, `.`, `_`; never changes between versions (DXPs and buttons are bound to it) |
| `version` | raise it on every release |
| `entryPoint` | a JavaScript name, unique across all scripts of the mod |
| `file` | path of the script, relative to the manifest |
| `icon` | an SVG file; the mod icon and one per script |
| `wrapInTransaction` | `true`: the script runs in one transaction, so a click is one undo step |
| `capabilities` | only what the scripts need: `LibraryRead`, `LibraryWrite`, `AI` |
| `files` | extra files bundled with the mod as resources (`ActionModResource.LoadResource` in the typings) |

Parameters:

| Field | Rule |
|---|---|
| `name` | a JavaScript identifier; `document`, `application` and `resources` are reserved |
| `type` | `String`, `Boolean`, `Integer`, `LongInteger`, `Real`, `SingleReal`, `Currency`, `Date`, `DateTime`, `Time`, `TimeSpan`, `DataTable`, `DataColumn`, `Page`, `Visualization`, `DataViewDefinition` |
| `enum` | allowed values, String parameters only |
| `optional`, `range`, `array`, `allowedDataTypes` | see the schema |
| `displayName`, `description` | what the user sees when wiring the script |

Name parameters camelCase (`pageTitle`); a parameter that carries a document property's value
takes the property's name (the naming standard). An empty optional argument stopped an action
without an error in Analyst 15.0: leave the argument out of the button instead of passing "".

## Script file

```js
"use strict";
(() => {
    const { DataProperty, DataPropertyClass } = Spotfire.Dxp.Data;

    /**
     * @param {{document: Spotfire.Dxp.Application.Document, pageTitle?: string}} args
     */
    function goToPage({ document, pageTitle }) {
        // synchronous work only: no async, no Promise
    }

    RegisterEntryPoint(goToPage);
})();
```

- Spotfire loads the file as is: plain JavaScript, no modules, no imports. Wrap it in an IIFE so
  helpers stay private, and register exactly the entry point the manifest names.
- The entry point receives one object with `document` (the analysis) and one key per parameter.
  `application` and `resources` are reserved names.
- The entry point must be synchronous; `RegisterEntryPoint` refuses a function that returns a
  Promise (typings, API 2.5).
- `console.log(...)` writes to the script output and the progress dialog.
- Throw an `Error` with a short sentence when the action cannot do its job. With
  `wrapInTransaction: true` the click's changes are then rolled back and Spotfire shows the
  error (expected from the transaction; **Not yet tested** live). For a situation the user can fix
  (nothing selected), write one sentence to a status property instead and return.
- Each script file is loaded on its own, so shared helpers are copied into each file. When a mod
  has many scripts, keep the shared code in source blocks and assemble the files with a small
  build script; check that `build/` is current in the tests.

## .NET from JavaScript

| Need | Write |
|---|---|
| out parameter | `const out = OutParam.create(DataProperty); if (registry.TryGetProperty(DataPropertyClass.Document, name, out.out)) { out.value.Value }` |
| indexer | `document.Properties.Get(name)`, `document.Properties.Set(name, value)` |
| collections | `for (const page of document.Pages) { ... }` |
| .NET object | `new RowSelection(new IndexSet(table.RowCount, false))` |
| typed array | `TypedArray.create(System.String, ["a", "b"])` |
| .NET types | `System.DateTime.UtcNow`, `System.String` |

- A LongInteger parameter arrives as a JavaScript `BigInt`.
- A numeric document property takes a value of its own data type. Writing a JavaScript number
  into an Integer or LongInteger property needs a conversion
  (`DataType.TryConvertFromNumeric(value, out.out, type)`); that route is **Not yet tested** live.
- Type-check the plain JavaScript with `tsc --checkJs` against `action-mods/api.d.ts` (a
  `types/globals.d.ts` with `/// <reference types="@spotfire/mods-api/action-mods/api.d.ts" />`
  and a `tsconfig.json` that includes `build/*.js`). The example's `npm run check` does this.

## Icons

- 16 x 16 SVG (`viewBox="0 0 16 16"`), ASCII, one per script.
- Spotfire draws the SVG as given on light and dark chrome. Pick stroke colors with at least 3:1
  contrast on white and on a dark panel (`#2B2B2B`): mid-tones such as `#808080` and `#5B7BF5`.
- A visual button shows its script's icon, so two buttons that must look different need two
  scripts.
