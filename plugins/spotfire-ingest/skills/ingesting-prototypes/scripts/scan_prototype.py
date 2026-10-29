"""Inventory the elements of an app prototype before it is mapped to Spotfire.

Scans a file or a folder holding a Shiny for Python (Core or Express), Streamlit, Dash,
Plotly, Quarto, plain HTML or React prototype and lists what a Spotfire analysis has to
reproduce: pages and tabs, layout containers, inputs, outputs, reactivity, data loads and
styling hints. Each element gets a suggested Spotfire element and fidelity where the mapping
is mechanical, and a gap ID (G1 to G13 of the mapping reference) where Spotfire has no direct
equivalent. Elements the scanner cannot resolve are marked "?" for you to read in the code.

The inventory is a starting point for the mapping table. It does not run the prototype and
it does not replace reading the code.

Usage:
    python scan_prototype.py <file or folder> --out <ingest folder>

Writes prototype-inventory.md and prototype-inventory.json into the output folder.
Standard library only.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "dist",
             "build", ".quarto", "_site", "site-packages", "_smoke"}
EXTENSIONS = {".py": "python", ".qmd": "quarto", ".html": "html", ".htm": "html",
              ".jsx": "react", ".tsx": "react", ".js": "script", ".ts": "script"}

GAPS = {
    "G1": "shaded X bands (vrect, ReferenceArea, Gantt)",
    "G2": "filled ribbons and areas",
    "G3": "dashed or dotted data series",
    "G4": "zoom events and range sliders on charts",
    "G5": "in-memory models and objects",
    "G6": "markdown or text with inline live values",
    "G7": "light page with dark plots, or the reverse",
    "G8": "progress bars and spinners",
    "G9": "horizontal-only box select",
    "G10": "date sliders and range sliders",
    "G11": "file upload, in-page tabs, popovers, hover cards, timers",
    "G12": "Python packages missing from Spotfire's Python",
    "G13": "charts with no native type",
}

# Normalized input kind -> (Spotfire control, fidelity, gap)
INPUT_MAP = {
    "select": ("`dropdown` control", "EXACT", ""),
    "multiselect": ("`multiSelectListbox` control", "CLOSE", ""),
    "slider": ("`slider` control", "EXACT", ""),
    "range_slider": ("two `slider` or `input` controls, or a range filter on the column",
                     "SUBSTITUTE", "G10"),
    "date_slider": ("`input` control, or a range filter on the time column",
                    "SUBSTITUTE", "G10"),
    "date": ("`input` control on a Date property", "EXACT", ""),
    "date_range": ("two `input` controls, or a range filter on the time column",
                   "SUBSTITUTE", "G10"),
    "numeric": ("`input` control", "EXACT", ""),
    "text": ("`input` control", "EXACT", ""),
    "radio": ("`radio` (single-select list box) or `dropdown`", "SUBSTITUTE", ""),
    "checkbox": ("`checkbox` control (a Yes/No drop-down)", "SUBSTITUTE", ""),
    "button": ("`button` (refreshDataFunction action or script)", "EXACT", ""),
    "link": ("`link` with a gotoPage action", "EXACT", ""),
    "file": ("none: data enters at build time", "MANUAL", "G11"),
    "download": ("Spotfire's own export, no control", "SUBSTITUTE", ""),
    "theme": ("`app.theme.base`, drop the control", "SUBSTITUTE", "G7"),
    "control_placeholder": ("text-area control (kind from the annotation)", "EXACT", ""),
    "state": ("document property or marking", "?", ""),
}

# Chart kind -> (draft visual, fidelity, gap)
CHART_MAP = {
    "line": ("`lineChart`", "EXACT", ""),
    "scatter": ("`scatterPlot`", "EXACT", ""),
    "bar": ("`barChart`", "EXACT", ""),
    "histogram": ("`barChart` on a binned x, or a data function that writes the bins",
                  "SUBSTITUTE", ""),
    "box": ("data function quartiles drawn as `barChart` or `table`", "SUBSTITUTE", ""),
    "violin": ("data function quartiles drawn as `barChart` or `table`", "SUBSTITUTE", ""),
    "heatmap": ("`crossTable` with a gradient coloring", "SUBSTITUTE", ""),
    "imshow": ("`crossTable` with a gradient coloring", "SUBSTITUTE", ""),
    "density_heatmap": ("`crossTable` with a gradient coloring", "SUBSTITUTE", ""),
    "pie": ("horizontal sorted `barChart`", "SUBSTITUTE", ""),
    "treemap": ("horizontal sorted `barChart` or `crossTable`", "SUBSTITUTE", ""),
    "sunburst": ("horizontal sorted `barChart` or `crossTable`", "SUBSTITUTE", ""),
    "icicle": ("horizontal sorted `barChart` or `crossTable`", "SUBSTITUTE", ""),
    "funnel": ("horizontal `barChart` sorted descending", "SUBSTITUTE", ""),
    "waterfall": ("data function steps drawn as `barChart`", "SUBSTITUTE", ""),
    "area": ("both edges as same-color series (a band layer is slim tier)", "SUBSTITUTE", "G2"),
    "indicator": ("HTML KPI band", "CLOSE", ""),
    "value_box": ("HTML KPI band", "CLOSE", ""),
    "metric": ("HTML KPI band", "CLOSE", ""),
    "table": ("`table`", "EXACT", ""),
    "map": ("`map` with tile and marker layers", "EXACT", ""),
    "choropleth": ("`map` feature layer", "CLOSE", ""),
    "density_map": ("`map` marker layer colored by value", "SUBSTITUTE", ""),
    "scatter_3d": ("`scatterPlot` colored by the third dimension", "SUBSTITUTE", ""),
    "surface": ("gridded `crossTable`", "SUBSTITUTE", ""),
    "contour": ("data function contour lines", "SUBSTITUTE", ""),
    "timeline": ("line colored by state (X bands are slim tier)", "SUBSTITUTE", "G1"),
    "sankey": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "parallel": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "candlestick": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "ohlc": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "polar": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "radar": ("visualization mod or native approximation", "SUBSTITUTE", "G13"),
    "picture": ("rebuilt natively from the same data", "SUBSTITUTE", ""),
    "chart": ("visual type from the figure code", "?", ""),
}

PX_KINDS = {"line": "line", "scatter": "scatter", "bar": "bar", "histogram": "histogram",
            "box": "box", "violin": "violin", "imshow": "imshow", "pie": "pie",
            "treemap": "treemap", "sunburst": "sunburst", "icicle": "icicle",
            "funnel": "funnel", "area": "area", "density_heatmap": "density_heatmap",
            "scatter_mapbox": "map", "scatter_map": "map", "scatter_geo": "map",
            "line_mapbox": "map", "line_map": "map", "choropleth": "choropleth",
            "choropleth_mapbox": "choropleth", "choropleth_map": "choropleth",
            "density_mapbox": "density_map", "density_map": "density_map",
            "scatter_3d": "scatter_3d", "timeline": "timeline",
            "parallel_coordinates": "parallel", "line_polar": "polar",
            "scatter_polar": "polar", "bar_polar": "polar", "strip": "scatter",
            "ecdf": "line", "scatter_matrix": "scatter"}
GO_KINDS = {"Scatter": "scatter", "Scattergl": "scatter", "Bar": "bar",
            "Histogram": "histogram", "Box": "box", "Violin": "violin",
            "Heatmap": "heatmap", "Pie": "pie", "Treemap": "treemap",
            "Sunburst": "sunburst", "Icicle": "icicle", "Funnel": "funnel",
            "Waterfall": "waterfall", "Indicator": "indicator", "Table": "table",
            "Scattermapbox": "map", "Scattermap": "map", "Scattergeo": "map",
            "Choropleth": "choropleth", "Choroplethmapbox": "choropleth",
            "Densitymapbox": "density_map", "Scatter3d": "scatter_3d",
            "Surface": "surface", "Contour": "contour", "Sankey": "sankey",
            "Parcoords": "parallel", "Candlestick": "candlestick", "Ohlc": "ohlc",
            "Scatterpolar": "polar", "Barpolar": "polar"}

SHINY_INPUTS = {"select": "select", "selectize": "select", "slider": "slider",
                "numeric": "numeric", "text": "text", "text_area": "text",
                "password": "text", "radio_buttons": "radio", "checkbox": "checkbox",
                "switch": "checkbox", "checkbox_group": "multiselect",
                "action_button": "button", "task_button": "button",
                "action_link": "link", "file": "file", "date": "date",
                "date_range": "date_range", "dark_mode": "theme"}
ST_INPUTS = {"selectbox": "select", "multiselect": "multiselect", "slider": "slider",
             "select_slider": "select", "number_input": "numeric",
             "text_input": "text", "text_area": "text", "radio": "radio",
             "checkbox": "checkbox", "toggle": "checkbox", "date_input": "date",
             "time_input": "text", "button": "button", "form_submit_button": "button",
             "file_uploader": "file", "download_button": "download",
             "color_picker": "text", "pills": "select", "segmented_control": "radio"}
ST_CHARTS = {"plotly_chart": "chart", "altair_chart": "chart", "vega_lite_chart": "chart",
             "line_chart": "line", "bar_chart": "bar", "area_chart": "area",
             "scatter_chart": "scatter", "map": "map", "pydeck_chart": "map",
             "pyplot": "picture", "bokeh_chart": "chart", "dataframe": "table",
             "data_editor": "table", "table": "table", "metric": "metric"}
DASH_INPUTS = {"Dropdown": "select", "Slider": "slider", "RangeSlider": "range_slider",
               "RadioItems": "radio", "Checklist": "multiselect", "Input": "text",
               "Textarea": "text", "DatePickerSingle": "date",
               "DatePickerRange": "date_range", "Upload": "file",
               "Download": "download", "Link": "link"}
EXTRA_PACKAGES = {"scipy", "sklearn", "statsmodels", "torch", "tensorflow", "keras",
                  "xgboost", "lightgbm", "prophet", "pmdarima", "sktime", "shap",
                  "geopandas", "shapely", "networkx", "numba", "polars"}
DATETIME_CALLS = {"datetime", "date", "datetime.datetime", "datetime.date", "dt.datetime",
                  "dt.date", "pd.Timestamp", "pd.to_datetime", "Timestamp"}


def pascal(text):
    """Property name in PascalCase from an input id or label."""
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", str(text))
    words = re.findall(r"[A-Za-z0-9]+", text)
    name = "".join(w[:1].upper() + w[1:] for w in words)
    if name and name[0].isdigit():
        name = "P" + name
    return name


class Inventory:
    def __init__(self):
        self.items = []
        self.frameworks = {}
        self.files = []

    def add(self, kind, framework, where, widget, ident="", label="", details="",
            spotfire="", fidelity="", gap="", note=""):
        if gap and gap not in note:
            note = (GAPS[gap] + (": " + note if note else "")) if gap in GAPS else note
        self.items.append({"kind": kind, "framework": framework, "where": where,
                           "widget": widget, "id": ident, "label": label,
                           "details": details, "spotfire": spotfire,
                           "fidelity": fidelity or ("?" if not spotfire else ""),
                           "gap": gap, "note": note})


# ---------------------------------------------------------------- Python files

def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        base = dotted(node.func)
        return f"{base}()" if base else ""
    return ""


def literal(node):
    """Literal value of a node, or the source text when it is not a literal."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        try:
            return "<" + ast.unparse(node) + ">"
        except Exception:  # unparse is best effort only
            return "<expr>"


def is_datetime(node):
    if isinstance(node, ast.Call) and dotted(node.func) in DATETIME_CALLS:
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(is_datetime(e) for e in node.elts)
    return False


def kw(call, name):
    for item in call.keywords:
        if item.arg == name:
            return item.value
    return None


def arg(call, index, name=None):
    if name:
        value = kw(call, name)
        if value is not None:
            return value
    if index is not None and len(call.args) > index:
        node = call.args[index]
        if not isinstance(node, ast.Starred):
            return node
    return None


def short(value, limit=80):
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit - 3] + "..."


def prop_type(value, kind):
    if kind in ("multiselect",):
        return "String list"
    if kind in ("date", "date_range", "date_slider"):
        return "Date or DateTime"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Integer"
    if isinstance(value, float):
        return "Real"
    if isinstance(value, (tuple, list)) and value and isinstance(value[0], (int, float)):
        return "Real" if any(isinstance(v, float) for v in value) else "Integer"
    if kind == "checkbox":
        return "Boolean"
    if kind in ("button", "link", "file", "download", "theme"):
        return ""
    return "String"


class PythonScanner:
    def __init__(self, inv, path, rel, text, framework_hint=None, line_offset=0):
        self.inv, self.rel, self.text = inv, rel, text
        self.offset = line_offset
        self.tree = ast.parse(text)
        self.framework = framework_hint or self.detect(text)
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                child._parent = node
        self.static_text = 0
        self.session_keys = set()
        self.containers = self.find_containers()
        self.render_ids = set()
        self.placeholders = []
        self.local_modules = {p.stem for p in Path(path).parent.glob("*.py")} \
            if path else set()

    def find_containers(self):
        """Names bound to Streamlit containers (columns, tabs, expanders, forms)."""
        names = set()
        for node in ast.walk(self.tree):
            value, targets = None, []
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                value, targets = node.context_expr, [node.optional_vars]
            if not (isinstance(value, ast.Call) and dotted(value.func).startswith("st.")):
                continue
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        return names

    @staticmethod
    def detect(text):
        found = []
        if re.search(r"^\s*(import streamlit|from streamlit)", text, re.M):
            found.append("streamlit")
        if re.search(r"^\s*from shiny\.express import", text, re.M):
            found.append("shiny-express")
        elif re.search(r"^\s*(from shiny|import shiny)", text, re.M):
            found.append("shiny")
        if re.search(r"^\s*(from dash|import dash)", text, re.M):
            found.append("dash")
        if re.search(r"^\s*(import plotly|from plotly)", text, re.M):
            found.append("plotly")
        return "+".join(found) or "python"

    def where(self, node):
        return f"{self.rel}:{getattr(node, 'lineno', 0) + self.offset}"

    def ancestors(self, node):
        """Enclosing call names, including the context managers of `with` blocks."""
        names = []
        cur = getattr(node, "_parent", None)
        while cur is not None:
            if isinstance(cur, ast.Call):
                names.append(dotted(cur.func))
            elif isinstance(cur, ast.With):
                for item in cur.items:
                    if isinstance(item.context_expr, ast.Call):
                        names.append(dotted(item.context_expr.func))
                    else:
                        names.append(dotted(item.context_expr))
            cur = getattr(cur, "_parent", None)
        return names

    def assigned_name(self, node):
        parent = getattr(node, "_parent", None)
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and \
                isinstance(parent.targets[0], ast.Name):
            return parent.targets[0].id
        if isinstance(parent, (ast.AnnAssign, ast.NamedExpr)) and \
                isinstance(parent.target, ast.Name):
            return parent.target.id
        return ""

    def enclosing_function(self, node):
        cur = getattr(node, "_parent", None)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
            cur = getattr(cur, "_parent", None)
        return None

    def run(self):
        fw = self.framework
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.function(node)
            elif isinstance(node, ast.Call):
                self.call(node)
            elif isinstance(node, ast.Subscript) and dotted(node.value) == \
                    "st.session_state":
                key = literal(node.slice)
                if isinstance(key, str):
                    self.session_keys.add(key)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) \
                    and dotted(node.value) == "st.session_state":
                self.session_keys.add(node.attr)
        drop = [i for i in self.placeholders if self.inv.items[i]["id"] in self.render_ids]
        for index in reversed(drop):
            del self.inv.items[index]
        side = re.search(r"\bst\.sidebar\b", self.text)
        if "streamlit" in self.framework and side:
            line = self.text.count("\n", 0, side.start()) + 1 + self.offset
            self.inv.add("layout", self.framework, f"{self.rel}:{line}", "st.sidebar",
                         spotfire="text area holding the controls, first item of a row",
                         fidelity="SUBSTITUTE")
        if self.static_text:
            self.inv.add("output", fw, self.rel, "static text", label="",
                         details=f"{self.static_text} markdown or text calls",
                         spotfire="text-area HTML", fidelity="EXACT")
        if self.session_keys:
            self.inv.add("reactivity", fw, self.rel, "st.session_state",
                         details="keys: " + ", ".join(sorted(self.session_keys)),
                         spotfire="document properties (a JSON String property for "
                         "structured state)", fidelity="SUBSTITUTE")

    def imports(self, node):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module or ""]
        for name in names:
            top = name.split(".")[0]
            if top in EXTRA_PACKAGES:
                self.inv.add("data", self.framework, self.where(node), f"import {name}",
                             spotfire="install into Spotfire's Python, or port to numpy",
                             fidelity="SUBSTITUTE", gap="G12")
            elif top in self.local_modules and top != Path(self.rel).stem:
                self.inv.add("data", self.framework, self.where(node), f"import {name}",
                             details="local module",
                             spotfire="inline into the data function script",
                             fidelity="EXACT",
                             note="a data function cannot import sibling files")

    def function(self, node):
        fw = self.framework
        decos = [dotted(d.func) if isinstance(d, ast.Call) else dotted(d)
                 for d in node.decorator_list]
        reads = sorted({dotted(c.func).split(".")[1] for c in ast.walk(node)
                        if isinstance(c, ast.Call) and dotted(c.func).startswith("input.")
                        and dotted(c.func).count(".") == 1})
        read_text = ("reads " + ", ".join(reads)) if reads else ""
        for deco in decos:
            if deco.startswith("render.") or deco in ("render_widget", "render_plotly"):
                kind = deco.split(".")[-1]
                spot = {"plot": "native visual from the figure code",
                        "data_frame": "`table`", "table": "`table`",
                        "text": "`label` control bound to a value property",
                        "ui": "text-area HTML with label controls",
                        "download": "Spotfire's own export"}.get(kind,
                                                                "native visual from the "
                                                                "figure code")
                fid = {"ui": "SUBSTITUTE", "download": "SUBSTITUTE", "text": "CLOSE",
                       "data_frame": "EXACT", "table": "EXACT"}.get(kind, "")
                self.render_ids.add(node.name)
                self.inv.add("output", fw, self.where(node), f"@{deco}", ident=node.name,
                             details=read_text, spotfire=spot, fidelity=fid,
                             gap="G6" if kind == "ui" else "")
            elif deco == "reactive.calc" or deco == "reactive.Calc":
                self.inv.add("reactivity", fw, self.where(node), "@reactive.calc",
                             ident=node.name, details=read_text,
                             spotfire="automatic data function (or a calculated column "
                             "when it is per row)", fidelity="EXACT")
            elif deco in ("reactive.effect", "reactive.Effect"):
                event = [d for d in node.decorator_list if isinstance(d, ast.Call)
                         and dotted(d.func) == "reactive.event"]
                trig = ", ".join(ast.unparse(a) for a in event[0].args) if event else ""
                self.inv.add("reactivity", fw, self.where(node), "@reactive.effect",
                             ident=node.name,
                             details="; ".join(x for x in ("on " + trig if trig else "",
                                                           read_text) if x),
                             spotfire="manual data function plus a button, or a script "
                             "for side effects", fidelity="EXACT" if trig else "?")
            elif deco in ("st.cache_data", "st.cache_resource", "st.cache"):
                self.inv.add("reactivity", fw, self.where(node), f"@{deco}",
                             ident=node.name,
                             spotfire="data function (automatic when inputs drive it, "
                             "otherwise precomputed data)", fidelity="EXACT")
            elif deco.endswith("callback"):
                self.callback(node, deco)

    def callback(self, node, deco):
        call = [d for d in node.decorator_list if isinstance(d, ast.Call)]
        if not call:
            return
        deps = {"Output": [], "Input": [], "State": []}
        for sub in ast.walk(call[0]):
            if isinstance(sub, ast.Call) and dotted(sub.func).split(".")[-1] in deps:
                parts = [literal(a) for a in sub.args[:2]]
                deps[dotted(sub.func).split(".")[-1]].append(
                    ".".join(str(p) for p in parts if p is not None))
        props = " ".join(deps["Input"] + deps["State"])
        spot, fid, gap = "automatic data function", "EXACT", ""
        if "n_clicks" in props:
            spot = "manual data function plus a button"
        if re.search(r"selectedData|clickData", props):
            spot, fid = "marking with limitByMarkings on the detail visuals", "SUBSTITUTE"
        if "relayoutData" in props:
            gap = "G4"
        if "hoverData" in props:
            spot, fid = "tooltip only", "SUBSTITUTE"
        details = "; ".join(f"{k}: {', '.join(v)}" for k, v in deps.items() if v)
        self.inv.add("reactivity", self.framework, self.where(node), "@callback",
                     ident=node.name, details=details, spotfire=spot, fidelity=fid, gap=gap)

    def call(self, node):
        name = dotted(node.func)
        if not name:
            return
        attr = name.split(".")[-1]
        base = name.rsplit(".", 1)[0] if "." in name else ""
        fw = self.framework
        if "shiny" in fw:
            self.shiny_call(node, name, attr)
        if "streamlit" in fw:
            self.streamlit_call(node, name, attr, base)
        if "dash" in fw:
            self.dash_call(node, name, attr, base)
        self.plotly_call(node, name, attr, base)
        self.data_call(node, name, attr)

    # Shiny ---------------------------------------------------------------
    def shiny_call(self, node, name, attr):
        fw = self.framework
        match = re.fullmatch(r"(?:ui\.)?input_(\w+)", name)
        if match and match.group(1) in SHINY_INPUTS:
            widget = match.group(1)
            kind = SHINY_INPUTS[widget]
            ident = literal(arg(node, 0, "id"))
            label = literal(arg(node, 1, "label"))
            details, default = [], None
            if widget in ("select", "selectize", "radio_buttons", "checkbox_group"):
                choices = literal(arg(node, 2, "choices"))
                default = literal(kw(node, "selected"))
                details.append(f"choices={short(choices)}")
                if literal(kw(node, "multiple")) is True:
                    kind = "multiselect"
            elif widget == "slider":
                lo, hi = arg(node, 2, "min"), arg(node, 3, "max")
                value = arg(node, 4, "value")
                default = literal(value)
                details += [f"min={short(literal(lo))}", f"max={short(literal(hi))}"]
                step = kw(node, "step")
                if step is not None:
                    details.append(f"step={short(literal(step))}")
                if is_datetime(lo) or is_datetime(value):
                    kind = "date_range" if isinstance(value, (ast.Tuple, ast.List)) \
                        else "date_slider"
                elif isinstance(value, (ast.Tuple, ast.List)):
                    kind = "range_slider"
            elif widget == "numeric":
                default = literal(arg(node, 2, "value"))
                for key, pos in (("min", 3), ("max", 4), ("step", 5)):
                    val = arg(node, pos, key)
                    if val is not None:
                        details.append(f"{key}={short(literal(val))}")
            elif widget in ("checkbox", "switch", "text", "text_area", "date"):
                default = literal(arg(node, 2, "value"))
            elif widget == "date_range":
                default = [literal(arg(node, 2, "start")), literal(arg(node, 3, "end"))]
            if default is not None:
                details.insert(0, f"default={short(default)}")
            self.add_input(node, f"ui.input_{widget}", kind, ident, label, details, default)
            return
        if name in ("ui.nav_panel", "ui.nav", "nav_panel"):
            title = literal(arg(node, 0, "title"))
            context = self.ancestors(node)
            nested = [c for c in context if re.search(r"navset_|navs_", c)]
            if nested:
                self.inv.add("layout", fw, self.where(node), "ui.nav_panel in a navset",
                             label=str(title), spotfire="separate page, or stacked on the "
                             "page", fidelity="SUBSTITUTE", gap="G11",
                             note="tabs inside a page")
            else:
                self.inv.add("page", fw, self.where(node), "ui.nav_panel", label=str(title),
                             spotfire=f"page `{title}`", fidelity="EXACT")
        elif name in ("ui.sidebar",):
            width = literal(kw(node, "width"))
            self.inv.add("layout", fw, self.where(node), name,
                         details=f"width={width}" if width is not None else "",
                         spotfire="text area holding the controls, first item of a row",
                         fidelity="SUBSTITUTE")
        elif name in ("ui.layout_columns", "ui.layout_column_wrap"):
            widths = literal(kw(node, "col_widths"))
            self.inv.add("layout", fw, self.where(node), name,
                         details=f"col_widths={short(widths)}" if widths else "",
                         spotfire="`row` with the same weights", fidelity="EXACT")
        elif name == "ui.card_header":
            self.inv.add("layout", fw, self.where(node), name,
                         label=str(literal(arg(node, 0))),
                         spotfire="visual title of the card's visual", fidelity="CLOSE")
        elif name in ("ui.accordion", "ui.accordion_panel"):
            self.inv.add("layout", fw, self.where(node), name,
                         label=str(literal(arg(node, 0))) if name.endswith("panel") else "",
                         spotfire="always-open section in the panel", fidelity="SUBSTITUTE")
        elif name in ("ui.modal", "ui.popover", "ui.modal_show", "ui.tooltip"):
            self.inv.add("layout", fw, self.where(node), name,
                         spotfire="section of the panel, or its own page",
                         fidelity="SUBSTITUTE", gap="G11")
        elif name == "ui.value_box":
            self.add_chart(node, name, "value_box", label=str(literal(arg(node, 0))))
        elif re.fullmatch(r"ui\.output_\w+|output_widget", name):
            self.placeholders.append(len(self.inv.items))
            self.inv.add("output", fw, self.where(node), name,
                         ident=str(literal(arg(node, 0, "id"))),
                         details="placeholder; see the render function of the same name",
                         spotfire="see the render function", fidelity="?")
        elif re.fullmatch(r"ui\.update_\w+", name):
            self.inv.add("reactivity", fw, self.where(node), name,
                         ident=str(literal(arg(node, 0, "id"))),
                         spotfire="`column` value source on the control",
                         fidelity="EXACT")
        elif name in ("reactive.value", "reactive.Value"):
            self.inv.add("reactivity", fw, self.where(node), name,
                         ident=self.assigned_name(node),
                         details=f"initial={short(literal(arg(node, 0)))}",
                         spotfire="document property (JSON String for structured state)",
                         fidelity="SUBSTITUTE")
        elif name in ("ui.Progress",):
            self.inv.add("output", fw, self.where(node), name,
                         spotfire="Spotfire's busy indicator", fidelity="SUBSTITUTE",
                         gap="G8")

    # Streamlit -----------------------------------------------------------
    def streamlit_call(self, node, name, attr, base):
        fw = self.framework
        in_st = base == "st" or base.startswith("st.") or base in self.containers
        if attr in ST_INPUTS and in_st:
            kind = ST_INPUTS[attr]
            label = literal(arg(node, 0, "label"))
            ident = literal(kw(node, "key")) or self.assigned_name(node) or pascal(label)
            details, default = [], None
            if attr in ("selectbox", "multiselect", "radio", "select_slider", "pills",
                        "segmented_control"):
                options = literal(arg(node, 1, "options"))
                details.append(f"options={short(options)}")
                if attr in ("selectbox", "radio"):
                    index = literal(kw(node, "index"))
                    index = 0 if index is None else index
                    if (isinstance(options, (list, tuple)) and isinstance(index, int)
                            and 0 <= index < len(options)):
                        default = options[index]
                else:
                    default = literal(kw(node, "default") or kw(node, "value"))
                if attr == "select_slider" and isinstance(default, (tuple, list)):
                    kind = "range_slider"
            elif attr == "slider":
                lo, hi = arg(node, 1, "min_value"), arg(node, 2, "max_value")
                value = arg(node, 3, "value")
                step = arg(node, 4, "step")
                default = literal(value)
                details += [f"min={short(literal(lo))}", f"max={short(literal(hi))}"]
                if step is not None:
                    details.append(f"step={short(literal(step))}")
                if is_datetime(lo) or is_datetime(value) or is_datetime(hi):
                    kind = "date_range" if isinstance(value, (ast.Tuple, ast.List)) \
                        else "date_slider"
                elif isinstance(value, (ast.Tuple, ast.List)):
                    kind = "range_slider"
            elif attr == "number_input":
                lo, hi = arg(node, 1, "min_value"), arg(node, 2, "max_value")
                default = literal(arg(node, 3, "value"))
                details += [f"min={short(literal(lo))}", f"max={short(literal(hi))}"]
                step = arg(node, 4, "step")
                if step is not None:
                    details.append(f"step={short(literal(step))}")
            elif attr == "date_input":
                value = arg(node, 1, "value")
                default = literal(value)
                if isinstance(value, (ast.Tuple, ast.List)):
                    kind = "date_range"
            elif attr in ("checkbox", "toggle", "text_input", "text_area"):
                default = literal(arg(node, 1, "value"))
            if default is not None:
                details.insert(0, f"default={short(default)}")
            if base.startswith("st.sidebar"):
                details.append("in sidebar")
            self.add_input(node, f"st.{attr}", kind, ident, label, details, default)
            return
        if not in_st:
            return
        if attr in ST_CHARTS:
            kind = ST_CHARTS[attr]
            on_select = kw(node, "on_select")
            label = literal(arg(node, 0, "label")) if attr == "metric" else ""
            self.add_chart(node, f"st.{attr}", kind, label=str(label or ""))
            if on_select is not None:
                self.inv.add("reactivity", fw, self.where(node), f"st.{attr}(on_select=...)",
                             spotfire="marking on the visual, limitByMarkings on the "
                             "detail visuals", fidelity="EXACT")
        elif attr == "tabs" and in_st:
            labels = literal(arg(node, 0, "tabs"))
            self.inv.add("layout", fw, self.where(node), "st.tabs", label=short(labels),
                         spotfire="separate pages, or views stacked on one page",
                         fidelity="SUBSTITUTE", gap="G11", note="tabs inside a page")
        elif name in ("st.navigation",):
            self.inv.add("layout", fw, self.where(node), name,
                         spotfire="`app.pageNavigation: \"Tabs\"`", fidelity="EXACT")
        elif name in ("st.Page",):
            title = literal(kw(node, "title")) or literal(arg(node, 0))
            self.inv.add("page", fw, self.where(node), name, label=str(title),
                         spotfire=f"page `{title}`", fidelity="EXACT")
        elif attr == "columns":
            spec = literal(arg(node, 0, "spec"))
            self.inv.add("layout", fw, self.where(node), "st.columns",
                         details=f"spec={short(spec)}",
                         spotfire="`row` with the same weights", fidelity="EXACT")
        elif attr == "expander":
            self.inv.add("layout", fw, self.where(node), "st.expander",
                         label=str(literal(arg(node, 0, "label"))),
                         spotfire="always-open section in the panel", fidelity="SUBSTITUTE")
        elif attr in ("popover", "dialog"):
            self.inv.add("layout", fw, self.where(node), f"st.{attr}",
                         label=str(literal(arg(node, 0, "label"))),
                         spotfire="section of the panel, or its own page",
                         fidelity="SUBSTITUTE", gap="G11")
        elif attr == "form":
            self.inv.add("layout", fw, self.where(node), "st.form",
                         spotfire="inputs plus one button that runs a manual data function",
                         fidelity="EXACT")
        elif attr in ("progress", "spinner", "status"):
            self.inv.add("output", fw, self.where(node), f"st.{attr}",
                         spotfire="Spotfire's busy indicator", fidelity="SUBSTITUTE",
                         gap="G8")
        elif attr in ("markdown", "write", "caption", "info", "success", "warning", "error",
                      "text", "latex"):
            first = arg(node, 0, "body")
            if isinstance(first, ast.JoinedStr) or (
                    first is not None and not isinstance(first, ast.Constant)):
                self.inv.add("output", fw, self.where(node), f"st.{attr}",
                             details="text with live values",
                             spotfire="text-area HTML with `label` controls",
                             fidelity="CLOSE", gap="G6")
            else:
                self.static_text += 1
        elif attr in ("title", "header", "subheader"):
            self.inv.add("layout", fw, self.where(node), f"st.{attr}",
                         label=str(literal(arg(node, 0, "body"))),
                         spotfire="page title, visual title or a header text area",
                         fidelity="CLOSE")
        elif name == "st.set_page_config":
            self.inv.add("style", fw, self.where(node), name,
                         details=", ".join(f"{k.arg}={short(literal(k.value))}"
                                           for k in node.keywords),
                         spotfire="page layout and `app.theme`", fidelity="CLOSE")

    # Dash ----------------------------------------------------------------
    def dash_call(self, node, name, attr, base):
        fw = self.framework
        ident = literal(kw(node, "id"))
        if base.endswith("dcc") and attr in DASH_INPUTS:
            kind = DASH_INPUTS[attr]
            details, default = [], literal(kw(node, "value"))
            if attr == "Dropdown":
                details.append(f"options={short(literal(kw(node, 'options') or arg(node, 0)))}")
                if literal(kw(node, "multi")) is True:
                    kind = "multiselect"
            if attr in ("Slider", "RangeSlider"):
                for key in ("min", "max", "step"):
                    val = kw(node, key)
                    if val is not None:
                        details.append(f"{key}={short(literal(val))}")
            if attr == "Input" and literal(kw(node, "type")) == "number":
                kind = "numeric"
            if default is not None:
                details.insert(0, f"default={short(default)}")
            label = literal(kw(node, "placeholder")) or ""
            self.add_input(node, f"dcc.{attr}", kind, ident, label, details, default)
        elif base.endswith("html") and attr == "Button":
            label = literal(arg(node, 0, "children"))
            self.add_input(node, "html.Button", "button", ident, label, [], None)
        elif base.endswith("dcc") and attr == "Graph":
            self.inv.add("output", fw, self.where(node), "dcc.Graph", ident=str(ident),
                         details="figure built in a callback or inline",
                         spotfire="see the figure code", fidelity="?")
        elif attr == "DataTable":
            sel = literal(kw(node, "row_selectable"))
            self.add_chart(node, "dash_table.DataTable", "table", ident=str(ident))
            if sel:
                self.inv.add("reactivity", fw, self.where(node), "row_selectable",
                             ident=str(ident), spotfire="the table's own marking",
                             fidelity="EXACT")
        elif base.endswith("dcc") and attr == "Tabs":
            nested = [c for c in self.ancestors(node) if c.endswith("Tabs")]
            if nested:
                self.inv.add("layout", fw, self.where(node), "dcc.Tabs (nested)",
                             spotfire="separate pages, or views stacked on one page",
                             fidelity="SUBSTITUTE", gap="G11", note="tabs inside a page")
        elif base.endswith("dcc") and attr == "Tab":
            label = literal(kw(node, "label"))
            nested = [c for c in self.ancestors(node) if c.endswith("Tabs")]
            if len(nested) <= 1:
                self.inv.add("page", fw, self.where(node), "dcc.Tab", label=str(label),
                             spotfire=f"page `{label}`", fidelity="EXACT")
        elif base.endswith("dcc") and attr == "Store":
            self.inv.add("reactivity", fw, self.where(node), "dcc.Store", ident=str(ident),
                         spotfire="document property (JSON String for structured state)",
                         fidelity="SUBSTITUTE")
        elif base.endswith("dcc") and attr == "Interval":
            self.inv.add("reactivity", fw, self.where(node), "dcc.Interval",
                         ident=str(ident), spotfire="none: stored data only",
                         fidelity="MANUAL", gap="G11", note="timer")
        elif base.endswith("dcc") and attr == "Loading":
            self.inv.add("output", fw, self.where(node), "dcc.Loading",
                         spotfire="Spotfire's busy indicator", fidelity="SUBSTITUTE",
                         gap="G8")
        elif attr == "Col" and base.endswith("dbc"):
            width = literal(kw(node, "width") or kw(node, "md") or kw(node, "lg"))
            self.inv.add("layout", fw, self.where(node), "dbc.Col",
                         details=f"width={short(width)}" if width is not None else "",
                         spotfire="item of a `row` with this weight", fidelity="EXACT")
        elif attr == "CardHeader":
            self.inv.add("layout", fw, self.where(node), name,
                         label=str(literal(arg(node, 0, "children"))),
                         spotfire="visual title of the card's visual", fidelity="CLOSE")
        elif name in ("dash.register_page", "register_page"):
            title = literal(kw(node, "name")) or literal(kw(node, "title"))
            self.inv.add("page", fw, self.where(node), name, label=str(title),
                         spotfire=f"page `{title}`", fidelity="EXACT")

    # Plotly --------------------------------------------------------------
    def plotly_call(self, node, name, attr, base):
        fw = self.framework
        if base in ("px", "plotly.express") and attr in PX_KINDS:
            kind = PX_KINDS[attr]
            details = []
            for key in ("x", "y", "color", "size", "facet_row", "facet_col", "trendline",
                        "line_shape", "title", "barmode", "orientation"):
                val = kw(node, key)
                if val is not None:
                    details.append(f"{key}={short(literal(val), 40)}")
            self.add_chart(node, f"px.{attr}", kind, details=details)
            if kw(node, "facet_row") is not None or kw(node, "facet_col") is not None:
                self.inv.add("output", fw, self.where(node), "facets",
                             spotfire="`trellis` on the visual", fidelity="EXACT")
        elif base in ("go", "plotly.graph_objects") and attr in GO_KINDS:
            kind = GO_KINDS[attr]
            mode = literal(kw(node, "mode"))
            if attr in ("Scatter", "Scattergl"):
                kind = "line" if isinstance(mode, str) and "lines" in mode else "scatter"
                if mode is None:
                    kind = "line"
            details = [f"mode={mode}"] if mode else []
            for key in ("name", "x", "y"):
                val = kw(node, key)
                if val is not None:
                    details.append(f"{key}={short(literal(val), 40)}")
            self.add_chart(node, f"go.{attr}", kind, details=details)
            line = kw(node, "line")
            dash = literal(kw(node, "line_dash"))
            if isinstance(line, ast.Call) and dotted(line.func) == "dict":
                dash = literal(kw(line, "dash")) or dash
            elif isinstance(line, ast.Dict):
                for k, v in zip(line.keys, line.values):
                    if literal(k) == "dash":
                        dash = literal(v)
            if dash and dash != "solid":
                self.inv.add("output", fw, self.where(node), f"go.{attr}(line.dash={dash})",
                             spotfire="distinct solid color with a clear legend name",
                             fidelity="CLOSE", gap="G3")
        elif attr == "add_vrect":
            self.inv.add("output", fw, self.where(node), "add_vrect",
                         spotfire="line colored by state (X bands are slim tier)",
                         fidelity="SUBSTITUTE", gap="G1")
        elif attr == "add_hrect":
            self.inv.add("output", fw, self.where(node), "add_hrect",
                         spotfire="two horizontal reference lines (a band is slim tier)",
                         fidelity="CLOSE")
        elif attr in ("add_hline", "add_vline"):
            val = kw(node, "y" if attr == "add_hline" else "x") or arg(node, 0)
            self.inv.add("output", fw, self.where(node), attr,
                         details=f"value={short(literal(val), 40)}",
                         spotfire="reference line (`referenceLayers`)", fidelity="EXACT")
        elif attr == "add_annotation":
            self.inv.add("output", fw, self.where(node), "add_annotation",
                         spotfire="reference-layer label, visual title or a panel note",
                         fidelity="CLOSE")
        elif attr == "add_shape":
            self.inv.add("output", fw, self.where(node), "add_shape",
                         details=f"type={literal(kw(node, 'type'))}",
                         spotfire="reference layer or X band (read the shape)", fidelity="?")
        elif attr == "make_subplots":
            specs = ast.unparse(node)
            secondary = "secondary_y" in specs
            self.inv.add("layout", fw, self.where(node), "make_subplots",
                         details="secondary_y" if secondary else "",
                         spotfire="two visuals stacked with the same x" if secondary else
                         "one trellised `lineChart`, or separate visuals",
                         fidelity="SUBSTITUTE" if secondary else "EXACT")
        if attr in ("update_layout", "update_xaxes", "update_yaxes") or base in ("go", "px"):
            for item in node.keywords:
                value = literal(item.value)
                if item.arg == "template" and isinstance(value, str) and "dark" in value:
                    self.inv.add("style", fw, self.where(node), f"template={value}",
                                 spotfire="`app.theme.base` (document-wide)",
                                 fidelity="CLOSE", gap="G7")
                elif item.arg == "selectdirection" and value == "h":
                    self.inv.add("reactivity", fw, self.where(node), "selectdirection='h'",
                                 spotfire="marking on band bars, or typed start and end",
                                 fidelity="CLOSE", gap="G9")
                elif item.arg in ("xaxis_rangeslider_visible", "rangeslider") and value:
                    self.inv.add("output", fw, self.where(node), "rangeslider",
                                 spotfire="Spotfire's own zoom sliders", fidelity="CLOSE",
                                 gap="G4")
                elif item.arg == "dragmode" and value in ("select", "lasso"):
                    self.inv.add("reactivity", fw, self.where(node), f"dragmode={value}",
                                 spotfire="marking", fidelity="EXACT")
        for item in node.keywords:
            if item.arg == "fill":
                value = literal(item.value)
                if isinstance(value, str) and value.startswith("to"):
                    self.inv.add("output", fw, self.where(node), f"fill={value}",
                                 spotfire="both edges as same-color series",
                                 fidelity="CLOSE", gap="G2")
        if (base in ("plt", "matplotlib.pyplot") and attr in ("subplots", "figure")) or (
                base in ("sns", "seaborn") and attr.endswith("plot") or attr == "heatmap"
                and base in ("sns", "seaborn")):
            self.add_chart(node, name, "picture")

    # Data ----------------------------------------------------------------
    def data_call(self, node, name, attr):
        fw = self.framework
        if re.fullmatch(r"(pd|pandas)\.read_\w+", name):
            source = literal(arg(node, 0))
            self.inv.add("data", fw, self.where(node), name, details=short(source),
                         spotfire="table in `data/` (SBDF or CSV), embedded",
                         fidelity="EXACT")
            if attr == "read_excel":
                self.inv.items[-1]["note"] = "convert the workbook to CSV or SBDF"
        elif name in ("np.random.default_rng", "np.random.seed", "random.seed",
                      "numpy.random.default_rng"):
            seed = literal(arg(node, 0))
            self.inv.add("data", fw, self.where(node), name, details=f"seed={seed}",
                         spotfire="precomputed table, or a data function with a fixed seed",
                         fidelity="EXACT" if seed is not None else "?",
                         note="" if seed is not None else "no seed: results change per run")
        elif name in ("datetime.now", "datetime.datetime.now", "dt.datetime.now",
                      "date.today", "datetime.date.today", "pd.Timestamp.now",
                      "pd.Timestamp.today", "datetime.today"):
            self.inv.add("data", fw, self.where(node), name,
                         spotfire="a fixed start date", fidelity="SUBSTITUTE",
                         note="builds must be reproducible")

    # Helpers -------------------------------------------------------------
    def add_input(self, node, widget, kind, ident, label, details, default):
        spot, fid, gap = INPUT_MAP.get(kind, ("?", "?", ""))
        prop = pascal(ident if ident and not str(ident).startswith("<") else label)
        ptype = prop_type(default, kind)
        if ptype and prop and kind in ("range_slider", "date_range"):
            spot = f"{spot}; properties `{prop}Min` and `{prop}Max` ({ptype})"
        elif ptype and prop and kind == "multiselect":
            spot = f"{spot} on list-valued property `{prop}` ({ptype})"
        elif ptype and prop:
            spot = f"{spot} on property `{prop}` ({ptype})"
        self.inv.add("input", self.framework, self.where(node), widget,
                     ident="" if ident is None else str(ident),
                     label="" if label is None else str(label),
                     details="; ".join(details), spotfire=spot, fidelity=fid, gap=gap)

    def add_chart(self, node, widget, kind, label="", ident="", details=None):
        spot, fid, gap = CHART_MAP.get(kind, CHART_MAP["chart"])
        if not ident:
            func = self.enclosing_function(node)
            ident = func.name if func is not None else ""
        self.inv.add("output", self.framework, self.where(node), widget, ident=ident,
                     label=label, details="; ".join(details or []), spotfire=spot,
                     fidelity=fid, gap=gap)


def scan_python(inv, path, rel, text, hint=None, offset=0):
    try:
        scanner = PythonScanner(inv, path, rel, text, hint, offset)
    except SyntaxError as exc:
        inv.add("note", "python", f"{rel}:{(exc.lineno or 0) + offset}", "syntax error",
                details=str(exc.msg), fidelity="?",
                note="the file does not compile: fix or pick another version first")
        return "python"
    scanner.run()
    return scanner.framework


# ---------------------------------------------------------------- Quarto

def scan_quarto(inv, path, rel, text):
    front = re.match(r"---\n(.*?)\n---", text, re.S)
    meta = front.group(1) if front else ""
    dashboard = bool(re.search(r"format:\s*\n?\s*dashboard|format:\s*dashboard", meta))
    shiny = bool(re.search(r"server:\s*shiny", meta))
    fw = "quarto-dashboard" if dashboard else "quarto"
    in_code, cell, cell_start, options = False, [], 0, {}
    for lineno, line in enumerate(text.splitlines(), 1):
        where = f"{rel}:{lineno}"
        fence = re.match(r"```\s*\{(\w+)", line)
        if not in_code and fence:
            in_code, cell, cell_start, options = True, [], lineno, {}
            lang = fence.group(1)
            continue
        if in_code and line.startswith("```"):
            in_code = False
            if options.get("content") == "valuebox":
                inv.add("output", fw, f"{rel}:{cell_start}", "valuebox",
                        label=options.get("title", ""), spotfire=CHART_MAP["value_box"][0],
                        fidelity="CLOSE")
            if lang == "python":
                code = "\n".join(cell)
                scan_python(inv, path, rel, code, "shiny" if shiny else None, cell_start)
            elif lang == "ojs":
                for off, cline in enumerate(cell, 1):
                    match = re.search(r"viewof\s+(\w+)\s*=\s*Inputs\.(\w+)", cline)
                    if match:
                        kind = {"range": "slider", "select": "select", "radio": "radio",
                                "checkbox": "multiselect", "toggle": "checkbox",
                                "text": "text", "date": "date"}.get(match.group(2), "?")
                        spot, fid, gap = INPUT_MAP.get(kind, ("?", "?", ""))
                        inv.add("input", "ojs", f"{rel}:{cell_start + off}",
                                f"Inputs.{match.group(2)}", ident=match.group(1),
                                spotfire=f"{spot} on property `{pascal(match.group(1))}`",
                                fidelity=fid, gap=gap)
            continue
        if in_code:
            opt = re.match(r"#\|\s*([\w-]+):\s*(.*)", line)
            if opt:
                options[opt.group(1)] = opt.group(2).strip().strip("\"'")
            cell.append(line)
            continue
        heading = re.match(r"(#{1,3})\s+(.*?)\s*(\{.*\})?\s*$", line)
        if heading:
            level, title, attrs = len(heading.group(1)), heading.group(2), heading.group(3) or ""
            if ".sidebar" in attrs:
                inv.add("layout", fw, where, "{.sidebar}",
                        spotfire="text area holding the controls", fidelity="SUBSTITUTE")
            elif ".tabset" in attrs:
                inv.add("layout", fw, where, "{.tabset}", label=title,
                        spotfire="separate pages, or views stacked on one page",
                        fidelity="SUBSTITUTE", gap="G11", note="tabs inside a page")
            elif level == 1 and dashboard:
                inv.add("page", fw, where, "# heading", label=title,
                        spotfire=f"page `{title}`", fidelity="EXACT")
            elif level == 2 and dashboard:
                inv.add("layout", fw, where, "## row or column", label=title, details=attrs,
                        spotfire="`row` or `column` with weights", fidelity="EXACT")
        if re.search(r"\{\.panel-tabset", line):
            inv.add("layout", fw, where, ".panel-tabset",
                    spotfire="separate pages, or views stacked on one page",
                    fidelity="SUBSTITUTE", gap="G11", note="tabs inside a page")
    return fw + ("+shiny" if shiny else "")


# ---------------------------------------------------------------- HTML and React

def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_html(inv, rel, text):
    fw = "html"
    for m in re.finditer(r"<SpotfireControl\b([^>]*)>", text, re.I):
        attrs = m.group(1)
        ident = re.search(r'id\s*=\s*"([^"]+)"', attrs)
        label = re.search(r'label\s*=\s*"([^"]+)"', attrs)
        inv.add("input", fw, f"{rel}:{line_of(text, m.start())}", "SpotfireControl",
                ident=ident.group(1) if ident else "", label=label.group(1) if label else "",
                spotfire=INPUT_MAP["control_placeholder"][0], fidelity="EXACT")
    for m in re.finditer(r"\[(SPOTFIRE\s+\w+|INSERT\s+\w+)\s*:\s*([^\]]+)\]", text):
        inv.add("input", fw, f"{rel}:{line_of(text, m.start())}", m.group(1).strip(),
                label=m.group(2).strip(), spotfire="control or action named in the note",
                fidelity="EXACT")
    for m in re.finditer(r"<select\b([^>]*)>", text, re.I):
        ident = re.search(r'id\s*=\s*"([^"]+)"', m.group(1))
        add_simple_input(inv, fw, rel, text, m.start(), "<select>", "select",
                         ident.group(1) if ident else "")
    for m in re.finditer(r"<input\b([^>]*)>", text, re.I):
        attrs = m.group(1)
        typ = re.search(r'type\s*=\s*"([^"]+)"', attrs)
        ident = re.search(r'id\s*=\s*"([^"]+)"', attrs)
        kind = {"range": "slider", "number": "numeric", "checkbox": "checkbox",
                "radio": "radio", "date": "date", "file": "file"}.get(
            typ.group(1).lower() if typ else "text", "text")
        add_simple_input(inv, fw, rel, text, m.start(), f"<input type={typ.group(1) if typ else 'text'}>",
                         kind, ident.group(1) if ident else "")
    for m in re.finditer(r"<button\b[^>]*>(.*?)</button>", text, re.I | re.S):
        label = re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip()
        add_simple_input(inv, fw, rel, text, m.start(), "<button>", "button", "", label)
    for m in re.finditer(r"<details\b", text, re.I):
        inv.add("layout", fw, f"{rel}:{line_of(text, m.start())}", "<details>",
                spotfire="always-open section (the sanitizer removes <details>)",
                fidelity="SUBSTITUTE")
    for m in re.finditer(r"Plotly\.(newPlot|react)\s*\(", text):
        inv.add("output", "plotly-html", f"{rel}:{line_of(text, m.start())}",
                f"Plotly.{m.group(1)}", spotfire="read the traces in the data JSON",
                fidelity="?")
    for m in re.finditer(r'"type"\s*:\s*"(\w+)"', text):
        trace = m.group(1)
        kind = GO_KINDS.get(trace[:1].upper() + trace[1:])
        if kind and "Plotly" in text:
            spot, fid, gap = CHART_MAP.get(kind, CHART_MAP["chart"])
            inv.add("output", "plotly-html", f"{rel}:{line_of(text, m.start())}",
                    f"trace type {trace}", spotfire=spot, fidelity=fid, gap=gap)
    for m in re.finditer(r'"fill"\s*:\s*"(to\w+)"', text):
        inv.add("output", "plotly-html", f"{rel}:{line_of(text, m.start())}",
                f"fill={m.group(1)}", spotfire="both edges as same-color series",
                fidelity="CLOSE", gap="G2")
    for m in re.finditer(r"<style\b", text, re.I):
        inv.add("style", fw, f"{rel}:{line_of(text, m.start())}", "<style>",
                spotfire="`app.theme` and the styling skill (the sanitizer removes <style>)",
                fidelity="CLOSE")
    return fw


def add_simple_input(inv, fw, rel, text, pos, widget, kind, ident, label=""):
    spot, fid, gap = INPUT_MAP.get(kind, ("?", "?", ""))
    prop = pascal(ident or label)
    if prop and kind not in ("button", "link", "file"):
        spot = f"{spot} on property `{prop}`"
    inv.add("input", fw, f"{rel}:{line_of(text, pos)}", widget, ident=ident, label=label,
            spotfire=spot, fidelity=fid, gap=gap)


RECHARTS = {"LineChart": "line", "BarChart": "bar", "AreaChart": "area",
            "ComposedChart": "line", "ScatterChart": "scatter", "PieChart": "pie",
            "Treemap": "treemap", "RadarChart": "radar", "RadialBarChart": "polar",
            "FunnelChart": "funnel", "Sankey": "sankey"}


def scan_react(inv, rel, text):
    fw = "react"
    for m in re.finditer(r"const\s*\[\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*(?:React\.)?useState"
                         r"\s*(?:<[^>]*>)?\(([^)]*)\)", text):
        ident, init = m.group(1), m.group(3).strip()
        inv.add("input", fw, f"{rel}:{line_of(text, m.start())}", "useState", ident=ident,
                details=f"initial={init}",
                spotfire=f"document property `{pascal(ident)}` or a marking",
                fidelity="?")
    for m in re.finditer(r"useMemo\s*\(", text):
        inv.add("reactivity", fw, f"{rel}:{line_of(text, m.start())}", "useMemo",
                spotfire="expression or automatic data function", fidelity="?")
    for m in re.finditer(r"<(\w+)\b([^>]*)>", text):
        tag, attrs = m.group(1), m.group(2)
        where = f"{rel}:{line_of(text, m.start())}"
        if tag in RECHARTS:
            spot, fid, gap = CHART_MAP.get(RECHARTS[tag], CHART_MAP["chart"])
            inv.add("output", fw, where, f"<{tag}>", spotfire=spot, fidelity=fid, gap=gap)
        elif tag == "Area":
            inv.add("output", fw, where, "<Area>", spotfire="both edges as same-color series",
                    fidelity="CLOSE", gap="G2")
        elif tag == "ReferenceLine":
            inv.add("output", fw, where, "<ReferenceLine>", spotfire="reference line",
                    fidelity="EXACT")
        elif tag == "ReferenceArea":
            gap = "G1" if re.search(r"\bx1\s*=", attrs) else ""
            inv.add("output", fw, where, "<ReferenceArea>",
                    spotfire=("line colored by state (X bands are slim tier)" if gap else
                              "two horizontal reference lines (a band is slim tier)"),
                    fidelity="SUBSTITUTE" if gap else "CLOSE", gap=gap)
        elif tag == "Brush":
            inv.add("output", fw, where, "<Brush>", spotfire="Spotfire's own zoom sliders",
                    fidelity="CLOSE", gap="G4")
        elif tag == "Line" and "strokeDasharray" in attrs:
            inv.add("output", fw, where, "<Line strokeDasharray>",
                    spotfire="distinct solid color with a clear legend name",
                    fidelity="CLOSE", gap="G3")
        elif tag in ("select", "input", "button"):
            ident = re.search(r'\bid\s*=\s*"([^"]+)"', attrs)
            typ = re.search(r'\btype\s*=\s*"([^"]+)"', attrs)
            kind = {"select": "select", "button": "button"}.get(tag) or {
                "range": "slider", "number": "numeric", "checkbox": "checkbox",
                "date": "date", "file": "file"}.get(typ.group(1) if typ else "", "text")
            add_simple_input(inv, fw, rel, text, m.start(), f"<{tag}>", kind,
                             ident.group(1) if ident else "")
    if re.search(r"\b(activeTab|setActiveTab|setTab)\b", text):
        inv.add("layout", fw, rel, "tab state",
                spotfire="pages (top-level tabs) or stacked views (tabs inside a page)",
                fidelity="?", note="read the tab component")
    return fw


# ---------------------------------------------------------------- driver

def collect(target):
    target = Path(target)
    if target.is_file():
        return [target], target.parent
    files = []
    for path in sorted(target.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(target).parts):
            continue
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            files.append(path)
    return files, target


def scan(target):
    inv = Inventory()
    files, root = collect(target)
    for path in files:
        rel = path.relative_to(root).as_posix() if path != root else path.name
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        kind = EXTENSIONS[path.suffix.lower()]
        before = len(inv.items)
        if kind == "python":
            fw = scan_python(inv, path, rel, text)
            if "streamlit" in fw and "pages" in path.relative_to(root).parts[:-1]:
                inv.add("page", fw, rel, "pages/ file", label=path.stem,
                        spotfire=f"page from `{path.stem}`", fidelity="EXACT")
        elif kind == "quarto":
            fw = scan_quarto(inv, path, rel, text)
        elif kind == "html":
            fw = scan_html(inv, rel, text)
        elif kind == "react" or (kind == "script" and re.search(
                r"useState|from ['\"]react['\"]|from ['\"]recharts['\"]", text)):
            fw = scan_react(inv, rel, text)
        elif kind == "script" and "Plotly." in text:
            fw = scan_html(inv, rel, text)
        else:
            continue
        if len(inv.items) > before or fw != "python":
            inv.files.append(rel)
            inv.frameworks[rel] = fw
    def order(item):
        path, _, line = item["where"].rpartition(":")
        if not line.isdigit():
            path, line = item["where"], "0"
        return (path, int(line))
    inv.items.sort(key=order)
    for number, item in enumerate(inv.items, 1):
        item["number"] = f"E{number:02d}"
    return inv


KIND_ORDER = [("page", "Pages"), ("layout", "Layout"), ("input", "Inputs"),
              ("output", "Outputs"), ("reactivity", "Reactivity"), ("data", "Data"),
              ("style", "Look"), ("note", "Notes")]


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def element_text(item):
    parts = [item["widget"]]
    if item["id"]:
        parts.append(f"id `{item['id']}`")
    if item["label"]:
        parts.append(f"\"{item['label']}\"")
    if item["details"]:
        parts.append(f"({item['details']})")
    return " ".join(parts)


def write_markdown(inv, target):
    lines = [f"# Prototype inventory: {Path(target).name}", "",
             "Written by scan_prototype.py. A starting point for `ingest/mapping-table.md`: "
             "confirm every row in the code, fill in every \"?\", and add what the scanner "
             "cannot see (computations inside functions, data shapes, colors).", "",
             "| File | Framework |", "|---|---|"]
    for rel in inv.files:
        lines.append(f"| {cell(rel)} | {inv.frameworks.get(rel, '')} |")
    header = ["| # | Prototype element | Where | Spotfire element | Fidelity | "
              "Substitute and reason | Owner decision |",
              "|---|---|---|---|---|---|---|"]
    for kind, title in KIND_ORDER:
        items = [i for i in inv.items if i["kind"] == kind]
        if not items:
            continue
        lines += ["", f"## {title}", ""] + header
        for item in items:
            reason = (f"{item['gap']}: {item['note']}" if item["gap"] else item["note"])
            lines.append(f"| {item['number']} | {cell(element_text(item))} | "
                         f"{cell(item['where'])} | {cell(item['spotfire'] or '?')} | "
                         f"{item['fidelity'] or '?'} | {cell(reason)} | |")
    gaps = [i for i in inv.items if i["gap"]]
    lines += ["", "## Gaps to resolve with the owner", ""]
    if gaps:
        lines += ["| # | Gap | Element | Where |", "|---|---|---|---|"]
        for item in gaps:
            lines.append(f"| {item['number']} | {item['gap']} {GAPS.get(item['gap'], '')} | "
                         f"{cell(element_text(item))} | {cell(item['where'])} |")
    else:
        lines.append("No gap constructs found by the scanner. Read the code for others.")
    unresolved = [i for i in inv.items if i["fidelity"] in ("", "?")]
    lines += ["", f"{len(inv.items)} elements, {len(gaps)} gap flags, "
              f"{len(unresolved)} to resolve by reading the code.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("target", help="prototype file or folder")
    parser.add_argument("--out", default=".", help="folder for the inventory files "
                        "(the app's ingest folder)")
    args = parser.parse_args()
    if not Path(args.target).exists():
        print(f"not found: {args.target}", file=sys.stderr)
        return 2
    inv = scan(args.target)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "prototype-inventory.md").write_text(write_markdown(inv, args.target),
                                                encoding="utf-8")
    (out / "prototype-inventory.json").write_text(
        json.dumps({"files": inv.frameworks, "elements": inv.items}, indent=2),
        encoding="utf-8")
    gaps = sum(1 for i in inv.items if i["gap"])
    print(f"{len(inv.items)} elements in {len(inv.files)} files, {gaps} gap flags")
    print(f"wrote {out / 'prototype-inventory.md'} and prototype-inventory.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
