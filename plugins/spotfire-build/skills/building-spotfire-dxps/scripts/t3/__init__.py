"""Standard-engine generator: resolved spec -> HOME, STYLE, APP + engine parts -> one builder.

    import t3
    result = t3.generate(resolved, raw_spec, app_dir, tier, columns_of=..., meta=...)
    result.text          the builder (IronPython 3.4, lines <= 79, ASCII)
    result.problems      [(path, message)] - spec features the standard engine cannot build yet
    result.notes         what it leaves out on purpose (table descriptions, ...)
    result.manual        [[what, how], ...] - what the public API cannot build (t3/_manual.py)
    result.parts         engine parts included, result.members() -> sfapi checks

Tiers: standard (the default), quick (fonts and red negatives), compact (data, visuals, colors,
layout, save), report (standard + engine/report.py). Text-area controls, property triggers, action
mods and the document theme have no public API: the builder leaves a marker for each control and
lists every such item in APP "manual" (TODO lines in the build log). Visualization mods (top-level
vizMods, visual type mod with layers: scripts/t3/mod.py) are built when the mod is embedded,
installed or pinned. Engine parts live in scripts/engine (references/engine.md); the per-kind spec ->
APP converters are the modules of this package whose names do not start with "_" (KIND, SPEC_TYPES,
STYLE_KEYS, HANDLED, convert()).
"""
import copy
import importlib
import ntpath
import os
from pathlib import Path

from . import _filters, _house, _literal, _manual, _sections
from ._assemble import Imports, Part, collapse_blank_lines, drop_docstrings, used_names, wrap_comment
from ._common import (COMMON_STYLE_KEYS, LEVELS, NOT_YET, REF_STYLE_KEYS, Context, blank,
                      check_style_value)

T3_DIR = Path(__file__).resolve().parent
ENGINE_DIR = T3_DIR.parent / "engine"
TIERS = ("standard", "quick", "compact", "report")
TIER_TEXT = {
    "standard": "standard tier: the standard engine with full styling (fonts, number formats, "
                "widths, red negatives, reference lines)",
    "quick": "quick tier: fonts and red negatives",
    "compact": "compact tier (quickest): data, visuals, colors and layout; no font styling",
    "report": "report tier (exception): the standard engine plus a step report, MANUAL-STEPS and "
              "snapshots",
}
SECTION_LABELS = {"relations": "a relation", "filteringSchemes": "a named filtering scheme"}
# Feature parts (engine/features/<name>.py) in builder order, and the parts each feature needs. A part
# is included when the app uses its feature; "# @feature <name>" blocks in core and the builders are
# kept for the features in use (Result.features). modload finds the visualization mods (vizMods, the
# "mod" kind).
FEATURE_PARTS = ("guard", "preflight", "pathfree", "properties", "markings", "datafunctions",
                 "scripts", "controls", "modload", "textjs", "links", "settings", "legend", "coloring",
                 "filterpanel")
FEATURE_NEEDS = {"dataFunctions": ("datafunctions",), "vizMods": ("modload",),
                 "legendHide": ("legend",), "cellColoring": ("coloring",),
                 "kpiColoring": ("coloring",), "pathFree": ("pathfree",),
                 "filterLayout": ("filterpanel",)}
# Kinds Spotfire's VisualCollection.AddNew leaves without the default marking (seen in live builds in
# Analyst 15.0: KPI charts and cross tables persisted with no marking): featured apps mark them
# explicitly.
UNMARKED_KINDS = ("kpi", "cross")
# Kinds whose builders the report tier's manual fixes know by a feature flag of the same name.
KIND_FLAGS = ("scatter", "map")
COMMON_KEYS = ("id", "type", "title", "showTitle", "description", "table", "marking", "legend",
               "limitByMarkings", "emptyMarkingBehavior", "useFiltering", "settings", "postScript",
               "fittingModels", "actionTriggers")
UNSET = {"limitExpression": None, "coloring": None, "referenceLayers": [], "fittingModels": [],
         "limitByMarkings": [], "emptyMarkingBehavior": "ShowAll", "useFiltering": True,
         "settings": {}, "postScript": None, "actionTriggers": []}

_REGISTRY = {}


# ---------------------------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------------------------
def registry():
    """{spec visual type: converter module}, discovered from scripts/t3/<kind>.py."""
    if not _REGISTRY:
        for path in sorted(T3_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod = importlib.import_module(__name__ + "." + path.stem)
            for vtype in getattr(mod, "SPEC_TYPES", ()):
                _REGISTRY[vtype] = mod
    return _REGISTRY


def kinds():
    """{engine kind: converter module}."""
    return dict((m.KIND, m) for m in registry().values())


def builder_path(kind):
    return ENGINE_DIR / "builders" / (kind + ".py")


def style_keys(kind):
    """{key: (check, tier)} accepted in app.style.visual.<kind> ("ref" = reference lines)."""
    if kind == "ref":
        return dict((k, (c, t)) for k, c, t in REF_STYLE_KEYS)
    mod = kinds().get(kind)
    out = dict((k, (c, t)) for k, c, t in COMMON_STYLE_KEYS)
    if mod is not None:
        out.update((k, (c, t)) for k, c, t in mod.STYLE_KEYS)
    if kind == "text":
        out.pop("legend", None)
    return out


def visual_style_keys(vtype):
    """{key: check} a spec visual of this type may carry as per-visual style keys."""
    mod = registry().get(vtype)
    if mod is None:
        return {}
    return dict((k, c) for k, c, _ in mod.STYLE_KEYS)


def kind_of(vtype):
    mod = registry().get(vtype)
    return mod.KIND if mod is not None else None


# ---------------------------------------------------------------------------------------------
# app.style validation (dxpgen Validator calls this; issues are (level, path, message))
# ---------------------------------------------------------------------------------------------
def validate_style(style, path="app.style"):
    issues = []
    if not isinstance(style, dict):
        return [("error", path, "must be an object (palette, font, text, negative, formats, visual)")]
    known = ("palette", "font", "text", "negative", "formats", "visual")
    for key in style:
        if key not in known:
            issues.append(("warning", path + "." + key, "unknown field '%s' (known: %s); the builder ignores "
                           "it" % (key, ", ".join(known))))
    palette = style.get("palette")
    names = dict(_house.PALETTE)
    if palette is not None:
        if not isinstance(palette, dict):
            issues.append(("error", path + ".palette", "must be an object of name -> '#RRGGBB'"))
        else:
            for name, value in palette.items():
                problem = check_style_value("color", value)
                if problem or value is None or str(value).startswith("@"):
                    issues.append(("error", path + ".palette." + name, "must be '#RRGGBB'"))
                if not name.replace("_", "").isalnum():
                    issues.append(("error", path + ".palette." + name, "palette names use letters, digits "
                                   "and '_'"))
            names.update(palette)
    if style.get("font") is not None and not (isinstance(style["font"], str) and style["font"].strip()):
        issues.append(("error", path + ".font", "must be a font family name"))
    for key in ("text", "negative"):
        if style.get(key) is not None:
            problem = check_style_value("color", style[key], names)
            if problem:
                issues.append(("error", path + "." + key, problem))
    formats = style.get("formats")
    if formats is not None:
        if not isinstance(formats, dict):
            issues.append(("error", path + ".formats", "must be an object of name -> format string"))
        else:
            for name, value in formats.items():
                if not isinstance(value, str) or not value:
                    issues.append(("error", path + ".formats." + name, "must be a format string"))
    visual = style.get("visual")
    if visual is not None:
        if not isinstance(visual, dict):
            issues.append(("error", path + ".visual", "must be an object of engine kind -> defaults"))
        else:
            valid = sorted(kinds()) + ["ref"]
            for kind, defaults in visual.items():
                vp = path + ".visual." + kind
                if kind not in valid:
                    issues.append(("warning", vp, "unknown engine kind '%s' (%s); the builder ignores it"
                                   % (kind, ", ".join(valid))))
                    continue
                if not isinstance(defaults, dict):
                    issues.append(("error", vp, "must be an object of style key -> value"))
                    continue
                accepted = style_keys(kind)
                for key, value in defaults.items():
                    if key not in accepted:
                        issues.append(("warning", vp + "." + key, "unknown style key '%s' for %s (%s); the "
                                       "builder ignores it" % (key, kind, ", ".join(sorted(accepted)))))
                        continue
                    problem = check_style_value(accepted[key][0], value, names)
                    if problem:
                        issues.append(("error", vp + "." + key, problem))
    return issues


def check_visual_style(vtype, key, value, palette_names=None):
    """Problem text for a per-visual style key, or None."""
    check = visual_style_keys(vtype).get(key)
    return check_style_value(check, value, palette_names) if check else None


# ---------------------------------------------------------------------------------------------
# STYLE
# ---------------------------------------------------------------------------------------------
def compose_style(resolved, problems):
    """The full STYLE (house + app.style), before the tier trims it. app.theme is a manual step
    (t3/_manual.py): the public API cannot set the document theme."""
    app = resolved.get("app") or {}
    spec = app.get("style") if isinstance(app.get("style"), dict) else {}
    palette = dict(spec.get("palette") or {})
    for name, value in _house.PALETTE.items():
        palette.setdefault(name, value)
    formats = dict(spec.get("formats") or {})
    for name, value in _house.FORMATS.items():
        formats.setdefault(name, value)
    visual = {}
    for kind, defaults in (spec.get("visual") or {}).items():
        if isinstance(defaults, dict):
            visual[kind] = dict(defaults)
    for kind, defaults in _house.VISUAL.items():
        merged = visual.setdefault(kind, {})
        for key, value in defaults.items():
            merged.setdefault(key, value)
    return {"palette": palette, "font": spec.get("font") or _house.FONT,
            "text": spec.get("text") or _house.TEXT, "negative": spec.get("negative") or _house.NEGATIVE,
            "formats": formats, "visual": visual}, set(spec.get("palette") or {}), set(spec.get("formats") or {})


def _palette_refs(node, found):
    if isinstance(node, dict):
        for value in node.values():
            _palette_refs(value, found)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _palette_refs(value, found)
    elif isinstance(node, str) and node.startswith("@"):
        found.add(node[1:])


def _format_refs(app, style):
    found = set()
    for entry in app.get("tables", []) + app.get("dfTables", []):
        found.update(entry[1].keys())
    for page in app.get("pages", []):
        for vs in page.get("visuals", []):
            for item in vs.get("kpis", []):
                if item[2]:
                    found.add(item[2])
            if vs.get("yFormat"):
                found.add(vs["yFormat"])
    for defaults in style.get("visual", {}).values():
        if defaults.get("yFormat"):
            found.add(defaults["yFormat"])
    return found


def trim_style(style, tier, used_kinds, app, spec_palette, spec_formats):
    """STYLE for one tier: only what its code reads, only kinds the app uses; house palette and
    format entries (and, below standard, the spec's own) only when referenced."""
    level = LEVELS[tier]
    out = {}
    visual = {}
    wanted = set(used_kinds)
    if wanted & set(("line", "bar", "scatter")):
        wanted.add("ref")
    for kind, defaults in style["visual"].items():
        if kind not in wanted:
            continue
        accepted = style_keys(kind)
        kept = dict((k, v) for k, v in defaults.items()
                    if k in accepted and LEVELS[accepted[k][1]] <= level)
        if kept:
            visual[kind] = kept
    body = {"text": style["text"], "visual": visual}
    if level >= LEVELS["quick"]:
        body.update(font=style["font"], negative=style["negative"])
    refs = set()
    _palette_refs(body, refs)
    _palette_refs(app, refs)
    keep_spec = level >= LEVELS["standard"]
    out["palette"] = dict((k, v) for k, v in style["palette"].items()
                          if k in refs or (keep_spec and k in spec_palette))
    if level >= LEVELS["quick"]:
        out["font"] = style["font"]
    out["text"] = style["text"]
    if level >= LEVELS["quick"]:
        out["negative"] = style["negative"]
    fmt_refs = _format_refs(app, body)
    out["formats"] = dict((k, v) for k, v in style["formats"].items()
                          if k in fmt_refs or (keep_spec and k in spec_formats))
    out["visual"] = visual
    return out


# ---------------------------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------------------------
def _default_marking(resolved):
    marks = [m for m in resolved.get("markings") or [] if isinstance(m, dict) and m.get("name")]
    for m in marks:
        if m.get("default") is True:
            return m
    return marks[0] if marks else None


def _tier_file(output, tier):
    """build/<name>.dxp -> build/<name> <tier>.dxp."""
    stem, ext = os.path.splitext(output)
    return stem + " " + tier + (ext or ".dxp")


def _win(path):
    return str(path).replace("/", "\\")


def convert_visual(v, rv, path, ctx, marking_name):
    vtype = v.get("type")
    mod = registry().get(vtype)
    if mod is None:
        ctx.unsupported(path, "visual type '%s'" % vtype)
        return None
    kind = mod.KIND
    if not builder_path(kind).is_file():
        ctx.unsupported(path, "visual type '%s' (engine/builders/%s.py is missing)" % (vtype, kind))
        return None
    out = {"id": v["id"], "type": kind, "title": v.get("title") or ""}
    show = v.get("showTitle", True)
    if show != ctx.default(kind, "showTitle", True):
        out["showTitle"] = show
    for key in ("postScript", "fittingModels"):
        if not blank(v.get(key)) and key not in mod.HANDLED:      # fittingModels: line, bar, scatter
            ctx.unsupported(path + "." + key, "'%s' on a %s" % (key, vtype))
    if v.get("useFiltering", True) is False and "useFiltering" not in mod.HANDLED:     # mod: its own
        ctx.unsupported(path + ".useFiltering", "useFiltering false")
    if v.get("description"):
        ctx.note("visual descriptions")
    body = mod.convert(v, rv, path, ctx)
    lines = body.pop("refs", None)
    out.update(body)
    for key, check, tier in mod.STYLE_KEYS:
        # a style key that is also a SPEC field of the type (totals, lineWidth) is the converter's
        if key in rv and key not in out and key not in mod.HANDLED and ctx.has(tier):
            value = rv[key]
            if check == "format":
                value = ctx.format_name(value)
            elif check == "color":
                value = ctx.color(value, path + "." + key)
            if value != ctx.default(kind, key, object()):
                out[key] = value
    if kind != "text":
        legend = v.get("legend")
        visible = legend.get("visible", True) if isinstance(legend, dict) else (
            legend if isinstance(legend, bool) else True)
        if visible != ctx.default(kind, "legend", True):
            out["legend"] = visible
        hide = legend.get("hide") if isinstance(legend, dict) else None
        if hide and kind == "map":
            # every map data layer has its own legend; the map's holds only title, description, trellis
            layer_kinds = [k for k in hide if k != "trellis"]
            if layer_kinds:
                out["layerLegendHide"] = layer_kinds          # engine/builders/map.py map_layer_legends
            hide = [k for k in hide if k == "trellis"]
        if hide:
            out["legendHide"] = list(hide)                     # engine feature legendHide
    if lines:
        out["refs"] = lines
    if kind == "map":
        links = visual_links(v, marking_name)    # limits and the limit expression are on the layers
        links.pop("limits", None)
        links.pop("empty", None)
        out.update(links)
    elif kind != "text":
        out.update(visual_links(v, marking_name))
    if isinstance(v.get("settings"), dict) and v["settings"]:
        out["settings"] = dict(v["settings"])     # engine/features/settings.py
    handled = set(COMMON_KEYS) | set(mod.HANDLED) | set(k for k, _, _ in mod.STYLE_KEYS)
    for key, value in v.items():
        if key in handled or blank(value) or UNSET.get(key, object()) == value:
            continue
        ctx.unsupported(path + "." + key, "'%s' on a %s" % (key, vtype))
    return out


def visual_links(v, marking_name):
    """marking (name, or None = not markable; written only when it is not the default marking),
    limits (limitByMarkings), empty (emptyMarkingBehavior, always written with limits: a live build on
    Analyst 15.0 showed an empty table where ShowAll was left to the default): engine/features/links.py."""
    out = {}
    if "marking" in v and v.get("marking") != marking_name:
        out["marking"] = v.get("marking")
    if v.get("limitByMarkings"):
        out["limits"] = list(v["limitByMarkings"])
        out["empty"] = v.get("emptyMarkingBehavior") or "ShowAll"
    return out


def convert_layout(node):
    if not isinstance(node, dict) or not node:
        return None
    if "visual" in node:
        out = {"visual": node["visual"]}
    else:
        kind = "row" if "row" in node else "column"
        out = {kind: [convert_layout(child) for child in node.get(kind) or []]}
    weight = node.get("weight")
    if weight is not None and weight != 1:
        out["weight"] = weight
    return out


def build_app(resolved, raw, app_dir, tier, ctx):
    """APP for one tier."""
    app = resolved.get("app") or {}
    app_dir = Path(app_dir)
    output = app.get("output") or ("build/" + app.get("name", "analysis") + ".dxp")
    out_file = _tier_file(output, tier)
    suffix = tier
    out_full = Path(os.path.normpath(os.path.join(str(app_dir), out_file)))
    log_full = out_full.parent / ("build-log-" + suffix + ".txt")
    tables = [t for t in resolved.get("tables") or [] if isinstance(t, dict)]
    pages = [p for p in resolved.get("pages") or [] if isinstance(p, dict)]
    out = {"name": app.get("name", ""), "output": _rel(out_full, app_dir), "log": _rel(log_full, app_dir),
           "description": app.get("description") or "", "keywords": list(app.get("keywords") or [])}
    out["defaultTable"] = ctx.default_table
    mark = _default_marking(resolved)
    out["marking"] = [mark["name"], ctx.color(mark.get("color"), "markings")] if mark else ["Marking", None]
    out["activePage"] = resolved.get("activePage") or (pages[0].get("title") if pages else None)
    nav = app.get("pageNavigation") or "Tabs"
    if nav != "Tabs":
        out["navigation"] = nav
    if tier == "report":
        snaps = app.get("snapshots") or {}
        out["tag"] = suffix
        out["snapshots"] = ([int(snaps.get("width", 1600)), int(snaps.get("height", 900))]
                            if snaps.get("enabled", True) else None)
    extra = _sections.markings(resolved, mark, ctx)
    if extra:
        out = _insert_after(out, "marking", "markings", extra)
    entries = [_table_entry(t, n, app_dir, ctx) for n, t in enumerate(tables)]
    out["tables"] = [e[:-1] for e in entries if not e[-1]]
    props = _sections.properties(resolved, ctx)
    if props:
        out["properties"] = props
    functions = _sections.data_functions(resolved, raw, app_dir, ctx)
    if functions:
        out["dataFunctions"] = functions
        out["dfTables"] = [e[:2] for e in entries if e[-1] and e[1]]
    elif [e for e in entries if e[-1]]:
        ctx.unsupported("tables", "a dataFunction table without data functions")
    scripts = _sections.scripts(resolved, raw, app_dir, ctx)
    if scripts:
        out["scripts"] = scripts
    viz = _sections.viz_mods(resolved, app_dir, ctx)
    if viz:
        out["vizMods"] = viz                           # engine feature vizMods
    marking_name = mark["name"] if mark else "Marking"
    ctx.marking_name = marking_name                    # map layers get the visual's marking
    filter_pages, filter_types = _filters.app_keys(resolved)
    if filter_types:
        out["filterTypes"] = filter_types              # engine feature filterLayout
    raw_pages = raw.get("pages") if isinstance(raw.get("pages"), list) else []
    out["pages"] = []
    for i, p in enumerate(pages):
        rp = raw_pages[i] if i < len(raw_pages) and isinstance(raw_pages[i], dict) else {}
        entry = _page_entry(p, rp, "pages[%d]" % i, ctx, marking_name)
        if p.get("title") in filter_pages:
            entry["filters"] = filter_pages[p.get("title")]     # engine feature filterLayout
        out["pages"].append(entry)
    manual = _manual.steps(resolved, raw)
    if manual:
        out["manual"] = manual                         # engine feature manual: TODO lines in the log
    return out, out_full, log_full


def _insert_after(d, after, key, value):
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == after:
            out[key] = value
    return out


def _rel(full, app_dir):
    try:
        return _win(os.path.relpath(str(full), str(app_dir)))
    except ValueError:                 # another drive
        return _win(full)


def _table_entry(t, n, app_dir, ctx):
    """[name, {format: [columns]}, (file), is-data-function-table]."""
    path = "tables[%d]" % n
    name = t.get("name")
    src = t.get("source") if isinstance(t.get("source"), dict) else {}
    produced = src.get("type") == "dataFunction"
    if src.get("type") != "sbdf" and not produced:
        ctx.unsupported(path + ".source", "a '%s' table source" % src.get("type"))
    for key, what in (("calculatedColumns", "calculated columns"), ("hierarchies", "hierarchies"),
                      ("settings", "table settings")):
        if not blank(t.get(key)):
            ctx.unsupported(path + "." + key, what)
    if t.get("embed") is False and not produced:
        ctx.unsupported(path + ".embed", "a linked (not embedded) table")
    if t.get("description"):
        ctx.note("table descriptions")
    groups = {}
    for cname, cspec in (t.get("columns") or {}).items():
        if not isinstance(cspec, dict):
            continue
        if not blank(cspec.get("settings")):
            ctx.unsupported("%s.columns.%s.settings" % (path, cname), "column settings")
        if cspec.get("description"):
            ctx.note("column descriptions")
        if cspec.get("format"):
            groups.setdefault(ctx.format_name(cspec["format"]), []).append(cname)
    entry = [name, groups]
    file_path = src.get("path")
    if file_path and not produced:
        default = os.path.normcase(os.path.normpath(os.path.join(str(app_dir), "data", name + ".sbdf")))
        if os.path.normcase(os.path.normpath(file_path)) != default:
            entry.append(_rel(Path(file_path), app_dir))
    return entry + [produced]


def _page_entry(p, rp, path, ctx, marking_name):
    out = {"title": p.get("title")}
    if p.get("filterPanel"):
        out["filterPanel"] = True
    if p.get("detailsOnDemand"):
        out["detailsOnDemand"] = True
    if p.get("visible") is False:
        out["visible"] = False         # engine feature hiddenPages (public Page.Visible, api 10.7)
    if p.get("filteringScheme"):
        ctx.unsupported(path + ".filteringScheme", "a page filtering scheme")
    raw_visuals = rp.get("visuals") if isinstance(rp.get("visuals"), list) else []
    visuals = []
    for j, v in enumerate(p.get("visuals") or []):
        rv = raw_visuals[j] if j < len(raw_visuals) and isinstance(raw_visuals[j], dict) else {}
        converted = convert_visual(v, rv, "%s.visuals[%d]" % (path, j), ctx, marking_name)
        if converted is not None:
            visuals.append(converted)
    out["visuals"] = visuals
    layout = convert_layout(p.get("layout"))
    if layout:
        out["layout"] = layout
    return out


def check_sections(resolved, ctx):
    for key, label in SECTION_LABELS.items():
        if not blank(resolved.get(key)):
            ctx.unsupported(key, label)
    app = resolved.get("app") or {}
    if app.get("canvas") is not None:
        ctx.unsupported("app.canvas", "a fixed canvas size")


# ---------------------------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------------------------
class Result(object):
    def __init__(self):
        self.text = ""
        self.problems = []
        self.notes = []
        self.parts = []
        self.features = set()
        self.manual = []             # [[what, how], ...]: what the public API cannot build
        self.home = self.style = self.app = None
        self.output = self.log = None

    def members(self):
        """(public specs, setter specs) of the included engine parts."""
        api, setters = [], []
        for part in self.parts:
            for src, dst in ((part.api, api), (part.set, setters)):
                for spec in src:
                    if spec not in dst:
                        dst.append(spec)
        return api, setters


def generate(resolved, raw, app_dir, tier, columns_of=None, meta=None):
    """Builder text for one tier (Result.problems non-empty = the spec needs --tier slim)."""
    if tier not in TIERS:
        raise ValueError("unknown tier '%s' (%s)" % (tier, ", ".join(TIERS)))
    app_dir = Path(app_dir).resolve()            # the spelling resolve_spec used for the data paths
    result = Result()
    style_problems = []
    style, spec_palette, spec_formats = compose_style(resolved, style_problems)
    ctx = Context(resolved, raw, app_dir, tier, style, columns_of)
    ctx.problems.extend(style_problems)
    check_sections(resolved, ctx)
    app, out_full, log_full = build_app(resolved, raw, app_dir, tier, ctx)
    result.manual = list(app.get("manual") or [])
    result.problems = ctx.problems
    result.notes = ctx.notes
    result.output, result.log = out_full, log_full
    if ctx.problems:
        return result
    used = []
    for page in app["pages"]:
        for vs in page["visuals"]:
            if vs["type"] not in used:
                used.append(vs["type"])
    result.home = str(app_dir)
    features = features_of(app)
    if features and mark_kpi_charts(app):
        features = features_of(app)
    if "preflight" in features:
        app = preflight_keys(app, app_dir, meta or {})
    result.style = trim_style(style, tier, used, app, spec_palette, spec_formats)
    result.app = app
    result.features = features
    result.parts = engine_parts(used, tier, result.features)
    result.text = assemble(result, tier, meta or {})
    return result


def files_read(app, app_dir):
    """Every file the builder reads from HOME at run time, relative to HOME (Windows separators), each
    once, in build order: sbdf tables, data-function code, IronPython scripts, each visualization mod's
    manifest and the files it lists that exist now, text-area HTML and JavaScript files. Data the
    builder carries (inline code) is not a file at run time."""
    out = []

    def add(rel):
        rel = ntpath.normpath(rel)
        if rel not in out:
            out.append(rel)
    for entry in app.get("tables", []):
        add(entry[2] if len(entry) > 2 else ntpath.join("data", entry[0] + ".sbdf"))
    for d in app.get("dataFunctions", []):
        if d.get("file"):
            add(ntpath.join("datafunctions", d["file"]))
    for s in app.get("scripts", []):
        if s.get("file"):
            add(ntpath.join("scripts", s["file"]))
    for entry in app.get("vizMods", []):
        folder = entry[1] if len(entry) > 1 else ""
        manifest = ntpath.join(folder, "mod-manifest.json") if folder else "mod-manifest.json"
        add(manifest)
        man = _sections.read_manifest(app_dir, folder.replace("\\", "/")) if folder else None
        for name in _sections.manifest_files(man):
            rel = ntpath.join(folder, name.replace("/", "\\")) if folder else name.replace("/", "\\")
            if os.path.isfile(os.path.join(str(app_dir), *ntpath.normpath(rel).split("\\"))):
                add(rel)
    for page in app.get("pages", []):
        for vs in page.get("visuals", []):
            if vs.get("html"):
                add(ntpath.join("html", vs["html"]))
            for js in vs.get("js", []):
                if len(js) > 1 and js[1]:
                    add(js[1])
    return out


def preflight_keys(app, app_dir, meta):
    """APP with the preflight keys after "log": spec (12 hex digits of spec.json's sha256), release
    (dxpgen release only) and files (files_read)."""
    keys = [("spec", (meta.get("spec_sha") or "0" * 12)[:12])]
    if meta.get("release"):
        keys.append(("release", meta["release"]))
    keys.append(("files", files_read(app, app_dir)))
    out = {}
    for k, v in app.items():
        out[k] = v
        if k == "log":
            out.update(keys)
    return out


def mark_kpi_charts(app):
    """KPI charts and cross tables without their own marking get the default marking explicitly (APP
    visual "marking", feature links: a KPI chart and each tile, a cross table). Spotfire's
    VisualCollection.AddNew gives the other charts and tables the default marking but leaves these
    kinds (UNMARKED_KINDS) without one (seen in live builds in Analyst 15.0: VisualizationData.Marking
    persisted as null on KPI charts while the line and bar charts next to them had "Marking", and cross
    tables unmarked). A spec "marking" equal to the
    default marking name is dropped by visual_links and comes back here, so an explicit default marking
    works too. Called only for apps with features, so the proven builders of apps without features stay
    byte-identical (their KPI charts and cross tables keep the gap). True when a visual changed."""
    changed = False
    for page in app.get("pages", []):
        for vs in page.get("visuals", []):
            if vs["type"] in UNMARKED_KINDS and "marking" not in vs:
                vs["marking"] = app["marking"][0]
                changed = True
    return changed


def features_of(app):
    """Features the APP uses: they select the feature parts and the "# @feature" blocks kept."""
    found = set()
    for key in ("properties", "markings", "dataFunctions", "scripts"):
        if app.get(key):
            found.add(key)
    if app.get("manual"):
        found.add("manual")                            # engine/core.py: TODO lines in the log
    if app.get("vizMods"):
        found.add("vizMods")                           # engine/features/modload.py, builders/mod.py
    for d in app.get("dataFunctions", []):
        if [i for i in d["in"] if isinstance(i[2], dict) and i[2].get("marking")]:
            found.add("markedInputs")
    if app.get("filterTypes"):
        found.add("filterLayout")                      # engine/features/filterpanel.py
    for page in app.get("pages", []):
        if page.get("visible") is False:
            found.add("hiddenPages")                   # engine/core.py hide_page
        if "filters" in page:
            found.add("filterLayout")
        for vs in page.get("visuals", []):
            if vs.get("controls"):
                found.add("controls")                  # engine/features/controls.py: markers
            if vs.get("js"):
                found.add("textjs")
            if vs.get("legendHide"):
                found.add("legendHide")
            if vs.get("layerLegendHide"):
                found.add("layerLegends")             # engine/builders/map.py map_layer_legends
            if [k for k in ("marking", "limits", "empty") if k in vs] or (
                    vs["type"] in ("table", "kpi") and "where" in vs):
                found.add("links")
            if vs.get("yLog"):
                found.add("log")
            if vs.get("horizontal") or vs.get("sort"):
                found.add("barLayout")
            if vs.get("settings"):
                found.add("settings")
            found.update(visual_features(vs))
    if found - set(("manual",)):
        # the refused-save re-check and build session switch (guard) and the preflight (every file the
        # builder reads exists in HOME before the first change; the spec hash on the log's first line):
        # every featured app (manual steps alone keep the plain builder)
        found.update(("guard", "preflight"))
        if app.get("tables"):
            # sbdf tables loaded by file name, so the DXP keeps no local folder (features/pathfree.py);
            # apps without features keep their proven builders (and the full path)
            found.add("pathFree")
    return found


def colorings_of(vs):
    """Every APP coloring object of a visual: chart color axis, cells, KPI tiles, map layers."""
    out = [vs["coloring"]] if isinstance(vs.get("coloring"), dict) else []
    out += [c for _, c in vs.get("cellColors", [])]
    out += [k[3] for k in vs.get("kpis", []) if len(k) > 3 and k[3]]
    out += [layer["coloring"] for layer in vs.get("layers", []) if layer.get("coloring")]
    return out


def visual_features(vs):
    """Coloring, axis-range, fitting and trellis features (engine/features/coloring.py, _chart.py
    blocks) and the kind flags of the scatter and map builders (report-tier manual fixes)."""
    found = set()
    if vs["type"] in KIND_FLAGS:
        found.update((vs["type"], "markers"))
    colorings = colorings_of(vs)
    if colorings:
        found.add("coloring")
    if vs.get("cellColors"):
        found.add("cellColoring")
    if [k for k in vs.get("kpis", []) if len(k) > 3 and k[3]]:
        found.add("kpiColoring")
    if [c for c in colorings if c.get("settings")] or [layer for layer in vs.get("layers", [])
                                                       if layer.get("settings")]:
        found.add("settings")
    if [k for k in ("yMax", "xMin", "xMax") if k in vs]:
        found.add("range")
    if vs.get("curves"):
        found.add("fitting")
    if vs.get("trellis") or vs.get("yEach"):
        found.add("trellis")                           # engine/builders/_chart.py trellis, y_each
    return found


def feature_part_names(features):
    """engine/features parts for these features, dependencies included, in FEATURE_PARTS order."""
    wanted = set(features)
    for feature in list(features):
        wanted.update(FEATURE_NEEDS.get(feature, ()))
    return [name for name in FEATURE_PARTS if name in wanted]


def engine_parts(kinds_used, tier, features=frozenset()):
    """core, the feature parts, the shared parts and builders the app's kinds need (first use first),
    report (report)."""
    features = set(features)
    parts = [Part("core", ENGINE_DIR / "core.py", _read(ENGINE_DIR / "core.py"), tier, features)]
    for name in feature_part_names(features):
        path = ENGINE_DIR / "features" / (name + ".py")
        parts.append(Part(name, path, _read(path), tier, features))
    seen = set()
    for kind in kinds_used:
        path = builder_path(kind)
        part = Part(kind, path, _read(path), tier, features)
        for shared in part.uses:
            if shared not in seen:
                seen.add(shared)
                spath = ENGINE_DIR / "builders" / (shared + ".py")
                parts.append(Part(shared, spath, _read(spath), tier, features))
        parts.append(part)
    if tier == "report":
        parts.append(Part("report", ENGINE_DIR / "report.py", _read(ENGINE_DIR / "report.py"), tier,
                          features))
    return parts


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def header_lines(result, tier, meta):
    app = result.app
    name = app["name"]
    rule = "# " + "=" * 69
    out_rel = app["output"]
    log_rel = app["log"]
    lines = [rule]
    lines += wrap_comment("%s - %s builder, Spotfire Analyst 15.0, IronPython 3.4. Generated by "
                          "dxpgen.py (building-spotfire-dxps skill) from spec.json %s on %s: %s."
                          % (name, tier, meta.get("spec_sha", "")[:12], meta.get("generated", "")[:10],
                             TIER_TEXT[tier].split(": ", 1)[-1]))
    if meta.get("release"):
        lines += wrap_comment("Release %s: HOME is the version folder versions\\%s, which holds every file "
                              "this builder reads and receives the saved DXP. Paste only the builder of "
                              "the version you want (versions\\README.md)."
                              % (meta["release"], meta["release"]))
    lines += [
        "#",
        "# Run it in a NEW analysis with any starter data loaded:",
        "#   Edit > Document Properties > Scripts > New > IronPython 3 >",
        "#   untick \"Execute in transaction\" > paste > Run Script > Cancel.",
        "# (Inside a transaction Spotfire refuses the save; Cancel keeps this",
        "# script out of the analysis.)",
    ]
    if "guard" in result.features:
        lines += wrap_comment("After the save the open analysis shows a 'Build Session' page and is "
                              "linked to a scratch file in build\\session: close it without saving "
                              "and open the saved DXP.")
    pages = len(app["pages"])
    lines += wrap_comment("It loads the data (embedded), builds %d page(s), removes the starter "
                          "table and page, and saves %s. Each item runs on its own, so one failure "
                          "never stops the build; failures go to %s."
                          % (pages, out_rel, log_rel))
    if result.manual:
        lines += wrap_comment("%d item(s) have no public API (text-area controls, property triggers, "
                              "action mods, the theme): the log lists them as TODO lines and "
                              "MANUAL-STEPS-%s.md says how to add each by hand."
                              % (len(result.manual), app.get("tag") or tier))
    if tier == "report":
        tag = app["tag"]
        lines += wrap_comment("Report tier: every step goes to build-report-%s.json, each failed step "
                              "with its fix to MANUAL-STEPS-%s.md and one PNG per page and visual to "
                              "snapshots-%s (next to the log)." % (tag, tag, tag))
    lines += [
        "#",
        "# Do not edit: change spec.json and run dxpgen.py build again",
        "# (HOME, STYLE and APP: the skill's references/engine.md).",
        rule,
    ]
    return lines


def assemble(result, tier, meta):
    imports = Imports()
    bodies = []
    core_tail = None
    for part in result.parts:
        for node, source in part.imports:
            imports.add(node, source)
        lines = drop_docstrings(part.code) if result.features else part.code
        code = "\n".join(lines).strip("\n")
        if part.name == "core":
            head, _, tail = code.partition("# @builders")
            bodies.append(head.strip("\n"))
            core_tail = tail.strip("\n")
        else:
            bodies.append(code)
    bodies.append(core_tail or "")
    literals = [_literal.home_literal(result.home),
                "# " + "=" * 64 + " STYLE\n" + _literal.literal("STYLE", result.style),
                "# " + "=" * 66 + " APP\n" + (_literal.dense("APP", result.app) if result.features
                                              else _literal.literal("APP", result.app))]
    code = "\n\n".join(literals) + "\n\n" + "\n\n\n".join(b for b in bodies if b)
    import_lines = imports.render(used_names(code))
    text = "\n".join(header_lines(result, tier, meta)) + "\n" + "\n".join(import_lines) + "\n\n" + code + "\n"
    return collapse_blank_lines(text)
