# Standard engine, feature part "filterpanel":
# each page's filter panel shows only the tables and columns a user needs
# (references/spec-format.md "Filter panel"; scripts/t3/_filters.py reads the spec). Not
# styled: the panel keeps Spotfire's own look.
# APP page "filters": [{table, columns ("*" or [names]), expanded (only
# when False), groups [[name, [columns]] or [name, [columns], False]]},
# ...] in display order; APP "filterTypes": [[table, column, type], ...]
# with type a FilterTypeIdentifiers member name.
# Built after the starter tables are removed, so every table (the
# data-function outputs included) has its group, and before the save.
# What Spotfire does (observed in Analyst 15.0):
#   - a page's FilterPanel holds one TableGroup per table of its filtering
#     scheme (FilterPanel.SynchronizeTableGroups); TableGroup.Name is the
#     table name; FilterGroup.GetFilter(name) looks at that group's own
#     handles only (sub groups are separate groups);
#   - a filter whose column has no handle anywhere in the table group is
#     added back at the top level when the filter collection changes
#     (TableGroup.FilterCollectionChanged, AutoSynchronizeFilters), so an
#     unwanted column is hidden (FilterHandle.Visible = False), never
#     removed; a filter made here (AddNewFilter) gets its handle that way
#     at once, so the handle is looked up again before adding one (no
#     second handle for the same column);
#   - FilterGroup.Add(filter) appends a new handle (no move) and
#     FilterGroup.Remove(filter) removes that group's handle, so a column
#     goes into a sub group with sub.Add(filter), then old_group.Remove;
#   - TableGroup.AddNewSubGroup appends the sub group (a name used twice
#     throws); the items of a group are ordered with Items.Move;
#   - Filter.TypeId accepts CheckBoxFilter, ItemFilter, RadioButtonFilter,
#     RangeFilter, TextFilter and ListBoxFilter; the type belongs to the
#     filtering scheme, which every page shares (applied once per column).
# Each table, the hidden rest and each filter type is its own ok(...).
# A listed column the table does not have (a data function that did
# not return it) is left out with a NOTE line; the rest of the table
# is still organized.
# @api Page.FilterPanel; FilterPanel.TableGroups
# @api TableGroupCollection.GetEnumerator; TableGroupCollection.IndexOf
# @api TableGroupCollection.Move; TableGroup.Name; TableGroup.Expanded
# @api TableGroup.Visible; TableGroup.SubGroups; TableGroup.GetSubGroup
# @api TableGroup.AddNewSubGroup; TableGroup.FilterCollectionReference
# @api FilterGroup.GetFilter; FilterGroup.FilterHandles; FilterGroup.Add
# @api FilterGroup.Remove; FilterGroup.Items
# @api FilterGroupItemCollection.IndexOf; FilterGroupItemCollection.Move
# @api FilterSubGroup.Visible; FilterSubGroup.Expanded
# @api FilterHandle.FilterReference; FilterHandle.Visible
# @api FilterHandle.ParentGroup; Spotfire.Dxp.Application.Filters.Filter.Name
# @api Spotfire.Dxp.Application.Filters.Filter.TypeId
# @api FilterCollection.Contains(String); FilterCollection.Item
# @api FilterCollection.AddNewFilter(DataColumn)
# @api FilterCollection.DataTableReference; DataTable.Columns
# @api DataColumnCollection.Item; DataColumnCollection.Contains(String)
# @api Document.FilteringSchemes
# @api FilteringSchemeCollection.DefaultFilteringSchemeReference
# @api FilteringScheme.Item; FilterTypeIdentifiers.CheckBoxFilter
# @api FilterTypeIdentifiers.ListBoxFilter
# @api FilterTypeIdentifiers.RadioButtonFilter
# @api FilterTypeIdentifiers.RangeFilter; FilterTypeIdentifiers.TextFilter
# @api FilterTypeIdentifiers.ItemFilter
# @set TableGroup.Expanded; TableGroup.Visible; FilterSubGroup.Visible
# @set FilterSubGroup.Expanded; FilterHandle.Visible
# @set Spotfire.Dxp.Application.Filters.Filter.TypeId
from Spotfire.Dxp.Application.Filters import FilterTypeIdentifiers

# --------------------------------------------------------- filter panel
def filter_group(panel, table):
    """The panel's group of a table, or None."""
    for tg in panel.TableGroups:
        if tg.Name == table:
            return tg
    return None


def filter_of(fc, name):
    """The filter of column name in a filter collection (made when the
    collection has none yet)."""
    if fc.Contains(name):
        return fc[name]
    return fc.AddNewFilter(fc.DataTableReference.Columns[name])


def filter_find(tg, name):
    """The handle of a column: top level, then the sub groups; or None."""
    found = tg.GetFilter(name)
    if found is not None:
        return found
    for sub in tg.SubGroups:
        found = sub.GetFilter(name)
        if found is not None:
            return found
    return None


def filter_handle(tg, name):
    """The handle of a column; a column without one gets a new top-level
    handle (Spotfire adds it itself when the filter is new)."""
    found = filter_find(tg, name)
    if found is not None:
        return found
    item = filter_of(tg.FilterCollectionReference, name)
    found = filter_find(tg, name)
    if found is not None:
        return found
    return tg.Add(item)


def filter_known(tg, names, missing):
    """The names the table has, in order; the others go to missing."""
    cols = tg.FilterCollectionReference.DataTableReference.Columns
    out = []
    for name in names:
        if cols.Contains(name):
            out.append(name)
        elif name not in missing:
            missing.append(name)
    return out


def filter_into(tg, sub, name):
    """Column name into sub group sub: a new handle there, then the old
    one removed from its group."""
    found = sub.GetFilter(name)
    if found is not None:
        return found
    old = filter_handle(tg, name)
    item = old.FilterReference
    new = sub.Add(item)
    old.ParentGroup.Remove(item)
    return new


def filter_order(group, items):
    """items (handles and sub groups of group) first, in this order."""
    for i in range(len(items)):
        at = group.Items.IndexOf(items[i])
        if at >= 0 and at != i:
            group.Items.Move(at, i)


def filter_table(panel, entry, index):
    """One table: sub groups, shown and hidden columns, order, place."""
    tg = filter_group(panel, entry["table"])
    if tg is None:
        raise Exception("the filter panel has no group for table "
                        + entry["table"])
    subs = []
    moved = []
    missing = []
    for g in entry.get("groups", []):
        names = filter_known(tg, g[1], missing)
        if not names:
            continue
        sub = tg.GetSubGroup(g[0])
        if sub is None:
            sub = tg.AddNewSubGroup(g[0])
        handles = [filter_into(tg, sub, name) for name in names]
        for h in [x for x in sub.FilterHandles]:
            h.Visible = h.FilterReference.Name in names
        filter_order(sub, handles)
        sub.Visible = True
        sub.Expanded = g[2] if len(g) > 2 else True
        subs.append(sub)
        moved += names
    cols = entry["columns"]
    shown = []
    if cols != "*":
        cols = filter_known(tg, cols, missing)
        shown = [filter_handle(tg, name) for name in cols]
    count = len(moved)
    for h in [x for x in tg.FilterHandles]:
        name = h.FilterReference.Name
        h.Visible = name not in moved if cols == "*" else name in cols
        count += 1 if h.Visible else 0
    if cols != "*":
        filter_order(tg, shown + subs)
    tg.Expanded = entry.get("expanded", True)
    tg.Visible = True
    at = panel.TableGroups.IndexOf(tg)
    if at >= 0 and at != index:
        panel.TableGroups.Move(at, index)
    if missing:
        LOG.append("NOTE filters " + entry["table"] + ": no column "
                   + ", ".join(missing) + " in the table, left out")
    return count


def filter_others(panel, names):
    """Hide the groups of every table the layout does not list."""
    hidden = 0
    for tg in [x for x in panel.TableGroups]:
        if tg.Name not in names:
            tg.Visible = False
            hidden += 1
    return hidden


def filter_layout(page, ps):
    panel = page.FilterPanel
    entries = ps["filters"]
    shown = 0
    failed = 0
    start = len(LOG)
    for i in range(len(entries)):
        n = ok("filters " + ps["title"] + "/" + entries[i]["table"],
               filter_table, panel, entries[i], i)
        shown += n or 0
        failed += 1 if n is None else 0
    hidden = ok("filters " + ps["title"] + ": other tables",
                filter_others, panel, [e["table"] for e in entries])
    notes = [x for x in LOG[start:] if x.startswith("NOTE")]
    good = not failed and not notes and hidden is not None
    head = "OK" if good else "NOTE"
    LOG.append(head + " filters " + ps["title"] + ": " + str(len(entries))
               + " table(s) with " + str(shown) + " filter(s) shown, "
               + str(hidden or 0) + " other table(s) hidden")


def filter_type(table, column, name):
    """A column's filter type (on the default filtering scheme, which
    every page uses)."""
    scheme = Document.FilteringSchemes.DefaultFilteringSchemeReference
    item = filter_of(scheme[T[table]], column)
    item.TypeId = getattr(FilterTypeIdentifiers, name)
