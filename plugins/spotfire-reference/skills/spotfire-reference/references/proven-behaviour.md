# Proven Spotfire Analyst behaviour

Facts observed on a live Spotfire Analyst, with the version they were proven on and the symptom you
see when a script, data function or page gets them wrong. Everything here was proven on Spotfire
Analyst 15.0 (core build 71.0.22206.3863, bundled Python 3.14) on Windows 11 unless the row says
otherwise. The last section lists facts read from Spotfire's code that are **Not yet tested** live.

Before you rely on a fact on another version, check the member or behaviour on that version. The
API index (`api-index.md`) tells you whether a member exists; it does not tell you how it behaves.

Contents:

1. Python data functions
2. Document properties and IronPython scripts
3. Script speed
4. Text areas and the HTML sanitizer
5. Visuals and expressions
6. Maps
7. Markings and interaction
8. Visualization mods and action mods
9. Script trust
10. Files, data and saving
11. Read from Spotfire's code, not yet tested live

## 1. Python data functions

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| Analyst runs Python data functions in its own CPython 3.14 with numpy 2.4.4, pandas 2.3.3 and spotfire 2.4.2. torch and scipy are not bundled. | 15.0 | `ModuleNotFoundError` on a machine that has only the bundled packages, while the function runs on yours. |
| The user site folder of the same Python version (`%APPDATA%\Python\Python314\site-packages`) comes first on the data function's `sys.path`. Packages you installed there for your own Python 3.14 (pandas 3, for example) replace the bundled ones. | 15.0 | The same DXP gives different results or errors on different machines. Write code that runs on pandas 2.3 and 3, and expose `pandas.__version__` in a diagnostic output when results differ. |
| Under pandas 3 a text column has dtype `str`, which Spotfire's SBDF writer refuses. Convert every text output column with `.astype(object)`. An all-empty text column needs `pd.StringDtype("python")`. | 15.0 with pandas 3.0 | The output table is not created and no error is shown. Outside Spotfire, `spotfire.sbdf.export_data` fails with "unknown dtype 'str'". |
| A registered input that is not bound arrives defined and set to `None`. Default on `None` as well as on `NameError`. | 15.0 | `TypeError` from `int(None)`, or a default that never applies. |
| Integer input columns arrive as nullable `Int32` or `Int64`; missing values are `pd.NA`. | 15.0 (spotfire 2.4.2) | `TypeError: boolean value of NA is ambiguous` in comparisons and `if` tests. |
| Nullable `Int64`, `Int32`, `boolean`, `Float64` and `string` output columns export. An object column holding integers, a column of mixed types and an all-missing object column do not. Give every output column a concrete dtype, or pin types with `spotfire.set_spotfire_types(df, {"Pump Count": "LongInteger"})`. | 15.0 (spotfire 2.4.2) | The run fails with "cannot convert '1308' to Spotfire LongInteger type", "types ... do not match" or "cannot determine type". |
| A Python `int` scalar output arrives as LongInteger and a `float` as Real. Declare output document properties with those types or cast in the script. An Integer property fed a Python `int` is **Not yet tested**. | 15.0 | The output property keeps its old value or the binding reports a type mismatch. |
| Every registered output must be assigned on every code path, early-return and pass-through branches included. | 15.0 | "Output variable '<name>' was not defined". |
| A data function's output table exists only after its first run. | 15.0 | A visual, filter layout or control created on that table before the first run has nothing to bind to. |
| A document property cannot be both an input and an output of the same automatic data function. | 15.0 | Spotfire switches the function to manual refresh, and it stops reacting to changes. |

## 2. Document properties and IronPython scripts

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| Scripts run IronPython 3.4: no f-strings, walrus operator, type annotations, `async` or `{**x}`. Enum members named `None` need `getattr(Enum, "None")`; generic methods are called as `AddNew[LineChart]()`; .NET out parameters come back as a tuple. | 15.0 | `SyntaxError` when the script runs, or an error on `Enum.None`. |
| Document property names allow letters and digits in each dot-separated segment. No `_`, `-` or spaces; the `spotfire.` prefix is reserved. Names are matched without regard to case. | 15.0 | Creating the property fails, or two names that differ only in case resolve to one property. |
| A property value must have the exact .NET type: Real takes `72.0`, Integer a 32-bit integer, Date a `DateTime`. There is no numeric widening. | 15.0 | A type error when a script assigns `72` to a Real property. |
| `DataProperty.Description` has no setter. Set the description when you create the property. | 15.0 (API) | The assignment fails; a changed description needs a new property. |
| `Application.SaveAs` refuses to save while a transaction runs. A script started from the script editor with "Execute in transaction" ticked runs inside one. Untick the box for a script that saves. | 15.0 | "document is not idle" and no file. |
| Closing the script editor with Cancel undoes what the script changed in the open document. OK keeps the changes and stores the script in the analysis. | 15.0 | Changes vanish after Cancel (markings revert, for example), or a one-off script stays in the analysis after OK. |
| After a script saves the analysis with `SaveAs`, the open document is linked to the saved file. A later Ctrl+S writes the in-memory state over it. | 15.0 | A good saved file is overwritten. Reopen the saved file with File > Open instead of saving again. |
| Callbacks queued with `ApplicationThread.InvokeAsynchronously` from a script started in the script editor never ran. | 15.0 | A save or render queued to run "after the script" never happens. |
| Page titles are unique without regard to case. A clash is renamed `<title> (2)` without an error. | 15.0 | Lookups by title find the wrong page, and an auto-generated name ships. |
| Pages created through the API have no filtering scheme and their panels hidden. | 15.0 | The Filters panel is missing on a scripted page until you set the scheme and show the panel. |
| A new marking defaults to black. Set the default table and the default marking before you create visuals. | 15.0 | Marked items show in black, or visuals bind to the wrong marking. |
| `TextDataReaderSettings()` defaults to separator `;`, no header row, a guessed culture and ANSI encoding. Set all four. | 15.0 | A CSV loads as one column, or its header row becomes data. |
| The API has no public data source type for Excel files. Convert workbook data to SBDF or CSV first. | 15.0 (API) | There is no script route to load an `.xlsx`. |

## 3. Script speed

Measured with a timing script on a page driven by property triggers, 15.0.

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| Spotfire spends about 0.65 to 1.3 s preparing a large stored IronPython script on every run (about 1 s per 250 KB of code), even when the run does nothing. Python's own `compile()` of the same code takes about 40 ms. A stub that holds the code as a string literal, compiles it once per session, keeps the code object with `AppDomain.CurrentDomain.SetData(key, code)` (key = name + length + hash) and runs it with `exec(code, dict(globals()))` cut a trigger run from 650 ms to 50 ms. | 15.0 | Every click on a page driven by large scripts lags by about a second. |
| Setting a document property from a script fires that property's trigger script at once. One click that sets several properties runs several trigger scripts. | 15.0 | Cascading trigger runs and slow clicks. |
| Trigger scripts run inside a transaction. The same display update called directly, outside a transaction, took 3 to 5 times longer because each change was processed on its own. Batch direct updates with `Document.Transactions.ExecuteTransaction(...)`. | 15.0 | Slow updates when a script changes many layers or colors. |
| Each assignment to a reference layer or coloring property re-evaluates the chart. `SetColorForCategory` costs about 12 ms per call. Keep a signature per layer and set only what changed. | 15.0 | Clicks slow down as layers are added. |
| Removing and re-adding a column of a shared table recalculated every chart on that table (3.7 s measured). | 15.0 | Multi-second clicks. |
| Hiding or showing a chart re-lays out the page (2 to 4 s measured). One chart trellised by lane in RowsColumns mode instead of one chart per lane brought show and hide to 0.6 to 0.9 s. | 15.0 | Slow show and hide of signals or lanes. |
| A where clause that uses `DocumentProperty(...)` re-queries the visual without rebuilding any table. | 15.0 | Rebuilding tables on every window change is slow; load a wide range once and limit the visuals to the window. |

## 4. Text areas and the HTML sanitizer

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| Analyst sanitizes text-area HTML when it renders it. The preference that controls it (`PerformHtmlSanitation` in the TextArea preference group) is on by default. The HTML is stored unchanged, so the same DXP renders differently where an administrator turned sanitation off. | 15.0 | The page looks right on the author's machine and loses its styling and controls on other machines. Test with sanitation on. |
| These elements are removed with everything inside them: `style`, `script`, `details`, `summary`, `button`, `input`, `select`, `option`, `textarea`, `svg`, `iframe`, `object`, `embed`, `section`, `header`, `nav`, `center`, `small`, `sup`, `sub`, `mark`, `kbd`, `s`, `form`, `link`, `meta`, `canvas`, `article`, `footer`, `main`, `aside`, `figure`, `caption`, `video`, `audio`. HTML comments are removed too. | 15.0 | Controls placed inside them disappear with them. A panel built from `<details>` blocks loses every control. |
| One rejected declaration in an inline `style` drops the whole attribute. The only functions accepted are `rgb()` and `rgba()`. `var()`, `calc()`, `url()`, gradients, transforms, `hsl()` and double quotes inside a value are rejected. Flex, grid with plain track lists (`1fr 1fr`), `box-shadow` with `rgba()`, `border-radius`, `!important` and single-quoted font names pass. | 15.0 | An element loses all of its inline styling, not only the bad declaration. |
| Values of `class`, `id` and `title` may hold only letters, digits, spaces and `` . , - _ # ' ` / % ``. Any other character removes the attribute. `title` survives only on `a` and `img`; `a` takes no `style`; `data-*`, `on*` and `hidden` are removed. | 15.0 | Tooltips containing a colon vanish; utility-class names with brackets are stripped. |
| An `img` survives only when its `src` is a key of the text area's image collection. External URLs and `data:` URIs remove the element. | 15.0 | Logos and icons disappear. |
| `href` values with `https:`, `mailto:`, `file:///` and `#anchor` are kept; `javascript:` is dropped and the `a` stays. | 15.0 | A link that ran script does nothing. |
| `${Property}` is not substituted in text-area HTML. It is substituted in visual and page titles. Show a property value in a text area with a label control. | 15.0 | The page shows the literal text `${Property}`. |
| A label control HTML-encodes its value and turns `\n` into a line break. | 15.0 | Markup inside a value shows as text. |
| Text-area controls render as Spotfire widgets: buttons as `input[type=button].sfc-action-button`, drop-downs as `div.sf-element-dropdown`, list boxes as `div.sf-element-list-box`, sliders as `span.TextAreaSlider`. | 15.0 | CSS that targets `select` or `button` never matches. |
| Text-area JavaScript runs after every full render of the text area, with Spotfire's jQuery available as `$`. A script that appends a `<style>` element with a fixed `id` into a `div` the HTML keeps is how CSS rules with selectors get past the sanitizer. | 15.0 | A `<style>` block in the HTML is removed. A script without a fixed `id` adds a duplicate on every render. |
| Injected CSS is global to the page document. Unscoped rules also restyle the Filters panel. Scope every selector under one panel class. | 15.0 | The Filters panel changes look. |
| Generic CSS on inputs hid text-area sliders: the track rendered with zero height and the thumb in the canvas color. Style `.TextAreaSlider` explicitly. | 15.0 | Sliders are invisible. |
| A drop-down inside an element with `display: none` renders zero pixels wide once shown. Hide sections by moving them off screen. | 15.0 | Drop-downs appear collapsed after a section opens. |
| Analyst logs sanitizer findings as "GetSanitizedHtmlContent for text area '...' ... discovered N issues". | 15.0 | Read this log line to find which text area lost content. |

## 5. Visuals and expressions

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| On a scatter plot or map marker layer whose marker-by is empty (the default), the label, size, line order, rotation and tooltip expressions must aggregate (`First([Name])`, `Avg([Flow Rate (bbl/d)])`, `UniqueConcatenate([Id])`), or the marker-by must contain `baserowid()`. X, Y, color and drawing order may stay raw. | 15.0 | The visual shows only "Please specify an aggregation method." On a map, one bad layer blanks the whole map, tile layer included. The red issue icon next to the title names the failing layer. |
| A reference line or layer label shows its expression text unless the expression has an alias: `First(DocumentProperty("UpperLimit")) as [Upper Limit]`. | 15.0 | Labels read `First(DocumentProperty("UpperLimit"))`. |
| In a reference layer expression, `DateTime(y, m, d, h, mi, s)` is invalid. Use `DateTime("yyyy-MM-dd HH:mm:ss")`. | 15.0 | The layer reports an invalid expression. |
| Spotfire expressions have no `Replace()`; use `Substitute()`. | 15.0 | Expression error. |
| Line charts created through the API persist `BreakOnEmpty = false`, so a line colored by category joins across gaps. Use one `If()` measure per category and set BreakOnEmpty to true. | 15.0 | Lines bridge periods in which the category had no data. |
| Trellis Panels mode shows at most about three panels per screen when the maximum number of rows is greater than or equal to the panel count. RowsColumns mode with the row axis on a lane column shows every lane. | 15.0 | Users must scroll to see more than three panels. |
| Stacked charts line up their time axes when each sets the same `YAxis.Scale.Span` (58 px worked). | 15.0 | The time axes of stacked charts are offset by the width of each y axis. |
| A dashed or dotted series on a line chart is one reference layer per series with `EvaluationModes` Category, `ElementByAxis` `<>`, `Avg([Value])` and a dashed line connection. The connection stroke does not inherit the series color and is black by default: set it. | 15.0 | Black dashed lines. Element-by `<[Timestamp]>` draws a band of horizontal lines instead. |
| Scatter label layout Auto moves crowded labels far from their markers, and a newline in a label is clipped. Use `MarkerLabelLayout.Center` with labels staggered over two rows. | 15.0 | Labels float away from their points or lose their second line. |
| A scatter line connection cannot be clicked. To make a long segment clickable, add a table of points along it and relate it to the segment table by key. | 15.0 | Clicks on lines mark nothing. |
| A click on a graphical-table row header does not mark; a click on a cell does. Show names in a calculated-value column. | 15.0 | Users click names and nothing marks. |
| Spotfire refuses a table relation that would close a cycle (a third relation among three tables already related in a chain). | 15.0 | The relation is not added. |

## 6. Maps

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| A map chart created through the API has no layers, no background map and no marking. `AutoConfigure()` deletes every layer. | 15.0 | An empty map, or layers lost after an auto-configure call. |
| Each data layer has its own legend. The map's own legend holds only title, description and trellis. Hide legend items on each layer's `Legend.Items`. | 15.0 | Hiding items on the map legend does nothing; every layer lists Marking, Marker by, Shape by, Size by and Data limiting. |
| A layer limited by a marking with the empty behaviour ShowEmpty draws nothing while nothing is marked, and raises no issue. | 15.0 | Base geometry (routes, sites) is missing until something is marked. Use ShowAll on base layers. |

## 7. Markings and interaction

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| A visual limited by a marking needs its empty behaviour set explicitly (`Data.LimitingMarkingsEmptyBehavior`: ShowAll, ShowEmpty or ShowMessage with `LimitingMarkingsEmptyMessage`). Left at the default, a marking-limited table showed empty. | 15.0 | An empty table or chart when the page opens. |
| Visuals highlight each other's marked rows when they use the same marking on the same table, or on tables joined by a relation. | 15.0 | A marking reaches one visual and the rest of the page does not react. |
| No action runs on a marking change. To react to marking, give an automatic data function an input limited by the marking; the function writes a document property, and a trigger script on that property does the rest. | 15.0 | There is no event to attach a script to; users end up pressing a button after every selection. |

## 8. Visualization mods and action mods

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| Visual title-bar buttons render only for action-mod scripts. An IronPython script cannot be a title-bar button. | 15.0 | The button never appears. |
| An empty optional action-mod argument stops the action without a message. Leave the argument out instead. | 15.0 | The button or menu item does nothing. |
| Each visual button shows its script's manifest icon. Two buttons with different icons need two scripts. | 15.0 | Two buttons on one visual show the same icon. |
| A mod loaded from its project folder (the development route) stores the manifest path, including the local user folder, in the DXP. Use a library-published or pinned mod in anything you share. | 15.0 | A local path and user name ship inside the DXP; other users cannot load the mod. |
| Mods cannot read Binary columns. `First(Base64Encode([Geometry]))` on a mod axis passes WKB geometry as text. | 15.0 | The mod receives no geometry. |
| `AxesNames` of a mod layer can list a name that has no axis object (seen for the color axis). Check the result of `Axis(name)` for `None`. | 15.0 | A script that configures every listed axis fails on the first run. |

## 9. Script trust

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| A script or data function created through the API in a user's session is stamped as approved for that user and runs at once for them. Other users get Spotfire's trust prompt. | 15.0 | A DXP built on one account stops at the trust prompt when another account runs it unattended. |
| Replacing a data function's code inside the DXP file, outside Analyst, keeps the old approval stamp. The function opens untrusted ("not trusted and could not be executed") and `ExecuteSynchronously()` does nothing without an error. A person fixes it in Analyst: File > Manage trust, review, Trust, refresh, save. After that the saved DXP runs unattended for that user; an unsaved copy stays untrusted. | 15.0 | Outputs stay stale and no error is shown. |
| Data functions cannot be signed. Only members of the Script Author group can trust a script for every user. Web clients cannot grant trust. | 15.0 (Spotfire documentation) | Web Player users see untrusted functions that they cannot fix themselves. |

## 10. Files, data and saving

| Behaviour | Proven on | Symptom when you get it wrong |
|---|---|---|
| A DXP is a ZIP. `AnalysisDocument.xml` is one line of serialized objects with document-wide ids, shared strings and per-user approval stamps, and Analyst 15.0 also writes 14.8 and 14.6 copies of the document. Create objects through the API, never by editing the XML. | 15.0 | A hand-edited file fails to open or opens with untrusted scripts. |
| `SaveAs(path, DocumentSaveSettings())` is the current save call and writes the 14.x compatibility copies. `Save(String)` is obsolete. | 15.0 (API) | Obsolete-member warnings, or a file older versions cannot open. |
| File-based tables are embedded only when the user's preference says so. Force embedding per table through `Document.Data.SaveSettings`. | 15.0 | The DXP opens without data on another machine. |
| A file-based table keeps its source path in the DXP even when its data is embedded. A stream-based source keeps a temporary spool path under the user's profile. | 15.0 | Local paths and the user name ship inside the DXP. |
| Strings in the saved document escape control characters as `_xHH` (a tab is `_x09`). | 15.0 | A search of the extracted XML for a tab or newline finds nothing. |
| Library version history on Spotfire Server is on by default and supports revert. It has no compare feature. | Spotfire Server documentation | Expecting a diff between two library versions. Compare extracted files instead. |

## 11. Read from Spotfire's code, not yet tested live

These come from reading Spotfire 15.0's method bodies. Treat them as **Not yet tested** until you
see them on a live Analyst.

| Behaviour | Status | Symptom when you get it wrong |
|---|---|---|
| `DataFunction.ExecuteSynchronously()` also returns False when the inputs did not change since the last run. A run failed only when it returns False and `NeedsRefresh` is still True. | **Not yet tested** | A script reports a failure for a function that had nothing to do. |
| `ScriptManager.ExecuteScript(...)` writes script errors to its output stream instead of raising them; running a stored script definition raises them. | **Not yet tested** | Errors in a script started this way pass unnoticed. |
| Spotfire stops a trigger script that re-triggers itself after 20 nested runs. | **Not yet tested** | A property trigger that sets its own property loops, then stops part way. |
