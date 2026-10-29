# IronPython API patterns (Spotfire Analyst 15.0)

Every member below is in the public Spotfire 15.0 API. The patterns are the ones used in live
builds and app scripts on Analyst 15.0; a snippet that has not run as written is marked
**Not yet tested**.

## .NET from IronPython

| Need | Write |
|---|---|
| out parameter | it comes back in a tuple: `found, table = Document.Data.Tables.TryGetValue("PUMP_DATA")` |
| generic method | `page.Visuals.AddNew[LineChart]()`, `visual.As[HtmlTextArea]()` |
| enum member named `None` | `getattr(LimitingMarkingsEmptyBehavior, "None")` |
| pseudo-enums (`ScriptLanguage`, `ScriptParameterType`, `DataType`) | compare with `.Equals`, never `is` |
| exact .NET numeric type | `from System import Int32, Int64, Double`; `Int64(0)` for a LongInteger value |
| typed array | `from System import Array`; `Array[DataSelection]([marking])` |
| typed list | `from System.Collections.Generic import List`; `List[ScriptParameter]()` |

## Document properties

```python
from Spotfire.Dxp.Data import DataPropertyClass

# Read: the indexer gives the value.
target = Document.Properties["TargetEfficiencyPct"]

# Write: the value must match the property's data type. Writing a property
# runs its trigger script, if it has one, when the transaction completes.
Document.Properties["StatusMessage"] = "Ready"

# Exists?
exists = Document.Data.Properties.ContainsProperty(DataPropertyClass.Document, "MinPoints")

# The DataProperty object (type, description):
found, prop = Document.Data.Properties.TryGetProperty(DataPropertyClass.Document, "MinPoints")
```

Create properties with the asset script `Create Document Properties.py`
(`DataProperty.CreateCustomPrototype(name, description, defaultValue, dataType, attributes)`, then
`AddProperty`). `DataProperty.Description` is read-only once the property exists, so the
description is the second argument of the prototype. Pass the default as the exact .NET type of
the data type (`Int32` for Integer, `Int64` for LongInteger, `Double` for Real).

Spotfire matches property names without regard to case. Two names that differ only in case are an
error in the naming standard.

## Pages and visuals

```python
from Spotfire.Dxp.Application.Visuals import HtmlTextArea, VisualTypeIdentifiers

def page_by_title(title):
    for page in Document.Pages:
        if page.Title == title:
            return page
    return None

def visual_by_title(page, title, type_id=None):
    for visual in page.Visuals:
        if visual.Title == title and (type_id is None or visual.TypeId.Equals(type_id)):
            return visual
    return None

page = page_by_title("Pump Overview")
Document.ActivePageReference = page                      # open the page

panel = visual_by_title(page, "Controls", VisualTypeIdentifiers.HtmlTextArea)
text_area = panel.As[HtmlTextArea]()                      # the typed content
```

- Look pages and visuals up by title (and type), never by index: page order changes.
- Navigation that does nothing else is a native go-to-page action on a link or button, not a
  script.

## Tables, columns, markings, filters

```python
from Spotfire.Dxp.Data import IndexSet, RowSelection

found, table = Document.Data.Tables.TryGetValue("PUMP_DATA")
found, column = table.Columns.TryGetValue("Flow Rate (bbl/d)")
found, marking = Document.Data.Markings.TryGetValue("Selected Pump")

rows = marking.GetSelection(table).AsIndexSet()           # marked row indexes
marking.SetSelection(RowSelection(IndexSet(table.RowCount, False)), table)   # clear
marking.SetSelection("[Status] = \"Alarm\"", table)      # mark by expression (API 14.5 and later)

for scheme in Document.FilteringSchemes:
    scheme.ResetAllFilters()
```

- Never add or remove tables while you iterate `Document.Data.Tables`: collect first, then change.
- A schema change (removing and re-adding a column) recalculates every visual on the table and is
  slow (a 3.7 s case is in [performance.md](performance.md)). Prefer a `Where` clause on
  `DocumentProperty(...)` in the visuals.

## Data functions

```python
for function in Document.Data.DataFunctions:
    if function.Name == "Calculate Pump Efficiency":
        function.ExecuteSynchronously()      # runs now; Execute() only queues
```

The full run chain is `assets/scripts/Run All Data Functions.py`.

## Scripts and text-area JavaScript through the API

Upsert an IronPython script so a rerun does not add a duplicate (Spotfire allows two scripts with
one name):

```python
from System.Collections.Generic import List
from Spotfire.Dxp.Application.Scripting import (
    ScriptDefinition, ScriptLanguage, ScriptParameter, ScriptParameterCollection,
    ScriptParameterType)

params = List[ScriptParameter]()
params.Add(ScriptParameter("pageTitle", "Page to open", ScriptParameterType.String))
wanted = ScriptDefinition.Create("Go To Page", "Opens a page by title.", code,
                                 ScriptLanguage.IronPython3,
                                 ScriptParameterCollection(params), True)
found, existing = Document.ScriptManager.TryGetScript("Go To Page")
if not found:
    Document.ScriptManager.AddScriptDefinition(wanted)
elif not existing.IsEquivalentTo(wanted):
    Document.ScriptManager.Replace(existing, wanted)     # buttons keep working
```

- `ScriptDefinition.Create(name, description, code, language, parameters, wrapInTransaction)` is
  the only factory. The parameter collection must not be None.
- Names may not contain `\ / " : * ? < > |` or control characters. IronPython parameter names are
  Python identifiers and not keywords.
- `Replace` needs the registered object (from `TryGetScript`), never a look-alike.
- Creating a script stamps it as approved for the Windows user who runs the code. Other users get
  a trust prompt. Editing the script outside Analyst drops the stamp.
- Text-area JavaScript goes through `HtmlTextArea.Scripts.Add(HtmlTextAreaScript(definition,
  values))` with a `ScriptLanguage.JavaScript` definition. The `styling-spotfire-dxps` skill uses
  this for its stylesheet injector.

## Transactions

A script created in Analyst runs in a transaction ("Execute in transaction", `WrapInTransaction`
True). The whole script is one undo step, and display updates are processed once at the end. For a
batch of changes outside such a script, wrap them yourself:

```python
from Spotfire.Dxp.Framework.DocumentModel import Executor

def apply_changes():
    pass   # many property, layer or visual changes

Document.Transactions.ExecuteTransaction(Executor(apply_changes))
```

The same display update without a transaction took 3 to 5 times longer in Analyst 15.0
([performance.md](performance.md)).

## Expression facts that scripts trip over

- Spotfire expressions have no `Replace()` function; use `Substitute()`.
- `DateTime(y, m, d, h, mi, s)` is not valid in a reference-layer expression; use
  `DateTime("yyyy-MM-dd HH:mm:ss")`.
- A reference-layer label shows the expression's display name, so give it an alias:
  `First(-15.0) as [Upset below -15]`. A label from a property: `First(DocumentProperty("X")) as
  [Label]`.
- `DetailItemCollection` has no `Clear()`.
