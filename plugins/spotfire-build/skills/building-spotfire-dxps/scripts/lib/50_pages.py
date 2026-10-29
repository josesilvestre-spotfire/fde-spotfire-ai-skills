# ============================================================================
# 50_pages.py - spec pages and their layout:
#   pages_create       every spec page with a temporary unique title, registered
#                      under its spec title (doc_finish sets the final titles);
#                      Visible, filter and details-on-demand panels, filtering scheme
#   page_apply_layout  layout tree -> one LayoutDefinition holding every visual of
#                      the page -> ApplyLayout -> GetVisualBounds self-check
# IronPython 3.4 (no f-strings, walrus, annotations, print or tabs).
# Requires newer than 14.6: none (newest public member: Page.Visible, api 10.7).
# Internal API: none.
# BCL: System.Single, System.Drawing.Rectangle.
# ============================================================================
import clr
clr.AddReference("System.Drawing")
from System import Single
from System.Drawing import Rectangle
from Spotfire.Dxp.Application.Layout import LayoutDefinition, DockingPlacement, PanelRegion, PanelState

_pages_space = 100000      # GetVisualBounds(v, Rectangle(0, 0, 100000, 100000)) = persisted RelativeBounds
_pages_splitter = 3        # splitter thickness in that space (IL, LayoutBuilder)
_pages_tolerance = 3       # allowed drift per coordinate in the layout self-check


# ---- pages ---------------------------------------------------------------------
def pages_create(pages):
    """Create every spec page (one B.step each) and register it under its spec title.

    A page is added as 'dxpb-page-NN': titles are unique case-insensitively and a clash is
    renamed silently ('Page (2)'), so a temporary title can never collide with the pages of the
    starting document. Visuals, controls and links find pages through B.page(title); doc_finish
    removes the starting pages and sets the final titles. Returns the created pages."""
    created = []
    exact = set()
    folded = set()
    number = 0
    for pspec in pages:
        number += 1
        title = pspec.get("title")
        if title in exact:
            B.step("page", title, _pages_duplicate, (title,))
            continue
        exact.add(title)
        key = "" if title is None else str(title).strip().lower()
        if key in folded:
            B.warn("page title '" + str(title) + "' differs from another page title only in case or "
                   "spaces; Spotfire keeps titles unique and will rename it")
        folded.add(key)
        page = B.step("page", title, _pages_add, (number, title))
        if page is None:
            continue
        created.append(page)
        visible = bool(pspec.get("visible", True))
        B.step("page.visible", title, _pages_set_visible, (page, pspec),
               fallback=("Show" if visible else "Hide") + " the page '" + str(title) + "'.")
        B.step("page.panels", title, _pages_set_panels, (page, pspec),
               fallback=_pages_panels_manual(title, pspec))
        scheme = pspec.get("filteringScheme")
        B.step("page.filteringScheme", title, _pages_set_scheme, (page, scheme),
               fallback=_pages_scheme_manual(title, scheme))
    return created


def _pages_duplicate(title):
    raise Exception("page title '" + str(title) + "' is used by more than one spec page; only the "
                    "first one is built")


def _pages_add(number, title):
    """An empty title is still registered, so the page and its visuals are built; Spotfire rejects
    the empty title at the final rename (doc_finish), which reports it as a manual step and the
    page keeps its temporary title."""
    if title is None:
        raise Exception("page has no title")
    page = B.doc.Pages.AddNew("dxpb-page-%02d" % number)     # appended at the end, becomes active
    B.register_page(title, page)
    if not str(title).strip():
        B.warn("a spec page has an empty title; it keeps the temporary title " + page.Title)
    return page


def _pages_set_visible(page, pspec):
    page.Visible = bool(pspec.get("visible", True))
    return page.Visible


def _pages_set_panels(page, pspec):
    """API-made pages start with both panels hidden and without docking (IL). Visibility comes
    from the spec; the docking GUI-made pages persist (filters right 0, details-on-demand
    right 1, docked) is added so a panel opened later docks like on any other page."""
    page.FilterPanel.Visible = bool(pspec.get("filterPanel", False))
    page.DetailsOnDemandPanel.Visible = bool(pspec.get("detailsOnDemand", False))
    try:
        # Not yet tested: explicit docking renders like a GUI-made page when a panel is shown
        #.
        _pages_dock(page.FilterPanel, 0)
        _pages_dock(page.DetailsOnDemandPanel, 1)
    except Exception as e:
        B.warn("page '" + str(pspec.get("title")) + "': panel docking left at Spotfire's default: "
               + exc_text(e))
    return page


def _pages_dock(panel, index):
    panel.DockingPlacement = DockingPlacement(PanelRegion.Right, index)
    panel.PanelState = PanelState.Docked


def _pages_set_scheme(page, name):
    """FilterPanel.FilteringSchemeReference = the named scheme, or the default scheme. API-made
    pages start with none, which leaves the page without an active filtering (IL), so the
    default is assigned first: a missing named scheme still leaves a working page."""
    # Not yet tested: the saved page has FilterPanel.FilteringScheme set, TableGroups > 0 and a
    # Page.ActiveFilteringSelectionReference.
    panel = page.FilterPanel
    panel.FilteringSchemeReference = B.doc.FilteringSchemes.DefaultFilteringSchemeReference
    if not name:
        return panel.FilteringSchemeReference
    try:
        # raises when the scheme is missing or its FilteringScheme does not exist yet
        # (Not yet tested: created by an internal event handler right after Filterings.Add in
        # the same script).
        scheme = B.filtering_scheme(name)
    except Exception as e:
        raise Exception(exc_text(e) + "; the page uses the default filtering scheme")
    panel.FilteringSchemeReference = scheme
    return scheme


def _pages_scheme_manual(title, name):
    scheme = ("the filtering scheme '" + str(name) + "'") if name else "the default filtering scheme"
    return ("On page '" + str(title) + "', show the Filters panel and select " + scheme
            + " in the filtering-scheme menu at the top of the panel (if that menu is hidden, turn it on "
            "under Edit > Document Properties > Filtering Schemes); hide the panel again if the page "
            "should not show it.")


def _pages_panels_manual(title, pspec):
    def word(flag):
        return "shown" if flag else "hidden"
    return ("On page '" + str(title) + "', keep the Filters panel " + word(pspec.get("filterPanel", False))
            + " and the Details-on-Demand panel " + word(pspec.get("detailsOnDemand", False)) + ".")


# ---- layout --------------------------------------------------------------------
def page_apply_layout(page, pspec):
    """pspec["layout"] -> one LayoutDefinition holding every visual on the page -> ApplyLayout,
    then a read-back of every visual's bounds against the shares the spec asks for (warning on
    drift). A page with one visual needs no layout: Spotfire gives a lone visual the page."""
    title = pspec.get("title", "")
    spec_ids = [v.get("id") for v in pspec.get("visuals", [])]
    tree = _pages_root(pspec.get("layout"))
    if tree is not None:
        _pages_validate(tree, spec_ids, title)
    placed = _pages_resolve(page, spec_ids, title)
    if not placed:
        return page
    if tree is not None:
        tree = _pages_prune(tree, placed)
    if tree is None:
        if len(placed) > 1:
            raise Exception("page '" + title + "' has " + str(len(placed)) + " visuals but no layout")
        tree = {"row": [{"visual": list(placed.keys())[0]}]}
        if not _pages_check(page, placed, _pages_expected(tree), title, False):
            _pages_apply(page, tree, placed)        # repair an unexpected auto-placement
    else:
        _pages_apply(page, tree, placed)
    _pages_check(page, placed, _pages_expected(tree), title, True)
    return page


def _pages_root(layout):
    """None when the spec gives no layout; a bare {"visual": id} becomes a one-item row."""
    if not layout:
        return None
    if isinstance(layout, dict) and "visual" in layout and "row" not in layout and "column" not in layout:
        return {"row": [layout]}
    return layout


def _pages_validate(tree, spec_ids, title):
    """Spotfire rejects a LayoutDefinition that misses a visual, names one twice, nests a section
    in one of the same orientation or holds an empty section (IL): check all of it up front."""
    errors = []
    counts = {}
    _pages_walk(tree, "layout", None, counts, errors)
    for vid in spec_ids:
        n = counts.get(vid, 0)
        if n == 0:
            errors.append("visual '" + str(vid) + "' is not in the layout")
        elif n > 1:
            errors.append("visual '" + str(vid) + "' appears " + str(n) + " times")
    for vid in sorted(counts):
        if vid not in spec_ids:
            errors.append("visual '" + vid + "' is not a visual of this page")
    if errors:
        raise Exception("invalid layout on page '" + title + "': " + "; ".join(errors))


def _pages_walk(node, path, parent, counts, errors):
    if not isinstance(node, dict):
        errors.append(path + " must be an object")
        return
    kinds = [k for k in ("row", "column", "visual") if k in node]
    if len(kinds) != 1:
        errors.append(path + " needs exactly one of row, column, visual")
        return
    if parent is not None and "weight" in node:      # the root's weight is ignored by Spotfire
        problem = _pages_weight_problem(node["weight"])
        if problem:
            errors.append(path + ".weight " + problem)
    kind = kinds[0]
    if kind == "visual":
        vid = node["visual"]
        if not isinstance(vid, str) or not vid:
            errors.append(path + ".visual must be a visual id")
            return
        counts[vid] = counts.get(vid, 0) + 1
        return
    if kind == parent:
        errors.append(path + " is a " + kind + " directly inside a " + kind
                      + " (nested containers must alternate row and column)")
    items = node[kind]
    if not isinstance(items, list) or not items:
        errors.append(path + "." + kind + " must be a non-empty list")
        return
    for i in range(len(items)):
        _pages_walk(items[i], path + "." + kind + "[" + str(i) + "]", kind, counts, errors)


def _pages_weight_problem(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "must be a number"
    if value != value or value < 1e-12 or value > 1e12:
        return "must be between 1e-12 and 1e12 (got " + repr(value) + ")"
    return None


def _pages_weight(node):
    return float(node.get("weight", 1))


def _pages_as_visual(obj):
    """The Visual wrapper for a builder result (content objects carry it in .Visual)."""
    inner = getattr(obj, "Visual", None)
    return obj if inner is None else inner


def _pages_resolve(page, spec_ids, title):
    """{spec visual id: Visual} covering every visual on the page; ApplyLayout rejects a
    definition that misses one. A visual builder that failed after Spotfire created its visual
    leaves an unregistered visual behind; 90_build.build_visual records it per visual id in
    B.visual_leftovers. A failed id with exactly one leftover keeps its layout slot with that
    visual (as far as it was built); every other unregistered visual is removed and the ids
    that still have no visual are pruned from the layout."""
    on_page = [v for v in page.Visuals]
    by_guid = dict((str(v.Id), v) for v in on_page)
    owners = {}
    for vid in B.created["visuals"]:
        owners[B.created["visuals"][vid]["guid"]] = vid
    placed = {}
    missing = []
    for vid in spec_ids:
        visual = None
        if vid in B.created["visuals"]:
            visual = by_guid.get(str(_pages_as_visual(B.visual(vid)).Id))
        if visual is None:
            missing.append(vid)
        else:
            placed[vid] = visual
    orphans = []
    foreign = []
    for v in on_page:
        owner = owners.get(str(v.Id))
        if owner is None:
            orphans.append(v)
        elif owner not in spec_ids:
            foreign.append(owner)
    if foreign:
        raise Exception("page '" + title + "' also holds visuals of other pages: " + ", ".join(foreign)
                        + " (two spec pages with the same title?)")
    leftovers = getattr(B, "visual_leftovers", None) or {}
    orphan_guids = set(str(v.Id) for v in orphans)
    for vid in list(missing):
        mine = [v for v in leftovers.get(vid) or [] if str(v.Id) in orphan_guids]
        if len(mine) == 1:
            placed[vid] = by_guid[str(mine[0].Id)]
            orphan_guids.discard(str(mine[0].Id))
            missing.remove(vid)
            B.warn("page '" + title + "': visual '" + str(vid) + "' failed after Spotfire created it; "
                   "it keeps its layout slot as far as it was built")
    for v in orphans:
        if str(v.Id) not in orphan_guids:
            continue
        name = str(v.Title) + " (" + v.TypeId.Name + ")"
        page.Visuals.Remove(v)
        B.warn("page '" + title + "': removed visual '" + name + "' left behind by a failed visual "
               "builder, so the layout could be applied")
    for vid in missing:
        B.warn("page '" + title + "': visual '" + str(vid) + "' was not built; the layout is applied "
               "without it")
    if page.Visuals.Count != len(placed):
        raise Exception("page '" + title + "' holds " + str(page.Visuals.Count) + " visuals but "
                        + str(len(placed)) + " could be matched to the spec")
    return placed


def _pages_prune(node, placed):
    """Copy of the tree without the visuals that are not placed; empty containers disappear
    (Spotfire divides by zero on an empty section). Orientation alternation is preserved."""
    if "visual" in node:
        return node if node["visual"] in placed else None
    kind = "row" if "row" in node else "column"
    items = []
    for item in node[kind]:
        kept = _pages_prune(item, placed)
        if kept is not None:
            items.append(kept)
    if not items:
        return None
    copy = dict(node)
    copy[kind] = items
    return copy


def _pages_apply(page, tree, placed):
    """A LayoutDefinition is single-use: build a new one for every ApplyLayout."""
    # Not yet tested: the VisualPanel of a just-added visual exists when the builder runs
    # wrapped in a transaction (IL says yes).
    layout = LayoutDefinition()
    _pages_emit(layout, tree, placed, True)
    page.ApplyLayout(layout)
    return layout


def _pages_emit(layout, node, placed, root):
    """row = side-by-side section (items left to right), column = stacked section (items top
    to bottom). Proportions are System.Single weights relative to their siblings."""
    kind = "row" if "row" in node else "column"
    if root:
        if kind == "row":
            layout.BeginSideBySideSection()
        else:
            layout.BeginStackedSection()
    else:
        weight = Single(_pages_weight(node))
        if kind == "row":
            layout.BeginSideBySideSection(weight)
        else:
            layout.BeginStackedSection(weight)
    for item in node[kind]:
        if "visual" in item:
            layout.Add(placed[item["visual"]], Single(_pages_weight(item)))
        else:
            _pages_emit(layout, item, placed, False)
    layout.EndSection()


def _pages_expected(tree):
    """{visual id: [x, y, width, height]} in the 100000 x 100000 page space, computed the way
    LayoutBuilder does it (IL): a section's items share its range by weight, each splitter sits
    at int(share * 100000) of the page and is 3 units thick, a panel starts after the previous
    splitter and ends at the next splitter or at the section's edge."""
    out = {}
    _pages_expect(tree, (0.0, 1.0), (0.0, 1.0), (0, _pages_space), (0, _pages_space), out)
    return out


def _pages_expect(node, xs, ys, xe, ye, out):
    kind = "row" if "row" in node else "column"
    items = node[kind]
    weights = [_pages_weight(item) for item in items]
    total = sum(weights)
    low, high = xs if kind == "row" else ys
    start, edge = xe if kind == "row" else ye
    pos = low
    for i in range(len(items)):
        nxt = pos + (high - low) * weights[i] / total
        end = _pages_cut(nxt) if i < len(items) - 1 else edge
        if kind == "row":
            child = ((pos, nxt), ys, (start, end), ye)
        else:
            child = (xs, (pos, nxt), xe, (start, end))
        item = items[i]
        if "visual" in item:
            cxe, cye = child[2], child[3]
            out[item["visual"]] = [cxe[0], cye[0], cxe[1] - cxe[0], cye[1] - cye[0]]
        else:
            _pages_expect(item, child[0], child[1], child[2], child[3], out)
        pos = nxt
        start = end + _pages_splitter


def _pages_cut(share):
    """Splitter position int(share * 100000f); the epsilon absorbs double vs Single rounding."""
    return int(share * _pages_space + 1e-6)


def _pages_check(page, placed, expected, title, record):
    """Compare GetVisualBounds (the persisted RelativeBounds when the area is 100000 x 100000)
    with the expected bounds. record=True stores both in B.created["layouts"] and warns on drift."""
    # Not yet tested: the read-back equals the computed bounds
    #, and equals VisualPanel.RelativeBounds in the decompiled file.
    area = Rectangle(0, 0, _pages_space, _pages_space)
    bounds = {}
    drift = []
    for vid in sorted(placed):
        r = page.GetVisualBounds(placed[vid], area)
        actual = [r.X, r.Y, r.Width, r.Height]
        want = expected.get(vid)
        bounds[vid] = {"actual": actual, "expected": want}
        if want is None or max([abs(actual[i] - want[i]) for i in range(4)]) > _pages_tolerance:
            drift.append(vid + " at " + str(actual) + ", expected " + str(want))
    if record:
        B.created.setdefault("layouts", {})[title] = bounds
        if drift:
            B.warn("layout of page '" + title + "' differs from the spec (tolerance "
                   + str(_pages_tolerance) + " of 100000): " + "; ".join(drift))
    return not drift
