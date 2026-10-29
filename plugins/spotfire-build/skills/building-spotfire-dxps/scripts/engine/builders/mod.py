# Standard engine, kind "mod": a visualization mod visual with its main
# view and its layers (feature vizMods). Proven in live builds on Analyst
# 15.0: AddNew(ModIdentifier), Layers.Clear, several layers with
# AddLayer(type, title) on several tables, where clauses with ${...} and
# DocumentProperty, multi-measure Values with aliases,
# <[Axis.Default.Names]>, BinByDateTime, a layer marking, typed
# Property<T> on the main view and the layers, clearing an axis with ""
# or "<>", Title set again when AddLayer does not keep it.
#   - new_mod_visual: page.Visuals.AddNew(ModIdentifier).Visual with the
#     ModIdentifier that features/modload.py load_viz found (VIZ); when
#     the mod is not in the analysis or Spotfire refuses to add it: a
#     placeholder text area "[mod: <id>]" (TYPE_IDS["mod"]) and a TODO
#     line, and core leaves the data links, settings and legend items off
#     it (MOD_PLACEHOLDERS).
#   - build_mod: the main view's table, limiting expression and
#     filtering, its axes and typed properties, its legend (only when
#     APP gives "legend": absent keeps the manifest's default); then,
#     when APP has "layers", Layers.Clear() and one AddLayer(type, title)
#     per layer with its table, limiting expression, filtering, marking
#     (always set: AddLayer leaves a layer unmarked), limiting markings,
#     empty behavior, axes and properties, each its own ok(); last a NOTE
#     when Spotfire reports a view as not valid. APP without "layers"
#     keeps the mod's own layers.
#   Axes are set in the mod's own order (AxesNames), then "Color" (the
#   color axis is not in AxesNames). An expression that reads back
#   different (whitespace and case aside) is a FAILED line; "" clears an
#   axis ("<>" when Spotfire refuses "").
#   Properties: Property<T>(name) with T from the manifest type (string
#   String, integer Int32, double Double, boolean Boolean), through
#   public reflection when IronPython refuses the generic call; None = the mod
#   has no property of that name and type (FAILED line); every value is
#   read back after the set.
# APP keys: mod (a vizMods id), table, where, filtering (False only),
# axes {name: expression | "" (clear)}, props [[name, type, value], ...],
# legend, layers [{type, title, table, marking (name or None; absent =
# the default marking), where, filtering, limits, empty, axes, props},
# ...]. As on every visual: the main view's marking, limits and empty
# through features/links.py, settings through features/settings.py
# (paths relative to the ModVisualization), legendHide through
# features/legend.py. Action triggers on the visual are manual steps.
# Converter: scripts/t3/mod.py.
# @api ModVisualization; VisualCollection.AddNew(ModIdentifier)
# @api ModVisualization.Visual; ModVisualization.Data; ModVisualization.Layers
# @api ModVisualization.Axis(String); ModVisualization.Axes; ModVisualization.AxesNames
# @api ModVisualization.HasColorAxis; ModVisualization.ColorAxis
# @api ModVisualization.Property(String); ModVisualization.IsConfigurationValid
# @api ModVisualization.Legend; Legend.Visible
# @api ModLayerCollection.AddLayer(String, String); ModLayerCollection.Clear
# @api ModLayer.Title; ModLayer.Data; ModLayer.Axis(String); ModLayer.Axes
# @api ModLayer.AxesNames; ModLayer.HasColorAxis; ModLayer.ColorAxis
# @api ModLayer.Property(String); ModLayer.IsConfigurationValid
# @api ModAxis.Expression; ModAxis.Name; ColorAxis.Expression; ModProperty`1.Value
# @api Visual.As; HtmlTextArea.HtmlContent; VisualTypeIdentifiers.HtmlTextArea
# @api VisualizationData.DataTableReference; VisualizationData.MarkingReference
# @api VisualizationData.WhereClauseExpression; VisualizationData.UseActiveFiltering
# @api VisualizationData.Filterings; VisualizationFilteringCollection.Add(DataSelection)
# @api VisualizationFilteringCollection.Contains(DataSelection)
# @api VisualizationData.LimitingMarkingsEmptyBehavior
# @api LimitingMarkingsEmptyBehavior.ShowAll; LimitingMarkingsEmptyBehavior.ShowEmpty
# @api LimitingMarkingsEmptyBehavior.ShowMessage; DataManager.Markings
# @api DataMarkingSelectionCollection.TryGetValue(String, out DataMarkingSelection)
# @set ModLayer.Title; ModAxis.Expression; ColorAxis.Expression; ModProperty`1.Value
# @set HtmlTextArea.HtmlContent; VisualizationData.DataTableReference
# @set VisualizationData.MarkingReference; VisualizationData.WhereClauseExpression
# @set VisualizationData.UseActiveFiltering
# @set VisualizationData.LimitingMarkingsEmptyBehavior
import clr
from System import Array, Boolean, Double, Int32, String, Type
from Spotfire.Dxp.Application.Mods import ModVisualization
from Spotfire.Dxp.Application.Visuals import HtmlTextArea
from Spotfire.Dxp.Data import LimitingMarkingsEmptyBehavior

# ---------------------------------------------------- visualization mod
MOD_TYPES = {"string": String, "integer": Int32, "double": Double,
             "boolean": Boolean}
MOD_PLACEHOLDERS = []    # ids of the mod visuals built as placeholders


def new_mod_visual(page, vs):
    """The mod visual's Visual; a placeholder text area when the mod is
    not in the analysis or Spotfire refuses to add it."""
    mid = VIZ.get(vs["mod"])
    if mid is not None:
        mv = ok(vs["id"] + ": add mod " + vs["mod"], mod_add, page, mid)
        if mv is not None:
            return mv.Visual
    v = new_visual(page, "mod")
    v.As[HtmlTextArea]().HtmlContent = (
        "<p><b>[mod: " + vs["mod"] + "]</b></p><p>This visualization "
        "is not available in this analysis.</p>")
    MOD_PLACEHOLDERS.append(vs["id"])
    LOG.append("TODO " + vs["id"] + ": placeholder for mod " + vs["mod"]
               + "; " + VIZ_FIX)
    return v


def mod_add(page, mid):
    mv = page.Visuals.AddNew(mid)
    if mv is None:
        raise Exception("Visuals.AddNew(ModIdentifier) returned nothing")
    return mv


def build_mod(v, vs):
    vid = vs["id"]
    if vid in MOD_PLACEHOLDERS:
        return
    mv = v.As[ModVisualization]()
    if mv is None:
        raise Exception("the visual is not a visualization mod")
    ok(vid + ": data", mod_data, vid, mv, vs)
    mod_view(vid + ":", mv, vs)
    if "legend" in vs:
        ok(vid + ": legend", legend, mv, vs)
    built = []
    if "layers" in vs:
        ok(vid + ": layers", mod_clear, mv)
        for ls in vs["layers"]:
            layer = mod_layer(vid + ": layer " + ls["title"], mv, ls)
            if layer is not None:
                built.append(layer)
    ok(vid + ": check", mod_check, vid, mv, built)


def mod_data(name, content, s):
    """Table first (the axis expressions resolve against it), then the
    limiting expression and the filtering of the main view or a layer."""
    data = content.Data
    if s.get("table"):
        if s["table"] not in T:
            raise Exception("table " + s["table"] + " is not loaded")
        data.DataTableReference = T[s["table"]]
    if "where" in s:
        data.WhereClauseExpression = s["where"]
        back = str(data.WhereClauseExpression or "")
        if "${" in s["where"] and "${" not in back:
            LOG.append("NOTE " + name + ": the limiting expression reads "
                       "back without ${...}: " + back)
    if s.get("filtering") is False:
        data.UseActiveFiltering = False


def mod_view(name, content, s):
    """Axes, then properties, of the main view or a layer."""
    axes = s.get("axes", {})
    for axis in mod_axis_order(content, axes):
        ok(name + " axis " + axis, mod_axis_set, content, axis, axes[axis])
    for p in s.get("props", []):
        ok(name + " property " + p[0], mod_prop, content, p)


def mod_clear(mv):
    mv.Layers.Clear()


def mod_layer(name, mv, ls):
    layer = ok(name, mod_add_layer, mv, ls)
    if layer is None:
        return None
    ok(name + " data", mod_data, name, layer, ls)
    ok(name + " marking", mod_layer_marking, layer, ls)
    mod_view(name, layer, ls)
    return layer


def mod_add_layer(mv, ls):
    layer = mv.Layers.AddLayer(ls["type"], ls["title"])
    if layer is None:
        raise Exception("AddLayer returned nothing")
    if str(layer.Title) != ls["title"]:
        layer.Title = ls["title"]
    return layer


def mod_layer_marking(layer, ls):
    """AddLayer leaves a layer unmarked, so its marking is always set
    (absent = the default marking; None = cannot be marked); then the
    markings that limit it and the empty behavior."""
    data = layer.Data
    if "marking" not in ls:
        data.MarkingReference = MARK
    elif ls["marking"]:
        data.MarkingReference = mod_marking(ls["marking"])
    else:
        data.MarkingReference = None
    for name in ls.get("limits", []):
        m = mod_marking(name)
        if not data.Filterings.Contains(m):
            data.Filterings.Add(m)
    if "empty" in ls:
        data.LimitingMarkingsEmptyBehavior = getattr(
            LimitingMarkingsEmptyBehavior, ls["empty"])


def mod_marking(name):
    found, m = Document.Data.Markings.TryGetValue(name)
    if not found:
        raise Exception("no marking " + name)
    return m


def mod_axis_order(content, axes):
    """The axes APP gives, in the mod's own order (AxesNames), then the
    others (Color) by name."""
    try:
        names = [str(n) for n in content.AxesNames]
    except Exception:
        names = []
    first = [n for n in names if n in axes]
    return first + sorted([n for n in axes if n not in first])


def mod_axis(content, name):
    """Axis(name); the color axis for "Color" (it is not in Axes); else
    a case-insensitive match on the names in Axes."""
    try:
        axis = content.Axis(name)
    except Exception:
        axis = None
    if axis is not None:
        return axis
    if name == "Color" and content.HasColorAxis:
        return content.ColorAxis
    for a in content.Axes:
        if a is not None and str(a.Name).lower() == name.lower():
            return a
    names = [str(n) for n in content.AxesNames]
    raise Exception("no axis " + name + " (axes: " + ", ".join(names)
                    + ")")


def mod_squash(text):
    return "".join(str(text or "").split()).lower()


def mod_axis_set(content, name, expr):
    """One axis: its expression, or "" to clear it (Spotfire takes "" or
    "<>", depending on the axis); FAILED when it reads back different."""
    axis = mod_axis(content, name)
    if expr in ("", "<>"):
        try:
            axis.Expression = expr
        except Exception:
            axis.Expression = "<>" if expr == "" else ""
        return
    axis.Expression = expr
    back = str(axis.Expression or "")
    if mod_squash(back) != mod_squash(expr):
        raise Exception("reads back " + back)


def mod_property(content, name, net_type):
    """ModProperty<T> of the main view or a layer, or None when the mod
    has no such property or stores another type; through public reflection
    when IronPython refuses the generic call."""
    try:
        return content.Property[net_type](name)
    except Exception as e:
        refused = why(e)
    for m in content.GetType().GetMethods():
        if m.Name == "Property" and m.IsGenericMethodDefinition:
            typed = m.MakeGenericMethod(
                Array[Type]([clr.GetClrType(net_type)]))
            return typed.Invoke(content, Array[object]([name]))
    raise Exception("Property<T> refused: " + refused)


def mod_prop(content, p):
    """[name, manifest type, value]: set, then read back."""
    net_type = MOD_TYPES[p[1]]
    prop = mod_property(content, p[0], net_type)
    if prop is None:
        raise Exception("the mod has no " + p[1] + " property " + p[0])
    prop.Value = net_type(p[2])
    back = prop.Value
    if p[1] in ("integer", "double"):
        same = abs(float(back) - float(p[2])) < 1e-6
    else:
        same = back == p[2]
    if not same:
        raise Exception("reads back " + str(back))


def mod_check(vid, mv, layers):
    """A NOTE when Spotfire reports a view as not valid (an axis without
    an expression, a column its table does not have)."""
    bad = [str(x.Title) for x in layers if not x.IsConfigurationValid()]
    if not mv.IsConfigurationValid():
        bad.insert(0, "main view")
    if bad:
        LOG.append("NOTE " + vid + ": Spotfire reports these views as "
                   "not valid: " + ", ".join(bad))


BUILDERS["mod"] = build_mod
TYPE_IDS["mod"] = "HtmlTextArea"      # the placeholder (new_mod_visual)
