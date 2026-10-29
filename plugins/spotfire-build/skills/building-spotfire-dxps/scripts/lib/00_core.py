# ============================================================================
# 00_core.py - build context, step/report bookkeeping, value conversion,
# the settings escape hatch and the finish (save inline first, queued save as
# the fallback, queued snapshots).
# IronPython 3.4 inside Spotfire Analyst 15.0 (Python 3.4 syntax: no f-strings,
# no walrus, no annotations, no print). Every other lib module depends on this.
# Requires newer than 14.6: none (newest public member: ScriptManager.
# GetAllScriptsWithName, api 12.0). Visual.Render is [Obsolete] in 15.0 (Linux
# only); Windows Analyst still renders with it, so the snapshots keep it.
# Public API only: text-area controls, property triggers and the document theme
# have no public API, so 10/40/80 record them as manual steps (B.fallback).
# ============================================================================
import clr
clr.AddReference("System.Drawing")
import sys
import traceback
import json

from System import (Array, Activator, Type, String, Object, Boolean, Int32, Int64, Double, Single,
                    Decimal, DateTime, TimeSpan, Enum, Guid)
from System.Globalization import CultureInfo, NumberStyles
from System.IO import File, Directory, Path
from System.Reflection import BindingFlags
from System.Drawing import Color, ColorTranslator, Bitmap, Graphics, Rectangle
from System.Drawing.Imaging import ImageFormat
from System.Collections.Generic import List, Dictionary
from Spotfire.Dxp.Application import DocumentSaveSettings
from Spotfire.Dxp.Data import DataType, DataPropertyClass
from Spotfire.Dxp.Data.Expressions import ExpressionUtilities
from Spotfire.Dxp.Framework.ApplicationModel import ApplicationThread, ApplicationInvocation

INVARIANT = CultureInfo.InvariantCulture

# Every key a module records under B.created, so the report always has the full set
# (verify_dxp reads them). "relations" is a list; every other entry is a dict.
_CORE_CREATED_KEYS = ("pages", "visuals", "controls", "tables", "properties", "scripts", "dataFunctions",
                      "markings", "filteringSchemes", "triggers", "document", "theme", "layouts", "mods",
                      "charts", "visualSettings", "coloring", "referenceLayers", "fittingModels",
                      "tableVisuals", "maps", "textAreas")
_CORE_SAVE_TRIES = 5      # re-queue SaveAs this often while Spotfire still reports "not idle"


def _core_now():
    # invariant culture: ':' in a custom format is the culture's time separator otherwise
    return DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff", INVARIANT)


def exc_text(e):
    """Message of an exception, including .NET inner exceptions (reflection wraps them)."""
    parts = [str(e)]
    ce = getattr(e, "clsException", None)
    depth = 0
    while ce is not None and depth < 6:
        inner = getattr(ce, "InnerException", None)
        if inner is None:
            break
        parts.append(inner.GetType().Name + ": " + str(inner.Message))
        ce = inner
        depth += 1
    return " | ".join(parts)


class BuildContext(object):
    """Shared state of one build. The generated builder creates the single instance `B`."""

    def __init__(self, spec, app_dir, document, application, spec_sha, builder_sha):
        self.spec = spec
        self.app = spec.get("app", {})
        self.app_dir = app_dir
        self.doc = document
        self.application = application
        self.group = "init"
        self._pages = {}
        self._visuals = {}
        self._save_tries = 0
        # visual id -> Visuals a failed visual builder left on its page (90_build, 50_pages)
        self.visual_leftovers = {}
        # the starting document's pages, snapshotted by doc_prepare and removed by doc_finish
        self.document_old_pages = None
        self.created = {}
        for key in _CORE_CREATED_KEYS:
            self.created[key] = {}
        self.created["relations"] = []
        self.report = {
            "app": self.app.get("name", ""),
            "spec": spec_sha,
            "builder": builder_sha,
            "spotfire": str(document.GetType().Assembly.GetName().Version),
            "started": _core_now(),
            "finished": None,
            "status": "running",
            "steps": [],
            "fallbacks": [],
            "warnings": [],
            "created": self.created,
            "output": self.output_path(),
            "saved": False,
            "snapshots": [],
        }

    # ---- paths ------------------------------------------------------------
    def path(self, relative):
        """Absolute path for a path relative to the app folder (absolute paths pass through)."""
        if relative is None:
            return None
        if Path.IsPathRooted(relative):
            return relative
        return Path.GetFullPath(Path.Combine(self.app_dir, relative.replace("/", "\\")))

    def output_path(self):
        out = self.app.get("output") or ("build/" + self.app.get("name", "analysis") + ".dxp")
        return self.path(out)

    def build_dir(self):
        return Path.GetDirectoryName(self.output_path())

    # ---- steps and report --------------------------------------------------
    def begin(self, group):
        self.group = group

    def step(self, name, target, fn, args=(), fallback=None, critical=False):
        """Run fn(*args) and record the outcome. Returns fn's result, or None on failure.

        fallback: text of the manual action the user must take if this step fails. When given,
        a failure is recorded as a fallback (build continues) instead of an error.
        critical: re-raise after recording. That stops the rest of the build; run_build (90_build)
        catches it, so the report is still written and the analysis still saved.
        """
        entry = {"group": self.group, "name": name, "target": target, "status": "ok",
                 "seconds": 0.0, "message": "", "traceback": ""}
        self.report["steps"].append(entry)
        t0 = DateTime.Now
        try:
            result = fn(*args)
            entry["seconds"] = round((DateTime.Now - t0).TotalSeconds, 3)
            return result
        except Exception as e:
            entry["seconds"] = round((DateTime.Now - t0).TotalSeconds, 3)
            entry["message"] = exc_text(e)
            entry["traceback"] = traceback.format_exc()
            if fallback is not None:
                entry["status"] = "fallback"
                self.fallback(self.group + "." + name, target, entry["message"], fallback)
            else:
                entry["status"] = "failed"
            if critical:
                raise
            return None

    def skip(self, name, target, reason):
        self.report["steps"].append({"group": self.group, "name": name, "target": target,
                                     "status": "skipped", "seconds": 0.0, "message": reason,
                                     "traceback": ""})

    def fallback(self, feature, target, reason, manual):
        self.report["fallbacks"].append({"feature": feature, "target": target, "reason": reason,
                                         "manual": manual})

    def warn(self, message):
        self.report["warnings"].append(message)

    # ---- lookups -------------------------------------------------------------
    def table(self, name):
        found, t = self.doc.Data.Tables.TryGetValue(name)
        if not found:
            raise Exception("data table not found: " + str(name))
        return t

    def has_table(self, name):
        if not name:
            return False      # TryGetValue(None) throws ArgumentNullException
        found, t = self.doc.Data.Tables.TryGetValue(name)
        return found

    def table_or_default(self, name):
        if name:
            return self.table(name)
        default = self.spec.get("defaultTable")
        if default:
            return self.table(default)
        t = self.doc.Data.Tables.DefaultTableReference
        if t is None:
            raise Exception("no table given and the document has no default table")
        return t

    def prop(self, name):
        found, p = self.doc.Data.Properties.TryGetProperty(DataPropertyClass.Document, name)
        if not found:
            raise Exception("document property not found: " + str(name))
        return p

    def script(self, name):
        """Registered IronPython ScriptDefinition by exact name (a JavaScript one may share it)."""
        for sd in self.doc.ScriptManager.GetAllScriptsWithName(name):
            if str(sd.Language.Language).startswith("IronPython"):
                return sd
        raise Exception("IronPython script not found: " + str(name))

    def marking(self, name):
        found, m = self.doc.Data.Markings.TryGetValue(name)
        if not found:
            raise Exception("marking not found: " + str(name))
        return m

    def filtering_scheme(self, name):
        """FilteringScheme (Document.FilteringSchemes) for a spec filtering-scheme name; None or "" =
        the document's default scheme. Raises when the scheme is missing or its FilteringScheme is not
        created yet (it is made by an internal handler after Data.Filterings.Add)."""
        if not name:
            return self.doc.FilteringSchemes.DefaultFilteringSchemeReference
        found, sel = self.doc.Data.Filterings.TryGetValue(name)
        if not found:
            raise Exception("filtering scheme not found: " + str(name))
        scheme = _core_scheme_for(sel)
        if scheme is None:
            raise Exception("filtering scheme '" + str(name) + "' exists but its FilteringScheme is not "
                            "created yet")
        return scheme

    def register_page(self, title, page):
        self._pages[title] = page
        self.created["pages"][title] = str(page.Id)

    def page(self, title):
        """A page this build created, by spec title. During the build the pages carry temporary
        titles and the starting document's pages are removed at the end, so only registered pages
        are returned (a title match on the starting pages would point at a page about to go)."""
        if title in self._pages:
            return self._pages[title]
        raise Exception("page not created by this build: " + str(title))

    def register_visual(self, vid, visual, vtype):
        self._visuals[vid] = visual
        self.created["visuals"][vid] = {"type": vtype, "title": visual.Title, "guid": str(visual.Id)}

    def visual(self, vid):
        if vid not in self._visuals:
            raise Exception("visual id not built: " + str(vid))
        return self._visuals[vid]

    # ---- finish: report, save (inline first, else queued), queued snapshots ----
    def finish(self):
        self.report["finished"] = _core_now()
        failed = [s for s in self.report["steps"] if s["status"] == "failed"]
        if failed:
            self.report["status"] = "errors"
        elif self.report["fallbacks"]:
            self.report["status"] = "ok-with-fallbacks"
        else:
            self.report["status"] = "ok"
        try:
            self.write_report()   # written now too, in case the save never happens
        except Exception as e:
            # never let a report problem stop the save that follows
            self.warn("could not write the report before saving: " + exc_text(e))
        if self._save_inline():
            return
        try:
            self._queue("save", self.save)
        except Exception as e:
            # no application thread to queue on: nothing else can save the analysis
            self.warn("could not queue the save (" + exc_text(e) + "); use File > Save As")
        _core_guard("report", self.write_report)()     # the warning above reaches the file now

    def _save_inline(self):
        """SaveAs inside the script. A queued call may never run (in live tests on Analyst 15.0 the
        queued save never executed), so this comes first. Inside a transaction SaveAs throws 'document is
        not idle': then finish() queues the save. True when the analysis was saved."""
        try:
            self._save_as()
        except Exception as e:
            self.warn("save inside the script was refused (" + exc_text(e) + "); retrying after the "
                      "script ends; if build-report.json never shows saved=true, use File > Save As")
            return False
        _core_guard("save", self._saved)()
        return True

    def _queue(self, name, fn):
        """Run fn after the builder script returns, outside its transaction (SaveAs throws
        'document is not idle' inside one)."""
        thread = self.application.GetService[ApplicationThread]()
        thread.InvokeAsynchronously(ApplicationInvocation(_core_guard(name, fn)))

    def save(self):
        """The queued save (fallback of _save_inline), retried while Spotfire is not idle."""
        # Not yet tested: the queued call runs once the script's transaction has ended, also while
        # the script dialog is still open (the user closes it with Cancel afterwards).
        try:
            self._save_as()
        except Exception as e:
            self._save_tries += 1
            if "not idle" in exc_text(e) and self._save_tries < _CORE_SAVE_TRIES:
                self._queue("save", self.save)     # still busy: try again after the queued work
                return
            raise
        self._saved()

    def _save_as(self):
        out = self.output_path()
        Directory.CreateDirectory(Path.GetDirectoryName(out))
        self.application.SaveAs(out, DocumentSaveSettings())

    def _saved(self):
        self.report["saved"] = True
        self.write_report()
        snaps = self.app.get("snapshots", {"enabled": True})
        if snaps is None or snaps.get("enabled", True):
            try:
                self._queue("snapshots", self.snapshots)
            except Exception as e:
                self.warn("could not queue the snapshots: " + exc_text(e))
                self.write_report()

    def snapshots(self):
        snaps = self.app.get("snapshots") or {}
        width = int(snaps.get("width", 1600))
        height = int(snaps.get("height", 900))
        folder = Path.Combine(self.build_dir(), "snapshots")
        Directory.CreateDirectory(folder)
        for old in Directory.GetFiles(folder, "*.png"):
            File.Delete(old)
        area = Rectangle(0, 0, width, height)
        names = []
        page_no = 0
        for page in self.doc.Pages:
            page_no += 1
            page_bmp = Bitmap(width, height)
            page_g = Graphics.FromImage(page_bmp)
            page_g.Clear(Color.White)
            vis_no = 0
            for visual in page.Visuals:
                vis_no += 1
                try:
                    bounds = page.GetVisualBounds(visual, area)
                    visual.Render(page_g, bounds)  # noqa: obsolete (Windows Analyst still supports it)
                    if bounds.Width > 0 and bounds.Height > 0:
                        bmp = Bitmap(bounds.Width, bounds.Height)
                        g = Graphics.FromImage(bmp)
                        g.Clear(Color.White)
                        visual.Render(g, Rectangle(0, 0, bounds.Width, bounds.Height))  # noqa: obsolete
                        g.Dispose()
                        name = "p%02d-v%02d-%s.png" % (page_no, vis_no, _core_file_name(visual.Title))
                        bmp.Save(Path.Combine(folder, name), ImageFormat.Png)
                        bmp.Dispose()
                        names.append(name)
                except Exception as e:
                    self.warn("snapshot of '" + visual.Title + "' failed: " + exc_text(e))
            page_g.Dispose()
            name = "p%02d-page-%s.png" % (page_no, _core_file_name(page.Title))
            page_bmp.Save(Path.Combine(folder, name), ImageFormat.Png)
            page_bmp.Dispose()
            names.append(name)
        self.report["snapshots"] = names
        self.write_report()

    def write_report(self):
        folder = self.build_dir()
        Directory.CreateDirectory(folder)
        File.WriteAllText(Path.Combine(folder, "build-report.json"), _core_json(self.report))
        lines = ["# Manual steps for " + str(self.report["app"]), ""]
        if not self.report["fallbacks"]:
            lines.append("None - everything was built automatically.")
        n = 0
        for f in self.report["fallbacks"]:
            n += 1
            lines.append(str(n) + ". **" + str(f.get("target")) + "** (" + str(f.get("feature")) + "): "
                         + str(f.get("manual")))
            lines.append("   - why: " + str(f.get("reason")))
        File.WriteAllText(Path.Combine(folder, "MANUAL-STEPS.md"), "\n".join(lines) + "\n")


def _core_json_default(value):
    """json.dumps fallback for values JSON has no type for (.NET objects, DateTime, Decimal, ...)."""
    return str(value)


def _core_json(report):
    """build-report.json text. A module that stored a non-JSON value or a non-string key must not cost
    the report: unknown values become their text; unsortable keys drop the key sorting."""
    try:
        return json.dumps(report, indent=2, sort_keys=True, default=_core_json_default)
    except TypeError:
        return json.dumps(report, indent=2, skipkeys=True, default=_core_json_default)


def _core_scheme_for(selection):
    """FilteringScheme of a DataFilteringSelection, or None while it does not exist yet."""
    try:
        scheme = B.doc.FilteringSchemes[selection]
    except Exception:
        scheme = None
    if scheme is None:
        for candidate in B.doc.FilteringSchemes:
            ref = candidate.FilteringSelectionReference
            if ref is not None and ref.Equals(selection):
                return candidate
    return scheme


def _core_guard(name, fn):
    def run():
        try:
            fn()
        except Exception as e:
            B.report["steps"].append({"group": "finish", "name": name, "target": "",
                                      "status": "failed", "seconds": 0.0, "message": exc_text(e),
                                      "traceback": traceback.format_exc()})
            B.report["status"] = "errors"
            try:
                B.write_report()
            except Exception:
                pass
    return run


def _core_file_name(text):
    out = []
    for ch in (text or ""):
        out.append(ch if (ch.isalnum() or ch in " -_") else "_")
    name = "".join(out).strip()
    return name[:60] if name else "untitled"


# ---- value conversion ---------------------------------------------------------
def color(value):
    """'#RRGGBB' or '#AARRGGBB' (or a .NET color name) -> System.Drawing.Color."""
    if isinstance(value, Color):
        return value
    s = str(value).strip()
    if s.startswith("#") and len(s) == 9:
        return Color.FromArgb(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), int(s[7:9], 16))
    return ColorTranslator.FromHtml(s)


_CORE_MISSING = object()


def enum_value(enum_type, name):
    """Member of a .NET enum or pseudo-enum class by name. Handles members named None."""
    value = getattr(enum_type, name, _CORE_MISSING)
    if value is _CORE_MISSING:
        raise Exception("no member '" + str(name) + "' on " + str(enum_type))
    return value


def esc(column_name):
    """Column name as an expression identifier: Flow Rate -> [Flow Rate]."""
    return ExpressionUtilities.EscapeIdentifier(column_name)


def data_type(name):
    return enum_value(DataType, name)


def net_value(type_name, value):
    """Convert a JSON value to the exact .NET type a Spotfire DataType expects."""
    if value is None:
        return None
    if type_name == "String":
        return String(str(value))
    if type_name == "Integer":
        return Int32(int(value))
    if type_name == "LongInteger":
        return Int64(int(value))
    if type_name == "Real":
        return Double(float(value))
    if type_name == "SingleReal":
        return Single(float(value))
    if type_name == "Currency":
        # NumberStyles.Float: str() of a float may use an exponent (1e-05)
        return Decimal.Parse(str(value), NumberStyles.Float, INVARIANT)
    if type_name == "Boolean":
        if isinstance(value, bool):
            return Boolean(value)
        return Boolean(str(value).lower() in ("true", "1", "yes"))
    if type_name in ("Date", "DateTime", "Time"):
        # A Time string ("06:00:00") gets today's date here; document properties pass Time defaults
        # as text instead, so Spotfire's own Time parser picks the date part (20_data).
        return DateTime.Parse(str(value), INVARIANT)
    if type_name == "TimeSpan":
        return TimeSpan.Parse(str(value), INVARIANT)
    raise Exception("unsupported data type: " + str(type_name))


def net_list(type_name, values):
    """List<Object> of converted values, for DataProperty.Value assignments (the setter converts an
    IList<Object> element by element). Creating a list-valued property needs a typed List<T>
    instead: CreateCustomPrototype stores list defaults unconverted (20_data._data_typed_list)."""
    items = List[Object]()
    for v in values:
        items.Add(net_value(type_name, v))
    return items


# ---- settings escape hatch ------------------------------------------------------
def _core_convert_for(prop_type, value):
    """Convert a JSON value to a public property's .NET type."""
    if value is None:
        return None
    if prop_type.IsEnum:
        return Enum.Parse(prop_type, str(value))
    if prop_type == clr.GetClrType(Color):
        return color(value)
    if prop_type == clr.GetClrType(Boolean):
        return Boolean(bool(value))
    if prop_type == clr.GetClrType(Int32):
        return Int32(int(value))
    if prop_type == clr.GetClrType(Int64):
        return Int64(int(value))
    if prop_type == clr.GetClrType(Double):
        return Double(float(value))
    if prop_type == clr.GetClrType(Single):
        return Single(float(value))
    if prop_type == clr.GetClrType(String):
        return String(str(value))
    if isinstance(value, str):
        # pseudo-enum classes (DataType, ScriptLanguage, ...) expose static members by name
        member = prop_type.GetProperty(value, BindingFlags.Static | BindingFlags.Public)
        if member is not None:
            return member.GetValue(None, None)
        field = prop_type.GetField(value, BindingFlags.Static | BindingFlags.Public)
        if field is not None:
            return field.GetValue(None)
    return value


def apply_settings(obj, settings):
    """settings: {"XAxis.Scale.ShowGridlines": False, ...} relative to obj (public API only)."""
    if not settings:
        return
    for path in sorted(settings.keys()):
        value = settings[path]
        parts = path.split(".")
        target = obj
        for part in parts[:-1]:
            target = getattr(target, part)
        last = parts[-1]
        prop = target.GetType().GetProperty(last, BindingFlags.Instance | BindingFlags.Public)
        if prop is None:
            raise Exception("settings: no public property '" + last + "' on " + target.GetType().FullName)
        setattr(target, last, _core_convert_for(prop.PropertyType, value))


def run_post_script(code, scope_values):
    """postScript escape hatch: run linted IronPython with the given names in scope."""
    if not code:
        return
    scope = {"Document": B.doc, "Application": B.application, "B": B}
    for k in scope_values:
        scope[k] = scope_values[k]
    exec(code, scope)


def clr_type(python_type):
    return clr.GetClrType(python_type)
