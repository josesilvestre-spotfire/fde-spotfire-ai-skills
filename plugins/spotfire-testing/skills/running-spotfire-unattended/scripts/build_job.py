# Build and render job for the runner (IronPython 3, Spotfire Analyst 15.0).
#
# "sfrun.py build" and "sfrun.py render" run this script through runner.dxp.
# It receives JOB, a dict read from job.json:
#   analysis     absolute path of the .dxp to open (the base of a build, or
#                the analysis to render)
#   builder      optional IronPython file to run in the opened analysis; it
#                sees Document, Application and JOB like a script run from
#                the script editor
#   output       optional absolute path; the analysis is saved there (Save As)
#   activePage   optional page title made active before saving
#   render       true to render every page to PNG (default true)
#   width, height  render size in pixels (default 1600 x 900)
#   saveOnError  "true" to save even when the builder raised an error
# Results go to JOB["jobDir"]: build_result.json, builder_output.txt and
# renders/page_NN.png. The source analysis is never written unless output
# names the same file.
import clr
import sys
import time
import traceback
import json

clr.AddReference("System.Drawing")
from System.IO import Directory, File, Path
from System.Drawing import Bitmap, Graphics, Rectangle, Color
from System.Drawing.Imaging import ImageFormat
from Spotfire.Dxp.Application import DocumentSaveSettings

RESULT = {"ok": False, "log": [], "renders": []}


def log(text):
    RESULT["log"].append(time.strftime("%H:%M:%S") + "  " + text)


class Capture(object):
    """Collects what the builder prints."""

    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass


def flag(name, default):
    value = JOB.get(name, default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes")


def render_pages(doc, folder):
    width = int(JOB.get("width", 1600))
    height = int(JOB.get("height", 900))
    Directory.CreateDirectory(folder)
    index = 0
    for page in doc.Pages:
        index += 1
        bitmap = Bitmap(width, height)
        graphics = Graphics.FromImage(bitmap)
        try:
            graphics.Clear(Color.White)
            for visual in [v for v in page.Visuals]:
                try:
                    visual.Render(graphics, page.GetVisualBounds(
                        visual, Rectangle(0, 0, width, height)))
                except Exception:
                    log("render failed: %s / %s" % (page.Title,
                                                    visual.Title))
            name = "page_%02d.png" % index
            bitmap.Save(Path.Combine(folder, name), ImageFormat.Png)
            RESULT["renders"].append({"page": page.Title,
                                      "file": "renders/" + name})
        finally:
            graphics.Dispose()
            bitmap.Dispose()
    log("rendered %d page(s)" % index)


def run_builder(path):
    code = File.ReadAllText(path)
    scope = dict(globals())
    scope["Document"] = Application.Document
    scope["__name__"] = "__builder__"
    capture = Capture()
    saved_stdout = sys.stdout
    sys.stdout = capture
    started = time.time()
    try:
        exec(compile(code, path, "exec"), scope)
    finally:
        sys.stdout = saved_stdout
        File.WriteAllText(Path.Combine(JOB["jobDir"], "builder_output.txt"),
                          "".join(capture.parts))
        RESULT["builderSeconds"] = round(time.time() - started, 1)


def main():
    Directory.CreateDirectory(JOB["jobDir"])
    analysis = JOB.get("analysis")
    if analysis:
        if not Application.Open(analysis):
            raise Exception("could not open " + analysis)
        log("opened " + analysis)
    doc = Application.Document
    builder_ok = True
    if JOB.get("builder"):
        try:
            run_builder(JOB["builder"])
            log("builder finished in %s s" % RESULT["builderSeconds"])
        except Exception:
            builder_ok = False
            RESULT["builderError"] = traceback.format_exc()
            log("builder failed")
        doc = Application.Document
    page_title = JOB.get("activePage")
    if page_title:
        for page in doc.Pages:
            if page.Title == page_title:
                doc.ActivePageReference = page
    output = JOB.get("output")
    if output and (builder_ok or flag("saveOnError", False)):
        Directory.CreateDirectory(Path.GetDirectoryName(output))
        Application.SaveAs(output, DocumentSaveSettings())
        RESULT["saved"] = output
        log("saved " + output)
    RESULT["pages"] = [p.Title for p in doc.Pages]
    RESULT["tables"] = [{"name": t.Name, "rows": t.RowCount,
                         "columns": t.Columns.Count}
                        for t in doc.Data.Tables]
    if flag("render", True):
        render_pages(doc, Path.Combine(JOB["jobDir"], "renders"))
    RESULT["ok"] = builder_ok and (not output or "saved" in RESULT)


try:
    main()
except Exception:
    RESULT["error"] = traceback.format_exc()
    log("job failed")
File.WriteAllText(Path.Combine(JOB["jobDir"], "build_result.json"),
                  json.dumps(RESULT, indent=1))
