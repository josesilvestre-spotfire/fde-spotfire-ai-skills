# Standard engine, feature part "links": a visual's data links
# after its builder ran (lib/60_charts.py _charts_set_marking /
# _charts_add_limit / _charts_set_empty / _charts_set_where): its own
# marking (a name, or None = cannot be marked), the markings that limit
# its data, the empty-marking behavior and, for tables and KPI charts,
# the limiting expression. A KPI chart's tiles get the same settings
# (lib/70_tables.py _tables_kpi_sync_data).
# APP visual keys: marking (name or None; absent = the default marking),
# limits [marking names], empty "ShowAll"|"ShowEmpty"|"ShowMessage"
# (always set with limits), where (table, kpi; line and bar builders
# set their own).
# @api Visualization.Data; VisualizationData.MarkingReference
# @api VisualizationData.Filterings; VisualizationData.WhereClauseExpression
# @api VisualizationFilteringCollection.Add(DataSelection)
# @api VisualizationFilteringCollection.Contains(DataSelection)
# @api VisualizationData.LimitingMarkingsEmptyBehavior
# @api LimitingMarkingsEmptyBehavior.ShowEmpty
# @api LimitingMarkingsEmptyBehavior.ShowMessage
# @api DataMarkingSelectionCollection.TryGetValue(String, out DataMarkingSelection)
# @api KpiChart.KpiCollection; KpiCollection.GetEnumerator
# @api KpiContent.Visualization; KpiVisualization.Data
# @set VisualizationData.MarkingReference
# @set VisualizationData.WhereClauseExpression
# @set VisualizationData.LimitingMarkingsEmptyBehavior
from Spotfire.Dxp.Application.Visuals import Visualization, KpiChart
from Spotfire.Dxp.Data import LimitingMarkingsEmptyBehavior

# ----------------------------------------------------- visual data links
LINK_KEYS = ("marking", "limits", "empty", "where")


def marking_named(name):
    found, m = Document.Data.Markings.TryGetValue(name)
    if not found:
        raise Exception("no marking " + name)
    return m


def data_links(v, vs):
    if not [k for k in LINK_KEYS if k in vs]:
        return
    datas = [v.As[Visualization]().Data]
    if vs["type"] == "kpi":
        for content in v.As[KpiChart]().KpiCollection:
            datas.append(content.Visualization.Data)
    for data in datas:
        if "marking" in vs:
            name = vs["marking"]
            data.MarkingReference = marking_named(name) if name else None
        for name in vs.get("limits", []):
            m = marking_named(name)
            if not data.Filterings.Contains(m):
                data.Filterings.Add(m)
        if "empty" in vs:
            data.LimitingMarkingsEmptyBehavior = getattr(
                LimitingMarkingsEmptyBehavior, vs["empty"])
        if "where" in vs:
            data.WhereClauseExpression = vs["where"]
