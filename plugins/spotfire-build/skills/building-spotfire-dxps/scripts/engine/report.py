# Standard engine, add-on "report" (report tier only): a step report on
# top of the standard engine. scripts/dxpgen.py puts it after the
# builders, so its ok(), save_now(), save(), write_log() and finish()
# replace the core ones before the build runs:
#   - every ok() step is recorded with group, seconds, error, traceback
#     and a manual fix derived from the function it ran;
#   - after the save: build-report-<tag>.json (every step),
#     MANUAL-STEPS-<tag>.md (each failed step with its fix, then every
#     TODO line: what the public API cannot build) and
#     snapshots-<tag>\*.png (one image per page and per visual; rendered
#     at once, queued for after the script only when nothing renders).
# APP keys it reads: tag (file name suffix), snapshots ([width, height]
# of the page image, or None to skip them). The feature parts' manual
# fixes sit in "# @feature" blocks of fix_for(). Apps with features (the
# guard part): after the inline save, the report files and the snapshots,
# finish() runs the build session switch (features/guard.py) and writes
# the report and the log again; the snapshots skip the "Build Session"
# page.
# @api Page.GetVisualBounds; Visual.Render; Visual.Id; Visual.Title
# @api Page.Visuals
import sys
from System import DateTime
from System.Drawing import Bitmap, Graphics, Rectangle, Color
from System.Drawing.Imaging import ImageFormat
from System.Globalization import CultureInfo

# ======================================================== report add-on
# Replaces ok(), save_now(), save(), write_log() and finish() above:
# every step is recorded, and after the save the build writes the step
# report, MANUAL-STEPS and the snapshots next to the log.
BUILD = Path.GetDirectoryName(LOG_FILE)
TAG = APP["tag"]
REPORT_FILE = Path.Combine(BUILD, "build-report-" + TAG + ".json")
MANUAL_FILE = Path.Combine(BUILD, "MANUAL-STEPS-" + TAG + ".md")
SNAP_DIR = Path.Combine(BUILD, "snapshots-" + TAG)
STEPS = []                # every step in order: the report
GROUP = ["start"]         # group the next steps are recorded under
SAVED = [False]           # True once the .dxp is written
SAVE_ERROR = [""]         # why the save inside the script was refused
SNAPS = []                # snapshot file names
INV = CultureInfo.InvariantCulture
STARTED = DateTime.Now
RETRIED = "retried after the script ended: "
GROUPS = {"rename_starter": "start", "load": "data",
          "set_format": "data", "marking": "data",
          "default_marking": "data",
          "list_pages": "pages", "add_page": "pages",
          "remove_pages": "pages", "page_settings": "pages",
          "set_active": "finish", "remove_starter_tables": "finish",
          "describe": "finish", "keywords": "finish",
          "navigation": "finish", "write_log": "save",
          "write_report": "save",
          "save_now": "save", "queue": "save"}
# @feature guard
GROUPS.update({"switch_session": "save", "session_page": "save",
               "repoint": "save"})
# @endfeature
# @feature filterLayout
GROUPS.update({"filter_type": "filters", "filter_layout": "filters"})
# @endfeature
KIND_NAMES = {"text": "Text Area", "kpi": "KPI chart", "table": "Table",
              "line": "Line chart", "bar": "Bar chart",
              "cross": "Cross table"}
# @feature vizMods
KIND_NAMES["mod"] = "Visualization mod"
GROUPS.update({"load_viz": "visualization mods",
               "rename_starter_page": "pages"})
# @endfeature


def now_text():
    return DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", INV)


STARTED_TEXT = now_text()


def exc_text(e):
    """Exception text plus .NET inner exceptions."""
    parts = [str(e)]
    ce = getattr(e, "clsException", None)
    depth = 0
    while ce is not None and depth < 5:
        inner = getattr(ce, "InnerException", None)
        if inner is None:
            break
        parts.append(inner.GetType().Name + ": " + str(inner.Message))
        ce = inner
        depth += 1
    return " | ".join(parts)


def tb_text():
    """Traceback of the exception being handled (no module imports)."""
    try:
        etype, value, tb = sys.exc_info()
        lines = ["Traceback (most recent call last):"]
        while tb is not None:
            code = tb.tb_frame.f_code
            lines.append('  File "%s", line %d, in %s'
                         % (code.co_filename, tb.tb_lineno,
                            code.co_name))
            tb = tb.tb_next
        name = getattr(etype, "__name__", str(etype))
        lines.append(name + ": " + str(value))
        return "\n".join(lines)
    except Exception:
        return ""


def ok(name, fn, *args):
    """The core's guarded call, recorded as one step. Never raises."""
    key = getattr(fn, "__name__", "")
    if key == "build_page":
        GROUP[0] = "page: " + args[1]["title"]
    elif key in GROUPS:
        GROUP[0] = GROUPS[key]
    entry = {"group": GROUP[0], "name": name, "function": key,
             "status": "ok", "seconds": 0.0, "error": "",
             "traceback": "", "fix": ""}
    STEPS.append(entry)
    t0 = DateTime.Now
    try:
        result = fn(*args)
    except Exception as e:
        result = None
        entry["status"] = "failed"
        entry["error"] = exc_text(e)
        entry["traceback"] = tb_text()
        entry["fix"] = fix_text(key, args)
        LOG.append("FAILED " + name + ": " + entry["error"])
    entry["seconds"] = round((DateTime.Now - t0).TotalSeconds, 3)
    return result


def mark_failed(name, error, fix):
    """Turn the last step called name into a failure (a refused save
    returns False instead of raising)."""
    for entry in reversed(STEPS):
        if entry["name"] == name:
            entry["status"] = "failed"
            entry["error"] = error
            entry["fix"] = fix
            return


# ---------------------------------------------------------- manual fixes
def fix_text(key, args):
    """What to do by hand when the step running function key failed."""
    try:
        return fix_for(key, list(args) + [None, None, None, None])
    except Exception:
        return "Repeat this step by hand in Analyst."


def fix_for(key, a):
    if key == "rename_starter":
        return ("Rename the starter data table '" + a[0].Name
                + "' (the build loads a table with that name).")
    if key == "load":
        return ("File > Add data: " + (a[1] or "data\\" + a[0] + ".sbdf")
                + " as a table named " + a[0] + ", embedded.")
    if key == "set_format":
        return ("Column properties of " + a[0] + "." + a[1]
                + " > Formatting: custom format " + fmt(a[2]) + ".")
    if key in ("marking", "default_marking"):
        return ("Edit > Document Properties > Markings: rename the "
                "default marking to '" + APP["marking"][0] + "' with "
                "color " + str(APP["marking"][1]) + ".")
    if key == "add_page":
        return "Add a page titled '" + a[0] + "'."
    if key == "remove_pages":
        return "Delete the starter page (right-click its tab > Delete)."
    if key == "page_settings":
        return ("Page '" + a[1]["title"] + "': set the title and the "
                "Filters panel (shown: " + str(bool(a[1].get(
                    "filterPanel", False))) + ").")
    # @feature hiddenPages
    if key == "hide_page":
        return ("Hide the page '" + a[0].Title + "' (right-click its "
                "tab > Hide page).")
    # @endfeature
    if key == "new_visual":
        return ("Add a " + KIND_NAMES.get(a[1], a[1]) + " to page '"
                + a[0].Title + "'.")
    if key == "set_title":
        return ("Visual title '" + a[1].get("title", "") + "', shown: "
                + str(bool(opt(a[1], "showTitle", True))) + ".")
    if key == "run_builder":
        return ("Finish '" + a[1].get("title", a[1]["id"]) + "' by hand"
                " (" + KIND_NAMES.get(a[1]["type"], a[1]["type"])
                + " on " + str(a[1].get("table")) + ").")
    if key == "add_kpi":
        return ("Properties > KPIs > Add: value " + a[2][1] + ", name '"
                + a[2][0] + "'.")
    if key in ("kpi_format", "y_format"):
        return "Properties > Formatting: custom format " + fmt(a[1]) + "."
    if key == "add_column":
        return "Properties > Columns: show '" + a[2] + "'."
    if key == "column_width":
        return ("Drag the right edge of the '" + a[2] + "' header to "
                "about " + str(a[3]) + " px.")
    if key == "legend":
        return ("Properties > Legend: " + ("show" if opt(a[1], "legend",
                True) else "hide") + " the legend.")
    if key in ("legend_font", "table_fonts", "axis_fonts", "kpi_font",
               "label_font"):
        return ("Properties > Fonts: " + STYLE["font"] + ", sizes as in "
                "STYLE['visual'] of this builder.")
    if key == "negatives":
        return ("Properties > Colors: rule 'less than 0' = "
                + hexcode(STYLE["negative"]) + ", default color "
                + hexcode(STYLE["text"]) + ", color the text.")
    if key == "colors":
        if a[1].get("color"):
            return ("Properties > Colors: color by (None), color "
                    + hexcode(a[1]["color"]) + ".")
        return ("Properties > Colors: color by " + a[1]["colorBy"]
                + "; " + ", ".join([k + " " + hexcode(c) for k, c in
                                    sorted(a[1].get("categories",
                                                    {}).items())]) + ".")
    if key == "y_range":
        return "Properties > Y-axis > Range: min " + str(a[1]) + "."
    if key == "ref_line":
        return ("Properties > Lines & Curves: add a "
                + ("vertical" if a[1]["axis"] == "X" else "horizontal")
                + " line at " + a[1]["value"] + " named '"
                + a[1]["label"] + "'.")
    if key == "line_width":
        return "Properties > Appearance: line width " + str(a[1]) + "."
    if key == "stack":
        return "Properties > Appearance: bar layout as in the spec."
    if key in ("cell_width", "row_header_width"):
        return ("Drag the cross-table column edge to about "
                + str(a[1]) + " px.")
    if key in ("kpi_tiles", "kpi_empty", "kpi_tile"):
        return "Properties > Appearance of the KPI chart, as in STYLE."
    # @feature coloring
    if key in ("axis_coloring", "configure", "add_rule", "cell_coloring",
               "kpi_coloring"):
        return ("Properties > Colors of the visual (or the map layer): "
                "set the coloring the spec gives (" + key + ").")
    # @endfeature
    # @feature fitting
    if key == "add_curve":
        return ("Properties > Lines & Curves: add the "
                + a[1]["kind"] + " " + str(a[1].get("expression", ""))
                + " named '" + str(a[1].get("label", "")) + "'.")
    # @endfeature
    # @feature range
    if key == "axis_ranges":
        return "Properties > X-axis / Y-axis > Range: as in the spec."
    # @endfeature
    # @feature trellis
    if key == "trellis":
        return ("Properties > Trellis: " + (
            "panels by " + a[1]["panel"] if a[1].get("panel") else
            "rows " + str(a[1].get("rowsBy")) + ", columns "
            + str(a[1].get("columnsBy"))) + ", as in the spec.")
    if key == "y_each":
        return ("Properties > Y-axis > Scale: tick 'Individual scaling' "
                + ("per trellis panel." if a[1] else "per color."))
    # @endfeature
    # @feature filterLayout
    if key == "filter_type":
        return ("Filters panel > right-click the " + a[1] + " filter of "
                + a[0] + " > Filter type > " + a[2] + ".")
    if key in ("filter_layout", "filter_table", "filter_others"):
        return ("Filters panel > Organize Filters on this page: show only "
                "the tables and columns of APP 'filters' (this builder), "
                "in that order.")
    # @endfeature
    # @feature markers
    if key in ("size_by", "marker_shapes", "marker_labels",
               "marker_size", "line_by"):
        return ("Properties > Size / Shape / Labels / Line connection "
                "of the scatter plot or map layer, as in the spec.")
    # @endfeature
    # @feature map
    if key.startswith("map_"):
        return ("Map properties > Layers: finish this step by hand, as "
                "in the spec (" + key + ").")
    # @endfeature
    # @feature settings
    if key == "set_setting":
        return ("Set " + a[1] + " = " + str(a[2]) + " on '" + a[0].Title
                + "' (its Properties dialog, or a script).")
    # @endfeature
    # @feature legendHide
    if key == "hide_legend_items":
        return ("Properties > Legend of '" + a[0].Title + "': untick "
                + ", ".join(a[1]["legendHide"]) + ".")
    # @endfeature
    # @feature textjs
    if key == "attach_js":
        return ("Edit the text area > Edit JavaScript > Add: script '"
                + a[1][0] + "'" + (" from " + a[1][1] if a[1][1] else "")
                + ".")
    # @endfeature
    # @feature vizMods
    if key == "rename_starter_page":
        return ("Rename the starter page '" + a[0].Title + "' (the "
                "build adds its pages with the spec's titles).")
    if key == "load_viz":
        return "Visualization mod " + a[0][0] + ": " + VIZ_FIX + "."
    if key in ("new_mod_visual", "mod_add"):
        return ("Visualization mod on page '" + a[0].Title + "': "
                + VIZ_FIX + ".")
    if key == "mod_data":
        return ("Visualization properties > Data of " + a[0] + ": data "
                "table " + str(a[2].get("table")) + ", limit data using "
                "expressions " + str(a[2].get("where", "(none)"))
                + ", filtering " + ("off" if a[2].get("filtering") is False
                                    else "on") + ".")
    if key in ("mod_clear", "mod_add_layer"):
        return ("Visualization properties of the mod > Layers: remove "
                "the layers it starts with, then add the layers of APP "
                "(type and title) in that order.")
    if key == "mod_layer_marking":
        return ("Layer '" + a[1]["title"] + "' > Data: marking "
                + (a[1].get("marking", APP["marking"][0]) or "(None)")
                + ", limit by markings "
                + (", ".join(a[1].get("limits", [])) or "(none)") + ".")
    if key == "mod_axis_set":
        return ("Set the axis " + a[1] + " of the mod visual to "
                + (a[2] or "(empty)") + " (the axis selector or "
                "Visualization properties > Data).")
    if key == "mod_prop":
        return ("Set the mod property " + a[1][0] + " to "
                + str(a[1][2]) + " (the mod's own settings).")
    # @endfeature
    if key == "apply_layout":
        return ("Arrange the visuals on page '" + a[0].Title + "' as "
                "the APP layout tree of this builder describes.")
    if key == "set_active":
        return "Click the page tab '" + APP["activePage"] + "'."
    if key == "remove_starter_tables":
        return ("Delete the starter data table(s) and make "
                + str(APP["defaultTable"]) + " the default table.")
    if key in ("describe", "keywords"):
        return ("Edit > Document Properties > General: description and "
                "keywords as in APP.")
    if key == "navigation":
        return "Show the pages as " + APP["navigation"] + "."
    # @feature guard
    if key in ("switch_session", "session_page", "repoint"):
        return ("Nothing to fix in the saved DXP " + OUT + ". This "
                "analysis may still be linked to it: close it without "
                "saving (answer No) and open the saved DXP.")
    # @endfeature
    if key in ("save_now", "queue", "save"):
        # @feature guard
        return ("File > Save As > " + OUT + " (keep the data embedded), "
                "then check: " + recheck())
        # @endfeature
        return ("File > Save As > " + OUT + " (keep the data embedded), "
                "then check the marking name and the description.")
    if key in ("write_log", "write_report"):
        return "Nothing to fix in the analysis: is " + BUILD + " writable?"
    return "Repeat this step by hand in Analyst."


# ---------------------------------------------------------------- report
def counts():
    c = {"ok": 0, "failed": 0, "skipped": 0}
    for s in STEPS:
        c[s["status"]] = c.get(s["status"], 0) + 1
    return c


def open_steps():
    """Failed steps still to do by hand; a refused save is dropped once
    a later save worked."""
    return [s for s in STEPS if s["status"] == "failed"
            and not (s["name"] == "save" and SAVED[0])]


def build_status():
    todo = open_steps()
    if not todo:
        return "ok"
    if all([s["group"].startswith("snapshots") for s in todo]):
        return "ok, snapshots incomplete"
    return "errors"


def visuals_info():
    info = {}
    for ps in APP["pages"]:
        for vs in ps["visuals"]:
            v = VIS.get(vs["id"])
            info[vs["id"]] = {"page": ps["title"], "type": vs["type"],
                              "title": vs.get("title", ""),
                              "guid": str(v.Id) if v is not None else None}
    return info


def report_data():
    steps = []
    for s in STEPS:
        item = dict(s)
        if item["status"] == "ok":
            del item["fix"]
            del item["traceback"]
        steps.append(item)
    try:
        version = str(Document.GetType().Assembly.GetName().Version)
    except Exception:
        version = "unknown"
    return {"app": APP["name"], "tier": TAG, "spotfire": version,
            "started": STARTED_TEXT, "written": now_text(),
            "elapsedSeconds": round((DateTime.Now - STARTED)
                                    .TotalSeconds, 1),
            "status": build_status(), "counts": counts(),
            "saved": SAVED[0], "output": OUT,
            "files": {"log": LOG_FILE, "manualSteps": MANUAL_FILE,
                      "snapshots": SNAP_DIR},
            "pages": [ps["title"] for ps in APP["pages"]
                      if ps["title"] in PAGES],
            "visuals": visuals_info(), "snapshots": list(SNAPS),
            "log": list(LOG), "steps": steps}


def manual_text():
    todo = open_steps()
    later = [s for s in todo if s["group"].startswith("snapshots")]
    todo = [s for s in todo if not s["group"].startswith("snapshots")]
    retried = [s for s in STEPS if s["status"] == "skipped"]
    c = counts()
    lines = ["# Manual steps - " + APP["name"] + " (" + TAG + " tier)", "",
             "Build started " + STARTED_TEXT + "; this file written "
             + now_text() + ".", "",
             str(len(STEPS)) + " steps: " + str(c["ok"]) + " ok, "
             + str(c["failed"]) + " failed, " + str(c["skipped"])
             + " skipped.", ""]
    if SAVED[0]:
        lines.append("Saved: " + OUT)
    else:
        lines.append("Not saved by the script (yet). If this file does "
                     "not exist, use File > Save As: " + OUT)
    lines.append("")
    if not todo:
        lines.append("Nothing to fix: every step was built "
                     "automatically.")
    else:
        lines.append("## Fix in Analyst (" + str(len(todo)) + ")")
        lines.append("")
        n = 0
        for s in todo:
            n += 1
            lines.append(str(n) + ". **" + s["name"] + "** ("
                         + s["group"] + ")")
            lines.append("   - Fix: " + (s["fix"] or "Repeat this item "
                                         "by hand in Analyst."))
            lines.append("   - Error: " + s["error"][:400])
    by_hand = [x[5:] for x in LOG if x.startswith("TODO ")]
    if by_hand:
        lines.append("")
        lines.append("## Add by hand (" + str(len(by_hand)) + ")")
        lines.append("")
        lines.append("The public API cannot build these items:")
        lines.append("")
        n = 0
        for item in by_hand:
            n += 1
            lines.append(str(n) + ". " + item)
    if later:
        lines.append("")
        lines.append("## Optional: snapshots (" + str(len(later)) + ")")
        lines.append("")
        for s in later:
            lines.append("- " + s["name"] + ": " + s["error"][:300])
        lines.append("- Fix: none needed; export a picture from Analyst "
                     "(File > Export) if you want one.")
    if retried:
        lines.append("")
        lines.append(str(len(retried)) + " snapshot step(s) could not "
                     "render inside the script and were retried after "
                     "it (details in " + Path.GetFileName(REPORT_FILE)
                     + ").")
    lines.append("")
    lines.append("Every step with seconds, error and traceback: "
                 + Path.GetFileName(REPORT_FILE) + ". Problems in order: "
                 + Path.GetFileName(LOG_FILE) + ".")
    return "\n".join(lines) + "\n"


def write_report():
    Directory.CreateDirectory(BUILD)
    text = json.dumps(report_data(), indent=2, sort_keys=True,
                      default=str)
    File.WriteAllText(REPORT_FILE, text + "\n")
    File.WriteAllText(MANUAL_FILE, manual_text())


def write_log():
    """A head line, then every problem line in order."""
    Directory.CreateDirectory(BUILD)
    todo = len(open_steps())
    earlier = len([x for x in LOG if x.startswith("FAILED")])
    if todo and build_status() != "errors":
        head = ("No problems in the analysis; " + str(todo) + " "
                "snapshot step(s) failed (optional, see below).")
    elif todo:
        head = (str(todo) + " problem(s) to fix; the build went on. "
                "Fixes: " + Path.GetFileName(MANUAL_FILE))
    elif earlier:
        head = ("No problems left (" + str(earlier) + " failure(s) "
                "below were retried successfully).")
    else:
        head = "No problems."
    # @feature preflight
    head = log_stamp(head)
    # @endfeature
    File.WriteAllText(LOG_FILE, "\r\n".join([head] + LOG))


# ------------------------------------------------------------- snapshots
def file_name(text):
    out = []
    for ch in (text or ""):
        out.append(ch if (ch.isalnum() or ch in " -_") else "_")
    name = "".join(out).strip()
    return name[:60] if name else "untitled"


def render_page(page, number):
    """Every visual of the page drawn at its place in one image (saved
    only when at least one visual could be drawn)."""
    width, height = APP["snapshots"]
    area = Rectangle(0, 0, width, height)
    bmp = Bitmap(width, height)
    g = Graphics.FromImage(bmp)
    name = "p%02d-page-%s.png" % (number, file_name(page.Title))
    missed = []
    drawn = 0
    try:
        g.Clear(Color.White)
        for visual in [x for x in page.Visuals]:
            try:
                bounds = page.GetVisualBounds(visual, area)
                visual.Render(g, bounds)  # noqa: obsolete
                drawn += 1
            except Exception as e:
                missed.append(visual.Title + " (" + exc_text(e) + ")")
        if drawn:
            bmp.Save(Path.Combine(SNAP_DIR, name), ImageFormat.Png)
            SNAPS.append(name)
    finally:
        g.Dispose()
        bmp.Dispose()
    if not drawn:
        raise Exception("no visual could be drawn: " + "; ".join(missed))
    if missed:
        raise Exception(name + " saved without: " + "; ".join(missed))
    return name


def render_visual(page, number, index, visual):
    width, height = APP["snapshots"]
    r = page.GetVisualBounds(visual, Rectangle(0, 0, width, height))
    if r.Width <= 0 or r.Height <= 0:
        raise Exception("the visual has no area on the page")
    bmp = Bitmap(r.Width, r.Height)
    g = Graphics.FromImage(bmp)
    try:
        g.Clear(Color.White)
        visual.Render(g, Rectangle(0, 0, r.Width, r.Height))  # noqa
        name = "p%02d-v%02d-%s.png" % (number, index,
                                       file_name(visual.Title))
        bmp.Save(Path.Combine(SNAP_DIR, name), ImageFormat.Png)
        SNAPS.append(name)
    finally:
        g.Dispose()
        bmp.Dispose()
    return name


def render_all():
    """PNG of every page and visual (Visual.Render into a Bitmap, as
    lib/00_core.py does). Returns the number of visuals rendered."""
    Directory.CreateDirectory(SNAP_DIR)
    for old in Directory.GetFiles(SNAP_DIR, "*.png"):
        File.Delete(old)
    del SNAPS[:]
    number = 0
    rendered = 0
    for page in [p for p in Document.Pages]:
        # @feature guard
        if page.Title == SESSION_PAGE:
            continue
        # @endfeature
        number += 1
        ok("page image " + page.Title, render_page, page, number)
        index = 0
        for visual in [x for x in page.Visuals]:
            index += 1
            if ok("visual image " + page.Title + " / " + visual.Title,
                  render_visual, page, number, index, visual):
                rendered += 1
    return rendered


def snapshots(group):
    GROUP[0] = group
    return render_all()


# ------------------------------------------------------------------ save
def guarded(fn):
    """A queued call that never raises: a failure is recorded and the
    log and report are written again."""
    def run():
        try:
            fn()
        except Exception as e:
            try:
                STEPS.append({"group": "after script", "name": "queued "
                              + fn.__name__, "function": fn.__name__,
                              "status": "failed", "seconds": 0.0,
                              "error": exc_text(e), "traceback": tb_text(),
                              "fix": fix_text("save", [])})
                write_log()
                write_report()
            except Exception:
                pass
    return run


def queued_snapshots():
    for s in STEPS:
        if s["group"] == "snapshots" and s["status"] == "failed":
            s["status"] = "skipped"
            s["error"] = RETRIED + s["error"]
    snapshots("snapshots (after script)")
    write_report()
    write_log()


def after_save():
    """Report files, then the snapshots: rendered at once, and queued
    for after the script only when no visual renders inside it (a queued
    call never ran in live tests on Analyst 15.0)."""
    ok("write report", write_report)
    if not APP.get("snapshots"):
        LOG.append("NOTE snapshots are off (app.snapshots.enabled).")
    elif not ok("snapshots", snapshots, "snapshots"):
        GROUP[0] = "save"
        ok("queue snapshots", queue, guarded(queued_snapshots))
    GROUP[0] = "save"
    ok("write report", write_report)
    ok("write log", write_log)


def save():
    """Fallback after the script ends, retried while Spotfire reports
    'not idle'."""
    GROUP[0] = "save (after script)"
    try:
        Application.SaveAs(OUT, DocumentSaveSettings())
    except Exception as e:
        TRIES[0] += 1
        if "not idle" in str(e) and TRIES[0] < 20:
            queue(guarded(save))
            return
        LOG.append("FAILED save: " + str(e)
                   + " - use File > Save As instead.")
        mark_failed("save", exc_text(e), fix_text("save", []))
        write_log()
        write_report()
        return
    LOG.append("Saved " + OUT)
    SAVED[0] = True
    write_log()
    write_report()
    if APP.get("snapshots") and not SNAPS:
        snapshots("snapshots (after script)")
        write_report()
        write_log()


def save_now():
    try:
        Application.SaveAs(OUT, DocumentSaveSettings())
        LOG.append("Saved " + OUT)
        return True
    except Exception as e:
        SAVE_ERROR[0] = exc_text(e)
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
    """Inline save first, queued save as the fallback, then the report
    files and the snapshots."""
    ok("write log", write_log)
    ok("write report", write_report)
    if ok("save", save_now):
        SAVED[0] = True
        ok("write log", write_log)
    else:
        mark_failed("save", "Spotfire refused the save inside the script ("
                    + SAVE_ERROR[0] + "); it is retried after the script "
                    "ends.", fix_text("save", []))
        ok("write log", write_log)
        ok("queue save", queue, guarded(save))
    after_save()
    # @feature guard
    if SAVED[0]:
        ok("build session", switch_session)
        ok("write report", write_report)
        ok("write log", write_log)
    # @endfeature
