# export_tables_job.py: IronPython 3 job script that writes data tables of a saved
# analysis to CSV files, for the reconciliation of a workbook-based app
# against the workbook's values. Public Spotfire API only.
#
# Run it with the running-spotfire-unattended skill:
#   python <runner skill>/scripts/sfrun.py job scripts/export_tables_job.py
#       --set source=<app>/build/<name> standard.dxp
#       --set tables=PRESSURE_PROFILE,SEGMENT_RESULTS
# It opens the analysis (it saves nothing), and writes one UTF-8 CSV per table,
# <TABLE>.csv, into the job folder (JOB["jobDir"]), plus export_tables.json
# with the row and column counts. "tables" is a comma-separated list; leave it
# out to export every table.
# Status: **Not yet tested** in Analyst.
# @api AnalysisApplication.Open(String); AnalysisApplication.Document
# @api DataManager.CreateDataWriter(TypeIdentifier)
# @api DataWriterTypeIdentifiers.SpreadsheetDataCsvUtf8Writer
# @api DataWriter.Write(Stream, DataTable, IEnumerable<Int32>, IEnumerable<String>)
import json
from System.IO import File, FileMode, FileStream, Path
from System.Collections.Generic import List
from Spotfire.Dxp.Data.Export import DataWriterTypeIdentifiers


def export_table(doc, table, folder):
    """One table to <folder>/<TABLE>.csv; returns (rows, columns)."""
    writer = doc.Data.CreateDataWriter(
        DataWriterTypeIdentifiers.SpreadsheetDataCsvUtf8Writer)
    rows = List[int]()
    for i in range(table.RowCount):
        rows.Add(i)
    names = List[str]()
    for column in table.Columns:
        names.Add(column.Name)
    target = Path.Combine(folder, table.Name + ".csv")
    stream = FileStream(target, FileMode.Create)
    try:
        writer.Write(stream, table, rows, names)
    finally:
        stream.Close()
    return table.RowCount, names.Count


Application.Open(JOB["source"])
DOC = Application.Document
WANTED = [x.strip() for x in str(JOB.get("tables") or "").split(",")
          if x.strip()]
DONE = {}
for t in DOC.Data.Tables:
    if WANTED and t.Name not in WANTED:
        continue
    n_rows, n_cols = export_table(DOC, t, JOB["jobDir"])
    DONE[t.Name] = {"rows": n_rows, "columns": n_cols}
MISSING = [name for name in WANTED if name not in DONE]
File.WriteAllText(Path.Combine(JOB["jobDir"], "export_tables.json"),
                  json.dumps({"exported": DONE, "missing": MISSING},
                             indent=1, sort_keys=True))
if MISSING:
    raise Exception("tables not in the analysis: " + ", ".join(MISSING))
