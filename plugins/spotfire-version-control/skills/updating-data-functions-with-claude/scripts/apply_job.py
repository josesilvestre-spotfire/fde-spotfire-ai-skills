# Unattended Spotfire Analyst job (IronPython 3, Spotfire Analyst 15.0),
# started by update_data_function.py through the runner (sfrun.py).
#
# Opens the source DXP, replaces the script of one data function through the
# Spotfire API, runs the function, records the trust state, the data tables
# and a render of every page, and saves the result as a new DXP. The source
# file is never written.
import json
import traceback
from System.IO import File, Path, Directory
from System.Drawing import Bitmap, Graphics, Rectangle, Color
from System.Drawing.Imaging import ImageFormat
from Spotfire.Dxp.Application import DocumentSaveSettings
from Spotfire.Dxp.Data import DataValueCursor
from Spotfire.Dxp.Data.DataFunctions import DataFunctionDefinitionBuilder

MAX_ROWS = 50
RESULT = {"steps": []}


def step(text):
    RESULT["steps"].append(text)


def table_summary(table):
    columns = [c for c in table.Columns]
    info = {"name": table.Name, "rows": table.RowCount,
            "columns": [c.Name for c in columns]}
    if table.RowCount <= MAX_ROWS:
        cursors = [DataValueCursor.CreateFormatted(c) for c in columns]
        info["values"] = [[cur.CurrentValue for cur in cursors]
                          for _row in table.GetRows(*cursors)]
    return info


def render_pages(doc, folder):
    files = []
    width, height = 1600, 900
    index = 0
    for page in doc.Pages:
        index += 1
        bitmap = Bitmap(width, height)
        graphics = Graphics.FromImage(bitmap)
        try:
            graphics.Clear(Color.White)
            for visual in [v for v in page.Visuals]:
                visual.Render(graphics, page.GetVisualBounds(
                    visual, Rectangle(0, 0, width, height)))
            name = "page_%02d.png" % index
            bitmap.Save(Path.Combine(folder, name), ImageFormat.Png)
            files.append({"page": page.Title, "file": name})
        finally:
            graphics.Dispose()
            bitmap.Dispose()
    return files


try:
    report_dir = JOB["reportDir"]
    Directory.CreateDirectory(report_dir)
    RESULT["opened"] = bool(Application.Open(JOB["source"]))
    doc = Application.Document
    step("opened " + JOB["source"])
    matches = [f for f in doc.Data.DataFunctions
               if f.Name == JOB["function"]]
    if not matches:
        raise Exception("no data function named " + JOB["function"])
    function = matches[0]
    old = function.DataFunctionDefinition
    RESULT["approvedBefore"] = bool(old.IsApprovedByCurrentUser)
    RESULT["oldScript"] = old.Settings["script"]
    builder = DataFunctionDefinitionBuilder(old)
    builder.Settings["script"] = File.ReadAllText(JOB["functionScript"])
    function.DataFunctionDefinition = builder.Build()
    step("script replaced through the Spotfire API")
    RESULT["approvedAfter"] = bool(
        function.DataFunctionDefinition.IsApprovedByCurrentUser)
    RESULT["executed"] = bool(function.ExecuteSynchronously())
    RESULT["needsRefresh"] = bool(function.NeedsRefresh)
    step("function executed: " + str(RESULT["executed"]))
    RESULT["tables"] = [table_summary(t) for t in doc.Data.Tables]
    RESULT["renders"] = render_pages(doc, report_dir)
    step("rendered %d page(s)" % len(RESULT["renders"]))
    Application.SaveAs(JOB["target"], DocumentSaveSettings())
    RESULT["saved"] = JOB["target"]
    step("saved " + JOB["target"])
except Exception:
    RESULT["error"] = traceback.format_exc()
File.WriteAllText(Path.Combine(JOB["reportDir"], "spotfire_result.json"),
                  json.dumps(RESULT, indent=1))
