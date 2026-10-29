# ============================================================================
# 90_build.py - visual dispatch table and the build order (references/architecture.md).
# List-level functions (data_load_tables, df_build_all, ...) wrap each item in
# B.step themselves; this file wraps each visual and each page layout, guards
# every group (an unexpected error is recorded as a failed step and the build
# goes on) and always ends with B.finish() (report, then the queued save).
# Starter data: Analyst opens the script editor only once the analysis has a
# data table, so a new analysis with starter tables is accepted. A starter
# table whose name a spec table uses is renamed before the tables load; all
# starter tables are removed after doc_finish (which removes the starter pages).
# IronPython 3.4. Requires newer than 14.6: none. Internal API: none.
# ============================================================================
import traceback
from System.IO import Path

VISUAL_BUILDERS = {
    "lineChart": "vis_line",
    "barChart": "vis_bar",
    "combinationChart": "vis_combination",
    "scatterPlot": "vis_scatter",
    "scatterPlot3D": "vis_scatter3d",
    "pieChart": "vis_pie",
    "boxPlot": "vis_box",
    "heatMap": "vis_heatmap",
    "treemap": "vis_treemap",
    "waterfallChart": "vis_waterfall",
    "histogram": "vis_histogram",
    "table": "vis_table",
    "crossTable": "vis_crosstable",
    "summaryTable": "vis_summary",
    "graphicalTable": "vis_graphical",
    "kpiChart": "vis_kpi",
    "map": "vis_map",
    "textArea": "vis_textarea",
    "mod": "vis_mod",
}


def build_visual(page, vspec):
    """Dispatch to the visual builder, register the Visual under the spec id. Visuals a failing
    builder leaves on the page are recorded in B.visual_leftovers for page_apply_layout."""
    vid = vspec.get("id")
    vtype = vspec.get("type")
    fn = globals().get(VISUAL_BUILDERS.get(vtype, ""))
    if fn is None:
        raise Exception("no builder for visual type: " + str(vtype))
    before = set(str(v.Id) for v in page.Visuals)
    try:
        result = fn(page, vspec)
        if result is None:
            raise Exception("builder for " + str(vid) + " returned nothing")
        inner = getattr(result, "Visual", None)          # a content object carries its Visual
        visual = result if inner is None else inner
        B.register_visual(vid, visual, vtype)
    except Exception:
        B.visual_leftovers[vid] = [v for v in page.Visuals if str(v.Id) not in before]
        raise
    return visual


def _build_run(group, fn, args=()):
    """Run one list-level group. The functions record a step per item; anything they raise outside
    their own steps (a malformed spec entry, a bug) becomes one failed step and the build goes on."""
    B.begin(group)
    try:
        return fn(*args)
    except Exception as e:
        B.report["steps"].append({"group": group, "name": "group", "target": "(all)", "status": "failed",
                                  "seconds": 0.0, "message": exc_text(e), "traceback": traceback.format_exc()})
        return None


def _build_layout_text(node):
    """Compact layout description for the manual fallback: row[a 18, column 82[b 60, c 40]]."""
    if not isinstance(node, dict):
        return "?"
    if "visual" in node:
        text = str(node.get("visual"))
    else:
        kind = "row" if "row" in node else "column"
        text = kind + "[" + ", ".join(_build_layout_text(item) for item in (node.get(kind) or [])) + "]"
    if "weight" in node:
        text += " " + ("%g" % node["weight"] if isinstance(node["weight"], (int, float)) else str(node["weight"]))
    return text


def _build_pages(pages):
    pages_create(pages)
    done = set()
    for pspec in pages:
        title = pspec.get("title")
        B.begin("pages")
        if title in done:
            # pages_create built only the first page with this title; its visuals must not land there
            B.skip("page", str(title), "another spec page has the same title; this page, its visuals and "
                   "its layout are skipped")
            continue
        if title not in B.created["pages"]:
            B.skip("page", str(title), "page was not created; its visuals and layout are skipped")
            continue
        done.add(title)
        page = B.page(title)
        B.begin("visuals:" + str(title))
        for vspec in pspec.get("visuals") or []:
            B.step("visual", str(vspec.get("id")), build_visual, (page, vspec))
        B.begin("layout:" + str(title))
        layout = pspec.get("layout")
        B.step("layout", str(title), page_apply_layout, (page, pspec),
               fallback="Arrange the visuals on page '" + str(title) + "' by hand"
                        + ((": " + _build_layout_text(layout) + " (row = left to right, column = top to "
                            "bottom, numbers are relative sizes)") if layout else "") + ".")


def _build_theme(theme):
    base = theme.get("base") or "LightSfx"
    manual = "Set the document theme to " + str(base) + " in Analyst"
    if theme.get("customStyles"):
        manual += (" and apply the theme-editor JSON of app.theme.customStyles (saved as "
                   + Path.Combine(B.build_dir(), "theme.json") + " when it could be written)")
    # Not yet tested: the Analyst menu path for importing theme-editor JSON by hand.
    B.step("theme", base, doc_apply_theme, (theme,), fallback=manual + ".")


def _build_start_problem():
    """Why the open document is not a new analysis, or None. The builder removes the pages and data
    tables it finds and saves under the app's name, so it must never run inside someone's real
    analysis. Starter data is fine: Analyst opens the script editor only once a table is loaded."""
    # Not yet tested: LoadedFromFileName stays empty when the starter data came from a data file
    # (File > Open on a .sbdf/.csv) rather than from an analysis file.
    meta = B.application.DocumentMetadata
    for name in (meta.LoadedFromFileName, meta.FileNameUsedBySave):
        if name:
            return "it was opened from or saved to " + str(name)
    return None


def _build_spec_table_names():
    return set(str(t.get("name")).lower() for t in B.spec.get("tables") or [] if t.get("name"))


def _build_starter_tables():
    """Snapshot the starting document's data tables (removed at the end). One whose name a spec
    table uses is renamed '<name> (starter)' first, so the spec table loads as a new table instead
    of replacing the starter's data (data_load_tables reuses a table of the same name)."""
    spec_names = _build_spec_table_names()
    starters = [t for t in B.doc.Data.Tables]      # snapshot: renaming while iterating is unsafe
    B.starter_tables = starters
    B.created.setdefault("document", {})["starterTables"] = [t.Name for t in starters]
    for table in starters:
        if table.Name.lower() in spec_names:
            B.step("renameStarterTable", table.Name, _build_rename_starter, (table, spec_names))
    return starters


def _build_rename_starter(table, spec_names):
    base = table.Name
    name = base + " (starter)"
    n = 2
    while B.has_table(name) or name.lower() in spec_names:
        name = base + " (starter " + str(n) + ")"
        n += 1
    table.Name = name
    return table.Name


def _build_remove_starter_tables():
    """After doc_finish removed the starter pages (and their visuals): remove the starter tables,
    then make the spec's default table the document's default again."""
    spec_names = _build_spec_table_names()
    removed = 0
    for table in getattr(B, "starter_tables", None) or []:
        if not B.doc.Data.Tables.Contains(table):
            continue
        name = table.Name
        if name.lower() in spec_names:
            # its rename failed, so the spec table was loaded into it (ReplaceData): keep it
            B.warn("starter table '" + name + "' now holds the spec table of that name; kept")
            continue
        if B.step("removeStarterTable", name, _build_remove_table, (table,),
                  fallback="Delete the data table '" + name + "' (starter data of the new analysis)."):
            removed += 1
    B.created.setdefault("document", {})["removedStarterTables"] = removed
    wanted = _data_wanted_default_table(B.spec.get("tables") or [])
    if wanted and B.has_table(wanted):
        B.step("defaultTable", wanted, _data_set_default_table, (wanted,))
    return removed


def _build_remove_table(table):
    B.doc.Data.Tables.Remove(table)
    return True


def run_build(spec=None):
    """Never lets an exception escape: an error leaving the builder script would make Spotfire roll
    back the script's transaction, i.e. everything built so far, before the queued save runs.
    spec: accepted for the ARCHITECTURE signature run_build(spec); the build always reads B.spec,
    which the generated builder created from the same SPEC dict.
    Refuses (before changing anything) unless the open document is a new analysis."""
    problem = _build_start_problem()
    if problem:
        message = ("Nothing was changed. Run this builder in a new analysis (File > New, add any starter "
                   "data): the open document is not new because " + problem + ".")
        B.report["status"] = "refused"
        B.report["steps"].append({"group": "doc.prepare", "name": "blank-start", "target": "", "status": "failed",
                                  "seconds": 0.0, "message": message, "traceback": ""})
        try:
            B.write_report()
        except Exception:
            pass
        raise Exception("DXP builder: " + message)
    try:
        _build_all()
    except Exception as e:
        B.report["steps"].append({"group": B.group, "name": "build", "target": "(stopped)", "status": "failed",
                                  "seconds": 0.0, "message": exc_text(e), "traceback": traceback.format_exc()})
    B.finish()


def _build_all():
    spec = B.spec
    app = spec.get("app") or {}

    B.begin("doc.prepare")
    B.step("prepare", B.app.get("name", ""), doc_prepare)
    _build_run("doc.prepare", _build_starter_tables)
    _build_run("doc.prepare", _build_theme, (app.get("theme") or {"base": "LightSfx"},))

    _build_run("properties", data_add_properties, (spec.get("properties") or [],))
    _build_run("tables", data_load_tables, (spec.get("tables") or [],))
    # markings and filtering schemes come before data functions so that inputs limited by a
    # named marking or scheme can be bound at registration
    _build_run("markings", data_markings, (spec.get("markings") or [],))
    _build_run("filteringSchemes", data_filtering_schemes, (spec.get("filteringSchemes") or [],))
    _build_run("dataFunctions", df_build_all, (spec.get("dataFunctions") or [],))
    _build_run("tables.metadata", data_table_metadata, (spec.get("tables") or [],))
    _build_run("relations", data_relations, (spec.get("relations") or [],))
    _build_run("scripts", scripts_add_all, (spec.get("scripts") or [],))
    _build_run("pages", _build_pages, (spec.get("pages") or [],))
    _build_run("triggers", scripts_add_triggers, (spec.get("triggers") or [],))

    B.begin("doc.finish")
    B.step("finish", B.app.get("name", ""), doc_finish)
    _build_run("doc.finish", _build_remove_starter_tables)
