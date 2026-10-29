// A small mock of the globals Spotfire gives an action-mod script
// (apiVersion 2.5), with only the members the Pump Actions scripts use.
// It follows the real API where it matters for these scripts: out
// parameters through OutParam.create(Type) (.out is passed, .value is read),
// indexers as Get and Set methods, .NET collections iterable with for...of,
// and Set refusing a value of another type or an unknown property.
// The real API surface is checked by tsc (npm run check).
import vm from "node:vm";

class IndexSet {
    constructor(capacity, filled) {
        this.capacity = capacity;
        this.rows = filled === true ? [...Array(capacity).keys()] : [];
    }
    get IsEmpty() {
        return this.rows.length === 0;
    }
}

class RowSelection {
    constructor(indexSet) {
        this.indexSet = indexSet;
    }
    AsIndexSet() {
        return this.indexSet;
    }
}

const TOKENS = {
    DataProperty: { name: "DataProperty" },
    DataMarkingSelection: { name: "DataMarkingSelection" },
    Document: { name: "DataPropertyClass.Document" }
};

/**
 * A document from a plain description:
 * {properties: {name: [type, value]}, pages: [title], active: title,
 *  tables: {name: rowCount}, markings: {name: {table: [rows]}}}
 */
export function makeDocument(spec) {
    const writes = [];
    const properties = {};
    for (const [name, [type, value]] of Object.entries(spec.properties || {})) {
        properties[name] = { Name: name, DataType: type, Value: value };
    }
    const pages = (spec.pages || []).map((title) => ({ Title: title }));
    const tables = Object.entries(spec.tables || {}).map(([name, rows]) => ({ Name: name, RowCount: rows }));
    const markings = Object.entries(spec.markings || {}).map(([name, byTable]) => {
        const marked = Object.assign({}, byTable);
        return {
            Name: name,
            GetSelection: (table) => {
                const set = new IndexSet(table.RowCount, false);
                set.rows = (marked[table.Name] || []).slice();
                return new RowSelection(set);
            },
            SetSelection: (selection, table) => {
                if (!(selection instanceof RowSelection)) {
                    throw new Error("SetSelection needs a RowSelection");
                }
                marked[table.Name] = selection.AsIndexSet().rows.slice();
                writes.push(["marking", name, table.Name, marked[table.Name].length]);
            },
            marked
        };
    });
    let active = pages.find((p) => p.Title === spec.active) || pages[0] || null;

    const document = {
        Data: {
            Properties: {
                TryGetProperty: (cls, name, out) => {
                    if (cls !== TOKENS.Document) {
                        throw new Error("only document properties are mocked");
                    }
                    const found = Object.keys(properties).find((k) => k.toLowerCase() === name.toLowerCase());
                    if (!found) {
                        return false;
                    }
                    out.value = properties[found];
                    return true;
                }
            },
            Markings: Object.assign(markings, {
                TryGetValue: (name, out) => {
                    const m = markings.find((x) => x.Name === name);
                    if (!m) {
                        return false;
                    }
                    out.value = m;
                    return true;
                }
            }),
            Tables: tables
        },
        Properties: {
            Get: (name) => (properties[name] ? properties[name].Value : null),
            Set: (name, value) => {
                const prop = properties[name];
                if (!prop) {
                    throw new Error("Property not found: " + name);
                }
                if (prop.DataType === "String" && typeof value !== "string") {
                    throw new Error("Wrong type for " + name);
                }
                prop.Value = value;
                writes.push(["property", name, value]);
            }
        },
        Pages: pages,
        get ActivePageReference() {
            return active;
        },
        set ActivePageReference(page) {
            if (!pages.includes(page)) {
                throw new Error("not a page of this document");
            }
            active = page;
            writes.push(["page", page.Title]);
        }
    };
    return { document, writes, properties };
}

/** Runs one script file and returns its registered entry point. */
export function loadScript(code, filename) {
    const registered = [];
    const output = [];
    const context = vm.createContext({
        Spotfire: {
            Dxp: {
                Data: {
                    DataProperty: TOKENS.DataProperty,
                    DataPropertyClass: { Document: TOKENS.Document },
                    DataMarkingSelection: TOKENS.DataMarkingSelection,
                    IndexSet,
                    RowSelection
                }
            }
        },
        OutParam: {
            create: (type) => {
                const holder = { type, value: null };
                holder.out = holder;
                return holder;
            }
        },
        RegisterEntryPoint: (fn) => registered.push(fn),
        console: { log: (...parts) => output.push(parts.join(" ")) }
    });
    vm.runInContext(code, context, { filename });
    return { registered, output };
}
