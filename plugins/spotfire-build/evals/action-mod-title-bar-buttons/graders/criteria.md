---
type: llm
weight: 1
---

Grade the response and the files under `ranking-actions/`. Pass when all of these hold; list
every criterion that fails.

1. The response explains that title-bar buttons on a visual run action-mod scripts only, never
   IronPython scripts, so the solution is an action mod.
2. `mod-manifest.json` has `"type": "action"`, `"apiVersion": "2.5"`, an id, a version, a mod
   icon, and two scripts, each with a unique id, a unique `entryPoint`, a `file`, a description,
   its own icon and `"wrapInTransaction": true`.
3. Each script file is plain JavaScript that registers exactly its manifest entry point with
   `RegisterEntryPoint`; the entry point is synchronous (no `async`, no Promise) and takes
   `{document, ...parameters}`.
4. Parameters are declared with valid names (not `document`, `application` or `resources`) and
   types; the marking name and the page title are parameters or clearly named constants.
5. The clear-marking script clears the marking in every table it holds rows of (for example
   `SetSelection(new RowSelection(new IndexSet(table.RowCount, false)), table)`) and finds the
   marking by name with an out parameter (`OutParam.create(...)`).
6. The page script finds the page by title (not by index) and sets
   `document.ActivePageReference`; a missing page is reported, not silently ignored.
7. Icons are 16 x 16 SVG (`viewBox="0 0 16 16"`), one per script, with colours that stay visible
   on light and dark chrome; the response notes that each title-bar button shows its script's
   icon.
8. The test plan runs without Spotfire: a type check against the official
   `@spotfire/mods-api` action-mod typings (`tsc --checkJs`) and/or scenario tests against a mock,
   plus the manifest check (the skill's `check_action_mod.py` or the official schema).
9. Hooking up is described as manual steps in Analyst (connect the mod in Mods development,
   Disconnect to embed and sign, then add title-bar action triggers to the visual and select the
   scripts), with no code that calls non-public Spotfire classes or uses reflection.
10. The response mentions naming each configuration (the tooltip text) and leaving empty optional
    arguments out, or publishing the mod to the library for other users.
