# Configure Demo Layers
# Sets up the demo-layers mod visual on the active page with three layers
# on two tables: hourly readings, the same readings in time bins, and the
# pump events (markable with the marking Event Pick).
#
# Before you run it: load data/csv/READINGS.csv as READINGS and
# data/csv/EVENTS.csv as EVENTS, and connect the mod (Tools > Development >
# Mods development > Connect to file, or the development server). The script
# uses the demo-layers visual on the active page, or adds one.
# Safe to run again: it rebuilds the layers each time.
from System import Boolean, Double, Int32, Int64, String
from Spotfire.Dxp.Application.Mods import ModVisualization
from Spotfire.Dxp.Data import (DataProperty, DataPropertyAttributes,
                               DataPropertyClass, DataType)

MOD_ID = "demo-layers"
TITLE = "Readings and events"


def ensure_property(name, data_type, default, description):
    registry = Document.Data.Properties
    if not registry.ContainsProperty(DataPropertyClass.Document, name):
        registry.AddProperty(DataPropertyClass.Document,
                             DataProperty.CreateCustomPrototype(
                                 name, description, default, data_type,
                                 DataProperty.DefaultAttributes
                                 | DataPropertyAttributes.IsPropagated))


def table(name):
    found, t = Document.Data.Tables.TryGetValue(name)
    if not found:
        raise Exception("Load the table " + name + " first.")
    return t


def marking(name):
    found, m = Document.Data.Markings.TryGetValue(name)
    return m if found else Document.Data.Markings.Add(name)


def mod_visual(page):
    for visual in page.Visuals:
        content = visual.As[ModVisualization]()
        if content is not None and content.ModIdentifier.Id == MOD_ID:
            return content
    for mid in Document.ModManager.GetVisualizationModsIncludingPinned():
        if mid.Id == MOD_ID:
            return page.Visuals.AddNew(mid)
    raise Exception("Connect the " + MOD_ID + " mod first (Mods development).")


def set_props(view, values):
    """Typed mod properties: the type must match the manifest."""
    for name, net_type, value in values:
        prop = view.Property[net_type](name)
        if prop is None:
            raise Exception("No %s property %s" % (net_type.__name__, name))
        prop.Value = net_type(value)


def add_layer(mv, layer_type, title, source, where, mark, axes, props):
    layer = mv.Layers.AddLayer(layer_type, title)
    if layer.Title != title:
        layer.Title = title
    layer.Data.DataTableReference = source      # before the axes
    layer.Data.WhereClauseExpression = where
    # AddLayer leaves a new layer without a marking: always set it.
    layer.Data.MarkingReference = mark
    for name, expression in axes:
        layer.Axis(name).Expression = expression
    set_props(layer, props)
    return layer


ensure_property("ViewAsset", DataType.String, String("Pump A"),
                "Asset the layers show")
ensure_property("BinLevel", DataType.LongInteger, Int64(3),
                "Time bin of the Daily range layer: 3 day, 4 hour")

readings, events = table("READINGS"), table("EVENTS")
mv = mod_visual(Document.ActivePageReference)
mv.Visual.Title = TITLE
mv.Data.DataTableReference = readings
mv.Legend.Visible = False
set_props(mv, [("heading", String, "Pump readings"),
               ("showGrid", Boolean, True),
               ("lineWidth", Double, 1.5),
               ("maxRows", Int32, 5000)])

where = '[Asset] = "${ViewAsset}"'
mv.Layers.Clear()
add_layer(mv, "Series", "Readings", readings, where, None,
          [("X", "[Timestamp (UTC)]"),
           ("Values", "[Pressure (psig)], [Flow (bbl/d)]"),
           ("Series", "<[Axis.Default.Names]>")],
          [("role", String, "raw"), ("lineWidth", Double, 1.0)])
daily = add_layer(
    mv, "Series", "Daily range", readings, where, None,
    [("X", "Min([Timestamp (UTC)])"),
     ("Values", "Min([Pressure (psig)]) as [Pressure min], "
                "Max([Pressure (psig)]) as [Pressure max]"),
     ("Series", "<[Axis.Default.Names]>"),
     ("Bin", '<BinByDateTime([Timestamp (UTC)],"Year.Quarter.Month.Day.Hour",${BinLevel})>')],
    [("role", String, "binned"), ("visible", Boolean, True)])
daily.Data.UseActiveFiltering = False
add_layer(mv, "Records", "Events", events, where, marking("Event Pick"),
          [("Key", "<[Event ID]>"),
           ("Attributes", "<[Asset] NEST [Start] NEST [End]>"),
           ("Values", "Max([Severity])")],
          [("role", String, "events")])
