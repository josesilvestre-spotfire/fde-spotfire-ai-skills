# Standard engine, kind "text": HTML text area.
# APP keys: html (file in HOME\html) or htmlText (inline HTML),
# controls {id: marker text}: each {{control:id}} becomes a visible
# marker (features/controls.py; the controls are added by hand from
# MANUAL-STEPS), js [[name, file in HOME] | [name, None, code]] attached
# after the single HtmlContent set (features/textjs.py).
# Converter: scripts/t3/text.py.
# @api HtmlTextArea.HtmlContent; VisualTypeIdentifiers.HtmlTextArea
# @set HtmlTextArea.HtmlContent
from System.IO import File, Path
from Spotfire.Dxp.Application.Visuals import HtmlTextArea

# ------------------------------------------------------------ text area
def build_text(v, vs):
    if "htmlText" in vs:
        html = vs["htmlText"]
    else:
        html = File.ReadAllText(Path.Combine(HOME, "html", vs["html"]))
    # @feature controls
    if vs.get("controls"):
        html = place_controls(v, vs, html)
    # @endfeature
    v.As[HtmlTextArea]().HtmlContent = html
    # @feature textjs
    if vs.get("js"):
        text_scripts(v, vs)
    # @endfeature


BUILDERS["text"] = build_text
TYPE_IDS["text"] = "HtmlTextArea"
