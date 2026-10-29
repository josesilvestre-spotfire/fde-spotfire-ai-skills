# ============================================================================
# 80_textareas.py - HTML text areas: HTML, CSS injection, JavaScript and
# text-area controls (property controls and action controls).
# IronPython 3.4 inside Spotfire Analyst 15.0 (Python 3.4 syntax: no f-strings,
# no walrus, no annotations, no print).
#
#   vis_textarea(page, vspec) -> Visual
#     1. VisualCollection.AddNew(HtmlTextArea); Title and ShowTitle at once.
#     2. Every control of vspec.controls, in the order of their {{control:<id>}}
#        placeholders, becomes a manual step (no public API adds a control).
#     3. HtmlContent set ONCE: each placeholder replaced by a visible "[control: <id>]"
#        marker that the manual step tells the user to replace.
#        CSS: safe mode prepends <div id="style-container" class="sfdxb-style-<vid>"></div>
#        and attaches a small JavaScript that injects the CSS once into that div; rich mode
#        prepends <style>.
#     4. The CSS injector and every vspec.js entry through attach_js (40_scripts.py).
#     5. vis_common (60_charts.py) last, with only the fields a text area has (title,
#        showTitle, settings, postScript), so the escape hatches see the finished area.
#
# Text-area controls have no public API in Spotfire 15.0: each control becomes a visible
# "[control: <id>]" marker and a manual step (B.fallback) with the exact Analyst
# instruction (Edit Text Area > Insert Property Control / Insert Action Control).
# Members: lib/80_textareas.members.txt (public), .set.txt.
# Reference: references/api-textareas.md.
#
# Spec interpretation owned by this module:
# - checkbox: Spotfire has no check-box property control (RenderType.CheckBox maps to no
#   control type), so it is a Drop-down list on the Boolean property, Yes = True / No = False.
# - radio: no radio-button property control either (RenderType.RadioButton maps to no
#   control type), so it is a single-select List box (all options visible) with the same values.
# - slider: NumericalRangeValueProvider min / max / step (default 1), range labels shown.
# - button/link: `script` wins over `action` when both are given (warned).
#   Visualization arguments must name a visual built BEFORE this text area (list the text
#   area after it in the page's visuals; the layout decides placement, not build order).
# - description: an HtmlTextArea has none (Visualization.Description); warned, not stored.
#
# Requires newer than 14.6: none (newest public member used: DataColumn.DataType [api 7.5]).
# ============================================================================
import re
import json
from System import String, Object, Boolean, Decimal, Enum, Array
from System.IO import File, Directory, Path
from Spotfire.Dxp.Application.Visuals import HtmlTextArea, VisualTypeIdentifiers
from Spotfire.Dxp.Application.AnalyticItems import BookmarkManager
from Spotfire.Dxp.Framework.DocumentModel import TypeIdentifier, DocumentNode
from Spotfire.Dxp.Framework.ApplicationModel import DocumentOperation

_textareas_ns_controls = "Spotfire.Dxp.Application.HtmlTextAreaControls."
_textareas_ns_links = "Spotfire.Dxp.Application.ActionLinks."
_textareas_ns_scripting = "Spotfire.Dxp.Application.Scripting."

_textareas_placeholder_re = re.compile(r"\{\{\s*control\s*:\s*([^{}\s]+)\s*\}\}")

# spec kind -> (RenderType member, Spotfire UI name of the property control)
_textareas_property_kinds = {
    "label": ("Label", "Label"),
    "input": ("TextBox", "Input field"),
    "multilineInput": ("MultiLineTextBox", "Input field (multiple lines)"),
    "dropdown": ("DropDown", "Drop-down list"),
    "listbox": ("ListBox", "List box"),
    "multiSelectListbox": ("MultiSelectListBox", "List box (multiple select)"),
    "slider": ("Slider", "Slider"),
    "checkbox": ("DropDown", "Drop-down list"),
    "radio": ("ListBox", "List box"),
}
_textareas_numeric_types = ("Integer", "LongInteger", "Real", "SingleReal", "Currency")
_textareas_whole_types = ("Integer", "LongInteger")
_textareas_node_params = ("Page", "Visualization", "DataTable")
_textareas_checkbox_items = [("Yes", True), ("No", False)]
# The vspec fields a text area has. Table, marking, data limits, legend, description and
# coloring belong to visualizations (an HtmlTextArea has no Data, Legend or Description).
_textareas_common_keys = ("id", "type", "title", "showTitle", "settings", "postScript")


# ---- public builder ------------------------------------------------------------
def vis_textarea(page, vspec):
    """HTML text area with controls, CSS and JavaScript. Returns the Visual."""
    vid = vspec["id"]
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.HtmlTextArea)
    ta = visual.As[HtmlTextArea]()
    # Title and ShowTitle at once (public Visual members), exactly as vis_common sets them later (a
    # title present in the spec, "" included, is stored as given): attach_js records the text-area
    # title, and what the user sees never depends on vis_common, which only partly fits a text area.
    if vspec.get("title") is not None:
        visual.Title = str(vspec["title"])
    visual.ShowTitle = bool(vspec.get("showTitle", True))
    where = _textareas_where(page, vspec)
    if vspec.get("description"):
        B.warn(where + ": Spotfire text areas have no description (Visualization.Description does not "
               "apply to HtmlTextArea); 'description' was not stored")
    html = vspec.get("html") or ""
    css = vspec.get("css") or ""
    safe = (B.app.get("htmlMode") or "safe") != "rich"
    controls = vspec.get("controls") or {}
    if not isinstance(controls, dict):
        B.warn(where + ": 'controls' is not an object of control id -> control; no control was built")
        controls = {}
    info = {"htmlMode": "safe" if safe else "rich", "css": None, "js": [], "controls": [],
            "manual": []}
    B.created.setdefault("textAreas", {})[vid] = info

    # 1. controls, before HtmlContent, in placeholder order; unplaced ones after (sorted)
    order = []
    for match in _textareas_placeholder_re.finditer(html):
        if match.group(1) not in order:
            order.append(match.group(1))
    unplaced = sorted([cid for cid in controls.keys() if cid not in order])
    tokens = {}
    manuals = {}
    for cid in order + unplaced:
        cspec = controls.get(cid)
        if cspec is None:
            B.fallback(B.group + ".textArea.control", vid + "/" + cid,
                       "the HTML has a {{control:" + cid + "}} placeholder but 'controls' has no entry '" + cid + "'",
                       "In " + where + ": Edit Text Area and replace the [control: " + cid + "] marker with the "
                       "control it stands for, or delete it (spec.json has no control '" + cid + "').")
            info["manual"].append(cid)
            continue
        manuals[cid] = _textareas_manual(where, cid, cspec)
        # no public API adds a text-area control: a visible marker plus a manual step
        B.fallback(B.group + ".textArea.control", vid + "/" + cid,
                   "Spotfire 15.0 has no public API for text-area controls", manuals[cid])
        info["manual"].append(cid)

    # 2. HtmlContent, once, after every control exists
    body = _textareas_fill(html, tokens, where)
    for cid in unplaced:
        B.warn(where + ": control '" + cid + "' has no {{control:" + cid + "}} placeholder in the "
               "HTML; it was appended at the end")
        body += "<p>" + (tokens[cid] if cid in tokens else _textareas_marker(cid)) + "</p>"
    prefix = ""
    if css:
        if not safe:
            prefix = "<style>" + css + "</style>"
            info["css"] = "style-block"
        elif 'id="style-container"' not in html and "id='style-container'" not in html:
            # the class marks this text area's own container (class values of letters, digits and
            # '-' / '_' survive the sanitizer), so the injector never writes into another text area's
            prefix = '<div id="style-container" class="' + _textareas_style_class(vid) + '"></div>'
    B.step("textArea.html", vid, _textareas_set_html, (ta, vid, prefix + body, tokens, manuals))

    # 3. JavaScript: the CSS injector first (safe mode), then vspec.js in spec order
    if css and safe:
        name = _textareas_css_name(vid)
        done = B.step("textArea.css", vid, _textareas_attach,
                      (ta, vid, name, _textareas_css_js(vid, css)),
                      fallback=_textareas_js_manual(where, vid, name))
        if done:
            info["css"] = "injected-js"
            info["js"].append(name)
    n = 0
    for js in vspec.get("js") or []:
        n += 1
        if not isinstance(js, dict):
            B.warn(where + ": js entry " + str(n) + " is not resolved to {name, code} by dxpgen; skipped")
            continue
        name = str(js.get("name") or ("Script " + str(n)))
        done = B.step("textArea.js", vid + "/" + name, _textareas_attach, (ta, vid, name, js.get("code")),
                      fallback=_textareas_js_manual(where, vid, name))
        if done:
            info["js"].append(name)

    # 4. title, showTitle, settings, postScript through vis_common - last
    B.step("textArea.common", vid, _textareas_common, (visual, ta, vspec))
    return visual


def _textareas_common(visual, ta, vspec):
    """vis_common (60_charts.py) with only the fields an HtmlTextArea has. Looked up when the step
    runs, so a missing or failing vis_common fails this step only, never the text area."""
    common = {}
    for key in _textareas_common_keys:
        if key in vspec:
            common[key] = vspec[key]
    return vis_common(visual, ta, common)


# ---- HTML ------------------------------------------------------------------------
def _textareas_fill(html, tokens, where):
    """Replace each {{control:<id>}} with its token, or a visible marker for a failed control."""
    used = []

    def replace(match):
        cid = match.group(1)
        if cid in used:
            B.warn(where + ": {{control:" + cid + "}} appears more than once; only the first one "
                   "keeps the control")
            return ""
        used.append(cid)
        if cid in tokens:
            return tokens[cid]
        return _textareas_marker(cid)

    return _textareas_placeholder_re.sub(replace, html)


def _textareas_marker(cid):
    text = cid.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # inline style only with plain values: survives the default sanitizer
    return ('<span style="color: #E94165; border: 1px dashed #E94165; padding: 0 4px">[control: '
            + text + ']</span>')


def _textareas_set_html(ta, vid, html, tokens, manuals):
    """Set HtmlContent once. Spotfire stores it verbatim; a token that did not survive means
    its control was deleted by the setter, which becomes a manual step."""
    ta.HtmlContent = html
    stored = ta.HtmlContent or ""
    lost = []
    summary = B.created.get("textAreas", {}).get(vid)
    for cid in sorted(tokens.keys()):
        if tokens[cid] not in stored:
            key = vid + "/" + cid
            lost.append(cid)
            if key in B.created["controls"]:
                del B.created["controls"][key]
            if summary is not None and cid in summary["controls"]:
                summary["controls"].remove(cid)
                summary["manual"].append(cid)
            B.fallback(B.group + ".textArea.control", key,
                       "the control token is not in the stored HTML, so Spotfire removed the control",
                       manuals[cid])
    if lost:
        B.warn("text area " + vid + ": control token(s) lost when HtmlContent was set: " + ", ".join(lost))
    return len(stored)


# ---- CSS and JavaScript -----------------------------------------------------------
def _textareas_css_name(vid):
    """Name of the CSS injector script, in the app's naming policy: 'Inject Panel Controls Styles'
    (program) or 'injectPanelControlsStyles' (camelCase) for the text area 'panelControls'."""
    words = _textareas_words(vid)
    if (B.app.get("namingPolicy") or "program") == "camelCase":
        return "inject" + "".join(words) + "Styles"
    return "Inject " + " ".join(words) + " Styles"


def _textareas_style_class(vid):
    """Class on the text area's own #style-container."""
    return "sfdxb-style-" + _textareas_safe_name(vid)


def _textareas_css_js(vid, css):
    """IIFE that injects the CSS once into this text area's #style-container (sfStyle.js pattern).
    Text-area JavaScript runs after every full render of the text area, which also rebuilds its
    DOM (and drops the old style), so a re-render re-injects; the fixed style id prevents
    duplicates. When the HTML brought its own container (no class), the first empty one is used,
    else the last one, else the document head."""
    style_id = "sfdxb-css-" + _textareas_safe_name(vid)
    own = "div[id='style-container']." + _textareas_style_class(vid)
    return "\n".join([
        "// Generated by the Spotfire DXP builder for text area '" + _textareas_safe_name(vid) + "'.",
        "// Injects the text area's CSS once into its #style-container (survives the HTML sanitizer).",
        "(function () {",
        "  var styleId = " + json.dumps(style_id) + ";",
        "  if (document.getElementById(styleId)) { return; }",
        "  var css = " + json.dumps(css) + ";",
        "  var host = document.querySelector(" + json.dumps(own) + ");",
        "  if (!host) {",
        "    var hosts = document.querySelectorAll(\"div[id='style-container']\");",
        "    for (var i = 0; i < hosts.length; i++) {",
        "      if (!hosts[i].firstChild) { host = hosts[i]; break; }",
        "    }",
        "    if (!host) { host = hosts.length ? hosts[hosts.length - 1] : (document.head || document.body); }",
        "  }",
        "  var style = document.createElement(\"style\");",
        "  style.id = styleId;",
        "  style.type = \"text/css\";",
        "  style.appendChild(document.createTextNode(css));",
        "  host.appendChild(style);",
        "})();",
    ])


def _textareas_attach(ta, vid, name, code):
    """attach_js (40_scripts.py). On failure the code is saved under build/textarea-js/ so the
    manual step can point at a file, then the error is re-raised for B.step."""
    try:
        if not code:
            raise Exception("JavaScript '" + str(name) + "' has no code")
        attach_js(ta, name, code)
        return name
    except Exception:
        _textareas_save_js(vid, name, code)
        raise


def _textareas_js_file(vid, name):
    return _textareas_safe_name(vid) + "-" + _textareas_safe_name(name) + ".js"


def _textareas_js_path(vid, name):
    """Where a JavaScript that could not be attached is saved: textarea-js/ next to the analysis
    (B.build_dir(), the folder of app.output)."""
    try:
        return Path.Combine(Path.Combine(B.build_dir(), "textarea-js"), _textareas_js_file(vid, name))
    except Exception:
        return "build/textarea-js/" + _textareas_js_file(vid, name)


def _textareas_save_js(vid, name, code):
    target = _textareas_js_path(vid, name)
    try:
        Directory.CreateDirectory(Path.GetDirectoryName(target))
        File.WriteAllText(target, code or "")
    except Exception as e:
        B.warn("could not save " + target + ": " + exc_text(e))


# ---- manual steps and names ------------------------------------------------------
def _textareas_where(page, vspec):
    title = str(vspec.get("title") or "")
    name = ("'" + title + "' (" + vspec["id"] + ")") if title else ("'" + vspec["id"] + "'")
    return "text area " + name + " on page '" + _textareas_page_title(page) + "'"


def _textareas_page_title(page):
    """Spec title of a page this build created. Pages carry temporary titles ('dxpb-page-NN') until
    doc_finish renames them (50_pages), so manual steps must name the spec title the user will see:
    B.created["pages"] maps it to the page id (register_page)."""
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


def _textareas_num(value):
    try:
        if isinstance(value, float) and value == int(value):
            return str(int(value))
    except (OverflowError, ValueError):
        pass                                            # inf / nan
    return str(value)


def _textareas_values_text(cspec):
    values = cspec.get("values") or {}
    if values.get("fixed") is not None:
        parts = []
        for item in values["fixed"]:
            value = item.get("value", item.get("text"))
            text = item.get("text")
            parts.append(str(value if text is None else text) + " = " + str(value))
        return " with fixed values " + ", ".join(parts)
    column = values.get("column")
    if column is not None:
        return " with values from column " + str(column.get("table")) + "." + str(column.get("column"))
    return " (no value source given in the spec)"


def _textareas_manual(where, cid, cspec):
    """Precise manual instruction for one control (used when it falls back). Never raises: it is
    built outside B.step, after the text area exists, so a malformed control spec must not cost the
    whole text area."""
    try:
        return _textareas_manual_text(where, cid, cspec)
    except Exception:
        return ("In " + where + ": Edit Text Area and replace the [control: " + str(cid) + "] marker with the "
                "control described for '" + str(cid) + "' in spec.json.")


def _textareas_manual_text(where, cid, cspec):
    kind = cspec.get("kind")
    head = "In " + where + ": Edit Text Area, delete the [control: " + cid + "] marker and, at that spot, "
    if kind in ("button", "link"):
        what = ("Insert Action Control > " + ("Link" if kind == "link" else "Button") + " labeled '"
                + str(cspec.get("label") or cid) + "' that " + _textareas_action_text(cspec))
    elif kind in _textareas_property_kinds:
        what = ("Insert Property Control > " + _textareas_property_kinds[kind][1]
                + " bound to document property " + str(cspec.get("property")))
        if kind == "slider":
            what += (" (range " + _textareas_num(cspec.get("min")) + " to " + _textareas_num(cspec.get("max"))
                     + ", step " + _textareas_num(cspec.get("step") or 1) + ")")
        elif kind == "checkbox":
            what += (" (Boolean) with fixed values Yes = True, No = False (Spotfire has no check-box "
                     "property control)")
        elif kind == "radio":
            what += _textareas_values_text(cspec) + " (single selection; Spotfire has no radio-button control)"
        elif kind in ("dropdown", "listbox", "multiSelectListbox"):
            what += _textareas_values_text(cspec)
            if kind == "multiSelectListbox":
                what += " (the property must be list-valued)"
    else:
        what = "insert the control described for '" + cid + "' in spec.json (unknown kind " + str(kind) + ")"
    return head + what + "."


def _textareas_action_text(cspec):
    script = cspec.get("script")
    action = cspec.get("action") or {}
    if script:
        args = cspec.get("args") or {}
        text = "runs the IronPython script '" + str(script) + "'"
        if args:
            text += " with arguments " + ", ".join([k + " = " + str(args[k]) for k in sorted(args.keys())])
        return text
    if action.get("gotoPage"):
        return "goes to page '" + str(action["gotoPage"]) + "'"
    if action.get("applyBookmark"):
        return ("applies bookmark '" + str(action["applyBookmark"]) + "' (create the bookmark first if it "
                "does not exist)")
    if action.get("refreshDataFunction"):
        return "refreshes data function '" + str(action["refreshDataFunction"]) + "'"
    return "does what spec.json describes (no script or action given)"


def _textareas_js_manual(where, vid, name):
    return ("In " + where + ": Edit Text Area > Insert JavaScript, add a new script named '" + name
            + "' with the code saved as " + _textareas_js_path(vid, name) + ".")


def _textareas_visual_title(vid):
    for pspec in B.spec.get("pages") or []:
        for v in pspec.get("visuals") or []:
            if v.get("id") == vid:
                return str(v.get("title") or vid)
    return str(vid)


def _textareas_words(text):
    """'panelControls' -> ['Panel', 'Controls'] (splits camelCase and non-alphanumerics)."""
    words = []
    current = ""
    prev = ""
    for ch in str(text or ""):
        if not ch.isalnum():
            if current:
                words.append(current)
            current = ""
        elif ch.isupper() and current and not prev.isupper():
            words.append(current)
            current = ch
        else:
            current += ch
        prev = ch
    if current:
        words.append(current)
    if not words:
        return ["Text", "Area"]
    return [w[:1].upper() + w[1:] for w in words]


def _textareas_safe_name(text):
    out = []
    for ch in str(text or ""):
        out.append(ch if (ch.isalnum() or ch in "-_") else "_")
    return "".join(out) or "textarea"
