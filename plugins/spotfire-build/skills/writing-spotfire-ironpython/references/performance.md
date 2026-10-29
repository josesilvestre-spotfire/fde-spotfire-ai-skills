# Script speed: measured in Spotfire Analyst 15.0

These timings come from a timing job on an analysis whose pages are driven by IronPython: about
20 property triggers, one large shared script, line charts with reference layers. Clicks went from
2 to 4 s to 0.15 to 1.4 s with the changes below; a click that changes nothing took 56 ms.

## 1. Stored scripts are prepared again on every run

| Measurement | Time |
|---|---|
| Spotfire preparing a large stored script before it runs, even when it does nothing | 0.65 to 1.3 s (about 1 s per 250 KB of code) |
| CPython-style `compile()` of the same code inside IronPython | about 40 ms |
| a tiny script | about 65 ms |
| a trigger run with the compile-once stub | about 50 ms (from 650 ms) |

Fix: store each large script as a stub that holds the code as a string literal, compiles it once
per Analyst session and keeps the compiled code in the .NET AppDomain. The key is the script name,
the code length and its hash, so a new version compiles again.

```bash
python scripts/make_compile_once_stub.py "Update Pump Page" "scripts/Update Pump Page.py" > stub.py
```

Store `stub.py` as the document script "Update Pump Page" and keep editing the source file.

## 2. One click, many triggers

A click that sets several properties runs each property's trigger script. With the stubs the cost
per run is small; without them every trigger pays the preparation time above. Design triggers so a
cascade ends. Spotfire's code caps a script that triggers itself again at 20 nested runs and then
raises an error (read from the product code; **Not yet tested** live).

## 3. Transactions

Trigger scripts run in a transaction. The same display update called directly, without a
transaction, took 3 to 5 times longer, because every layer change was processed on its own. Wrap
direct batches in `Document.Transactions.ExecuteTransaction(Executor(fn))`.

## 4. Set only what changed

- Every assignment to a reference layer or visual property is evaluated again, even when the value
  is the same. Keep a signature of each layer's settings (for example a JSON string in a hidden
  document property, parsed only when it changed) and set a layer only when it is new or its
  signature changed.
- `SetColorForCategory` cost about 12 ms per call. Set only the categories that changed.

## 5. Schema changes are expensive

Removing and re-adding one column on an events table cost 3.7 s, because every chart on that table
recalculated. Keep tables stable and move the changing part into expressions.

## 6. One chart instead of many

Hiding or showing one signal re-laid the page and rewrote several line charts (one per lane):
2 to 4 s. One line chart trellised in RowsColumns mode, with the lane column on rows, made the same
change 0.6 to 0.9 s.

- Trellis Panels mode showed only about 3 panels per screen when max rows was at least the panel
  count. RowsColumns mode shows every lane.
- Line labels show the color-by and line-by values, so color by the label column.

## 7. Filter in the visual, not in the table

A `Where` clause on `DocumentProperty(...)` makes a visual query again without rebuilding a table.
Load a wide range once and limit the visuals to the window the user picked. Long windows can be
thinned in the expression, for example with `Mod(RowId(), k) = 0`.
