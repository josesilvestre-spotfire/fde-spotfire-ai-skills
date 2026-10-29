"""Filter panel organization: the spec semantics shared by dxpgen validate, the standard
engine's generator and verify_dxp, so the three read a layout the same way.

Spec (references/spec-format.md "Filter panel"):

    "filterPanelLayout": {"tables": [...]}            top level: the layout of every page without "filters"
    page "filters": {"tables": [...]} | "all"         the page's own layout; "all" = Spotfire's default panel
                                                      (every table and column), on purpose

    table entry: {"table": "WELLS", "expanded": true, "columns": ["Well Name", "Region"] | "*",
                  "filterTypes": {"Well Name": "ListBoxFilter"},
                  "subGroups": [{"name": "Well parameters", "columns": [...], "expanded": false}]}

Semantics: listed tables are shown in the listed order, every other table is hidden; listed columns are
shown in the listed order at the top level of their table, then the sub groups in the listed order (each
with its columns in order); every other column is hidden ("*" = every column of the table that is not in a
sub group, in Spotfire's order). Filter types belong to the filtering scheme, which every page shares.

APP (engine/features/filterpanel.py):

    page "filters"  [{"table", "columns" ("*" | [names]), "expanded" (only False),
                      "groups" [[name, [columns]] or [name, [columns], False], ...]}, ...]
    "filterTypes"   [[table, column, FilterTypeIdentifiers member], ...] (each column once)
"""

# Filter.TypeId accepts these (15.0 IL of Filter.set_TypeId; CheckBoxHierarchyFilter only on a filter that
# already is one, so it is not offered)
FILTER_TYPES = ("CheckBoxFilter", "ListBoxFilter", "RadioButtonFilter", "RangeFilter", "TextFilter", "ItemFilter")
# filter types that need an ordered (number, date or time) column
RANGE_ONLY = ("RangeFilter",)
UNORDERED_TYPES = ("String", "Boolean")
LAYOUT_KEYS = ("tables",)
TABLE_KEYS = ("table", "expanded", "columns", "filterTypes", "subGroups")
GROUP_KEYS = ("name", "columns", "expanded")
ALL = "all"


def page_layout(spec, page):
    """The layout a page uses: its own "filters", else the top-level "filterPanelLayout"; None when the page
    keeps Spotfire's default panel ("filters": "all", or no layout anywhere)."""
    if not isinstance(page, dict):
        return None
    own = page.get("filters")
    if own == ALL:
        return None
    if isinstance(own, dict):
        return own
    top = spec.get("filterPanelLayout") if isinstance(spec, dict) else None
    return top if isinstance(top, dict) else None


def uses_layouts(spec):
    """True when any page of the spec organizes its filter panel."""
    pages = spec.get("pages") if isinstance(spec, dict) else None
    return any(page_layout(spec, p) is not None for p in (pages if isinstance(pages, list) else []))


def tables_of(layout):
    """Normalized table entries of a (valid) layout: [{table, columns ("*" or [names]), expanded,
    filterTypes {column: type}, subGroups [{name, columns, expanded}]}] in display order."""
    out = []
    for entry in (layout.get("tables") if isinstance(layout, dict) else None) or []:
        if not isinstance(entry, dict):
            continue
        columns = entry.get("columns")
        if columns != "*":
            columns = [c for c in (columns if isinstance(columns, list) else []) if isinstance(c, str)]
        groups = []
        for g in entry.get("subGroups") or []:
            if isinstance(g, dict):
                groups.append({"name": g.get("name"),
                               "columns": [c for c in g.get("columns") or [] if isinstance(c, str)],
                               "expanded": g.get("expanded", True) is not False})
        types = entry.get("filterTypes") if isinstance(entry.get("filterTypes"), dict) else {}
        out.append({"table": entry.get("table"), "columns": columns,
                    "expanded": entry.get("expanded", True) is not False,
                    "filterTypes": dict(types), "subGroups": groups})
    return out


def app_entry(table):
    """One normalized table entry -> the APP form of engine/features/filterpanel.py."""
    out = {"table": table["table"], "columns": table["columns"] if table["columns"] == "*"
           else list(table["columns"])}
    if not table["expanded"]:
        out["expanded"] = False
    if table["subGroups"]:
        out["groups"] = [[g["name"], list(g["columns"])] + ([] if g["expanded"] else [False])
                         for g in table["subGroups"]]
    return out


def app_keys(spec):
    """({page title: APP "filters"}, APP "filterTypes") for the pages that organize their panel."""
    pages = {}
    types = []
    seen = set()
    for page in spec.get("pages") or []:
        layout = page_layout(spec, page)
        if layout is None:
            continue
        entries = tables_of(layout)
        pages[page.get("title")] = [app_entry(t) for t in entries]
        for t in entries:
            for column, ftype in t["filterTypes"].items():
                key = (t["table"], column)
                if key not in seen:
                    seen.add(key)
                    types.append([t["table"], column, ftype])
    return pages, types


def shown_columns(table):
    """Columns a normalized table entry shows: top level (None for "*") and per sub group."""
    top = None if table["columns"] == "*" else list(table["columns"])
    return top, [(g["name"], list(g["columns"])) for g in table["subGroups"]]
