---
name: building-action-mods
description: Builds and reviews Spotfire action mods (Spotfire 15.0, action API 2.5) in plain JavaScript. Covers the manifest, script files with RegisterEntryPoint, typed parameters, .NET interop from JavaScript, icons, wiring scripts to text-area buttons and to visual floating, title-bar and context-menu buttons, splitting work with IronPython property triggers, and connecting, updating and publishing the mod. Ships a tested four-script example with a type check against the official typings, a mock-based scenario test and a manifest checker. Use when creating, fixing, testing or wiring an action mod, adding buttons to visuals, or replacing IronPython buttons with action-mod scripts.
compatibility: Spotfire Analyst 15.0. Node 22.12+ for the type check and scenario test; Python 3.10+ for the manifest checker.
metadata:
  maturity: Assembled from proven parts, not run as a whole
  spotfire: "15.0"
---

# Building Spotfire action mods

An action mod is a signed package of JavaScript scripts that change the analysis through the
Spotfire API: write properties, open pages, clear markings, run data functions. Users run them
from text-area buttons and from buttons and menu items on visuals. Action mods need Spotfire
15.0 (action API 2.5).

## When to use one

- A button on a visual (floating, title bar, context menu): only action-mod scripts can be put
  there. Title-bar buttons render only for action-mod scripts, never for IronPython (Analyst
  15.0).
- A button with an icon, or one action reused across analyses from the library.
- Work that is easier to test outside Spotfire: the scripts type-check against the official
  typings and run against a mock.

Keep heavy logic in IronPython behind a property trigger and let the action write the property
(the `writing-spotfire-ironpython` skill). This split ran live in Analyst 15.0: the actions stay
small, the trigger keeps one code path for every host.

## Workflow

1. Copy `assets/pump-actions/` and rename the mod id, scripts and entry points. The mod id and
   script ids never change after release.
2. Write one file per script in `build/`: an IIFE that registers exactly the manifest's entry
   point with `RegisterEntryPoint`. The function is synchronous and receives
   `{document, <parameters>}`.
3. Give every script a description, a 16 x 16 SVG icon and `"wrapInTransaction": true`.
4. Check: `npm run check` (tsc against the 2.5 typings), `npm test` (scenarios against the mock),
   `python scripts/check_action_mod.py <project> --schema node_modules/@spotfire/mods-api/action-mods/schema.json`.
5. Connect it in Analyst (Mods development > Connect to file or development server), Disconnect to
   embed and sign it, wire the hosts, save.
6. For other users, publish it to the library and pin it.

## Rules

1. **Synchronous entry points.** `RegisterEntryPoint` takes a function that does not return a
   Promise; no `async`.
2. **One name per binding.** Script ids, entry points and parameter names are what hosts store;
   renaming one breaks every button that uses it. Parameter names are camelCase, or the property's
   exact name when the parameter carries a document property's value
   ([references/naming-standard.md](references/naming-standard.md)).
3. **Leave optional arguments out.** An empty optional argument stopped the action without an
   error in Analyst 15.0.
4. **One icon per script.** A visual button shows its script's icon, so two buttons that must look
   different need two scripts. Icons are drawn as given on light and dark chrome: use mid-tone
   strokes with 3:1 contrast on both.
5. **Name each configuration.** The configuration's name is the context-menu text and the button
   tooltip; without one, items of one script differ only by their argument values.
6. **Write only what changes.** Set a property only when its value differs, so its trigger runs
   once per real change. A command that must run on every click carries a fresh id.
7. **Errors:** a situation the user can fix (nothing selected) gets one sentence in a status
   property; anything else throws an `Error` with a short prefix, which rolls the transaction
   back (**Not yet tested** live).
8. **No local paths in delivered DXPs.** A mod connected from a folder stores the folder path; a
   customer package uses the library mod.

## The example: pump-actions

| Script | Parameters | What it does |
|---|---|---|
| `next-asset` | `assets` | writes the next pump of a comma list into `ViewAsset`; visuals filtering on `${ViewAsset}` follow |
| `go-to-page` | `pageTitle` | opens a page by title (exact, then without case and outer spaces) |
| `clear-marking` | `markingNames` | clears one or more markings in every table |
| `set-text-property` | `propertyName`, `propertyValue` | writes a String property only when it changes |

Results for this version: tsc `--checkJs --strict` clean against `@spotfire/mods-api` 2.5.0, 0
errors against the official action-mods schema, 41 scenario checks passed. `next-asset` is adapted
from an action that a build wired to a floating button on a mod visual in Analyst 15.0 (the saved
DXP passed its trigger and argument checks). None of the four scripts as written has run in
Spotfire: **Not yet tested**.

`tests/mock.mjs` mocks only the members these scripts use and follows the real API where it
matters (out parameters, `Get`/`Set` indexers, iterable collections, typed property writes).
Extend it with each new member you use, and keep the type check as the source of truth for the
API surface.

## References

- Manifest fields, parameter types, the script file, .NET interop, icons:
  [references/manifest-and-scripts.md](references/manifest-and-scripts.md)
- Hosts, configuration names, arguments, wiring by hand, the split with IronPython triggers,
  comparison with IronPython buttons: [references/hosts-and-wiring.md](references/hosts-and-wiring.md)
- Connect, update, publish, trust and signing:
  [references/connect-update-publish.md](references/connect-update-publish.md)

Spotfire 15.0 has no public API to wire an action-mod script to a button or visual trigger, so
wiring is a manual step in Analyst. For mod visuals, use the
`building-visualization-mods` skill; for a whole DXP, the `building-spotfire-dxps` skill.
