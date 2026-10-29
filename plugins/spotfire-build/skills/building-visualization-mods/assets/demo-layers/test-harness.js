/*
 * Headless test of the demo-layers visualization mod.
 *
 * Loads src/index.html into jsdom, replaces the Spotfire mod API with a mock
 * (initialize, a reader over the layers, mod properties, render context,
 * error overlay) and runs src/main.js in the page. Then it renders synthetic
 * layers and checks what the mod draws and how it marks.
 *
 * Run: npm install, then npm test (or node test-harness.js).
 * The mock follows the API 2.4 typings (@spotfire/mods-api): a layer's
 * title() resolves to {value}, property(name) to an object with value(),
 * and dataView.allRows() resolves to null when the data view has expired.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const SRC = path.join(__dirname, "src");
let failures = 0;
function check(condition, message) {
    console.log((condition ? "  ok   " : "  FAIL ") + message);
    if (!condition) {
        failures++;
    }
}

// ------------------------------------------------------- synthetic data
// Two pumps, hourly, three days; the same shape as data/make_demo_csv.py.
const START = Date.UTC(2026, 0, 1);
function readingRows(asset) {
    const rows = [];
    for (let h = 0; h < 72; h++) {
        const t = new Date(START + h * 3600e3);
        const day = Math.sin(2 * Math.PI * h / 24);
        rows.push(seriesRow(t, "Pressure (psig)", 120 + 6 * day));
        rows.push(seriesRow(t, "Flow (bbl/d)", 2400 + 150 * day));
    }
    return rows;
}
function binnedRows() {
    const rows = [];
    for (let d = 0; d < 3; d++) {
        const t = new Date(START + d * 86400e3);
        rows.push(seriesRow(t, "Pressure min", 114 + d));
        rows.push(seriesRow(t, "Pressure max", 126 + d));
    }
    return rows;
}
function seriesRow(t, series, value) {
    return {
        continuous: (axis) => ({
            value: () => (axis === "X" ? t : value),
            formattedValue: () => String(axis === "X" ? t.toISOString() : value)
        }),
        categorical: () => ({ formattedValue: () => series }),
        isMarked: () => false,
        mark: () => {}
    };
}
const markCalls = [];
function eventRow(id, marked) {
    return {
        continuous: () => ({ value: () => 3, formattedValue: () => "3.0" }),
        categorical: (axis) => ({
            formattedValue: (sep) => (axis === "Key" ? id : ["Pump A", "2026-01-01 09:00", "2026-01-01 13:00"].join(sep || " "))
        }),
        isMarked: () => marked,
        mark: (mode) => markCalls.push([id, mode || "Replace"])
    };
}

// ------------------------------------------------------------ the mock
function dataView(rows, axes, marking) {
    return {
        getErrors: async () => [],
        allRows: async () => rows,
        marking: async () => marking,
        continuousAxis: async (name) => {
            if (!axes.includes(name)) throw new Error("no axis " + name);
            return { name };
        },
        categoricalAxis: async (name) => {
            if (!axes.includes(name)) throw new Error("no axis " + name);
            return { name };
        }
    };
}
function prop(value) {
    return { value: () => value, set: () => {} };
}
function layer(type, title, view, props) {
    return {
        type,
        data: () => Promise.resolve(view),
        title: () => Promise.resolve({ value: title }),
        property: (name) => Promise.resolve(prop(name in props ? props[name] : null))
    };
}
function standardLayers(options) {
    const o = options || {};
    return {
        items: [
            layer("Series", "Readings", dataView(readingRows("Pump A"), ["X", "Values", "Series"], null),
                { role: "raw", lineWidth: 1, visible: true }),
            layer("Series", "Daily range", dataView(binnedRows(), ["X", "Values", "Series", "Bin"], null),
                { role: "binned", lineWidth: null, visible: o.hideDaily ? false : true }),
            layer("Records", "Events", dataView([eventRow("E01", false), eventRow("E02", true), eventRow("E03", false)],
                ["Key", "Attributes", "Values"], { name: "Event Pick" }), { role: "events" })
        ]
    };
}

async function main() {
    const html = fs.readFileSync(path.join(SRC, "index.html"), "utf8");
    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
    const win = dom.window;
    const doc = win.document;

    let renderFn = null;
    let completed = 0;
    let waiter = null;
    const overlay = { shown: [], hidden: 0 };
    const context = {
        interactive: true,
        styling: { general: { backgroundColor: "#202124", font: { color: "#E8EAED", fontFamily: "Roboto" } } },
        signalRenderComplete: () => {
            completed++;
            if (waiter) {
                const w = waiter;
                waiter = null;
                w();
            }
        }
    };
    win.Spotfire = {
        initialize: (onLoaded) => onLoaded({
            visualization: { layers: () => "layers-proxy" },
            windowSize: () => "size-proxy",
            property: (name) => name,
            createReader: () => ({ subscribe: (fn) => { renderFn = fn; } }),
            getRenderContext: () => context,
            controls: {
                errorOverlay: {
                    show: (message) => overlay.shown.push(message),
                    hide: () => { overlay.hidden++; }
                }
            }
        })
    };
    win.eval(fs.readFileSync(path.join(SRC, "main.js"), "utf8"));
    check(typeof renderFn === "function", "the mod subscribes to a reader");

    const settings = { heading: "Pump readings", showGrid: true, lineWidth: 1.5, maxRows: 5000 };
    function render(layers, overrides) {
        const s = Object.assign({}, settings, overrides || {});
        return new Promise((resolve) => {
            waiter = resolve;
            renderFn(layers, { width: 800, height: 600 }, prop(s.heading), prop(s.showGrid),
                prop(s.lineWidth), prop(s.maxRows));
        });
    }

    console.log("render three layers");
    await render(standardLayers());
    const root = doc.getElementById("demo-root");
    check(root.querySelector(".demo-heading").textContent === "Pump readings", "heading from the mod property");
    const cards = [...root.querySelectorAll("section.demo-card")];
    check(cards.length === 3, "one card per layer (" + cards.length + ")");
    const titles = cards.map((c) => c.querySelector(".demo-card-title").textContent);
    check(titles.join("|") === "Readings|Daily range|Events", "layer titles in order: " + titles.join(", "));
    check(cards[0].querySelectorAll("polyline").length === 2, "Readings: one line per series");
    check(cards[0].querySelectorAll("line.demo-grid").length === 3, "grid lines when showGrid is true");
    check(cards[1].querySelectorAll("polyline").length === 2, "Daily range: min and max lines");
    check(cards[0].querySelector("polyline").getAttribute("stroke-width") === "1", "layer lineWidth wins over the visual's");
    check(cards[1].querySelector("polyline").getAttribute("stroke-width") === "1.5", "visual lineWidth when the layer sets none");
    const rows = [...cards[2].querySelectorAll("tr")];
    check(rows.length === 3, "Events: one row per record");
    check(rows[1].classList.contains("is-marked") && !rows[0].classList.contains("is-marked"), "marked record highlighted");
    check(cards[2].querySelector(".demo-meta").textContent.includes("1 marked (Event Pick)"), "marking name and count shown");
    check(root.style.getPropertyValue("--bg") === "#202124", "background from the Spotfire theme");
    check(completed === 1, "signalRenderComplete once per render");

    console.log("marking");
    rows[0].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    rows[2].dispatchEvent(new win.MouseEvent("click", { bubbles: true, ctrlKey: true }));
    check(JSON.stringify(markCalls) === JSON.stringify([["E01", "Replace"], ["E03", "Toggle"]]),
        "click replaces, Ctrl+click toggles: " + JSON.stringify(markCalls));

    console.log("hidden layer, grid off, row cap");
    await render(standardLayers({ hideDaily: true }), { showGrid: false, maxRows: 2 });
    const cards2 = [...root.querySelectorAll("section.demo-card")];
    check(cards2[1].textContent.includes("Hidden by the layer's settings"), "a layer with visible false draws no chart");
    check(cards2[0].querySelectorAll("line.demo-grid").length === 0, "no grid lines when showGrid is false");
    check(cards2[2].querySelectorAll("tr").length === 2, "maxRows caps the rows each card shows");

    console.log("expired data view");
    const expired = standardLayers();
    expired.items[0] = layer("Series", "Readings", Object.assign(dataView([], ["X"], null), { allRows: async () => null }), {});
    const before = root.innerHTML;
    await render(expired);
    check(root.innerHTML === before, "an expired data view keeps the cards on screen");
    check(completed === 3, "signalRenderComplete on the early return too");

    console.log("error path");
    const broken = standardLayers();
    broken.items[1] = { type: "Series", data: () => Promise.reject(new Error("view failed")),
        title: () => Promise.resolve({ value: "Broken" }), property: () => Promise.resolve(prop(null)) };
    await render(broken);
    check(overlay.shown.some((m) => m.includes("view failed")), "errors go to the error overlay");
    check(completed === 4, "signalRenderComplete after an error");

    console.log("export (not interactive)");
    context.interactive = false;
    await render(standardLayers());
    check(root.querySelectorAll("tr.is-clickable").length === 0, "no click targets when the view is not interactive");

    console.log("no layers");
    context.interactive = true;
    await render({ items: [] });
    check(root.textContent.includes("This visual has no layers."), "placeholder text without layers");

    console.log(failures ? "\n" + failures + " FAILED" : "\nALL CHECKS PASSED");
    process.exit(failures ? 1 : 0);
}

main().catch((e) => {
    console.error("FAILED:", e);
    process.exit(1);
});
