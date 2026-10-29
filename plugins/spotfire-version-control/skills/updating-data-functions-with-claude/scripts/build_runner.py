# Builds the runner analysis (IronPython 3, Spotfire Analyst 15.0).
#
# Run it once, in a new blank analysis:
#   1. "python sfrun.py install" copies this file to
#      <DXP_WORKSPACE>/runner/build_runner_ready.py with RUNNER_DIR filled in.
#   2. In Analyst, start a new blank analysis. Open File > Document properties
#      > Scripts > New, choose IronPython 3, untick "Execute in transaction",
#      paste build_runner_ready.py and click Run Script. Then close the
#      dialogs with Cancel: Cancel undoes the changes in the open analysis,
#      but the files this script saved stay on disk.
#
# The script:
#   - saves the empty analysis as blank.dxp in RUNNER_DIR, the default base
#     that build jobs open;
#   - adds the IronPython script "Run Pending Job" (runner_job.py, no
#     transaction) and the JavaScript "Runner Auto Click"
#     (runner_autoclick.js);
#   - adds the page "Runner" with one text area that carries the JavaScript;
#   - saves the result as runner.dxp in RUNNER_DIR.
#
# One step stays manual, because the public Spotfire API has no call that
# adds an action control to a text area:
#   3. Open runner.dxp. Right-click the Runner text area > Edit text area.
#      Click "Insert action control", choose the control type Button,
#      display text Run Pending Job (exact spelling), action Script >
#      Run Pending Job, OK. Close the editor and use File > Save.
#
# Only public Spotfire API classes are used.
from System import String
from System.IO import File, Path
from System.Collections.Generic import List, Dictionary
from Spotfire.Dxp.Application import DocumentSaveSettings
from Spotfire.Dxp.Application.Layout import LayoutDefinition
from Spotfire.Dxp.Application.Scripting import (
    ScriptDefinition, ScriptLanguage, ScriptParameter,
    ScriptParameterCollection, HtmlTextAreaScript)
from Spotfire.Dxp.Application.Visuals import (
    VisualTypeIdentifiers, HtmlTextArea)

RUNNER_DIR = r"__RUNNER_DIR__"
LABEL = "Run Pending Job"
PAGE = "Runner"


def add_script(name, description, code, language):
    manager = Document.ScriptManager
    for script in [s for s in manager.GetScripts()]:
        if script.Name == name:
            manager.Remove(script)
    definition = ScriptDefinition.Create(
        name, description, code, language,
        ScriptParameterCollection(List[ScriptParameter]()), False)
    manager.AddScriptDefinition(definition)
    found, definition = manager.TryGetScript(name)
    return definition


def build():
    if "__RUNNER" in RUNNER_DIR:
        raise Exception("Set RUNNER_DIR, or use the build_runner_ready.py "
                        "file that 'sfrun.py install' writes.")
    has_runner_page = any(p.Title == PAGE for p in Document.Pages)
    if Document.Data.Tables.Count == 0 and not has_runner_page:
        Application.SaveAs(Path.Combine(RUNNER_DIR, "blank.dxp"),
                           DocumentSaveSettings())
    job_code = File.ReadAllText(Path.Combine(RUNNER_DIR, "runner_job.py"))
    click_code = File.ReadAllText(Path.Combine(RUNNER_DIR,
                                               "runner_autoclick.js"))
    add_script(LABEL, "Runs the pending job in job.json next to this file.",
               job_code, ScriptLanguage.IronPython3)
    click_script = add_script("Runner Auto Click",
                              "Clicks Run Pending Job when the page opens.",
                              click_code, ScriptLanguage.JavaScript)
    old_pages = [p for p in Document.Pages]
    page = Document.Pages.AddNew(PAGE)
    visual = page.Visuals.AddNew(VisualTypeIdentifiers.HtmlTextArea)
    visual.Title = PAGE
    visual.ShowTitle = False
    text_area = visual.As[HtmlTextArea]()
    text_area.HtmlContent = (
        "<div style='padding:16px;font-family:Arial'><h3>Runner</h3>"
        "<p>When this analysis opens, the Run Pending Job button runs the "
        "job in job.json next to this file. With no pending job it does "
        "nothing.</p><p>Button:</p></div>")
    text_area.Scripts.Add(HtmlTextAreaScript(click_script,
                                             Dictionary[String, String]()))
    layout = LayoutDefinition()
    layout.BeginStackedSection()
    layout.Add(visual)
    layout.EndSection()
    page.ApplyLayout(layout)
    Document.ActivePageReference = page
    for old in old_pages:
        Document.Pages.Remove(old)
    Application.SaveAs(Path.Combine(RUNNER_DIR, "runner.dxp"),
                       DocumentSaveSettings())


build()
