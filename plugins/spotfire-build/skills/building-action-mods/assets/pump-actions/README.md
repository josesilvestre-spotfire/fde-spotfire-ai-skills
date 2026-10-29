# pump-actions: an action mod example

Mod id `pump-actions`, version 1.0.0, apiVersion 2.5 (Spotfire 15.0), type action, no extra
capabilities. Plain JavaScript: Spotfire loads `build/*.js` as is, so no Node and no build step
are needed to use it. Node is used only for the checks.

| Script id | Entry point | Parameters | What it does | Icon |
|---|---|---|---|---|
| `next-asset` | `nextAsset` | `assets` (String, comma list) | writes the pump after the current one into `ViewAsset` | `icons/next-asset.svg` |
| `go-to-page` | `goToPage` | `pageTitle` (String) | opens a page by title; `StatusMessage` lists the pages when none matches | `icons/go-to-page.svg` |
| `clear-marking` | `clearMarking` | `markingNames` (String, comma list) | clears the markings in every table | `icons/clear-marking.svg` |
| `set-text-property` | `setTextProperty` | `propertyName`, `propertyValue` (String) | writes a String document property only when the value changes | `icons/set-text-property.svg` |

Every script has `"wrapInTransaction": true`. Never change a script id or a parameter name after
release: buttons and visual triggers are bound to them.

The analysis needs the document properties `ViewAsset` (String) and, optionally, `StatusMessage`
(String) shown by a label.

## Checks

```bash
npm install              # once; Node 22.12 or later; npm.cmd if PowerShell blocks npm.ps1
npm run check            # tsc --checkJs of build/*.js against the action-mod API 2.5
npm test                 # scenarios against tests/mock.mjs: ends with ALL SCENARIOS PASSED
python ../../scripts/check_action_mod.py . --schema node_modules/@spotfire/mods-api/action-mods/schema.json
```

`npm test` needs no packages. Results for this version: tsc clean, 0 schema errors, 41 scenario
checks passed. None of these scripts has run in Spotfire yet: **Not yet tested**.

## Use it in Analyst 15.0

1. Tools > Development > Mods development > Connect to file, and pick `mod-manifest.json` (or run
   `npm run server` and connect to the development server). The mod appears under In development.
2. Disconnect: Spotfire copies the files into the analysis, embeds the mod and signs it with your
   code-trust certificate.
3. Wire the scripts: a text-area action control (button or link) runs a script with values for its
   parameters; a visual gets a floating button, a title-bar button or a context-menu item through
   its action triggers.

Dialog labels can differ slightly between versions.
