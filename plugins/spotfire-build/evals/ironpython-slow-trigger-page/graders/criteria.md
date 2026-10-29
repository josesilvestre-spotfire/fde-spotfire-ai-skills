---
type: llm
weight: 1
---

Grade the response and the file `Reset Page.py`. Pass when all of these hold; list every
criterion that fails.

1. The script uses Python 3.4 syntax: no f-strings (the response explains briefly that IronPython
   3.4 targets the Python 3.4 language, so it uses `%` formatting or `str.format`), no walrus, no
   annotations.
2. The script has no `print` call; status goes to the `StatusMessage` document property.
3. Filters are reset through the filtering schemes (for example `FilteringScheme.ResetAllFilters()`
   for each scheme in `Document.FilteringSchemes`).
4. The marking is found by name (`Document.Data.Markings.TryGetValue`, unpacked as a tuple) and
   cleared per table, for example with `SetSelection(RowSelection(IndexSet(table.RowCount, False)), table)`.
5. The page is looked up by its title, never by index, and opened with
   `Document.ActivePageReference`; a missing page is reported in `StatusMessage` instead of
   raising an unexplained error.
6. The script parameter for the page title is named camelCase (for example `pageTitle`).
7. The speed advice names the cause measured in Analyst 15.0: Spotfire prepares a large stored
   script again on every run (roughly 1 s per 250 KB), and recommends a compile-once stub that
   keeps the code as a string, compiles it once per session and caches it (for example with the
   skill's `make_compile_once_stub.py`).
8. The advice also covers at least two of: batching changes in one transaction
   (`Document.Transactions.ExecuteTransaction(Executor(...))`), setting reference layers or colors
   only when they changed, avoiding schema changes, writing a property only when its value
   changes so its trigger does not run for nothing.
9. Trigger set-up is described as a manual step in Analyst (Document Properties, select the
   property, Script, choose the script), with no code that calls non-public Spotfire classes or
   uses reflection to create triggers.
