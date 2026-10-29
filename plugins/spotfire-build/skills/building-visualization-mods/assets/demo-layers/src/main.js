/*
 * Layer demo: one card for each layer of this visual.
 *
 * A card shows the layer's title and type, its row count, how many of its
 * rows are marked and with which marking, and the layer's own settings.
 * Series layers draw their values over time as lines, one line per name on
 * the "Split by" axis. The lines share one vertical range unless their
 * values are far apart (the range of all values is more than five times the
 * widest line's own range); then each line gets its own range, so values of
 * different sizes keep their shape. Records layers list their rows; a click
 * on a row marks it, Ctrl+click adds it to the marking or removes it.
 *
 * Settings of the visual: heading (the text above the cards), showGrid
 * (grid lines in the line charts), lineWidth (the line width of a layer
 * that sets none) and maxRows (the rows each card shows at most).
 */
(function () {
    "use strict";

    var SVG_NS = "http://www.w3.org/2000/svg";
    var COLORS = ["#3050EF", "#E94165", "#0EA053", "#F5A623", "#7E57C2"];
    var LAYER_PROPS = { Series: ["role", "lineWidth", "visible"], Records: ["role"] };
    var root = document.getElementById("demo-root");

    Spotfire.initialize(function (mod) {
        var reader = mod.createReader(mod.visualization.layers(), mod.windowSize(),
            mod.property("heading"), mod.property("showGrid"),
            mod.property("lineWidth"), mod.property("maxRows"));
        reader.subscribe(function (layers, size, heading, grid, width, maxRows) {
            var context = mod.getRenderContext();
            var settings = {
                heading: valueOf(heading, "Layers"),
                grid: valueOf(grid, false) === true,
                width: Number(valueOf(width, 1)) || 1,
                maxRows: Math.max(1, Number(valueOf(maxRows, 1000)) || 1000)
            };
            render(mod, context, layers, settings).catch(function (e) {
                mod.controls.errorOverlay.show("The layers could not be shown: " + message(e), "render");
            }).then(function () {
                context.signalRenderComplete();
            });
        });
    });

    /** Draws every card; keeps the old cards while newer data is on its way. */
    async function render(mod, context, layers, settings) {
        mod.controls.errorOverlay.hide("render");
        applyTheme(context.styling);
        var items = (layers && layers.items) || [];
        var cards = [];
        for (var i = 0; i < items.length; i++) {
            var card = await layerCard(items[i], settings, context.interactive !== false);
            if (card === null) {
                return;
            }
            cards.push(card);
        }
        root.textContent = "";
        root.appendChild(el("h1", "demo-heading", settings.heading));
        if (!cards.length) {
            root.appendChild(el("p", "demo-empty", "This visual has no layers."));
        }
        cards.forEach(function (c) { root.appendChild(c); });
    }

    async function layerCard(layer, settings, interactive) {
        var names = LAYER_PROPS[layer.type] || [];
        var reads = [layer.data(), layer.title()].concat(names.map(function (n) {
            return layer.property(n);
        }));
        var parts = await Promise.all(reads);
        var dataView = parts[0];
        var title = parts[1] && parts[1].value ? String(parts[1].value) : layer.type;
        var props = {};
        names.forEach(function (n, k) { props[n] = valueOf(parts[2 + k], null); });

        var card = el("section", "demo-card");
        var head = el("div", "demo-card-head");
        head.appendChild(el("span", "demo-card-title", title));
        head.appendChild(el("span", "demo-badge", layer.type));
        card.appendChild(head);
        var errors = await dataView.getErrors();
        if (errors.length) {
            card.appendChild(el("p", "demo-error", errors.join(" ")));
            return card;
        }
        var rows = await dataView.allRows();
        if (rows === null) {
            return null;
        }
        var marking = await dataView.marking();
        var marked = rows.filter(function (r) { return r.isMarked(); }).length;
        card.appendChild(el("div", "demo-meta", rows.length + " rows, " + marked + " marked" +
            (marking ? " (" + marking.name + ")" : ", cannot be marked") + " | " + describe(props)));
        rows = rows.slice(0, settings.maxRows);
        if (layer.type === "Series") {
            if (props.visible === false) {
                card.appendChild(el("p", "demo-note", "Hidden by the layer's settings."));
            } else {
                card.appendChild(await lineChart(dataView, rows, props.lineWidth || settings.width, settings.grid));
            }
        } else {
            card.appendChild(await recordList(dataView, rows, interactive));
        }
        return card;
    }

    async function lineChart(dataView, rows, width, grid) {
        var split = await hasAxis(dataView, "Series", true);
        var series = {};
        var order = [];
        rows.forEach(function (row) {
            var x = row.continuous("X").value();
            var t = x instanceof Date ? x.getTime() : Number(x);
            var y = Number(row.continuous("Values").value());
            if (!isFinite(t) || !isFinite(y)) {
                return;
            }
            var name = split ? row.categorical("Series").formattedValue() : "Values";
            if (!series[name]) {
                series[name] = [];
                order.push(name);
            }
            series[name].push([t, y]);
        });
        var all = [].concat.apply([], order.map(function (n) { return series[n]; }));
        var box = el("div", "demo-chart-box");
        if (!all.length) {
            box.appendChild(el("p", "demo-note", "No values to draw."));
            return box;
        }
        var x0 = Math.min.apply(null, all.map(function (p) { return p[0]; }));
        var x1 = Math.max.apply(null, all.map(function (p) { return p[0]; }));
        var svg = svgEl("svg", { "class": "demo-chart", viewBox: "0 0 300 100", preserveAspectRatio: "none" });
        if (grid) {
            [25, 50, 75].forEach(function (y) {
                svg.appendChild(svgEl("line", { "class": "demo-grid", x1: 0, x2: 300, y1: y, y2: y,
                    "vector-effect": "non-scaling-stroke" }));
            });
        }
        var ranges = order.map(function (name) {
            var ys = series[name].map(function (p) { return p[1]; });
            return [Math.min.apply(null, ys), Math.max.apply(null, ys)];
        });
        var low = Math.min.apply(null, ranges.map(function (r) { return r[0]; }));
        var high = Math.max.apply(null, ranges.map(function (r) { return r[1]; }));
        var widest = Math.max.apply(null, ranges.map(function (r) { return r[1] - r[0]; }));
        var own = widest > 0 && high - low > 5 * widest;
        var legend = el("div", "demo-legend");
        order.forEach(function (name, k) {
            var color = COLORS[k % COLORS.length];
            var y0 = own ? ranges[k][0] : low;
            var y1 = own ? ranges[k][1] : high;
            var points = series[name].sort(function (a, b) { return a[0] - b[0]; }).map(function (p) {
                var px = x1 > x0 ? (p[0] - x0) / (x1 - x0) * 300 : 150;
                var py = y1 > y0 ? 96 - (p[1] - y0) / (y1 - y0) * 92 : 50;
                return px.toFixed(1) + "," + py.toFixed(1);
            });
            svg.appendChild(svgEl("polyline", { points: points.join(" "), fill: "none", stroke: color,
                "stroke-width": width, "vector-effect": "non-scaling-stroke" }));
            var item = el("span", "", name);
            var swatch = el("span", "demo-swatch", "");
            swatch.style.background = color;
            item.insertBefore(swatch, item.firstChild);
            legend.appendChild(item);
        });
        box.appendChild(svg);
        box.appendChild(legend);
        return box;
    }

    async function recordList(dataView, rows, interactive) {
        var key = await hasAxis(dataView, "Key", true);
        var attributes = await hasAxis(dataView, "Attributes", true);
        var values = await hasAxis(dataView, "Values", false);
        var table = el("table", "demo-records");
        rows.forEach(function (row) {
            var tr = el("tr", (row.isMarked() ? "is-marked " : "") + (interactive ? "is-clickable" : ""));
            tr.appendChild(el("td", "", key ? row.categorical("Key").formattedValue() : ""));
            tr.appendChild(el("td", "", attributes ? row.categorical("Attributes").formattedValue(" | ") : ""));
            tr.appendChild(el("td", "", values ? row.continuous("Values").formattedValue() : ""));
            if (interactive) {
                tr.addEventListener("click", function (e) {
                    row.mark(e.ctrlKey ? "Toggle" : "Replace");
                });
            }
            table.appendChild(tr);
        });
        return table;
    }

    /** True when the axis exists and has an expression. */
    async function hasAxis(dataView, name, categorical) {
        try {
            var axis = categorical ? await dataView.categoricalAxis(name) : await dataView.continuousAxis(name);
            return !!axis;
        } catch (e) {
            return false;
        }
    }

    function applyTheme(styling) {
        var general = (styling && styling.general) || {};
        var font = general.font || {};
        if (font.color) {
            root.style.setProperty("--fg", font.color);
        }
        if (general.backgroundColor) {
            root.style.setProperty("--bg", general.backgroundColor);
        }
        if (font.fontFamily) {
            root.style.fontFamily = font.fontFamily;
        }
    }

    function describe(props) {
        var parts = Object.keys(props).map(function (n) { return n + " " + props[n]; });
        return parts.length ? parts.join(", ") : "no layer settings";
    }

    function valueOf(property, fallback) {
        try {
            var v = property ? property.value() : null;
            return v === null || v === undefined ? fallback : v;
        } catch (e) {
            return fallback;
        }
    }

    function message(e) {
        return e && e.message ? e.message : String(e);
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) {
            node.className = cls.trim();
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        return node;
    }

    function svgEl(tag, attrs) {
        var node = document.createElementNS(SVG_NS, tag);
        Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        return node;
    }
})();
