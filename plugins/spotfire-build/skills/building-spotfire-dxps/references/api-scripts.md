# API reference: scripts, text-area JavaScript, property triggers

Owner: `scripts/lib/40_scripts.py` (the slim tier's library); the standard engine's
`scripts/engine/features/scripts.py` and `scripts/engine/features/textjs.py` use the same calls.
Spotfire Analyst 15.0 (core build 71.0.22206.3863), IronPython 3.4. Every member below is public and
verified with `scripts/sfapi.py has` (list: `scripts/lib/40_scripts.members.txt`). Newest member
used: `ScriptLanguage.IronPython3` [api 14.1]; nothing newer than 14.6.

Evidence tags: [API] signature verified against the API index; [DXP] seen in a saved analysis.
Behaviour not proven on a live Spotfire is marked **Not yet tested**.

## Functions

| function | does | on failure |
|---|---|---|
| `scripts_add_all(scripts)` | upsert each spec script, one `B.step("script", name)` each; returns `{name: ScriptDefinition}`; warns (never deletes) when the starting document already holds scripts outside the spec | step `failed` (public API: a spec problem to fix) |
| `script_def(name)` | registered IronPython `ScriptDefinition` named exactly `name` (JavaScript twins ignored) | raises |
| `attach_js(text_area, name, code, params=None)` | JavaScript on an `HtmlTextArea` (or its `Visual`) via `HtmlTextArea.Scripts`; returns the registered JS definition | raises; the caller (`80_textareas`) wraps it in `B.step` |
| `scripts_add_triggers(triggers)` | per spec entry, one `B.step("trigger", "<property> -> <script>")`: checks that the property and the script exist, warns when the script declares parameters, then records the trigger as a manual step (no public API adds a trigger) | fallback: the manual step, naming property, script and script file |

`B.created["scripts"][name] = {language, action: added|unchanged|replaced, parameters, transaction, file}`;
JavaScript entries `{language: "JavaScript", parameters, textAreas: [titles]}` (key `"<name> [JavaScript]"`
when an IronPython script has the same name). Triggers are never created: `build-report.json` lists
each as a fallback with its manual step.

## R1 Upsert an IronPython 3 script [public]

```python
items = List[ScriptParameter]()
items.Add(ScriptParameter("threshold", "Alert limit", ScriptParameterType.Real))
wanted = ScriptDefinition.Create(name, description, code, ScriptLanguage.IronPython3,
                                 ScriptParameterCollection(items), transaction)
existing = [sd for sd in Document.ScriptManager.GetAllScriptsWithName(name) if not is_js(sd)]
if not existing:                          Document.ScriptManager.AddScriptDefinition(wanted)
elif existing[0].IsEquivalentTo(wanted):  pass                                   # keep, unchanged
else:                                     Document.ScriptManager.Replace(existing[0], wanted)
```

- `ScriptDefinition.Create(String name, String description, String scriptCode, ScriptLanguage, ScriptParameterCollection, Boolean wrapInTransaction)` [api 12.0] is the only factory (no public constructor); definitions are immutable (`With*` returns an unregistered copy).
- `parameters` must be a collection, never None: Create enumerates it.
- Create validates the name (not empty, none of `\ / " : * ? < > |` or U+0000-U+001F) and the IronPython parameter names (`^[_A-Za-z][_a-zA-Z0-9]*$`, not a Python keyword: `False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield`). The module pre-checks these for clear messages.
- Parameter types: the 14 static properties of `ScriptParameterType` (`String Integer LongInteger Real SingleReal Boolean Date DateTime Time TimeSpan Currency Page Visualization DataTable`); `Name` equals the property name [API].
- `IsEquivalentTo` compares Name, Description, ScriptCode, Language, Parameters and WrapInTransaction, not approval stamps. "unchanged" keeps the existing object (and its stamp).
- `Replace(old, new)` keeps the script's place in the document, so buttons and triggers that run the script keep working and run the new code.
- Create stamps the definition as approved for the current Windows user, so it runs at once for that user (proven on Analyst 15.0); other users get Spotfire's trust prompt. In the saved XML the stamp is a DPAPI blob that starts `AQAAANCMnd8BFdERjHoAwE/Cl+sB` [DXP].

## R2 Look up the registered definition [public]

`GetAllScriptsWithName(name)` [api 12.0] returns the registered objects; take the first
non-JavaScript one (`sd.Language.Equals(ScriptLanguage.JavaScript)`; `ScriptLanguage` overrides
`Equals` [API]). `B.script` (`scripts/lib/00_core.py`) does the same. `TryGetScript` [api 3.3]
returns the first ordinal, case-sensitive match of any language; the standard engine's `textjs` part
uses it and refuses a non-JavaScript match. `Replace` and `Remove` match with
`ScriptDefinition.Equals`, which compares the serialized definition including the approval stamp, so
only the registered object works, never a freshly created look-alike.

## R3 JavaScript on an HTML text area [public]

```python
items, values = List[ScriptParameter](), Dictionary[String, String]()
for k in sorted(params):
    items.Add(ScriptParameter(k, "", ScriptParameterType.String)); values[k] = text(params[k])
wanted = ScriptDefinition.Create(name, "", code, ScriptLanguage.JavaScript, ScriptParameterCollection(items), False)
sd = upsert_js(name, wanted)                       # see rules below
ta.Scripts.RemoveAt(i)  # for every earlier copy on this text area with the same name
ta.Scripts.Add(HtmlTextAreaScript(sd, values))
```

- `HtmlTextAreaScriptCollection.Add` throws unless the language is JavaScript, and registers the definition in `ScriptManager` only when no `IsEquivalentTo` match exists; the parameter values are stored as literal values per text area.
- JavaScript parameters must be `ScriptParameterType.String` and valid JS identifiers (not reserved words). Non-string spec values are JSON-encoded (`true`, `12`, `{"a":1}`).
- Upsert rules (avoid near-duplicate definitions): first use of a name in a build upserts (a stale definition from an earlier build is replaced in place); a later use with equivalent code and parameters shares the definition (parameter values stay per text area); a later use with different code gets its own definition with the same name plus a warning, because replacing would re-code the text areas already using it. Give different scripts different names.
- The script runs in the browser view after each full render of the text area, with Spotfire's jQuery in scope; it does not re-run when a control value changes. CSS that needs selectors goes in this way (write a `<style>` with a fixed `id` into `#style-container`), because the sanitizer strips `<style>` and `<script>` from HtmlContent (proven on Analyst 15.0; the `styling-spotfire-dxps` skill has the injector).

### R3 in the standard engine (`scripts/engine/features/textjs.py`, feature `textjs`)

No parameters (the stylesheet injectors need none): `ScriptDefinition.Create(name, "", code,
ScriptLanguage.JavaScript, ScriptParameterCollection(List[ScriptParameter]()), True)` (wrap
`True`), registered once per name (`ScriptManager.TryGetScript` first; a non-JavaScript script of
that name is an error), then `ta.Scripts.Add(HtmlTextAreaScript(sd, Dictionary[String, String]()))`
after the text area's single HtmlContent set. `HtmlTextAreaScript` is in
`Spotfire.Dxp.Application.Scripting` [API]. The builder reads the `.js` file from the app folder
(HOME) when it runs. dxpgen rejects a JavaScript name equal to an IronPython script name and one
name with two different codes.

## R4 Property-change trigger [manual step]

Spotfire 15.0 has no public API that adds a script trigger to a document property, so the builder
does not create one. Both tiers check what they can through the public API, then hand the trigger to
you:

- slim tier (`scripts_add_triggers`): `B.prop(name)` (`DataManager.Properties.TryGetProperty`) and
  `script_def(script)` must succeed; a trigger script that declares parameters is warned (a spec
  trigger passes no arguments); the step then ends in its fallback, which the library writes to
  `build-report.json` and `MANUAL-STEPS.md` next to the saved DXP.
- standard engine: the trigger is an item of APP `"manual"`. The builder adds the script like any
  other, logs `TODO trigger <property> -> <script>: ...`, and dxpgen writes the same instruction to
  `build/MANUAL-STEPS-<tier>.md`.

The instruction: Edit > Document Properties > Properties, select the document property, click
Script..., choose to run a script when the value changes, select the script and click OK. When the
script is missing, add it first (IronPython 3) from its spec `file` or `code`.

Behaviour once the trigger is added (Spotfire 15.0):

- One script per property; the dialog replaces an existing one.
- The script runs when the property value changes, whatever changed it: a control, a script, or a
  data-function output (proven on Analyst 15.0). Setting the property from a script fires the
  trigger at once, so one click that sets several properties runs several trigger scripts.
- Trigger scripts are not part of Spotfire's data-function dependency graph, so a trigger that
  writes properties a function reads is not a "cyclic dependency"
  ([api-datafunctions.md](api-datafunctions.md)).
- Spotfire's dialog can pass arguments to the script (seen in saved analyses: a Visualization
  argument) [DXP]; a spec trigger passes none.
- A trigger script that re-triggers itself stops after 20 nested runs (**Not yet tested**).
- Spotfire runs property triggers only where the license feature "Spotfire Enterprise Player" is on.
  Analyst has it; check the consumer and Web Player groups (**Not yet tested**).

## Pitfalls

1. Duplicate script names are allowed: `AddScriptDefinition` never checks. Always upsert.
2. Never pass a look-alike to `Replace` or `Remove`: InvalidOperationException "The supplied
   ScriptDefinition object is not found in the ScriptManager".
3. `ExecuteScript(String code, ...)` writes script errors to its output stream instead of raising
   them; `ExecuteScript(ScriptDefinition, ...)` raises `ScriptExecutionException`; pass
   `ScriptLanguage.IronPython3` to the code overloads, the ones without a `ScriptLanguage` do not run
   IronPython 3 (**Not yet tested**). The module never executes scripts.
4. Pseudo-enums (`ScriptLanguage`, `ScriptParameterType`) are classes with static members: compare
   with `.Equals`, look up with `getattr` from an allowlist (`getattr(ScriptParameterType, "Name")`
   would return an instance-property descriptor).
5. Out parameters come back as tuples in IronPython:
   `found, sd = Document.ScriptManager.TryGetScript(name)`.
6. In the saved XML, control characters in script code are written as `_xHH` (a tab is `_x09`)
   [DXP]. Generate code with spaces.
7. Document property names are case-insensitive, script names case-sensitive. Keep one exact name
   per binding.
8. Generated document scripts never `print` (the `writing-spotfire-ironpython` skill); dxpgen and
   `scripts/lint_ipy.py` check spec scripts against the API index.

## Not yet tested

| item | smallest test |
|---|---|
| API-created scripts open trusted for the building user after save and reopen | reopen the built DXP, click a button (added from MANUAL-STEPS) wired to a built script; no trust prompt |
| JS parameter values reach the script as variables named after the parameter | `attach_js(ta, "Probe", 'document.getElementById("p").innerText = msg;', {"msg": "hello"})`, HTML `<span id="p"></span>` |
| replacing a stale same-named JS definition on a re-run leaves one definition | run the builder twice in the same (non-blank) document with changed JS; Document Properties > Scripts lists the name once |
| a trigger added by hand on a property written by an automatic, marking-limited data function fires on every marking change and is not reset by closing the Document Properties dialog | build an app with that pattern, add the trigger from MANUAL-STEPS, save, reopen, mark rows: the properties the trigger writes follow |
| standard engine: text-area JavaScript attached once per name runs on every host text area | an app with the stylesheet injector on several pages: every page shows the styled look; Document Properties > Scripts lists the injector once |

## Persisted structure (what verify_dxp reads)

- Scripts: archive resource named `EmbeddedScripts.xml` (`EmbeddedResources/<k>.emb`,
  `ScriptManager.EmbeddedScripts: ObjectReference<EmbeddedResource> Id: k`):
  `<EmbeddedScript ManagedScriptId="<guid>"><ScriptDefinition Name=".." LanguageName="IronPython" LanguageVersion="3" WrapScript="true|false"><Description/><Parameters><ScriptParameter Name=".." TypeName="Real|String|Page|..."><Description/></ScriptParameter></Parameters><ScriptCode>..</ScriptCode><ApprovalStamp>..</ApprovalStamp><AdditionalApprovalStamps/></ScriptDefinition></EmbeddedScript>` [DXP].
  JavaScript: `LanguageName="JavaScript" LanguageVersion=""`, parameters all `TypeName="String"`
  (**Not yet tested** against a saved file).
- Object graph: `ScriptManager.ManagedScripts: ManagedScriptDefinition[n]`, each with only a hidden
  `DocumentNodeId` = the `ManagedScriptId` above (that is the link to the name and code) [DXP].
- Trigger (added by hand): `ScriptManager.ScriptEventHandlers: PropertyChangedScriptEventHandler[n] { DataPropertyReference -> SingleInstanceDataPropertyContainer+SingleInstanceManagedDataProperty<Document>, ScriptReference: ManagedScript { ScriptDefinitionReference: ManagedScriptDefinitionReference { ScriptReference -> ManagedScriptDefinition, ScriptArguments: [] } } }`; the property name comes from `DataPropertyContainer.ListenableProperties["<lowercase name>"].DataProperty -> DataProperty "<Name>"` [DXP, 14.6 and 15.0 files].
- Text-area JavaScript: `HtmlTextArea.CustomJavaScripts: ManagedJavaScriptCollection { Items: ManagedJavaScript[n] { ScriptApplication: ManagedScript { ScriptDefinitionReference { ScriptReference -> ManagedScriptDefinition (JavaScript), ScriptArguments: KeyValuePair<String, ManagedScriptArgumentValue>[] (literal values) } } } }` (**Not yet tested** against a saved file).
- Checks per spec item: script exists exactly once by name; `LanguageName/Version` =
  IronPython/3; `WrapScript` = `transaction`; parameters in spec order with name, `TypeName` and
  description; description; code equal after XML unescape, `_xHH` decode (pattern
  `_x((0+[0-9])|(0+[B-C])|(0+[E-F])|(1+([0-9]|[A-F]))|XX)`) and newline normalization;
  `ApprovalStamp` present. Per trigger: a missing handler is a WARN (the manual step is not done
  yet); a handler whose property matches case-insensitively is checked for its script name (PASS or
  FAIL). Per text area: every `js` name reachable from its `CustomJavaScripts` (ScriptReference ->
  `ManagedScriptId` -> `EmbeddedScript` Name, LanguageName JavaScript). Hygiene: no duplicate script
  names; no scripts outside the spec except the JavaScript ones attached by the builder.
