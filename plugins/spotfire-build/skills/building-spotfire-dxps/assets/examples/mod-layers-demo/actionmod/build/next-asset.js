// Layer Demo Actions - script "next-asset"
// Shows the next asset in the layers of the demo visual: reads the
// document property ViewAsset, finds it in Assets (a comma-separated list
// such as "Pump A,Pump B") and writes the asset after it, wrapping around
// at the end. When ViewAsset is not in the list, the first asset is
// written. The layers filter on ViewAsset, so they all follow.
// Parameter: Assets (String).
// Plain JavaScript loaded by Spotfire as is: one function registered with
// RegisterEntryPoint.
"use strict";
(() => {
    const { DataProperty, DataPropertyClass } = Spotfire.Dxp.Data;
    const VIEW_PROP = "ViewAsset";

    /** @param {unknown} value */
    function text(value) {
        return value == null ? "" : String(value);
    }

    /**
     * Value of a document property as text; "" when it is missing.
     * @param {Spotfire.Dxp.Application.Document} document
     * @param {string} name
     */
    function getProp(document, name) {
        const prop = OutParam.create(DataProperty);
        const found = document.Data.Properties.TryGetProperty(
            DataPropertyClass.Document, name, prop.out);
        return found ? text(prop.value.Value) : "";
    }

    /**
     * @param {{document: Spotfire.Dxp.Application.Document,
     *     Assets?: string}} args
     */
    function nextAsset({ document, Assets }) {
        const list = text(Assets).split(",").map((s) => s.trim())
            .filter((s) => s.length > 0);
        if (list.length === 0) {
            console.log("next-asset: Assets is empty, nothing changed");
            return;
        }
        const current = getProp(document, VIEW_PROP).trim();
        const at = list.indexOf(current);
        const next = list[(at + 1) % list.length];
        if (next !== current) {
            document.Properties.Set(VIEW_PROP, next);
        }
        console.log("next-asset: " + VIEW_PROP + " " + (current || "(empty)")
            + " -> " + next);
    }

    RegisterEntryPoint(nextAsset);
})();
