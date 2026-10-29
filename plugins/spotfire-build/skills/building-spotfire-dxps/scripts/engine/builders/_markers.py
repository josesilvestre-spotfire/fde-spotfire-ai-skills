# Standard engine, shared part "_markers": marker settings that
# the scatter plot and the map's marker layers share (ScatterPlot and
# MarkerLayerVisualization have the same ShapeAxis, SizeAxis,
# LabelColumn, LabelVisibility, MarkerSize and LineConnection members).
# Keys read (APP scatter visual or map marker layer): sizeBy, shapeBy
# (categorical), shape (MarkerType member name, e.g. "StarFive"),
# labelBy (label expression), labels ("All" | "Marked" | "None"; absent
# with labelBy = "All"), markerSize (% of the plot), lineBy (categorical:
# one line per category).
# Expressions are written as given. Unless the marker-by contains
# baserowid() the markers aggregate, and sizeBy, labelBy (and the
# settings LineConnection.OrderAxis / RotationAxis) must be aggregated
# (Avg(...), First(...)); a raw one makes the visual show "Please
# specify an aggregation method." and draw nothing (dxpgen rejects it,
# verify_dxp FAILs it; references/api-maps.md).
# @api ScatterPlot.ShapeAxis; ScatterPlot.SizeAxis; ScatterPlot.LabelColumn
# @api ScatterPlot.LabelVisibility; ScatterPlot.MarkerSize
# @api ScatterPlot.LineConnection
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.ShapeAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.SizeAxis
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.LabelColumn
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.LabelVisibility
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.MarkerSize
# @api Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.LineConnection
# @api ShapeAxis.Expression; ShapeAxis.DefaultShape; SizeAxis.Expression
# @api MarkerShape.ctor(MarkerType); MarkerType; LabelColumn.Expression
# @api LabelVisibility.All; LabelVisibility.Marked
# @api Spotfire.Dxp.Application.Visuals.LineConnection.ConnectionAxis
# @api CategoricalAxisBase.Expression
# @set ShapeAxis.Expression; ShapeAxis.DefaultShape; SizeAxis.Expression
# @set LabelColumn.Expression; ScatterPlot.LabelVisibility
# @set ScatterPlot.MarkerSize; CategoricalAxisBase.Expression
# @set Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.LabelVisibility
# @set Spotfire.Dxp.Application.Visuals.Maps.MarkerLayerVisualization.MarkerSize
from System import Single
from Spotfire.Dxp.Application.Visuals import MarkerShape, MarkerType
from Spotfire.Dxp.Application.Visuals import LabelVisibility

# ------------------------------------------------- markers (scatter, map)
def marker_style(name, content, ms):
    """Size, shape, label, marker size and line settings, each on its
    own (content: a ScatterPlot or a MarkerLayerVisualization)."""
    if ms.get("sizeBy"):
        ok(name + " size by", size_by, content, ms["sizeBy"])
    if ms.get("shapeBy") or ms.get("shape"):
        ok(name + " shapes", marker_shapes, content, ms)
    if ms.get("labelBy") or ms.get("labels"):
        ok(name + " labels", marker_labels, content, ms)
    if ms.get("markerSize") is not None:
        ok(name + " marker size", marker_size, content, ms["markerSize"])
    if ms.get("lineBy"):
        ok(name + " line by", line_by, content, ms["lineBy"])


def size_by(content, expression):
    content.SizeAxis.Expression = expression


def marker_shapes(content, ms):
    if ms.get("shapeBy"):
        content.ShapeAxis.Expression = ms["shapeBy"]
    if ms.get("shape"):
        content.ShapeAxis.DefaultShape = MarkerShape(
            getattr(MarkerType, ms["shape"]))


def marker_labels(content, ms):
    """getattr: LabelVisibility has a member named None."""
    if ms.get("labelBy"):
        content.LabelColumn.Expression = ms["labelBy"]
    content.LabelVisibility = getattr(LabelVisibility,
                                      ms.get("labels", "All"))


def marker_size(content, size):
    content.MarkerSize = Single(float(size))


def line_by(content, expression):
    content.LineConnection.ConnectionAxis.Expression = expression
