# ============================================================================
# 40_scripts.py - IronPython scripts, text-area JavaScript, property triggers.
#
#   scripts_add_all(scripts)        upsert every spec script (IronPython 3, typed parameters,
#                                   transaction flag), one B.step each -> {name: ScriptDefinition}
#   script_def(name)                the registered IronPython ScriptDefinition named `name`
#                                   (what the property-trigger check needs)
#   attach_js(text_area, name, code, params=None)
#                                   JavaScript on an HTML text area through the public
#                                   HtmlTextArea.Scripts API (used by 80_textareas; raises on
#                                   failure, the caller wraps it in B.step)
#   scripts_add_triggers(triggers)  property-change triggers: no public API adds one, so each
#                                   becomes a manual step that names the property and script
#
# Requires newer than 14.6: none (newest member used: ScriptLanguage.IronPython3 [api 14.1]).
# Public API only.
# Reference: references/api-scripts.md. IronPython 3.4: no f-strings, walrus, annotations, print.
# ============================================================================
import re
import json
from System import String
from System.Collections.Generic import List, Dictionary
from Spotfire.Dxp.Application.Scripting import (ScriptDefinition, ScriptLanguage, ScriptParameter,
                                                ScriptParameterCollection, ScriptParameterType,
                                                HtmlTextAreaScript)
from Spotfire.Dxp.Application.Visuals import HtmlTextArea

# references/spec-format.md parameter types. Each is a static property of the ScriptParameterType pseudo-enum class.
_scripts_param_types = ("String", "Integer", "LongInteger", "Real", "SingleReal", "Boolean", "Date",
                        "DateTime", "Time", "TimeSpan", "Currency", "Page", "Visualization", "DataTable")

# ScriptDefinition.Create rejects these IronPython parameter names.
_scripts_py_reserved = ("False", "None", "True", "and", "as", "assert", "async", "await", "break",
                        "class", "continue", "def", "del", "elif", "else", "except", "finally", "for",
                        "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or",
                        "pass", "raise", "return", "try", "while", "with", "yield")

_scripts_param_name_re = re.compile(r"^[_A-Za-z][_A-Za-z0-9]*\Z")

# Characters ScriptDefinition.Create rejects in a script name (plus U+0000..U+001F).
_scripts_bad_name_chars = "\\/\":*?<>|"

# JavaScript definitions attached during this build: name -> [registered ScriptDefinition, ...]
_scripts_js_built = {}


# ---- shared helpers -------------------------------------------------------------
def _scripts_text(value):
    return "" if value is None else str(value)


def _scripts_entries(items, what):
    """The object entries of a spec list. 90_build calls the list-level functions outside B.step, so
    they must never raise: anything that is not an object is recorded as a skipped step instead."""
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        B.skip(what, "spec", "expected a list of objects, got " + type(items).__name__)
        return []
    out = []
    n = 0
    for item in items:
        n += 1
        if isinstance(item, dict):
            out.append(item)
        else:
            B.skip(what, "#" + str(n), "not an object in the spec: " + repr(item)[:80])
    return out


def _scripts_is_js(sd):
    return sd.Language is not None and sd.Language.Equals(ScriptLanguage.JavaScript)


def _scripts_registered(name, javascript):
    """Registered definitions named `name` (ordinal match), JavaScript ones or all others."""
    out = []
    for sd in B.doc.ScriptManager.GetAllScriptsWithName(name):
        if _scripts_is_js(sd) == javascript:
            out.append(sd)
    return out


def _scripts_check_name(name):
    if not name or not name.strip():
        raise Exception("script name is empty")
    for ch in name:
        if ch in _scripts_bad_name_chars or ord(ch) < 32:
            raise Exception("script name '" + name + "' contains a character Spotfire rejects "
                            "(\\ / \" : * ? < > | or a control character)")


def _scripts_upsert(name, wanted, javascript):
    """Add `wanted`, or replace the first registered definition with the same name and language
    class. Replace keeps the ManagedScriptDefinition node, so buttons and handlers that point at
    the old definition run the new one. Returns (registered definition, action)."""
    sm = B.doc.ScriptManager
    existing = _scripts_registered(name, javascript)
    if len(existing) > 1:
        B.warn("the document already holds " + str(len(existing)) + " scripts named '" + name
               + "'; the first was updated, the others were left as they are")
    if not existing:
        sm.AddScriptDefinition(wanted)          # no duplicate-name check in Spotfire: upsert only
        return wanted, "added"
    if existing[0].IsEquivalentTo(wanted):      # Name, Description, code, language, parameters, transaction
        return existing[0], "unchanged"
    sm.Replace(existing[0], wanted)             # needs the registered object, never a look-alike
    return wanted, "replaced"


# ---- IronPython scripts ------------------------------------------------------------
def _scripts_parameters(plist, script_name):
    """Spec parameters -> (ScriptParameterCollection, [names]). Create needs a collection, never None."""
    items = List[ScriptParameter]()
    names = []
    for p in plist or []:
        pname = p.get("name") or ""
        ptype = p.get("type") or "String"
        if not _scripts_param_name_re.match(pname) or pname in _scripts_py_reserved:
            raise Exception("script '" + script_name + "': parameter name '" + pname
                            + "' is not a valid IronPython identifier")
        if pname in names:
            raise Exception("script '" + script_name + "': duplicate parameter '" + pname + "'")
        if ptype not in _scripts_param_types:
            raise Exception("script '" + script_name + "': unsupported parameter type '" + str(ptype)
                            + "' (use one of " + ", ".join(_scripts_param_types) + ")")
        items.Add(ScriptParameter(pname, p.get("description") or "", getattr(ScriptParameterType, ptype)))
        names.append(pname)
    return ScriptParameterCollection(items), names


def _scripts_add_one(sspec):
    name = _scripts_text(sspec.get("name"))
    _scripts_check_name(name)
    code = sspec.get("code")
    if not code:
        raise Exception("script '" + name + "' has no code (the spec needs 'code' or 'file')")
    params, names = _scripts_parameters(sspec.get("parameters"), name)
    flag = sspec.get("transaction")
    transaction = True if flag is None else bool(flag)
    # Create stamps the definition with the current Windows user's approval (IL: createApprovalStamp).
    # Not yet tested: the saved analysis reopens with these scripts trusted for the same user.
    wanted = ScriptDefinition.Create(name, sspec.get("description") or "", code,
                                     ScriptLanguage.IronPython3, params, transaction)
    sd, action = _scripts_upsert(name, wanted, False)
    B.created["scripts"][name] = {"language": "IronPython3", "action": action, "parameters": names,
                                  "transaction": transaction, "file": sspec.get("file") or ""}
    return sd


def _scripts_report_existing(spec_names):
    """Scripts outside the spec are never removed (they may be wired to something); a starting
    document that already holds some is reported, like doc_prepare does for tables."""
    others = sorted(set([sd.Name for sd in B.doc.ScriptManager.GetScripts() if sd.Name not in spec_names]))
    if others:
        B.warn("the starting document already holds script(s) that are not in the spec and stay in the "
               "analysis: " + ", ".join(others) + " (start each build from a new blank analysis)")
    return others


def scripts_add_all(scripts):
    """Upsert every spec script in its own step. Returns {name: registered ScriptDefinition}."""
    built = {}
    seen = {}
    entries = _scripts_entries(scripts, "script")
    spec_names = set([_scripts_text(s.get("name")) for s in entries])
    B.step("existing", "document scripts", _scripts_report_existing, (spec_names,))
    for sspec in entries:
        name = _scripts_text(sspec.get("name"))
        if name in seen:
            B.warn("script '" + name + "' is defined more than once in the spec; the last definition wins")
        seen[name] = True
        sd = B.step("script", name, _scripts_add_one, (sspec,))
        if sd is not None:
            built[name] = sd
    return built


def script_def(name):
    """The registered IronPython ScriptDefinition named `name` (exact, case-sensitive).

    JavaScript definitions with the same name are ignored. The returned object is the one held
    by Document.ScriptManager, so managed_script_for(), Replace and Remove accept it."""
    found = _scripts_registered(name, False)
    if not found:
        if _scripts_registered(name, True):
            raise Exception("'" + str(name) + "' is a JavaScript definition, not an IronPython script")
        raise Exception("script not found: " + str(name))
    return found[0]


# ---- JavaScript on HTML text areas (public API) -------------------------------------
def _scripts_js_value(value):
    """JavaScript parameter values are strings; other JSON values are JSON-encoded."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _scripts_js_register(name, wanted):
    """Registered JavaScript definition to attach.

    First use of a name in this build: upsert (a stale definition left by an earlier build is
    replaced in place, so re-runs do not stack copies). Later uses: reuse an equivalent
    definition; different code under the same name gets its own definition (warned), because
    replacing it would silently re-code the text areas that already use it."""
    built = _scripts_js_built.get(name)
    if built is None:
        sd, action = _scripts_upsert(name, wanted, True)
        _scripts_js_built[name] = [sd]
        return sd
    for sd in built:
        if sd.IsEquivalentTo(wanted):
            return sd
    B.warn("JavaScript '" + name + "' is attached with different code or parameters to several text "
           "areas; each variant is stored as its own script with the same name - give them distinct names")
    B.doc.ScriptManager.AddScriptDefinition(wanted)
    built.append(wanted)
    return wanted


def _scripts_record_js(name, ta, keys):
    key = name
    entry = B.created["scripts"].get(key)
    if entry is not None and entry.get("language") != "JavaScript":
        B.warn("JavaScript '" + name + "' has the same name as an IronPython script; rename one of them")
        key = name + " [JavaScript]"
        entry = B.created["scripts"].get(key)
    if entry is None:
        entry = {"language": "JavaScript", "parameters": keys, "textAreas": []}
        B.created["scripts"][key] = entry
    entry["textAreas"].append(ta.Title or "")


def attach_js(text_area, name, code, params=None):
    """Attach JavaScript to an HTML text area through the public HtmlTextArea.Scripts API.

    text_area: the HtmlTextArea content (a Visual is converted). params: {name: value}; every
    JavaScript parameter is a String parameter, non-string values are JSON-encoded. Re-attaching
    the same name to the same text area replaces the earlier copy. Raises on failure.
    Returns the registered JavaScript ScriptDefinition."""
    if text_area is None:
        raise Exception("attach_js: no text area given for '" + str(name) + "'")
    ta = text_area if hasattr(text_area, "Scripts") else text_area.As[HtmlTextArea]()
    _scripts_check_name(name)
    if not code:
        raise Exception("JavaScript '" + name + "' has no code")
    params = params or {}
    keys = sorted(params.keys())
    items = List[ScriptParameter]()
    values = Dictionary[String, String]()
    for key in keys:
        items.Add(ScriptParameter(key, "", ScriptParameterType.String))   # JS parameters must be String
        values[key] = _scripts_js_value(params[key])
    wanted = ScriptDefinition.Create(name, "", code, ScriptLanguage.JavaScript,
                                     ScriptParameterCollection(items), False)
    sd = _scripts_js_register(name, wanted)
    i = ta.Scripts.Count - 1
    while i >= 0:
        current = ta.Scripts[i].ScriptDefinition
        if current is not None and current.Name == name:
            ta.Scripts.RemoveAt(i)
        i -= 1
    # Add accepts JavaScript only and reuses the registered equivalent definition (IL), so the
    # upsert above leaves exactly one definition per distinct script.
    # Not yet tested: parameter values reach the script as JavaScript variables named after the
    # parameter; the script runs after each full render of the text area.
    ta.Scripts.Add(HtmlTextAreaScript(sd, values))
    _scripts_record_js(name, ta, keys)
    return sd


# ---- property-change triggers (manual steps) ------------------------------------------
def _scripts_trigger_manual(prop_name, script_name):
    text = ("In Analyst: Edit > Document Properties > Properties, select the document property '"
            + prop_name + "', click Script..., choose to execute a script when the property value "
            "changes, select the script '" + script_name + "' and click OK.")
    for sspec in B.spec.get("scripts") or []:
        if not isinstance(sspec, dict) or sspec.get("name") != script_name:
            continue
        if sspec.get("file"):
            text += (" If the script is missing, first add it (IronPython 3) from "
                     + str(sspec.get("file")) + ".")
        else:
            text += (" If the script is missing, first add it (IronPython 3) with the code given for '"
                     + script_name + "' in spec.json.")
        break
    return text


def _scripts_add_trigger(prop_name, script_name):
    """Property triggers have no public API in Spotfire 15.0: check that the property and the script
    exist (public), then raise, so the step becomes the manual step of _scripts_trigger_manual."""
    canonical = B.prop(prop_name).Name                     # public check: the property exists
    sd = script_def(script_name)
    if sd.Parameters.Count > 0:
        B.warn("trigger script '" + script_name + "' declares parameters ("
               + ", ".join([p.Name for p in sd.Parameters])
               + "); a property trigger passes no arguments")
    raise Exception("no public API adds a property trigger (" + canonical + " -> " + script_name + ")")


def scripts_add_triggers(triggers):
    """Attach every spec trigger (document property change -> IronPython script), one step each.

    Internal API: when it is unavailable or a call fails, the step becomes a manual step that
    names the property and the script. Returns {property: script name} for the attached ones."""
    done = {}
    seen = {}
    for tspec in _scripts_entries(triggers, "trigger"):
        prop_name = _scripts_text(tspec.get("property"))
        script_name = _scripts_text(tspec.get("script"))
        if prop_name.lower() in seen:
            B.warn("property '" + prop_name + "' has more than one trigger in the spec; Spotfire runs one "
                   "script per property, the last one ('" + script_name + "') is kept")
        seen[prop_name.lower()] = True
        result = B.step("trigger", prop_name + " -> " + script_name, _scripts_add_trigger,
                        (prop_name, script_name),
                        fallback=_scripts_trigger_manual(prop_name, script_name))
        if result is not None:
            done[prop_name] = script_name
    return done
