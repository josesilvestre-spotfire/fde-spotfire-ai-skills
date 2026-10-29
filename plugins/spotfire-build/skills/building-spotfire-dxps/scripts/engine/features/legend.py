# Standard engine, feature part "legend": hide individual legend
# items (Properties > Legend > the item check boxes) after the visual is
# built, its data links and settings set. Each kind is matched by the
# runtime type of Legend.Items entries; the types and who makes them come
# from the 15.0 assemblies (VisualizationData makes the filtering and
# marking items, GroupByAxis (LineChart.LineByAxis) and LineConnection
# the line-by items, ColorAxis and colorings the color items, reference
# layers and FittingModelCollection the lines-and-curves items, Trellis
# the trellis item).
# APP visual "legendHide": [kind, ...] with kinds filtering, marking,
# lineBy, colorBy, referenceLayers, trellis.
# @api Visual.As; Visualization; Visualization.Legend; Legend.Items
# @api Legend.LegendItemCollection.GetEnumerator; LegendItem.Visible
# @api LegendFilteringsItem; LegendMarkingItem; LegendGroupByItem
# @api LegendLineConnectionItem; LegendColorItem; LegendTrellisItem
# @api LegendReferenceLayerItem; LegendReferenceLayerTitleItem
# @api LegendFittingModelCollectionItem
# @set LegendItem.Visible
from Spotfire.Dxp.Application.Visuals import Visualization

# --------------------------------------------------------- legend items
LEGEND_ITEMS = {
    "filtering": ("LegendFilteringsItem",),
    "marking": ("LegendMarkingItem",),
    "lineBy": ("LegendGroupByItem", "LegendLineConnectionItem"),
    "colorBy": ("LegendColorItem",),
    "referenceLayers": ("LegendReferenceLayerItem",
                        "LegendReferenceLayerTitleItem",
                        "LegendFittingModelCollectionItem"),
    "trellis": ("LegendTrellisItem",)}


def hide_legend_items(v, vs):
    names = []
    for kind in vs["legendHide"]:
        names += list(LEGEND_ITEMS[kind])
    for item in v.As[Visualization]().Legend.Items:
        if item.GetType().Name in names:
            item.Visible = False
