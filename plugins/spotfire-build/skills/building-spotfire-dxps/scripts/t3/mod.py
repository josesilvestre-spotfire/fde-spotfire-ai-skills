"""spec mod -> engine kind "mod" (engine/builders/mod.py; the mod itself: engine/features/modload.py).

A mod visual of the standard engine names a visualization mod listed in the spec's top-level "vizMods"
({"id", "project"}: the project folder holds mod-manifest.json and the files it lists). The manifest
types everything: the axes of the main view and of each layer type (mode categorical / continuous /
dual), the mod and layer properties (string, integer, double, boolean). references/spec-format.md "Visualization mods".

APP visual (after the generic id, type, title, showTitle):

    mod      the vizMods id          table   the main view's table
    where    main view limiting expression ([$P] -> DocumentProperty("P"))
    filtering  False when the main view ignores filtering
    axes     {name: expression | ""}   manifest order, only the axes the spec gives ("" clears)
    props    [[name, type, value], ...] spec order, value typed by the manifest
    layers   [{type, title, table, marking (name or None, always written), where, filtering,
               limits, empty, axes, props}] - given = exactly these layers, in order (absent: the
               mod's own layers stay)
    legend   True only when the spec itself says legend visible true (absent: the manifest's
             legend.defaultVisibility stays); False comes from the generic code

The helpers below (manifest_axes, manifest_props, layer_def, axis_text, prop_value) are shared with
dxpgen validate and verify_dxp, so the three read a mod visual the same way.
"""
import json

from ._common import blank, unwrap

KIND = "mod"
SPEC_TYPES = ("mod",)
STYLE_KEYS = ()
HANDLED = ("modId", "axes", "properties", "layers", "limitExpression", "useFiltering")
LAYER_KEYS = ("type", "title", "table", "axes", "properties", "marking", "limitExpression", "useFiltering",
              "limitByMarkings", "emptyMarkingBehavior")
AXIS_MODES = ("categorical", "continuous", "dual")
PROP_TYPES = ("string", "integer", "double", "boolean")
COLOR_AXIS = "Color"
MAX_TEXT = 102400                      # characters a mod string property holds
INT32 = (-2147483648, 2147483647)


# ---------------------------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------------------------
def layer_types(man):
    """Layer type names the manifest declares (manifest order)."""
    return [x["type"] for x in (man or {}).get("layers") or []
            if isinstance(x, dict) and isinstance(x.get("type"), str)]


def layer_def(man, layer_type):
    """The manifest's layers[] entry of a layer type, or None."""
    for x in (man or {}).get("layers") or []:
        if isinstance(x, dict) and x.get("type") == layer_type:
            return x
    return None


def _view(man, layer_type=None):
    if layer_type is None:
        return man if isinstance(man, dict) else {}
    found = layer_def(man, layer_type)
    return found if isinstance(found, dict) else {}


def axis_mode(defn):
    """An axis definition's mode (categorical, continuous or dual; dual when not given)."""
    mode = defn.get("mode") if isinstance(defn, dict) else None
    return mode if mode in AXIS_MODES else "dual"


def manifest_axes(man, layer_type=None):
    """{axis name: axis definition} of the main view (layer_type None) or of a layer type, in manifest
    order; "Color" is added when the view declares a colorAxis (its mode, else dual)."""
    view = _view(man, layer_type)
    dvd = view.get("dataViewDefinition") if isinstance(view.get("dataViewDefinition"), dict) else {}
    out = {}
    for a in dvd.get("axes") or []:
        if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"] not in out:
            out[a["name"]] = a
    color = dvd.get("colorAxis")
    if isinstance(color, dict) and COLOR_AXIS not in out:
        out[COLOR_AXIS] = dict(color, name=COLOR_AXIS, mode=color.get("mode") if color.get("mode") in AXIS_MODES
                               else "dual")
    return out


def manifest_props(man, layer_type=None):
    """{property name: type} of the mod (layer_type None) or of a layer type, in manifest order."""
    view = _view(man, layer_type)
    out = {}
    for p in view.get("properties") or []:
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"] not in out:
            out[p["name"]] = p.get("type")
    return out


def required_unset(man, layer_type, given):
    """Names of the view's required axes that get no expression from the spec (given: {name: value}) and
    that the manifest does not configure itself (automaticConfiguration expressionHeuristics "none"):
    the view stays invalid until they are set."""
    out = []
    for name, defn in manifest_axes(man, layer_type).items():
        if name == COLOR_AXIS or defn.get("optional") is True:
            continue
        auto = defn.get("automaticConfiguration") if isinstance(defn.get("automaticConfiguration"), dict) else {}
        if auto.get("expressionHeuristics") != "none":
            continue
        value = given.get(name) if isinstance(given, dict) else None
        if value is None or value == "" or value == []:
            out.append(name)
    return out


# ---------------------------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------------------------
def _same(text):
    return text


def axis_text(value, mode, column=None, expr=None):
    """The expression an axis gets from a spec value; None = leave the axis as the mod configures it,
    "" = clear it. column(text) turns a bare column name into [Name] (the view's table), expr(text)
    translates [$P] into DocumentProperty("P").

    categorical  "<...>" as written; a column name (bare or [Name]) -> <[Name]>; a list of levels
                 -> <[A] NEST [B]>
    continuous   the expression as written; a bare column name -> [Name]; a list -> several measures
                 joined with ", " (the manifest axis needs allowMultipleMeasures)
    dual         as continuous"""
    column = column or _same
    expr = expr or _same
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if not blank(item)]
        if mode == "categorical":
            levels = [expr(column(unwrap(item))) for item in items if unwrap(item)]
            return "<" + " NEST ".join(levels) + ">" if levels else ""
        return ", ".join(expr(column(item)) for item in items)
    text = str(value).strip()
    if not text:
        return ""
    if mode == "categorical":
        if text.startswith("<"):
            return expr(text)
        return "<" + expr(column(text)) + ">"
    return expr(column(text))


def _describe(value):
    if isinstance(value, (dict, list)):
        return "an object" if isinstance(value, dict) else "a list"
    if value is None:
        return "null"
    kind = ("a boolean" if isinstance(value, bool) else "a whole number" if isinstance(value, int)
            else "a number" if isinstance(value, float) else "a string")
    text = json.dumps(value, ensure_ascii=False)
    return kind + " " + (text if len(text) <= 60 else text[:57] + "...")


def prop_value(value, ptype, name="?"):
    """A spec property value typed by the manifest type: string (an object or a list becomes compact
    JSON text), integer (32-bit; a whole float is accepted), double, boolean. Raises ValueError with
    the validate message."""
    if ptype == "string":
        if isinstance(value, (dict, list)):
            text = json.dumps(value, sort_keys=True, separators=(",", ":"))
        elif isinstance(value, str):
            text = value
        else:
            raise ValueError("property '%s' is string in the mod's manifest, got %s" % (name, _describe(value)))
        if len(text) > MAX_TEXT:
            raise ValueError("the text has %d characters; a mod string property holds at most %d"
                             % (len(text), MAX_TEXT))
        return text
    if ptype == "integer":
        whole = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
        if isinstance(value, bool) or not whole or not INT32[0] <= int(value) <= INT32[1]:
            raise ValueError("property '%s' is an integer (32-bit), got %s" % (name, _describe(value)))
        return int(value)
    if ptype == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value \
                or value in (float("inf"), float("-inf")):
            raise ValueError("property '%s' is double in the mod's manifest, got %s" % (name, _describe(value)))
        return float(value)
    if ptype == "boolean":
        if not isinstance(value, bool):
            raise ValueError("property '%s' is boolean in the mod's manifest, got %s" % (name, _describe(value)))
        return value
    raise ValueError("property '%s' has type %s in the mod's manifest; the builder sets %s properties"
                     % (name, _describe(ptype), ", ".join(PROP_TYPES)))


def natural_type(value):
    """The manifest type a value suggests (a property the manifest does not list)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    return "string"


# ---------------------------------------------------------------------------------------------
# spec -> APP
# ---------------------------------------------------------------------------------------------
def convert(v, rv, path, ctx):
    mod_id = v.get("modId")
    man = ctx.viz_manifests.get(mod_id)
    if man is None:
        ctx.unsupported(path + ".modId", "a mod visual whose mod is not listed in vizMods")
        return {}
    table = ctx.table(v)
    out = {"mod": mod_id, "table": table}
    out.update(view(v, path, man, None, table, ctx))
    layers = v.get("layers")
    if isinstance(layers, list):
        out["layers"] = []
        for k, layer in enumerate(layers):
            if isinstance(layer, dict):
                out["layers"].append(convert_layer(layer, "%s.layers[%d]" % (path, k), man, v, table, ctx))
    legend = rv.get("legend")
    if (isinstance(legend, dict) and legend.get("visible") is True) or legend is True:
        out["legend"] = True                          # absent: the manifest's legend.defaultVisibility stays
    return out


def view(s, path, man, layer_type, table, ctx):
    """where, filtering, axes, props of the main view (layer_type None) or of a layer."""
    out = {}
    if s.get("limitExpression"):
        out["where"] = ctx.expr(s["limitExpression"])
    if s.get("useFiltering") is False:
        out["filtering"] = False
    axes = view_axes(s.get("axes"), manifest_axes(man, layer_type), table, ctx)
    if axes:
        out["axes"] = axes
    props = view_props(s.get("properties"), manifest_props(man, layer_type), path + ".properties", ctx)
    if props:
        out["props"] = props
    return out


def view_axes(given, defs, table, ctx):
    """{name: expression}: the manifest's axes first (manifest order), then any other name (spec order;
    dxpgen validate reports those)."""
    if not isinstance(given, dict):
        return {}
    out = {}
    names = [n for n in defs if n in given] + [n for n in given if n not in defs]

    def column(text):
        return ctx.column(text, table)
    for name in names:
        text = axis_text(given[name], axis_mode(defs.get(name)), column, ctx.expr)
        if text is not None:
            out[name] = text
    return out


def view_props(given, types, path, ctx):
    """[[name, type, value], ...] in spec order."""
    out = []
    for name, value in (given.items() if isinstance(given, dict) else ()):
        ptype = types.get(name) or natural_type(value)
        try:
            out.append([name, ptype, prop_value(value, ptype, name)])
        except ValueError as e:
            ctx.problems.append(("%s.%s" % (path, name), str(e)))
    return out


def convert_layer(layer, lp, man, v, table, ctx):
    ltype = layer.get("type")
    ltable = layer.get("table") or table
    # the layer marking is always written: AddLayer leaves a new layer unmarked
    marking = layer["marking"] if "marking" in layer else v.get("marking", ctx.marking_name)
    entry = {"type": ltype, "title": layer.get("title") or ltype, "table": ltable, "marking": marking}
    body = view(layer, lp, man, ltype, ltable, ctx)
    for key in ("where", "filtering"):
        if key in body:
            entry[key] = body.pop(key)
    if layer.get("limitByMarkings"):
        entry["limits"] = list(layer["limitByMarkings"])
        entry["empty"] = layer.get("emptyMarkingBehavior") or "ShowAll"     # always with limits (links)
    entry.update(body)
    return entry
