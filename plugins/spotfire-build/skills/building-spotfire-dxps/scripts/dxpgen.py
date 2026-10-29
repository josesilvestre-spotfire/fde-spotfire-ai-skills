#!/usr/bin/env python3
"""dxpgen - app spec (spec.json) -> validated, resolved -> ONE IronPython 3.4 builder for Spotfire Analyst.

Part of the building-spotfire-dxps skill. CPython 3.10 or newer, standard library only. Contract:
references/architecture.md and references/spec-format.md.

Commands
  new <AppSlug> [--name "App Name"]      scaffold $DXP_WORKSPACE/apps/<AppSlug>/ (spec.json, data/, html/,
                                         scripts/, datafunctions/, build/)
  validate <app> [--json]                numbered errors and warnings, each with the path to the field
                                         (also customer-ready text: textlint.py; reference-line types)
  build <app> [--tier T] [--clipboard]   validate (abort on errors), resolve the spec, write
                                         build/build_<AppSlug>_<tier>.py and build/MANUAL-STEPS-<tier>.md,
                                         check the builder (parse, lines <= 79, ASCII, names, lint_ipy.py,
                                         Spotfire's IronPython parser, sfapi.py members) and print the run
                                         instructions; --clipboard copies it. Tiers: standard (default, the
                                         standard engine: engine/ + t3/), quick, compact (quickest), report
                                         and slim (exceptions, when a standard build has issues or the spec
                                         needs a feature the standard engine lacks: "not in the standard
                                         engine yet: use --tier slim"), full (the whole concatenated
                                         library, about 450 KB: library development only).
  release <app> --version vX.Y [--notes "..."] [--force] [--tier T]
                                         every handover: copy the runtime files (spec.json, DESIGN.md,
                                         html/, scripts/, datafunctions/, tools/, actionmod/ without
                                         node_modules, the referenced data/ files, build/RUN-STEPS.md) to
                                         <app>/versions/vX.Y/, generate the builder from that copy (HOME =
                                         the version folder, the DXP saves into versions/vX.Y/build/),
                                         check it, and add the version to versions/README.md. Never
                                         overwrites a version folder (--force: only one without a saved
                                         DXP). Leaves out source/, _work/, devtests/, docs/, build/session/.
  verify <app>                           run verify_dxp.py check <app folder>

<app> is an app folder, its spec.json, or an app slug under $DXP_WORKSPACE/apps/ (DXP_BUILDER_HOME is
accepted as an older name of DXP_WORKSPACE). The API index for the member checks: SFAPI_INDEX, else the
newest $DXP_WORKSPACE/api/spotfire-api-*.json (write it with dump_api.ps1); without one the member
checks are skipped with a note.
Options for validate/build: --no-lint (skip lint_ipy.py; for build also ipy_parse.ps1 and sfapi.py),
--no-sanitize (skip the check of text-area HTML against dxpgen's emulation of Spotfire's default HTML
sanitizer), --tools-dir DIR (where lint_ipy.py / ipy_parse.ps1 / sfapi.py / verify_dxp.py live; default:
this folder).
Exit codes: 0 ok, 1 validation errors (or the generated builder fails its checks, or verify fails),
2 usage (bad arguments, app or tool not found, refusing to overwrite).

This tool never runs anything in Spotfire. You paste the builder into Analyst's script editor and click
Run Script, or run it unattended with the running-spotfire-unattended skill.
"""
import argparse
import ast
import base64
import builtins
import codecs
import concurrent.futures
import copy
import csv
import datetime
import difflib
import hashlib
import html.parser
import json
import keyword
import os
import pprint
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
SKILL_DIR = TOOL_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
import t3  # noqa: E402  (standard engine: style layer, spec -> HOME/STYLE/APP, tiers)
from t3 import mod as t3mod  # noqa: E402  (mod visuals: manifest axes and properties, value typing)
import textlint  # noqa: E402  (customer-ready text check: app.textLint, app.bannedTerms)
import sfenv  # noqa: E402  (DXP_WORKSPACE, SFAPI_INDEX, SPOTFIRE_HOME, SPOTFIRE_PYTHON)
LIB_DIR = TOOL_DIR / "lib"
WORKSPACE_ENV = sfenv.WORKSPACE_ENV

EXIT_OK, EXIT_INVALID, EXIT_USAGE = 0, 1, 2

# ---------------------------------------------------------------------------------------------
# references/spec-format.md vocabulary
# ---------------------------------------------------------------------------------------------
DATA_TYPES = ("String", "Integer", "LongInteger", "Real", "SingleReal", "Currency", "Date", "DateTime",
              "Time", "TimeSpan", "Boolean", "Binary")
NUMERIC_TYPES = ("Integer", "LongInteger", "Real", "SingleReal", "Currency")
PARAM_TYPES = ("String", "Integer", "LongInteger", "Real", "SingleReal", "Boolean", "Date", "DateTime",
               "Time", "TimeSpan", "Currency", "Page", "Visualization", "DataTable")
NODE_PARAM_TYPES = ("Page", "Visualization", "DataTable")
NAMING_POLICIES = ("program", "camelCase")
HTML_MODES = ("safe", "rich")
THEMES = ("LightSfx", "DarkSfx", "Light", "Dark")
NAVIGATION_MODES = ("Tabs", "Links", "None", "Off")
EMPTY_MARKING_BEHAVIORS = ("ShowAll", "ShowEmpty", "ShowMessage")
SOURCE_TYPES = ("sbdf", "csv", "dataFunction")
ENGINES = ("python", "terr")
REFRESH_MODES = ("automatic", "manual")

VISUAL_TYPES = ("lineChart", "barChart", "combinationChart", "scatterPlot", "scatterPlot3D", "pieChart",
                "boxPlot", "heatMap", "treemap", "waterfallChart", "histogram", "table", "crossTable",
                "summaryTable", "graphicalTable", "kpiChart", "map", "textArea", "mod")

# visual type -> content class the visual `settings` paths are relative to (resolved in the API index)
CONTENT_CLASS = {
    "lineChart": "LineChart", "barChart": "BarChart", "combinationChart": "CombinationChart",
    "scatterPlot": "ScatterPlot", "scatterPlot3D": "ScatterPlot3D", "pieChart": "PieChart",
    "boxPlot": "BoxPlot", "heatMap": "HeatMap", "treemap": "Treemap", "waterfallChart": "WaterfallChart",
    "histogram": "BarChart", "table": "TablePlot", "crossTable": "CrossTablePlot",
    "summaryTable": "SummaryTable", "graphicalTable": "Miniatures.GraphicalTable", "kpiChart": "KpiChart",
    "map": "Maps.MapChart", "textArea": "HtmlTextArea", "mod": "Mods.ModVisualization",
}
# Content classes with Layers.AddNewReferenceLayer() and FittingModels (checked in the 15.0 index).
REFERENCE_LAYER_TYPES = ("lineChart", "barChart", "combinationChart", "scatterPlot", "boxPlot",
                         "waterfallChart", "histogram")
FITTING_MODEL_TYPES = REFERENCE_LAYER_TYPES
COLOR_BY_TYPES = ("lineChart", "barChart", "combinationChart", "scatterPlot", "scatterPlot3D", "boxPlot",
                  "treemap", "waterfallChart", "histogram")

# lib function per visual type and the module expected to define it (references/architecture.md, Library)
VISUAL_MODULE = {
    "vis_line": "60_charts.py", "vis_bar": "60_charts.py", "vis_combination": "60_charts.py",
    "vis_scatter": "60_charts.py", "vis_scatter3d": "60_charts.py", "vis_pie": "60_charts.py",
    "vis_box": "60_charts.py", "vis_heatmap": "60_charts.py", "vis_treemap": "60_charts.py",
    "vis_waterfall": "60_charts.py", "vis_histogram": "60_charts.py", "vis_common": "60_charts.py",
    "vis_table": "70_tables.py", "vis_crosstable": "70_tables.py", "vis_summary": "70_tables.py",
    "vis_graphical": "70_tables.py", "vis_kpi": "70_tables.py", "vis_map": "75_maps.py",
    "vis_textarea": "80_textareas.py", "vis_mod": "85_mods.py",
}

CONTROL_KINDS = ("label", "input", "multilineInput", "dropdown", "listbox", "multiSelectListbox", "slider",
                 "checkbox", "radio", "button", "link")
PROPERTY_CONTROL_KINDS = CONTROL_KINDS[:9]
VALUE_SOURCE_KINDS = ("dropdown", "listbox", "multiSelectListbox", "radio")
ACTION_KEYS = ("gotoPage", "applyBookmark", "refreshDataFunction")

RULE_FIELDS = {"greaterThan": ("value",), "lessThan": ("value",), "equal": ("value",),
               "between": ("low", "high"), "top": ("count",), "bottom": ("count",),
               "expression": ("expression",)}
_CC = "Spotfire.Dxp.Application.Visuals.ConditionalColoring."
RULE_CLASSES = {"greaterThan": [_CC + "ThresholdColorRule"], "lessThan": [_CC + "ThresholdColorRule"],
                "equal": [_CC + "ThresholdColorRule", _CC + "StringColorRule"],
                "between": [_CC + "RangeColorRule"], "top": [_CC + "TopBottomColorRule"],
                "bottom": [_CC + "TopBottomColorRule"], "expression": [_CC + "ExpressionColorRule"]}
COLORING_CLASS = _CC + "Coloring"
REFERENCE_LAYER_CLASS = "Spotfire.Dxp.Application.Visuals.ReferenceElements.ReferenceLayer"
FITTING_CLASSES = {"straightLine": "Spotfire.Dxp.Application.Visuals.FittingModels.StraightLineFittingModel",
                   "curve": "Spotfire.Dxp.Application.Visuals.FittingModels.ReferenceCurveFittingModel"}
_MAPS = "Spotfire.Dxp.Application.Visuals.Maps."
MAP_LAYER_CLASSES = {"tile": (None, _MAPS + "StandardTileLayer"),
                     "marker": (_MAPS + "MarkerLayerVisualization", _MAPS + "MapChartDataLayer"),
                     "feature": (_MAPS + "FeatureLayerVisualization", _MAPS + "MapChartDataLayer")}
DATA_TABLE_CLASS = "Spotfire.Dxp.Data.DataTable"
DATA_COLUMN_CLASS = "Spotfire.Dxp.Data.DataColumn"
DATA_FUNCTION_CLASS = "Spotfire.Dxp.Data.DataFunctions.DataFunction"          # dataFunctions[].settings
KPI_CLASS = "Spotfire.Dxp.Application.Visuals.KpiVisualization"              # kpis[].settings
_MINI = "Spotfire.Dxp.Application.Visuals.Miniatures."
GT_COLUMN_CLASSES = {"sparkline": _MINI + "SparklineMiniatureVisualization",    # graphical-table columns[].settings
                     "calculatedValue": _MINI + "CalculatedValueMiniatureVisualization",
                     "icon": _MINI + "IconMiniatureVisualization",
                     "bulletGraph": _MINI + "BulletGraphMiniatureVisualization"}
GT_RULE_CLASSES = {"calculatedValue": _MINI + "CalculatedValueRule", "icon": _MINI + "IconRule"}
REFERENCE_LAYER_KINDS = ("horizontalLine", "verticalLine", "band")
FITTING_KINDS = ("straightLine", "curve")
DASHES = ("solid", "dot", "dash", "double")
GT_KINDS = ("sparkline", "calculatedValue", "icon", "bulletGraph")
MAP_LAYER_KINDS = ("tile", "marker", "feature")
# Map layer fields: the library's (lib/75_maps.py) and the standard engine's (the scatter vocabulary,
# the visual data limits per layer, the default marker shape; references/spec-format.md "Maps").
MAP_LAYER_KEYS = ("kind", "table", "latitude", "longitude", "geometry", "colorBy", "sizeBy", "lineBy", "title",
                  "settings", "coloring", "labelBy", "labels", "markerSize", "shape", "shapeBy", "marking",
                  "limitByMarkings", "emptyMarkingBehavior", "limitExpression")
MAP_ENGINE_KEYS = ("labelBy", "labels", "markerSize", "shape", "shapeBy", "marking", "limitByMarkings",
                   "emptyMarkingBehavior", "limitExpression")
# Spotfire.Dxp.Application.Visuals.MarkerType (shape of scatter and map markers; Custom needs a file)
MARKER_TYPES = ("Square", "Circle", "Diamond", "TriangleUp", "TriangleDown", "TriangleLeft", "TriangleRight",
                "StarFour", "StarFive", "Pentagon", "HorizontalRectangle", "VerticalRectangle", "Plus", "Cross",
                "SquareOutline", "CircleOutline", "DiamondOutline", "TriangleUpOutline", "TriangleDownOutline",
                "TriangleLeftOutline", "TriangleRightOutline", "StarFourOutline", "StarFiveOutline",
                "PentagonOutline", "HorizontalRectangleOutline", "VerticalRectangleOutline", "PlusOutline",
                "CrossOutline", "HorizontalLine", "VerticalLine", "PlusLine", "CrossLine", "StarSixLine",
                "RightPointingArrow", "LeftPointingArrow", "UpPointingArrow", "DownPointingArrow",
                "RightPointingArrowOutline", "LeftPointingArrowOutline", "UpPointingArrowOutline",
                "DownPointingArrowOutline", "RightPointingArrowLine", "LeftPointingArrowLine",
                "UpPointingArrowLine", "DownPointingArrowLine")

# Built-in document properties: exempt from naming, never created (standards N13).
BUILTIN_PROPERTIES = ("MaxMissingTimeParts", "FiscalYearOffset", "Spotfire.Versioning.Pruning.MaxVersions",
                      "Description", "Keywords", "AllowWebPlayerResume", "PublicBookmarkCreation",
                      "PrivateBookmarkCreation", "spotfire.Comments", "spotfire.versioning.enabled",
                      "Preview.Thumb", "Preview.Mode")

# Known fields (anything else is a warning: the builder ignores it)
TOP_KEYS = ("specVersion", "app", "tables", "defaultTable", "relations", "markings", "filteringSchemes",
            "properties", "dataFunctions", "scripts", "triggers", "actionMods", "vizMods", "filterPanelLayout",
            "pages", "activePage")
APP_KEYS = ("name", "description", "keywords", "output", "namingPolicy", "htmlMode", "theme",
            "pageNavigation", "canvas", "snapshots", "minimumSpotfireVersion", "style", "textLint",
            "bannedTerms")
# validate-only app keys (scripts/textlint.py); resolve_spec drops them so they never reach a builder
VALIDATE_ONLY_APP_KEYS = ("textLint", "bannedTerms")
TABLE_KEYS = ("name", "source", "description", "columns", "calculatedColumns", "hierarchies", "embed",
              "settings")
SOURCE_KEYS = {"sbdf": ("type", "path"),
               "csv": ("type", "path", "separator", "culture", "encoding", "header", "columns"),
               "dataFunction": ("type", "function", "output")}
PROPERTY_KEYS = ("name", "type", "default", "description", "listValued")
DF_KEYS = ("name", "description", "engine", "script", "scriptCode", "inputs", "outputs", "refresh",
           "executeAtBuild", "settings")
DF_INPUT_KEYS = ("name", "type", "dataTypes", "bind", "description")
DF_OUTPUT_KEYS = ("name", "type", "target", "description")
BIND_KEYS = {"table": ("table", "columns", "limitByFiltering", "limitByMarking"),
             "column": ("table", "column", "limitByFiltering", "limitByMarking"),
             "value": ("property", "value", "expression", "limitByFiltering", "limitByMarking")}
SCRIPT_KEYS = ("name", "description", "file", "code", "parameters", "transaction")
PAGE_KEYS = ("title", "visible", "filterPanel", "detailsOnDemand", "filteringScheme", "filters", "visuals",
             "layout")
COMMON_VISUAL_KEYS = ("id", "type", "title", "showTitle", "description", "table", "marking",
                      "limitByMarkings", "emptyMarkingBehavior", "limitExpression", "useFiltering", "legend",
                      "coloring", "referenceLayers", "fittingModels", "settings", "postScript", "actionTriggers")
TEXT_AREA_COMMON_KEYS = ("id", "type", "title", "showTitle", "description", "settings", "postScript",
                         "actionTriggers")
# legend.hide item kinds (engine/features/legend.py maps them to the LegendItem types)
LEGEND_HIDE_KINDS = ("filtering", "marking", "lineBy", "colorBy", "referenceLayers", "trellis")
# on a map, legend.hide applies to every data layer's own legend (engine/builders/map.py
# map_layer_legends); the map's own legend holds only the title, description and trellis items
MAP_LEGEND_HIDE_KINDS = ("filtering", "marking", "lineBy", "colorBy", "trellis", "markerBy", "shape", "size",
                         "rotation", "limits", "dataTable", "layerTitle")
# legend.hide on a mod visual: the main view's legend items (standard engine)
MOD_LEGEND_HIDE_KINDS = ("filtering", "marking", "colorBy")
# Scatter plots and map marker layers aggregate their markers unless the marker-by has baserowid():
# these fields must then be aggregated (sfexpr.unaggregated), with the aggregation the message suggests
MARKER_AGG_FIELDS = (("labelBy", "First"), ("sizeBy", "Avg"))
MARKER_AGG_SETTINGS = (("LabelColumn.Expression", "First"), ("SizeAxis.Expression", "Avg"),
                       ("LineConnection.OrderAxis.Expression", "Avg"), ("RotationAxis.Expression", "Avg"))
# visual action triggers (where Analyst shows an action-mod action; a manual step, no public API)
TRIGGER_DISPLAYS = ("FloatingButton", "TitleBarButton", "ContextMenuItem")
# settings shorthands on visuals: the limiting-marking options live on the visual's Data
SETTINGS_ALIASES = {"LimitingMarkingsEmptyBehavior": "Data.LimitingMarkingsEmptyBehavior",
                    "LimitingMarkingsEmptyMessage": "Data.LimitingMarkingsEmptyMessage"}
SCALE_DEFAULTS = (("min", None), ("max", None), ("log", False), ("gridlines", True),
                  ("individualScaling", False), ("title", None))
# What resolve_spec fills into a scale object the spec gives. 'gridlines' is left out on purpose:
# lib/60_charts.py keeps Spotfire's own default for an axis whose scale has no 'gridlines' (Y gridlines
# on, X off, like charts made in Analyst); filling SPEC's "gridlines": true would switch X gridlines on
# for every chart that only sets, say, xScale.min.
SCALE_FILL = tuple(kv for kv in SCALE_DEFAULTS if kv[0] != "gridlines")

# Visual-specific fields and their kinds (see Validator.check_kind). references/spec-format.md fields plus what lib/60_charts.py
# reads beyond them: axis lists (y = several measures, x and categorical axes = nested levels), xScale on every
# scaled chart, zScale on the 3D scatter, labels on scatter/pie/waterfall/histogram, colorBy on pie/heat map.
VISUAL_FIELDS = {
    "lineChart": {"x": "exprs", "y": "exprs", "colorBy": "expr", "lineBy": "exprs", "trellis": "trellis",
                  "xScale": "scale", "yScale": "scale", "showMarkers": "bool", "lineWidth": "linewidth",
                  "steps": "bool"},
    "barChart": {"x": "exprs", "y": "exprs", "colorBy": "expr", "orientation": ("ci", "vertical", "horizontal"),
                 "stack": ("ci", "stacked", "sideBySide", "percent"), "sort": ("ci", "none", "ascending", "descending"),
                 "labels": "labels", "trellis": "trellis", "xScale": "scale", "yScale": "scale"},
    "combinationChart": {"x": "exprs", "series": "series", "colorBy": "expr", "secondaryScale": "exprlist",
                         "trellis": "trellis", "xScale": "scale", "yScale": "scale"},
    "scatterPlot": {"x": "exprs", "y": "exprs", "colorBy": "expr", "sizeBy": "expr", "shapeBy": "exprs",
                    "labelBy": "expr", "labels": "labels", "markerSize": "markersize", "lineBy": "exprs",
                    "trellis": "trellis", "xScale": "scale", "yScale": "scale", "shape": "markertype"},
    "scatterPlot3D": {"x": "exprs", "y": "exprs", "z": "exprs", "colorBy": "expr", "sizeBy": "expr",
                      "trellis": "trellis", "xScale": "scale", "yScale": "scale", "zScale": "scale"},
    "pieChart": {"sector": "exprs", "size": "expr", "colorBy": "expr", "labels": "labels", "trellis": "trellis"},
    "boxPlot": {"x": "exprs", "y": "exprs", "colorBy": "expr", "trellis": "trellis", "xScale": "scale",
                "yScale": "scale"},
    "heatMap": {"x": "exprs", "y": "exprs", "value": "expr", "colorBy": "expr", "trellis": "trellis",
                "xScale": "scale", "yScale": "scale"},
    "treemap": {"hierarchy": "exprs", "size": "expr", "colorBy": "expr", "trellis": "trellis"},
    "waterfallChart": {"category": "exprs", "value": "expr", "colorBy": "expr", "labels": "labels",
                       "trellis": "trellis", "xScale": "scale", "yScale": "scale"},
    "histogram": {"column": "expr", "bins": "posint", "colorBy": "expr", "labels": "labels", "trellis": "trellis",
                  "xScale": "scale", "yScale": "scale"},
    "table": {"columns": "strlist", "sort": "tablesort", "widths": "widths"},
    "crossTable": {"rows": "exprs", "columns": "exprs", "measures": "exprlist", "totals": "totals"},
    "summaryTable": {"columns": "strlist", "statistics": "strlist"},
    "graphicalTable": {"rows": "exprs", "columns": "gtcolumns"},
    "kpiChart": {"kpis": "kpis"},
    "map": {"layers": "layers", "autoZoom": "bool", "extent": "extent", "interactiveLayer": "any"},
    "textArea": {"html": "any", "css": "any", "js": "any", "controls": "any"},
    "mod": {"modId": "expr", "axes": "modaxes", "properties": "dict", "layers": "any"},
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
PROPERTY_NAME_RE = re.compile(r"^[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*$")
VISUAL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
SETTINGS_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*control\s*:\s*([^{}\s]+)\s*\}\}")   # same as lib/80_textareas.py
BAD_SCRIPT_NAME_CHARS = '\\/":*?<>|'
BAD_FILE_NAME_CHARS = '\\/:*?"<>|'
# ScriptDefinition.Create rejects these parameter names (lib/40_scripts.py)
PY_RESERVED = ("False", "None", "True", "and", "as", "assert", "async", "await", "break", "class",
               "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
               "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
               "while", "with", "yield")
INT32 = (-2147483648, 2147483647)
INT64 = (-9223372036854775808, 9223372036854775807)

LINT_LINE_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?P<level>error|warning): (?P<msg>.*)$")


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


KIND_CHECK = {"str": is_str, "bool": is_bool, "int": is_int, "num": is_num,
              "list": lambda v: isinstance(v, list), "dict": lambda v: isinstance(v, dict)}
KIND_LABEL = {"str": "a string", "bool": "true or false", "int": "a whole number", "num": "a number",
              "list": "a list", "dict": "an object"}


def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "a boolean"
    if isinstance(v, int):
        return "a whole number"
    if isinstance(v, float):
        return "a number"
    if isinstance(v, str):
        return "a string"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "an object"
    return type(v).__name__


def describe(v):
    """Type and a short rendering of a JSON value, for messages."""
    if isinstance(v, (dict, list)):
        return type_name(v)
    text = json.dumps(v, ensure_ascii=False)
    if len(text) > 60:
        text = text[:57] + "..."
    return type_name(v) + " " + text


def pjoin(base, *parts):
    """JSON-ish path: pjoin('pages', 0, 'visuals', 2, 'x') -> pages[0].visuals[2].x"""
    out = base or ""
    for p in parts:
        if isinstance(p, int):
            out += "[%d]" % p
        elif _IDENT_RE.match(str(p)):
            out += ("." if out else "") + str(p)
        else:
            out += "[" + json.dumps(str(p), ensure_ascii=False) + "]"
    return out


def did_you_mean(word, candidates):
    if not isinstance(word, str):
        return ""
    pool = [c for c in candidates if isinstance(c, str)]
    hits = difflib.get_close_matches(word, pool, n=1, cutoff=0.6)
    if not hits:
        low = {c.lower(): c for c in pool}
        if word.lower() in low:
            hits = [low[word.lower()]]
    return (" (did you mean '%s'?)" % hits[0]) if hits else ""


def vtuple(text):
    try:
        return tuple(int(x) for x in str(text).split("."))
    except ValueError:
        return ()


def newer_than(api_version, minimum):
    """True when an [api x.y] version is newer than the minimum Spotfire version (both 'a.b[.c]')."""
    if not api_version:
        return False
    a, m = vtuple(api_version), vtuple(minimum)
    if not a or not m:
        return False
    width = max(len(a), len(m))
    return a + (0,) * (width - len(a)) > m + (0,) * (width - len(m))


def as_list(v):
    return v if isinstance(v, list) else []


def one_or_many(v):
    """A spec field that holds one value or a list of them, as a list (None -> [])."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def short_type(full):
    """Spotfire.Dxp.Application.Visuals.ScaleAxis -> ScaleAxis (generic arguments shortened too)."""
    return re.sub(r"[A-Za-z_][\w]*\.(?=[A-Za-z_])", "", str(full or ""))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_text_file(path):
    """(text, None) or (None, reason). UTF-8, BOM tolerated, newlines normalized to \\n."""
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return None, str(e)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return None, "not UTF-8 (%s); save the file as UTF-8" % e
    return text.replace("\r\n", "\n").replace("\r", "\n"), None


# ---------------------------------------------------------------------------------------------
# naming policy (references/architecture.md, Naming)
# ---------------------------------------------------------------------------------------------
_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of", "on",
                "or", "per", "the", "to", "vs", "vs.", "via", "with", "over", "than", "versus"}
_PASCAL_SEG = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_SEG = re.compile(r"^[a-z][A-Za-z0-9]*$")
_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_LOWER_TABLE = re.compile(r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)*|[a-z][A-Za-z0-9]*)$")
_TYPE_PREFIX_PASCAL = re.compile(r"^(?:Str|Int|Dbl|Flt|Bool|Bln|Lst|Arr|Obj|Txt)[A-Z]")
_TYPE_PREFIX_CAMEL = re.compile(r"^(?:str|int|dbl|flt|bool|bln|dt|lst|arr|obj|txt)[A-Z]")
# numbering prefixes: "1. Overview", "1A. Discover", "2) Detail", "01_Data", "3 - Events", "01 Overview"
# (not "3D Scatter", "10 Year Forecast", "24 Hour Trend")
_NUMBERING = re.compile(r"^\s*(?:\d{1,3}[A-Za-z]?[.):_]|\d{1,3}\s*-\s|0\d\s)")
# Spotfire's own de-duplication suffix "Marking (2)" and "Untitled ..." (not "Production (2023)")
_AUTO_NAME = re.compile(r"\(\d{1,2}\)\s*$|^\s*untitled\b", re.I)


def _words(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def suggest_pascal(name):
    return ".".join("".join(w[:1].upper() + w[1:].lower() for w in _words(seg)) or seg
                    for seg in name.split(".")) or name


def suggest_camel(name):
    out = []
    for seg in name.split("."):
        ws = _words(seg)
        out.append((ws[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in ws[1:])) if ws else seg)
    return ".".join(out)


def suggest_upper_snake(name):
    return "_".join(w.upper() for w in _words(name)) or name


def suggest_title(name):
    parts = re.split(r"(\s+)", name.replace("_", " ").strip())
    out = []
    first = True
    for p in parts:
        if not p.strip():
            out.append(p)
            continue
        if p.startswith(("(", "[")) or (not first and p.lower() in _SMALL_WORDS):
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
        first = False
    return "".join(out)


def title_case_problem(text):
    t = re.sub(r"\\?\$\{[^}]*\}", " ", text)            # live ${...} expressions
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)          # units in parentheses / brackets
    if "_" in t:
        return "uses underscores; Title Case uses spaces"
    words = [w for w in re.split(r"[\s/&+,:;\-]+", t) if w]
    for i, w in enumerate(words):
        core = w.strip(".'\"!?")
        if not core or not core[0].isalpha() or core[0].isupper():
            continue
        if i > 0 and core.lower() in _SMALL_WORDS:
            continue
        return "'%s' should start with a capital letter (Title Case)" % core
    return None


def naming_issues(kind, name, policy):
    """[(level, message)] for a name that breaks the naming policy (references/architecture.md, Naming).

    kind: property, table, function, script, jsScript, column, page, marking, scheme."""
    out = []
    if not isinstance(name, str) or not name:
        return out
    if kind == "property" and name in BUILTIN_PROPERTIES:
        return out
    if _AUTO_NAME.search(name):
        out.append(("error", "'%s' looks auto-generated ('(2)', 'Untitled'); give it a real name" % name))
    if kind == "property":
        segs = name.split(".")
        if policy == "camelCase":
            if not all(_CAMEL_SEG.match(s) for s in segs):
                out.append(("error", "'%s' must be camelCase (camelCase naming policy), e.g. '%s'"
                            % (name, suggest_camel(name))))
            elif _TYPE_PREFIX_CAMEL.match(segs[0]):
                out.append(("warning", "'%s' looks like it carries a type prefix; use a plain name" % name))
        else:
            if not all(_PASCAL_SEG.match(s) and re.search("[a-z]", s) for s in segs):
                out.append(("error", "'%s' must be PascalCase with no spaces or underscores (program naming "
                            "policy), e.g. '%s'" % (name, suggest_pascal(name))))
            elif _TYPE_PREFIX_PASCAL.match(segs[0]):
                out.append(("warning", "'%s' looks like it carries a type prefix; the program policy wants "
                            "plain PascalCase" % name))
    elif kind == "table":
        if policy == "camelCase":
            if not _LOWER_TABLE.match(name):
                out.append(("error", "table '%s' must be lowercase or camelCase (camelCase naming policy), "
                            "e.g. '%s'" % (name, suggest_camel(name))))
        elif not _UPPER_SNAKE.match(name):
            out.append(("error", "table '%s' must be UPPER_SNAKE_CASE (program naming policy), e.g. '%s'"
                        % (name, suggest_upper_snake(name))))
    elif kind in ("function", "script", "jsScript"):
        what = {"function": "data function", "script": "script", "jsScript": "JavaScript file name"}[kind]
        if policy == "camelCase":
            if not _CAMEL_SEG.match(name):
                out.append(("error", "%s '%s' must be camelCase (camelCase naming policy), e.g. '%s'"
                            % (what, name, suggest_camel(name))))
        else:
            problem = title_case_problem(name)
            if problem:
                out.append(("error", "%s '%s' must be Title Case \"Verb Object\" (program naming policy): %s; "
                            "e.g. '%s'" % (what, name, problem, suggest_title(name))))
            elif len(name.split()) < 2:
                out.append(("warning", "%s '%s' should be \"Verb Object\", e.g. 'Calculate %s'"
                            % (what, name, name)))
    elif kind == "column":
        if policy != "camelCase":
            problem = title_case_problem(name)
            if problem:
                out.append(("error", "column '%s' must be Title Case with units in parentheses (program "
                            "naming policy): %s; e.g. '%s'" % (name, problem, suggest_title(name))))
    elif kind in ("page", "marking", "scheme"):
        what = {"page": "page title", "marking": "marking", "scheme": "filtering scheme"}[kind]
        if _NUMBERING.match(name):
            out.append(("error", "%s '%s' starts with a number; no numbering prefixes" % (what, name)))
        problem = title_case_problem(name)
        if problem:
            out.append(("error", "%s '%s' must be Title Case: %s; e.g. '%s'"
                        % (what, name, problem, suggest_title(name))))
    return out


# ---------------------------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------------------------
class Report(object):
    """Numbered errors (block the build), warnings and notes (checks that could not run)."""

    def __init__(self):
        self.items = []
        self._seen = set()

    def add(self, level, path, message):
        key = (level, path or "", message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append({"level": level, "path": path or "(spec)", "message": message})

    def error(self, path, message):
        self.add("error", path, message)

    def warn(self, path, message):
        self.add("warning", path, message)

    def note(self, message):
        self.add("note", "", message)

    def extend(self, other):
        for item in other.items:
            self.add(item["level"], item["path"], item["message"])

    def _of(self, level):
        return [i for i in self.items if i["level"] == level]

    @property
    def errors(self):
        return self._of("error")

    @property
    def warnings(self):
        return self._of("warning")

    @property
    def notes(self):
        return self._of("note")

    def render(self, title=None):
        lines = []
        if title:
            lines.append(title)
        errors, warnings, notes = self.errors, self.warnings, self.notes
        if errors:
            lines.append("")
            lines.append("Errors (%d):" % len(errors))
            for n, item in enumerate(errors, 1):
                lines.append("  E%d. %s: %s" % (n, item["path"], item["message"]))
        if warnings:
            lines.append("")
            lines.append("Warnings (%d):" % len(warnings))
            for n, item in enumerate(warnings, 1):
                lines.append("  W%d. %s: %s" % (n, item["path"], item["message"]))
        if notes:
            lines.append("")
            lines.append("Notes:")
            for item in notes:
                lines.append("  - " + item["message"])
        lines.append("")
        lines.append("Result: %d error%s, %d warning%s." % (len(errors), "" if len(errors) == 1 else "s",
                                                            len(warnings), "" if len(warnings) == 1 else "s"))
        return "\n".join(lines)

    def as_dict(self):
        return {"errors": [{"n": n, "path": i["path"], "message": i["message"]}
                           for n, i in enumerate(self.errors, 1)],
                "warnings": [{"n": n, "path": i["path"], "message": i["message"]}
                             for n, i in enumerate(self.warnings, 1)],
                "notes": [i["message"] for i in self.notes]}


# ---------------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------------
def parse_spec_text(text):
    """(spec, duplicate keys). Raises ValueError (incl. json.JSONDecodeError) for invalid JSON."""
    dups = []

    def pairs_hook(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                dups.append(k)
            obj[k] = v
        return obj

    def bad_constant(name):
        raise ValueError("%s is not allowed in spec.json (use a number or null)" % name)

    return json.loads(text, object_pairs_hook=pairs_hook, parse_constant=bad_constant), dups


def load_spec(spec_path, report):
    """Read and parse spec.json; problems go into the report. Returns (spec or None, raw bytes)."""
    try:
        raw = Path(spec_path).read_bytes()
    except OSError as e:
        report.error("spec.json", "cannot read %s: %s" % (spec_path, e))
        return None, b""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        report.error("spec.json", "not UTF-8: %s" % e)
        return None, raw
    try:
        spec, dups = parse_spec_text(text)
    except json.JSONDecodeError as e:
        report.error("spec.json", "invalid JSON at line %d, column %d: %s (comments are not allowed)"
                     % (e.lineno, e.colno, e.msg))
        return None, raw
    except ValueError as e:
        report.error("spec.json", "invalid JSON: %s" % e)
        return None, raw
    for key in sorted(set(dups)):
        report.error("spec.json", "key '%s' appears twice in one object; JSON keeps only the last one" % key)
    if not isinstance(spec, dict):
        report.error("spec.json", "the spec must be a JSON object, got %s" % type_name(spec))
        return None, raw
    return spec, raw


def workspace_root():
    """$DXP_WORKSPACE (or the older DXP_BUILDER_HOME), else None."""
    return sfenv.workspace_root()


def resolve_app(arg):
    """(app_dir, spec_path) for an app folder, its spec.json or an app slug; None when not found."""
    p = Path(arg)
    if p.is_file():
        p = p.resolve()
        return p.parent, p
    if p.is_dir():
        p = p.resolve()
        return p, p / "spec.json"
    root = workspace_root()
    candidate = root / "apps" / arg if root is not None else None
    if candidate is not None and candidate.is_dir():
        candidate = candidate.resolve()
        return candidate, candidate / "spec.json"
    return None


def app_slug(app_dir):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", Path(app_dir).name) or "App"


# ---------------------------------------------------------------------------------------------
# API index (api/spotfire-api-<build>.json): settings paths -> public, settable properties
# ---------------------------------------------------------------------------------------------
_INT_TYPES = {"System.Int32", "System.Int64", "System.Int16", "System.Byte", "System.SByte", "System.UInt16",
              "System.UInt32", "System.UInt64"}
_FLOAT_TYPES = {"System.Double", "System.Single", "System.Decimal"}
_SUBST_RE = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?![\w.])")


def _split_top(s, sep=","):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return parts


def _apply_subst(s, subst):
    if not subst or not s:
        return s
    return _SUBST_RE.sub(lambda m: subst.get(m.group(0), m.group(0)), s)


def _index_build_key(path):
    m = re.search(r"spotfire-api-([\d.]+)\.json$", path.name)
    return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()


def find_index_file(api_dir=None):
    """The public API index: the newest spotfire-api-*.json in api_dir when given, else SFAPI_INDEX or
    the newest one in $DXP_WORKSPACE/api/ (sfenv.api_index). None when there is none: the member
    checks are then skipped with a note."""
    return sfenv.api_index(api_dir)


class ApiIndex(object):
    """Minimal reader of the public API index: types by name, inherited members, enum values."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.path = Path(path)
        self.product_version = data.get("productVersion", "")
        self.by_full = {}
        self.keys = {}
        for t in data.get("types", []):
            full = t.get("fullName")
            if not full:
                continue
            self.by_full[full] = t
            for k in (full, full.replace("+", "."), t.get("csName")):
                if k and k not in self.keys:
                    self.keys[k] = t

    def find_type(self, name):
        t = self.keys.get(name)
        if t is not None:
            return t
        for prefix in ("Spotfire.Dxp.Application.Visuals.", "Spotfire.Dxp.Application.", "Spotfire.Dxp.Data.",
                       "Spotfire.Dxp.Framework."):
            t = self.keys.get(prefix + name)
            if t is not None:
                return t
        suffix = "." + name
        hits = {}
        for k, t in self.keys.items():
            if k.endswith(suffix):
                hits[t["fullName"]] = t
        return list(hits.values())[0] if len(hits) == 1 else None

    def type_ref(self, type_string, subst=None):
        """(entry or None, generic substitution for the entry, clean type string, nullable)."""
        s = _apply_subst((type_string or "").strip(), subst)
        nullable = False
        if s.endswith("?"):
            nullable, s = True, s[:-1]
        if s.startswith("System.Nullable<") and s.endswith(">"):
            nullable, s = True, s[len("System.Nullable<"):-1]
        if s.endswith("[]"):
            return None, {}, s, nullable
        if "<" in s and s.endswith(">"):
            base = s[:s.index("<")]
            args = _split_top(s[s.index("<") + 1:-1])
            t = self.keys.get(base + "`" + str(len(args)))
            if t is None:
                return None, {}, s, nullable
            names = [g.get("name") for g in t.get("genericParameters", [])]
            return t, dict(zip(names, args)), s, nullable
        return self.keys.get(s), {}, s, nullable

    def _chain(self, t, subst=None):
        """(entry, substitution) for t, its base classes and its interfaces, breadth first."""
        seen = set()
        queue = [(t, subst or {})]
        while queue:
            cur, sb = queue.pop(0)
            if cur is None or cur["fullName"] in seen:
                continue
            seen.add(cur["fullName"])
            yield cur, sb
            refs = ([cur["baseType"]] if cur.get("baseType") else []) + list(cur.get("interfaces") or [])
            for ref in refs:
                nxt = self.by_full.get(ref.get("id"))
                if nxt is None:
                    continue
                names = [g.get("name") for g in nxt.get("genericParameters", [])]
                args = [_apply_subst(a, sb) for a in ref.get("args", [])]
                queue.append((nxt, dict(zip(names, args)) if names and args else {}))

    def member(self, t, name, subst=None):
        """('property'|'field', member, declaring entry, substitution) or None (public members only)."""
        for cur, sb in self._chain(t, subst):
            for p in cur.get("properties") or []:
                if p.get("name") == name and not p.get("indexParams") and p.get("visibility", "public") == "public":
                    return "property", p, cur, sb
            for f in cur.get("fields") or []:
                if f.get("name") == name and f.get("visibility", "public") == "public":
                    return "field", f, cur, sb
        return None

    def has_method(self, t, name):
        for cur, _ in self._chain(t):
            if any(m.get("name") == name for m in cur.get("methods") or []):
                return True
        return False

    def property_names(self, t):
        names = set()
        for cur, _ in self._chain(t):
            for p in cur.get("properties") or []:
                if not p.get("indexParams") and not p.get("isStatic"):
                    names.add(p["name"])
        return sorted(names)

    def static_member(self, t, name):
        for cur, _ in self._chain(t):
            for p in cur.get("properties") or []:
                if p.get("name") == name and p.get("isStatic"):
                    return True
            for f in cur.get("fields") or []:
                if f.get("name") == name and (f.get("isStatic") or f.get("isLiteral")):
                    return True
        return False

    def check_path(self, start, key, value, min_version):
        """Walk 'A.B.C' from the start type like apply_settings (lib/00_core.py) does: every step a
        readable public member, the last one an instance property with a public setter, the value
        convertible to its type. Returns (errors, warnings)."""
        errors, warnings = [], []
        t, sb = start, {}
        segs = key.split(".")
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            tname = short_type(t["fullName"])
            hit = self.member(t, seg, sb)
            if hit is None:
                if self.has_method(t, seg):
                    errors.append("%s.%s is a method, not a property (settings only set public properties; "
                                  "use postScript)" % (tname, seg))
                else:
                    errors.append("%s has no public property '%s'%s"
                                  % (tname, seg, did_you_mean(seg, self.property_names(t))))
                return errors, warnings
            kind, m, decl, msb = hit
            where = "%s.%s" % (short_type(decl["fullName"]), seg)
            version = m.get("apiVersion")
            if last:
                if kind == "property":
                    if m.get("isStatic"):
                        errors.append(where + " is static; settings set instance properties")
                    elif not m.get("hasPublicSetter"):
                        errors.append(where + " is read-only (no public setter)")
                    version = m.get("setApiVersion") or version
                elif m.get("isLiteral") or m.get("isInitOnly"):
                    errors.append(where + " is a read-only field")
                if errors:
                    return errors, warnings
                if newer_than(version, min_version):
                    warnings.append("%s needs Spotfire %s (newer than minimumSpotfireVersion %s)"
                                    % (where, version, min_version))
                if "obsolete" in m:
                    warnings.append("%s is obsolete%s" % (where, (": " + m["obsolete"]) if m.get("obsolete") else ""))
                e2, w2 = self.check_value(m.get("type"), msb, value, where)
                errors.extend(e2)
                warnings.extend(w2)
                return errors, warnings
            if kind == "property" and not m.get("canRead", True):
                errors.append(where + " cannot be read")
                return errors, warnings
            if newer_than(version, min_version):
                warnings.append("%s needs Spotfire %s (newer than minimumSpotfireVersion %s)"
                                % (where, version, min_version))
            nxt, nsb, clean, _ = self.type_ref(m.get("type"), msb)
            if nxt is None:
                warnings.append("cannot check '%s' beyond %s: its type %s is not in the API index"
                                % (key, where, short_type(clean)))
                return errors, warnings
            t, sb = nxt, nsb
        return errors, warnings

    def check_value(self, type_string, subst, value, where):
        """Can apply_settings convert this JSON value to the property type? (errors, warnings)"""
        entry, _, clean, nullable = self.type_ref(type_string, subst)
        kind = entry.get("kind") if entry else None
        if value is None:
            if nullable or clean in ("System.String", "System.Object") or kind in ("class", "interface"):
                return [], []
            return ["%s (%s) cannot be null" % (where, short_type(clean))], []
        if clean == "System.Boolean":
            return ([] if is_bool(value) else ["%s needs true or false, got %s" % (where, describe(value))]), []
        if clean in _INT_TYPES:
            return ([] if is_int(value) else ["%s needs a whole number, got %s" % (where, describe(value))]), []
        if clean in _FLOAT_TYPES:
            return ([] if is_num(value) else ["%s needs a number, got %s" % (where, describe(value))]), []
        if clean == "System.String":
            return [], ([] if is_str(value) else ["%s is text; %s is converted with str()" % (where, describe(value))])
        if clean == "System.Drawing.Color":
            if is_str(value) and COLOR_RE.match(value):
                return [], []
            return ["%s needs a color '#RRGGBB' or '#AARRGGBB', got %s" % (where, describe(value))], []
        if clean == "System.Object":
            return [], []
        if kind == "enum":
            names = [v.get("name") for v in (entry.get("enum") or {}).get("values", [])]
            flags = bool((entry.get("enum") or {}).get("isFlags"))
            members = ", ".join(names[:20]) + (", ..." if len(names) > 20 else "")
            if is_int(value):
                return [], ["%s: use the member name of %s instead of a number (members: %s)"
                            % (where, short_type(clean), members)]
            if not is_str(value):
                return ["%s needs a member name of %s (members: %s)" % (where, short_type(clean), members)], []
            parts = [p.strip() for p in value.split(",")] if flags else [value.strip()]
            bad = [p for p in parts if p not in names]
            if bad:
                return ["%s: '%s' is not a member of %s%s (members: %s)"
                        % (where, bad[0], short_type(clean), did_you_mean(bad[0], names), members)], []
            return [], []
        if kind in ("class", "struct", "interface"):
            if is_str(value):
                if self.static_member(entry, value):
                    return [], []
                return ["%s is a %s; '%s' names none of its public static members" % (where, short_type(clean),
                                                                                    value)], []
            return ["%s is a %s, which cannot be set from %s (use postScript)"
                    % (where, short_type(clean), type_name(value))], []
        return [], ["%s has type %s; dxpgen cannot check the value" % (where, short_type(clean))]


_INDEX_CACHE = {}


def load_index(api_dir=None):
    path = find_index_file(api_dir)
    if path is None:
        return None
    key = str(path)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = ApiIndex(path)
    return _INDEX_CACHE[key]


# ---------------------------------------------------------------------------------------------
# Spotfire 15.0 text-area HTML sanitizer, emulated: the allowlist and rules of the default sanitizer
# (on by default in Analyst 15.0), checked against Spotfire's own sanitizer on Analyst 15.0. The real
# sanitizer is the authority: when a text area renders differently, believe Spotfire.
# ---------------------------------------------------------------------------------------------
_S_TEXT = {"class", "dir", "id", "lang", "style"}
_S_BLOCK = {"align", "class", "dir", "id", "lang", "style"}
SANITIZER_ALLOWED = {
    "a": {"class", "dir", "href", "id", "lang", "target", "title"},
    "blockquote": _S_TEXT, "br": {"class", "dir", "id", "style"},
    "col": {"bgcolor", "class", "span", "style", "width"}, "colgroup": {"bgcolor", "span"},
    "font": {"class", "color", "dir", "face", "id", "lang", "size", "style"},
    "hr": {"align", "class", "dir", "id", "noshade", "size", "style", "width"},
    "img": {"border", "class", "dir", "height", "hspace", "id", "lang", "src", "style", "title", "vspace",
            "width"},
    "ol": {"class", "dir", "id", "lang", "style", "type"}, "ul": {"class", "dir", "id", "lang", "style", "type"},
    "q": {"cite", "class", "dir", "id", "lang", "style"},
    "table": {"align", "bgcolor", "border", "bordercolor", "cellpadding", "cellspacing", "class", "dir", "frame",
              "id", "lang", "rules", "style", "width"},
    "td": {"align", "bgcolor", "class", "colspan", "dir", "height", "id", "lang", "rowspan", "style", "valign",
           "width"},
    "th": {"bgcolor", "class", "dir", "id", "lang", "scope", "style"},
    "tr": {"bgcolor", "class", "dir", "id", "lang", "style"},
    "spotfirecontrol": {"id"},
}
for _tag in ("abbr", "acronym", "b", "cite", "code", "dd", "del", "dl", "dt", "em", "i", "ins", "label", "li",
             "pre", "span", "strike", "strong", "tbody", "tfoot", "thead", "u"):
    SANITIZER_ALLOWED[_tag] = _S_TEXT
for _tag in ("dir", "div", "h1", "h2", "h3", "h4", "h5", "h6", "p"):
    SANITIZER_ALLOWED[_tag] = _S_BLOCK
SANITIZER_INTERMEDIARY = {"html", "body", "o:p"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
              "track", "wbr", "keygen"}
_SANITIZER_HINTS = {
    "style": " - put the CSS in the text area's 'css' file (it is injected by JavaScript)",
    "script": " - attach JavaScript through the text area's 'js' list",
    "button": " - use a button control ({{control:id}} with kind 'button')",
    "input": " - use an input property control", "select": " - use a dropdown property control",
    "textarea": " - use a multilineInput property control",
    "details": " - collapsible sections do not survive; use plain divs",
    "summary": " - collapsible sections do not survive; use plain divs",
    "svg": " - use an image or a visual instead", "section": " - use <div>", "header": " - use <div>",
    "nav": " - use <div>", "small": " - use <span style=\"font-size: 11px\">",
    "sup": " - write &sup2; / &sup3; for powers", "sub": " - write the text inline",
    "center": " - use <div style=\"text-align: center\">", "head": " - give only the body content",
    "title": " - give only the body content", "link": " - stylesheets cannot be linked; use 'css'",
}
_RGB_CALL_RE = re.compile(r"rgba?\(\s*[-+]?[\d.]+%?\s*(?:,\s*[-+]?[\d.]+%?\s*){2,3}\)", re.I)
_CSS_CALL_RE = re.compile(r"([A-Za-z_-][\w-]*)\s*\(")
_ATTR_EXTRA_CHARS = " .,-_#'`/%"


def _attr_bad_char(value, extra=""):
    for ch in value:
        if not (ch.isalpha() or ch.isdecimal() or ch in _ATTR_EXTRA_CHARS or ch in extra):
            return ch
    return None


def sanitizer_style_problem(style):
    """Why the sanitizer drops this whole style attribute, or None."""
    for decl in style.split(";"):
        decl = decl.strip()
        if not decl:
            continue
        if ":" not in decl:
            return "'%s' is not a 'name: value' declaration" % decl
        name, value = decl.split(":", 1)
        name, value = name.strip(), value.strip()
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            return "property name '%s' is not allowed" % name
        if ":" in value:
            return "'%s' has a ':' in its value" % decl
        plain = _RGB_CALL_RE.sub("rgb", value)
        call = _CSS_CALL_RE.search(plain)
        if call:
            return "'%s(' in '%s' (only plain values and rgb()/rgba() survive)" % (call.group(1), decl)
        bad = _attr_bad_char(plain, "!")
        if bad:
            return "character '%s' in '%s' is not allowed" % (bad, decl)
    return None


class _SanitizerEmulator(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.issues = []          # (level, message)
        self.skip = None          # [tag, depth] while inside a removed element

    def _issue(self, level, message):
        self.issues.append((level, message))

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def _start(self, tag, attrs, closed):
        if self.skip is not None:
            if tag == self.skip[0] and not closed and tag not in _VOID_TAGS:
                self.skip[1] += 1
            return
        if tag in SANITIZER_INTERMEDIARY:
            self._issue("warning", "the <%s> tag is removed (its content is kept)" % tag)
            return
        if tag not in SANITIZER_ALLOWED:
            self._issue("error", "<%s> is removed together with everything inside it%s"
                        % (tag, _SANITIZER_HINTS.get(tag, "")))
            if not closed and tag not in _VOID_TAGS:
                self.skip = [tag, 1]
            return
        raw = self.get_starttag_text() or ""
        if tag == "spotfirecontrol" and not raw.startswith("<SpotfireControl"):
            self._issue("warning", "write control tokens as <SpotfireControl id=\"...\" /> (other spellings stop "
                                   "matching the control); better, use {{control:id}} placeholders")
        allowed = SANITIZER_ALLOWED[tag]
        for name, value in attrs:
            if name not in allowed:
                self._issue("error", "attribute '%s' on <%s> is removed" % (name, tag)
                            + (" (<a> takes no style; style a <span> inside it)" if tag == "a" and name == "style"
                               else ""))
                continue
            if value is None:
                continue
            if name == "style":
                problem = sanitizer_style_problem(value)
                if problem:
                    self._issue("error", "the whole style attribute of <%s> is dropped: %s" % (tag, problem))
            elif name == "href":
                v = value.strip()
                low = v.lower()
                if low.startswith("javascript:"):
                    self._issue("error", "javascript: links are removed (<a href>)")
                elif not v.startswith("#") and not re.match(r"^[a-z][a-z0-9+.-]*:", low):
                    self._issue("error", "href '%s' is not a well-formed absolute URI and is removed" % v)
            elif name == "src":
                if not re.match(r"^[0-9a-fA-F]{32}\.(?:png|jpg)$", value.strip()):
                    self._issue("error", "<img src='%s'> is removed with the image (external and data: images "
                                         "are not allowed; add images in Analyst)" % value.strip()[:60])
            else:
                bad = _attr_bad_char(value)
                if bad:
                    self._issue("error", "attribute %s=\"%s\" on <%s> is removed (character '%s' is not allowed in "
                                         "attribute values)" % (name, value[:40], tag, bad))

    def handle_endtag(self, tag):
        if self.skip is not None and tag == self.skip[0]:
            self.skip[1] -= 1
            if self.skip[1] == 0:
                self.skip = None


def emulate_sanitizer(html_text):
    """[(level, message, count)] for what Spotfire's default sanitizer would remove."""
    parser = _SanitizerEmulator()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as e:                           # html.parser is lenient; never let it stop validation
        return [("warning", "the HTML could not be parsed for the sanitizer check: %s" % e, 1)]
    counts = {}
    order = []
    for level, message in parser.issues:
        key = (level, message)
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    return [(level, message, counts[(level, message)]) for level, message in order]


def textarea_style_class(vid):
    """Class of a text area's own #style-container (lib/80_textareas.py _textareas_style_class)."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(vid or ""))
    return "sfdxb-style-" + (safe or "textarea")


def compose_textarea_html(html_text, css, safe, vid=None):
    """The HTML the builder sets (lib/80_textareas.py): each {{control:id}} placeholder becomes a control
    token (32 hex digits, like a Guid in N format), plus the text area's own style container when CSS is
    injected (safe mode, and only when the HTML has no #style-container of its own).
    Returns (html, {token id: control id})."""
    tokens = {}

    def token(match):
        tid = "%032x" % (0xdeadbeef00000000 + len(tokens) + 1)
        tokens[tid] = match.group(1)
        return '<SpotfireControl id="%s" />' % tid

    body = PLACEHOLDER_RE.sub(token, html_text or "")
    if css and safe and 'id="style-container"' not in (html_text or "") \
            and "id='style-container'" not in (html_text or ""):
        body = '<div id="style-container" class="%s"></div>' % textarea_style_class(vid) + body
    return body, tokens


# ---------------------------------------------------------------------------------------------
# typed values (document property defaults, control values, script arguments)
# ---------------------------------------------------------------------------------------------
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,7})?)?)?$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d{1,7})?)?$")
_TIMESPAN_RE = re.compile(r"^-?(?:\d+\.)?(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d{1,7})?)?$")
_VALUE_EXAMPLE = {"Date": '"2026-01-31"', "DateTime": '"2026-01-31T08:00:00"', "Time": '"06:00:00"',
                  "TimeSpan": '"01:30:00"'}


def _clock_ok(h, m, s):
    return int(h) < 24 and int(m) < 60 and int(s or 0) < 60


def typed_value_problem(value, dtype, strict=True):
    """Why a JSON value does not fit a Spotfire DataType exactly (references/spec-format.md properties), or None.
    strict: Real/SingleReal must be written with a decimal point (72.0, not 72)."""
    if dtype == "String":
        return None if is_str(value) else "must be a string for type String, got %s" % describe(value)
    if dtype in ("Integer", "LongInteger"):
        if not is_int(value):
            return "must be a whole number for type %s, got %s" % (dtype, describe(value))
        low, high = INT32 if dtype == "Integer" else INT64
        return None if low <= value <= high else "%s is outside the %s range" % (value, dtype)
    if dtype in ("Real", "SingleReal"):
        if isinstance(value, float):
            return None
        if is_int(value):
            return ("must be written with a decimal point for type %s: %s.0 (values need the exact type)"
                    % (dtype, value)) if strict else None
        return "must be a number for type %s, got %s" % (dtype, describe(value))
    if dtype == "Currency":
        return None if is_num(value) else "must be a number for type Currency, got %s" % describe(value)
    if dtype == "Boolean":
        return None if is_bool(value) else "must be true or false for type Boolean, got %s" % describe(value)
    if dtype in _VALUE_EXAMPLE:
        if not is_str(value):
            return "must be a string like %s for type %s, got %s" % (_VALUE_EXAMPLE[dtype], dtype, describe(value))
        v = value.strip()
        ok = False
        try:
            if dtype == "Date":
                ok = bool(_DATE_RE.match(v)) and bool(datetime.date.fromisoformat(v))
            elif dtype == "DateTime":
                m = _DATETIME_RE.match(v)
                ok = bool(m) and bool(datetime.date.fromisoformat(m.group(1))) and (
                    m.group(2) is None or _clock_ok(m.group(2), m.group(3), m.group(4)))
            elif dtype == "Time":
                m = _TIME_RE.match(v)
                ok = bool(m) and _clock_ok(m.group(1), m.group(2), m.group(3))
            else:
                m = _TIMESPAN_RE.match(v)
                ok = bool(m) and _clock_ok(m.group(1), m.group(2), m.group(3))
        except ValueError:
            ok = False
        return None if ok else "'%s' is not a valid %s; write it like %s" % (value, dtype, _VALUE_EXAMPLE[dtype])
    if dtype == "Binary":
        return "Binary values cannot be given in the spec"
    return None


def script_assigns(code, name, engine="python"):
    """True when a line of the data-function script assigns `name` (references/spec-format.md: every output assigned)."""
    n = re.escape(name)
    if engine == "terr":
        if re.search(r"^[ \t]*(?:%s|`%s`)[ \t]*(?:<<?-|=(?!=))" % (n, n), code, re.M):
            return True
        return bool(re.search(r"->>?[ \t]*%s[ \t]*$" % n, code, re.M))
    other = r"[A-Za-z_]\w*"
    pattern = (r"^[ \t]*\(?[ \t]*(?:%s[ \t]*,[ \t]*)*%s(?:[ \t]*,[ \t]*%s)*[ \t]*\)?[ \t]*(?::[^=\n]+)?=(?!=)"
               % (other, n, other))
    return bool(re.search(pattern, code, re.M))


def _df_output_tables(d):
    out = []
    for o in as_list(d.get("outputs")):
        target = o.get("target") if isinstance(o, dict) and isinstance(o.get("target"), dict) else {}
        if isinstance(o, dict) and str(o.get("type") or "").lower() == "table" and is_str(target.get("table")) \
                and target["table"]:
            out.append(target["table"])
    return out


def _df_read_tables(d, candidates):
    names = set()
    for inp in as_list(d.get("inputs")):
        bind = inp.get("bind") if isinstance(inp, dict) and isinstance(inp.get("bind"), dict) else {}
        if is_str(bind.get("table")) and bind["table"]:
            names.add(bind["table"])
        expression = bind.get("expression")
        if is_str(expression):
            for t in candidates:
                if "[" + t.replace("]", "]]") + "]." in expression:
                    names.add(t)
    return names


def df_build_order(functions):
    """(spec indices in build order, indices caught in a cycle). Mirrors lib/30_datafunctions.py
    _datafunctions_order: a function reading a table another spec function writes is built after it;
    stable otherwise; functions in a dependency cycle keep spec order."""
    idx = [i for i, d in enumerate(functions) if isinstance(d, dict)]
    producers = {}
    for i in idx:
        for t in _df_output_tables(functions[i]):
            producers.setdefault(t, []).append(i)
    deps = {}
    for i in idx:
        deps[i] = set(j for t in _df_read_tables(functions[i], list(producers)) for j in producers.get(t, []) if j != i)
    order, done = [], set()
    while len(order) < len(idx):
        nxt = next((i for i in idx if i not in done and not (deps[i] - done)), None)
        if nxt is None:
            cycle = [i for i in idx if i not in done]
            return order + cycle, cycle
        order.append(nxt)
        done.add(nxt)
    return order, []


_PROP_LOOKUP_RE = re.compile(r"""Properties\s*\[\s*(['"])([^'"\\]+)\1\s*\]|DocumentProperty\(\s*\\?(['"])([^'"\\]+)\\?\3\s*\)""")
_LIVE_PROP_RE = re.compile(r"(?<!\\)\$\{([A-Za-z0-9.]+)\}")
_SHORTHAND_PROP_RE = re.compile(r"\[\$([A-Za-z0-9.]+)\]")
_DOCPROP_RE = re.compile(r"""DocumentProperty\(\s*(['"])([^'"]+)\1\s*\)""")


# ---------------------------------------------------------------------------------------------
# data-file columns (validate checks column references against the files the builder loads)
# ---------------------------------------------------------------------------------------------
# SBDF value-type ids (Spotfire.Dxp.Data.Formats.Sbdf ValueTypeId) -> Spotfire DataType names
SBDF_TYPES = {1: "Boolean", 2: "Integer", 3: "LongInteger", 4: "SingleReal", 5: "Real", 6: "DateTime", 7: "Date",
              8: "Time", 9: "TimeSpan", 10: "String", 12: "Binary", 13: "Currency"}
_SBDF_FIXED = {1: 1, 2: 4, 3: 8, 4: 4, 5: 8, 6: 8, 7: 8, 8: 8, 9: 8, 13: 16}


def sbdf_columns(path):
    """[(column name, DataType name)] from the header of an SBDF file (file header and table-metadata
    sections only; the data slices are never read). Raises ValueError for a file that is not SBDF."""
    with open(path, "rb") as f:
        return _sbdf_header_columns(f)


def _sbdf_header_columns(f):
    def take(n):
        chunk = f.read(n)
        if len(chunk) != n:
            raise ValueError("truncated SBDF header")
        return chunk

    def u8():
        return take(1)[0]

    def i32():
        value = struct.unpack("<i", take(4))[0]
        if value < 0:
            raise ValueError("negative length in the SBDF header")
        return value

    def section(want):
        head = take(3)
        if head[0] != 0xDF or head[1] != 0x5B or head[2] != want:
            raise ValueError("not an SBDF file (section %d expected)" % want)

    def value(vt):
        if vt in _SBDF_FIXED:
            return take(_SBDF_FIXED[vt])
        if vt in (10, 12):
            raw = take(i32())
            return raw.decode("utf-8") if vt == 10 else raw
        raise ValueError("unknown SBDF value type %r in the header" % vt)

    def optional(vt):
        return value(vt) if u8() else None

    section(1)
    take(2)                                         # format version (1.0)
    section(2)
    for _ in range(i32()):                          # table metadata entries
        take(i32())
        vt = u8()
        optional(vt)
        optional(vt)
    count = i32()
    names = []
    for _ in range(i32()):                          # column metadata properties (Name, DataType, ...)
        name = take(i32()).decode("utf-8")
        vt = u8()
        optional(vt)
        names.append((name, vt))
    columns = []
    for _ in range(count):
        props = {}
        for name, vt in names:
            got = optional(vt)
            if got is not None:
                props[name] = got
        dtype = props.get("DataType")
        type_name = SBDF_TYPES.get(dtype[0]) if isinstance(dtype, bytes) and dtype else None
        if not is_str(props.get("Name")):
            raise ValueError("an SBDF column has no name")
        columns.append((props["Name"], type_name))
    return columns


def csv_columns(path, source):
    """[(column name, declared DataType or None)] from the header row of a delimited text source, or None
    when the names cannot be known here (no header row, a multi-character separator, unreadable file)."""
    if source.get("header", True) is False:
        return None
    sep = source.get("separator") or ","
    if len(sep) != 1:
        return None
    encoding = str(source.get("encoding") or "utf-8").lower().replace("_", "-")
    if encoding in ("utf-8", "utf8"):
        encoding = "utf-8-sig"
    try:
        with open(path, encoding=encoding, newline="") as f:
            header = next(csv.reader(f, delimiter=sep), None)
    except (OSError, LookupError, UnicodeDecodeError, csv.Error):
        return None
    if not header:
        return None
    declared = source.get("columns") if isinstance(source.get("columns"), dict) else {}
    return [(name, declared.get(name)) for name in header]


# The expression regexes live in scripts/sfexpr.py (shared with verify_dxp.py): string literals, aliases,
# identifiers, ${...}, Spotfire's own identifiers ([Axis.X], [Axis.Default.Names], [Y.FinalValue]) and THEN.
from sfexpr import (_EXPR_STRING_RE, _EXPR_ALIAS_RE, _EXPR_IDENT_RE, _EXPR_PREPROCESSOR_RE,  # noqa: E402
                    _EXPR_SPECIAL_RE, _EXPR_THEN_RE, unaggregated, row_level, TYPE_KIND, value_kind,
                    date_call_properties)


def expression_columns(text):
    """Column references of a Spotfire expression: [(table or None, column)]. Left out: string literals,
    ${...} and identifiers built from it ('[${Signal}]': the column is only known at run time), aliases
    ('as [Name]'), [$Property] shorthand, Spotfire's special identifiers ([Axis.X], [Axis.Default.Names],
    [Y.FinalValue], [Value] after THEN). '[T].[C]' gives table T."""
    if not is_str(text):
        return []
    s = _EXPR_PREPROCESSOR_RE.sub("\x00", text)
    s = _EXPR_STRING_RE.sub('""', s)
    s = _EXPR_ALIAS_RE.sub(" ", s)
    then = bool(_EXPR_THEN_RE.search(s))
    out = []
    table = None
    for m in _EXPR_IDENT_RE.finditer(s):
        name = m.group(1).replace("]]", "]")
        if s[m.end():m.end() + 2] == ".[":
            table = name                            # [Table].[Column]
            continue
        owner, table = table, None
        if not name or "\x00" in name or name.startswith("$") or _EXPR_SPECIAL_RE.match(name) \
                or (then and name == "Value"):
            continue
        out.append((owner, name))
    return out


# ---------------------------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------------------------
class Options(object):
    def __init__(self, lint=True, sanitize=True, tools_dir=None, api_dir=None, workers=4):
        self.lint = lint
        self.sanitize = sanitize
        self.tools_dir = Path(tools_dir) if tools_dir else TOOL_DIR
        self.api_dir = Path(api_dir) if api_dir else None    # None: SFAPI_INDEX or $DXP_WORKSPACE/api
        self.workers = workers


class Validator(object):
    """Every check of `dxpgen validate`. Errors block the build; warnings do not."""

    def __init__(self, spec, app_dir, options=None):
        self.spec = spec
        self.app_dir = Path(app_dir).resolve()
        self.opts = options or Options()
        self.r = Report()
        self.policy = "program"
        self.html_mode = "safe"
        self.min_version = "14.6"
        self.props = {}           # lower-case name -> spec name
        self.prop_specs = {}      # spec name -> property spec
        self.tables = {}          # spec table name -> table spec
        self.dfs = {}             # data function name -> (index, spec)
        self.produced = {}        # table name -> [(function, index, executeAtBuild)]
        self.df_props = {}        # property name -> [(function, index, executeAtBuild)]
        self.marking_names = ["Marking"]
        self.default_marking = "Marking"
        self.scheme_names = []
        self.scripts = {}         # script name -> spec
        self.page_titles = {}     # title -> page index
        self.visuals = {}         # visual id -> info
        self.visual_seen = {}     # visual id -> path of its first declaration
        self.mod_visuals = []     # ids of mod visuals (one version warning for all of them)
        self.ipy_jobs = []        # IronPython to lint
        self.html_jobs = []       # safe-mode text areas for the sanitizer
        self.settings_jobs = []   # (path, key, value, target classes, mode)
        self.texts = {}
        self.action_mods = {}     # action mod id -> parsed mod-manifest.json, or None (not in the project)
        self.viz_mods = {}        # visualization mod id -> parsed mod-manifest.json, or None (unreadable)
        self.js_names = {}        # text-area JavaScript name -> (path, code)
        self.script_codes = []    # IronPython script texts (the interaction audit looks for marking names)

    # ---- driver ----------------------------------------------------------------------------
    def run(self):
        s = self.spec
        self.check_keys(s, TOP_KEYS, "")
        version = s.get("specVersion", 1)
        if version != 1 or isinstance(version, bool):
            self.r.error("specVersion", "must be 1 (this dxpgen reads app spec v1), got %s" % describe(version))
        self.collect()
        self.v_app()
        self.v_properties()
        self.v_tables()
        self.v_relations()
        self.v_markings()
        self.v_schemes()
        self.v_data_functions()
        self.v_scripts()
        self.v_triggers()
        self.v_action_mods()
        self.v_viz_mods()
        self.v_pages()
        self.v_marking_reach()
        self.v_top_references()
        self.v_columns()
        self.v_filter_layouts()
        self.v_reference_types()
        self.v_settings()
        self.v_customer_text()
        self.v_tools()
        return self.r

    # ---- generic helpers -------------------------------------------------------------------
    def check_keys(self, obj, known, path):
        for k in obj:
            if k not in known:
                self.r.warn(pjoin(path, k), "unknown field '%s'%s; the builder ignores it" % (k, did_you_mean(k, known)))

    def section(self, key):
        v = self.spec.get(key)
        if v is None:
            return []
        if not isinstance(v, list):
            self.r.error(key, "must be a list, got %s" % describe(v))
            return []
        return v

    def field(self, obj, key, path, kinds, required=False, choices=None, nullable=True):
        """Type-check obj[key]; returns the value when it passes, else None (error recorded)."""
        p = pjoin(path, key)
        if key not in obj:
            if required:
                self.r.error(p, "missing required field '%s'" % key)
            return None
        v = obj[key]
        if v is None:
            if required or not nullable:
                self.r.error(p, "must not be null")
            return None
        if not any(KIND_CHECK[k](v) for k in kinds):
            self.r.error(p, "must be %s, got %s" % (" or ".join(KIND_LABEL[k] for k in kinds), describe(v)))
            return None
        if choices is not None and v not in choices:
            self.r.error(p, "must be one of %s, got %s%s" % (", ".join(choices), describe(v), did_you_mean(v, choices)))
            return None
        return v

    def obj(self, value, path, what="an object"):
        if not isinstance(value, dict):
            self.r.error(path, "must be %s, got %s" % (what, describe(value)))
            return False
        return True

    def naming(self, kind, name, path):
        for level, message in naming_issues(kind, name, self.policy):
            if level == "error":
                self.r.error(path, message)
            else:
                self.r.warn(path, message)

    def color_field(self, obj, key, path, required=False):
        v = self.field(obj, key, path, ["str"], required=required)
        if v is not None and not COLOR_RE.match(v):
            self.r.error(pjoin(path, key), "must be a color '#RRGGBB' or '#AARRGGBB', got %s" % describe(v))
            return None
        return v

    def palette_names(self):
        """Palette names '@name' may refer to: the house palette plus app.style.palette."""
        app = self.spec.get("app") if isinstance(self.spec.get("app"), dict) else {}
        style = app.get("style") if isinstance(app.get("style"), dict) else {}
        names = dict(t3._house.PALETTE)
        if isinstance(style.get("palette"), dict):
            names.update(style["palette"])
        return names

    def format_hint(self, value, path):
        """Warn about a format that looks like a name but is none (it would be used as written)."""
        if not is_str(value) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
            return
        if re.match(r"^[CDEFGNPRXcdefgnprx]\d{0,2}$", value):
            return                                   # .NET standard number format (N2, P1, C0, ...)
        app = self.spec.get("app") if isinstance(self.spec.get("app"), dict) else {}
        style = app.get("style") if isinstance(app.get("style"), dict) else {}
        formats = style.get("formats") if isinstance(style.get("formats"), dict) else {}
        names = set(t3._house.FORMATS) | set(formats)
        if value not in names:
            self.r.warn(path, "'%s' is not a format name of app.style.formats or the house formats (%s); it is "
                        "used as a format string as written%s" % (value, ", ".join(sorted(names)),
                                                                  did_you_mean(value, sorted(names))))

    def file_path(self, rel, path, what, exts=None):
        """Absolute path of an existing file given relative to the app folder; None (error) when missing."""
        p = Path(rel)
        if p.is_absolute():
            full = p
            self.r.warn(path, "absolute path; give paths relative to the app folder so the app can move")
        else:
            full = self.app_dir / p
            try:
                full.resolve().relative_to(self.app_dir)
            except ValueError:
                self.r.warn(path, "points outside the app folder (%s)" % rel)
        if not full.is_file():
            self.r.error(path, "%s not found: %s" % (what, full))
            return None
        if exts and full.suffix.lower() not in [e.lower() for e in exts]:
            self.r.warn(path, "expected a %s file, got '%s'" % ("/".join(exts), full.name))
        return full

    def file_text(self, full, path):
        key = str(full)
        if key not in self.texts:
            text, problem = read_text_file(full)
            if problem:
                self.r.error(path, "cannot read %s: %s" % (Path(full).name, problem))
            self.texts[key] = text
        return self.texts[key]

    def add_settings(self, settings, path, targets, mode="single"):
        """Queue a settings escape hatch for the API-index check (v_settings)."""
        if settings is None:
            return
        if not isinstance(settings, dict):
            self.r.error(path, "must be an object of dotted property paths to values, got %s" % describe(settings))
            return
        for key, value in settings.items():
            if not SETTINGS_KEY_RE.match(key):
                self.r.error(pjoin(path, key), "must be a dotted public property path like 'XAxis.Scale.ShowGridlines'")
                continue
            self.settings_jobs.append((pjoin(path, key), key, value, targets, mode))

    def expression_refs(self, text, path, strict=None):
        """Document properties named in an expression: [$Name] (spec shorthand), DocumentProperty("Name"),
        ${Name} (live preprocessor value). strict (what the expression is, in a mod view): an unknown
        ${Name} is an error there, not a warning (the mod's data view cannot be evaluated)."""
        if not is_str(text):
            return
        for m in _SHORTHAND_PROP_RE.finditer(text):
            self.ref_property(m.group(1), path, "[$%s]" % m.group(1))
        for m in _DOCPROP_RE.finditer(text):
            self.ref_property(m.group(2), path, "DocumentProperty(\"%s\")" % m.group(2))
        for m in _LIVE_PROP_RE.finditer(text):
            name = m.group(1)
            if name in BUILTIN_PROPERTIES:
                continue
            if self.props.get(name.lower()) is None and not any(p.lower() == name.lower() for p in self.df_props):
                hint = did_you_mean(name, list(self.prop_specs))
                if strict:
                    self.r.error(path, "${%s} names no declared document property%s; the mod %s cannot be evaluated"
                                 % (name, hint, strict))
                else:
                    self.r.warn(path, "${%s} names no declared document property%s" % (name, hint))

    # ---- registries ------------------------------------------------------------------------
    def collect(self):
        s = self.spec
        app = s.get("app") if isinstance(s.get("app"), dict) else {}
        if app.get("namingPolicy") in NAMING_POLICIES:
            self.policy = app["namingPolicy"]
        if app.get("htmlMode") in HTML_MODES:
            self.html_mode = app["htmlMode"]
        mv = app.get("minimumSpotfireVersion")
        if is_str(mv) and VERSION_RE.match(mv):
            self.min_version = mv
        for p in as_list(s.get("properties")):
            if isinstance(p, dict) and is_str(p.get("name")) and p["name"]:
                self.props.setdefault(p["name"].lower(), p["name"])
                self.prop_specs.setdefault(p["name"], p)
        for t in as_list(s.get("tables")):
            if isinstance(t, dict) and is_str(t.get("name")) and t["name"]:
                self.tables.setdefault(t["name"], t)
        for i, d in enumerate(as_list(s.get("dataFunctions"))):
            if not (isinstance(d, dict) and is_str(d.get("name")) and d["name"]):
                continue
            name = d["name"]
            self.dfs.setdefault(name, (i, d))
            ex = d.get("executeAtBuild", True) is not False
            for o in as_list(d.get("outputs")):
                if not isinstance(o, dict):
                    continue
                target = o.get("target") if isinstance(o.get("target"), dict) else {}
                if o.get("type") == "table" and is_str(target.get("table")) and target["table"]:
                    self.produced.setdefault(target["table"], []).append((name, i, ex))
                elif o.get("type") == "value" and is_str(target.get("property")) and target["property"]:
                    self.df_props.setdefault(target["property"], []).append((name, i, ex))
        order, cycle = df_build_order(as_list(s.get("dataFunctions")))
        self.df_pos = dict((spec_index, pos) for pos, spec_index in enumerate(order))
        self.df_cycle = cycle
        marks = [m for m in as_list(s.get("markings")) if isinstance(m, dict) and is_str(m.get("name")) and m["name"]]
        if marks:
            self.marking_names = [m["name"] for m in marks]
            defaults = [m["name"] for m in marks if m.get("default") is True]
            self.default_marking = defaults[0] if defaults else self.marking_names[0]
        self.scheme_names = [f["name"] for f in as_list(s.get("filteringSchemes"))
                             if isinstance(f, dict) and is_str(f.get("name")) and f["name"]]
        for sc in as_list(s.get("scripts")):
            if isinstance(sc, dict) and is_str(sc.get("name")) and sc["name"]:
                self.scripts.setdefault(sc["name"], sc)
        order = 0
        for pi, pg in enumerate(as_list(s.get("pages"))):
            if not isinstance(pg, dict):
                continue
            if is_str(pg.get("title")):
                self.page_titles.setdefault(pg["title"], pi)
            for vi, v in enumerate(as_list(pg.get("visuals"))):
                if isinstance(v, dict) and is_str(v.get("id")) and v["id"] and v["id"] not in self.visuals:
                    self.visuals[v["id"]] = {"page": pi, "index": vi, "type": v.get("type"), "order": order,
                                             "pageTitle": pg.get("title")}
                order += 1

    # ---- references ------------------------------------------------------------------------
    def ref_property(self, name, path, what="property", allow_outputs=True):
        """Canonical name of a referenced document property, or None (error recorded)."""
        if not is_str(name) or not name:
            self.r.error(path, "%s must be a document property name, got %s" % (what, describe(name)))
            return None
        if name in BUILTIN_PROPERTIES:
            return name
        canon = self.props.get(name.lower())
        if canon is None and allow_outputs:
            for pname, producers in self.df_props.items():
                if pname.lower() == name.lower() and any(ex for _, _, ex in producers):
                    canon = pname
                    break
        if canon is None:
            pool = list(self.prop_specs) + list(self.df_props)
            prefix = "" if what == "property" else what + ": "
            self.r.error(path, "%sunknown document property '%s'%s (declare it in 'properties')"
                         % (prefix, name, did_you_mean(name, pool)))
            return None
        if canon != name:
            self.r.error(path, "'%s' must be written exactly like the property, '%s' (one name per binding)"
                         % (name, canon))
        return canon

    def is_file_table(self, name):
        t = self.tables.get(name)
        return isinstance(t, dict) and isinstance(t.get("source"), dict) and t["source"].get("type") in ("sbdf", "csv")

    def known_table(self, name):
        return name in self.tables or name in self.produced

    def table_ready(self, name, before=None):
        """Does table `name` exist at that point of the build? File tables always; data-function tables
        once a function with executeAtBuild has run (before = a position in the data-function build
        order: only functions built earlier count)."""
        if self.is_file_table(name):
            return True
        return any(ex and (before is None or self.df_pos.get(idx, 10 ** 9) < before)
                   for _, idx, ex in self.produced.get(name, []))

    def ref_table(self, name, path, what="table"):
        """A table used after the data functions ran (visuals, relations, controls)."""
        if not is_str(name) or not name:
            self.r.error(path, "%s must be a data table name, got %s" % (what, describe(name)))
            return None
        if not self.known_table(name):
            pool = list(self.tables) + list(self.produced)
            self.r.error(path, "unknown data table '%s'%s" % (name, did_you_mean(name, pool)))
            return None
        if not self.table_ready(name):
            producers = self.produced.get(name, [])
            if producers:
                self.r.error(path, "table '%s' is created by data function '%s', which has executeAtBuild: false, so "
                             "it does not exist while the builder runs; set executeAtBuild to true (only tables "
                             "of functions run at build can be used here)" % (name, producers[0][0]))
            else:
                self.r.error(path, "table '%s' has source dataFunction, but no data function outputs it" % name)
            return None
        return name

    # ---- app ---------------------------------------------------------------------------------
    def v_app(self):
        if "app" not in self.spec:
            self.r.error("app", "missing required section 'app' (at least {\"name\": \"...\"})")
            return
        app = self.spec["app"]
        if not self.obj(app, "app"):
            return
        self.check_keys(app, APP_KEYS, "app")
        name = self.field(app, "name", "app", ["str"], required=True)
        if name is not None:
            if not name.strip():
                self.r.error("app.name", "must not be empty")
            elif app.get("output") is None and any(ch in BAD_FILE_NAME_CHARS or ord(ch) < 32 for ch in name):
                self.r.error("app.name", "'%s' contains characters a file name cannot have (%s); rename it or set "
                             "app.output" % (name, BAD_FILE_NAME_CHARS))
        self.field(app, "description", "app", ["str"])
        keywords = self.field(app, "keywords", "app", ["list"])
        for i, k in enumerate(keywords or []):
            if not is_str(k):
                self.r.error(pjoin("app", "keywords", i), "must be a string, got %s" % describe(k))
        out = self.field(app, "output", "app", ["str"])
        if out is not None:
            if not out.lower().endswith(".dxp"):
                self.r.error("app.output", "must end with .dxp, got '%s'" % out)
            elif Path(out).is_absolute():
                self.r.warn("app.output", "absolute path; a path relative to the app folder (build/...) keeps the "
                            "app portable")
            if any(ch in '*?"<>|' for ch in out):
                self.r.error("app.output", "contains characters a file name cannot have")
        self.field(app, "namingPolicy", "app", ["str"], choices=NAMING_POLICIES)
        if self.field(app, "htmlMode", "app", ["str"], choices=HTML_MODES) == "rich":
            self.r.warn("app.htmlMode", "rich text-area HTML renders as written only where Spotfire's HTML sanitizer "
                        "is off; servers sanitize text-area HTML by default")
        theme = self.field(app, "theme", "app", ["dict"])
        if theme is not None:
            self.v_theme(theme)
        if app.get("style") is not None:
            # standard-engine style layer (references/spec-format.md "app.style"; checks in scripts/t3)
            for level, path, message in t3.validate_style(app["style"], "app.style"):
                self.r.add(level, path, message)
        self.field(app, "pageNavigation", "app", ["str"], choices=NAVIGATION_MODES)
        canvas = self.field(app, "canvas", "app", ["dict"])
        if canvas is not None:
            self.check_keys(canvas, ("width", "height", "fitToWindow"), "app.canvas")
            for k in ("width", "height"):
                v = self.field(canvas, k, "app.canvas", ["int"], required=True)
                if v is not None and v <= 0:
                    self.r.error(pjoin("app.canvas", k), "must be a positive number of pixels")
            self.field(canvas, "fitToWindow", "app.canvas", ["bool"])
        snaps = self.field(app, "snapshots", "app", ["dict"])
        if snaps is not None:
            self.check_keys(snaps, ("enabled", "width", "height"), "app.snapshots")
            self.field(snaps, "enabled", "app.snapshots", ["bool"])
            for k in ("width", "height"):
                v = self.field(snaps, k, "app.snapshots", ["int"])
                if v is not None and not 16 <= v <= 10000:
                    self.r.error(pjoin("app.snapshots", k), "must be between 16 and 10000 pixels")
        mv = self.field(app, "minimumSpotfireVersion", "app", ["str"])
        if mv is not None and not VERSION_RE.match(mv):
            self.r.error("app.minimumSpotfireVersion", "must be a version like \"14.6\", got %s" % describe(mv))
        for path, message in textlint.config_problems(app):
            self.r.error(path, message)

    def v_theme(self, theme):
        """app.theme is a manual step: no public API sets the document theme. dxpgen build writes the custom
        styles to build/theme.json and MANUAL-STEPS says how to apply them."""
        path = "app.theme"
        self.r.note("app.theme is applied by hand after the build (no public API sets the theme): see "
                    "build/MANUAL-STEPS-<tier>.md, or use the styling-spotfire-dxps skill")
        self.check_keys(theme, ("base", "customStyles"), path)
        base = self.field(theme, "base", path, ["str"], choices=THEMES) or "LightSfx"
        cs = theme.get("customStyles")
        if cs is None:
            return
        cp = pjoin(path, "customStyles")
        styles = None
        if isinstance(cs, dict):
            styles = cs
        elif is_str(cs):
            full = self.file_path(cs, cp, "theme JSON file", (".json",))
            text = self.file_text(full, cp) if full is not None else None
            if text is not None:
                try:
                    styles = json.loads(text)
                except ValueError as e:
                    self.r.error(cp, "%s is not valid JSON: %s" % (full.name, e))
                    return
                if not isinstance(styles, dict):
                    self.r.error(cp, "%s must hold a JSON object (the theme editor's JSON)" % full.name)
                    styles = None
        else:
            self.r.error(cp, "must be a theme-editor JSON object or a path to a .json file, got %s" % describe(cs))
            return
        if styles is not None:
            general = styles.get("general") if isinstance(styles.get("general"), dict) else {}
            named = general.get("baseThemeSfx") or general.get("baseTheme")
            if named and named != base:
                self.r.warn(cp, "customStyles names base theme '%s' but app.theme.base is '%s'; build/theme.json "
                            "uses '%s'" % (named, base, base))

    # ---- document properties -----------------------------------------------------------------
    def v_properties(self):
        seen = {}
        for i, p in enumerate(self.section("properties")):
            path = pjoin("properties", i)
            if not self.obj(p, path):
                continue
            self.check_keys(p, PROPERTY_KEYS, path)
            name = self.field(p, "name", path, ["str"], required=True)
            ptype = self.field(p, "type", path, ["str"], required=True, choices=DATA_TYPES)
            self.field(p, "description", path, ["str"])
            list_valued = self.field(p, "listValued", path, ["bool"])
            np_ = pjoin(path, "name")
            if name is not None:
                if name in BUILTIN_PROPERTIES:
                    pass
                elif not PROPERTY_NAME_RE.match(name):
                    example = suggest_camel(name) if self.policy == "camelCase" else suggest_pascal(name)
                    self.r.error(np_, "'%s': document property names may contain only letters and digits, with dots "
                                 "between segments (Spotfire rule), e.g. '%s'" % (name, example))
                elif name.lower().startswith("spotfire."):
                    self.r.error(np_, "names starting with 'spotfire.' are reserved by Spotfire")
                else:
                    self.naming("property", name, np_)
                low = name.lower()
                if low in seen:
                    j, other = seen[low]
                    if other == name:
                        self.r.error(np_, "property '%s' is declared twice (also properties[%d])" % (name, j))
                    else:
                        self.r.error(np_, "'%s' differs only in case from properties[%d] '%s'; Spotfire property "
                                     "names are case-insensitive" % (name, j, other))
                else:
                    seen[low] = (i, name)
            if ptype == "Binary" and list_valued:
                self.r.error(pjoin(path, "listValued"), "list-valued Binary properties are not supported")
            if ptype is not None and p.get("default") is not None:
                self.typed_value(p["default"], ptype, pjoin(path, "default"), bool(list_valued), True)

    def typed_value(self, value, dtype, path, list_valued=False, strict=True):
        if list_valued:
            if not isinstance(value, list):
                self.r.error(path, "must be a JSON list for a list-valued property (listValued: true), got %s"
                             % describe(value))
                return
            for j, item in enumerate(value):
                self.typed_value(item, dtype, pjoin(path, j), False, strict)
            return
        if isinstance(value, (list, dict)):
            self.r.error(path, "must be a single %s value, got %s (lists need listValued: true)" % (dtype, describe(value)))
            return
        problem = typed_value_problem(value, dtype, strict)
        if problem:
            self.r.error(path, problem)

    # ---- tables --------------------------------------------------------------------------------
    def v_tables(self):
        seen = {}
        for i, t in enumerate(self.section("tables")):
            path = pjoin("tables", i)
            if not self.obj(t, path):
                continue
            self.check_keys(t, TABLE_KEYS, path)
            name = self.field(t, "name", path, ["str"], required=True)
            if name is not None:
                np_ = pjoin(path, "name")
                if not name.strip():
                    self.r.error(np_, "must not be empty")
                self.naming("table", name, np_)
                low = name.lower()
                if low in seen:
                    self.r.error(np_, "table '%s' is declared twice (also tables[%d]); table names must be unique "
                                 "(case-insensitive)" % (name, seen[low]))
                else:
                    seen[low] = i
            sp = pjoin(path, "source")
            src = self.field(t, "source", path, ["dict"], required=True)
            stype = None
            if src is not None:
                stype = self.field(src, "type", sp, ["str"], required=True, choices=SOURCE_TYPES)
                if stype:
                    self.check_keys(src, SOURCE_KEYS[stype], sp)
                if stype in ("sbdf", "csv"):
                    rel = self.field(src, "path", sp, ["str"], required=True)
                    if rel:
                        self.file_path(rel, pjoin(sp, "path"), "data file",
                                       (".sbdf",) if stype == "sbdf" else (".csv", ".txt", ".tsv"))
                    if stype == "csv":
                        self.v_csv(src, sp)
                elif stype == "dataFunction":
                    fn = self.field(src, "function", sp, ["str"], required=True)
                    out = self.field(src, "output", sp, ["str"], required=True)
                    if fn is not None:
                        if fn not in self.dfs:
                            self.r.error(pjoin(sp, "function"), "unknown data function '%s'%s"
                                         % (fn, did_you_mean(fn, list(self.dfs))))
                        elif out is not None:
                            self.v_table_output(fn, out, name, pjoin(sp, "output"))
            self.field(t, "description", path, ["str"])
            for cname, meta in (self.field(t, "columns", path, ["dict"]) or {}).items():
                cp = pjoin(path, "columns", cname)
                if not self.obj(meta, cp):
                    continue
                self.check_keys(meta, ("description", "format", "settings"), cp)
                self.field(meta, "description", cp, ["str"])
                self.field(meta, "format", cp, ["str"])
                self.add_settings(meta.get("settings"), pjoin(cp, "settings"), [DATA_COLUMN_CLASS])
            calc_names = {}
            for j, c in enumerate(self.field(t, "calculatedColumns", path, ["list"]) or []):
                cp = pjoin(path, "calculatedColumns", j)
                if not self.obj(c, cp):
                    continue
                self.check_keys(c, ("name", "expression", "description"), cp)
                cn = self.field(c, "name", cp, ["str"], required=True)
                ex = self.field(c, "expression", cp, ["str"], required=True)
                self.field(c, "description", cp, ["str"])
                if cn:
                    self.naming("column", cn, pjoin(cp, "name"))
                    if cn in calc_names:
                        self.r.error(pjoin(cp, "name"), "calculated column '%s' is declared twice (also "
                                     "calculatedColumns[%d])" % (cn, calc_names[cn]))
                    calc_names.setdefault(cn, j)
                if ex is not None:
                    if not ex.strip():
                        self.r.error(pjoin(cp, "expression"), "must not be empty")
                    self.expression_refs(ex, pjoin(cp, "expression"))
            for j, h in enumerate(self.field(t, "hierarchies", path, ["list"]) or []):
                hp = pjoin(path, "hierarchies", j)
                if not self.obj(h, hp):
                    continue
                self.check_keys(h, ("name", "levels"), hp)
                hn = self.field(h, "name", hp, ["str"], required=True)
                if hn:
                    self.naming("column", hn, pjoin(hp, "name"))
                levels = self.field(h, "levels", hp, ["list"], required=True)
                if levels is not None:
                    if not levels:
                        self.r.error(pjoin(hp, "levels"), "must name at least one column")
                    for k, level in enumerate(levels):
                        if not is_str(level) or not level:
                            self.r.error(pjoin(hp, "levels", k), "must be a column name, got %s" % describe(level))
            if self.field(t, "embed", path, ["bool"]) is False:
                self.r.warn(pjoin(path, "embed"), "linked (not embedded) tables are not allowed in a "
                            "delivered analysis")
            self.add_settings(t.get("settings"), pjoin(path, "settings"), [DATA_TABLE_CLASS])
            if stype == "dataFunction" and name and name in self.produced and not self.table_ready(name):
                if any(t.get(k) for k in ("description", "columns", "calculatedColumns", "hierarchies", "settings")):
                    self.r.warn(path, "metadata of '%s' is applied after its data function runs, but the function has "
                                "executeAtBuild: false, so the builder skips it" % name)

    def v_csv(self, src, sp):
        sep = self.field(src, "separator", sp, ["str"])
        if sep is not None and sep == "":
            self.r.error(pjoin(sp, "separator"), "must not be empty")
        self.field(src, "culture", sp, ["str"])
        enc = self.field(src, "encoding", sp, ["str"])
        if enc is not None:
            try:
                codecs.lookup(enc)
            except LookupError:
                self.r.warn(pjoin(sp, "encoding"), "unknown encoding '%s' (use utf-8, utf-16, latin-1, cp1252, ...)" % enc)
        self.field(src, "header", sp, ["bool"])
        cols = self.field(src, "columns", sp, ["dict"])
        for cname, dtype in (cols or {}).items():
            if dtype not in DATA_TYPES:
                self.r.error(pjoin(sp, "columns", cname), "must be a DataType name (%s), got %s%s"
                             % (", ".join(DATA_TYPES), describe(dtype), did_you_mean(dtype, DATA_TYPES)))
        if not cols:
            self.r.warn(sp, "list every column's DataType in source.columns; unlisted columns are typed by Spotfire")

    def v_table_output(self, fn, out, table_name, path):
        _, d = self.dfs[fn]
        outputs = [o for o in as_list(d.get("outputs")) if isinstance(o, dict)]
        hits = [o for o in outputs if o.get("name") == out]
        if not hits:
            self.r.error(path, "data function '%s' has no output '%s'%s"
                         % (fn, out, did_you_mean(out, [o.get("name") for o in outputs])))
            return
        o = hits[0]
        if o.get("type") != "table":
            self.r.error(path, "output '%s' of '%s' is not a table output" % (out, fn))
            return
        target = o.get("target").get("table") if isinstance(o.get("target"), dict) else None
        if table_name and target and target != table_name:
            self.r.error(path, "output '%s' of '%s' writes table '%s', not '%s'; name the table entry after the "
                         "output's target" % (out, fn, target, table_name))

    # ---- relations, markings, filtering schemes ----------------------------------------------
    def v_relations(self):
        pairs = {}
        for i, rel in enumerate(self.section("relations")):
            path = pjoin("relations", i)
            if not self.obj(rel, path):
                continue
            self.check_keys(rel, ("left", "right", "on"), path)
            left = self.field(rel, "left", path, ["str"], required=True)
            right = self.field(rel, "right", path, ["str"], required=True)
            if left:
                self.ref_table(left, pjoin(path, "left"))
            if right:
                self.ref_table(right, pjoin(path, "right"))
            if left and right:
                if left == right:
                    self.r.error(path, "a table cannot be related to itself")
                pair = tuple(sorted((left, right)))
                if pair in pairs:
                    self.r.error(path, "tables '%s' and '%s' are already related (relations[%d]); give several "
                                 "column pairs in one 'on' instead" % (left, right, pairs[pair]))
                pairs.setdefault(pair, i)
            on = self.field(rel, "on", path, ["list"], required=True)
            if on is not None:
                if not on:
                    self.r.error(pjoin(path, "on"), "needs at least one [leftColumn, rightColumn] pair")
                for j, pr in enumerate(on):
                    if not (isinstance(pr, list) and len(pr) == 2 and all(is_str(x) and x for x in pr)):
                        self.r.error(pjoin(path, "on", j), "must be a [leftColumn, rightColumn] pair of column names, "
                                     "got %s" % describe(pr))

    def v_markings(self):
        items = self.section("markings")
        seen = {}
        defaults = []
        for i, m in enumerate(items):
            path = pjoin("markings", i)
            if not self.obj(m, path):
                continue
            self.check_keys(m, ("name", "color", "default"), path)
            name = self.field(m, "name", path, ["str"], required=True)
            if name is not None:
                self.naming("marking", name, pjoin(path, "name"))
                if name.lower() in seen:
                    self.r.error(pjoin(path, "name"), "marking '%s' is declared twice (also markings[%d])"
                                 % (name, seen[name.lower()]))
                seen.setdefault(name.lower(), i)
            if m.get("color") is None:
                self.r.warn(path, "no color: Spotfire gives markings created through the API black")
            else:
                self.color_field(m, "color", path)
            if self.field(m, "default", path, ["bool"]):
                defaults.append(name)
        if len(defaults) > 1:
            self.r.error("markings", "%d markings have default: true (%s); at most one may"
                         % (len(defaults), ", ".join(str(d) for d in defaults)))
        elif not defaults and len(items) > 1:
            self.r.warn("markings", "no marking has default: true; '%s' (the first) becomes the default marking"
                        % self.marking_names[0])

    def v_schemes(self):
        seen = {}
        defaults = []
        for i, f in enumerate(self.section("filteringSchemes")):
            path = pjoin("filteringSchemes", i)
            if not self.obj(f, path):
                continue
            self.check_keys(f, ("name", "default"), path)
            name = self.field(f, "name", path, ["str"], required=True)
            if name is not None:
                self.naming("scheme", name, pjoin(path, "name"))
                if name.lower() in seen:
                    self.r.error(pjoin(path, "name"), "filtering scheme '%s' is declared twice (also "
                                 "filteringSchemes[%d])" % (name, seen[name.lower()]))
                seen.setdefault(name.lower(), i)
            if self.field(f, "default", path, ["bool"]):
                defaults.append(name)
        if len(defaults) > 1:
            self.r.error("filteringSchemes", "%d filtering schemes have default: true (%s); at most one may"
                         % (len(defaults), ", ".join(str(d) for d in defaults)))

    # ---- data functions --------------------------------------------------------------------------
    def v_data_functions(self):
        seen = {}
        functions = self.section("dataFunctions")
        if self.df_cycle:
            self.r.warn("dataFunctions", "data functions in a table dependency cycle keep spec order: %s"
                        % ", ".join(str(functions[i].get("name")) for i in self.df_cycle))
        for i, d in enumerate(functions):
            path = pjoin("dataFunctions", i)
            if not self.obj(d, path):
                continue
            self.check_keys(d, DF_KEYS, path)
            name = self.field(d, "name", path, ["str"], required=True)
            if name is not None:
                self.naming("function", name, pjoin(path, "name"))
                if name in seen:
                    self.r.error(pjoin(path, "name"), "data function '%s' is declared twice (also dataFunctions[%d])"
                                 % (name, seen[name]))
                seen.setdefault(name, i)
            self.field(d, "description", path, ["str"])
            engine = self.field(d, "engine", path, ["str"], choices=ENGINES) or "python"
            self.field(d, "refresh", path, ["str"], choices=REFRESH_MODES)
            ex = self.field(d, "executeAtBuild", path, ["bool"]) is not False
            code, label = None, None
            if d.get("script") is not None:
                rel = self.field(d, "script", path, ["str"])
                if rel:
                    full = self.file_path(rel, pjoin(path, "script"), "data-function script",
                                          (".py",) if engine == "python" else (".R",))
                    if full is not None:
                        code, label = self.file_text(full, pjoin(path, "script")), rel
                if d.get("scriptCode") is not None:
                    self.r.warn(pjoin(path, "scriptCode"), "both 'script' and 'scriptCode' are given; the script file "
                                "is used")
            elif d.get("scriptCode") is not None:
                code, label = self.field(d, "scriptCode", path, ["str"]), "scriptCode"
            else:
                self.r.error(path, "needs 'script' (a file under datafunctions/) or 'scriptCode'")
            if code is not None and not code.strip():
                self.r.error(path, "the data-function script is empty")
                code = None
            names = {}
            input_tables = set()
            for j, inp in enumerate(self.field(d, "inputs", path, ["list"]) or []):
                self.v_df_input(inp, pjoin(path, "inputs", j), name, i, ex, engine, names, input_tables)
            outputs = self.field(d, "outputs", path, ["list"]) or []
            if not outputs:
                self.r.warn(path, "has no outputs; a data function without outputs changes nothing in the analysis")
            for j, out in enumerate(outputs):
                self.v_df_output(out, pjoin(path, "outputs", j), name, engine, names, input_tables, code, label)
            self.add_settings(d.get("settings"), pjoin(path, "settings"), [DATA_FUNCTION_CLASS])

    def param_name(self, name, path, engine, names):
        if not name:
            self.r.error(path, "must not be empty")
            return
        if engine == "python":
            if not name.isidentifier() or keyword.iskeyword(name):
                self.r.error(path, "'%s' is not a valid Python identifier, so the script cannot read or assign it"
                             % name)
        elif not re.match(r"^[A-Za-z.][A-Za-z0-9._]*$", name):
            self.r.error(path, "'%s' is not a valid R name" % name)
        if name in names:
            self.r.error(path, "parameter name '%s' is used twice in this data function (also %s)" % (name, names[name]))
        else:
            names[name] = path

    def ref_input_table(self, tname, path, fn, fn_index, fn_ex):
        if not self.known_table(tname):
            pool = list(self.tables) + list(self.produced)
            self.r.error(path, "unknown data table '%s'%s" % (tname, did_you_mean(tname, pool)))
            return
        if self.table_ready(tname, before=self.df_pos.get(fn_index, 10 ** 9)):
            return
        producers = [p for p in self.produced.get(tname, [])]
        names = ", ".join("'%s'" % p[0] for p in producers) or "no data function"
        if any(p[1] == fn_index for p in producers) and len(producers) == 1:
            why = "'%s' writes it itself" % fn
        elif any(p[1] in self.df_cycle for p in producers) and fn_index in self.df_cycle:
            why = "%s and '%s' read each other's tables (a dependency cycle)" % (names, fn)
        else:
            why = "it is created by %s, which has executeAtBuild: false" % names
        if fn_ex:
            self.r.error(path, "'%s' runs at build, but its input table '%s' does not exist when it runs: %s"
                         % (fn, tname, why))
        else:
            self.r.warn(path, "input table '%s' does not exist yet when '%s' is registered (%s); the binding is "
                        "stored before the table exists (Not yet tested)" % (tname, fn, why))

    def v_df_input(self, inp, ip, fn, fn_index, fn_ex, engine, names, input_tables):
        if not self.obj(inp, ip):
            return
        self.check_keys(inp, DF_INPUT_KEYS, ip)
        iname = self.field(inp, "name", ip, ["str"], required=True)
        if iname is not None:
            self.param_name(iname, pjoin(ip, "name"), engine, names)
        itype = self.field(inp, "type", ip, ["str"], required=True, choices=("table", "column", "value"))
        self.field(inp, "description", ip, ["str"])
        dts = self.field(inp, "dataTypes", ip, ["list"])
        if dts is not None:
            if not dts:
                self.r.error(pjoin(ip, "dataTypes"), "must list at least one DataType (leave it out to allow all types)")
            for k, dt in enumerate(dts):
                if dt not in DATA_TYPES:
                    self.r.error(pjoin(ip, "dataTypes", k), "unknown DataType %s%s" % (describe(dt), did_you_mean(dt, DATA_TYPES)))
        bind = self.field(inp, "bind", ip, ["dict"], required=True)
        if bind is None or itype is None:
            return
        bp = pjoin(ip, "bind")
        self.check_keys(bind, BIND_KEYS[itype], bp)
        unlimited = False
        if itype in ("table", "column"):
            tname = self.field(bind, "table", bp, ["str"], required=True)
            if tname:
                self.ref_input_table(tname, pjoin(bp, "table"), fn, fn_index, fn_ex)
                input_tables.add(tname)
            if itype == "table":
                cols = bind.get("columns", "*")
                if not (cols is None or cols == "*" or (isinstance(cols, list) and cols
                                                        and all(is_str(c) and c for c in cols))):
                    self.r.error(pjoin(bp, "columns"), "must be \"*\" or a non-empty list of column names, got %s"
                                 % describe(cols))
            else:
                self.field(bind, "column", bp, ["str"], required=True)
        else:
            given = [k for k in ("property", "value", "expression") if k in bind]
            if len(given) != 1:
                self.r.error(bp, "a value input needs exactly one of property, value, expression (got %s)"
                             % (", ".join(given) or "none"))
            if "property" in bind:
                unlimited = True
                pname = self.ref_property(bind.get("property"), pjoin(bp, "property"), "bind.property", allow_outputs=False)
                if pname and iname and pname != iname and pname not in BUILTIN_PROPERTIES:
                    self.r.error(pjoin(ip, "name"), "value input '%s' is bound to property '%s': it must have the "
                                 "property's name (one name per binding)" % (iname, pname))
                pspec = self.prop_specs.get(pname) if pname else None
                if pspec and dts and pspec.get("type") in DATA_TYPES and pspec.get("type") not in dts:
                    self.r.error(pjoin(ip, "dataTypes"), "property '%s' is %s but dataTypes allows only %s; the run "
                                 "would reject the value" % (pname, pspec.get("type"), ", ".join(map(str, dts))))
            elif "value" in bind:
                unlimited = True
                v = bind.get("value")
                if v is None:
                    self.r.error(pjoin(bp, "value"), "null is not supported; bind a document property instead")
                elif isinstance(v, (list, dict)):
                    self.r.error(pjoin(bp, "value"), "must be a single value, got %s" % describe(v))
                elif dts and dts[0] in DATA_TYPES:
                    problem = typed_value_problem(v, dts[0], strict=False)
                    if problem:
                        self.r.error(pjoin(bp, "value"), problem)
            elif "expression" in bind:
                ex = self.field(bind, "expression", bp, ["str"])
                if ex is not None:
                    self.expression_refs(ex, pjoin(bp, "expression"))
        lf = bind.get("limitByFiltering")
        lm = bind.get("limitByMarking")
        if unlimited and (lf not in (None, False) or lm):
            self.r.warn(bp, "limitByFiltering / limitByMarking are ignored on property and value binds")
        if lf not in (None, False, True):
            if not is_str(lf):
                self.r.error(pjoin(bp, "limitByFiltering"), "must be a filtering scheme name, true (the active filtering "
                             "scheme) or null, got %s" % describe(lf))
            elif lf not in self.scheme_names:
                self.r.error(pjoin(bp, "limitByFiltering"), "unknown filtering scheme '%s'%s (true means the active "
                             "filtering scheme)" % (lf, did_you_mean(lf, self.scheme_names)))
        if lm not in (None, False):
            # lib/30_datafunctions.py _datafunctions_limits takes exactly one marking name
            if not is_str(lm) or not lm:
                self.r.error(pjoin(bp, "limitByMarking"), "must be one marking name (or null), got %s" % describe(lm))
            elif lm not in self.marking_names:
                self.r.error(pjoin(bp, "limitByMarking"), "unknown marking %s%s" % (describe(lm),
                             did_you_mean(lm, self.marking_names)))
            elif fn_ex and not unlimited:
                self.r.note("%s: input %s gets only the rows marked in '%s'; nothing is marked during the "
                            "build, so the build-time run of '%s' gets no rows (it must still return typed "
                            "outputs)" % (bp, iname, lm, fn))

    def v_df_output(self, out, op, fn, engine, names, input_tables, code, label):
        if not self.obj(out, op):
            return
        self.check_keys(out, DF_OUTPUT_KEYS, op)
        oname = self.field(out, "name", op, ["str"], required=True)
        if oname is not None:
            self.param_name(oname, pjoin(op, "name"), engine, names)
        if out.get("type") in ("column", "columns"):
            self.r.error(pjoin(op, "type"), "column outputs are not in spec v1; use a table output")
            otype = None
        else:
            otype = self.field(out, "type", op, ["str"], required=True, choices=("table", "value"))
        self.field(out, "description", op, ["str"])
        target = self.field(out, "target", op, ["dict"], required=True)
        tp = pjoin(op, "target")
        if target is not None and otype == "table":
            self.check_keys(target, ("table",), tp)
            tname = self.field(target, "table", tp, ["str"], required=True)
            if tname:
                if tname not in self.tables:
                    self.naming("table", tname, pjoin(tp, "table"))
                if tname in input_tables:
                    self.r.warn(tp, "'%s' reads and replaces table '%s': a circular dependency (Spotfire may refuse "
                                "it or loop on automatic refresh)" % (fn, tname))
        elif target is not None and otype == "value":
            self.check_keys(target, ("property",), tp)
            pname = self.field(target, "property", tp, ["str"], required=True)
            if pname:
                pp = pjoin(tp, "property")
                if pname in BUILTIN_PROPERTIES:
                    self.r.error(pp, "'%s' is a built-in property; write results to a property of your own" % pname)
                else:
                    canon = self.props.get(pname.lower())
                    if canon is None:
                        if PROPERTY_NAME_RE.match(pname):
                            self.naming("property", pname, pp)
                        else:
                            self.r.error(pp, "'%s' is not a valid document property name (letters and digits, dot-"
                                         "separated segments)" % pname)
                        self.r.warn(pp, "property '%s' is not declared in 'properties'; the first run creates it with "
                                    "the type the script returns (declare it to fix type and description)" % pname)
                    elif canon != pname:
                        self.r.error(pp, "'%s' must be written exactly like the property, '%s' (one name per "
                                     "binding)" % (pname, canon))
                    pspec = self.prop_specs.get(canon) if canon else None
                    ptype = pspec.get("type") if isinstance(pspec, dict) else None
                    # A property output keeps one DataType; a Python int exports as LongInteger and a float
                    # as Real (api-data-functions fact 10), so Integer / SingleReal need numpy.int32 / float32.
                    natural = {"Integer": ("int", "LongInteger", "int32"), "SingleReal": ("float", "Real", "float32")}
                    if engine == "python" and ptype in natural and code is not None and natural[ptype][2] not in code:
                        py_type, other, np_type = natural[ptype]
                        self.r.warn(pp, "property '%s' is %s, but a Python %s exports as %s, so the run fails with "
                                    "'Changing datatype of existing property'; declare the property %s or return "
                                    "numpy.%s from the script" % (canon, ptype, py_type, other, other, np_type))
                    if oname and pname != oname:
                        self.r.error(pjoin(op, "name"), "value output '%s' writes property '%s': it must have the "
                                     "property's name (one name per binding)" % (oname, pname))
        if code is not None and oname and not script_assigns(code, oname, engine):
            how = "'%s =' or '%s <-'" % (oname, oname) if engine == "terr" else "'%s ='" % oname
            self.r.error(pjoin(op, "name"), "the script (%s) never assigns output '%s': no line starting with %s"
                         % (label, oname, how))

    # ---- scripts and triggers ------------------------------------------------------------------
    def v_scripts(self):
        seen = {}
        for i, sc in enumerate(self.section("scripts")):
            path = pjoin("scripts", i)
            if not self.obj(sc, path):
                continue
            self.check_keys(sc, SCRIPT_KEYS, path)
            name = self.field(sc, "name", path, ["str"], required=True)
            np_ = pjoin(path, "name")
            if name is not None:
                bad = sorted(set(ch for ch in name if ch in BAD_SCRIPT_NAME_CHARS or ord(ch) < 32))
                if not name.strip():
                    self.r.error(np_, "must not be empty")
                elif bad:
                    self.r.error(np_, "script names cannot contain %s" % " ".join(repr(b) for b in bad))
                self.naming("script", name, np_)
                if name in seen:
                    self.r.error(np_, "script '%s' is declared twice (also scripts[%d])" % (name, seen[name]))
                else:
                    others = [k for k in seen if k.lower() == name.lower()]
                    if others:
                        self.r.warn(np_, "'%s' differs only in case from script '%s'" % (name, others[0]))
                seen.setdefault(name, i)
            self.field(sc, "description", path, ["str"])
            code = None
            code_path = pjoin(path, "code")
            job = None
            if sc.get("file") is not None:
                code_path = pjoin(path, "file")
                rel = self.field(sc, "file", path, ["str"])
                if rel:
                    full = self.file_path(rel, code_path, "script file", (".py",))
                    if full is not None:
                        code = self.file_text(full, code_path)
                        if code is not None:
                            job = {"path": code_path, "label": rel, "file": full, "document": True}
                if sc.get("code") is not None:
                    self.r.warn(pjoin(path, "code"), "both 'file' and 'code' are given; the file is used")
            elif sc.get("code") is not None:
                code = self.field(sc, "code", path, ["str"])
                if code is not None:
                    job = {"path": code_path, "label": "script '%s'" % name, "code": code, "document": True}
            else:
                self.r.error(path, "needs 'file' (scripts/...) or 'code'")
            if code is not None and not code.strip():
                self.r.error(code_path, "the script is empty")
                job = None
            if code is not None:
                self.script_codes.append(code)
            pnames = []
            if job is not None:
                job["globals"] = pnames            # script parameters are globals of the script (filled below)
                self.ipy_jobs.append(job)
            for j, prm in enumerate(self.field(sc, "parameters", path, ["list"]) or []):
                pp = pjoin(path, "parameters", j)
                if not self.obj(prm, pp):
                    continue
                self.check_keys(prm, ("name", "type", "description"), pp)
                pn = self.field(prm, "name", pp, ["str"], required=True)
                if pn is not None:
                    if not _IDENT_RE.match(pn) or pn in PY_RESERVED:
                        self.r.error(pjoin(pp, "name"), "'%s' is not a valid IronPython identifier" % pn)
                    if pn in pnames:
                        self.r.error(pjoin(pp, "name"), "parameter '%s' is declared twice" % pn)
                    pnames.append(pn)
                self.field(prm, "type", pp, ["str"], choices=PARAM_TYPES)
                self.field(prm, "description", pp, ["str"])
            self.field(sc, "transaction", path, ["bool"])
            if code:
                self.script_property_refs(code, code_path)

    def script_property_refs(self, code, path):
        """One name per binding: property lookups in IronPython must name declared properties."""
        for m in _PROP_LOOKUP_RE.finditer(code):
            name = m.group(2) or m.group(4)
            if not name or name in BUILTIN_PROPERTIES:
                continue
            canon = self.props.get(name.lower())
            if canon is None:
                canon = next((p for p in self.df_props if p.lower() == name.lower()), None)
            if canon is None:
                self.r.warn(path, "uses document property '%s', which the spec does not declare%s"
                            % (name, did_you_mean(name, list(self.prop_specs))))
            elif canon != name:
                self.r.warn(path, "uses '%s' but the property is named '%s' (one name per binding)" % (name, canon))

    def v_triggers(self):
        seen = {}
        for i, tr in enumerate(self.section("triggers")):
            path = pjoin("triggers", i)
            if not self.obj(tr, path):
                continue
            self.check_keys(tr, ("property", "script"), path)
            prop = self.field(tr, "property", path, ["str"], required=True)
            script = self.field(tr, "script", path, ["str"], required=True)
            canon = self.ref_property(prop, pjoin(path, "property")) if prop is not None else None
            if script is not None:
                sspec = self.scripts.get(script)
                if sspec is None:
                    self.r.error(pjoin(path, "script"), "unknown script '%s'%s" % (script, did_you_mean(script, list(self.scripts))))
                elif as_list(sspec.get("parameters")):
                    self.r.warn(pjoin(path, "script"), "script '%s' declares parameters; a property trigger passes no "
                                "arguments" % script)
            key = (canon or prop or "").lower()
            if key:
                if key in seen:
                    self.r.error(path, "property '%s' already has a trigger (triggers[%d]); Spotfire runs one script "
                                 "per property" % (prop, seen[key]))
                else:
                    seen[key] = i

    # ---- action mods ---------------------------------------------------------------------------
    def v_action_mods(self):
        """actionMods: [{id, project}] - the mods that buttons (actionMod) and visual actionTriggers run
        (spec-format.md "Action mods"). The builder cannot wire them (no public API): every button runs
        its IronPython script or action, and MANUAL-STEPS lists the action-mod wiring. The project
        folder's mod-manifest.json, when it exists, is read for the script ids and parameters."""
        for i, m in enumerate(self.section("actionMods")):
            path = pjoin("actionMods", i)
            if not self.obj(m, path):
                continue
            self.check_keys(m, ("id", "project"), path)
            mod_id = self.field(m, "id", path, ["str"], required=True)
            project = self.field(m, "project", path, ["str"])
            if not mod_id:
                continue
            if mod_id in self.action_mods:
                self.r.error(pjoin(path, "id"), "action mod '%s' is listed twice" % mod_id)
                continue
            manifest = None
            folder = self.app_dir / project.strip() if project and project.strip() else None
            if folder is None:
                self.r.warn(path, "no 'project': the mod must already be embedded, installed or pinned in Analyst "
                            "(script ids are not checked)")
            elif not folder.is_dir():
                self.r.warn(pjoin(path, "project"), "folder not found: %s; the mod must then be embedded, installed "
                            "or pinned in Analyst (script ids are not checked)" % folder)
            else:
                mpath = folder / "mod-manifest.json"
                if mpath.is_file():
                    text = self.file_text(mpath, pjoin(path, "project"))
                    try:
                        manifest = json.loads(text) if text is not None else None
                    except ValueError as e:
                        self.r.error(pjoin(path, "project"), "%s is not valid JSON: %s" % (mpath, e))
                    if manifest is not None and not isinstance(manifest, dict):
                        self.r.error(pjoin(path, "project"), "%s must hold a JSON object" % mpath)
                        manifest = None
                    if manifest is not None:
                        if manifest.get("id") != mod_id:
                            self.r.error(pjoin(path, "id"), "the manifest's id is %s, not '%s'"
                                         % (describe(manifest.get("id")), mod_id))
                        if manifest.get("type") != "action":
                            self.r.warn(pjoin(path, "project"), "the manifest's type is %s, not \"action\""
                                        % describe(manifest.get("type")))
                        unbuilt = [sc["file"] for sc in as_list(manifest.get("scripts"))
                                   if isinstance(sc, dict) and is_str(sc.get("file"))
                                   and not (folder / sc["file"]).is_file()]
                        if unbuilt:
                            self.r.warn(pjoin(path, "project"), "%d script bundle(s) not built yet (%s): run npm run "
                                        "build in %s before you add the mod to the analysis"
                                        % (len(unbuilt), ", ".join(unbuilt), folder))
                elif (folder / (mod_id + ".mod")).is_file():
                    self.r.note("action mod '%s' comes from %s (script ids are not checked)"
                                % (mod_id, folder / (mod_id + ".mod")))
                else:
                    self.r.warn(pjoin(path, "project"), "no mod-manifest.json or %s.mod in %s; the mod must then be "
                                "embedded, installed or pinned in Analyst (script ids are not checked)"
                                % (mod_id, folder))
            self.action_mods[mod_id] = manifest

    def v_action_label(self, label, path):
        """An action label (a button's actionMod.label, a visual trigger's label): the name of the action
        configuration, which Spotfire shows as the menu item text and the button tooltip."""
        if not is_str(label) or not label.strip():
            self.r.error(path, "must be a non-empty string (the action's name in menus and tooltips), got %s"
                         % describe(label))
        elif "\n" in label or "\r" in label or "\t" in label:
            self.r.error(path, "must be one line: it is the action's name in menus and tooltips")
        elif label != label.strip():
            self.r.warn(path, "starts or ends with spaces; Spotfire shows them in menus and tooltips")

    def v_action_mod_ref(self, ref, path, order, trigger=False):
        """One actionMod reference {mod, script, args} (a button's actionMod, a visual trigger's). A
        button's may add "label" (the action configuration's name); a trigger's label sits on the trigger,
        next to display and actionMod."""
        if not self.obj(ref, path):
            return
        if trigger and "label" in ref:
            self.r.error(pjoin(path, "label"), "a trigger's label goes on the trigger, next to 'display' and "
                         "'actionMod' (actionTriggers[].label)")
        self.check_keys(ref, ("mod", "script", "args", "label"), path)
        if not trigger and "label" in ref:
            self.v_action_label(ref["label"], pjoin(path, "label"))
        mod_id = self.field(ref, "mod", path, ["str"], required=True)
        script_id = self.field(ref, "script", path, ["str"], required=True)
        args = self.field(ref, "args", path, ["dict"]) or {}
        if mod_id is None or script_id is None:
            return
        if mod_id not in self.action_mods:
            self.r.error(pjoin(path, "mod"), "unknown action mod '%s'%s (list it in actionMods)"
                         % (mod_id, did_you_mean(mod_id, list(self.action_mods))))
            return
        manifest = self.action_mods[mod_id]
        if manifest is None:
            self.r.warn(pjoin(path, "script"), "script id '%s' is not checked: action mod '%s' has no "
                        "mod-manifest.json in its project folder" % (script_id, mod_id))
            return
        scripts = dict((sc.get("id"), sc) for sc in as_list(manifest.get("scripts")) if isinstance(sc, dict))
        sc = scripts.get(script_id)
        if sc is None:
            self.r.error(pjoin(path, "script"), "action mod '%s' has no script '%s'%s (its mod-manifest.json)"
                         % (mod_id, script_id, did_you_mean(script_id, [k for k in scripts if is_str(k)])))
            return
        params = dict((prm.get("name"), prm) for prm in as_list(sc.get("parameters")) if isinstance(prm, dict))
        for name, prm in params.items():
            if name not in args and not prm.get("optional"):
                self.r.warn(pjoin(path, "args"), "parameter '%s' of '%s' gets no value (add it to args)"
                            % (name, script_id))
        for name, value in args.items():
            ap = pjoin(path, "args", name)
            prm = params.get(name)
            if prm is None:
                self.r.error(ap, "script '%s' has no parameter '%s'%s" % (script_id, name,
                                                                        did_you_mean(name, list(params))))
                continue
            ptype = prm.get("type") or "String"
            if ptype not in PARAM_TYPES:
                self.r.error(ap, "a %s parameter cannot be set by the builder (literal values, Page, "
                             "Visualization and DataTable only)" % ptype)
            elif ptype == "Page":
                if not is_str(value) or value not in self.page_titles:
                    self.r.error(ap, "must be the title of a page (Page parameter), got %s" % describe(value))
            elif ptype == "Visualization":
                if not is_str(value) or value not in self.visuals:
                    self.r.error(ap, "must be the id of a visual (Visualization parameter), got %s"
                                 % describe(value))
                elif self.visuals[value]["order"] > order:
                    self.r.warn(ap, "visual '%s' is built after this one, so this argument fails at build time"
                                % value)
            elif ptype == "DataTable":
                self.ref_table(value, ap, "DataTable argument")
            elif ptype == "String":
                if not is_str(value):
                    self.r.error(ap, "must be a string, got %s" % describe(value))
                elif isinstance(prm.get("enum"), list) and value not in prm["enum"]:
                    self.r.error(ap, "must be one of %s, got %s" % (", ".join(map(str, prm["enum"])),
                                                                   describe(value)))
            elif ptype in DATA_TYPES:
                problem = typed_value_problem(value, ptype, strict=False)
                if problem:
                    self.r.error(ap, problem)

    def v_action_triggers(self, v, path, order):
        triggers = self.field(v, "actionTriggers", path, ["list"])
        named = {}
        for k, t in enumerate(triggers or []):
            tp = pjoin(path, "actionTriggers", k)
            if not self.obj(t, tp):
                continue
            self.check_keys(t, ("display", "actionMod", "label"), tp)
            self.field(t, "display", tp, ["str"], choices=TRIGGER_DISPLAYS)
            if t.get("actionMod") is None:
                self.r.error(tp, "missing required field 'actionMod'")
            else:
                self.v_action_mod_ref(t["actionMod"], pjoin(tp, "actionMod"), order, trigger=True)
            if "label" in t:
                self.v_action_label(t["label"], pjoin(tp, "label"))
                if is_str(t["label"]) and t["label"].strip():
                    key = (t.get("display") or "FloatingButton", t["label"].strip().lower())
                    if key in named:
                        self.r.warn(pjoin(tp, "label"), "same label as actionTriggers[%d], both %s: users cannot "
                                    "tell the two actions apart" % (named[key], key[0]))
                    else:
                        named[key] = k

    # ---- pages ---------------------------------------------------------------------------------
    def v_pages(self):
        pages = self.section("pages")
        if not pages:
            self.r.warn("pages", "no pages: the analysis would be empty")
        seen = {}
        for i, pg in enumerate(pages):
            path = pjoin("pages", i)
            if not self.obj(pg, path):
                continue
            self.check_keys(pg, PAGE_KEYS, path)
            title = self.field(pg, "title", path, ["str"], required=True)
            if title is not None:
                tp = pjoin(path, "title")
                if not title.strip():
                    self.r.error(tp, "must not be empty")
                else:
                    self.naming("page", title, tp)
                    self.expression_refs(title, tp)
                low = title.lower()
                if low in seen:
                    self.r.error(tp, "page title '%s' is used twice (also pages[%d]); page titles must be unique "
                                 "(case-insensitive)" % (title, seen[low]))
                else:
                    seen[low] = i
            self.field(pg, "visible", path, ["bool"])
            self.field(pg, "filterPanel", path, ["bool"])
            if pg.get("filters") is not None and pg["filters"] != t3._filters.ALL and not isinstance(pg["filters"], dict):
                self.r.error(pjoin(path, "filters"), "must be a filter layout {\"tables\": [...]} or \"all\" (Spotfire's "
                             "default panel: every table and column), got %s" % describe(pg["filters"]))
            self.field(pg, "detailsOnDemand", path, ["bool"])
            scheme = self.field(pg, "filteringScheme", path, ["str"])
            if scheme is not None and scheme not in self.scheme_names:
                self.r.error(pjoin(path, "filteringScheme"), "unknown filtering scheme '%s'%s (null = the default "
                             "scheme)" % (scheme, did_you_mean(scheme, self.scheme_names)))
            visuals = self.field(pg, "visuals", path, ["list"]) or []
            if not visuals:
                self.r.warn(path, "page %s has no visuals" % json.dumps(title))
            ids = []
            for j, v in enumerate(visuals):
                vid = self.v_visual(v, pjoin(path, "visuals", j))
                if vid:
                    ids.append(vid)
            self.v_layout(pg.get("layout"), pjoin(path, "layout"), ids)
        if self.mod_visuals and newer_than("14.8", self.min_version):
            self.r.warn("pages", "mod visual(s) %s need Spotfire 14.8 or newer to run the builder (ModVisualization.Axis "
                        "[api 14.7], Property<T> [api 14.8]); minimumSpotfireVersion is %s (the saved DXP still opens "
                        "in 14.6)" % (", ".join("'%s'" % m for m in self.mod_visuals), self.min_version))

    def marking_users(self, pg):
        """{marking: [(visual id or 'id/layer title', table)]} of one page: every non-text visual and map data
        layer that can be marked (an absent marking = the default marking, null = cannot be marked)."""
        users = {}
        default_table = self.spec.get("defaultTable")
        for v in as_list(pg.get("visuals")):
            if not isinstance(v, dict) or v.get("type") in (None, "textArea"):
                continue
            vid = str(v.get("id"))
            table = v.get("table") or default_table
            vm = v["marking"] if "marking" in v else self.default_marking
            if v.get("type") == "map":
                for layer in as_list(v.get("layers")):
                    if not isinstance(layer, dict) or layer.get("kind") not in ("marker", "feature"):
                        continue
                    m = layer["marking"] if "marking" in layer else vm
                    if is_str(m):
                        label = "%s/%s" % (vid, layer.get("title") or layer.get("table") or table)
                        users.setdefault(m, []).append((label, layer.get("table") or table))
                continue
            if v.get("type") == "mod":
                for layer in as_list(v.get("layers")):          # each layer is a view of its own
                    if not isinstance(layer, dict):
                        continue
                    m = layer["marking"] if "marking" in layer else vm
                    if is_str(m):
                        label = "%s/%s" % (vid, layer.get("title") or layer.get("type"))
                        users.setdefault(m, []).append((label, layer.get("table") or table))
            if is_str(vm):
                users.setdefault(vm, []).append((vid, table))
        return users

    def v_marking_reach(self):
        """Interaction audit (notes only; every marking must reach every relevant item of its page). The standard engine has no relations, so a marking highlights only visuals on the
        same table; a marking used by one visual of a page that limits nothing and that no data function
        reads changes nothing else when the user marks."""
        limiting = set()
        for d in self.section("dataFunctions"):
            for i in as_list(d.get("inputs")) if isinstance(d, dict) else []:
                b = i.get("bind") if isinstance(i, dict) and isinstance(i.get("bind"), dict) else {}
                if is_str(b.get("limitByMarking")):
                    limiting.add(b["limitByMarking"])
        pages = [pg for pg in self.section("pages") if isinstance(pg, dict)]
        for pg in pages:
            for v in as_list(pg.get("visuals")):
                if isinstance(v, dict):
                    limiting.update(m for m in as_list(v.get("limitByMarkings")) if is_str(m))
                    for layer in as_list(v.get("layers")):
                        if isinstance(layer, dict):
                            limiting.update(m for m in as_list(layer.get("limitByMarkings")) if is_str(m))
        for pg in pages:
            title = pg.get("title")
            users = self.marking_users(pg)
            for m in sorted(users):
                items = users[m]
                tables = sorted(set(str(t) for _, t in items))
                scripted = any(('"%s"' % m) in c or ("'%s'" % m) in c for c in self.script_codes)
                if len(items) == 1 and m not in limiting:
                    self.r.note("interactions, page %s: marking '%s' is used only by %s (%s): nothing else on "
                                "the page highlights or reacts when it is marked (no visual is limited by it, no "
                                "data function reads it%s); share it with the visuals on that table, add a "
                                "marking-limited data function, or give the visual \"marking\": null"
                                % (json.dumps(title), m, items[0][0], items[0][1],
                                   "; a script names it, so a button can still read it" if scripted else ""))
                elif len(tables) > 1:
                    self.r.note("interactions, page %s: marking '%s' spans tables %s; only visuals on the same "
                                "table highlight each other (no relations in the standard engine): %s"
                                % (json.dumps(title), m, ", ".join(tables),
                                   "; ".join("%s: %s" % (t, ", ".join(lbl for lbl, tt in items if str(tt) == t))
                                             for t in tables)))
            by_table = {}
            for m, items in users.items():
                for lbl, t in items:
                    by_table.setdefault(str(t), {}).setdefault(m, []).append(lbl)
            for t in sorted(by_table):
                if len(by_table[t]) > 1:
                    self.r.note("interactions, page %s: table %s is shown with different markings (%s): marking "
                                "one does not highlight the others" % (json.dumps(title), t, "; ".join(
                                    "%s: %s" % (m, ", ".join(lbls)) for m, lbls in sorted(by_table[t].items()))))

    def v_layout(self, layout, path, ids):
        if layout is None or layout == {}:
            if len(ids) > 1:
                self.r.error(path, "required when a page has more than one visual (%d here): {\"row\": [...]} or "
                             "{\"column\": [...]}" % len(ids))
            return
        if not isinstance(layout, dict):
            self.r.error(path, "must be an object like {\"row\": [...]}, got %s" % describe(layout))
            return
        counts = {}
        self._layout_walk(layout, path, None, counts, True)
        for vid in ids:
            n = counts.get(vid, 0)
            if n == 0:
                self.r.error(path, "visual '%s' is not in the layout (every visual appears exactly once)" % vid)
            elif n > 1:
                self.r.error(path, "visual '%s' appears %d times in the layout (every visual appears exactly once)"
                             % (vid, n))
        for vid in counts:
            if vid in ids:
                continue
            info = self.visuals.get(vid)
            if info:
                self.r.error(path, "visual '%s' belongs to page %s, not to this one" % (vid, json.dumps(info.get("pageTitle"))))
            else:
                self.r.error(path, "unknown visual '%s' in the layout%s" % (vid, did_you_mean(vid, ids)))

    def _layout_walk(self, node, path, parent, counts, root):
        if not isinstance(node, dict):
            self.r.error(path, "must be an object: {\"row\": [...]}, {\"column\": [...]} or {\"visual\": \"id\"}, got %s"
                         % describe(node))
            return
        kinds = [k for k in ("row", "column", "visual") if k in node]
        if len(kinds) != 1:
            self.r.error(path, "needs exactly one of row, column, visual (got %s)" % (", ".join(kinds) or "none"))
            return
        kind = kinds[0]
        for k in node:
            if k not in (kind, "weight"):
                self.r.warn(pjoin(path, k), "unknown field '%s' in the layout; the builder ignores it" % k)
        if "weight" in node and not root:
            w = node["weight"]
            if not is_num(w):
                self.r.error(pjoin(path, "weight"), "must be a number, got %s" % describe(w))
            elif not 1e-12 <= w <= 1e12:
                self.r.error(pjoin(path, "weight"), "must be a positive number, got %s" % w)
        if kind == "visual":
            vid = node["visual"]
            if not is_str(vid) or not vid:
                self.r.error(pjoin(path, "visual"), "must be a visual id, got %s" % describe(vid))
                return
            counts[vid] = counts.get(vid, 0) + 1
            return
        if kind == parent:
            self.r.error(path, "a %s directly inside a %s; nested containers must alternate row and column" % (kind, kind))
        items = node[kind]
        if not isinstance(items, list) or not items:
            self.r.error(pjoin(path, kind), "must be a non-empty list")
            return
        for i, item in enumerate(items):
            self._layout_walk(item, pjoin(path, kind, i), kind, counts, False)

    # ---- visuals -------------------------------------------------------------------------------
    def v_visual(self, v, path):
        if not self.obj(v, path):
            return None
        vid = self.field(v, "id", path, ["str"], required=True)
        vtype = self.field(v, "type", path, ["str"], required=True, choices=VISUAL_TYPES)
        if vid is not None:
            ip = pjoin(path, "id")
            if not vid:
                self.r.error(ip, "must not be empty")
                vid = None
            else:
                if not VISUAL_ID_RE.match(vid):
                    self.r.warn(ip, "use letters, digits, '-' and '_' in visual ids, starting with a letter")
                if vid in self.visual_seen:
                    self.r.error(ip, "visual id '%s' is used twice (also %s); ids must be unique across the app"
                                 % (vid, self.visual_seen[vid]))
                else:
                    self.visual_seen[vid] = path
        if vtype is None:
            return vid
        is_text = vtype == "textArea"
        specific = VISUAL_FIELDS.get(vtype, {})
        common = TEXT_AREA_COMMON_KEYS if is_text else COMMON_VISUAL_KEYS
        styles = t3.visual_style_keys(vtype)          # references/spec-format.md "Per-visual style keys"
        for k in v:
            if k in common or k in specific:
                continue
            if k in styles:
                problem = t3.check_visual_style(vtype, k, v[k], self.palette_names())
                if problem:
                    self.r.error(pjoin(path, k), problem)
                elif styles[k] == "format":
                    self.format_hint(v[k], pjoin(path, k))
                continue
            if is_text and k in COMMON_VISUAL_KEYS:
                self.r.warn(pjoin(path, k), "'%s' does not apply to text areas; the builder ignores it" % k)
            else:
                self.r.warn(pjoin(path, k), "unknown field '%s' for a %s%s; the builder ignores it"
                            % (k, vtype, did_you_mean(k, list(common) + list(specific))))
        title = self.field(v, "title", path, ["str"])
        if title:
            self.expression_refs(title, pjoin(path, "title"))
            if _AUTO_NAME.search(title):
                self.r.warn(pjoin(path, "title"), "'%s' looks auto-generated; give the visual a real title" % title)
        show_title = self.field(v, "showTitle", path, ["bool"])
        if not (title or "").strip() and show_title is not False and vid:
            self.r.warn(path, "visual '%s' has no title but shows its title bar (SPEC default title \"\" is stored "
                        "as an empty title); give it a title or set showTitle: false" % vid)
        description = self.field(v, "description", path, ["str"])
        if is_text and description and description.strip():
            # HtmlTextArea has no Description (lib/80_textareas.py warns and drops it at build time)
            self.r.warn(pjoin(path, "description"), "text areas have no description in Spotfire; it is not stored")
        settings = v.get("settings")
        if isinstance(settings, dict) and not is_text:
            settings = dict((SETTINGS_ALIASES.get(k, k), val) for k, val in settings.items())
        self.add_settings(settings, pjoin(path, "settings"), [CONTENT_CLASS[vtype]])
        post = self.field(v, "postScript", path, ["str"])
        if post is not None:
            if not post.strip():
                self.r.warn(pjoin(path, "postScript"), "is empty")
            else:
                if "\n" not in post and re.match(r"^[\w./\\ -]+\.py$", post.strip()):
                    self.r.warn(pjoin(path, "postScript"), "postScript is IronPython code, not a file path")
                # run_post_script (lib/00_core.py) puts Document, Application, B, visual and content in scope
                self.ipy_jobs.append({"path": pjoin(path, "postScript"), "label": "postScript of '%s'" % vid,
                                      "code": post, "document": True, "globals": ["visual", "content", "B"]})
        info = self.visuals.get(vid) if vid else None
        order = info["order"] if info else 10 ** 9
        if v.get("actionTriggers") is not None:
            self.v_action_triggers(v, path, order)
        if is_text:
            self.v_textarea(v, path, vid, order)
        else:
            self.v_visual_data(v, path, vtype)
            self.v_visual_fields(v, path, vtype)
        if vtype == "mod":
            self.mod_visuals.append(vid or path)
            self.v_mod_visual(v, path)
        return vid

    def v_visual_data(self, v, path, vtype):
        if v.get("table") is not None:
            t = self.field(v, "table", path, ["str"])
            if t is not None:
                self.ref_table(t, pjoin(path, "table"))
        elif self.spec.get("defaultTable") is None and not self.tables and not self.produced:
            self.r.error(path, "has no data table: the app has no tables (add one to 'tables', or set 'table')")
        if v.get("marking") is not None:
            m = self.field(v, "marking", path, ["str"])
            if m is not None and m not in self.marking_names:
                self.r.error(pjoin(path, "marking"), "unknown marking '%s'%s (null = cannot be marked)"
                             % (m, did_you_mean(m, self.marking_names)))
        for k, m in enumerate(self.field(v, "limitByMarkings", path, ["list"]) or []):
            if not is_str(m) or m not in self.marking_names:
                self.r.error(pjoin(path, "limitByMarkings", k), "unknown marking %s%s" % (describe(m), did_you_mean(m, self.marking_names)))
        self.field(v, "emptyMarkingBehavior", path, ["str"], choices=EMPTY_MARKING_BEHAVIORS)
        limit = self.field(v, "limitExpression", path, ["str"])
        if limit is not None:
            self.expression_refs(limit, pjoin(path, "limitExpression"),
                                 strict="limiting expression" if vtype == "mod" else None)
        self.field(v, "useFiltering", path, ["bool"])
        legend = v.get("legend")
        lp = pjoin(path, "legend")
        if isinstance(legend, bool):
            self.r.warn(lp, "write {\"visible\": %s}; a bare boolean is accepted" % json.dumps(legend))
        elif isinstance(legend, dict):
            self.check_keys(legend, ("visible", "hide"), lp)
            self.field(legend, "visible", lp, ["bool"])
            kinds = {"map": MAP_LEGEND_HIDE_KINDS, "mod": MOD_LEGEND_HIDE_KINDS}.get(vtype, LEGEND_HIDE_KINDS)
            for k, kind in enumerate(self.field(legend, "hide", lp, ["list"]) or []):
                if kind not in kinds:
                    self.r.error(pjoin(lp, "hide", k), "%s is not a legend item kind%s%s (%s)"
                                 % (json.dumps(kind), {"map": " of a map", "mod": " of a mod visual"}.get(vtype, ""),
                                    did_you_mean(kind, kinds), ", ".join(kinds)))
        elif legend is not None:
            self.r.error(lp, "must be {\"visible\": true|false, \"hide\": [...]}, got %s" % describe(legend))
        ctx = {"table": "table", "crossTable": "crossTable", "kpiChart": "kpi", "summaryTable": "summaryTable",
               "mod": "mod", "map": "map", "graphicalTable": "graphicalTable", "heatMap": "heatMap"}.get(vtype, "chart")
        if v.get("coloring") is not None:
            self.v_coloring(v["coloring"], pjoin(path, "coloring"), ctx)
        layers = self.field(v, "referenceLayers", path, ["list"])
        if layers:
            if vtype not in REFERENCE_LAYER_TYPES:
                self.r.error(pjoin(path, "referenceLayers"), "%s visuals have no reference layers (line, bar, combination, "
                             "scatter, box and waterfall charts and histograms do)" % vtype)
            else:
                for k, layer in enumerate(layers):
                    self.v_reference_layer(layer, pjoin(path, "referenceLayers", k))
        models = self.field(v, "fittingModels", path, ["list"])
        if models:
            if vtype not in FITTING_MODEL_TYPES:
                self.r.error(pjoin(path, "fittingModels"), "%s visuals have no lines and curves (line, bar, combination, "
                             "scatter, box and waterfall charts and histograms do)" % vtype)
            else:
                for k, model in enumerate(models):
                    self.v_fitting_model(model, pjoin(path, "fittingModels", k))

    def v_marker_aggregation(self, obj, path):
        """Scatter plots and map marker layers: unless the marker-by contains baserowid() Spotfire
        aggregates the markers, and a raw label / size / line order / rotation makes the whole visual
        show 'Please specify an aggregation method.' and draw nothing - on a map one bad layer blanks
        the whole map (references/api-maps.md, "How a working map is configured")."""
        settings = obj.get("settings") if isinstance(obj.get("settings"), dict) else {}
        if row_level(settings.get("MarkerByAxis.Expression")):
            return
        items = [(pjoin(path, k), obj.get(k), agg) for k, agg in MARKER_AGG_FIELDS]
        items += [(pjoin(path, "settings", k), settings.get(k), agg) for k, agg in MARKER_AGG_SETTINGS]
        for p, value, agg in items:
            for text in (value if isinstance(value, list) else [value]):
                raw = unaggregated(text)
                if not raw:
                    continue
                t = text.strip()
                self.r.error(p, "'%s' is not aggregated (%s): the markers are aggregated (the marker-by is not "
                             "row level), so Spotfire shows 'Please specify an aggregation method.' and draws "
                             "nothing%s; write %s(%s), or give the settings \"MarkerByAxis.Expression\": "
                             "\"<baserowid()>\"" % (t, ", ".join("[%s]" % r for r in raw),
                                                   " (one bad layer blanks the whole map)" if ".layers[" in p
                                                   else "", agg, t if t.startswith("[") else "[%s]" % t))

    def v_visual_fields(self, v, path, vtype):
        for key, kind in VISUAL_FIELDS.get(vtype, {}).items():
            if v.get(key) is not None:
                self.check_kind(v[key], kind, pjoin(path, key), v)
        if vtype == "scatterPlot":
            self.v_marker_aggregation(v, path)        # scatterPlot3D: lib/60_charts.py uses <baserowid()>
        if vtype == "table" and isinstance(v.get("negatives"), list) and isinstance(v.get("columns"), list):
            shown = set(c.strip()[1:-1] if c.strip().startswith("[") and c.strip().endswith("]") else c.strip()
                        for c in v["columns"] if is_str(c))
            for k, col in enumerate(v["negatives"]):
                if is_str(col) and col.strip("[]") not in shown:
                    self.r.error(pjoin(path, "negatives", k), "red negatives are asked for column '%s', which the "
                                 "table does not show (add it to 'columns')" % col)
        if vtype == "histogram" and v.get("column") is None:
            self.r.error(path, "a histogram needs 'column'")
        if vtype == "mod" and v.get("modId") is None:
            self.r.error(path, "a mod visual needs 'modId'")
        if vtype == "kpiChart" and not v.get("kpis"):
            self.r.error(path, "a KPI chart needs at least one entry in 'kpis'")
        if vtype == "map" and not v.get("layers"):
            self.r.warn(path, "a map without layers is empty; add a tile layer and a marker or feature layer")
        if vtype == "map" and v.get("interactiveLayer") is not None:
            titles = [layer.get("title") or layer.get("table") or v.get("table") or self.spec.get("defaultTable")
                      for layer in as_list(v.get("layers")) if isinstance(layer, dict) and layer.get("kind") != "tile"]
            if v["interactiveLayer"] not in titles:
                self.r.error(pjoin(path, "interactiveLayer"), "names no data layer of this map (%s)"
                             % ", ".join(str(t) for t in titles))
        if vtype == "combinationChart":
            series = [s.get("expression") for s in as_list(v.get("series")) if isinstance(s, dict)]
            for k, ex in enumerate(as_list(v.get("secondaryScale"))):
                if is_str(ex) and series and ex not in series:
                    self.r.warn(pjoin(path, "secondaryScale", k), "'%s' is not one of the series expressions" % ex)

    def check_kind(self, value, kind, path, v=None):
        if kind == "any":
            return
        if isinstance(kind, tuple):
            choices = kind[1:] if kind[0] == "ci" else kind
            ok = (is_str(value) and value.strip().lower() in [c.lower() for c in choices]) if kind[0] == "ci" \
                else value in choices
            if not ok:
                self.r.error(path, "must be one of %s, got %s%s" % (", ".join(choices), describe(value),
                                                                   did_you_mean(value, choices)))
            return
        if kind == "labels":
            if not (is_bool(value) or (is_str(value) and value.strip().lower() in ("all", "marked", "none"))):
                self.r.error(path, "must be true, false, \"all\", \"marked\" or \"none\", got %s" % describe(value))
            return
        if kind in ("linewidth", "markersize"):
            low, high = (1, 10) if kind == "linewidth" else (0, 100)
            if not is_num(value):
                self.r.error(path, "must be a number, got %s" % describe(value))
            elif not low <= value <= high:
                self.r.warn(path, "%s is outside %s..%s; the builder clamps it" % (value, low, high))
            return
        if kind == "expr":
            if not is_str(value) or not value.strip():
                self.r.error(path, "must be an expression string, got %s" % describe(value))
            else:
                self.expression_refs(value, path)
        elif kind == "exprs":
            if is_str(value):
                self.check_kind(value, "expr", path)
            elif isinstance(value, list) and value:
                for k, item in enumerate(value):
                    self.check_kind(item, "expr", pjoin(path, k))
            else:
                self.r.error(path, "must be an expression string or a non-empty list of them, got %s" % describe(value))
        elif kind == "exprlist":
            if not isinstance(value, list):
                self.r.error(path, "must be a list of expression strings, got %s" % describe(value))
            else:
                for k, item in enumerate(value):
                    self.check_kind(item, "expr", pjoin(path, k))
        elif kind == "strlist":
            if not isinstance(value, list) or not all(is_str(x) and x for x in value):
                self.r.error(path, "must be a list of names, got %s" % describe(value))
        elif kind == "bool":
            if not is_bool(value):
                self.r.error(path, "must be true or false, got %s" % describe(value))
        elif kind == "number":
            if not is_num(value):
                self.r.error(path, "must be a number, got %s" % describe(value))
        elif kind == "posint":
            if not is_int(value) or value <= 0:
                self.r.error(path, "must be a positive whole number, got %s" % describe(value))
        elif kind == "dict":
            if not isinstance(value, dict):
                self.r.error(path, "must be an object, got %s" % describe(value))
        elif kind == "scale":
            self.v_scale(value, path)
        elif kind == "trellis":
            self.v_trellis(value, path)
        elif kind == "series":
            self.v_series(value, path)
        elif kind == "tablesort":
            self.v_table_sort(value, path)
        elif kind == "widths":
            self.v_widths(value, path, v)
        elif kind == "totals":
            if self.obj(value, path):
                self.check_keys(value, ("rows", "columns"), path)
                self.field(value, "rows", path, ["bool"])
                self.field(value, "columns", path, ["bool"])
        elif kind == "gtcolumns":
            self.v_gt_columns(value, path)
        elif kind == "kpis":
            self.v_kpis(value, path)
        elif kind == "layers":
            self.v_map_layers(value, path)
        elif kind == "markertype":
            if value not in MARKER_TYPES:
                self.r.error(path, "must be a marker shape (MarkerType member), got %s%s"
                             % (describe(value), did_you_mean(value, MARKER_TYPES)))
        elif kind == "extent":
            self.v_extent(value, path, v)
        elif kind == "modaxes":
            self.v_mod_axes(value, path)

    def v_scale(self, value, path):
        if not self.obj(value, path):
            return
        self.check_keys(value, [k for k, _ in SCALE_DEFAULTS], path)
        for k in ("min", "max"):
            x = value.get(k)
            if x is not None and not (is_num(x) or is_str(x)):
                self.r.error(pjoin(path, k), "must be a number, an expression string or null, got %s" % describe(x))
        if is_num(value.get("min")) and is_num(value.get("max")) and value["min"] >= value["max"]:
            self.r.error(path, "min must be smaller than max")
        for k in ("log", "gridlines", "individualScaling"):
            self.field(value, k, path, ["bool"])
        self.field(value, "title", path, ["str"])

    def v_trellis(self, value, path):
        if not self.obj(value, path):
            return
        self.check_keys(value, ("panelBy", "rowsBy", "columnsBy", "rows", "columns"), path)
        for k in ("panelBy", "rowsBy", "columnsBy"):
            if value.get(k) is not None:
                self.check_kind(value[k], "expr", pjoin(path, k))
        if value.get("panelBy") is not None and (value.get("rowsBy") is not None or value.get("columnsBy") is not None):
            self.r.error(path, "panelBy and rowsBy/columnsBy are exclusive")
        if all(value.get(k) is None for k in ("panelBy", "rowsBy", "columnsBy")):
            self.r.error(path, "needs panelBy, or rowsBy and/or columnsBy")
        for k in ("rows", "columns"):
            x = value.get(k)
            if x is not None and (not is_int(x) or x <= 0):
                self.r.error(pjoin(path, k), "must be a positive whole number, got %s" % describe(x))
            elif x is not None and value.get("panelBy") is None:
                self.r.warn(pjoin(path, k), "a fixed grid (rows, columns) applies to panelBy only; with rowsBy / "
                            "columnsBy the categories decide the grid and Spotfire ignores it")
        if value.get("panelBy") is not None and (value.get("rows") is None) != (value.get("columns") is None):
            self.r.warn(path, "a fixed grid needs both rows and columns: with only one of them Spotfire keeps its own "
                        "value for the other")

    def v_series(self, value, path):
        if not isinstance(value, list) or not value:
            self.r.error(path, "must be a non-empty list of {\"expression\", \"kind\"}, got %s" % describe(value))
            return
        for k, s in enumerate(value):
            sp = pjoin(path, k)
            if not self.obj(s, sp):
                continue
            self.check_keys(s, ("expression", "kind"), sp)
            ex = self.field(s, "expression", sp, ["str"], required=True)
            if ex:
                self.expression_refs(ex, pjoin(sp, "expression"))
            self.field(s, "kind", sp, ["str"], required=True, choices=("bar", "line"))

    def v_table_sort(self, value, path):
        if not isinstance(value, list):
            self.r.error(path, "must be a list of {\"column\", \"descending\"}, got %s" % describe(value))
            return
        for k, s in enumerate(value):
            sp = pjoin(path, k)
            if not self.obj(s, sp):
                continue
            self.check_keys(s, ("column", "descending"), sp)
            self.field(s, "column", sp, ["str"], required=True)
            self.field(s, "descending", sp, ["bool"])

    def v_widths(self, value, path, v):
        if not isinstance(value, dict):
            self.r.error(path, "must be an object of column name -> width in pixels, got %s" % describe(value))
            return
        for col, px in value.items():
            if not is_int(px) or px <= 0:
                self.r.error(pjoin(path, col), "must be a positive width in pixels, got %s" % describe(px))
        cols = v.get("columns") if isinstance(v, dict) else None
        if isinstance(cols, list):
            shown = set(c.strip()[1:-1] if c.strip().startswith("[") and c.strip().endswith("]") else c.strip()
                        for c in cols if is_str(c))
            for col in value:
                if col.strip("[]") not in shown:
                    self.r.error(pjoin(path, col), "a width is given for column '%s', which the table does not show (add "
                                 "it to 'columns')" % col)

    def v_gt_columns(self, value, path):
        if not isinstance(value, list):
            self.r.error(path, "must be a list of graphical-table columns, got %s" % describe(value))
            return
        known = ("kind", "title", "expression", "width", "x", "color", "individualScaling", "coloring", "rules",
                 "comparative", "comparativeColor", "ranges", "settings")
        per_kind = {"sparkline": ("x", "color", "individualScaling"), "calculatedValue": ("coloring", "rules"),
                    "icon": ("coloring", "rules"), "bulletGraph": ("comparative", "color", "comparativeColor", "ranges")}
        for k, col in enumerate(value):
            cp = pjoin(path, k)
            if not self.obj(col, cp):
                continue
            self.check_keys(col, known, cp)
            kind = self.field(col, "kind", cp, ["str"], required=True, choices=GT_KINDS)
            self.field(col, "title", cp, ["str"])
            ex = self.field(col, "expression", cp, ["str"], required=True)
            if ex:
                self.expression_refs(ex, pjoin(cp, "expression"))
            width = self.field(col, "width", cp, ["int"])
            if width is not None and width <= 0:
                self.r.error(pjoin(cp, "width"), "must be a positive width in pixels")
            if kind:
                for f in ("x", "color", "individualScaling", "coloring", "rules", "comparative", "comparativeColor",
                          "ranges"):
                    if col.get(f) is not None and f not in per_kind[kind]:
                        self.r.warn(pjoin(cp, f), "'%s' does not apply to %s columns" % (f, kind))
            for f in ("x", "comparative"):
                if col.get(f) is not None:
                    self.check_kind(col[f], "expr", pjoin(cp, f))
            self.color_field(col, "color", cp)
            self.color_field(col, "comparativeColor", cp)
            self.field(col, "individualScaling", cp, ["bool"])
            for n, rng in enumerate(self.field(col, "ranges", cp, ["list"]) or []):
                rp = pjoin(cp, "ranges", n)
                if not self.obj(rng, rp):
                    continue
                self.check_keys(rng, ("expression", "color", "label"), rp)
                rex = self.field(rng, "expression", rp, ["str"], required=True)
                if rex:
                    self.expression_refs(rex, pjoin(rp, "expression"))
                self.color_field(rng, "color", rp)
                self.field(rng, "label", rp, ["str"])
            coloring = col.get("coloring")
            if coloring is not None and self.obj(coloring, pjoin(cp, "coloring")):
                for key in coloring:
                    if key != "rules":
                        self.r.warn(pjoin(cp, "coloring", key), "only 'rules' apply to graphical-table columns; '%s' is "
                                    "ignored" % key)
                for n, rule in enumerate(self.field(coloring, "rules", pjoin(cp, "coloring"), ["list"]) or []):
                    self.v_rule(rule, pjoin(cp, "coloring", "rules", n), kind or "gt")
            for n, rule in enumerate(self.field(col, "rules", cp, ["list"]) or []):
                self.v_rule(rule, pjoin(cp, "rules", n), kind or "gt")
            if kind:
                self.add_settings(col.get("settings"), pjoin(cp, "settings"), [GT_COLUMN_CLASSES[kind]])

    def v_kpis(self, value, path):
        if not isinstance(value, list):
            self.r.error(path, "must be a list of KPIs, got %s" % describe(value))
            return
        for k, kpi in enumerate(value):
            kp = pjoin(path, k)
            if not self.obj(kpi, kp):
                continue
            self.check_keys(kpi, ("title", "value", "comparative", "time", "tileBy", "coloring", "settings",
                                  "format"), kp)
            self.add_settings(kpi.get("settings"), pjoin(kp, "settings"), [KPI_CLASS])
            self.field(kpi, "title", kp, ["str"])
            fmt = self.field(kpi, "format", kp, ["str"])     # number format (standard engine; references/spec-format.md)
            if fmt is not None:
                if not fmt.strip():
                    self.r.error(pjoin(kp, "format"), "must be a format name or a format string")
                else:
                    self.format_hint(fmt, pjoin(kp, "format"))
            val = self.field(kpi, "value", kp, ["str"], required=True)
            if val:
                self.expression_refs(val, pjoin(kp, "value"))
            for f in ("comparative", "time"):
                if kpi.get(f) is not None:
                    self.check_kind(kpi[f], "expr", pjoin(kp, f))
            if kpi.get("tileBy") is not None:
                self.check_kind(kpi["tileBy"], "exprs", pjoin(kp, "tileBy"))
            if kpi.get("coloring") is not None:
                self.v_coloring(kpi["coloring"], pjoin(kp, "coloring"), "kpi")

    def v_map_layers(self, value, path):
        if not isinstance(value, list):
            self.r.error(path, "must be a list of layers, got %s" % describe(value))
            return
        for k, layer in enumerate(value):
            lp = pjoin(path, k)
            if not self.obj(layer, lp):
                continue
            self.check_keys(layer, MAP_LAYER_KEYS, lp)
            kind = self.field(layer, "kind", lp, ["str"], required=True, choices=MAP_LAYER_KINDS)
            self.field(layer, "title", lp, ["str"])
            if kind == "tile":
                for f in ("table", "latitude", "longitude", "geometry", "colorBy", "sizeBy", "lineBy",
                          "coloring") + MAP_ENGINE_KEYS:
                    if layer.get(f) is not None:
                        self.r.warn(pjoin(lp, f), "'%s' does not apply to a tile layer" % f)
            elif kind:
                if layer.get("table") is not None:
                    t = self.field(layer, "table", lp, ["str"])
                    if t is not None:
                        self.ref_table(t, pjoin(lp, "table"))
                for f in ("latitude", "longitude", "geometry", "colorBy", "sizeBy", "lineBy"):
                    if layer.get(f) is not None:
                        self.check_kind(layer[f], "expr", pjoin(lp, f))
                if kind == "marker" and (layer.get("latitude") is None) != (layer.get("longitude") is None):
                    self.r.error(lp, "give both latitude and longitude, or neither (then geometry or the table's "
                                 "Latitude/Longitude columns are used)")
                if kind == "feature":
                    for f in ("latitude", "longitude", "sizeBy", "lineBy", "labelBy", "labels", "markerSize",
                              "shape", "shapeBy"):
                        if layer.get(f) is not None:
                            self.r.warn(pjoin(lp, f), "'%s' does not apply to a feature layer" % f)
                if layer.get("coloring") is not None:
                    self.v_coloring(layer["coloring"], pjoin(lp, "coloring"), "map")
                if layer.get("labelBy") is not None:
                    self.check_kind(layer["labelBy"], "expr", pjoin(lp, "labelBy"))
                if kind == "marker":
                    self.v_marker_aggregation(layer, lp)
                if layer.get("shapeBy") is not None:
                    self.check_kind(layer["shapeBy"], "exprs", pjoin(lp, "shapeBy"))
                if layer.get("labels") is not None:
                    self.check_kind(layer["labels"], "labels", pjoin(lp, "labels"))
                if layer.get("markerSize") is not None:
                    self.check_kind(layer["markerSize"], "markersize", pjoin(lp, "markerSize"))
                if layer.get("shape") is not None:
                    self.check_kind(layer["shape"], "markertype", pjoin(lp, "shape"))
                if layer.get("marking") is not None:
                    m = self.field(layer, "marking", lp, ["str"])
                    if m is not None and m not in self.marking_names:
                        self.r.error(pjoin(lp, "marking"), "unknown marking '%s'%s (null = cannot be marked)"
                                     % (m, did_you_mean(m, self.marking_names)))
                for n, m in enumerate(self.field(layer, "limitByMarkings", lp, ["list"]) or []):
                    if not is_str(m) or m not in self.marking_names:
                        self.r.error(pjoin(lp, "limitByMarkings", n), "unknown marking %s%s"
                                     % (describe(m), did_you_mean(m, self.marking_names)))
                self.field(layer, "emptyMarkingBehavior", lp, ["str"], choices=EMPTY_MARKING_BEHAVIORS)
                where = self.field(layer, "limitExpression", lp, ["str"])
                if where is not None:
                    self.expression_refs(where, pjoin(lp, "limitExpression"))
            if kind:
                viz, base = MAP_LAYER_CLASSES[kind]
                if viz is None:
                    self.add_settings(layer.get("settings"), pjoin(lp, "settings"), [base])
                else:
                    self.add_settings(layer.get("settings"), pjoin(lp, "settings"), [viz, base], mode="maps")

    def v_extent(self, value, path, v=None):
        """{west, south, east, north} in degrees (WGS84): the map's first view (AutoZoom off)."""
        if not self.obj(value, path):
            return
        self.check_keys(value, ("west", "south", "east", "north"), path)
        nums = {}
        for key, low, high in (("west", -180, 180), ("east", -180, 180), ("south", -85, 85), ("north", -85, 85)):
            val = value.get(key)
            if not is_num(val):
                self.r.error(pjoin(path, key), "must be a number of degrees, got %s" % describe(val))
            elif not low <= val <= high:
                self.r.error(pjoin(path, key), "must be within %s..%s degrees, got %s" % (low, high, val))
            else:
                nums[key] = val
        if len(nums) == 4 and (nums["west"] >= nums["east"] or nums["south"] >= nums["north"]):
            self.r.error(path, "west must be less than east and south less than north")
        if isinstance(v, dict) and v.get("autoZoom") is True:
            self.r.warn(path, "an extent switches AutoZoom off; autoZoom true is ignored")

    def v_mod_axes(self, value, path):
        """axes of a mod view (main view or layer): {name: expression | [expressions] | "" | null}; an unknown
        ${Name} is an error (the mod view cannot be evaluated). The manifest checks: v_mod_view."""
        if not isinstance(value, dict):
            self.r.error(path, "must be an object of axis name -> expression, got %s" % describe(value))
            return
        for name, ex in value.items():
            ap = pjoin(path, name)
            if ex is None:
                continue
            if is_str(ex):
                self.expression_refs(ex, ap, strict="axis '%s'" % name)
            elif isinstance(ex, list) and ex and all(is_str(x) for x in ex):
                for x in ex:
                    self.expression_refs(x, ap, strict="axis '%s'" % name)
            else:
                self.r.error(ap, "must be an expression string, a list of expressions or null, got %s" % describe(ex))

    # ---- visualization mods (references/spec-format.md "Visualization mods") ---------------------------
    def v_viz_mods(self):
        """vizMods: [{id, project}] - the visualization mods of the standard engine's mod visuals. The project
        folder's mod-manifest.json is required: it types the axes and properties of the mod visuals and their
        layers, and the builder loads the mod from that folder (unless it is embedded or pinned already)."""
        used = set()
        for pg in as_list(self.spec.get("pages")):
            for v in as_list(pg.get("visuals")) if isinstance(pg, dict) else []:
                if isinstance(v, dict) and v.get("type") == "mod" and is_str(v.get("modId")):
                    used.add(v["modId"])
        for i, m in enumerate(self.section("vizMods")):
            path = pjoin("vizMods", i)
            if not self.obj(m, path):
                continue
            self.check_keys(m, ("id", "project"), path)
            mod_id = self.field(m, "id", path, ["str"], required=True)
            if mod_id is not None and not mod_id.strip():
                self.r.error(pjoin(path, "id"), "must not be empty")
                continue
            if not mod_id:
                continue
            if mod_id in self.viz_mods:
                self.r.error(pjoin(path, "id"), "visualization mod '%s' is listed twice" % mod_id)
                continue
            if mod_id in self.action_mods:
                self.r.error(pjoin(path, "id"), "'%s' is listed in actionMods too; a mod id names one mod (visualization "
                             "mods go in vizMods, action mods in actionMods)" % mod_id)
            self.viz_mods[mod_id] = None
            if mod_id not in used:
                self.r.warn(path, "visualization mod '%s' is listed but no mod visual uses it; the builder leaves it "
                            "out" % mod_id)
            manifest = self.v_viz_manifest(m, path, mod_id)
            if manifest is None:
                continue
            self.viz_mods[mod_id] = manifest
            types = t3mod.layer_types(manifest)
            self.r.note("visualization mod '%s' %s (API %s): %d layer type(s) (%s), %d mod properties"
                        % (mod_id, manifest.get("version") or "(no version)", manifest.get("apiVersion") or "?",
                           len(types), ", ".join(types) or "none", len(t3mod.manifest_props(manifest))))

    def v_viz_manifest(self, m, path, mod_id):
        """The parsed mod-manifest.json of a vizMods entry's project folder, or None (error recorded)."""
        pp = pjoin(path, "project")
        project = m.get("project")
        if project is None:
            self.r.error(pp, "missing required field 'project': the standard engine reads the mod's "
                         "mod-manifest.json (layer types, axes, property types) and loads the mod from that folder")
            return None
        if not is_str(project) or not project.strip():
            self.r.error(pp, "must be the mod project folder (relative to the app), got %s" % describe(project))
            return None
        folder = self.app_dir / project.strip()
        if not folder.is_dir():
            self.r.error(pp, "folder not found: %s" % folder)
            return None
        mpath = folder / "mod-manifest.json"
        if not mpath.is_file():
            self.r.error(pp, "no mod-manifest.json in %s (the mod project folder: the manifest with the built files "
                         "next to it)" % folder)
            return None
        text = self.file_text(mpath, pp)
        if text is None:
            return None
        try:
            manifest = json.loads(text)
        except ValueError as e:
            self.r.error(pp, "%s is not valid JSON: %s" % (mpath, e))
            return None
        if not isinstance(manifest, dict):
            self.r.error(pp, "%s must hold a JSON object" % mpath)
            return None
        if manifest.get("id") != mod_id:
            self.r.error(pjoin(path, "id"), "the manifest's id is %s, not '%s'" % (describe(manifest.get("id")), mod_id))
        if manifest.get("type", "visualization") != "visualization":
            self.r.error(pp, "the manifest's type is %s, not \"visualization\" (action mods go in actionMods)"
                         % describe(manifest.get("type")))
        listed = [f.strip() for f in as_list(manifest.get("files")) if is_str(f) and f.strip()]
        if not listed:
            self.r.warn(pp, "the manifest lists no 'files'; Spotfire embeds only the files it lists")
        missing = [f for f in listed if not (folder / f).is_file()]
        if missing:
            self.r.error(pp, "mod-manifest.json lists %d file(s) that are not in %s: %s; build the mod first (Spotfire "
                         "refuses a project folder with missing files and the visual becomes a placeholder)"
                         % (len(missing), folder, ", ".join(missing)))
        icon = manifest.get("icon")
        if is_str(icon) and icon.strip() and not (folder / icon.strip()).is_file():
            self.r.warn(pp, "the manifest's icon %s is not in %s" % (icon.strip(), folder))
        return manifest

    def v_mod_visual(self, v, path):
        """A mod visual against its mod's manifest (vizMods): main view axes and properties, layers (type,
        title, table, marking, limits, axes, properties); an unknown ${...} in a mod view is an error."""
        mod_id = v.get("modId")
        man = None
        if is_str(mod_id) and mod_id.strip():
            if mod_id in self.viz_mods:
                man = self.viz_mods[mod_id]
            elif self.viz_mods:
                self.r.error(pjoin(path, "modId"), "unknown visualization mod '%s'%s (list it in vizMods)"
                             % (mod_id, did_you_mean(mod_id, list(self.viz_mods))))
            else:
                self.r.warn(pjoin(path, "modId"), "mod '%s' is not listed in vizMods: the standard engine builds mod "
                            "visuals only from vizMods (dxpgen build stops with 'use --tier slim'); the slim tier "
                            "looks for the mod in Analyst" % mod_id)
        if man is not None:
            self.v_mod_view(v, path, man, None, mod_id, "the main view")
        layers = v.get("layers")
        if layers is None:
            return
        lsp = pjoin(path, "layers")
        if not isinstance(layers, list):
            self.r.error(lsp, "must be a list of layers, got %s" % describe(layers))
            return
        if layers and man is not None and not t3mod.layer_types(man):
            self.r.error(lsp, "mod '%s' declares no layer types (manifest 'layers'), so it takes no layers" % mod_id)
            man = None
        titles = {}
        for k, layer in enumerate(layers):
            lp = pjoin(lsp, k)
            if not self.obj(layer, lp, "a layer object"):
                continue
            self.check_keys(layer, t3mod.LAYER_KEYS, lp)
            ltype = self.field(layer, "type", lp, ["str"], required=True)
            known = ltype is not None and man is not None
            if known and t3mod.layer_def(man, ltype) is None:
                types = t3mod.layer_types(man)
                self.r.error(pjoin(lp, "type"), "mod '%s' has no layer type '%s'%s (its layer types: %s)"
                             % (mod_id, ltype, did_you_mean(ltype, types), ", ".join(types)))
                known = False
            title = self.field(layer, "title", lp, ["str"])
            shown = title or ltype
            if title:
                self.expression_refs(title, pjoin(lp, "title"))
            if is_str(shown) and shown:
                if shown in titles:
                    self.r.error(pjoin(lp, "title"), "layer title '%s' is used twice in this visual (also layers[%d]); "
                                 "titles identify the layers for the mod and verify_dxp" % (shown, titles[shown]))
                else:
                    titles[shown] = k
            if layer.get("table") is not None:
                t = self.field(layer, "table", lp, ["str"])
                if t is not None:
                    self.ref_table(t, pjoin(lp, "table"))
            if layer.get("marking") is not None:
                mk = self.field(layer, "marking", lp, ["str"])
                if mk is not None and mk not in self.marking_names:
                    self.r.error(pjoin(lp, "marking"), "unknown marking '%s'%s (null = cannot be marked)"
                                 % (mk, did_you_mean(mk, self.marking_names)))
            for n, mk in enumerate(self.field(layer, "limitByMarkings", lp, ["list"]) or []):
                if not is_str(mk) or mk not in self.marking_names:
                    self.r.error(pjoin(lp, "limitByMarkings", n), "unknown marking %s%s"
                                 % (describe(mk), did_you_mean(mk, self.marking_names)))
            self.field(layer, "emptyMarkingBehavior", lp, ["str"], choices=EMPTY_MARKING_BEHAVIORS)
            self.field(layer, "useFiltering", lp, ["bool"])
            where = self.field(layer, "limitExpression", lp, ["str"])
            if where is not None:
                self.expression_refs(where, pjoin(lp, "limitExpression"), strict="layer's limiting expression")
            if layer.get("axes") is not None:
                self.v_mod_axes(layer["axes"], pjoin(lp, "axes"))
            if layer.get("properties") is not None and not isinstance(layer["properties"], dict):
                self.r.error(pjoin(lp, "properties"), "must be an object of property name -> value, got %s"
                             % describe(layer["properties"]))
            if known:
                self.v_mod_view(layer, lp, man, ltype, mod_id, "layer '%s'" % shown)

    def v_mod_view(self, s, path, man, layer_type, mod_id, label):
        """Axis names, axis value shapes, required axes and typed properties of one mod view (the main view:
        layer_type None) against the manifest."""
        defs = t3mod.manifest_axes(man, layer_type)
        axes = s.get("axes") if isinstance(s.get("axes"), dict) else {}
        for name, value in axes.items():
            ap = pjoin(path, "axes", name)
            if name not in defs:
                names = ", ".join(defs) or "none"
                if layer_type is None:
                    self.r.error(ap, "mod '%s' has no axis '%s' on its main view%s (main view axes: %s)"
                                 % (mod_id, name, did_you_mean(name, list(defs)), names))
                else:
                    self.r.error(ap, "layer type '%s' of mod '%s' has no axis '%s'%s (its axes: %s)"
                                 % (layer_type, mod_id, name, did_you_mean(name, list(defs)), names))
                continue
            self.v_mod_axis_value(value, ap, name, defs[name])
        for name in t3mod.required_unset(man, layer_type, axes):
            self.r.warn(pjoin(path, "axes") if "axes" in s else path, "required axis '%s' of %s gets no expression and "
                        "the manifest configures none; the view stays invalid until it is set" % (name, label))
        props = s.get("properties") if isinstance(s.get("properties"), dict) else {}
        types = t3mod.manifest_props(man, layer_type)
        for name, value in props.items():
            pp = pjoin(path, "properties", name)
            if name not in types:
                names = ", ".join(types) or "none"
                if layer_type is None:
                    self.r.error(pp, "mod '%s' has no property '%s'%s (its properties: %s)"
                                 % (mod_id, name, did_you_mean(name, list(types)), names))
                else:
                    self.r.error(pp, "layer type '%s' of mod '%s' has no property '%s'%s (its properties: %s)"
                                 % (layer_type, mod_id, name, did_you_mean(name, list(types)), names))
                continue
            try:
                t3mod.prop_value(value, types[name], name)
            except ValueError as e:
                self.r.error(pp, str(e))

    # a bare column name on a categorical axis: no brackets, parentheses or angle brackets ("Line-Up")
    _MOD_PLAIN_RE = re.compile(r"^[^\[\]()<>]+$")

    def v_mod_axis_value(self, value, path, name, defn):
        """The shape of one axis value for the manifest's axis mode (t3/mod.py axis_text builds it)."""
        if value is None or value == "" or not (is_str(value) or isinstance(value, list)):
            return
        mode = t3mod.axis_mode(defn)
        items = [x.strip() for x in (value if isinstance(value, list) else [value]) if is_str(x) and x.strip()]
        if isinstance(value, list) and mode != "categorical" and len(items) > 1 \
                and defn.get("allowMultipleMeasures") is not True:
            self.r.error(path, "axis '%s' takes one expression (its manifest entry has no allowMultipleMeasures); "
                         "give one string" % name)
        if mode == "continuous" and any(x.startswith("<") for x in items):
            self.r.error(path, "'%s' is a continuous axis: give an expression or a column name, not <...>" % name)
        if mode == "categorical" and is_str(value):
            text = value.strip()
            column = (t3._common.IDENT_RE.match(text) or t3._common.PLAIN_NAME_RE.match(text)
                      or self._MOD_PLAIN_RE.match(text))
            if not text.startswith("<") and not column:
                self.r.error(path, "'%s' is a categorical axis: give <...>, a column name or a list of levels, got %s"
                             % (name, describe(value)))

    # ---- coloring, reference layers, fitting models ----------------------------------------------
    def v_coloring(self, c, path, ctx):
        if isinstance(c, list):
            if ctx not in ("table", "crossTable"):
                self.r.error(path, "must be one coloring object (a list is accepted on table and crossTable visuals)")
                return
            for k, item in enumerate(c):
                self.v_coloring_one(item, pjoin(path, k), ctx)
            return
        self.v_coloring_one(c, path, ctx)

    def v_coloring_one(self, c, path, ctx):
        if not self.obj(c, path, "a coloring object"):
            return
        keys = ["categorical", "gradient", "fixed", "rules", "default", "settings"]
        if ctx == "table":
            keys.append("columns")
        if ctx == "crossTable":
            keys.append("measures")
        self.check_keys(c, keys, path)
        if ctx == "summaryTable":
            self.r.warn(path, "summary tables have no coloring; the builder ignores it")
        elif ctx == "mod":
            self.r.warn(path, "coloring is not applied to mods (it becomes a manual step); color through the mod's "
                        "Color axis (the standard engine stops: use --tier slim, or color through the mod's "
                        "properties)")
        elif ctx == "graphicalTable":
            self.r.warn(path, "graphical tables color per column (columns[].coloring.rules); the visual-level coloring "
                        "is ignored")
        backgrounds = [k for k in ("categorical", "gradient", "fixed") if c.get(k) is not None]
        if len(backgrounds) > 1:
            self.r.error(path, "%s are exclusive: give one background" % " and ".join(backgrounds))
        if not any(c.get(k) is not None for k in ("categorical", "gradient", "fixed", "rules", "default", "settings")):
            self.r.error(path, "needs one of categorical, gradient, fixed, rules or default")
        for key, col in (self.field(c, "categorical", path, ["dict"]) or {}).items():
            if not (is_str(col) and COLOR_RE.match(col)):
                self.r.error(pjoin(path, "categorical", key), "must be a color '#RRGGBB' or '#AARRGGBB', got %s" % describe(col))
        gradient = self.field(c, "gradient", path, ["list"])
        if gradient is not None:
            if len(gradient) < 2:
                self.r.warn(pjoin(path, "gradient"), "a gradient needs at least two points (for example min and max)")
            for k, point in enumerate(gradient):
                gp = pjoin(path, "gradient", k)
                if not self.obj(point, gp):
                    continue
                self.check_keys(point, ("at", "color"), gp)
                at = point.get("at")
                if at is None or isinstance(at, (bool, list, dict)):
                    self.r.error(pjoin(gp, "at"), "must be min, max, median, average, 'NN%%' or a number, got %s" % describe(at))
                elif is_str(at):
                    self.expression_refs(at, pjoin(gp, "at"))
                self.color_field(point, "color", gp, required=True)
        self.color_field(c, "fixed", path)
        self.color_field(c, "default", path)
        for k, rule in enumerate(self.field(c, "rules", path, ["list"]) or []):
            self.v_rule(rule, pjoin(path, "rules", k), ctx)
        self.add_settings(c.get("settings"), pjoin(path, "settings"), [COLORING_CLASS])
        if ctx == "table":
            cols = self.field(c, "columns", path, ["list"], required=True)
            if cols is not None:
                if not cols:
                    self.r.error(pjoin(path, "columns"), "must name at least one table column")
                for k, col in enumerate(cols):
                    if not is_str(col) or not col:
                        self.r.error(pjoin(path, "columns", k), "must be a column name, got %s" % describe(col))
        elif ctx == "crossTable":
            for k, m in enumerate(self.field(c, "measures", path, ["list"]) or []):
                if not is_str(m) or not m:
                    self.r.error(pjoin(path, "measures", k), "must be a measure name or expression, got %s" % describe(m))

    def v_rule(self, rule, path, ctx):
        if not self.obj(rule, path, "a rule object"):
            return
        self.check_keys(rule, ("type", "value", "low", "high", "count", "expression", "color", "settings", "shape"), path)
        rtype = self.field(rule, "type", path, ["str"], required=True, choices=tuple(RULE_FIELDS))
        self.color_field(rule, "color", path, required=True)
        if rtype:
            for f in RULE_FIELDS[rtype]:
                val = rule.get(f)
                if val is None:
                    self.r.error(path, "rule '%s' needs '%s'" % (rtype, f))
                elif f == "count":
                    if not is_int(val) or val <= 0:
                        self.r.error(pjoin(path, f), "must be a positive whole number, got %s" % describe(val))
                elif f == "expression":
                    if not is_str(val) or not val.strip():
                        self.r.error(pjoin(path, f), "must be a Boolean expression string, got %s" % describe(val))
                    else:
                        self.expression_refs(val, pjoin(path, f))
                elif isinstance(val, (list, dict)):
                    self.r.error(pjoin(path, f), "must be a number, a keyword (min, max, median, average, 'NN%%') or an "
                                 "expression, got %s" % describe(val))
                elif is_str(val):
                    self.expression_refs(val, pjoin(path, f))
        if rule.get("shape") is not None and ctx != "icon":
            self.r.warn(pjoin(path, "shape"), "'shape' only applies to icon columns of graphical tables")
        if ctx in GT_RULE_CLASSES:
            self.add_settings(rule.get("settings"), pjoin(path, "settings"), [GT_RULE_CLASSES[ctx]])
        elif ctx in GT_KINDS or ctx == "gt":
            if rule.get("settings") is not None:
                self.r.warn(pjoin(path, "settings"), "%s columns have no rules; these settings are not applied" % ctx)
        elif rtype:
            self.add_settings(rule.get("settings"), pjoin(path, "settings"), RULE_CLASSES[rtype], mode="any")

    def v_reference_layer(self, layer, path):
        if not self.obj(layer, path):
            return
        self.check_keys(layer, ("kind", "value", "low", "high", "color", "dash", "width", "label", "table", "settings",
                                "labelFont"), path)
        font = self.field(layer, "labelFont", path, ["num"])     # standard engine style key (references/spec-format.md)
        if font is not None and font <= 0:
            self.r.error(pjoin(path, "labelFont"), "must be a positive font size in points")
        kind = self.field(layer, "kind", path, ["str"], required=True, choices=REFERENCE_LAYER_KINDS)
        if kind == "band":
            for f in ("low", "high"):
                if layer.get(f) is None:
                    self.r.error(path, "a band needs '%s'" % f)
            if layer.get("value") is not None:
                self.r.warn(pjoin(path, "value"), "a band uses low and high; 'value' is ignored")
        elif kind and layer.get("value") is None:
            self.r.error(path, "a %s needs 'value'" % kind)
        for f in ("value", "low", "high"):
            val = layer.get(f)
            if val is None:
                continue
            if is_str(val):
                self.expression_refs(val, pjoin(path, f))
            else:
                self.r.error(pjoin(path, f), "must be an expression string (constants too, e.g. \"100\"), got %s" % describe(val))
        self.color_field(layer, "color", path)
        self.field(layer, "dash", path, ["str"], choices=DASHES)
        width = self.field(layer, "width", path, ["num"])
        if width is not None and not 1 <= width <= 10:
            self.r.warn(pjoin(path, "width"), "is clamped to 1..10")
        self.field(layer, "label", path, ["str"])
        if layer.get("table") is not None:
            t = self.field(layer, "table", path, ["str"])
            if t is not None:
                self.ref_table(t, pjoin(path, "table"))
                if newer_than("15.0", self.min_version):
                    self.r.warn(pjoin(path, "table"), "a reference layer on another table needs Spotfire 15.0 "
                                "(ReferenceLayer.Data [api 15.0]); minimumSpotfireVersion is %s" % self.min_version)
        self.add_settings(layer.get("settings"), pjoin(path, "settings"), [REFERENCE_LAYER_CLASS])

    def v_fitting_model(self, model, path):
        if not self.obj(model, path):
            return
        self.check_keys(model, ("kind", "expression", "color", "label", "settings", "dash", "width"), path)
        self.field(model, "dash", path, ["str"], choices=DASHES)        # standard engine (references/spec-format.md)
        width = self.field(model, "width", path, ["num"])
        if width is not None and not 1 <= width <= 10:
            self.r.error(pjoin(path, "width"), "must be 1..10 pixels, got %s" % width)
        kind = self.field(model, "kind", path, ["str"], required=True, choices=FITTING_KINDS)
        if kind == "curve":
            ex = self.field(model, "expression", path, ["str"], required=True)
            if ex:
                self.expression_refs(ex, pjoin(path, "expression"))
        elif kind == "straightLine" and model.get("expression") is not None:
            self.r.warn(pjoin(path, "expression"), "a straightLine has no expression; it is ignored")
        self.color_field(model, "color", path)
        self.field(model, "label", path, ["str"])
        if kind:
            self.add_settings(model.get("settings"), pjoin(path, "settings"), [FITTING_CLASSES[kind]])

    # ---- text areas and controls ------------------------------------------------------------------
    def v_textarea(self, v, path, vid, order):
        html_text = None
        hp = pjoin(path, "html")
        h = v.get("html")
        if h is None:
            self.r.warn(path, "a text area without 'html' is empty")
        elif not is_str(h):
            self.r.error(hp, "must be HTML starting with '<' or a path to an .html file, got %s" % describe(h))
        elif h.lstrip().startswith("<"):
            html_text = h
        elif not h.strip():
            self.r.warn(hp, "is empty")
        else:
            full = self.file_path(h.strip(), hp, "HTML file (inline HTML must start with '<')", (".html", ".htm"))
            if full is not None:
                html_text = self.file_text(full, hp)
        css_text = ""
        c = v.get("css")
        cp = pjoin(path, "css")
        if c is not None:
            if not is_str(c):
                self.r.error(cp, "must be CSS text or a path to a .css file, got %s" % describe(c))
            elif c.strip() and "{" not in c:
                full = self.file_path(c.strip(), cp, "CSS file", (".css",))
                if full is not None:
                    css_text = self.file_text(full, cp) or ""
            else:
                css_text = c
        js = v.get("js")
        jsp = pjoin(path, "js")
        if js is not None:
            if not isinstance(js, list):
                self.r.error(jsp, "must be a list of .js file paths, got %s" % describe(js))
            else:
                stems = {}
                for k, item in enumerate(js):
                    ip = pjoin(jsp, k)
                    if is_str(item):
                        full = self.file_path(item, ip, "JavaScript file", (".js",))
                        if full is not None:
                            text = self.file_text(full, ip)
                            if text is not None and not text.strip():
                                self.r.warn(ip, "the JavaScript file is empty")
                        stem = Path(item).stem
                    elif isinstance(item, dict) and is_str(item.get("name")) and is_str(item.get("code")):
                        self.check_keys(item, ("name", "code"), ip)
                        stem = item["name"]
                        if not item["code"].strip():
                            self.r.warn(pjoin(ip, "code"), "the JavaScript is empty")
                    else:
                        self.r.error(ip, "must be a path to a .js file, got %s" % describe(item))
                        continue
                    # ScriptDefinition names (lib/40_scripts.py _scripts_check_name)
                    bad = sorted(set(ch for ch in stem if ch in BAD_SCRIPT_NAME_CHARS or ord(ch) < 32))
                    if not stem.strip():
                        self.r.error(ip, "the JavaScript script name (the file stem) must not be empty")
                        continue
                    if bad:
                        self.r.error(ip, "the JavaScript script name '%s' cannot contain %s"
                                     % (stem, " ".join(repr(b) for b in bad)))
                    self.naming("jsScript", stem, ip)
                    if stem in stems:
                        self.r.error(ip, "two JavaScript files are named '%s' (also %s); the script name is the file "
                                     "stem" % (stem, stems[stem]))
                    stems.setdefault(stem, ip)
                    if stem in self.scripts:
                        self.r.error(ip, "JavaScript '%s' has the name of an IronPython script; the analysis keeps "
                                     "one script per name" % stem)
                    code = item.get("code") if isinstance(item, dict) else (
                        self.texts.get(str(self.app_dir / item)) if is_str(item) else None)
                    first = self.js_names.get(stem)
                    if first is None:
                        self.js_names[stem] = (ip, code)
                    elif first[1] != code:
                        self.r.error(ip, "JavaScript '%s' differs from the one of the same name at %s; the "
                                     "analysis registers each name once" % (stem, first[0]))
        controls = v.get("controls")
        ctp = pjoin(path, "controls")
        if controls is None:
            controls = {}
        elif not isinstance(controls, dict):
            self.r.error(ctp, "must be an object of control id -> control, got %s" % describe(controls))
            controls = {}
        counts = {}
        if html_text is not None:
            for m in PLACEHOLDER_RE.finditer(html_text):
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
            for cid in counts:
                if cid not in controls:
                    self.r.error(hp, "placeholder {{control:%s}} has no entry in 'controls'%s"
                                 % (cid, did_you_mean(cid, list(controls))))
            if "<spotfirecontrol" in html_text.lower():
                self.r.warn(hp, "contains literal <SpotfireControl> tokens; they do not refer to controls this build "
                            "creates - use {{control:id}} placeholders")
            if _LIVE_PROP_RE.search(html_text):
                self.r.warn(hp, "${...} is not substituted in text-area HTML; show property values with label controls")
        for cid, cspec in controls.items():
            cpath = pjoin(ctp, cid)
            if not re.match(r"^[^{}\s]+$", cid):
                self.r.error(cpath, "control ids cannot contain spaces or braces")
            if html_text is not None:
                n = counts.get(cid, 0)
                if n == 0:
                    self.r.error(cpath, "control '%s' is not placed: put {{control:%s}} in the HTML" % (cid, cid))
                elif n > 1:
                    self.r.error(cpath, "control '%s' is placed %d times; every control must be placed exactly once"
                                 % (cid, n))
            self.v_control(cid, cspec, cpath, order)
        if html_text is not None and self.html_mode == "safe" and self.opts.sanitize:
            composed, tokens = compose_textarea_html(html_text, css_text, True, vid)
            self.html_jobs.append({"path": hp, "label": "text area '%s'" % vid, "html": composed, "tokens": tokens,
                                   "static": emulate_sanitizer(composed), "tool": None})

    def v_control(self, cid, c, path, order):
        if not self.obj(c, path, "a control object"):
            return
        kind = self.field(c, "kind", path, ["str"], required=True, choices=CONTROL_KINDS)
        if kind is None:
            return
        if kind in ("button", "link"):
            self.v_action_control(cid, c, path, order, kind)
            return
        keys = ["kind", "property", "values"] + (["min", "max", "step", "showLabels"] if kind == "slider" else [])
        self.check_keys(c, keys, path)
        pname = None
        if c.get("property") is None:
            self.r.error(path, "a %s control needs 'property'" % kind)
        else:
            pname = self.ref_property(c.get("property"), pjoin(path, "property"))
        pspec = self.prop_specs.get(pname) if pname else None
        ptype = pspec.get("type") if pspec else None
        plist = bool(pspec.get("listValued")) if pspec else False
        pp = pjoin(path, "property")
        if pspec is not None:
            if kind == "multiSelectListbox" and not plist:
                self.r.error(pp, "a multiSelectListbox needs a list-valued property; set listValued: true on '%s'" % pname)
            elif kind not in ("multiSelectListbox", "label", "input", "multilineInput") and plist:
                self.r.warn(pp, "'%s' is list-valued but a %s sets one value (use multiSelectListbox)" % (pname, kind))
            if kind == "checkbox" and ptype != "Boolean":
                self.r.error(pp, "a checkbox needs a Boolean property; '%s' is %s" % (pname, ptype))
            if kind == "slider" and ptype not in NUMERIC_TYPES:
                self.r.error(pp, "a slider needs a numeric property; '%s' is %s" % (pname, ptype))
        if kind == "slider":
            low = self.field(c, "min", path, ["num"], required=True)
            high = self.field(c, "max", path, ["num"], required=True)
            step = self.field(c, "step", path, ["num"])
            if self.field(c, "showLabels", path, ["bool"]) is False:
                # lib/80_textareas.py _textareas_range_provider always sets ShowLabels = True
                self.r.warn(pjoin(path, "showLabels"), "is not applied: the builder always shows the slider's range "
                            "labels (switch them off in Analyst if needed)")
            if step is not None and step <= 0:
                self.r.error(pjoin(path, "step"), "must be greater than 0")
            if low is not None and high is not None:
                if high <= low:
                    self.r.error(path, "min must be smaller than max")
                else:
                    positions = int((high - low) / (step if step and step > 0 else 1) + 1e-9) + 1
                    if positions > 1000:
                        self.r.error(path, "the slider has %d positions; Spotfire lists at most 1000 values - use a "
                                     "larger step" % positions)
        if kind in VALUE_SOURCE_KINDS:
            values = self.field(c, "values", path, ["dict"], required=True)
            if values is not None:
                self.v_value_source(values, pjoin(path, "values"), ptype)
        elif c.get("values") is not None:
            self.r.warn(pjoin(path, "values"), "'values' is ignored for kind '%s'%s"
                        % (kind, " (a checkbox is a Yes/No drop-down)" if kind == "checkbox" else ""))

    def v_value_source(self, values, path, ptype):
        self.check_keys(values, ("fixed", "column"), path)
        given = [k for k in ("fixed", "column") if values.get(k) is not None]
        if len(given) != 1:
            self.r.error(path, "needs exactly one of 'fixed' or 'column'")
        fixed = values.get("fixed")
        if fixed is not None:
            fp = pjoin(path, "fixed")
            if not isinstance(fixed, list) or not fixed:
                self.r.error(fp, "must be a non-empty list of {\"text\", \"value\"}, got %s" % describe(fixed))
            else:
                seen = set()
                for k, item in enumerate(fixed):
                    ip = pjoin(fp, k)
                    if not self.obj(item, ip):
                        continue
                    self.check_keys(item, ("text", "value"), ip)
                    if "value" not in item and "text" not in item:
                        self.r.error(ip, "needs 'value' (and usually 'text')")
                        continue
                    text = item.get("text")
                    if text is not None and not is_str(text):
                        self.r.error(pjoin(ip, "text"), "must be a string, got %s" % describe(text))
                    value = item.get("value", text)
                    if ptype is not None and value is not None:
                        problem = typed_value_problem(value, ptype, strict=False)
                        if problem:
                            self.r.error(pjoin(ip, "value"), problem)
                    key = json.dumps(value, sort_keys=True)
                    if key in seen:
                        self.r.warn(ip, "value %s is listed twice" % key)
                    seen.add(key)
        col = values.get("column")
        if col is not None:
            cp = pjoin(path, "column")
            if self.obj(col, cp):
                self.check_keys(col, ("table", "column"), cp)
                t = self.field(col, "table", cp, ["str"], required=True)
                if t is not None:
                    self.ref_table(t, pjoin(cp, "table"))
                self.field(col, "column", cp, ["str"], required=True)

    def v_action_control(self, cid, c, path, order, kind):
        self.check_keys(c, ("kind", "label", "script", "args", "action", "actionMod"), path)
        if c.get("actionMod") is not None:
            self.v_action_mod_ref(c["actionMod"], pjoin(path, "actionMod"), order)
            if c.get("script") is None and c.get("action") is None:
                self.r.warn(path, "actionMod without 'script' or 'action': the %s does nothing until you wire it "
                            "to the action mod by hand (MANUAL-STEPS)" % kind)
                return
        label = c.get("label")
        if label is None:
            self.r.warn(path, "no label: the %s shows its id '%s'" % (kind, cid))
        elif not is_str(label) or not label.strip():
            self.r.error(pjoin(path, "label"), "must be a non-empty string, got %s" % describe(label))
        script, action = c.get("script"), c.get("action")
        if script is not None:
            name = self.field(c, "script", path, ["str"])
            if name is not None:
                sspec = self.scripts.get(name)
                if sspec is None:
                    self.r.error(pjoin(path, "script"), "unknown script '%s'%s" % (name, did_you_mean(name, list(self.scripts))))
                else:
                    self.v_script_args(c.get("args"), sspec, pjoin(path, "args"), order, name)
            if action is not None:
                self.r.warn(pjoin(path, "action"), "both 'script' and 'action' are given; the script is used")
        elif action is not None:
            a = self.field(c, "action", path, ["dict"])
            if a is not None:
                ap = pjoin(path, "action")
                for k in a:
                    if k not in ACTION_KEYS:
                        self.r.warn(pjoin(ap, k), "unknown action '%s'%s; the builder ignores it" % (k, did_you_mean(k, ACTION_KEYS)))
                given = [k for k in ACTION_KEYS if k in a]
                if len(given) != 1:
                    self.r.error(ap, "needs exactly one of gotoPage, applyBookmark, refreshDataFunction")
                if "gotoPage" in a and (not is_str(a["gotoPage"]) or a["gotoPage"] not in self.page_titles):
                    self.r.error(pjoin(ap, "gotoPage"), "unknown page %s%s" % (describe(a["gotoPage"]),
                                 did_you_mean(a["gotoPage"], list(self.page_titles))))
                if "applyBookmark" in a:
                    b = a["applyBookmark"]
                    if not is_str(b) or not b:
                        self.r.error(pjoin(ap, "applyBookmark"), "must be a bookmark name, got %s" % describe(b))
                    else:
                        self.r.warn(pjoin(ap, "applyBookmark"), "bookmark '%s' must already exist in the analysis (the spec "
                                    "cannot create bookmarks); otherwise this control becomes a manual step" % b)
                if "refreshDataFunction" in a and (not is_str(a["refreshDataFunction"])
                                                   or a["refreshDataFunction"] not in self.dfs):
                    self.r.error(pjoin(ap, "refreshDataFunction"), "unknown data function %s%s"
                                 % (describe(a["refreshDataFunction"]), did_you_mean(a["refreshDataFunction"], list(self.dfs))))
            if c.get("args"):
                self.r.warn(pjoin(path, "args"), "args are only used with 'script'")
        else:
            self.r.error(path, "a %s needs 'script' or 'action' (gotoPage, applyBookmark, refreshDataFunction)" % kind)

    def v_script_args(self, args, sspec, path, order, script_name):
        params = {}
        for p in as_list(sspec.get("parameters")):
            if isinstance(p, dict) and is_str(p.get("name")):
                params[p["name"]] = p.get("type") or "String"
        if args is None:
            args = {}
        if not isinstance(args, dict):
            self.r.error(path, "must be an object of script parameter -> value, got %s" % describe(args))
            return
        for name in params:
            if name not in args:
                self.r.warn(path, "script '%s' parameter '%s' gets no value (add it to args)" % (script_name, name))
        for name, value in args.items():
            ap = pjoin(path, name)
            if name not in params:
                self.r.error(ap, "script '%s' has no parameter '%s'%s" % (script_name, name, did_you_mean(name, list(params))))
                continue
            ptype = params[name]
            if ptype == "Page":
                if not is_str(value) or value not in self.page_titles:
                    self.r.error(ap, "must be the title of a page (Page parameter), got %s%s"
                                 % (describe(value), did_you_mean(value, list(self.page_titles))))
            elif ptype == "Visualization":
                if not is_str(value) or value not in self.visuals:
                    self.r.error(ap, "must be the id of a visual (Visualization parameter), got %s%s"
                                 % (describe(value), did_you_mean(value, list(self.visuals))))
                elif self.visuals[value]["order"] > order:
                    self.r.warn(ap, "visual '%s' is built after this text area, so this argument becomes a manual step; "
                                "list the text area after it in its page's visuals (the layout decides placement)" % value)
            elif ptype == "DataTable":
                self.ref_table(value, ap, "DataTable argument")
            elif ptype == "String" and not is_str(value):
                if value is None or isinstance(value, (list, dict)):
                    self.r.error(ap, "must be a string, got %s" % describe(value))
                else:
                    self.r.warn(ap, "%s is converted to text for the String parameter" % describe(value))
            elif ptype in DATA_TYPES:
                problem = typed_value_problem(value, ptype, strict=False)
                if problem:
                    self.r.error(ap, problem)

    # ---- top-level references, settings, external tools --------------------------------------------
    def v_top_references(self):
        dt = self.spec.get("defaultTable")
        if dt is not None:
            if not is_str(dt):
                self.r.error("defaultTable", "must be a table name or null, got %s" % describe(dt))
            else:
                self.ref_table(dt, "defaultTable")
        ap = self.spec.get("activePage")
        if ap is not None:
            if not is_str(ap) or ap not in self.page_titles:
                self.r.error("activePage", "unknown page %s%s (null = the first visible page)"
                             % (describe(ap), did_you_mean(ap, list(self.page_titles))))
            else:
                pg = as_list(self.spec.get("pages"))[self.page_titles[ap]]
                if isinstance(pg, dict) and pg.get("visible") is False:
                    self.r.warn("activePage", "page '%s' is hidden (visible: false)" % ap)

    # ---- column references against the data files ------------------------------------------
    # visual type -> fields holding expressions (a string or a list of levels / measures)
    COLUMN_EXPRESSION_FIELDS = {
        "lineChart": ("x", "y", "colorBy", "lineBy"), "barChart": ("x", "y", "colorBy"),
        "combinationChart": ("x", "colorBy"),          # secondaryScale entries may be bare series aliases
        "scatterPlot": ("x", "y", "colorBy", "sizeBy", "shapeBy", "labelBy", "lineBy"),
        "scatterPlot3D": ("x", "y", "z", "colorBy", "sizeBy"), "pieChart": ("sector", "size", "colorBy"),
        "boxPlot": ("x", "y", "colorBy"), "heatMap": ("x", "y", "value", "colorBy"),
        "treemap": ("hierarchy", "size", "colorBy"), "waterfallChart": ("category", "value", "colorBy"),
        "histogram": ("column", "colorBy"), "crossTable": ("rows", "columns", "measures"),
        "graphicalTable": ("rows",),
    }

    def v_columns(self):
        """Column references checked against the columns of the data files the builder loads (SBDF header,
        CSV header row) plus the calculated columns and hierarchies the spec adds to them. Plain column
        names (table columns, sorts, widths, coloring targets, column metadata, hierarchy levels, relations,
        control value sources, data-function column bindings) are errors when unknown; [identifiers] inside
        expressions are warnings (this check reads expressions lexically). Tables written by data functions
        are not checked: their columns are only known after the function runs."""
        self.columns = {}
        self.column_files = {}
        for i, t in enumerate(as_list(self.spec.get("tables"))):
            if not isinstance(t, dict) or not is_str(t.get("name")) or t["name"] in self.produced:
                continue
            cols = self.file_columns(t, pjoin("tables", i, "source", "path"))
            if cols is None:
                continue
            known = dict((name, dtype) for name, dtype in cols)
            for key in ("calculatedColumns", "hierarchies"):
                for c in as_list(t.get(key)):
                    if isinstance(c, dict) and is_str(c.get("name")) and c["name"]:
                        known.setdefault(c["name"], None)
            self.columns[t["name"]] = known
            self.column_files[t["name"]] = str(t["source"]["path"])
        if not self.columns:
            return
        for i, t in enumerate(as_list(self.spec.get("tables"))):
            if not isinstance(t, dict) or t.get("name") not in self.columns:
                continue
            name = t["name"]
            columns = t.get("columns") if isinstance(t.get("columns"), dict) else {}
            for cname in columns:
                self.check_column(name, cname, pjoin("tables", i, "columns", cname), "column metadata for")
            for h, hspec in enumerate(as_list(t.get("hierarchies"))):
                if isinstance(hspec, dict):
                    for k, level in enumerate(as_list(hspec.get("levels"))):
                        self.check_column(name, level, pjoin("tables", i, "hierarchies", h, "levels", k))
            for c, cspec in enumerate(as_list(t.get("calculatedColumns"))):
                if isinstance(cspec, dict):
                    self.check_expression(name, cspec.get("expression"), pjoin("tables", i, "calculatedColumns", c,
                                                                            "expression"))
        for i, rel in enumerate(as_list(self.spec.get("relations"))):
            if not isinstance(rel, dict):
                continue
            for k, pair in enumerate(as_list(rel.get("on"))):
                if isinstance(pair, list) and len(pair) == 2:
                    self.check_column(rel.get("left"), pair[0], pjoin("relations", i, "on", k, 0))
                    self.check_column(rel.get("right"), pair[1], pjoin("relations", i, "on", k, 1))
        for i, d in enumerate(as_list(self.spec.get("dataFunctions"))):
            if not isinstance(d, dict):
                continue
            for k, inp in enumerate(as_list(d.get("inputs"))):
                bind = inp.get("bind") if isinstance(inp, dict) and isinstance(inp.get("bind"), dict) else None
                if bind is None:
                    continue
                bp = pjoin("dataFunctions", i, "inputs", k, "bind")
                if inp.get("type") == "column":
                    self.check_column(bind.get("table"), bind.get("column"), pjoin(bp, "column"))
                elif inp.get("type") == "table" and isinstance(bind.get("columns"), list):
                    for n, col in enumerate(bind["columns"]):
                        self.check_column(bind.get("table"), col, pjoin(bp, "columns", n))
                elif inp.get("type") == "value" and is_str(bind.get("expression")):
                    self.check_expression(None, bind["expression"], pjoin(bp, "expression"))
        default = self.spec.get("defaultTable")
        if not is_str(default) or not default:
            firsts = [t.get("name") for t in as_list(self.spec.get("tables"))
                      if isinstance(t, dict) and self.is_file_table(t.get("name"))]
            default = firsts[0] if firsts else None
        for pi, pg in enumerate(as_list(self.spec.get("pages"))):
            if not isinstance(pg, dict):
                continue
            for vi, v in enumerate(as_list(pg.get("visuals"))):
                if isinstance(v, dict):
                    self.v_visual_columns(v, pjoin("pages", pi, "visuals", vi), v.get("table") or default)

    # ---- filter panel layouts (references/spec-format.md "Filter panel") ------------------------------
    def v_filter_layouts(self):
        """The top-level filterPanelLayout and every page's own "filters": structure, tables (known and built
        before the pages), columns (the SBDF header of a file table; the declared tables[].columns of a
        data-function table), sub groups, filter types (one type per column across the app: types belong to
        the filtering scheme every page shares). Design rule: in an app with two or more tables, a page with
        no layout is warned (an explicit "filters": "all" is a note)."""
        F = t3._filters
        types = {}                                    # (table, column) -> (type, path)
        top = self.spec.get("filterPanelLayout")
        if top is not None:
            if isinstance(top, dict):
                self.v_filter_layout(top, "filterPanelLayout", types)
                pages = [pg for pg in as_list(self.spec.get("pages")) if isinstance(pg, dict)]
                if pages and not any(F.page_layout(self.spec, pg) is top for pg in pages):
                    self.r.warn("filterPanelLayout", "no page uses this layout: every page has its own 'filters' "
                                "(or 'all'), so the builder ignores it, its filterTypes included")
            else:
                self.r.error("filterPanelLayout", "must be a filter layout {\"tables\": [...]}, got %s" % describe(top))
        n_tables = len(set(self.tables) | set(self.produced))
        for i, pg in enumerate(as_list(self.spec.get("pages"))):
            if not isinstance(pg, dict):
                continue
            own = pg.get("filters")
            if isinstance(own, dict):
                self.v_filter_layout(own, pjoin("pages", i, "filters"), types)
            if n_tables < 2 or F.page_layout(self.spec, pg) is not None:
                continue
            title = json.dumps(pg.get("title"))
            if own == F.ALL:
                self.r.note("page %s keeps Spotfire's default filter panel (\"filters\": \"all\"): every table and "
                            "column of the app is listed there" % title)
            else:
                self.r.warn(pjoin("pages", i), "page %s has no filter layout: the app has %d tables, so its filter "
                            "panel lists every table and column; give the page \"filters\" or the spec a "
                            "top-level \"filterPanelLayout\" with only the tables and columns a user needs "
                            "(references/architecture.md, App design rules), or \"filters\": \"all\" to keep them all on purpose"
                            % (title, n_tables))

    def filter_columns(self, table):
        """(columns {name: DataType or None} of a table for the filter layout, source text), or (None, why)."""
        if table in getattr(self, "columns", {}):
            return self.columns[table], self.column_files.get(table, "")
        if table in self.produced:
            t = self.tables.get(table) if isinstance(self.tables.get(table), dict) else {}
            declared = t.get("columns") if isinstance(t.get("columns"), dict) else {}
            return dict((c, None) for c in declared), "the columns declared in tables[].columns"
        return None, "its data file could not be read"

    def filter_column(self, table, column, path, cols, source):
        """Error unless column is a column of the table spelled exactly (filters are found by exact name)."""
        if not is_str(column) or not column.strip():
            self.r.error(path, "must be a column name, got %s" % describe(column))
            return None
        if cols is None:
            return column
        if column in cols:
            if cols[column] == "Binary":
                self.r.error(path, "column '%s' of table %s is Binary: Spotfire has no filter for it" % (column, table))
                return None
            return column
        same = [c for c in cols if c.lower() == column.lower()]
        if same:
            self.r.error(path, "write the column exactly as table %s spells it: '%s' (the builder finds filters by "
                         "their exact name)" % (table, same[0]))
        elif table in self.produced and table not in self.tables:
            self.r.error(path, "'%s': data-function table %s has no tables[] entry; add one (source type "
                         "dataFunction) whose \"columns\" declare every column a filter layout names (a description "
                         "is enough), so the layout can be checked" % (column, table))
        elif table in self.produced:
            self.r.error(path, "'%s' is not among %s of data-function table %s (%s); declare every column a filter "
                         "layout names there (a description is enough), so the layout can be checked"
                         % (column, source, table, ", ".join(sorted(cols)) or "none declared"))
        else:
            self.r.error(path, "'%s' is not a column of table %s (%s)%s" % (column, table, source,
                                                                          did_you_mean(column, list(cols))))
        return None

    def v_filter_layout(self, layout, path, types):
        F = t3._filters
        self.check_keys(layout, F.LAYOUT_KEYS, path)
        tables = self.field(layout, "tables", path, ["list"], required=True)
        if tables is None:
            return
        seen = {}
        for k, entry in enumerate(tables):
            tp = pjoin(path, "tables", k)
            if not self.obj(entry, tp, "a table entry {\"table\": ..., \"columns\": [...]}"):
                continue
            self.check_keys(entry, F.TABLE_KEYS, tp)
            table = self.field(entry, "table", tp, ["str"], required=True)
            self.field(entry, "expanded", tp, ["bool"])
            if table is None:
                continue
            if table in seen:
                self.r.error(pjoin(tp, "table"), "table %s is listed twice in this layout (also tables[%d])"
                             % (table, seen[table]))
                continue
            seen[table] = k
            if self.ref_table(table, pjoin(tp, "table"), "filter layout table") is None:
                continue
            cols, source = self.filter_columns(table)
            if cols is None:
                self.r.note("%s: the columns of table %s were not checked (%s)" % (tp, table, source))
            places = {}                               # column -> where the layout shows it
            columns = entry.get("columns", [])
            visible = 0
            if columns == "*":
                visible = 1
            elif isinstance(columns, list):
                for n, c in enumerate(columns):
                    name = self.filter_column(table, c, pjoin(tp, "columns", n), cols, source)
                    if name is None:
                        continue
                    if name in places:
                        self.r.error(pjoin(tp, "columns", n), "column '%s' is listed twice" % name)
                    places[name] = "columns"
                    visible += 1
            else:
                self.r.error(pjoin(tp, "columns"), "must be a list of column names or \"*\" (every column), got %s"
                             % describe(columns))
            groups = self.field(entry, "subGroups", tp, ["list"]) or []
            names = {}
            for g, group in enumerate(groups):
                gp = pjoin(tp, "subGroups", g)
                if not self.obj(group, gp, "a sub group {\"name\": ..., \"columns\": [...]}"):
                    continue
                self.check_keys(group, F.GROUP_KEYS, gp)
                gname = self.field(group, "name", gp, ["str"], required=True)
                self.field(group, "expanded", gp, ["bool"])
                if gname is not None:
                    if not gname.strip():
                        self.r.error(pjoin(gp, "name"), "must not be empty")
                    elif gname.lower() in names:
                        self.r.error(pjoin(gp, "name"), "sub group '%s' is used twice in table %s (Spotfire needs "
                                     "unique sub group names)" % (gname, table))
                    names[str(gname).lower()] = g
                gcols = self.field(group, "columns", gp, ["list"], required=True)
                if gcols is not None and not gcols:
                    self.r.error(pjoin(gp, "columns"), "a sub group needs at least one column")
                for n, c in enumerate(gcols or []):
                    name = self.filter_column(table, c, pjoin(gp, "columns", n), cols, source)
                    if name is None:
                        continue
                    if name in places:
                        where = "the top-level columns" if places[name] == "columns" else places[name]
                        self.r.error(pjoin(gp, "columns", n), "column '%s' is already shown in %s; a filter has one "
                                     "place in the panel" % (name, where))
                        continue
                    places[name] = "sub group '%s'" % gname
                    visible += 1
            if not visible:
                self.r.error(tp, "table %s shows no filter: list its \"columns\" (\"*\" = every column) or "
                             "\"subGroups\", or leave the table out (tables a layout does not list are hidden)"
                             % table)
            ftypes = self.field(entry, "filterTypes", tp, ["dict"]) or {}
            for column, ftype in ftypes.items():
                fp = pjoin(tp, "filterTypes", column)
                name = self.filter_column(table, column, fp, cols, source)
                if ftype not in F.FILTER_TYPES:
                    self.r.error(fp, "unknown filter type %s (%s)%s" % (describe(ftype), ", ".join(F.FILTER_TYPES),
                                                                      did_you_mean(str(ftype), F.FILTER_TYPES)))
                    continue
                if name is None:
                    continue
                dtype = cols.get(name) if cols else None
                if ftype in F.RANGE_ONLY and dtype in F.UNORDERED_TYPES:
                    self.r.error(fp, "a %s needs a number, date or time column; '%s' is %s (use CheckBoxFilter, "
                                 "ListBoxFilter, RadioButtonFilter or TextFilter)" % (ftype, name, dtype))
                    continue
                key = (table, name)
                if key in types and types[key][0] != ftype:
                    self.r.error(fp, "filter type %s differs from %s at %s: a filter type belongs to the filtering "
                                 "scheme every page shares, so a column has one type in the whole app"
                                 % (ftype, types[key][0], types[key][1]))
                else:
                    types.setdefault(key, (ftype, fp))

    def v_visual_columns(self, v, path, table):
        vtype = v.get("type")
        if vtype == "textArea":
            controls = v.get("controls") if isinstance(v.get("controls"), dict) else {}
            for cid, c in controls.items():
                values = c.get("values") if isinstance(c, dict) and isinstance(c.get("values"), dict) else {}
                src = values.get("column")
                if isinstance(src, dict):
                    self.check_column(src.get("table"), src.get("column"),
                                      pjoin(path, "controls", cid, "values", "column", "column"))
            return
        if not is_str(table):
            return
        for field in self.COLUMN_EXPRESSION_FIELDS.get(vtype, ()):
            for k, item in enumerate(one_or_many(v.get(field))):
                p = pjoin(path, field) if not isinstance(v.get(field), list) else pjoin(path, field, k)
                self.check_axis_value(table, item, p)
        if is_str(v.get("limitExpression")):
            self.check_expression(table, v["limitExpression"], pjoin(path, "limitExpression"))
        trellis = v.get("trellis") if isinstance(v.get("trellis"), dict) else {}
        for key in ("panelBy", "rowsBy", "columnsBy"):
            for item in one_or_many(trellis.get(key)):
                self.check_axis_value(table, item, pjoin(path, "trellis", key))
        for k, layer in enumerate(as_list(v.get("referenceLayers"))):
            if isinstance(layer, dict):
                target = layer.get("table") if is_str(layer.get("table")) else table
                for key in ("value", "low", "high"):
                    if is_str(layer.get(key)):
                        self.check_expression(target, layer[key], pjoin(path, "referenceLayers", k, key))
        if vtype == "combinationChart":
            for k, s in enumerate(as_list(v.get("series"))):
                expression = s.get("expression") if isinstance(s, dict) else s
                self.check_axis_value(table, expression, pjoin(path, "series", k, "expression"))
        elif vtype == "kpiChart":
            for k, kpi in enumerate(as_list(v.get("kpis"))):
                if isinstance(kpi, dict):
                    for key in ("value", "comparative", "time", "tileBy"):
                        for item in one_or_many(kpi.get(key)):
                            self.check_axis_value(table, item, pjoin(path, "kpis", k, key))
        elif vtype == "graphicalTable":
            for k, col in enumerate(as_list(v.get("columns"))):
                if not isinstance(col, dict):
                    continue
                for key in ("expression", "x", "comparative"):
                    self.check_axis_value(table, col.get(key), pjoin(path, "columns", k, key))
                for n, band in enumerate(as_list(col.get("ranges"))):
                    if isinstance(band, dict):
                        self.check_expression(table, band.get("expression"),
                                              pjoin(path, "columns", k, "ranges", n, "expression"))
        elif vtype == "map":
            for k, layer in enumerate(as_list(v.get("layers"))):
                if not isinstance(layer, dict):
                    continue
                target = layer.get("table") if is_str(layer.get("table")) else table
                for key in ("latitude", "longitude", "geometry", "colorBy", "sizeBy", "lineBy", "labelBy",
                            "shapeBy"):
                    for item in one_or_many(layer.get(key)):
                        self.check_axis_value(target, item, pjoin(path, "layers", k, key))
                if is_str(layer.get("limitExpression")):
                    self.check_expression(target, layer["limitExpression"],
                                          pjoin(path, "layers", k, "limitExpression"))
        elif vtype == "mod":
            axes = v.get("axes") if isinstance(v.get("axes"), dict) else {}
            for name, value in axes.items():
                for item in one_or_many(value):
                    self.check_axis_value(table, item, pjoin(path, "axes", name))
            for k, layer in enumerate(as_list(v.get("layers"))):
                if not isinstance(layer, dict):
                    continue
                target = layer.get("table") if is_str(layer.get("table")) else table
                laxes = layer.get("axes") if isinstance(layer.get("axes"), dict) else {}
                for name, value in laxes.items():
                    for item in one_or_many(value):
                        self.check_axis_value(target, item, pjoin(path, "layers", k, "axes", name))
                if is_str(layer.get("limitExpression")):
                    self.check_expression(target, layer["limitExpression"], pjoin(path, "layers", k, "limitExpression"))
        elif vtype in ("table", "summaryTable"):
            for k, col in enumerate(as_list(v.get("columns"))):
                self.check_column(table, col, pjoin(path, "columns", k))
            if vtype == "table":
                for k, s in enumerate(as_list(v.get("sort"))):
                    col = s.get("column") if isinstance(s, dict) else s
                    self.check_column(table, col, pjoin(path, "sort", k, "column"))
                widths = v.get("widths") if isinstance(v.get("widths"), dict) else {}
                for col in widths:
                    self.check_column(table, col, pjoin(path, "widths", col))
                for k, c in enumerate(one_or_many(v.get("coloring"))):
                    if isinstance(c, dict):
                        for n, col in enumerate(as_list(c.get("columns"))):
                            self.check_column(table, col, pjoin(path, "coloring", k, "columns", n))

    def file_columns(self, t, path):
        """Columns of a table's data file, or None when they cannot be read here (no file, data function)."""
        src = t.get("source") if isinstance(t.get("source"), dict) else {}
        stype, rel = src.get("type"), src.get("path")
        if stype not in ("sbdf", "csv") or not is_str(rel) or not rel:
            return None
        full = Path(rel) if Path(rel).is_absolute() else self.app_dir / rel
        if not full.is_file():
            return None                             # v_tables reported the missing file
        if stype == "csv":
            return csv_columns(full, src)
        try:
            return sbdf_columns(full)
        except (OSError, ValueError) as e:
            self.r.warn(path, "could not read the SBDF header of %s (%s); column references to table %s were "
                        "not checked" % (full.name, e, t.get("name")))
            return None

    def column_name(self, table, name):
        """The table's spelling of column `name` (Spotfire matches column names case-insensitively), or None."""
        cols = self.columns.get(table) or {}
        if name in cols:
            return name
        low = name.lower()
        for c in cols:
            if c.lower() == low:
                return c
        return None

    def check_column(self, table, column, path, what="column"):
        """Error when the plain column name (or '[Name]') is not a column of the table's data file."""
        if not is_str(table) or table not in self.columns or not is_str(column) or not column.strip():
            return
        name = column.strip()
        if name.startswith("[") and name.endswith("]"):
            name = name[1:-1].replace("]]", "]")
        if self.column_name(table, name) is None:
            self.r.error(path, "%s '%s' is not a column of table %s (%s)%s"
                         % (what, name, table, self.column_files.get(table, ""),
                            did_you_mean(name, list(self.columns[table]))))

    def check_expression(self, table, text, path):
        """Warning for every [column] of the expression that its table ([T].[C]: table T) does not have."""
        for owner, name in expression_columns(text):
            target = owner or table
            if not is_str(target) or target not in self.columns or self.column_name(target, name) is not None:
                continue
            self.r.warn(path, "[%s] is not a column of table %s (%s)%s; the expression cannot work"
                        % (name, target, self.column_files.get(target, ""),
                           did_you_mean(name, list(self.columns[target]))))

    def check_axis_value(self, table, value, path):
        """An axis value: an expression, or a bare column name, which the builder escapes when the table has
        it (outer <...> allowed). A bare word that is no column of the table is warned."""
        if not is_str(value) or not value.strip():
            return
        text = value.strip()
        inner = text[1:-1].strip() if text.startswith("<") and text.endswith(">") else text
        if inner and "[" not in inner and "(" not in inner and not re.match(r"^[-+]?\d", inner) \
                and inner.lower() not in ("true", "false", "null"):
            if table in self.columns and self.column_name(table, inner) is None:
                self.r.warn(path, "'%s' is neither a column of table %s (%s) nor an expression with [column] "
                            "references%s" % (inner, table, self.column_files.get(table, ""),
                                              did_you_mean(inner, list(self.columns[table]))))
            return
        self.check_expression(table, text, path)

    # ---- reference-line value types ---------------------------------------------------------------
    _DATE_FORMAT_RE = re.compile(r"yy|[Hh]{1,2}:mm|MMM|dd[-/. ]MM|MM[-/. ]dd")
    _NUMBER_FORMAT_RE = re.compile(r"^[-+#0,.%$ ;()E]*[#0][-+#0,.%$ ;()E]*$")
    _DATE_NAME_RE = re.compile(r"(?i)^(?:date|datetime|timestamp|time stamp)$|\s(?:date|datetime|timestamp)$")
    REF_AXIS = {"verticalLine": {"lineChart": "x", "scatterPlot": "x", "combinationChart": "x"},
                "horizontalLine": {"lineChart": "y", "scatterPlot": "y", "barChart": "y", "boxPlot": "y",
                                   "combinationChart": "series"}}
    KIND_WORDS = {"date": "a date", "number": "a number", "string": "text", "boolean": "true or false",
                  "time": "a time"}

    def prop_type(self, name):
        """Declared DataType of a document property, or None (undeclared, data-function output)."""
        canon = self.props.get(str(name).lower())
        pspec = self.prop_specs.get(canon) if canon else None
        return pspec.get("type") if isinstance(pspec, dict) and is_str(pspec.get("type")) else None

    def column_kind(self, table, name):
        """(kind, source) of a column: source 'type' (the data file's column type), 'format' (a date or
        number format in tables[].columns), 'name' (a date-like name: Date, Timestamp, Start Date) or
        (None, None). Data-function tables have no column types before they run: format, then name."""
        cols = getattr(self, "columns", {})
        canon = self.column_name(table, name) if table in cols else None
        if canon is not None and cols[table].get(canon) in TYPE_KIND:
            return TYPE_KIND[cols[table][canon]], "type"
        t = self.tables.get(table) if isinstance(self.tables.get(table), dict) else {}
        meta = t.get("columns") if isinstance(t.get("columns"), dict) else {}
        fmt = meta.get(name, {}).get("format") if isinstance(meta.get(name), dict) else None
        if is_str(fmt) and fmt.strip():
            if self._DATE_FORMAT_RE.search(fmt):
                return "date", "format"
            if self._NUMBER_FORMAT_RE.match(fmt):
                return "number", "format"
        if self._DATE_NAME_RE.search(name):
            return "date", "name"
        return None, None

    def axis_kind(self, table, axis):
        """(kind, guessed, text) of a continuous axis; (None, False, None) for a categorical (<...>)
        axis or when the kind cannot be told. guessed: the kind rests on a column name only."""
        items = [a.strip() for a in one_or_many(axis) if is_str(a) and a.strip()]
        kinds, guessed = set(), False
        for text in items:
            if text.startswith("<"):
                return None, False, None
            expr = text if ("[" in text or "(" in text or re.match(r"^[-+]?\d", text)) else "[%s]" % text
            sources = []

            def ck(col, sources=sources):
                kind, src = self.column_kind(table, col)
                if src:
                    sources.append(src)
                return kind
            kind, _ = value_kind(expr, self.prop_type, ck)
            if kind is None:
                return None, False, None
            kinds.add(kind)
            guessed = guessed or "name" in sources
        if len(kinds) != 1:
            return None, False, None
        return kinds.pop(), guessed, items[0]

    def v_reference_types(self):
        """A reference line must evaluate to the type of its axis (otherwise Spotfire reports "reference
        element's expression is not valid" or "Invalid type for function call 'DateAdd'"). Errors: DateAdd / AddDays /
        ... over a document property that is not a Date or DateTime property (any reference layer), and a
        line whose value type (a DocumentProperty's declared type, arithmetic, a literal, a date or
        number function) differs from its axis type (the data file's column type, a column format, an
        aggregation); a warning when the axis type rests on the column name only."""
        default = self.spec.get("defaultTable")
        if not is_str(default) or not default:
            firsts = [t.get("name") for t in as_list(self.spec.get("tables"))
                      if isinstance(t, dict) and self.is_file_table(t.get("name"))]
            default = firsts[0] if firsts else None
        dates = [n for n, p in self.prop_specs.items()
                 if isinstance(p, dict) and p.get("type") in ("Date", "DateTime")]
        hint = (" (DateTime properties of this spec: %s)" % ", ".join(dates[:6])) if dates else ""
        for pi, pg in enumerate(as_list(self.spec.get("pages"))):
            for vi, v in enumerate(as_list(pg.get("visuals")) if isinstance(pg, dict) else []):
                if not isinstance(v, dict) or not isinstance(v.get("referenceLayers"), list):
                    continue
                vtype = v.get("type")
                table = v.get("table") if is_str(v.get("table")) else default
                for k, layer in enumerate(v["referenceLayers"]):
                    if isinstance(layer, dict):
                        self.v_reference_type(layer, pjoin("pages", pi, "visuals", vi, "referenceLayers", k),
                                              v, vtype, table, hint)

    def v_reference_type(self, layer, lp, v, vtype, table, hint):
        kind = layer.get("kind")
        target = layer.get("table") if is_str(layer.get("table")) else table
        for f in (("low", "high") if kind == "band" else ("value",)):
            text = layer.get(f)
            if not is_str(text):
                continue
            bad = [(fn, p, self.prop_type(p)) for fn, p in date_call_properties(text)
                   if self.prop_type(p) and self.prop_type(p) not in ("Date", "DateTime")]
            if bad:
                fn, p, t = bad[0]
                self.r.error(pjoin(lp, f), "%s(...) takes DocumentProperty(\"%s\"), a %s property: Spotfire rejects "
                             "the line (\"Invalid type for function call '%s'\", \"reference element's expression "
                             "is not valid\"). A date reference line reads a DateTime property directly: let the "
                             "script or data function that sets the day also write a DateTime property and use "
                             "DocumentProperty(\"<it>\")%s" % (fn, p, t, fn, hint))
                continue
            field = self.REF_AXIS.get(kind, {}).get(vtype)
            if field is None:
                continue
            axis = v.get(field)
            if field == "series":
                axis = [s.get("expression") if isinstance(s, dict) else s for s in as_list(axis)]
            akind, guessed, atext = self.axis_kind(target, axis)
            if akind not in ("date", "number", "time"):
                continue
            vkind, why = value_kind(text, self.prop_type, lambda c, t=target: self.column_kind(t, c)[0])
            if vkind is None or vkind == akind:
                continue
            if akind == "date":
                fix = "bind date reference lines to a DateTime property, DocumentProperty(\"<it>\")%s" % hint
            else:
                fix = "use a numeric property or expression"
            msg = ("the %s axis (%s) holds %ss but this %s evaluates to %s (%s): Spotfire shows \"reference "
                   "element's expression is not valid\"; %s"
                   % ("X" if kind == "verticalLine" else "Y", atext, akind, kind,
                      self.KIND_WORDS.get(vkind, vkind), why, fix))
            if guessed:
                self.r.warn(pjoin(lp, f), msg + " (the axis type is guessed from the column name; a format in "
                            "tables[].columns makes this an error)")
            else:
                self.r.error(pjoin(lp, f), msg)

    # ---- customer-ready text (scripts/textlint.py) --------------------------------------------------
    def v_customer_text(self):
        """No internal language in anything a customer can read, embedded code included (textlint.py)."""
        def read(rel):
            full = Path(rel) if Path(rel).is_absolute() else self.app_dir / rel
            key = str(full)
            if key in self.texts:
                return self.texts[key], key
            if not full.is_file():
                return None, key
            return read_text_file(full)[0], key
        found = textlint.check_app(self.spec, read)
        for level, path, message in found:
            self.r.add(level, path, "customer-ready text: " + message)
        if found:
            code = sum(1 for f in found if "of the embedded code" in f[2])
            self.r.note("customer-ready text: %d finding(s) in visible text, %d in embedded code (rules: "
                        "scripts/textlint.py; per app: app.textLint, app.bannedTerms)" % (len(found) - code, code))

    def v_settings(self):
        if not self.settings_jobs:
            return
        try:
            index = load_index(self.opts.api_dir)
        except (OSError, ValueError) as e:
            self.r.note("the API index could not be read (%s); settings paths were not checked" % e)
            return
        if index is None:
            self.r.note("no spotfire-api-*.json in %s; settings paths were not checked" % self.opts.api_dir)
            return
        types = {}
        for path, key, value, targets, mode in self.settings_jobs:
            entries = []
            for name in targets:
                if name not in types:
                    types[name] = index.find_type(name)
                entries.append(types[name])
            if any(e is None for e in entries):
                missing = [n for n, e in zip(targets, entries) if e is None]
                self.r.note("type %s is not in the API index; %s was not checked" % (", ".join(missing), path))
                continue
            if mode == "maps":
                viz, base = entries
                head = key.split(".")[0]
                start = viz if head != "Title" and index.member(viz, head) is not None else base
                errors, warnings = index.check_path(start, key, value, self.min_version)
            elif mode == "any":
                results = [index.check_path(e, key, value, self.min_version) for e in entries]
                good = [res for res in results if not res[0]]
                errors, warnings = good[0] if good else results[0]
            else:
                errors, warnings = index.check_path(entries[0], key, value, self.min_version)
            for e in errors:
                self.r.error(path, e)
            for w in warnings:
                self.r.warn(path, w)

    def v_tools(self):
        """scripts/lint_ipy.py on every IronPython script and postScript (optional; run in parallel, results
        recorded here in spec order); the safe-mode text areas are checked with dxpgen's sanitizer
        emulation (finish_html)."""
        tools = self.opts.tools_dir
        lint = tools / "lint_ipy.py"
        tasks = []
        if self.ipy_jobs and self.opts.lint:
            if lint.is_file():
                tasks.extend(("lint", job) for job in self.ipy_jobs)
            else:
                self.r.note("scripts/lint_ipy.py not found: %d IronPython script(s) were not linted" % len(self.ipy_jobs))
        elif self.ipy_jobs:
            self.r.note("lint skipped (--no-lint): %d IronPython script(s) were not linted" % len(self.ipy_jobs))
        if self.html_mode == "safe" and not self.opts.sanitize:
            self.r.note("sanitizer check skipped (--no-sanitize): text-area HTML was not checked against Spotfire's "
                        "HTML sanitizer")
        results = {}
        if tasks:
            with tempfile.TemporaryDirectory(prefix="dxpgen-") as tmp:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, self.opts.workers)) as pool:
                    futures = {}
                    for n, (what, job) in enumerate(tasks):
                        futures[n] = pool.submit(run_lint_job, lint, job, tmp, n, self.min_version)
                    for n in sorted(futures):
                        results[n] = futures[n].result()
        for n, (what, job) in enumerate(tasks):
            for level, path, message in results.get(n, []):
                self.r.add(level, path, message)
        self.finish_html()

    def finish_html(self):
        """Safe mode: dxpgen's emulation of Spotfire's default sanitizer (allowlist and rules) reports what
        a sanitizing viewer would change."""
        for job in self.html_jobs:
            for level, message, count in job["static"]:
                text = "Spotfire's HTML sanitizer (on by default in 15.0) would change %s: %s%s" % (
                    job["label"], message, " (%d times)" % count if count > 1 else "")
                if level == "error":
                    self.r.error(job["path"], text)
                else:
                    self.r.warn(job["path"], text)

# ---------------------------------------------------------------------------------------------
# external tools (each optional; never Spotfire itself)
# ---------------------------------------------------------------------------------------------


def tail(text, lines=4, width=300):
    rows = [r.strip() for r in (text or "").splitlines() if r.strip()]
    s = " | ".join(rows[-lines:])
    return (s[:width] + "...") if len(s) > width else s


def run_lint_job(lint, job, tmp, n, min_version):
    """[(level, path, message)] from scripts/lint_ipy.py --json for one script or postScript. Script
    parameters (and the postScript scope names) are passed with --globals so they are not undefined."""
    if "file" in job:
        target = Path(job["file"])
    else:
        target = Path(tmp) / ("ipy_%03d.py" % n)
        target.write_text(job["code"], encoding="utf-8")
    cmd = [sys.executable, str(lint), str(target), "--min-version", min_version, "--json"]
    if job.get("document"):
        cmd.append("--document-script")
    if job.get("globals"):
        cmd.extend(["--globals", ",".join(job["globals"])])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return [("note", "", "lint_ipy.py could not run on %s: %s" % (job["label"], e))]
    findings = []
    try:
        data = json.loads(proc.stdout)
        for f in data.get("findings", []):
            if isinstance(f, dict):
                findings.append((f.get("severity"), f.get("line"), f.get("col"), f.get("message"), f.get("code")))
    except (ValueError, AttributeError, TypeError):
        for line in (proc.stdout or "").splitlines():
            m = LINT_LINE_RE.match(line.strip())
            if m:
                findings.append((m.group("level"), m.group("line"), m.group("col"), m.group("msg"), None))
    out = []
    for severity, line, col, message, code in findings:
        level = "error" if severity == "error" else "warning"
        out.append((level, job["path"], "lint (%s, line %s, col %s): %s%s"
                    % (job["label"], line, col, message, " [%s]" % code if code else "")))
    if proc.returncode not in (0, 1):
        out.append(("note", "", "lint_ipy.py failed on %s (exit %d): %s"
                    % (job["label"], proc.returncode, tail(proc.stderr or proc.stdout))))
    elif proc.returncode == 1 and not any(level == "error" for level, _, _ in out):
        out.append(("error", job["path"], "lint_ipy.py reported errors for %s: %s" % (job["label"], tail(proc.stdout))))
    return out


def validate_app(app_dir, spec_path, options=None):
    """(Report, spec or None, raw spec.json bytes)."""
    report = Report()
    spec, raw = load_spec(spec_path, report)
    if spec is None:
        return report, None, raw
    report.extend(Validator(spec, app_dir, options).run())
    return report, spec, raw


# ---------------------------------------------------------------------------------------------
# resolved spec (references/architecture.md, "Resolved spec"): files inlined, data paths absolute, defaults explicit
# ---------------------------------------------------------------------------------------------
def _fill(d, defaults, null_means_default=()):
    """Add missing keys (and replace null where null means 'use the default'); keeps key order."""
    for key, value in defaults:
        if key not in d or (d[key] is None and key in null_means_default):
            d[key] = copy.deepcopy(value)
    return d


def _abs_path(app_dir, rel):
    return os.path.normpath(os.path.join(str(app_dir), rel))


def _read(app_dir, rel):
    text, problem = read_text_file(Path(app_dir) / rel)
    if problem:
        raise ValueError("cannot read %s: %s" % (rel, problem))
    return text


def default_marking_name(spec):
    marks = [m for m in as_list(spec.get("markings")) if isinstance(m, dict) and is_str(m.get("name")) and m["name"]]
    for m in marks:
        if m.get("default") is True:
            return m["name"]
    return marks[0]["name"] if marks else "Marking"


def resolve_spec(spec, app_dir):
    """The dict embedded as SPEC in the builder. Assumes the spec validated without errors."""
    app_dir = Path(app_dir).resolve()
    s = copy.deepcopy(spec)
    out = {"specVersion": s.get("specVersion", 1)}

    app = s.get("app") if isinstance(s.get("app"), dict) else {}
    name = app.get("name") or "analysis"
    _fill(app, [("description", ""), ("keywords", []), ("output", "build/" + name + ".dxp"),
                ("namingPolicy", "program"), ("htmlMode", "safe"), ("theme", {"base": "LightSfx"}),
                ("pageNavigation", "Tabs"), ("canvas", None),
                ("snapshots", {"enabled": True, "width": 1600, "height": 900}), ("minimumSpotfireVersion", "14.6")],
          ("description", "keywords", "output", "namingPolicy", "htmlMode", "theme", "pageNavigation", "snapshots",
           "minimumSpotfireVersion"))
    theme = app["theme"]
    _fill(theme, [("base", "LightSfx")], ("base",))
    styles = theme.get("customStyles")
    if styles is None:
        theme.pop("customStyles", None)
    elif is_str(styles):
        theme["customStyles"] = json.loads(_read(app_dir, styles))
    if isinstance(app.get("canvas"), dict):
        _fill(app["canvas"], [("fitToWindow", True)], ("fitToWindow",))
    _fill(app["snapshots"], [("enabled", True), ("width", 1600), ("height", 900)], ("enabled", "width", "height"))
    for key in VALIDATE_ONLY_APP_KEYS:
        app.pop(key, None)
    out["app"] = app

    tables = []
    for t in as_list(s.get("tables")):
        _fill(t, [("description", ""), ("columns", {}), ("calculatedColumns", []), ("hierarchies", []),
                  ("embed", True)], ("description", "columns", "calculatedColumns", "hierarchies", "embed"))
        src = t.get("source") if isinstance(t.get("source"), dict) else {}
        if src.get("type") in ("sbdf", "csv") and is_str(src.get("path")):
            src["path"] = _abs_path(app_dir, src["path"])
        if src.get("type") == "csv":
            _fill(src, [("separator", ","), ("culture", "en-US"), ("encoding", "utf-8"), ("header", True),
                        ("columns", {})], ("separator", "culture", "encoding", "header", "columns"))
        for c in t["calculatedColumns"]:
            if isinstance(c, dict):
                _fill(c, [("description", "")], ("description",))
        tables.append(t)
    out["tables"] = tables
    default_table = s.get("defaultTable")
    out["defaultTable"] = default_table
    out["relations"] = as_list(s.get("relations"))
    out["markings"] = [_fill(m, [("default", False)], ("default",)) for m in as_list(s.get("markings"))]
    out["filteringSchemes"] = [_fill(f, [("default", False)], ("default",)) for f in as_list(s.get("filteringSchemes"))]
    out["properties"] = [_fill(p, [("description", ""), ("listValued", False), ("default", None)],
                               ("description", "listValued")) for p in as_list(s.get("properties"))]

    functions = []
    for d in as_list(s.get("dataFunctions")):
        _fill(d, [("description", ""), ("engine", "python"), ("refresh", "automatic"), ("executeAtBuild", True),
                  ("inputs", []), ("outputs", [])],
              ("description", "engine", "refresh", "executeAtBuild", "inputs", "outputs"))
        if is_str(d.get("script")) and d["script"]:
            d["scriptCode"] = _read(app_dir, d["script"])
        for inp in d["inputs"]:
            if isinstance(inp, dict) and inp.get("type") == "table" and isinstance(inp.get("bind"), dict):
                _fill(inp["bind"], [("columns", "*"), ("limitByFiltering", None), ("limitByMarking", None)], ("columns",))
        functions.append(d)
    out["dataFunctions"] = functions

    scripts = []
    for sc in as_list(s.get("scripts")):
        if is_str(sc.get("file")) and sc["file"]:
            sc["code"] = _read(app_dir, sc["file"])
        _fill(sc, [("description", ""), ("parameters", []), ("transaction", True)],
              ("description", "parameters", "transaction"))
        for prm in sc["parameters"]:
            if isinstance(prm, dict):
                _fill(prm, [("type", "String"), ("description", "")], ("type", "description"))
        scripts.append(sc)
    out["scripts"] = scripts
    out["triggers"] = as_list(s.get("triggers"))

    marking = default_marking_name(s)
    pages = []
    for pg in as_list(s.get("pages")):
        _fill(pg, [("visible", True), ("filterPanel", False), ("detailsOnDemand", False), ("filteringScheme", None),
                   ("visuals", []), ("layout", {})], ("visible", "filterPanel", "detailsOnDemand", "visuals", "layout"))
        pg["visuals"] = [_resolve_visual(v, app_dir, default_table, marking) for v in pg["visuals"]]
        pages.append(pg)
    out["pages"] = pages
    out["activePage"] = s.get("activePage")
    for key, value in s.items():                       # unknown top-level keys (warned) stay as given
        if key not in out:
            out[key] = value
    return out


def library_spec(resolved):
    """The resolved spec as the library builders (--tier full / slim) embed it: without app.style, the
    standard engine's style layer, the filter panel layouts (filterPanelLayout, page filters) and vizMods
    (lib/85_mods.py finds a mod in Analyst by modId), which lib/ never reads."""
    if isinstance(resolved.get("app"), dict):
        resolved["app"].pop("style", None)
    resolved.pop("filterPanelLayout", None)
    resolved.pop("vizMods", None)
    for page in as_list(resolved.get("pages")):
        if isinstance(page, dict):
            page.pop("filters", None)
    return resolved


def page_filter_layout(spec, page):
    """The normalized filter layout of a page ([{table, columns, expanded, filterTypes, subGroups}], display
    order), or None when the page keeps Spotfire's default panel (scripts/t3/_filters.py; verify_dxp uses it)."""
    layout = t3._filters.page_layout(spec, page)
    return None if layout is None else t3._filters.tables_of(layout)


def _resolve_visual(v, app_dir, default_table, marking):
    if not isinstance(v, dict):
        return v
    vtype = v.get("type")
    _fill(v, [("title", ""), ("showTitle", True), ("description", "")], ("title", "showTitle", "description"))
    if vtype == "textArea":
        html_value = v.get("html")
        if is_str(html_value) and html_value.strip() and not html_value.lstrip().startswith("<"):
            v["html"] = _read(app_dir, html_value.strip())
        elif not is_str(html_value):
            v["html"] = ""
        css = v.get("css")
        if is_str(css) and css.strip() and "{" not in css:
            v["css"] = _read(app_dir, css.strip())
        elif not is_str(css):
            v["css"] = ""
        scripts = []
        for item in as_list(v.get("js")):
            if is_str(item):
                scripts.append({"name": Path(item).stem, "code": _read(app_dir, item)})
            elif isinstance(item, dict):
                scripts.append(item)
        v["js"] = scripts
        controls = v.get("controls") if isinstance(v.get("controls"), dict) else {}
        for cspec in controls.values():
            if not isinstance(cspec, dict):
                continue
            if cspec.get("kind") == "slider":
                _fill(cspec, [("step", 1)], ("step",))
            if cspec.get("kind") in ("button", "link") and cspec.get("script") is not None:
                _fill(cspec, [("args", {})], ("args",))
        v["controls"] = controls
    else:
        if v.get("table") is None:
            v["table"] = default_table
        if "marking" not in v:
            v["marking"] = marking
        legend = v.get("legend")
        if isinstance(legend, bool):
            v["legend"] = {"visible": legend}
        elif isinstance(legend, dict):
            _fill(legend, [("visible", True)], ("visible",))
        _fill(v, [("limitByMarkings", []), ("emptyMarkingBehavior", "ShowAll"), ("limitExpression", None),
                  ("useFiltering", True), ("legend", {"visible": True}), ("coloring", None), ("referenceLayers", []),
                  ("fittingModels", [])],
              ("limitByMarkings", "emptyMarkingBehavior", "useFiltering", "legend", "referenceLayers", "fittingModels"))
        for key in ("xScale", "yScale", "zScale"):
            if isinstance(v.get(key), dict):
                _fill(v[key], SCALE_FILL, ("log", "individualScaling"))
        if isinstance(v.get("settings"), dict) and any(k in SETTINGS_ALIASES for k in v["settings"]):
            v["settings"] = dict((SETTINGS_ALIASES.get(k, k), val) for k, val in v["settings"].items())
        if vtype == "histogram":
            _fill(v, [("bins", 20)], ("bins",))
        if vtype == "map":
            _fill(v, [("autoZoom", True)], ("autoZoom",))
    _fill(v, [("settings", {}), ("postScript", None)], ("settings",))
    return v


# ---------------------------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------------------------
def library_files(lib_dir=None):
    return sorted(Path(lib_dir or LIB_DIR).glob("[0-9][0-9]_*.py"), key=lambda p: p.name)


def spec_literal(obj):
    """Python 3.4 literal of the resolved spec: plain dict/list/str/int/float/bool/None, ASCII only."""
    text = pprint.pformat(obj, indent=1, width=110, sort_dicts=False)
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    if ast.literal_eval(text) != obj:
        raise ValueError("the resolved spec does not round-trip as a Python literal")
    return text


def path_literal(path):
    s = str(path)
    if s.isascii() and '"' not in s and not s.endswith("\\") and "\n" not in s:
        return 'r"' + s + '"'
    return ascii(s)


def render_builder(resolved, app_dir, slug, spec_sha, lib_parts, lib_sha, generated):
    app = resolved.get("app", {})
    rule = "# " + "=" * 98
    lines = [
        "# -*- coding: utf-8 -*-",
        rule,
        "# Spotfire DXP builder for %s (app folder %s)" % (json.dumps(app.get("name", "")), slug),
        "# Generated by scripts/dxpgen.py on %s" % generated,
        "# spec.json sha256: %s" % spec_sha,
        "# library sha256:   %s" % lib_sha,
        "#   (lib/%s)" % ", lib/".join(name for name, _ in lib_parts),
        "# Saves to:         %s, plus build-report.json, MANUAL-STEPS.md and snapshots/ next to it"
        % json.dumps(app.get("output", "")),
        "#",
        "# How to run it (you start it; nothing runs automatically):",
        "#   1. In Spotfire Analyst open a new analysis and add any starter data.",
        "#   2. Edit > Document Properties > Scripts > New; untick 'Execute in transaction'.",
        "#   3. Choose IronPython 3, paste this whole file and click Run Script.",
        "#   4. Close the dialog with Cancel (OK would store this builder inside the analysis).",
        "#   The builder creates everything, then saves the analysis and writes its reports by itself.",
        "# Do not edit this file: change spec.json and run scripts/dxpgen.py build again.",
        rule,
        "",
    ]
    for name, text in lib_parts:
        lines.append("# " + "-" * 40 + " lib/" + name + " " + "-" * 40)
        lines.append(text.rstrip("\n"))
        lines.append("")
        lines.append("")
    lines.extend([rule, "# Resolved spec (generated by scripts/dxpgen.py) and the build call", rule,
                  "SPEC = " + spec_literal(resolved),
                  "APP_DIR = " + path_literal(app_dir),
                  "B = BuildContext(SPEC, APP_DIR, Document, Application, %s, %s)" % (json.dumps(spec_sha),
                                                                                     json.dumps(lib_sha)),
                  "run_build()"])
    return "\n".join(lines) + "\n"


_SCRIPT_GLOBALS = {"Document", "Application", "B", "SPEC", "APP_DIR"}


def _top_level_names(stmt):
    names = []
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [stmt.name]
    for sub in ast.walk(stmt):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            names.append(sub.id)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            names.extend((a.asname or a.name).split(".")[0] for a in sub.names)
    return names


def _bound_names(node):
    bound = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(sub.name)
        elif isinstance(sub, ast.arg):
            bound.add(sub.arg)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in sub.names)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
    return bound


def library_check(lib_parts, resolved):
    """[(level, message)] about the concatenated library: modules that do not parse, top-level names
    defined twice, names used but defined by no module (a module still missing), visual builders the
    spec needs. Missing pieces are warnings: the builder still runs and reports those steps as failed."""
    issues = []
    defined = {}
    trees = []
    for name, text in lib_parts:
        try:
            tree = ast.parse(text, filename="lib/" + name)
        except SyntaxError as e:
            issues.append(("error", "lib/%s does not parse: %s (line %s)" % (name, e.msg, e.lineno)))
            continue
        trees.append((name, tree))
        for stmt in tree.body:
            for n in _top_level_names(stmt):
                if n in defined and defined[n] != name and not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    issues.append(("warning", "top-level name '%s' is defined in lib/%s and again in lib/%s; the later "
                                   "definition wins in the builder" % (n, defined[n], name)))
                defined.setdefault(n, name)
    known = set(defined) | set(dir(builtins)) | _SCRIPT_GLOBALS
    missing = {}
    for name, tree in trees:
        for stmt in tree.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            bound = _bound_names(stmt)
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in known \
                        and sub.id not in bound:
                    missing.setdefault(sub.id, set()).add(name)
    for ident in sorted(missing):
        hint = VISUAL_MODULE.get(ident)
        issues.append(("warning", "%s() is used by %s but no lib module defines it%s"
                       % (ident, ", ".join("lib/" + m for m in sorted(missing[ident])),
                          " (expected in lib/%s)" % hint if hint else "")))
    builders = {}
    for name, tree in trees:
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VISUAL_BUILDERS"
                                                    for t in stmt.targets):
                try:
                    builders = ast.literal_eval(stmt.value)
                except ValueError:
                    pass
    used = sorted(set(v.get("type") for p in as_list(resolved.get("pages")) if isinstance(p, dict)
                      for v in as_list(p.get("visuals")) if isinstance(v, dict) and is_str(v.get("type"))))
    for vtype in used:
        fn = builders.get(vtype)
        if fn is None:
            issues.append(("warning", "VISUAL_BUILDERS (lib/90_build.py) has no entry for visual type '%s'" % vtype))
        elif fn not in defined:
            issues.append(("warning", "no lib module defines %s() for visual type '%s' (expected in lib/%s); those "
                           "visuals will fail in the build report" % (fn, vtype, VISUAL_MODULE.get(fn, "?"))))
    for required in ("BuildContext", "run_build"):
        if required not in defined:
            issues.append(("error", "the library defines no %s (lib/00_core.py, lib/90_build.py)" % required))
    return issues


def lint_builder(path, tools_dir, min_version):
    """(exit code, findings, stdout) of scripts/lint_ipy.py on the generated builder, or None when the tool
    is not available. The builder is not a document script (no --document-script)."""
    lint = Path(tools_dir) / "lint_ipy.py"
    if not lint.is_file():
        return None
    try:
        proc = subprocess.run([sys.executable, str(lint), str(path), "--min-version", min_version],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        return (-1, [], str(e))
    findings = []
    for line in (proc.stdout or "").splitlines():
        m = LINT_LINE_RE.match(line.strip())
        if m:
            findings.append(m.groupdict())
    return (proc.returncode, findings, (proc.stdout or "") + (proc.stderr or ""))


def copy_to_clipboard(path, sink=None):
    """Windows clipboard via PowerShell Set-Clipboard (CRLF line ends for the Analyst script editor).
    sink: write the same text to this file instead of the clipboard (used by the tests)."""
    put = ("Set-Clipboard -Value $t" if sink is None
           else "[System.IO.File]::WriteAllText('%s', $t)" % str(sink).replace("'", "''"))
    script = ("$t = [System.IO.File]::ReadAllText('%s', [System.Text.Encoding]::UTF8); "
              "$t = $t -replace '\\r?\\n', ([string][char]13 + [char]10); " % str(path).replace("'", "''")) + put
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return proc.returncode == 0, tail(proc.stderr or proc.stdout)


BUILD_TIERS = ("standard", "quick", "compact", "report", "slim", "full")


def build_app(app_dir, spec_path, options, clipboard=False, out=None, tier="standard"):
    """validate -> resolve -> write the builder of one tier -> checks. Returns an exit code.

    standard (default), quick, compact and report use the standard engine (engine/, t3/); slim
    delegates to slim_builder.py (the trimmed library, an exception tier); full is the whole
    concatenated library (too big for the script editor: library development only)."""
    if tier == "slim":
        import slim_builder              # it imports dxpgen, so not at module level
        app_dir = Path(app_dir).resolve()
        target = app_dir / "build" / ("build_%s_slim.py" % app_slug(app_dir))
        return slim_builder.slim_app(app_dir, spec_path, options, tag="slim", out_path=target,
                                     clipboard=clipboard, out=out)
    if tier == "full":
        return build_full(app_dir, spec_path, options, clipboard, out)
    if tier not in t3.TIERS:
        (out or sys.stdout).write("unknown tier '%s' (%s)\n" % (tier, ", ".join(BUILD_TIERS)))
        return EXIT_USAGE
    return build_engine(app_dir, spec_path, options, tier, clipboard, out)


def column_reader(resolved):
    """table name -> [(column, DataType name)] read from its SBDF header (None when unreadable)."""
    cache = {}

    def columns(name):
        if name not in cache:
            cache[name] = None
            for t in as_list(resolved.get("tables")):
                src = t.get("source") if isinstance(t, dict) and isinstance(t.get("source"), dict) else {}
                if t.get("name") == name and src.get("type") == "sbdf" and is_str(src.get("path")):
                    try:
                        cache[name] = sbdf_columns(src["path"])
                    except (OSError, ValueError):
                        cache[name] = None
        return cache[name]
    return columns


def ipy_parse(target, tools_dir):
    """(True|False, text) from scripts/ipy_parse.ps1 (Spotfire's own IronPython 3.4 compiler), or None
    when it cannot run here (no PowerShell, no script, no Spotfire install)."""
    ps1 = Path(tools_dir) / "ipy_parse.ps1"
    if os.name != "nt" or not ps1.is_file():
        return None
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
                               "-File", str(target)], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    for line in text.splitlines():
        if line.startswith("PARSE OK"):
            return True, line.strip()
    if text.startswith("ERROR ") or "\nERROR " in text:
        return False, tail(text, 6)
    return None


def sfapi_has(specs, tools_dir, setter=False, api_dir=None):
    """(missing specs, OK count) from sfapi.py has --stdin [--set], or None when it cannot run (no tool,
    or no API index: SFAPI_INDEX or $DXP_WORKSPACE/api)."""
    if not specs:
        return [], 0
    tool = Path(tools_dir) / "sfapi.py"
    index = find_index_file(api_dir)
    if not tool.is_file() or index is None:
        return None
    cmd = [sys.executable, str(tool), "--index", str(index), "has", "--stdin"] + (["--set"] if setter else [])
    try:
        proc = subprocess.run(cmd, input="\n".join(specs) + "\n", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (proc.stdout or "").splitlines()
    missing = [line[3:].strip() for line in lines if line.startswith("NO ")]
    okay = len([line for line in lines if line.startswith("OK ")])
    if not missing and okay < len(specs):
        missing = ["(sfapi.py answered %d of %d specs: %s)" % (okay, len(specs), tail(proc.stderr or ""))]
    return missing, okay


def engine_checks(target, text, result, options, min_version):
    """(Report, summary lines) of a standard-engine builder: Python parse, lines <= 79 / ASCII / tabs,
    undefined names, lint_ipy.py, Spotfire's IronPython 3.4 parser and sfapi.py for every member the
    included engine parts declare."""
    import slim_builder                  # it imports dxpgen, so not at module level
    checks = Report()
    summary = []
    try:
        ast.parse(text, filename=str(target))
        summary.append("Python parse OK")
    except SyntaxError as e:
        checks.error(target.name, "the builder does not parse: %s (line %s)" % (e.msg, e.lineno))
    problems = slim_builder.text_problems(text)
    for p in problems[:15]:
        checks.error(target.name, p)
    if not problems:
        summary.append("lines <= 79, ASCII, no tabs")
    names = slim_builder.undefined_names(text)
    for name, count in sorted(names.items()):
        checks.error(target.name, "%s is used %d time(s) but never defined" % (name, count))
    if not names:
        summary.append("every name defined")
    if not options.lint:
        summary.append("lint, IronPython parse and sfapi.py not run (--no-lint)")
        return checks, summary
    lint = lint_builder(target, options.tools_dir, min_version)
    if lint is None:
        checks.note("lint not run: scripts/lint_ipy.py not found in %s" % options.tools_dir)
    else:
        code, findings, output = lint
        (target.parent / ("lint-" + target.stem + ".txt")).write_text(output, encoding="utf-8")
        errors = [f for f in findings if f["level"] == "error"]
        for f in errors[:15]:
            checks.error(target.name, "lint line %s, col %s: %s" % (f["line"], f["col"], f["msg"]))
        for f in [f for f in findings if f["level"] != "error"][:10]:
            checks.warn(target.name, "lint line %s, col %s: %s" % (f["line"], f["col"], f["msg"]))
        if code not in (0, 1):
            checks.note("lint_ipy.py failed on the builder (exit %s): %s" % (code, tail(output)))
        summary.append("lint %d error(s), %d warning(s)" % (len(errors), len(findings) - len(errors)))
    parsed = ipy_parse(target, options.tools_dir)
    if parsed is None:
        checks.note("IronPython parse not run (scripts/ipy_parse.ps1 needs Windows PowerShell and Spotfire "
                    "Analyst 15.0 installed)")
    elif parsed[0]:
        summary.append(parsed[1])
    else:
        checks.error(target.name, "Spotfire's IronPython 3.4 parser: %s" % parsed[1])
    api, setters = result.members()
    counts = []
    for specs, setter, label in ((api, False, "members"), (setters, True, "setters")):
        found = sfapi_has(specs, options.tools_dir, setter=setter, api_dir=options.api_dir)
        if found is None:
            checks.note("sfapi.py has not run for the %s (tool or API index missing: %s)"
                        % (label, sfenv.NO_INDEX_HINT))
            continue
        missing, okay = found
        for spec in missing:
            checks.error(target.name, "sfapi.py has%s: %s is not in the 15.0 index"
                         % (" --set" if setter else "", spec))
        counts.append("%d %s" % (okay, label))
    if counts:
        summary.append("sfapi.py has: " + ", ".join(counts) + " OK")
    return checks, summary


def run_instructions(out, target, copied, output_path, extra=None):
    out.write("\nTo build the analysis (with the running-spotfire-unattended skill installed, run the builder "
              "through it instead):\n")
    out.write("  1. In Spotfire Analyst open a new analysis and add any starter data.\n")
    out.write("  2. Edit > Document Properties > Scripts > New, IronPython 3, and untick "
              "\"Execute in transaction\"\n     (inside a transaction Spotfire refuses to save).\n")
    if copied:
        out.write("  3. Paste (Ctrl+V) and click Run Script.\n")
    else:
        out.write("  3. Paste the whole content of %s and click Run Script.\n" % target.name)
    out.write("  4. Close the dialog with Cancel (OK would store the builder script inside the analysis).\n")
    out.write("The analysis saves itself to %s.\n" % output_path)
    for line in extra or []:
        out.write(line + "\n")


def build_engine(app_dir, spec_path, options, tier, clipboard=False, out=None, slug=None,
                 release=None, info=None):
    """standard / quick / compact / report: the standard engine (engine/ + t3/), plus
    build/MANUAL-STEPS-<tier>.md (what the public API cannot build) and build/theme.json (app.theme
    custom styles, for the manual theme step).
    slug: the builder's name part (default: the app folder name); release: the version a release
    builds (header line, APP "release" on the log's first line); info: a dict that receives target,
    output, log, home, files, size and check errors (dxpgen release reads it)."""
    out = out or sys.stdout
    report, spec, raw = validate_app(app_dir, spec_path, options)
    out.write(report.render("Validating %s" % spec_path) + "\n")
    if report.errors or spec is None:
        out.write("\nBuild aborted: fix the errors above, then run build again.\n")
        return EXIT_INVALID
    app_dir = Path(app_dir).resolve()
    slug = slug or app_slug(app_dir)
    target = app_dir / "build" / ("build_%s_%s.py" % (slug, tier))
    try:
        resolved = resolve_spec(spec, app_dir)
        meta = {"spec_sha": sha256_bytes(raw),
                "generated": datetime.datetime.now().replace(microsecond=0).isoformat()}
        if release:
            meta["release"] = release
        result = t3.generate(resolved, spec, app_dir, tier, column_reader(resolved), meta)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        out.write("\nBuild aborted: %s\n" % e)
        return EXIT_INVALID
    if result.problems:
        out.write("\nBuild aborted: the standard engine cannot build this spec yet. Build it with --tier slim "
                  "(the trimmed library), or change the spec:\n")
        for path, message in result.problems:
            out.write("  %s: %s\n" % (path, message))
        return EXIT_INVALID
    text = result.text
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    manual_file = write_manual_steps(app_dir, resolved, tier, result)
    min_version = resolved["app"].get("minimumSpotfireVersion") or "14.6"
    checks, summary = engine_checks(target, text, result, options, min_version)
    size = len(text.encode("utf-8"))
    if info is not None:
        info.update(target=target, output=result.output, log=result.log, home=result.home, size=size,
                    files=list((result.app or {}).get("files") or []), spec_sha=meta["spec_sha"],
                    errors=[e["message"] for e in checks.errors], summary=summary)
    out.write("\n%s builder written: %s\n" % (tier.capitalize(), target))
    out.write("  %s\n" % t3.TIER_TEXT[tier])
    if result.manual:
        out.write("  manual steps: %d item(s) have no public API; add them by hand after the build: %s\n"
                  % (len(result.manual), manual_file))
    out.write("  %.1f KB (%d bytes, %d lines); engine parts: %s\n"
              % (size / 1000.0, size, text.count("\n"), ", ".join(p.name for p in result.parts)))
    out.write("  checks: %s\n" % "; ".join(summary))
    if result.notes:
        out.write("  not stored by the standard engine (use --tier slim if they matter): %s\n"
                  % ", ".join(result.notes))
    if checks.items:
        out.write(checks.render("Checks of the generated builder:") + "\n")
    copied = False
    if clipboard:
        copied, problem = copy_to_clipboard(target)
        out.write("\nThe builder is on the clipboard.\n" if copied
                  else "\nCould not copy to the clipboard (%s); open the file and copy it by hand.\n" % problem)
    extra = ["Problems go to %s (no 'Saved' line there: use File > Save As)." % result.log]
    if "guard" in result.features:
        tag = tier
        extra.append("After Run Script + Cancel the open analysis shows a 'Build Session' page and is linked to "
                     "%s: close it without saving and open the saved DXP (closing the Document Properties dialog "
                     "resets the markings of the open analysis, never of the saved file)."
                     % (Path(result.output).parent / "session" / ("~build-session-" + tag + ".dxp")))
    if tier == "report":
        tag = result.app.get("tag", "report")
        extra.append("The report files go next to it: build-report-%s.json, MANUAL-STEPS-%s.md, "
                     "snapshots-%s\\." % (tag, tag, tag))
    extra.append("Then verify it: python \"%s\" check \"%s\" --dxp \"%s\""
                 % (TOOL_DIR / "verify_dxp.py", app_dir, result.output))
    if not release:
        extra.append("Handing it over? Release it instead, so the recipient gets a versioned builder and the "
                     "previous version stays as the backup: python \"%s\" release \"%s\" --version vX.Y "
                     "--notes \"...\"" % (Path(__file__).resolve(), app_dir))
    run_instructions(out, target, copied, result.output, extra)
    if clipboard and not copied:
        return EXIT_INVALID
    return EXIT_INVALID if checks.errors else EXIT_OK


def write_manual_steps(app_dir, resolved, tier, result):
    """build/MANUAL-STEPS-<tier>.md (what the public API cannot build; the report tier's builder rewrites
    it after the run with its failed steps too) and, when app.theme has custom styles, build/theme.json.
    Returns the MANUAL-STEPS path."""
    from t3 import _manual
    build = Path(app_dir) / "build"
    build.mkdir(parents=True, exist_ok=True)
    name = (resolved.get("app") or {}).get("name") or Path(app_dir).name
    path = build / ("MANUAL-STEPS-%s.md" % tier)
    path.write_text(_manual.markdown(name, tier, result.manual), encoding="utf-8", newline="\n")
    theme = (resolved.get("app") or {}).get("theme")
    styles = theme.get("customStyles") if isinstance(theme, dict) else None
    if isinstance(styles, dict):
        styles = json.loads(json.dumps(styles))
        general = styles.setdefault("general", {}) if isinstance(styles.get("general", {}), dict) else {}
        base = theme.get("base") or "LightSfx"
        general["baseTheme"] = base
        general["baseThemeSfx"] = base
        (build / "theme.json").write_text(json.dumps(styles, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                          newline="\n")
    return path


def build_full(app_dir, spec_path, options, clipboard=False, out=None):
    """--tier full: validate -> resolve -> build/build_<AppSlug>_full.py (every lib module, about 450 KB:
    too big for Analyst's script editor; library development only) -> checks. Returns an exit code."""
    out = out or sys.stdout
    report, spec, raw = validate_app(app_dir, spec_path, options)
    out.write(report.render("Validating %s" % spec_path) + "\n")
    if report.errors or spec is None:
        out.write("\nBuild aborted: fix the errors above, then run build again.\n")
        return EXIT_INVALID
    files = library_files()
    if not files:
        out.write("\nBuild aborted: no lib/[0-9][0-9]_*.py files in %s\n" % LIB_DIR)
        return EXIT_INVALID
    slug = app_slug(app_dir)
    target = Path(app_dir) / "build" / ("build_" + slug + "_full.py")
    try:
        resolved = library_spec(resolve_spec(spec, app_dir))
        parts = []
        lib_bytes = b""
        for f in files:
            data = f.read_bytes()
            lib_bytes += data
            parts.append((f.name, data.decode("utf-8-sig").replace("\r\n", "\n")))
        lib_sha = sha256_bytes(lib_bytes)
        spec_sha = sha256_bytes(raw)
        generated = datetime.datetime.now().replace(microsecond=0).isoformat()
        text = render_builder(resolved, Path(app_dir).resolve(), slug, spec_sha, parts, lib_sha, generated)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    except (OSError, ValueError, UnicodeDecodeError) as e:
        out.write("\nBuild aborted: %s\n" % e)
        return EXIT_INVALID

    checks = Report()
    try:
        ast.parse(text, filename=str(target))
    except SyntaxError as e:
        checks.error(target.name, "the generated builder does not parse: %s (line %s)" % (e.msg, e.lineno))
    for level, message in library_check(parts, resolved):
        if level == "error":
            checks.error("lib", message)
        else:
            checks.warn("lib", message)
    min_version = resolved["app"].get("minimumSpotfireVersion") or "14.6"
    lint = lint_builder(target, options.tools_dir, min_version) if options.lint else None
    lint_line = "not run (--no-lint)" if not options.lint else "not run (scripts/lint_ipy.py not found)"
    if lint is not None:
        code, findings, output = lint
        log = target.parent / "lint-builder.txt"
        log.write_text(output, encoding="utf-8")
        errors = [f for f in findings if f["level"] == "error"]
        lint_line = "%d error(s), %d warning(s) - full output in %s" % (len(errors), len(findings) - len(errors), log)
        for f in errors[:15]:
            checks.error(target.name, "lint line %s, col %s: %s" % (f["line"], f["col"], f["msg"]))
        if code not in (0, 1):
            checks.note("lint_ipy.py failed on the builder (exit %s): %s" % (code, tail(output)))
        elif code == 1 and not errors:
            checks.error(target.name, "lint_ipy.py reported errors: %s" % tail(output))

    size = len(text.encode("utf-8"))
    out.write("\nFull-library builder written: %s (%d KB)\n" % (target, (size + 1023) // 1024))
    out.write("  WARNING: the full library is too big for Analyst's script editor and is never the "
              "build to hand over;\n  use --tier standard (or --tier slim when the standard engine "
              "cannot build the spec).\n")
    out.write("  spec.json sha256 %s, library sha256 %s (%d modules)\n" % (spec_sha[:16], lib_sha[:16], len(parts)))
    out.write("  lint of the builder: %s\n" % lint_line)
    if t3._filters.uses_layouts(spec):
        out.write("  note: the filter panel layouts (filterPanelLayout, page filters) are built by the standard "
                  "engine only; this builder leaves every page's filter panel as Spotfire makes it\n")
    if checks.items:
        out.write(checks.render("Checks of the generated builder:") + "\n")
    copied = False
    if clipboard:
        copied, problem = copy_to_clipboard(target)
        if copied:
            out.write("\nThe builder is on the clipboard.\n")
        else:
            out.write("\nCould not copy to the clipboard (%s); open the file and copy it by hand.\n" % problem)
    output_path = Path(_abs_path(Path(app_dir).resolve(), resolved["app"]["output"]))
    out.write("\nTo build the analysis (you start it; nothing runs automatically):\n")
    out.write("  1. In Spotfire Analyst open a new analysis and add any starter data.\n")
    out.write("  2. Edit > Document Properties > Scripts > New; untick 'Execute in transaction'.\n")
    if copied:
        out.write("  3. Choose IronPython 3, paste (Ctrl+V) and click Run Script.\n")
    else:
        out.write("  3. Choose IronPython 3, paste the whole content of %s and click Run Script.\n" % target.name)
    out.write("  4. Close the dialog with Cancel (OK would store the builder script inside the analysis).\n")
    out.write("The analysis saves itself to %s,\nwith build-report.json and MANUAL-STEPS.md in %s.\n"
              % (output_path, output_path.parent))
    out.write("Then verify it: python \"%s\" verify \"%s\"\n" % (Path(__file__).resolve(), Path(app_dir).resolve()))
    if clipboard and not copied:
        return EXIT_INVALID
    return EXIT_INVALID if checks.errors else EXIT_OK


# ---------------------------------------------------------------------------------------------
# new (scaffold)
# ---------------------------------------------------------------------------------------------
def skeleton_spec(name):
    return {
        "specVersion": 1,
        "app": {"name": name, "description": "", "keywords": [], "namingPolicy": "program", "htmlMode": "safe",
                "theme": {"base": "LightSfx"}, "pageNavigation": "Tabs", "minimumSpotfireVersion": "14.6"},
        "tables": [],
        "defaultTable": None,
        "relations": [],
        "markings": [],
        "filteringSchemes": [],
        "properties": [],
        "dataFunctions": [],
        "scripts": [],
        "triggers": [],
        "pages": [{"title": "Overview", "visible": True, "filterPanel": False, "detailsOnDemand": False,
                   "filteringScheme": None,
                   "visuals": [{"id": "overviewText", "type": "textArea", "title": "Overview", "showTitle": False,
                                "html": "html/overview.html", "css": "", "js": [], "controls": {}}],
                   "layout": {}}],
        "activePage": "Overview",
    }


def skeleton_html(name):
    return ('<div style="padding: 12px 16px;">\n'
            '  <h2 style="margin: 0;">%s</h2>\n'
            '  <p style="margin: 6px 0 0 0; color: #555555;">Replace this text area with the app\'s pages, visuals and '
            'controls (see references/spec-format.md).</p>\n'
            '</div>\n' % html_escape(name))


def html_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def name_from_slug(slug):
    words = _words(slug)
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words) or slug


def cmd_new(args, out=None):
    out = out or sys.stdout
    slug = args.slug
    if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", slug):
        sys.stderr.write("AppSlug must start with a letter and use only letters, digits, '-' and '_' "
                         "(e.g. PumpStationMonitor)\n")
        return EXIT_USAGE
    root = Path(args.workspace) if getattr(args, "workspace", None) else workspace_root()
    if root is None:
        sys.stderr.write("Set DXP_WORKSPACE to the folder that holds apps/ (or pass --workspace DIR)\n")
        return EXIT_USAGE
    app_dir = root / "apps" / slug
    spec_path = app_dir / "spec.json"
    if spec_path.exists():
        sys.stderr.write("%s already exists; not overwriting it\n" % spec_path)
        return EXIT_USAGE
    name = args.name or name_from_slug(slug)
    if any(ch in BAD_FILE_NAME_CHARS or ord(ch) < 32 for ch in name):
        sys.stderr.write("the app name is also the output file name and cannot contain %s\n" % BAD_FILE_NAME_CHARS)
        return EXIT_USAGE
    for sub in ("data", "html", "scripts", "datafunctions", "build"):
        (app_dir / sub).mkdir(parents=True, exist_ok=True)
    overview = app_dir / "html" / "overview.html"
    if not overview.exists():
        overview.write_text(skeleton_html(name), encoding="utf-8")
    spec_path.write_text(json.dumps(skeleton_spec(name), indent=2) + "\n", encoding="utf-8")
    out.write("Created %s\n" % app_dir)
    for sub in ("spec.json", "data/", "html/overview.html", "scripts/", "datafunctions/", "build/"):
        out.write("  %s\n" % sub)
    out.write("\nNext:\n"
              "  1. Export the data to SBDF with Spotfire's own Python: scripts/sbdf_export.py <file> data/<TABLE>.sbdf\n"
              "  2. Write spec.json (references/spec-format.md) and the html/, scripts/, datafunctions/ files.\n"
              "  3. python \"%s\" validate \"%s\"\n"
              "  4. python \"%s\" build \"%s\" --clipboard\n"
              % (Path(__file__).resolve(), app_dir, Path(__file__).resolve(), app_dir))
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# release: one frozen, self-contained copy of the app per version (<app>\versions\vX.Y)
# ---------------------------------------------------------------------------------------------
RELEASE_VERSION_RE = re.compile(r"^v\d+(\.\d+){0,3}([-_][A-Za-z0-9]+)?$")
RELEASE_FILES = ("spec.json", "DESIGN.md", "build/RUN-STEPS.md")        # copied when present
RELEASE_FOLDERS = ("html", "scripts", "datafunctions", "tools", "actionmod")   # whole, when present
RELEASE_EXCLUDED = ("source", "_work", "devtests", "docs", "build/session", "versions")
RELEASE_SKIP = ("node_modules", "__pycache__", ".git", ".pytest_cache")
VERSIONS_TABLE_HEAD = "| Version | Date | Spec hash | Builders | Saved DXP | Status | Notes |"
VERSIONS_TABLE_RULE = "|---|---|---|---|---|---|---|"
STATUS_READY = "Generated, not yet run (paste-safety checks passed)"
STATUS_FAILED = "Checks FAILED - do not use"


def versions_readme_intro(name):
    return [
        "# %s - versions" % name,
        "",
        "Each folder `vX.Y\\` is a frozen, self-contained copy of one release (`dxpgen.py release`): the",
        "spec, the files the builders read (html, scripts, data functions, tools, actionmod,",
        "the SBDFs the spec loads), the builders, the logs and the saved DXP under `build\\`. Each folder's",
        "`VERSION.md` says which builder to paste.",
        "",
        "Rules:",
        "- **Open the DXP in `vX.Y\\build\\` to use a version.** Nothing needs to run.",
        "- **The builders in `vX.Y\\build\\` have HOME set to their own version folder.** They read only that",
        "  folder and save only into `vX.Y\\build\\`; they can never overwrite the live app (`..\\build\\`) or",
        "  another version. A builder whose files are not all there stops before it changes anything",
        "  (\"This builder does not match the files in ...\"): paste the builder of the version you want.",
        "- Never edit files inside a version folder: change the app folder and release a new version. The",
        "  previous good version stays as the backup.",
        "- The newest version is the last row. Spec hash = first 12 hex characters of sha256(spec.json), the",
        "  same value as in the builder header and on the first line of its build log. After the DXP was",
        "  opened and checked, write the outcome into Status (e.g. Good, Broken).",
        "",
    ]


def spec_file_refs(spec):
    """[(spec path, value, is_folder)] of every file or folder the spec references (relative to the app
    folder as written): table sources, data-function and IronPython code, text-area HTML / CSS /
    JavaScript files, app.theme.customStyles, action-mod and visualization-mod project folders."""
    refs = []

    def add(path, value, folder=False):
        if is_str(value) and value.strip():
            refs.append((path, value.strip(), folder))
    app = spec.get("app") if isinstance(spec.get("app"), dict) else {}
    theme = app.get("theme") if isinstance(app.get("theme"), dict) else {}
    add("app.theme.customStyles", theme.get("customStyles"))
    for n, t in enumerate(as_list(spec.get("tables"))):
        src = t.get("source") if isinstance(t, dict) and isinstance(t.get("source"), dict) else {}
        if src.get("type") in ("sbdf", "csv"):
            add("tables[%d].source.path" % n, src.get("path"))
    for n, d in enumerate(as_list(spec.get("dataFunctions"))):
        if isinstance(d, dict):
            add("dataFunctions[%d].script" % n, d.get("script"))
    for n, s in enumerate(as_list(spec.get("scripts"))):
        if isinstance(s, dict):
            add("scripts[%d].file" % n, s.get("file"))
    for n, m in enumerate(as_list(spec.get("actionMods"))):
        if isinstance(m, dict):
            add("actionMods[%d].project" % n, m.get("project"), folder=True)
    for n, m in enumerate(as_list(spec.get("vizMods"))):
        if isinstance(m, dict):
            add("vizMods[%d].project" % n, m.get("project"), folder=True)
    for i, pg in enumerate(as_list(spec.get("pages"))):
        for j, v in enumerate(as_list(pg.get("visuals")) if isinstance(pg, dict) else []):
            if not isinstance(v, dict) or v.get("type") != "textArea":
                continue
            vp = "pages[%d].visuals[%d]" % (i, j)
            if is_str(v.get("html")) and not v["html"].lstrip().startswith("<"):
                add(vp + ".html", v["html"])
            if is_str(v.get("css")) and "{" not in v["css"]:
                add(vp + ".css", v["css"])
            for k, item in enumerate(as_list(v.get("js"))):
                add("%s.js[%d]" % (vp, k), item)
    return refs


def _release_skip(names_dir, names):
    return [n for n in names if n in RELEASE_SKIP or n.endswith(".pyc")]


def _rel_posix(path, root):
    return Path(os.path.relpath(str(path), str(root))).as_posix()


def release_plan(app_dir, spec):
    """(files [(source, relative target)], folders [(source, relative target)], errors, warnings) of a
    release: RELEASE_FILES, RELEASE_FOLDERS and every file or folder the spec references (data files only
    when referenced). A reference outside the app folder is an error: a release must be complete."""
    app_dir = Path(app_dir).resolve()
    files, folders, errors, warnings = [], [], [], []
    for rel in RELEASE_FILES:
        if (app_dir / rel).is_file():
            files.append((app_dir / rel, rel))
    for rel in RELEASE_FOLDERS:
        if (app_dir / rel).is_dir():
            folders.append((app_dir / rel, rel))
    covered = [rel for _, rel in folders]
    for path, value, is_folder in spec_file_refs(spec):
        if Path(value).is_absolute() or Path(value).drive:
            errors.append("%s: %s is an absolute path; the copied spec would still read it from there (give "
                          "a path relative to the app folder)" % (path, value))
            continue
        full = (app_dir / value).resolve()
        try:
            rel = _rel_posix(full, app_dir)
            full.relative_to(app_dir)
        except ValueError:
            errors.append("%s: %s is outside the app folder; a release copies only the app folder (give "
                          "a path inside it)" % (path, value))
            continue
        if not (full.is_dir() if is_folder else full.is_file()):
            errors.append("%s: %s not found" % (path, value))
            continue
        if rel.split("/")[0] in RELEASE_SKIP:
            errors.append("%s: %s is in a folder a release never copies (%s)" % (path, value, rel.split("/")[0]))
            continue
        for ex in RELEASE_EXCLUDED:
            if rel == ex or rel.startswith(ex + "/"):
                warnings.append("%s: %s is in %s/, which a release leaves out; copied anyway because the "
                                "builder reads it" % (path, value, ex))
        if any(rel == c or rel.startswith(c + "/") for c in covered):
            continue
        if is_folder:
            folders.append((full, rel))
            covered.append(rel)
        elif rel not in [r for _, r in files]:
            files.append((full, rel))
    return files, folders, errors, warnings


def copy_release(files, folders, version_dir):
    """Copy the plan into version_dir (overwriting files with the same name, deleting nothing).
    Returns {top-level item: file count}."""
    import shutil
    counts = {}
    for src, rel in folders:
        dst = version_dir / rel
        shutil.copytree(str(src), str(dst), ignore=_release_skip, dirs_exist_ok=True)
        counts[rel + "/"] = len([p for p in dst.rglob("*") if p.is_file()])
    for src, rel in files:
        dst = version_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        top = rel.split("/")[0] + ("/" if "/" in rel else "")
        counts[top] = counts.get(top, 0) + 1
    return counts


def builder_literals(text):
    """(HOME, APP) literals of a standard-engine builder, None where absent."""
    found = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("HOME", "APP"):
                try:
                    found[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found.get("HOME"), found.get("APP")


def release_check(target, version_dir):
    """Problems of a release builder: HOME must be the version folder, the DXP and the log must land in
    its build folder, and every file of the preflight list must be in the version folder."""
    problems = []
    try:
        home, app = builder_literals(Path(target).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as e:
        return ["%s cannot be read back: %s" % (Path(target).name, e)]
    if home is None or os.path.normcase(os.path.normpath(home)) != os.path.normcase(str(version_dir)):
        problems.append("%s: HOME is %s, not the version folder %s" % (Path(target).name, home, version_dir))
        return problems
    build_dir = os.path.normcase(str(Path(version_dir) / "build"))
    for key in ("output", "log"):
        full = os.path.normcase(os.path.normpath(os.path.join(home, *str((app or {}).get(key, "")).split("\\"))))
        if not full.startswith(build_dir + os.sep):
            problems.append("%s: APP %s %s is not in %s" % (Path(target).name, key, (app or {}).get(key), build_dir))
    for rel in (app or {}).get("files") or []:
        if not os.path.isfile(os.path.join(home, *rel.split("\\"))):
            problems.append("%s: reads %s, which is not in the version folder" % (Path(target).name, rel))
    return problems


def _cell(text):
    return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def _is_table_head(line):
    return re.sub(r"\s+", " ", line.strip().lower()) == VERSIONS_TABLE_HEAD.lower()


def update_versions_readme(readme, name, row):
    """Write the README of <app>\\versions: the intro (only for a new README) and the version table
    (header matched without case), with the row of row[0] replaced or appended; any other text and rows
    stay as they are."""
    line = "| " + " | ".join(_cell(c) for c in row) + " |"
    lines = readme.read_text(encoding="utf-8").splitlines() if readme.is_file() else versions_readme_intro(name)
    heads = [n for n, text in enumerate(lines) if _is_table_head(text)]
    if heads:
        head = heads[0]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [VERSIONS_TABLE_HEAD, VERSIONS_TABLE_RULE]
        head = len(lines) - 2
    end = head + 1
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    for n in range(head + 2, end):
        cells = [c.strip() for c in lines[n].strip().strip("|").split("|")]
        if cells and cells[0] == _cell(row[0]):
            lines[n] = line
            break
    else:
        lines.insert(end, line)
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def version_note(name, version, spec_sha, status, built, notes):
    """VERSION.md of a version folder: what it is and which builder to paste."""
    lines = ["# %s %s" % (name, version), "",
             "- Released %s with `scripts/dxpgen.py release` from spec.json %s."
             % (datetime.date.today().isoformat(), spec_sha),
             "- Status: %s." % status,
             "- Paste one builder (HOME is this folder: it reads only this folder and saves into `build\\`):"]
    for b in built:
        lines.append("  - `build\\%s` saves `build\\%s`" % (Path(b["target"]).name, Path(b["output"]).name))
    if notes:
        lines.append("- Notes: %s" % notes)
    lines += ["- `build\\RUN-STEPS.md` (when present) is the app's copy: where it names a builder or a",
              "  folder, use the builders above and this folder.", ""]
    return "\n".join(lines)


def release_app(app_dir, spec_path, options, version, notes="", force=False, tier="standard", out=None):
    """dxpgen release: copy the app's runtime files into <app>\\versions\\<version>, generate the builders
    from that copy (HOME = the version folder, the DXP saves into its build folder), check them and
    record the release in <app>\\versions\\README.md. Returns an exit code."""
    out = out or sys.stdout
    app_dir = Path(app_dir).resolve()
    if not RELEASE_VERSION_RE.match(version or ""):
        out.write("--version must look like v2, v2.1 or v2.1.3 (optionally -rc1); got '%s'\n" % version)
        return EXIT_USAGE
    if app_dir.parent.name.lower() == "versions":
        out.write("%s is a version folder; release from the app folder %s\n" % (app_dir, app_dir.parent.parent))
        return EXIT_USAGE
    if tier not in t3.TIERS:
        out.write("a release uses the standard engine (tiers %s); got '%s'\n" % (", ".join(t3.TIERS), tier))
        return EXIT_USAGE
    if Path(spec_path).resolve() != app_dir / "spec.json":
        out.write("a release needs the app's own spec.json (%s)\n" % (app_dir / "spec.json"))
        return EXIT_USAGE
    pre = Options(lint=False, sanitize=False, tools_dir=options.tools_dir, api_dir=options.api_dir)
    report, spec, _ = validate_app(app_dir, spec_path, pre)
    if report.errors or spec is None:
        out.write(report.render("Validating %s (structure only; the full checks run on the copy)" % spec_path)
                  + "\n\nRelease aborted: fix the errors above; nothing was copied.\n")
        return EXIT_INVALID
    version_dir = app_dir / "versions" / version
    if version_dir.exists():
        saved = sorted(p for p in (version_dir / "build").rglob("*.dxp")) if (version_dir / "build").is_dir() else []
        if not force:
            out.write("%s already exists: a released version is never regenerated in place. Release a new "
                      "version, or add --force to regenerate one that was never built.\n" % version_dir)
            return EXIT_USAGE
        if saved:
            out.write("%s holds a saved DXP (%s): that version was built, so it is kept as it is (even with "
                      "--force). Release a new version.\n" % (version_dir, saved[0].name))
            return EXIT_USAGE
    files, folders, errors, warnings = release_plan(app_dir, spec)
    if errors:
        out.write("Release aborted, nothing was copied:\n" + "".join("  %s\n" % e for e in errors))
        return EXIT_INVALID
    version_dir.mkdir(parents=True, exist_ok=True)
    counts = copy_release(files, folders, version_dir)
    out.write("Release %s of %s\n  folder: %s\n  copied: %s\n" % (
        version, app_dir.name, version_dir, ", ".join("%s (%d)" % (k, counts[k]) for k in counts)))
    for w in warnings:
        out.write("  warning: %s\n" % w)
    slug = "%s_%s" % (app_slug(app_dir), version)        # RELEASE_VERSION_RE: safe in a file name
    built, problems = [], []
    for _ in (tier,):
        info = {}
        out.write("\n" + "=" * 100 + "\n")
        code = build_engine(version_dir, version_dir / "spec.json", options, tier, out=out, slug=slug,
                            release=version, info=info)
        if not info.get("target"):
            problems.append("the %s builder was not generated (exit %s)" % (tier, code))
            continue
        problems += info.get("errors", [])
        if code != EXIT_OK and not info.get("errors"):
            problems.append("%s: build exit %s" % (info["target"].name, code))
        problems += release_check(info["target"], version_dir)
        built.append(info)
    spec_sha = (built[0]["spec_sha"] if built else sha256_bytes((version_dir / "spec.json").read_bytes()))[:12]
    ready = bool(built) and not problems
    status = STATUS_READY if ready else STATUS_FAILED
    name = (spec.get("app") or {}).get("name") or app_dir.name
    saved = ", ".join("%s\\build\\%s" % (version, Path(b["output"]).name) for b in built)
    row = [version, datetime.date.today().isoformat(), spec_sha,
           ", ".join(Path(b["target"]).name for b in built) or "-",
           ("none yet (saves %s)" % saved) if saved else "-", status, notes or ""]
    readme = app_dir / "versions" / "README.md"
    update_versions_readme(readme, name, row)
    (version_dir / "VERSION.md").write_text(version_note(name, version, spec_sha, status, built, notes),
                                           encoding="utf-8", newline="\n")
    out.write("\n" + "=" * 100 + "\nRelease %s: %s\n" % (version, status))
    for p in problems:
        out.write("  problem: %s\n" % p)
    fresh = set(os.path.normcase(str(b["target"])) for b in built)
    stale = sorted(p.name for p in (version_dir / "build").glob("build_*.py") if os.path.normcase(str(p)) not in fresh)
    if stale:
        out.write("  warning: builder(s) of an earlier run of %s, not regenerated now and not in the README: %s\n"
                  % (version, ", ".join(stale)))
    if ready:
        out.write("Hand over the versioned builder%s (paste one, it saves into %s):\n"
                  % ("s" if len(built) > 1 else "", version_dir / "build"))
    elif built:
        out.write("Do not hand these over until the problems above are fixed (then release again with --force):\n")
    for b in built:
        out.write("  %s\n    -> %s\n" % (b["target"], b["output"]))
    out.write("Recorded in %s and %s.\n" % (readme, version_dir / "VERSION.md"))
    return EXIT_OK if ready else EXIT_INVALID


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------
def _options(args):
    return Options(lint=not getattr(args, "no_lint", False), sanitize=not getattr(args, "no_sanitize", False),
                   tools_dir=getattr(args, "tools_dir", None))


def _app_or_usage(arg):
    found = resolve_app(arg)
    if found is None:
        root = workspace_root()
        where = str(root / "apps") if root is not None else "$DXP_WORKSPACE/apps (DXP_WORKSPACE is not set)"
        sys.stderr.write("app not found: %s (give an app folder, its spec.json, or an app slug under %s)\n"
                         % (arg, where))
        return None
    app_dir, spec_path = found
    if not spec_path.is_file():
        sys.stderr.write("no spec.json in %s (scaffold one with: dxpgen.py new <AppSlug>)\n" % app_dir)
        return None
    return found


def cmd_validate(args, out=None):
    out = out or sys.stdout
    found = _app_or_usage(args.app)
    if found is None:
        return EXIT_USAGE
    app_dir, spec_path = found
    report, _, _ = validate_app(app_dir, spec_path, _options(args))
    if args.json:
        data = report.as_dict()
        data["spec"] = str(spec_path)
        out.write(json.dumps(data, indent=2) + "\n")
    else:
        out.write(report.render("Validating %s" % spec_path) + "\n")
    return EXIT_INVALID if report.errors else EXIT_OK


def cmd_build(args, out=None):
    found = _app_or_usage(args.app)
    if found is None:
        return EXIT_USAGE
    app_dir, spec_path = found
    return build_app(app_dir, spec_path, _options(args), clipboard=args.clipboard, out=out,
                     tier=getattr(args, "tier", "standard"))


def cmd_release(args, out=None):
    found = _app_or_usage(args.app)
    if found is None:
        return EXIT_USAGE
    app_dir, spec_path = found
    return release_app(app_dir, spec_path, _options(args), args.version, notes=args.notes or "",
                       force=args.force, tier=args.tier, out=out)


def cmd_verify(args, out=None):
    out = out or sys.stdout
    found = _app_or_usage(args.app)
    if found is None:
        return EXIT_USAGE
    app_dir, _ = found
    tool = Path(args.tools_dir or TOOL_DIR) / "verify_dxp.py"
    if not tool.is_file():
        sys.stderr.write("verify_dxp.py is not available, so the saved DXP cannot be verified yet\n")
        return EXIT_USAGE
    out.flush()
    proc = subprocess.run([sys.executable, str(tool), "check", str(app_dir)])
    return proc.returncode


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dxpgen.py", description="App spec -> validated, resolved -> one IronPython builder for Spotfire "
                                      "Analyst. Exit codes: 0 ok, 1 validation errors, 2 usage.")
    sub = parser.add_subparsers(dest="command", metavar="{new,validate,build,release,verify}")

    def tool_options(p, with_checks=True):
        if with_checks:
            p.add_argument("--no-lint", action="store_true",
                           help="do not run lint_ipy.py (build: nor ipy_parse.ps1 and sfapi.py on the builder)")
            p.add_argument("--no-sanitize", action="store_true",
                           help="do not check text-area HTML against Spotfire's sanitizer")
        p.add_argument("--tools-dir", help="folder with lint_ipy.py / ipy_parse.ps1 / sfapi.py / "
                                           "verify_dxp.py (default: this folder)")

    p_new = sub.add_parser("new", help="scaffold $DXP_WORKSPACE/apps/<AppSlug>/")
    p_new.add_argument("slug", metavar="AppSlug")
    p_new.add_argument("--name", help="analysis name (default: from the slug)")
    p_new.add_argument("--workspace", help="workspace folder (default: $DXP_WORKSPACE)")
    p_val = sub.add_parser("validate", help="validate an app spec")
    p_val.add_argument("app", help="app folder, spec.json, or app slug")
    p_val.add_argument("--json", action="store_true", help="machine-readable output")
    tool_options(p_val)
    p_build = sub.add_parser("build", help="validate, resolve and write build/build_<AppSlug>_<tier>.py")
    p_build.add_argument("app", help="app folder, spec.json, or app slug")
    p_build.add_argument("--tier", choices=BUILD_TIERS, default="standard",
                         help="standard (default: the standard engine, full styling), quick (fonts, red "
                              "negatives), compact (quickest: no styling), report (exception: standard + "
                              "step report, MANUAL-STEPS, snapshots), slim (exception: the trimmed library, "
                              "slim_builder.py), full (the whole library, about 450 KB; library development "
                              "only)")
    p_build.add_argument("--clipboard", action="store_true", help="copy the builder to the Windows clipboard")
    tool_options(p_build)
    p_rel = sub.add_parser("release", help="copy the app's runtime files to <app>/versions/<version>, generate "
                                           "the builders from that copy and record it in versions/README.md")
    p_rel.add_argument("app", help="app folder, spec.json, or app slug")
    p_rel.add_argument("--version", required=True, help="the version folder name: v2, v2.1, v2.1.3 (optionally "
                                                        "-rc1)")
    p_rel.add_argument("--notes", help="one line for the versions/README.md table")
    p_rel.add_argument("--force", action="store_true", help="regenerate an existing version folder that holds "
                                                            "no saved DXP (copies over it, deletes nothing)")
    p_rel.add_argument("--tier", choices=t3.TIERS, default="standard", help="standard (default), quick, compact "
                                                                           "or report")
    tool_options(p_rel)
    p_verify = sub.add_parser("verify", help="run verify_dxp.py check on the app")
    p_verify.add_argument("app", help="app folder, spec.json, or app slug")
    tool_options(p_verify, with_checks=False)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    handlers = {"new": cmd_new, "validate": cmd_validate, "build": cmd_build, "release": cmd_release,
                "verify": cmd_verify}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
