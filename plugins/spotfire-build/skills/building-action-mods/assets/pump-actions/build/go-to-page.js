// Pump Actions - script "go-to-page"
// Opens a page. Parameter pageTitle: the page title, matched exactly first,
// then without regard to case and outer spaces. When there is no such page,
// the document property StatusMessage (when it exists) lists the pages and
// the page shown stays.
// Plain JavaScript that Spotfire loads as is: one function registered with
// RegisterEntryPoint. The function must be synchronous.
"use strict";
(() => {
    const { DataProperty, DataPropertyClass } = Spotfire.Dxp.Data;
    const MESSAGE_PROP = "StatusMessage";

    /** @param {unknown} value */
    function text(value) {
        return value == null ? "" : String(value);
    }

    /**
     * Shows a message in StatusMessage when the analysis has it, and in the
     * script output.
     * @param {Spotfire.Dxp.Application.Document} document
     * @param {string} message
     */
    function say(document, message) {
        console.log("go-to-page: " + message);
        const prop = OutParam.create(DataProperty);
        if (document.Data.Properties.TryGetProperty(
            DataPropertyClass.Document, MESSAGE_PROP, prop.out)) {
            document.Properties.Set(MESSAGE_PROP, message);
        }
    }

    /**
     * @param {{document: Spotfire.Dxp.Application.Document,
     *     pageTitle?: string}} args
     */
    function goToPage({ document, pageTitle }) {
        const wanted = text(pageTitle).trim();
        if (wanted === "") {
            say(document, "This button has no page to open. Set its pageTitle.");
            return;
        }
        /** @type {Spotfire.Dxp.Application.Page | null} */
        let target = null;
        /** @type {Spotfire.Dxp.Application.Page | null} */
        let loose = null;
        const titles = [];
        for (const page of document.Pages) {
            const title = text(page.Title);
            titles.push(title);
            if (title === wanted && target == null) {
                target = page;
            }
            if (loose == null && title.trim().toLowerCase() === wanted.toLowerCase()) {
                loose = page;
            }
        }
        target = target || loose;
        if (target == null) {
            say(document, "There is no page named '" + wanted
                + "'. The pages are: " + titles.join(", ") + ".");
            return;
        }
        const shown = document.ActivePageReference;
        if (shown == null || text(shown.Title) !== text(target.Title)) {
            document.ActivePageReference = target;
        }
    }

    RegisterEntryPoint(goToPage);
})();
