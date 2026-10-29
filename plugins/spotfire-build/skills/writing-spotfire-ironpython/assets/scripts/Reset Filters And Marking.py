# Reset Filters And Marking
# Resets every filter of every filtering scheme and clears the marking given
# in the script parameter markingName (String, for example "Marking") in
# every data table. Leave markingName empty to reset only the filters.

from Spotfire.Dxp.Data import IndexSet, RowSelection

for scheme in Document.FilteringSchemes:
    scheme.ResetAllFilters()

name = (markingName or "").strip()
if name:
    found, marking = Document.Data.Markings.TryGetValue(name)
    if not found:
        Document.Properties["StatusMessage"] = "There is no marking named '%s'." % name
    else:
        for table in Document.Data.Tables:
            # An empty row selection of the table's size clears the marking.
            if not marking.GetSelection(table).AsIndexSet().IsEmpty:
                marking.SetSelection(
                    RowSelection(IndexSet(table.RowCount, False)), table)
