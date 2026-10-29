# Standard engine, feature part "pathfree": sbdf tables loaded
# without their folder, so the saved DXP keeps no local path. An
# embedded file table still persists its source's FilePath, and a stream
# source (SbdfFileDataSource(Stream)) persists the temp file it spools
# to instead (observed in Analyst 15.0; the table's data flow is
# replaced during the load by a clone of the connection's source, so
# setting FilePath after the load changes nothing). add_sbdf therefore
# opens the file by its bare name with the current folder set to the
# file's own folder: the DXP keeps "NAME.sbdf" (no drive, no user name;
# if the data is ever reloaded, Spotfire looks for that name next to the
# DXP). The folder is restored at once. Analyst loads SBDF out of process
# by default (DataImport_LoadOutOfProcess True): a new subprocess per
# load, started without a working directory, so it inherits the current
# folder and finds the bare name too (an impersonated server subprocess
# starts in its own folder and would not). When the load fails or gives
# no columns, the table is loaded from the full path as before, with a
# NOTE line. Another NOTE line names the source path the
# DXP keeps (read back through the table's source view). Included in
# every builder of an app with sbdf tables that uses any feature (apps
# without features keep their proven builders and the full path).
# Not yet tested: the by-name load in Analyst 15.0.
# @api SbdfFileDataSource.ctor(String); SbdfFileDataSource.IsPromptingAllowed
# @api DataTableCollection.Add(String, DataSource, Boolean)
# @api DataTableCollection.TryGetValue(String, out DataTable)
# @api DataTableCollection.Remove(DataTable); DataTable.Columns
# @api DataColumnCollection.Count; DataTable.RowCount
# @api DataTable.GenerateSourceView; SourceView.GetAllOperations
# @api Spotfire.Dxp.Data.DataOperations.DataSourceOperation.GetDataFlow
# @api DataFlow.DataSource; FileDataSource.FilePath
# @set SbdfFileDataSource.IsPromptingAllowed
from System.IO import Path, Directory
from Spotfire.Dxp.Data.Import import SbdfFileDataSource
from Spotfire.Dxp.Data.DataOperations import DataSourceOperation

# ------------------------------------------------ sbdf without a folder
def sbdf_source(path):
    ds = SbdfFileDataSource(path)
    ds.IsPromptingAllowed = False
    return ds


def add_by_name(name, path):
    """Tables.Add of the file opened by its bare name from its own
    folder (the current folder is restored whatever happens)."""
    old = Directory.GetCurrentDirectory()
    Directory.SetCurrentDirectory(Path.GetDirectoryName(path))
    try:
        t = Document.Data.Tables.Add(
            name, sbdf_source(Path.GetFileName(path)), True)
        rows = t.RowCount           # read while the folder is still set
        if t.Columns.Count == 0:
            raise Exception("no columns (" + str(rows) + " rows)")
        return t
    finally:
        Directory.SetCurrentDirectory(old)


def source_path(t):
    """The FilePath the DXP keeps for the table's data source."""
    view = t.GenerateSourceView()
    for op in view.GetAllOperations[DataSourceOperation]():
        return str(op.GetDataFlow().DataSource.FilePath)
    return "(no data source)"


def add_sbdf(name, path):
    """The table loaded by file name, else from the full path."""
    try:
        t = add_by_name(name, path)
    except Exception as e:
        found, old = Document.Data.Tables.TryGetValue(name)
        if found:
            Document.Data.Tables.Remove(old)
        LOG.append("NOTE " + name + ": loaded from the full path, which "
                   "the DXP keeps (by file name: " + why(e) + ")")
        return Document.Data.Tables.Add(name, sbdf_source(path), True)
    try:
        LOG.append("NOTE " + name + ": the DXP keeps the source path '"
                   + source_path(t) + "'")
    except Exception as e:
        LOG.append("NOTE " + name + ": loaded by file name; source path "
                   "not read back (" + why(e) + ")")
    return t
