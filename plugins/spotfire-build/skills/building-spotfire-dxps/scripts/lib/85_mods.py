# ============================================================================
# 85_mods.py - visualization mods (references/spec-format.md visual type "mod").
# vis_mod(page, vspec): find the mod by id (embedded in the document, installed
# or pinned in Analyst, then the Spotfire library), add it to the page, bind the
# data table, set axes by name and typed mod properties, then apply the common
# visual settings with vis_common (60_charts.py) last, so postScript sees the
# finished visual. A mod that is not available becomes a visible placeholder
# text area plus a manual step (install or pin the mod, then run again).
# Public API only - no internal reflection in this module.
#
# Requires newer than 14.6 (the Analyst that RUNS the builder; 15.0 also writes
# the 14.6 serialization, so the saved DXP still opens in 14.6):
#   ModVisualization.Axis(String), .AxesNames, .ColorAxis, .HasColorAxis  [api 14.7.0]
#   ModVisualization.Property<T>(String), .Properties                     [api 14.8.0]
# Everything else used here is [api] <= 14.5.
# ============================================================================
import json
from System import String, Boolean, Int32, Double
from Spotfire.Dxp.Application.Visuals import HtmlTextArea
from Spotfire.Dxp.Framework.Library import LibraryManager, LibraryItemType, LibraryItemRetrievalOption

# JSON value -> mod property type. Persisted as StringModProperty / BoolModProperty /
# IntModProperty / DoubleModProperty = ModProperty<String|Boolean|Int32|Double>.
_mods_types = (("String", String), ("Boolean", Boolean), ("Int32", Int32), ("Double", Double))
_mods_int32_min = -2147483648
_mods_int32_max = 2147483647
_mods_string_max = 102400          # StringModProperty.MaxLength
# words ignored when a library item title is matched to a mod id
# ("pump-fleet-monitor-mod" ~ "Pump Fleet Monitor", "text-card-mod" ~ "Text Card")
_mods_noise = ("mod", "mods", "spotfire", "sfire")
_mods_library_tries = 3


def vis_mod(page, vspec):
    """Build one mod visual. Returns the Visual (or a placeholder text area's Visual)."""
    vid = vspec["id"]
    mod_id = vspec.get("modId") or ""
    title = vspec.get("title") or _mods_title_hint(mod_id) or vid
    info = {"modId": mod_id, "source": None, "name": None, "version": None,
            "libraryPath": None, "placeholder": False}
    B.created.setdefault("mods", {})[vid] = info

    found = B.step("mod.find", vid, _mods_find, (mod_id,), fallback=_mods_manual_install(mod_id, vid))
    content = None
    if found is not None:
        mid, source, library_path = found
        mod_name = mid.Name or mod_id
        info.update(source=source, name=mod_name, version=str(mid.Version), libraryPath=library_path)
        content = B.step("mod.add", vid, _mods_add, (page, mid),
                         fallback="In Analyst, add the mod '" + mod_name + "' (" + mod_id + ") to page '"
                                  + _mods_page_title(page) + "' by hand and configure it as listed for '"
                                  + vid + "' in spec.json; the builder left a placeholder there.")
    if content is None:
        info["placeholder"] = True
        return B.step("mod.placeholder", vid, _mods_placeholder, (page, vspec))

    visual = content.Visual
    # Data table before the axes: axis expressions resolve against it. vis_common (60_charts) skips
    # the assignment when the table is already this object, so the axes set below stay untouched.
    B.step("mod.table", vid, _mods_set_table, (content, vspec))

    axes = vspec.get("axes") or {}
    for name in sorted(axes.keys()):
        target = vid + "/axis:" + name
        expression = _mods_axis_text(axes[name])
        if expression is None:
            B.skip("mod.axis", target, "null in the spec: left as the mod configured it")
            continue
        B.step("mod.axis", target, _mods_set_axis, (content, mod_id, name, expression),
               fallback="In Analyst, set the '" + name + "' axis of visual '" + title + "' to: "
                        + (expression if expression else "(empty)"))

    props = vspec.get("properties") or {}
    for name in sorted(props.keys()):
        target = vid + "/property:" + name
        value = props[name]
        if value is None:
            B.skip("mod.property", target, "null in the spec: left at the mod's default")
            continue
        B.step("mod.property", target, _mods_set_property, (content, mod_id, name, value),
               fallback="Set the mod property '" + name + "' of visual '" + title + "' to "
                        + _mods_short(json.dumps(value)) + " in the mod's own settings.")

    _mods_unsupported(vid, title, vspec)
    # title, showTitle, description, marking, limitByMarkings, limitExpression, useFiltering,
    # legend, settings and postScript - last, so the escape hatches see the finished mod.
    B.step("mod.common", vid, _mods_common, (visual, content, vspec))
    B.step("mod.check", vid, _mods_check, (content, vid))
    return visual


def _mods_common(visual, content, vspec):
    # resolved at call time inside the step, so even a missing 60_charts is recorded, not raised
    return vis_common(visual, content, vspec)


# ---- finding the mod ------------------------------------------------------------
def _mods_find(mod_id):
    """(ModIdentifier, source, library path) for a visualization mod id, or raise with what exists."""
    if not mod_id:
        raise Exception("the mod visual has no modId")
    available = []
    # Embedded mods of this document come first, then installed/pinned mods not yet listed (IL).
    for mid in B.doc.ModManager.GetVisualizationModsIncludingPinned():
        if mid.Id == mod_id:
            return (mid, "available", None)
        available.append(mid.Id + " " + str(mid.Version))
    mid, detail = _mods_from_library(mod_id)
    if mid is not None:
        return (mid, "library", detail)
    raise Exception("mod '" + mod_id + "' is not embedded in the document, installed or pinned in this "
                    "Analyst (available: " + (", ".join(available) if available else "none")
                    + "); library: " + detail)


def _mods_from_library(mod_id):
    """(ModIdentifier, library path) or (None, reason). Library items carry no mod id, so a
    visualization mod whose title matches the id is loaded and its id confirmed."""
    key = _mods_norm(mod_id)
    if not key:
        return (None, "skipped (no searchable words in the mod id)")
    try:
        library = B.application.GetService[LibraryManager]()
    except Exception as e:
        return (None, "not available (" + exc_text(e) + ")")
    if library is None:
        return (None, "not available (not connected to a Spotfire Server)")
    try:
        # Not yet tested: "type:visualizationmod" is the search keyword. Inferred: Spotfire's own code
        # searches "type:dxp", "type:sbdf", "type:dataconnection" and the item type id is
        # "spotfire.visualizationmod". Also check that an offline Analyst raises instead of prompting.
        items = library.Search("type:visualizationmod", LibraryItemRetrievalOption.IncludePath)
    except Exception as e:
        return (None, "search failed (" + exc_text(e) + ")")
    candidates = []
    for item in items:
        if item.ItemType == LibraryItemType.VisualizationMod and _mods_norm(item.Title) == key:
            candidates.append(item)
    if not candidates:
        return (None, "no visualization mod titled like '" + _mods_title_hint(mod_id) + "'")
    candidates.sort(key=lambda it: it.LastModified, reverse=True)
    tried = []
    for item in candidates[:_mods_library_tries]:
        # TryLoad... embeds the mod in the document (ModManager AddOrUpdate, IL) even before a visual
        # uses it. Not yet tested: whether an embedded but unused mod is dropped at save.
        ok, mid, error = B.doc.ModManager.TryLoadVisualizationModFromLibrary(item)
        if ok and mid is not None and mid.Id == mod_id:
            return (mid, item.Path)
        if ok and mid is not None:
            tried.append(item.Path + " holds '" + mid.Id + "'")
            B.warn("library mod '" + item.Path + "' was loaded while looking for '" + mod_id
                   + "' but its id is '" + mid.Id + "'; it may stay embedded, unused, in the analysis")
        else:
            tried.append(item.Path + " did not load (" + str(error) + ")")
    return (None, "no matching mod among " + "; ".join(tried))


def _mods_add(page, mid):
    # AddNew(ModIdentifier) returns the ModVisualization content and embeds the mod (IL).
    # Not yet tested: no trust prompt blocks the script for a mod the user has not trusted yet.
    content = page.Visuals.AddNew(mid)
    if content is None:
        raise Exception("Visuals.AddNew(ModIdentifier) returned nothing")
    return content


def _mods_set_table(content, vspec):
    table = B.table_or_default(vspec.get("table"))
    content.Data.DataTableReference = table
    return table


# ---- axes -------------------------------------------------------------------------
def _mods_axis_text(value):
    """Axis value from the spec: an expression, or a list of expressions on one axis."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join([str(v) for v in value])
    return str(value)


# "# noqa: version" below: these [api 14.7] members are intended and listed in the module header;
# dxpgen warns once when a spec really has a mod visual, so the generated builder's lint stays quiet.
def _mods_axis_names(content):
    names = list(content.AxesNames)  # noqa: version
    if content.HasColorAxis:  # noqa: version
        names.append("Color")
    return names


def _mods_find_axis(content, mod_id, name):
    # Not yet tested: Axis(name) returns None (not an exception) for an unknown name, and mod axes
    # exist right after AddNew.
    try:
        axis = content.Axis(name)  # noqa: version
    except Exception:
        axis = None
    if axis is not None:
        return axis
    # The mod's color axis is a ColorAxis outside AxesNames (corpus: ColorAxis "Color").
    if name == "Color" and content.HasColorAxis:  # noqa: version
        return content.ColorAxis
    names = _mods_axis_names(content)
    raise Exception("mod '" + mod_id + "' has no axis '" + name + "'" + _mods_did_you_mean(name, names)
                    + "; its axes are: " + (", ".join(names) if names else "(none)"))


def _mods_set_axis(content, mod_id, name, expression):
    axis = _mods_find_axis(content, mod_id, name)
    axis.Expression = expression
    return axis.Expression


# ---- properties -------------------------------------------------------------------
def _mods_value_candidates(value):
    """[(type label, .NET type, converted value)] to try, most likely first, for a JSON value."""
    if isinstance(value, bool):
        return [("Boolean", Boolean, Boolean(value))]
    if isinstance(value, int):
        out = []
        if _mods_int32_min <= value <= _mods_int32_max:
            out.append(("Int32", Int32, Int32(value)))
        out.append(("Double", Double, Double(float(value))))
        return out
    if isinstance(value, float):
        out = [("Double", Double, Double(value))]
        if (value == value and abs(value) != float("inf") and value == int(value)
                and _mods_int32_min <= int(value) <= _mods_int32_max):
            out.append(("Int32", Int32, Int32(int(value))))
        return out
    if isinstance(value, (dict, list)):
        # mods keep structured state as JSON text in string properties (GUI-built DXPs)
        value = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if isinstance(value, str):
        if len(value) > _mods_string_max:
            raise Exception("the text has " + str(len(value)) + " characters; a mod string property "
                            "holds at most " + str(_mods_string_max))
        return [("String", String, value)]
    raise Exception("unsupported value type for a mod property: " + type(value).__name__)


def _mods_property_type(content, name):
    """Type label of an existing mod property, or None when the mod has no such property."""
    for label, net_type in _mods_types:
        if content.Property[net_type](name) is not None:
            return label
    return None


def _mods_set_property(content, mod_id, name, value):
    candidates = _mods_value_candidates(value)
    for label, net_type, converted in candidates:
        # Property[T] is None when the name is missing OR the stored type is not T (IL: isinst).
        # Not yet tested: the generic call syntax Property[String](name) from IronPython 3.
        prop = content.Property[net_type](name)
        if prop is not None:
            prop.Value = converted
            return label
    actual = _mods_property_type(content, name)
    if actual is not None:
        raise Exception("mod '" + mod_id + "' property '" + name + "' is " + actual + " but the spec value "
                        + _mods_short(json.dumps(value)) + " is "
                        + " or ".join([c[0] for c in candidates]))
    names = [p.Name for p in content.Properties]
    raise Exception("mod '" + mod_id + "' has no property '" + name + "'" + _mods_did_you_mean(name, names)
                    + "; its properties are: " + (", ".join(names) if names else "(none)"))


# ---- checks, placeholder, messages ---------------------------------------------------
def _mods_unsupported(vid, title, vspec):
    if vspec.get("coloring"):
        B.fallback(B.group + ".mod.coloring", vid, "vis_mod does not apply the common 'coloring' field",
                   "In Analyst, set the colors of the Color axis of visual '" + title + "' to: "
                   + _mods_short(json.dumps(vspec["coloring"], sort_keys=True), 300))
    for key in ("referenceLayers", "fittingModels"):
        if vspec.get(key):
            B.skip("mod." + key, vid, key + " are not available on mod visuals")


def _mods_check(content, vid):
    # Not yet tested: what IsConfigurationValid() checks for a mod (required axes, columns).
    valid = content.IsConfigurationValid()
    if not valid:
        B.warn("mod visual '" + vid + "': Spotfire reports the configuration as not valid; check that every "
               "required axis has an expression whose columns exist in the data table")
    return valid


def _mods_placeholder(page, vspec):
    """Visible stand-in so the page layout still holds when the mod could not be added."""
    mod_id = vspec.get("modId") or ""
    text_area = page.Visuals.AddNew[HtmlTextArea]()
    text_area.HtmlContent = ("<p><b>[mod: " + _mods_html(mod_id) + "]</b></p>"
                             "<p>This visualization mod is not available in this Analyst. Make it available "
                             "(see MANUAL-STEPS.md) and run the builder again.</p>")
    visual = text_area.Visual
    visual.Title = vspec.get("title") or ("Mod " + mod_id)
    visual.ShowTitle = True
    return visual


def _mods_page_title(page):
    """Spec title of a page this build created: pages carry temporary titles ('dxpb-page-NN') until
    doc_finish renames them (50_pages), so a manual step must name the title the user will see.
    B.created["pages"] maps the spec title to the page id (register_page)."""
    try:
        pid = str(page.Id)
        pages = B.created.get("pages") or {}
        for title in pages:
            if pages[title] == pid:
                return str(title)
    except Exception:
        pass
    try:
        return str(page.Title or "")
    except Exception:
        return ""


def _mods_manual_install(mod_id, vid):
    hint = _mods_title_hint(mod_id) or mod_id
    return ("Make the mod '" + mod_id + "' available, then run the builder again: add it to the blank analysis "
            "before you run the builder (drag its .mod file in, or Tools > Development > Mods development > "
            "Connect to file for its mod-manifest.json; the builder reuses mods embedded in the document), "
            "or install/pin it in Analyst, or save it to the Spotfire library with a title like '" + hint
            + "'. Until then '" + vid + "' is a placeholder text area.")


def _mods_words(text):
    words = []
    current = []
    for ch in (text or "").lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return [w for w in words if w not in _mods_noise]


def _mods_norm(text):
    return "".join(_mods_words(text))


def _mods_title_hint(mod_id):
    return " ".join([w[:1].upper() + w[1:] for w in _mods_words(mod_id)])


def _mods_did_you_mean(name, names):
    key = "".join(name.lower().split())
    for n in names:
        if n != name and "".join(n.lower().split()) == key:
            return " (did you mean '" + n + "'?)"
    return ""


def _mods_short(text, limit=80):
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _mods_html(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
