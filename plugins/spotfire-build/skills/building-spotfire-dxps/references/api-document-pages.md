# Document, pages and layout (scripts/lib/10_document.py, scripts/lib/50_pages.py)

Spotfire Analyst 15.0 (Core 71.0.22206.3863), IronPython 3.4. Public API only: every member used is
listed in `scripts/lib/10_document.members.txt`, `scripts/lib/50_pages.members.txt` and the `.set.txt`
files and checked with `scripts/sfapi.py has`. Nothing here needs an API newer than 14.6 (newest:
`Page.Visible`, `PageNavigationMode.Off`, api 10.7). Items not yet proven in a live build are marked
**Not yet tested**.

## Build sequence

| group | call | does |
|---|---|---|
| `doc.prepare` | `doc_prepare()` (critical) | snapshot of the starting pages into `B.document_old_pages` |
| `doc.prepare` | `doc_apply_theme(theme)` | writes `app.theme.customStyles` to `build/theme.json`, records `created.theme`, then fails on purpose: the theme is a manual step (see Theme below) |
| `pages` | `pages_create(pages)` | per page: `AddNew("dxpb-page-NN")`, `B.register_page(title)`, `Visible`, panels, filtering scheme |
| `layout:<title>` | `page_apply_layout(page, pspec)` | layout tree -> one `LayoutDefinition` -> `ApplyLayout` -> `GetVisualBounds` self-check |
| `doc.finish` | `doc_finish()` | remove starting pages, final titles (read back), navigation, canvas, active page, description, keywords |

Every item is its own `B.step`; `doc_finish` nests one step per sub-item. Starter data tables of the new
analysis are handled by `90_build` (renamed on a name clash, removed after `doc_finish`).

## Facts the code relies on

Pages
- `PageCollection.AddNew(title)` appends the page and makes it the **active** page. Titles are
  unique case-insensitively (trimmed, NFC, max 1000 chars): a clash is renamed silently to `T (2)`.
  The `Page.Title` setter does the same, excluding the page itself; `None`, `""` and whitespace-only
  throw. Hence: temporary titles during the build, final titles at the end, always read back.
- A blank analysis is not empty: it can hold a localized "Page" and, with the user preference on, a
  "Cover Page". The builder snapshots whatever exists. Never `Pages.Clear()` (no active-page
  handling).
  `Remove(page)` returns False when the page is not in the collection and has **no guard**:
  removing the last page leaves zero pages. Remove the starting pages only after the spec pages
  exist, and never the last one.
- API-made pages start with both panels `Visible=False`, `DockingPlacement=None`,
  `PanelState=None` and `FilterPanel.FilteringSchemeReference=None` (so no active filtering).
  Assign `Document.FilteringSchemes.DefaultFilteringSchemeReference` or a named scheme
  (`data_filtering_scheme(name)` in 20_data). Pages made in Analyst's UI persist filters `(Right, 0)`
  and details-on-demand `(Right, 1)`, both `PanelState.Docked`; the builder sets the same.
- `Page.Visible` is a plain undoable property (no active-page logic).
- `Page.Title` / `Visual.Title` are preprocessor expressions: `${...}`, `$map`, `$esc`,
  `$csearch` are live; `\${` is a literal. The getter returns the evaluated text, the file
  stores the raw expression. Titles containing `$` are not compared on read-back.
- `PageNavigationMode`: `Tabs=0, Links=1, None=2, Off=3`. `PageNavigationMode.None` is a Python 3
  syntax error: `getattr(PageNavigationMode, "None")` (fallback `Enum.Parse`).
- `Pages.VisualizationAreaSize`: default `Size.Empty` + `FitToWindow=True`; a negative size
  throws. No canvas in the spec = that default, set explicitly.
- `Document.ActivePageReference` must be a page of `Document.Pages`, else ArgumentException.
  Set it last (every `AddNew` changes it). The builder picks `activePage`, else the first
  visible spec page, else the first page.
- `Document.Properties.Keywords` is `IList<String>`: assign `List[str]([...])`.
  `Description` is a plain string. There is no document title API (title = file name).
- `VisualCollection.AddNew` auto-places a new visual by splitting the largest panel; a lone
  visual on a page gets the whole page. `VisualCollection` has no indexer: iterate, use `.Count`.

Layout (`LayoutDefinition`, `Page.ApplyLayout`)
- Every visual of the page exactly once, else ArgumentException ("Not all panels were specified",
  "supplied more than once", "is not defined for page"). `Add` takes the **Visual**, not content.
- A nested section must differ in orientation from its parent; every `Begin*Section` needs an
  `EndSection()`, the root too. Empty nested sections divide by zero: never emit them.
- `row` = `BeginSideBySideSection` (items left to right), `column` = `BeginStackedSection`
  (top to bottom). Proportions are `System.Single` weights relative to their siblings (pass
  `Single(w)`), valid about 1e-12..1e12; the root's proportion is ignored.
- A definition is single-use: build a new one for every `ApplyLayout`.
- Bounds rule, in the 100000 x 100000 page space: shares are absolute fractions of the page; a
  section's items split its share range by weight; each splitter sits at `int(share * 100000)`
  and is 3 units thick; a panel starts 3 after the previous splitter (or at the section edge)
  and ends at the next splitter (or the section edge).
- `page.GetVisualBounds(v, Rectangle(0, 0, 100000, 100000))` returns exactly the persisted
  `VisualPanel.RelativeBounds` and needs no UI. The builder compares it with the bounds rule
  (tolerance 3) and warns on drift.
- Worked example: row[text 20, column 80[trend 60, row 40[a 50, b 50]]] gives
  text `0,0,20000,100000`, trend `20003,0,79997,60000`, a `20003,60003,39997,39997`,
  b `60003,60003,39997,39997`.

Theme
- The document theme and its custom styles have no public API in Spotfire 15.0, so `app.theme` is a
  manual step. `dxpgen.py build` writes `app.theme.customStyles` to `build/theme.json` (with
  `general.baseTheme` and `general.baseThemeSfx` set to `app.theme.base`), and
  `build/MANUAL-STEPS-<tier>.md` lists the step when the spec sets `app.theme`: apply the base theme in
  Analyst with the custom styles of `build/theme.json`. In the library tiers, `doc_apply_theme` writes
  the same file (and removes a stale one when the spec has no custom styles), then fails on purpose so
  the step is logged as a fallback. The Analyst menu path for applying theme JSON by hand is **Not yet
  tested**.
- The `styling-spotfire-dxps` skill covers themes: base themes, custom styles and the theme JSON.

## Recipes

```python
# pages (50_pages): temporary title, register, panels, scheme
page = Document.Pages.AddNew("dxpb-page-%02d" % n)
B.register_page(spec_title, page)
page.Visible = True
page.FilterPanel.Visible = False
page.DetailsOnDemandPanel.Visible = False
page.FilterPanel.DockingPlacement = DockingPlacement(PanelRegion.Right, 0)
page.FilterPanel.PanelState = PanelState.Docked
page.FilterPanel.FilteringSchemeReference = Document.FilteringSchemes.DefaultFilteringSchemeReference

# layout: one definition with every visual of the page
ld = LayoutDefinition()
ld.BeginSideBySideSection()                 # root row (or BeginStackedSection for a column)
ld.Add(controls_visual, Single(18.0))
ld.BeginStackedSection(Single(82.0))
ld.Add(trend_visual, Single(60.0))
ld.BeginSideBySideSection(Single(40.0))
ld.Add(a_visual, Single(1.0)); ld.Add(b_visual, Single(1.0))
ld.EndSection(); ld.EndSection(); ld.EndSection()
page.ApplyLayout(ld)
r = page.GetVisualBounds(trend_visual, Rectangle(0, 0, 100000, 100000))

# finish (10_document)
Document.Pages.Remove(old_page)             # only while Pages.Count > 1
page.Title = "Fleet Overview"               # then read page.Title back
Document.Pages.NavigationMode = getattr(PageNavigationMode, "Tabs")
area = Document.Pages.VisualizationAreaSize
area.Size = Size(1920, 1080); area.FitToWindow = True
Document.ActivePageReference = first_page
Document.Properties.Description = "..."
Document.Properties.Keywords = List[str](["pumps", "midstream"])
```

## Pitfalls

- Resolve visuals for the layout from the page itself: a visual builder that fails after
  `AddNew` leaves an unregistered visual, and `ApplyLayout` rejects a definition without it.
  `page_apply_layout` pairs such leftovers with the unbuilt spec ids in build order when the
  counts match (they keep their slots), otherwise removes them and prunes the unbuilt ids
  (siblings then take the space; warnings name every case). Visuals registered for another page
  on this page (duplicate page titles) fail the layout step.
- Exact duplicate page titles: only the first page is built (failed step). Titles that differ
  only in case or spaces are built, and Spotfire renames the later one at the final rename (the
  title step fails with the new name).
- `90_build` looks pages up with `B.page(title)` outside a step: `pages_create` registers a page
  for every distinct spec title, empty ones included (Spotfire then rejects the empty title at
  the final rename, which fails that step), so that lookup cannot stop the build.
- Do not call `Page.AutoConfigure()` / `Document.AutoConfigure()` (user preferences) or
  `ApplyLayout(TileMode)` (silently a no-op without a UI canvas).
- `len()` does not work on `Document.Pages` / `page.Visuals`; `Pages[-1]` throws. Snapshot a
  collection before changing it.
- Numbers in titles: use Python formatting (culture-invariant), not .NET `ToString()`.

## Not yet tested

1. `getattr(PageNavigationMode, "None")` returns the enum member (value 2); how `None` and `Off`
   render in the 15.0 page bar.
2. Explicit panel docking `(Right, 0/1)` + `PanelState.Docked` renders like a page made in the UI when a
   panel is shown (null docking with a visible panel also occurs in saved analyses).
3. After `FilteringSchemeReference = DefaultFilteringSchemeReference` and save: `FilterPanel.
   FilteringScheme` set, `TableGroups` > 0, `Page.ActiveFilteringSelectionReference` set.
4. `Document.FilteringSchemes[selection]` exists right after `Data.Filterings.Add(name)` in the
   same script (20_data falls back to iterating the schemes; [api-data.md](api-data.md) U2).
5. The `VisualPanel` of a just-added visual exists before the builder script ends, so
   add-visuals-then-`ApplyLayout` works.
6. `GetVisualBounds` read-back equals the bounds rule (the worked example's numbers) and the saved
   `VisualPanel.RelativeBounds`.
7. Page titles with `${...}` evaluate like visual titles; `\${` reads back as a literal `${`.
8. A fixed `VisualizationAreaSize.Size` combined with `FitToWindow=True` (occurs in saved analyses):
   rendering behaviour.
9. `Keywords` persist (`List<String>` value of the document `Keywords` property).
10. Removing a starting page whose own button runs the builder (only if the builder is ever run
    from a text-area button instead of the script editor): expect no crash; otherwise keep that
    page and remove it in a queued `InvokeAsynchronously` call.

## What verify_dxp should check

Persisted paths in the saved DXP, as `verify_dxp.py` reads them:

| check | where | expected |
|---|---|---|
| page count and order | `Pages: PageManager / Pages: PageCollection / Items: Page[n]` | spec pages in spec order; no `dxpb-page-NN` title; no page of the starting document (`created.document.preExistingPages`) |
| title | `Page.TitleExpression.Expression` | spec title, raw (backslash escapes kept) |
| visible | `Page.Visible` | spec `visible` |
| panels | `Page.Panels.Items[]` `FilterPanel` / `DetailsOnDemandPanel` `.Visible` | spec `filterPanel` / `detailsOnDemand`; docking `{Region: Right, Index: 0/1}` + `PanelState+DockedPanelState` is informational |
| filtering scheme | `FilterPanel.FilteringScheme -> FilteringScheme` -> its `DataFilteringSelection` name | spec `filteringScheme`, else the default scheme; never null |
| navigation | `PageManager.NavigationMode` | `PageNavigationMode.<app.pageNavigation>` |
| active page | `PageCollection.ActivePage` and `Document.ActivePageReference` | both -> the page titled `created.document.activePage` |
| canvas | `PageCollection.VisualizationAreaSize { Size {width, height}, FitToWindow }` | `app.canvas`, or `0x0` + `true` |
| description | `AnalysisProperties ... DataProperty "Description" Value` | `app.description` |
| keywords | `DataProperty "Keywords" Value: List<String>` | `app.keywords` in order |
| layout | `Page.VisualPanels.Items[] { RelativeBounds {x, y, width, height}, Visual -> }` | equals `created.layouts[title][id].actual`; within 3 of `.expected` |
| theme | Document: `UseCustomStyles`, `KnownTheme`, the stored custom-styles JSON | spec with custom styles and `UseCustomStyles` false: WARN (manual step not done yet). Added by hand: the JSON equals `app.theme.customStyles` with the base set (PASS or FAIL; Spotfire may store `general.baseTheme` without the `Sfx` suffix, which is accepted) and equals `build/theme.json` (WARN). No `app.theme` but custom styles present: WARN |

Do not assert `HasDynamicLayout`, `DynamicLayoutWidth`, `PanelRegionSpan*` (user preferences)
or the content of `document-theme.css` (differs per Spotfire build).

Report fields written by these modules (`build/build-report.json` -> `created`):
- `pages`: `{spec title: page Guid}` (00_core `register_page`).
- `layouts`: `{page title: {visual id: {"actual": [x, y, w, h], "expected": [x, y, w, h]}}}`.
- `document`: `preExistingPages`, `removedPages`, `pageTitles` (read-back per spec title),
  `navigationMode`, `canvas`, `activePage`, `description`, `keywords`, `pageOrder`.
- `theme`: `base`, `customStyles` (bool), `file` (path of `build/theme.json` or null), `applied`
  (always false: the theme is a manual step).

## Filter panel organization (standard engine feature `filterLayout`)

Members checked with `scripts/sfapi.py has` (public, and `--set` for setters): `Page.FilterPanel`,
`FilterPanel.TableGroups` (`TableGroupCollection`: `IndexOf`, `Move`), `TableGroup.Name` (= the table name),
`Expanded`, `Visible`, `SubGroups`, `GetSubGroup`, `AddNewSubGroup`, `FilterCollectionReference`;
`FilterGroup.GetFilter(name)`, `FilterHandles`, `Add(Filter)`, `Remove(Filter)`, `Items`
(`FilterGroupItemCollection`: `IndexOf`, `Move`); `FilterSubGroup.Visible`, `Expanded`;
`FilterHandle.FilterReference`, `Visible`, `ParentGroup`; `Filter.Name`, `Filter.TypeId` (set);
`FilterTypeIdentifiers.CheckBoxFilter / ListBoxFilter / RadioButtonFilter / RangeFilter / TextFilter /
ItemFilter`; `FilterCollection.Contains(String)`, `Item[String]`, `AddNewFilter(DataColumn)`;
`FilteringScheme.Item[DataTable]`. Code: `scripts/engine/features/filterpanel.py`.

Behaviour in Analyst 15.0:
- A page's filter panel holds one `TableGroup` per table of its filtering scheme and keeps the groups in
  step with the scheme's filter collections (`AutoSynchronizeFilters` on).
- When a filter collection changes, every filter whose column has no handle anywhere in the table group
  (top level and sub groups) is added at the top level. So a column is hidden (`FilterHandle.Visible =
  False`), never removed; a removed handle comes back visible. `FilterCollection.AddNewFilter` triggers the
  same, so a filter made by the builder already has its top-level handle: look the handle up again before
  `FilterGroup.Add`, or the column gets two handles.
- `FilterGroup.Add(filter)` creates a new `FilterHandle` and appends it to `Items` (no move);
  `FilterGroup.Remove(filter)` removes the first handle of that group referring to it; `GetFilter(name)`
  compares `Filter.Name` exactly and looks at the group's own handles only. Moving a column into a sub
  group: `sub.Add(filter)`, then `old_handle.ParentGroup.Remove(filter)`.
- `TableGroup.AddNewSubGroup(name)` appends the sub group; a name already used throws ("The group name
  '...' is not unique."). Nested sub groups throw ("Nested groups are not supported.").
- The `Filter.TypeId` setter accepts CheckBoxFilter, ItemFilter, RadioButtonFilter, RangeFilter, TextFilter
  and ListBoxFilter (CheckBoxHierarchyFilter only when the filter already is one) and rebuilds the filter
  for its column (the selection resets). The type lives in the filtering scheme's filter collection, so it
  is the same on every page that uses the scheme.

Persisted (verify_dxp `ModelBuilder.filter_layout`): `FilterPanel.TableGroups` -> `TableGroup
{VisibleSelectedPair {Visible, Selected}, Expanded, Items -> FilterGroupItemCollection {Items[]},
FilterCollection, AutoSynchronizeFilters, DataTable -> DataTable {Name}}`; `FilterHandle
{VisibleSelectedPair, Filter -> Filter {FilterBase -> <Type>Filter {DataColumn ->
PersistedZombieCrossReference {Value -> DataColumn {Name}}}}}`; `FilterSubGroup {VisibleSelectedPair,
Expanded, Items, Name}`. A sub group may sit anywhere among the handles (for example after an ordinary
filter).
