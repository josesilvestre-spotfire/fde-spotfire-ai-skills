// Pump Actions - script "clear-marking"
// Clears markings in every data table. Parameter markingNames: one marking
// name or several separated by commas, for example "Marking, Event Pick".
// Names match exactly first, then without regard to case and outer spaces.
// A name with no marking is reported in the script output; the other
// markings are still cleared.
// Plain JavaScript that Spotfire loads as is: one function registered with
// RegisterEntryPoint. The function must be synchronous.
"use strict";
(() => {
    const { DataMarkingSelection, IndexSet, RowSelection } = Spotfire.Dxp.Data;

    /** @param {unknown} value */
    function text(value) {
        return value == null ? "" : String(value);
    }

    /**
     * The marking with this name, or null.
     * @param {Spotfire.Dxp.Application.Document} document
     * @param {string} name
     */
    function findMarking(document, name) {
        const out = OutParam.create(DataMarkingSelection);
        if (document.Data.Markings.TryGetValue(name, out.out)) {
            return out.value;
        }
        const wanted = name.trim().toLowerCase();
        for (const marking of document.Data.Markings) {
            if (text(marking.Name).trim().toLowerCase() === wanted) {
                return marking;
            }
        }
        return null;
    }

    /**
     * @param {{document: Spotfire.Dxp.Application.Document,
     *     markingNames?: string}} args
     */
    function clearMarking({ document, markingNames }) {
        const names = text(markingNames).split(",").map((s) => s.trim())
            .filter((s) => s.length > 0);
        const missing = [];
        let cleared = 0;
        for (const name of names) {
            const marking = findMarking(document, name);
            if (marking == null) {
                missing.push(name);
                continue;
            }
            for (const table of document.Data.Tables) {
                if (!marking.GetSelection(table).AsIndexSet().IsEmpty) {
                    // An empty row selection of the table's size clears it.
                    marking.SetSelection(
                        new RowSelection(new IndexSet(table.RowCount, false)),
                        table);
                    cleared++;
                }
            }
        }
        console.log("clear-marking: cleared " + cleared + " table selection(s)"
            + (missing.length ? "; no marking named " + missing.join(", ") : ""));
    }

    RegisterEntryPoint(clearMarking);
})();
