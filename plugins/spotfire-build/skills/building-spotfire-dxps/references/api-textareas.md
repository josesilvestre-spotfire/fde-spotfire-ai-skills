# API reference: HTML text areas, CSS injection, text-area controls

Owners: `scripts/engine/builders/text.py` with the feature parts `scripts/engine/features/controls.py`
and `scripts/engine/features/textjs.py` (standard engine; converter `scripts/t3/text.py`), and
`scripts/lib/80_textareas.py` (`vis_textarea(page, vspec)`, slim tier). Spotfire Analyst 15.0,
IronPython 3.4. Public API only. The library's members are checked with `scripts/sfapi.py has`
(`scripts/lib/80_textareas.members.txt`, setters in `scripts/lib/80_textareas.set.txt`); the engine
parts declare theirs in `# @api` and `# @set` lines, which dxpgen checks at each build. Nothing used is
newer than 14.6.

Evidence tags: [API] in the public API index; [DXP] seen in DXPs saved by Analyst; **Not yet tested**
marks what has not run in a live Spotfire.

## What the builder does with a text area

Standard engine (`build_text`, kind `text`):

1. Adds the visual with `page.Visuals.AddNew(VisualTypeIdentifiers.HtmlTextArea)`, then sets
   `Visual.Title` and `Visual.ShowTitle`.
2. Reads the HTML: a file under the app's `html/` folder, read when the builder runs, or inline HTML
   carried in the builder.
3. Feature `controls`: every `{{control:<id>}}` becomes a visible marker (see "Text-area controls").
4. Sets `HtmlTextArea.HtmlContent` once.
5. Feature `textjs`: attaches each `js` entry (see "CSS and JavaScript").

The standard engine does not take a text-area `css` field: dxpgen stops with "not in the standard engine
yet: use --tier slim". Put the CSS inside an injector JavaScript listed in `js`, or build with
`--tier slim`.

Slim tier (`vis_textarea`), steps in order:

| step (report name) | target | does | on failure |
|---|---|---|---|
| (unwrapped) | | `page.Visuals.AddNew(VisualTypeIdentifiers.HtmlTextArea)`, `visual.As[HtmlTextArea]()`, `Visual.Title`, `Visual.ShowTitle` | the visual step fails |
| `textArea.control` | `<vid>/<cid>` | no API call: one manual step per control, in placeholder order (unplaced controls after, sorted) | always a fallback: `[control: <cid>]` marker in the HTML |
| `textArea.html` | `<vid>` | `HtmlContent` set once: CSS prefix plus the HTML with markers | failed (library defect) |
| `textArea.css` | `<vid>` | safe mode only: the injector JavaScript "Inject `<Vid Words>` Styles" through `attach_js` | fallback; the code is saved to `build/textarea-js/<vid>-<name>.js` |
| `textArea.js` | `<vid>/<name>` | each `vspec.js` entry through `attach_js`, in spec order | fallback; the code is saved as above |
| `textArea.common` | `<vid>` | `vis_common(visual, ta, {id, type, title, showTitle, settings, postScript})`, last | failed |

- The injector name follows `app.namingPolicy`: text area `panelControls` gives "Inject Panel Controls
  Styles" (program) or "injectPanelControlsStyles" (camelCase).
- An HtmlTextArea has no `Data` (table, marking, limits, filtering), no `Legend` and no `Description`
  (`Visualization.Description` does not apply; the saved Visual holds only Id, TitleExpression, ShowTitle
  and InternalContent [DXP]). A spec `description` on a text area is warned and not stored.
- Report: `B.created["textAreas"][vid] = {htmlMode, css: "injected-js" | "style-block" | None, js: [names],
  controls: [], manual: [control ids]}`. Fallback features: `<group>.textArea.control`,
  `<group>.textArea.css`, `<group>.textArea.js`. The library writes `build-report.json` and
  `MANUAL-STEPS.md` next to the saved DXP.

## HtmlContent and control tokens [API]

- `HtmlTextArea.HtmlContent {get; set;}` [api 3.1]. Spotfire stores the string verbatim and sanitizes it
  when it renders, so the saved DXP holds exactly what the builder wrote.
- A control you insert in Analyst lives in the HTML as a token `<SpotfireControl id="<32 lower-case hex>" />`,
  with one space before `/>` [DXP]. The web view matches tokens literally: case, attribute order and
  spacing must stay as Spotfire wrote them. A lower-case `<spotfirecontrol>` or an extra attribute
  (`label="..."`) breaks the match.
- Spotfire deletes a control whose token is missing from the HTML when the file opens, and setting
  HtmlContent does the same (**Not yet tested** from a script). Once controls are added by hand, a
  script that rewrites HtmlContent must carry every token byte for byte.
- `${property}` is not substituted in text-area HTML. Show a property value with a Label property control.
- Placeholders: `{{control:<id>}}`, whitespace inside the braces tolerated. dxpgen requires every
  control to be placed exactly once and control ids without spaces or braces. The slim library keeps
  only the first of duplicate placeholders and appends an unplaced control at the end (both warned).

## Text-area controls: manual steps

Spotfire Analyst 15.0 has no public API that adds a property control or an action control to a text
area, so the builder does not create them. Instead:

1. Each `{{control:<id>}}` becomes a visible marker: a `<span>` with a red dashed border written with
   plain inline style values, so it survives the sanitizer.
   - Standard engine: `[<control type>: <property>]` for a property control
     (`[Drop-down list: SelectedPumpId]`), `[Button: <label>]` or `[Link: <label>]` for an action
     control, and `[control: <id>]` for a placeholder the spec does not describe.
   - Slim tier: `[control: <id>]` for every control.
2. `dxpgen.py build` writes `build/MANUAL-STEPS-<tier>.md` with one numbered instruction per control,
   page by page. The builder logs each item as a `TODO <what>: <how>` line in
   `build/build-log-<tier>.txt`, and the report tier's `MANUAL-STEPS-report.md` adds an "Add by hand"
   section with the same items. A FAILED line in the log is a separate problem.
3. You do each step in Analyst on the saved DXP, then save it.

A property-control step reads, for example: "Page 'Pump Overview', text area 'Controls' (controls):
Edit Text Area, delete the marker [Drop-down list: ViewMode] and, at that spot, Insert Property Control >
Drop-down list bound to the document property ViewMode with fixed values Hourly = H, Daily = D."
An action-control step reads: "... delete the marker [Button: Run Model] and, at that spot, Insert Action
Control > Button labeled 'Run Model' that runs the IronPython script 'Run Pump Model'."

How to do one step in Analyst:

1. Go to the page, right-click the text area and select Edit Text Area.
2. Delete the marker text and leave the cursor at that spot.
3. On the editor toolbar, open Insert Property Control and pick the control type the step names, or
   click Insert Action Control for a button or a link.
4. Property control: select the document property the step names and give the values it lists (fixed
   values as display text = value, unique values of a column, or the slider range). Action control:
   choose Button or Link, type the label as the display text, and add the action the step names (a
   script with its argument values, a page, a bookmark or a data function refresh).
5. Close the editor, check the control, and save the DXP.

| spec `kind` | Insert Property Control / Insert Action Control | marker (standard engine) | saved as [DXP] |
|---|---|---|---|
| `label` | Label | `[Label: <property>]` | `PropertyControl`, RenderType `Label`, no value provider |
| `input` | Input field | `[Input field: <property>]` | RenderType `TextBox` |
| `multilineInput` | Input field (multiple lines) | `[Input field (multiple lines): <property>]` | RenderType `MultiLineTextBox` |
| `dropdown` | Drop-down list, fixed values or a column | `[Drop-down list: <property>]` | RenderType `DropDown` |
| `listbox` | List box, fixed values or a column | `[List box: <property>]` | RenderType `ListBox` |
| `multiSelectListbox` | List box (multiple select); the property must be list-valued | `[List box (multiple select): <property>]` | RenderType `MultiSelectListBox` |
| `slider` | Slider with the range min to max and the step | `[Slider: <property>]` | RenderType `Slider` |
| `checkbox` | Drop-down list on the Boolean property, fixed values Yes = True, No = False | `[Drop-down list: <property>]` | RenderType `DropDown` |
| `radio` | List box (single selection, all options visible) | `[List box: <property>]` | RenderType `ListBox` |
| `button` | Insert Action Control > Button | `[Button: <label>]` | `ActionControl`, ViewMode `Button` |
| `link` | Insert Action Control > Link | `[Link: <label>]` | `ActionControl`, ViewMode `Link` |

- Spotfire has no check-box or radio-button property control: `checkbox` and `radio` stand for the
  substitutes in the table, and the step says so.
- dxpgen validates the binding before it writes the step: `multiSelectListbox` needs a list-valued
  property (`listValued: true`, error); a list-valued property on another value-setting kind is warned;
  `checkbox` needs a Boolean property and `slider` a numeric one (errors); a slider has `min` < `max`,
  `step` > 0 and at most 1000 positions (Spotfire lists at most 1000 values); `dropdown`, `listbox`,
  `multiSelectListbox` and `radio` need exactly one of `values.fixed` or `values.column`.
- A `slider` `showLabels: false` is warned and not part of the step: switch the range labels off in
  Analyst when you add the slider.
- Button and link actions in the step: `script` (with `args`: JSON values for String and numeric
  parameters, a page title for `Page`, a visual id for `Visualization`, a table name for `DataTable`),
  else `action.gotoPage`, `action.applyBookmark` (the step says to create the bookmark first when it does
  not exist: the spec cannot create bookmarks) or `action.refreshDataFunction`. `script` wins over
  `action`.
- A control `actionMod` (a button or link that runs an action-mod script) is also a manual step: the
  step names the IronPython `script` and adds "use the action of the action mod instead when the mod is
  in the analysis". The `building-action-mods` skill writes action mods; [api-mods.md](api-mods.md)
  lists the action-mod manual steps.

## CSS and JavaScript

- Safe mode (`app.htmlMode: "safe"`, the default) assumes Spotfire's default HTML sanitizer: it drops
  `<style>`, `<script>`, `<details>`, `<button>`, `<input>`, `<select>`, `<svg>` and `<section>` with
  their whole subtree (any control token inside included); a `div` with an `id` survives. CSS therefore
  goes in through a text-area JavaScript.
- Slim tier with `css`: the library prepends `<div id="style-container" class="sfdxb-style-<vid>"></div>`
  (unless the HTML has a `style-container` of its own) and attaches the injector JavaScript:
  - an IIFE with the style id `sfdxb-css-<vid>`; it returns when that id is already in the document,
    else it appends the style to its own container `div[id='style-container'].sfdxb-style-<vid>`. Only
    when the HTML brought its own container (no class): the first empty `div[id='style-container']`, else
    the last one, else `document.head`. The class keeps one text area from writing into another's
    container, whose re-render would drop the style.
- Text-area JavaScript runs after every full render of the text area (which rebuilds its DOM), not on
  control value updates. Spotfire runs it as a function body with its own jQuery as `$`. A re-render
  drops the old style with the old DOM and the script injects it again; the fixed id prevents duplicates.
  CSS is page-global: scope selectors under a panel class.
- Rich mode (`app.htmlMode: "rich"`): `<style>` + css + `</style>` is prepended. It renders only where
  the server has HTML sanitation turned off.
- Template pattern (standard engine): one host text area per page carries the stylesheet injector in
  `js`, and its HTML starts with `<div id="style-container"></div><div id="styleDivSF"></div>`. The
  injector appends its `<style>` once (guarded by a marker), so no other text area needs the divs or the
  script. The `styling-spotfire-dxps` skill holds the CSS template and the injector.

Attach a JavaScript to a text area [API]:

```python
from System import String
from System.Collections.Generic import Dictionary, List
from Spotfire.Dxp.Application.Scripting import (ScriptDefinition, ScriptLanguage, ScriptParameter,
                                                ScriptParameterCollection, HtmlTextAreaScript)
found, sd = Document.ScriptManager.TryGetScript(name)
if not found:
    sd = ScriptDefinition.Create(name, "", code, ScriptLanguage.JavaScript,
                                 ScriptParameterCollection(List[ScriptParameter]()), True)
    Document.ScriptManager.AddScriptDefinition(sd)
ta.Scripts.Add(HtmlTextAreaScript(sd, Dictionary[String, String]()))
```

- `HtmlTextArea.Scripts` and `HtmlTextAreaScript(ScriptDefinition, IDictionary<String, String>)` are
  [api 12.0]. `Scripts.Add` accepts JavaScript definitions only.
- Standard engine (`textjs`): registers each name once, attaches it after the text area's single
  HtmlContent set, reads a `.js` file from the app folder when the builder runs (inline `{name, code}` is
  carried in the builder), and logs one line per script and text area (`<id>: script <name>`). A
  JavaScript name must differ from every IronPython script name, and two text areas that list one name
  must list the same code.
- Slim tier: `attach_js(text_area, name, code, params=None)` in `scripts/lib/40_scripts.py`. Every
  parameter is a String parameter (other values are JSON-encoded); attaching a name again replaces the
  earlier copy on that text area.
- CSS hooks for the controls you add by hand (class names in the DOM Analyst 15.0 renders): action button
  `input[type=button].sfc-action-button`; link `a` (no class); input field `input[type=text]`; multi-line
  input `textarea`; drop-down `.sf-element-dropdown` (popup items `.sf-element-dropdown-list-item`); list
  boxes `.sf-element-list-box` and `.sf-element-list-box-item`; slider `.TextAreaSlider
  .sf-element-item-slider`; label: a bare `<span>` (wrap it in your own element). Drop-downs and list
  boxes are Spotfire widgets (`div.sf-element-*`), so a `select` selector never matches.

## Sanitizer rules (safe mode)

- Attribute values (`class`, `id` and others) keep only letters, digits, space and
  ``. , - _ # ' ` / %``; any other character removes the attribute.
- Inline `style`: plain values and `rgb()` / `rgba()` only. `var()`, `calc()`, `url()`, gradients and
  other function calls, or a `:` inside a value, drop the whole style attribute, not just the declaration.
- `<a>` takes no `style` (style a `<span>` inside it); `href` must be an absolute URI or `#...`;
  `javascript:` links are removed. External and `data:` images are removed (add images in Analyst).
- dxpgen validate checks safe-mode HTML against its emulation of Spotfire's default sanitizer
  (`--no-sanitize` skips the check).

## Pitfalls

1. Never rewrite HtmlContent of a text area that has controls without every token, byte for byte.
2. Lower-case `<spotfirecontrol>` or an extra attribute on the token breaks the control.
3. Drop-downs and list boxes are Spotfire widgets (`div.sf-element-*`), not `<select>`.
4. Text-area CSS and element ids are page-global: namespace classes and ids per panel.
5. HtmlTextArea has no Description, Data or Legend; do not pass those spec fields to code that sets them.
6. Run the builder before you add controls by hand: a rebuild makes a new DXP with markers again.

## Not yet tested

| item | smallest test |
|---|---|
| CSS injector: the style lands in its own container, is injected again after a re-render, no duplicates | resize the text area; one `style#sfdxb-css-<vid>` in the DOM |
| Text-area JavaScript attached by the builder, and its look in Web Player under the default sanitizer | open the saved DXP in Web Player |
| JavaScript parameter values reach the script as variables named after the parameter | attach a script with one parameter and log it |
| JavaScript and button scripts stay trusted after save and reopen | reopen the DXP; styles apply, buttons run without a trust prompt |
| Setting HtmlContent from a script removes a hand-added control whose token is missing | add a control by hand, set HtmlContent without its token, list `Controls` |

## Saved structure (what verify_dxp checks)

Visual `InternalContent: HtmlTextArea` (`TypeId "Spotfire.HtmlTextArea"`), Visual `ShowTitle` = spec
`showTitle`, `TitleExpression.Expression` = spec `title`. Per spec text area:

- `HtmlContent`: no `{{control:` left (FAIL otherwise); every `<SpotfireControl>` token resolves to a
  control (FAIL otherwise).
- Each spec control is either added by hand (PASS or FAIL on kind, bound property, fixed values, column,
  slider range, label, script and arguments, page, data function, bookmark) or still its marker (WARN:
  the manual step is not done yet). Neither control nor marker is a FAIL. A marker of an id the spec does
  not describe is a FAIL.
- Hand-added controls are matched to spec controls by kind and property (property controls) or by label,
  script or target page (action controls). A control without a token in the HTML and a control the spec
  does not describe are warned.
- A spec button with `actionMod`: when the hand-added button runs an action-mod script, the verifier
  compares that script and its arguments with `actionMod`; otherwise it compares the IronPython `script`.
- Safe mode with `css`: the HTML starts with `<div id="style-container" class="sfdxb-style-<vid>"></div>`
  unless the spec HTML has its own container, and the injector is the first attached JavaScript. Rich
  mode with `css`: the HTML starts with `<style>`.
- Each `js` name is attached. The HTML, with tokens and markers turned back into placeholders, equals
  the spec HTML (WARN on a difference).

Shapes in `AnalysisDocument.xml` that the verifier reads [DXP]:

- `Controls.Items[]`, `Id: Guid` (the token id with dashes).
- `PropertyControl { RenderType: RenderType.<X>, DataProperty -> SingleInstanceManagedDataProperty<Document> }`;
  the property is found in `DataPropertyContainer.ListenableProperties["<lowercase name>"]`.
- `ValueProvider`: `FixedValuesProvider { Values: FixedValueItem[] {Name, Value}, HasExpressionValues }`,
  `ColumnValuesProvider { DataColumnReference -> DataColumn "<column>" }`,
  `NumericalRangeValueProvider { Min, Max, Interval, ShowLabels }`, or null (label, input, multi-line input).
- `ActionControl { Label, ViewMode "Button" | "Link", ScriptApplication -> ManagedScript { ScriptDefinitionReference,
  ScriptArguments[] } | ActionLinkReference -> ActionLink { GotoPageDocumentOperation | ApplyBookmarkDocumentOperation }
  | DataFunctionReference -> DataFunction }`; `ActionLinks.Items[]` holds the links.
- `CustomJavaScripts.Items[]`: the injector (safe mode with css), then each `js` name, in order;
  JavaScript definitions in `EmbeddedScripts.xml` with `LanguageName="JavaScript"`.
- `IncludeInBookmark: false`, `BackgroundColor "#ffffff"` (defaults, untouched).

## Example fragment

`assets/examples/fragments/textareas.json` (pages "Pump Control Panel" and "Pump Panel Detail") with the
companion files `assets/examples/fragments/html/pump_control_panel.css`,
`assets/examples/fragments/html/Highlight Open Events.js` and
`assets/examples/fragments/datafunctions/count_open_pump_events.py`. It covers every control kind (each
becomes a manual step), both value sources, every action, script arguments of literal, Page and
Visualization type, safe-mode CSS and `js`. Its `applyBookmark` button ("Morning Review") needs the
bookmark first. The fragment has text-area `css`, so build it with `--tier slim`. Rich mode needs
`app.htmlMode: "rich"` and is not part of the fragment.
