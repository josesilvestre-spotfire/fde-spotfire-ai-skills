# Standard engine, feature part "textjs": JavaScript on text
# areas through the public API (lib/40_scripts.py attach_js;
# references/api-textareas.md). Each script is registered once in the
# document (ScriptDefinition.Create(name, "", code, JavaScript, no
# parameters, wrap True) and attached to
# every text area that lists it, after the text area's single
# HtmlContent set. The code is read from HOME when the builder runs, so
# the builder stays small (inline code from the spec is carried in APP).
# One ok() per script and text area: "<id>: script <name>".
# APP text visual "js": [[name, file relative to HOME] | [name, None,
# code], ...] (name = the file stem).
# @api ScriptDefinition.Create(String, String, String, ScriptLanguage, ScriptParameterCollection, Boolean)
# @api ScriptLanguage.JavaScript; ScriptParameterCollection.ctor(IEnumerable<ScriptParameter>)
# @api Document.ScriptManager; ScriptManager.AddScriptDefinition(ScriptDefinition)
# @api ScriptManager.TryGetScript(String, out ScriptDefinition)
# @api HtmlTextArea.Scripts; HtmlTextAreaScriptCollection.Add(HtmlTextAreaScript)
# @api HtmlTextAreaScript.ctor(ScriptDefinition, IDictionary<String,String>)
# @api Visual.As; ScriptDefinition.Language; ScriptLanguage.Equals(Object)
from System import String
from System.IO import File, Path
from System.Collections.Generic import Dictionary, List
from Spotfire.Dxp.Application.Visuals import HtmlTextArea
from Spotfire.Dxp.Application.Scripting import ScriptDefinition
from Spotfire.Dxp.Application.Scripting import HtmlTextAreaScript
from Spotfire.Dxp.Application.Scripting import ScriptLanguage
from Spotfire.Dxp.Application.Scripting import ScriptParameter
from Spotfire.Dxp.Application.Scripting import ScriptParameterCollection

# ------------------------------------------------- text-area JavaScript
JS = {}


def js_definition(entry):
    """The registered JavaScript of an APP js entry (registered once)."""
    name = entry[0]
    if name in JS:
        return JS[name]
    found, sd = Document.ScriptManager.TryGetScript(name)
    if found and not sd.Language.Equals(ScriptLanguage.JavaScript):
        raise Exception("the document already has a non-JavaScript "
                        "script named " + name)
    if not found:
        if len(entry) > 2:
            code = entry[2]
        else:
            code = File.ReadAllText(Path.Combine(HOME, entry[1]))
        sd = ScriptDefinition.Create(
            name, "", code, ScriptLanguage.JavaScript,
            ScriptParameterCollection(List[ScriptParameter]()), True)
        Document.ScriptManager.AddScriptDefinition(sd)
    JS[name] = sd
    return sd


def attach_js(ta, entry):
    sd = js_definition(entry)
    ta.Scripts.Add(HtmlTextAreaScript(sd, Dictionary[String, String]()))


def text_scripts(v, vs):
    ta = v.As[HtmlTextArea]()
    for entry in vs["js"]:
        ok(vs["id"] + ": script " + entry[0], attach_js, ta, entry)
