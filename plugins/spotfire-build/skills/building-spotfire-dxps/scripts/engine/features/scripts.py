# Standard engine, feature part "scripts": IronPython 3 scripts
# registered in the document (lib/40_scripts.py _scripts_add_one), so
# text-area buttons can run them. The code is read from HOME\scripts at
# build time. ScriptDefinition.Create stamps the building user's trust.
# APP "scripts": [{name, file | code, description, params [[name, type,
# description], ...], transaction False (absent = true)}]
# @api ScriptDefinition.Create(String, String, String, ScriptLanguage, ScriptParameterCollection, Boolean)
# @api ScriptLanguage.IronPython3; ScriptParameterCollection.ctor(IEnumerable<ScriptParameter>)
# @api ScriptParameter.ctor(String, String, ScriptParameterType)
# @api ScriptParameterType.String; ScriptParameterType.Integer
# @api ScriptParameterType.LongInteger; ScriptParameterType.Real
# @api ScriptParameterType.Boolean; ScriptParameterType.DateTime
# @api Document.ScriptManager; ScriptManager.AddScriptDefinition(ScriptDefinition)
from System.IO import File, Path
from System.Collections.Generic import List
from Spotfire.Dxp.Application.Scripting import ScriptDefinition
from Spotfire.Dxp.Application.Scripting import ScriptLanguage
from Spotfire.Dxp.Application.Scripting import ScriptParameter
from Spotfire.Dxp.Application.Scripting import ScriptParameterCollection
from Spotfire.Dxp.Application.Scripting import ScriptParameterType

# ------------------------------------------------------------- scripts
SCRIPTS = {}


def add_script(s):
    items = List[ScriptParameter]()
    for p in s.get("params", []):
        items.Add(ScriptParameter(p[0], p[2] if len(p) > 2 else "",
                                  getattr(ScriptParameterType, p[1])))
    code = s.get("code")
    if code is None:
        code = File.ReadAllText(Path.Combine(HOME, "scripts", s["file"]))
    sd = ScriptDefinition.Create(
        s["name"], s.get("description", ""), code,
        ScriptLanguage.IronPython3, ScriptParameterCollection(items),
        s.get("transaction", True))
    Document.ScriptManager.AddScriptDefinition(sd)
    SCRIPTS[s["name"]] = sd
