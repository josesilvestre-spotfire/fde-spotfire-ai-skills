// Scenarios for the Pump Actions scripts against the mock in mock.mjs.
// Run: node tests/run.mjs (no packages needed). Ends with
// "ALL SCENARIOS PASSED" or exits with code 1.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadScript, makeDocument } from "./mock.mjs";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "mod-manifest.json"), "utf8"));
let failures = 0;

function check(condition, message) {
    console.log((condition ? "  ok   " : "  FAIL ") + message);
    if (!condition) {
        failures++;
    }
}

function entry(scriptId) {
    const script = manifest.scripts.find((s) => s.id === scriptId);
    const code = fs.readFileSync(path.join(ROOT, script.file), "utf8");
    const loaded = loadScript(code, script.file);
    check(loaded.registered.length === 1 && loaded.registered[0].name === script.entryPoint,
        scriptId + ": registers exactly its entry point " + script.entryPoint);
    const fn = loaded.registered[0];
    return (args) => {
        const result = fn(args);
        check(result === undefined || typeof result.then !== "function", scriptId + ": runs synchronously");
        return loaded.output;
    };
}

function throws(fn) {
    try {
        fn();
        return false;
    } catch (e) {
        return true;
    }
}

console.log("manifest");
for (const script of manifest.scripts) {
    check(fs.existsSync(path.join(ROOT, script.file)), script.id + ": file " + script.file);
    check(fs.existsSync(path.join(ROOT, script.icon)), script.id + ": icon " + script.icon);
}

console.log("next-asset");
{
    const run = entry("next-asset");
    const { document, writes, properties } = makeDocument({ properties: { ViewAsset: ["String", "Pump A"] } });
    run({ document, assets: "Pump A, Pump B" });
    check(properties.ViewAsset.Value === "Pump B", "Pump A -> Pump B");
    run({ document, assets: "Pump A, Pump B" });
    check(properties.ViewAsset.Value === "Pump A", "wraps around to Pump A");
    properties.ViewAsset.Value = "Pump X";
    run({ document, assets: "Pump A,Pump B" });
    check(properties.ViewAsset.Value === "Pump A", "unknown current value -> first pump");
    const before = writes.length;
    run({ document, assets: "" });
    check(writes.length === before, "empty assets writes nothing");
    const bare = makeDocument({ properties: {} });
    check(throws(() => run({ document: bare.document, assets: "Pump A" })), "missing ViewAsset raises an error");
}

console.log("go-to-page");
{
    const run = entry("go-to-page");
    const { document, writes, properties } = makeDocument({
        properties: { StatusMessage: ["String", ""] },
        pages: ["Pump Overview", "Pump Detail"], active: "Pump Overview" });
    run({ document, pageTitle: " pump detail " });
    check(document.ActivePageReference.Title === "Pump Detail", "title matched without case and outer spaces");
    run({ document, pageTitle: "Pump Detail" });
    check(writes.filter((w) => w[0] === "page").length === 1, "no change when the page is already shown");
    run({ document, pageTitle: "Nope" });
    check(document.ActivePageReference.Title === "Pump Detail", "unknown title keeps the page");
    check(properties.StatusMessage.Value.includes("Pump Overview, Pump Detail"), "StatusMessage lists the pages");
    const quiet = makeDocument({ pages: ["Only"] });
    run({ document: quiet.document, pageTitle: "" });
    check(quiet.writes.length === 0, "empty pageTitle without StatusMessage writes nothing");
}

console.log("clear-marking");
{
    const run = entry("clear-marking");
    const { document, writes } = makeDocument({
        tables: { PUMP_READINGS: 144, PUMP_EVENTS: 6 },
        markings: { "Marking": { PUMP_READINGS: [1, 2, 3] }, "Event Pick": { PUMP_EVENTS: [0] } } });
    const output = run({ document, markingNames: "marking, Event Pick, Missing" });
    const cleared = writes.filter((w) => w[0] === "marking");
    check(cleared.length === 2 && cleared.every((w) => w[3] === 0), "both markings cleared in their tables");
    check(output.some((line) => line.includes("no marking named Missing")), "unknown marking reported");
    run({ document, markingNames: "Marking" });
    check(writes.filter((w) => w[0] === "marking").length === 2, "nothing written when nothing is marked");
}

console.log("set-text-property");
{
    const run = entry("set-text-property");
    const { document, writes, properties } = makeDocument({ properties: { ViewMode: ["String", "Hourly"] } });
    run({ document, propertyName: "ViewMode", propertyValue: "Daily" });
    check(properties.ViewMode.Value === "Daily", "value written");
    run({ document, propertyName: "ViewMode", propertyValue: "Daily" });
    check(writes.length === 1, "same value: no second write, so its trigger runs once");
    check(throws(() => run({ document, propertyName: "Missing", propertyValue: "x" })), "unknown property raises an error");
    check(throws(() => run({ document, propertyName: " ", propertyValue: "x" })), "empty propertyName raises an error");
}

console.log(failures ? "\n" + failures + " FAILED" : "\nALL SCENARIOS PASSED");
process.exit(failures ? 1 : 0);
