"""What the public Spotfire API cannot build: the manual steps of an app.

Spotfire Analyst 15.0 has no public API for text-area controls (property and action controls),
property-change script triggers, the document theme and custom styles, action mods (buttons and visual
action triggers that run an action-mod script) or a mod loaded from a project folder. The builder does
not create them. This module turns the spec items into:

    control_marker(cid, c)  the text of the visible marker that replaces {{control:<id>}} in the HTML
                            ("Drop-down list: SelectedPumpId", "Button: Reset Filters")
    steps(resolved)         [[what, how], ...]: one numbered instruction per item, in build order
                            (controls page by page, action-mod triggers, property triggers, action
                            mods, theme). APP "manual" carries them (the builder logs each as a TODO
                            line) and dxpgen writes them to build/MANUAL-STEPS-<tier>.md.
    markdown(app, steps)    the MANUAL-STEPS text

Standard library only; the slim tier's library (scripts/lib) words its own fallbacks the same way.
"""

PROPERTY_KINDS = {
    "label": "Label",
    "input": "Input field",
    "multilineInput": "Input field (multiple lines)",
    "dropdown": "Drop-down list",
    "listbox": "List box",
    "multiSelectListbox": "List box (multiple select)",
    "slider": "Slider",
    "checkbox": "Drop-down list",
    "radio": "List box",
}
ACTION_KINDS = {"button": "Button", "link": "Link"}


def _num(value):
    if isinstance(value, float) and value == value and value == int(value):
        return str(int(value))
    return str(value)


def control_marker(cid, c):
    """Marker text for a control: '<UI kind>: <property>' or '<Button|Link>: <label>'."""
    if not isinstance(c, dict):
        return "control: " + str(cid)
    kind = c.get("kind")
    if kind in ACTION_KINDS:
        return ACTION_KINDS[kind] + ": " + str(c.get("label") or cid)
    if kind in PROPERTY_KINDS:
        return PROPERTY_KINDS[kind] + ": " + str(c.get("property") or cid)
    return "control: " + str(cid)


def _values_text(c):
    values = c.get("values") if isinstance(c.get("values"), dict) else {}
    if values.get("fixed") is not None:
        parts = []
        for item in values["fixed"]:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            value = item.get("value", item.get("text"))
            text = item.get("text")
            parts.append(str(value if text is None else text) + " = " + str(value))
        return " with fixed values " + ", ".join(parts)
    column = values.get("column")
    if isinstance(column, dict):
        return " with values from column " + str(column.get("table")) + "." + str(column.get("column"))
    return " (the spec gives no value source)"


def _action_text(c):
    action = c.get("action") if isinstance(c.get("action"), dict) else {}
    if c.get("script"):
        text = "runs the IronPython script '" + str(c["script"]) + "'"
        args = c.get("args") if isinstance(c.get("args"), dict) else {}
        if args:
            text += " with arguments " + ", ".join(k + " = " + str(args[k]) for k in sorted(args))
        return text
    if action.get("gotoPage"):
        return "goes to page '" + str(action["gotoPage"]) + "'"
    if action.get("applyBookmark"):
        return ("applies bookmark '" + str(action["applyBookmark"]) + "' (create the bookmark first if "
                "it does not exist)")
    if action.get("refreshDataFunction"):
        return "refreshes data function '" + str(action["refreshDataFunction"]) + "'"
    ref = c.get("actionMod") if isinstance(c.get("actionMod"), dict) else None
    if ref:
        return ("runs the action '" + str(ref.get("script")) + "' of the action mod '" + str(ref.get("mod"))
                + "'" + _mod_args(ref))
    return "does what spec.json describes for it"


def _mod_args(ref):
    args = ref.get("args") if isinstance(ref.get("args"), dict) else {}
    if not args:
        return ""
    return " with arguments " + ", ".join(k + " = " + str(args[k]) for k in sorted(args))


def control_step(page_title, v, cid, c):
    """Instruction for one text-area control."""
    title = str(v.get("title") or "")
    where = ("text area '" + title + "' (" + str(v.get("id")) + ")") if title else (
        "text area '" + str(v.get("id")) + "'")
    marker = control_marker(cid, c)
    head = ("Page '" + str(page_title) + "', " + where + ": Edit Text Area, delete the marker ["
            + marker + "] and, at that spot, ")
    kind = c.get("kind") if isinstance(c, dict) else None
    if kind in ACTION_KINDS:
        what = ("Insert Action Control > " + ACTION_KINDS[kind] + " labeled '" + str(c.get("label") or cid)
                + "' that " + _action_text(c))
        if c.get("actionMod") and (c.get("script") or c.get("action")):
            ref = c["actionMod"]
            what += (" (the spec also names the action '" + str(ref.get("script")) + "' of the action mod '"
                     + str(ref.get("mod")) + "': use it instead when the mod is in the analysis)")
    elif kind in PROPERTY_KINDS:
        what = ("Insert Property Control > " + PROPERTY_KINDS[kind] + " bound to the document property "
                + str(c.get("property")))
        if kind == "slider":
            what += (" (range " + _num(c.get("min")) + " to " + _num(c.get("max")) + ", step "
                     + _num(c.get("step") or 1) + ")")
        elif kind == "checkbox":
            what += (" (Boolean) with fixed values Yes = True, No = False (Spotfire has no check-box "
                     "property control)")
        elif kind == "radio":
            what += _values_text(c) + " (single selection; Spotfire has no radio-button property control)"
        elif kind in ("dropdown", "listbox", "multiSelectListbox"):
            what += _values_text(c)
            if kind == "multiSelectListbox":
                what += " (the property must be list-valued)"
    else:
        what = "insert the control described for '" + str(cid) + "' in spec.json"
    return head + what + "."


def trigger_step(t, scripts):
    prop = str(t.get("property"))
    script = str(t.get("script"))
    text = ("Edit > Document Properties > Properties, select the document property '" + prop
            + "', click Script..., choose to run a script when the value changes, select the script '"
            + script + "' and click OK.")
    for s in scripts:
        if isinstance(s, dict) and s.get("name") == script and s.get("file"):
            text += " The builder adds the script from " + str(s["file"]) + "."
            break
    return text


def action_trigger_step(page_title, v, trig):
    ref = trig.get("actionMod") if isinstance(trig.get("actionMod"), dict) else {}
    title = str(v.get("title") or v.get("id"))
    text = ("Page '" + str(page_title) + "', visual '" + title + "': Visualization properties > Action "
            "triggers > add a " + str(trig.get("display") or "FloatingButton") + " that runs the action '"
            + str(ref.get("script")) + "' of the action mod '" + str(ref.get("mod")) + "'" + _mod_args(ref))
    if trig.get("label"):
        text += ", named '" + str(trig["label"]) + "'"
    return text + "."


def action_mod_step(m):
    project = m.get("project")
    text = ("Action mod '" + str(m.get("id")) + "': add it to the analysis (pin or install it in your "
            "library, or Tools > Development > Mods development > Connect to file")
    if project:
        text += " > " + str(project).replace("\\", "/").rstrip("/") + "/mod-manifest.json"
    return text + "), then wire the buttons and action triggers listed here to it."


def theme_step(theme):
    base = theme.get("base") or "LightSfx"
    text = "Apply the document theme " + str(base) + " in Analyst"
    if theme.get("customStyles"):
        text += (" with the custom styles that dxpgen saved as build/theme.json (theme editor JSON); "
                 "the `styling-spotfire-dxps` skill covers themes")
    return text + "."


def steps(resolved, raw=None):
    """[[what, how], ...] for every item of the spec the public API cannot build. raw: the spec as
    written (resolve_spec fills a default app.theme; only a theme the author wrote is a manual step)."""
    out = []
    scripts = resolved.get("scripts") or []
    for page in resolved.get("pages") or []:
        if not isinstance(page, dict):
            continue
        ptitle = page.get("title")
        for v in page.get("visuals") or []:
            if not isinstance(v, dict):
                continue
            controls = v.get("controls") if isinstance(v.get("controls"), dict) else {}
            for cid, c in controls.items():
                if isinstance(c, dict):
                    out.append(["control " + str(v.get("id")) + "/" + str(cid),
                                control_step(ptitle, v, cid, c)])
            for n, trig in enumerate(v.get("actionTriggers") or []):
                if isinstance(trig, dict):
                    out.append(["action trigger " + str(v.get("id")) + "[" + str(n) + "]",
                                action_trigger_step(ptitle, v, trig)])
    for t in resolved.get("triggers") or []:
        if isinstance(t, dict):
            out.append(["trigger " + str(t.get("property")) + " -> " + str(t.get("script")),
                        trigger_step(t, scripts)])
    for m in resolved.get("actionMods") or []:
        if isinstance(m, dict) and m.get("id"):
            out.append(["action mod " + str(m["id"]), action_mod_step(m)])
    theme = ((raw if isinstance(raw, dict) else resolved).get("app") or {}).get("theme")
    if isinstance(theme, dict) and theme:
        out.append(["theme", theme_step(theme)])
    return out


def markdown(name, tier, items):
    """MANUAL-STEPS-<tier>.md text."""
    lines = ["# Manual steps - " + str(name) + " (" + str(tier) + " tier)", ""]
    if not items:
        lines.append("Nothing to add by hand: the public API builds every item of this spec.")
        return "\n".join(lines) + "\n"
    lines += ["Spotfire Analyst 15.0 has no public API for these items, so the builder does not create "
              "them. After the build, open the saved DXP, do each step, and save. The build log lists "
              "the same items as TODO lines; a FAILED line in the log is a separate problem.", ""]
    for n, (what, how) in enumerate(items, 1):
        lines.append("%d. **%s**: %s" % (n, what, how))
    return "\n".join(lines) + "\n"
