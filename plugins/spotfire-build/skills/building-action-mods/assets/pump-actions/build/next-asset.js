// Pump Actions - script "next-asset"
// Shows the next pump: reads the document property ViewAsset, finds it in
// the parameter assets (a comma-separated list such as "Pump A,Pump B") and
// writes the pump after it, wrapping around at the end. When ViewAsset is
// not in the list, the first pump is written. Visuals that filter on
// ${ViewAsset} follow.
// Plain JavaScript that Spotfire loads as is: one function registered with
// RegisterEntryPoint. The function must be synchronous.
"use strict";
(() => {
    const { DataProperty, DataPropertyClass } = Spotfire.Dxp.Data;
    const VIEW_PROP = "ViewAsset";

    /** @param {unknown} value */
    function text(value) {
        return value == null ? "" : String(value);
    }

    /**
     * The value of a document property as text, or null when it is missing.
     * @param {Spotfire.Dxp.Application.Document} document
     * @param {string} name
     */
    function readText(document, name) {
        const prop = OutParam.create(DataProperty);
        if (!document.Data.Properties.TryGetProperty(
            DataPropertyClass.Document, name, prop.out)) {
            return null;
        }
        return text(prop.value.Value);
    }

    /**
     * @param {{document: Spotfire.Dxp.Application.Document,
     *     assets?: string}} args
     */
    function nextAsset({ document, assets }) {
        const list = text(assets).split(",").map((s) => s.trim())
            .filter((s) => s.length > 0);
        if (list.length === 0) {
            console.log("next-asset: the button has no pumps in assets");
            return;
        }
        const current = readText(document, VIEW_PROP);
        if (current === null) {
            throw new Error("The document property " + VIEW_PROP
                + " is missing.");
        }
        const next = list[(list.indexOf(current.trim()) + 1) % list.length];
        if (next !== current) {
            document.Properties.Set(VIEW_PROP, next);
        }
        console.log("next-asset: " + VIEW_PROP + " " + (current || "(empty)")
            + " -> " + next);
    }

    RegisterEntryPoint(nextAsset);
})();
