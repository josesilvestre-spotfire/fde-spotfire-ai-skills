# Standard engine, part "core" (IronPython 3.4, Spotfire Analyst 15.0).
# Everything a builder needs besides HOME, STYLE, APP and the per-kind
# builders: helpers, data loading with embedding and column formats, the
# marking, pages, common visual helpers, the build loop, the layout tree,
# starter-table handling and the inline-first save. Apps with features
# (the guard part) also get the build session switch after a successful
# inline save (features/guard.py switch_session) and the preflight
# (features/preflight.py): every file the builder reads from HOME must
# exist before the first document change, and the log's first line names
# the spec hash (and release) of the builder. Apps with a filter panel
# layout (features/filterpanel.py) organize each page's filter panel
# after the starter tables are removed. Apps with mod visuals (feature
# vizMods) find each visualization mod (features/modload.py load_viz)
# and add their visuals through builders/mod.py new_mod_visual; their
# starter pages get a " (starter)" title and go only after every page is
# built, so a mod visual you placed on the starter page keeps the mod in
# the analysis until the app's own mod visuals exist. Everything the
# public API cannot build (text-area controls, property triggers, the
# document theme, action mods) is listed in APP "manual" and logged as
# TODO lines at the end of the build (feature manual).
#
# scripts/dxpgen.py assembles a builder from it (references/engine.md):
#   - this leading comment block is not copied; "# @..." lines never are;
#   - lines between "# @tier quick" and "# @end" are kept for the quick,
#     standard and report tiers, lines between "# @tier standard" and
#     "# @end" for standard and report only (compact keeps neither);
#   - imports are hoisted to the top of the builder (unused ones dropped);
#   - the used builders (engine/builders) and, for the report tier,
#     engine/report.py go where the "# @builders" line is.
# Members verified with scripts/sfapi.py has (dxpgen runs it per build;
# the styling members sit in the tier blocks, so each tier checks its
# own):
# @api AnalysisApplication.DocumentMetadata; DocumentMetadata.LoadedFromFileName
# @api Document.Data; DataManager.Tables; DataTable.Name; DataTable.Id
# @api SbdfFileDataSource.ctor(String); SbdfFileDataSource.IsPromptingAllowed
# @api DataTableCollection.Add(String, DataSource, Boolean)
# @api DataManager.SaveSettings; DataSaveSettings.TryGetDataTableSettings
# @api DataSaveSettings.DataTableSettings; DataTableSaveSettings.UseLinkedData
# @api DataTableSaveSettings.ctor(DataTable, Boolean, Boolean)
# @api DataTable.Columns; DataColumn.DataType; DataType.CreateLocalizedFormatter
# @api NumberFormatter.FormatString; DataColumn.Properties
# @api DataColumnProperties.Formatter; DataType.Real
# @api DataManager.Markings; DataMarkingSelectionCollection.DefaultMarkingReference
# @api DataMarkingSelection.Name; DataMarkingSelection.Color
# @api Document.Pages; PageCollection.AddNew(String); PageCollection.Remove(Page)
# @api Page.Title; Page.FilterPanel; FilterPanel.FilteringSchemeReference
# @api FilterPanel.Visible; Document.FilteringSchemes
# @api FilteringSchemeCollection.DefaultFilteringSchemeReference
# @api Page.DetailsOnDemandPanel; DetailsOnDemandPanel.Visible
# @api Page.Visuals; VisualCollection.AddNew(TypeIdentifier); Visual.Title
# @api Visual.ShowTitle; Visual.As; Legend.Visible; VisualTypeIdentifiers
# @api LayoutDefinition.ctor; LayoutDefinition.BeginSideBySideSection
# @api LayoutDefinition.BeginStackedSection; LayoutDefinition.Add
# @api LayoutDefinition.EndSection; Page.ApplyLayout
# @api Document.ActivePageReference; DataTableCollection.DefaultTableReference
# @api DataTableCollection.Remove(DataTable); Document.Properties
# @api DocumentProperties.Description; DocumentProperties.Keywords
# @api PageCollection.NavigationMode; PageNavigationMode.Links
# @api PageNavigationMode.None; PageNavigationMode.Off
# @api AnalysisApplication.SaveAs(String, DocumentSaveSettings)
# @api DocumentSaveSettings.ctor; AnalysisApplication.GetService
# @api ApplicationThread.InvokeAsynchronously; ApplicationInvocation
# @set DataTable.Name; SbdfFileDataSource.IsPromptingAllowed
# @set DataTableSaveSettings.UseLinkedData; NumberFormatter.FormatString
# @set DataColumnProperties.Formatter; DataMarkingSelection.Name
# @set DataMarkingSelection.Color; Page.Title; FilterPanel.Visible
# @set FilterPanel.FilteringSchemeReference; DetailsOnDemandPanel.Visible
# @set Visual.Title; Visual.ShowTitle; Legend.Visible
# @set Document.ActivePageReference; DataTableCollection.DefaultTableReference
# @set DocumentProperties.Description; DocumentProperties.Keywords
# @set PageCollection.NavigationMode
import clr
clr.AddReference("System.Drawing")
import json
from System import Single
from System.IO import File, Path, Directory
from System.Drawing import ColorTranslator
from System.Collections.Generic import List
from Spotfire.Dxp.Application import DocumentSaveSettings
from Spotfire.Dxp.Application import PageNavigationMode
from Spotfire.Dxp.Application.Layout import LayoutDefinition
from Spotfire.Dxp.Application.Visuals import VisualTypeIdentifiers
from Spotfire.Dxp.Data import DataTableSaveSettings, DataType
from Spotfire.Dxp.Data.Import import SbdfFileDataSource
from Spotfire.Dxp.Framework.Styles import FontMetadata
from Spotfire.Dxp.Framework.Styles import FontStyleFlags, FontUnit
from Spotfire.Dxp.Framework.ApplicationModel import ApplicationThread
from Spotfire.Dxp.Framework.ApplicationModel import ApplicationInvocation

# =============================================================== engine
# Standard engine (engine/core.py and engine/builders). Nothing below
# needs editing: change spec.json and run dxpgen.py build again.
OUT = Path.Combine(HOME, APP["output"])
LOG_FILE = Path.Combine(HOME, APP["log"])
LOG = []
BUILDERS = {}        # kind -> build_<kind>(v, vs); each builder adds itself
TYPE_IDS = {}        # kind -> VisualTypeIdentifiers member name


def why(e):
    """Exception text plus the .NET inner exception."""
    text = str(e)
    inner = getattr(getattr(e, "clsException", None), "InnerException",
                    None)
    if inner is not None:
        text += " | " + str(inner.Message)
    return text


def ok(name, fn, *args):
    """Run one build item; a failure becomes a log line, never a stop."""
    try:
        return fn(*args)
    except Exception as e:
        LOG.append("FAILED " + name + ": " + why(e))
        return None


def rename_starter(t):
    if t.Name in TABLE_NAMES:
        t.Name = t.Name + " (starter)"


# --------------------------------------------------------- style values
def hexcode(value):
    """'@name' (STYLE palette) or '#RRGGBB' -> '#RRGGBB'."""
    if value.startswith("@"):
        return STYLE["palette"][value[1:]]
    return value


def rgb(value):
    return ColorTranslator.FromHtml(hexcode(value))


def fmt(name):
    """Format name from STYLE['formats'], or a literal format string."""
    return STYLE["formats"].get(name, name)


def opt(vs, key, default=None):
    """A visual's own value for key, else the STYLE default for its
    type, else default."""
    if key in vs:
        return vs[key]
    return STYLE["visual"].get(vs["type"], {}).get(key, default)


# @tier quick
# @api FontMetadata.ctor(String, Single, FontStyleFlags, FontUnit)
# @api FontStyleFlags.Bold; FontStyleFlags.Regular; FontUnit.Point
def font(size, bold=False):
    flags = FontStyleFlags.Bold if bold else FontStyleFlags.Regular
    return FontMetadata(STYLE["font"], Single(size), flags,
                        FontUnit.Point)
# @end


# @tier standard
def formatter(name):
    f = DataType.Real.CreateLocalizedFormatter()
    f.FormatString = fmt(name)
    return f
# @end


# ----------------------------------------------------------------- data
T = {}


def load(name, rel=None):
    """data\\<name>.sbdf (or rel, relative to HOME), embedded."""
    path = Path.Combine(HOME, rel or "data\\" + name + ".sbdf")
    # @feature !pathFree
    ds = SbdfFileDataSource(path)
    ds.IsPromptingAllowed = False
    t = Document.Data.Tables.Add(name, ds, True)
    # @endfeature
    # @feature pathFree
    t = add_sbdf(name, path)
    # @endfeature
    settings = Document.Data.SaveSettings
    found, entry = settings.TryGetDataTableSettings(t.Id)
    if found:
        entry.UseLinkedData = False
    else:
        settings.DataTableSettings.Add(
            DataTableSaveSettings(t, False, False))
    T[name] = t


def set_format(tname, cname, name):
    col = T[tname].Columns[cname]
    formatter_ = col.DataType.CreateLocalizedFormatter()
    formatter_.FormatString = fmt(name)
    col.Properties.Formatter = formatter_


def marking():
    m = Document.Data.Markings.DefaultMarkingReference
    m.Name = APP["marking"][0]
    if APP["marking"][1]:
        m.Color = rgb(APP["marking"][1])


def default_marking():
    return Document.Data.Markings.DefaultMarkingReference


# ---------------------------------------------------------------- pages
PAGES = {}
VIS = {}


def list_pages():
    return [p for p in Document.Pages]


def add_page(title):
    PAGES[title] = Document.Pages.AddNew(title)


def remove_pages(pages):
    for p in pages:
        Document.Pages.Remove(p)


# @feature vizMods
def rename_starter_page(page):
    """Apps with mod visuals keep the starter pages until their own
    visuals are built: the new title keeps the spec's page titles free."""
    page.Title = page.Title + " (starter)"
# @endfeature


def page_settings(page, ps):
    page.Title = ps["title"]
    page.FilterPanel.FilteringSchemeReference = (
        Document.FilteringSchemes.DefaultFilteringSchemeReference)
    page.FilterPanel.Visible = bool(ps.get("filterPanel", False))
    if "detailsOnDemand" in ps:
        page.DetailsOnDemandPanel.Visible = bool(ps["detailsOnDemand"])


# ------------------------------------------------------ common visuals
def new_visual(page, kind):
    return page.Visuals.AddNew(getattr(VisualTypeIdentifiers,
                                       TYPE_IDS[kind]))


def set_title(v, vs):
    v.Title = vs.get("title", "")
    v.ShowTitle = bool(opt(vs, "showTitle", True))


def legend(content, vs):
    content.Legend.Visible = bool(opt(vs, "legend", True))


def run_builder(v, vs):
    BUILDERS[vs["type"]](v, vs)


def build_visual(page, vs):
    """Add the visual first and keep it, so the layout always holds
    every visual on the page; then title and content as separate items.
    Returns True when the visual exists."""
    vid = vs["id"]
    # @feature !vizMods
    v = ok(vid + ": add", new_visual, page, vs["type"])
    # @endfeature
    # @feature vizMods
    # @note a mod visual is added from its ModIdentifier (builders/mod.py
    # @note new_mod_visual: a placeholder text area when the mod is not
    # @note in the analysis; the data links, settings and legend items
    # @note then stay off it)
    if vs["type"] == "mod":
        v = ok(vid + ": add", new_mod_visual, page, vs)
    else:
        v = ok(vid + ": add", new_visual, page, vs["type"])
    # @endfeature
    if v is None:
        return False
    VIS[vid] = v
    ok(vid + ": title", set_title, v, vs)
    ok(vid + ": build", run_builder, v, vs)
    # @feature vizMods
    if vid in MOD_PLACEHOLDERS:
        return True
    # @endfeature
    # @feature links
    ok(vid + ": data links", data_links, v, vs)
    # @endfeature
    # @feature settings
    if vs.get("settings"):
        ok(vid + ": settings", visual_settings, v, vs)
    # @endfeature
    # @feature legendHide
    if vs.get("legendHide"):
        ok(vid + ": legend items", hide_legend_items, v, vs)
    # @endfeature
    return True


# --------------------------------------------------------------- layout
def weight(node):
    return float(node.get("weight", 1))


def prune(node, built, used):
    """Copy of a layout node without unbuilt visuals or empty sections;
    a section inside one of the same kind is merged into its parent."""
    if "visual" in node:
        vid = node["visual"]
        if vid in built and vid not in used:
            used.append(vid)
            return node
        return None
    kind = "row" if "row" in node else "column"
    items = []
    for child in node[kind]:
        kept = prune(child, built, used)
        if kept is None:
            continue
        if kind in kept:
            total = sum([weight(g) for g in kept[kind]])
            for g in kept[kind]:
                g2 = dict(g)
                g2["weight"] = weight(kept) * weight(g) / total
                items.append(g2)
        else:
            items.append(kept)
    if not items:
        return None
    out = dict(node)
    out[kind] = items
    return out


def emit(L, node, root):
    """row = side-by-side section, column = stacked section."""
    kind = "row" if "row" in node else "column"
    if kind == "row" and root:
        L.BeginSideBySideSection()
    elif kind == "row":
        L.BeginSideBySideSection(Single(weight(node)))
    elif root:
        L.BeginStackedSection()
    else:
        L.BeginStackedSection(Single(weight(node)))
    for item in node[kind]:
        if "visual" in item:
            L.Add(VIS[item["visual"]], Single(weight(item)))
        else:
            emit(L, item, False)
    L.EndSection()


def apply_layout(page, tree, built):
    used = []
    if tree and "visual" in tree:
        tree = {"column": [tree]}
    tree = prune(tree or {"column": []}, built, used)
    extra = [{"visual": vid} for vid in built if vid not in used]
    if tree is None:
        tree = {"column": []}
    kind = "row" if "row" in tree else "column"
    tree[kind] = tree[kind] + extra
    if extra:
        LOG.append("NOTE " + page.Title + ": not in the layout tree, "
                   "added at the end: "
                   + ", ".join([x["visual"] for x in extra]))
    if not tree[kind]:
        return
    L = LayoutDefinition()
    emit(L, tree, True)
    page.ApplyLayout(L)


def build_page(page, ps):
    built = []
    for vs in ps["visuals"]:
        if build_visual(page, vs):
            built.append(vs["id"])
    ok("layout " + ps["title"], apply_layout, page, ps.get("layout"),
       built)


# --------------------------------------------------------------- finish
def set_active():
    Document.ActivePageReference = PAGES[APP["activePage"]]


# @feature hiddenPages
# @api Page.Visible
# @set Page.Visible
# @note lib/50_pages.py _pages_set_visible; run after the active page
# @note is set, so every page is built while it is still shown.
def hide_page(page):
    page.Visible = False
# @endfeature


def remove_starter_tables():
    if APP["defaultTable"] in T:
        tables = Document.Data.Tables
        tables.DefaultTableReference = T[APP["defaultTable"]]
    for t in STARTER_TABLES:
        Document.Data.Tables.Remove(t)


def describe():
    Document.Properties.Description = APP["description"]


def keywords():
    Document.Properties.Keywords = List[str](APP["keywords"])


def navigation():
    mode = getattr(PageNavigationMode, APP["navigation"])
    Document.Pages.NavigationMode = mode


# ----------------------------------------------------------------- save
def write_log():
    Directory.CreateDirectory(Path.GetDirectoryName(LOG_FILE))
    failed = [x for x in LOG if x.startswith("FAILED")]
    head = "No problems." if not failed else (
        str(len(failed)) + " problem(s), the build went on:")
    # @feature preflight
    head = log_stamp(head)
    # @endfeature
    File.WriteAllText(LOG_FILE, "\r\n".join([head] + LOG))


TRIES = [0]


def queue(fn):
    thread = Application.GetService[ApplicationThread]()
    thread.InvokeAsynchronously(ApplicationInvocation(fn))


def save():
    try:
        Application.SaveAs(OUT, DocumentSaveSettings())
        LOG.append("Saved " + OUT)
    except Exception as e:
        TRIES[0] += 1
        if "not idle" in str(e) and TRIES[0] < 20:
            queue(save)
            return
        LOG.append("FAILED save: " + str(e)
                   + " - use File > Save As instead.")
    write_log()


def save_now():
    try:
        Application.SaveAs(OUT, DocumentSaveSettings())
        LOG.append("Saved " + OUT)
        return True
    except Exception as e:
        LOG.append("Save inside the script was refused (" + str(e)
                   + "); retrying after the script ends. No 'Saved' "
                   "line below means: use File > Save As, then check "
                   "the marking name and the description (closing the "
                   "Document Properties dialog can reset them).")
        # @feature guard
        LOG.append("CHECK after File > Save As: " + recheck())
        # @endfeature
        return False


def finish():
    """The save runs inside the script first (it works when 'Execute in
    transaction' is unticked); when Spotfire refuses it, it is queued for
    after the script, and File > Save As is the last resort."""
    ok("write log", write_log)
    if ok("save", save_now):
        # @feature guard
        ok("build session", switch_session)
        # @endfeature
        ok("write log", write_log)
    else:
        ok("queue save", queue, save)
        ok("write log", write_log)


# @builders


# ================================================================ build
OPENED_FROM = Application.DocumentMetadata.LoadedFromFileName
if OPENED_FROM:
    raise Exception(
        "Nothing was changed: this analysis was opened from "
        + OPENED_FROM + ". Run the script in a new analysis with "
        "starter data loaded (File > New, add any data).")
# @feature preflight
MISSING = missing_files()
if MISSING:
    raise Exception(mismatch_text(MISSING))
# @endfeature

TABLE_NAMES = [entry[0] for entry in APP["tables"]]
# @feature dataFunctions
for d in APP["dataFunctions"]:
    TABLE_NAMES += [o[2] for o in d["out"] if o[1] == "table"]
# @endfeature
STARTER_TABLES = [t for t in Document.Data.Tables]
for t in STARTER_TABLES:
    ok("rename starter table", rename_starter, t)
# @feature properties
for p in APP["properties"]:
    ok("property " + p[0], add_property, p)
# @endfeature
for entry in APP["tables"]:
    ok("load " + entry[0], load, entry[0],
       entry[2] if len(entry) > 2 else None)
for entry in APP["tables"]:
    if entry[0] in T:
        for name in sorted(entry[1]):
            for cname in entry[1][name]:
                ok("format " + entry[0] + "." + cname, set_format,
                   entry[0], cname, name)
ok("marking", marking)
MARK = ok("default marking", default_marking)
# @feature markings
for entry in APP["markings"]:
    ok("marking " + entry[0], add_marking, entry[0], entry[1])
# @endfeature
# @feature dataFunctions
for d in APP["dataFunctions"]:
    ok("data function " + d["name"], build_function, d)
for entry in APP["dfTables"]:
    if entry[0] in T:
        for name in sorted(entry[1]):
            for cname in entry[1][name]:
                ok("format " + entry[0] + "." + cname, set_format,
                   entry[0], cname, name)
# @endfeature
# @feature scripts
for s in APP["scripts"]:
    ok("script " + s["name"], add_script, s)
# @endfeature
# @feature vizMods
for entry in APP["vizMods"]:
    if not ok("viz mod " + entry[0], load_viz, entry):
        LOG.append("TODO viz mod " + entry[0] + ": " + VIZ_FIX)
# @endfeature

OLD_PAGES = ok("list pages", list_pages) or []
# @feature vizMods
# @note a mod you added to the starter page stays in the analysis while
# @note a visual uses it; the starter pages go only after the new mod
# @note visuals exist, so they get new titles first
for p in OLD_PAGES:
    ok("rename starter page", rename_starter_page, p)
# @endfeature
for ps in APP["pages"]:
    ok("page " + ps["title"], add_page, ps["title"])
# @feature !vizMods
if PAGES:
    ok("remove starter page", remove_pages, OLD_PAGES)
# @endfeature
for ps in APP["pages"]:
    if ps["title"] in PAGES:
        page = PAGES[ps["title"]]
        ok("page settings " + ps["title"], page_settings, page, ps)
        ok("page " + ps["title"] + " visuals", build_page, page, ps)
# @feature vizMods
if PAGES:
    ok("remove starter page", remove_pages, OLD_PAGES)
# @endfeature

ok("active page", set_active)
# @feature hiddenPages
for ps in APP["pages"]:
    if ps["title"] in PAGES and ps.get("visible", True) is False:
        ok("hide page " + ps["title"], hide_page, PAGES[ps["title"]])
# @endfeature
ok("remove starter data", remove_starter_tables)
# @feature filterLayout
for entry in APP.get("filterTypes", []):
    ok("filter type " + entry[0] + "." + entry[1], filter_type, entry[0],
       entry[1], entry[2])
for ps in APP["pages"]:
    if ps["title"] in PAGES and "filters" in ps:
        ok("filters " + ps["title"], filter_layout, PAGES[ps["title"]], ps)
# @endfeature
ok("description", describe)
ok("keywords", keywords)
if APP.get("navigation"):
    ok("page navigation", navigation)
# @feature manual
for entry in APP["manual"]:
    LOG.append("TODO " + entry[0] + ": " + entry[1])
# @endfeature
WANTED = sum([len(ps["visuals"]) for ps in APP["pages"]])
LOG.append("Built " + str(len(VIS)) + " of " + str(WANTED)
           + " visuals on " + str(len(PAGES)) + " page(s).")
finish()
