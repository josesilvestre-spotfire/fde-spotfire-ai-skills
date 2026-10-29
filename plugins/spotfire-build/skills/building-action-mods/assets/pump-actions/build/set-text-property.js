// Pump Actions - script "set-text-property"
// Writes propertyValue into the String document property propertyName,
// only when the value changes. Use it for buttons that switch a view
// ("Daily", "Hourly") or send a command to a property trigger script: the
// trigger then runs once per real change.
// The property must exist; this script never creates properties.
// Plain JavaScript that Spotfire loads as is: one function registered with
// RegisterEntryPoint. The function must be synchronous.
"use strict";
(() => {
    const { DataProperty, DataPropertyClass } = Spotfire.Dxp.Data;

    /** @param {unknown} value */
    function text(value) {
        return value == null ? "" : String(value);
    }

    /**
     * @param {{document: Spotfire.Dxp.Application.Document,
     *     propertyName?: string, propertyValue?: string}} args
     */
    function setTextProperty({ document, propertyName, propertyValue }) {
        const name = text(propertyName).trim();
        if (name === "") {
            throw new Error("This button has no propertyName.");
        }
        const prop = OutParam.create(DataProperty);
        if (!document.Data.Properties.TryGetProperty(
            DataPropertyClass.Document, name, prop.out)) {
            throw new Error("There is no document property named " + name + ".");
        }
        const value = text(propertyValue);
        if (text(prop.value.Value) === value) {
            console.log("set-text-property: " + name + " already holds the value");
            return;
        }
        document.Properties.Set(name, value);
        console.log("set-text-property: " + name + " = " + value);
    }

    RegisterEntryPoint(setTextProperty);
})();
