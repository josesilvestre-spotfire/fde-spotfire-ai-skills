# Excel to Spotfire map

How each workbook part, formula pattern and Excel function becomes a Spotfire element: a data
table, a document property, a calculated column (with OVER where rows depend on other rows), a
visual expression, or Python in a data function.

Status: the Spotfire expressions below follow the Spotfire expression language. They are **Not
yet tested** as part of this skill on a live Spotfire. The reconciliation step (stage 7, run by
`building-spotfire-dxps`) checks every ported calculation against the workbook's values, so a
wrong mapping shows up as a failed output.

## 1. Workbook parts

| In the workbook | In the DXP | Note |
|---|---|---|
| Raw data pasted into ranges, Excel tables | Data table loaded through a connection, CSV or SBDF | One table per range; headers become Title Case column names with units |
| Row-level formula filled down a column | Calculated column | Only when every input is a column of the same table or a document property |
| Running totals, lags, period-over-period comparisons | Calculated column with OVER, or a data function | Use the data function when the order or the grouping is not a plain column |
| Iteration, circular references, Goal Seek, Solver, matrices | Python data function | Converge to the Logic Spec tolerance; Solver becomes scipy or a hand-written search only after the owner agrees |
| Input cells, scenario switches, drop-down lists, form controls | Document properties with text-area controls | One name per binding: property = data function parameter = control |
| Named ranges | Document property (single value) or table (range) | The name becomes the property name in PascalCase |
| Lookup tables | Related or joined table, or a lookup in the data function | Approximate lookups go in the data function (see section 3) |
| One sheet per well, case or month (template copies) | One long table with an Asset or Case column; trellis, filters and marking | Template drift is resolved with the owner first |
| What-if data tables (`{=TABLE()}`) | Data function that runs the sweep and writes a table | Inputs of the sweep become a property or a small table |
| Charts | Native visuals | Chart series ranges name the outputs to reconcile |
| Pivot tables | Cross tables | The pivot cache source names the table |
| Conditional formatting | Color rules on the visual | Font colors become cell or marker colors |
| Summary or dashboard sheet | First page with an HTML KPI band | KPI values are value outputs of a data function, shown by labels |
| VBA macros | IronPython scripts or data functions behind buttons | Only after the code is read; macros never run during ingest |
| External links | A data table or document property loaded from the source | The stored value is used for reconciliation |
| Power Query | Data connection or data function | Rebuild the query; the stored result is the reconciliation input |
| Hidden sheets, rows and columns | Nothing by default | Carry only what feeds an output; list the rest in the change list |
| Array formulas and dynamic arrays | Data function | Spill ranges become output tables |
| Manual steps (copy, paste, sort, Goal Seek) | Data function, script or a documented step | Recorded in the App Brief |

## 2. Where a formula goes

1. Reads only its own row plus document properties: **calculated column**.
2. Reads other rows of the same table in a fixed order (cumulative, previous period): **calculated
   column with OVER** when the order and group are columns; otherwise **data function**.
3. Aggregates a table to one value (total, maximum, average): **visual expression** when only a
   visual shows it; **data function value output** when a KPI band, another calculation or a
   reconciliation needs it.
4. Reads another table by key: **relation** for display, **join** (add columns) for calculated
   columns, **data function** for approximate or multi-key lookups.
5. Iterates, solves, interpolates, inverts a matrix, or depends on a circular reference: **data
   function**.
6. When one chain of blocks mixes several of the above, keep the whole chain in one data function
   so the DXP ships the reconciled code unchanged.

The standard engine of the `building-spotfire-dxps` skill does not build calculated columns,
relations or hierarchies yet (they need its slim tier; see `spec-draft.md`). In the draft spec,
compute such columns in the data function that writes the table, set the Logic Spec's
"Implemented as" to that data function, and record the intended calculated column or relation
in the mapping table.

OVER patterns for calculated columns:

| Workbook pattern | Spotfire calculated column |
|---|---|
| Running total down a column per well (`=E9+D10`) | `Sum([Monthly Volume (bbl)]) OVER (Intersect([Well], AllPrevious([Month])))` |
| Previous row (`=C10-C9`) | `[Rate (bbl/d)] - Sum([Rate (bbl/d)]) OVER (Intersect([Well], Previous([Month])))` |
| Share of a group total (`=B5/SUM($B$5:$B$24)`) | `[Volume (bbl)] / Sum([Volume (bbl)]) OVER ([Field])` |
| Rank within a group | `Rank([Volume (bbl)], "desc", [Field])` |
| Row number | `RowId()` |

## 3. Functions

| Excel | Spotfire expression | Python (data function) | Note |
|---|---|---|---|
| `+ - * /` | same | same | Division by zero: Excel `#DIV/0!`; use `div()` in Python |
| `^` | `^` or `Power(a, b)` | `power(a, b)` | Excel `=-2^2` is 4 (negation first); Python `-2**2` is -4 |
| `%` (`5%`) | `0.05` | `0.05` | |
| `&` | `&` or `Concatenate(a, b)` | `text_general(a) + text_general(b)` | Numbers in text use Excel's General format |
| `=`, `<>` on text | `=`, `!=` | `eq(a, b)` | Excel compares text without regard to case |
| `IF`, `IFS` | `If(c, a, b)`, `Case when ... then ... else ... end` | `a if c else b` | An empty cell in a test counts as 0 or "" in Excel |
| `SWITCH`, `CHOOSE` | `Case [X] when 1 then ... end` | dict lookup | |
| `AND`, `OR`, `NOT` | `and`, `or`, `not` | `and`, `or`, `not` | |
| `IFERROR`, `IFNA` | `SN(expr, fallback)` for nulls | `iferror(lambda: expr, fallback, where)` | The port records each hidden error; see the issue catalog |
| `ISBLANK`, `ISERROR` | `[X] is null` | `x is None`, `try` | |
| `ROUND` | `Round(x, n)` | `xround(x, n)` | Excel rounds half away from zero on the 15-digit value; Spotfire's midpoint rule is Not yet tested |
| `ROUNDUP`, `ROUNDDOWN`, `TRUNC` | `Ceiling`/`Floor` on scaled values | `roundup`, `rounddown`, `trunc` | |
| `INT` | `Floor(x)` | `xint(x)` | `INT(-2.5)` is -3 |
| `MOD` | `Mod(a, b)` | `mod(a, b)` | Sign follows the divisor |
| `ABS`, `SQRT`, `EXP`, `LN`, `LOG10`, `LOG` | `Abs`, `Sqrt`, `Exp`, `Ln`, `Log10`, `Log(x, base)` | `abs`, `sqrt`, `math.exp`, `ln`, `log10`, `math.log` | Excel gives `#NUM!` for a log of a value <= 0 |
| `PI()` | `PI()` | `math.pi` | |
| `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT` over a column | `Sum`, `Avg`, `Min`, `Max`, `Count` (visual) or `... OVER (...)` (column) | `xsum`, `average`, `xmin`, `xmax`, `count` | Excel skips empty cells and text in ranges; `MAX` of nothing is 0 |
| `SUMIF(S)`, `COUNTIF(S)`, `AVERAGEIF(S)` | `Sum(If([Status]="Open", [X])) OVER ([Group])` | `df.loc[mask, col].sum()` | |
| `SUMPRODUCT` | `Sum([A] * [B])` | `(df.A * df.B).sum()` | |
| `MEDIAN`, `PERCENTILE`, `STDEV.S`, `VAR.S` | `Median`, `Percentile(x, p)`, `StdDev`, `Var` | `numpy` | Excel PERCENTILE.INC interpolation equals `numpy.percentile` default |
| `CORREL`, `SLOPE`, `INTERCEPT`, `LINEST`, `TREND`, `FORECAST` | Lines and curves in a visual, or a data function | `numpy.polyfit`, `numpy.corrcoef` | |
| `VLOOKUP(..., FALSE)`, `XLOOKUP`, `INDEX`/`MATCH(...,0)` | Relation or join on the key | `pandas.merge` or `vlookup(v, rows, k, approximate=False)` | |
| `VLOOKUP` without the fourth argument, `MATCH(...,1)`, `LOOKUP` | Data function | `vlookup(v, rows, k)` (binary search like Excel), or `pandas.merge_asof` on sorted data | Range lookups on unsorted data return rows Excel may not; the issue scan flags them |
| `OFFSET`, `INDIRECT` | Explicit column or table | Explicit index | Resolve what they point to with the owner |
| `DATE`, `YEAR`, `MONTH`, `DAY` | `Date(y, m, d)`, `Year`, `Month`, `Day` | `to_serial`, `from_serial`, `year`, `month`, `day` | Excel serials count 1900-02-29 (serial 60), a day that never existed |
| `EDATE`, `EOMONTH` | `DateAdd("month", n, [Date])` | `edate`, `eomonth` | Month ends are clipped (Jan 31 + 1 month is Feb 28) |
| `DATEDIF`, `YEARFRAC` | `DateDiff("day", a, b)` | `(b - a).days`, explicit day-count rule | YEARFRAC basis 0 is 30/360 |
| `TODAY`, `NOW` | `Today()`, `DateTimeNow()` | `datetime` | Volatile: reconcile with a fixed date |
| `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `SUBSTITUTE`, `FIND` | same names | `str` methods | Excel TRIM also collapses inner spaces |
| `TEXT`, `VALUE` | Column format, `Real([X])` | `format`, `float` | |
| `NPV` | Data function | `npv(rate, values)` | The first value is discounted by one full period |
| `IRR`, `XIRR`, `XNPV` | Data function | `irr(values)`, numpy root finding | Excel IRR tries 20 iterations from the guess |
| `PMT`, `FV`, `PV` | Data function | `pmt`, numpy-financial formulas | |
| `MMULT`, `MINVERSE`, `TRANSPOSE` | Data function | `numpy` | |
| `{=TABLE()}` what-if data table | Data function | loop over the input values | |
| VBA functions (UDF) | Data function | port of the VBA code | Read the code first; the issue scan lists the calls |

## 4. Excel behaviour the port reproduces

`excel_compat.py` holds these, standard library only, so they travel with the data function:

| Behaviour | Excel | Plain Python | Helper |
|---|---|---|---|
| Rounding | Half away from zero on the 15-digit decimal value (`ROUND(2.675,2)` = 2.68) | `round()` is half to even on the binary value (2.67) | `xround`, `roundup`, `rounddown` |
| Serial dates | 1900 system counts 1900-02-29; some workbooks use the 1904 system | `datetime` has no such day | `to_serial`, `from_serial` (`date1904=`) |
| Empty cells | 0 in arithmetic, skipped by SUM and AVERAGE | `None` raises | `arith`, `xsum`, `average` |
| Range lookups | `VLOOKUP`, `HLOOKUP`, `MATCH` default to approximate | no default | `vlookup`, `match` |
| Precision | 15 significant digits | 17 | `sig15` |
| Hidden errors | `IFERROR` returns the fallback silently | exceptions | `iferror` records each error in `HIDDEN_ERRORS` |
| Negative powers | `0^0` and a negative base with a fractional exponent give `#NUM!` | 1 and a complex number | `power` |
| Text comparison | case-insensitive | case-sensitive | `eq` |

In Spotfire, an arithmetic expression with an empty (null) value gives null, where Excel gives a
number. Wrap such columns with `SN([X], 0)` when the workbook relies on empty cells being 0.
**Not yet tested.**
