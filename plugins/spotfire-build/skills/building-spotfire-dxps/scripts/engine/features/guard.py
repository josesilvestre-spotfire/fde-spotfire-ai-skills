# Standard engine, feature part "guard": the re-check text of a refused
# save and the build session switch. Included in every builder of an app
# that uses any feature.
#   - recheck(): what closing the Document Properties dialog can reset
#     (the markings and the description), named in the refused-save log
#     line and the report tier's fix text. Spotfire refuses SaveAs inside
#     a transaction, which is what a ticked "Execute in transaction" box
#     in the New Script dialog runs the builder in.
#   - switch_session(): called by finish() only after the inline save of
#     the DXP succeeded (never on the queued-save path). The analysis the
#     builder ran in stays open after the run, linked to the saved DXP;
#     closing the Document Properties dialog then re-applies the Markings
#     tab it showed when it opened (only the default marking) and deletes
#     the other markings in that open copy, and Ctrl+S or "save changes?"
#     would write that copy over the good file. So the switch (a) adds a
#     page "Build Session" with one HTML text area that says so and makes
#     it the active page, (b) saves the open analysis once more to
#     build\session\~build-session-<tier>.dxp, so it is linked
#     to that scratch file from then on, (c) logs "Session re-pointed to
#     <scratch> - open the saved DXP to use the app" after the "Saved
#     <path>" line. Each step runs in its own ok(); a failure is logged
#     (with a NOTE that the analysis may still be linked to the saved DXP)
#     and the saved DXP is never touched again.
# Uses why, OUT, LOG_FILE, LOG and ok (core).
# APP keys it reads: marking, markings (when present).
# @api PageCollection.AddNew(String); Page.Visuals; Visual.As
# @api VisualCollection.AddNew(TypeIdentifier); VisualTypeIdentifiers.HtmlTextArea
# @api HtmlTextArea.HtmlContent; Visual.Title; Visual.ShowTitle
# @api Document.ActivePageReference; Document.Pages
# @api AnalysisApplication.SaveAs(String, DocumentSaveSettings); DocumentSaveSettings.ctor
# @set HtmlTextArea.HtmlContent; Visual.Title; Visual.ShowTitle
# @set Document.ActivePageReference
from System.IO import Path, Directory
from Spotfire.Dxp.Application import DocumentSaveSettings
from Spotfire.Dxp.Application.Visuals import HtmlTextArea
from Spotfire.Dxp.Application.Visuals import VisualTypeIdentifiers

# ------------------------------------------------- refused-save check
def recheck():
    names = [APP["marking"][0]] + [m[0] for m in APP.get("markings", [])]
    text = ("Edit > Document Properties > Markings must list "
            + ", ".join(names))
    return text + "; General > Description."


# ------------------------------------------------- build session switch
SESSION_PAGE = "Build Session"


def session_file():
    """build\\session\\~build-session-<tier>.dxp (folder made);
    the tag is the log's (build-log-<tag>.txt)."""
    tag = Path.GetFileNameWithoutExtension(LOG_FILE)
    if tag.startswith("build-log-"):
        tag = tag[len("build-log-"):]
    folder = Path.Combine(Path.GetDirectoryName(OUT), "session")
    Directory.CreateDirectory(folder)
    return Path.Combine(folder, "~build-session-" + tag + ".dxp")


def session_html():
    """Sanitizer-safe: allowlisted elements, plain inline styles."""
    path = OUT.replace("&", "&amp;").replace("<", "&lt;")
    path = path.replace(">", "&gt;")
    return ('<div style="padding: 24px; font-family: Roboto, Arial, '
            'sans-serif; font-size: 14px; color: #232323;">'
            '<h2 style="margin: 0 0 12px 0;">Build session</h2>'
            '<p>This is the build session, not the app. Closing the '
            'Document Properties dialog resets its markings.</p>'
            '<p>Close this analysis without saving and open:</p>'
            '<p style="font-family: Consolas, monospace; '
            'font-weight: bold;">' + path + '</p></div>')


def session_page():
    page = Document.Pages.AddNew(SESSION_PAGE)
    v = page.Visuals.AddNew(VisualTypeIdentifiers.HtmlTextArea)
    v.Title = SESSION_PAGE
    v.ShowTitle = False
    v.As[HtmlTextArea]().HtmlContent = session_html()
    Document.ActivePageReference = page


def repoint():
    """Save the open analysis to the scratch file (never to OUT)."""
    target = session_file()
    if target.lower() == OUT.lower():
        raise Exception("the scratch file would be the saved DXP")
    Application.SaveAs(target, DocumentSaveSettings())
    return target


def switch_session():
    """Only after the saved DXP was written: the open analysis becomes
    the build session, linked to a scratch file."""
    ok("build session page", session_page)
    target = ok("build session save", repoint)
    if target:
        LOG.append("Session re-pointed to " + target + " - open the "
                   "saved DXP to use the app")
    else:
        LOG.append("NOTE this analysis may still be linked to " + OUT
                   + ": close it without saving (answer No) and open "
                   "the saved DXP.")
