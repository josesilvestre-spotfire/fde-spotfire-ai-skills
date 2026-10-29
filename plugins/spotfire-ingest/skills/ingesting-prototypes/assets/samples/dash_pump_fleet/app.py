"""Pump fleet explorer: a synthetic Dash prototype used by the ingest skill tests."""

import numpy as np
import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, State, callback, dash_table, dcc, html

rng = np.random.default_rng(3)
FLEET = pd.DataFrame({
    "pump_id": [f"P-{n}" for n in range(101, 121)],
    "area": rng.choice(["North", "South", "East"], 20),
    "flow_bpd": rng.normal(1800, 200, 20).round(0),
    "efficiency_pct": rng.normal(72, 5, 20).round(1),
    "vibration_mms": rng.normal(3.2, 0.6, 20).round(2),
})

app = Dash(__name__)
app.layout = html.Div([
    dcc.Store(id="picked-pumps"),
    dcc.Interval(id="refresh", interval=60_000),
    dcc.Tabs([
        dcc.Tab(label="Fleet", children=[
            dcc.Dropdown(id="areas", options=["North", "South", "East"],
                         value=["North", "South"], multi=True),
            dcc.RangeSlider(id="flow-range", min=1000, max=2600, step=50,
                            value=[1400, 2200]),
            dcc.DatePickerRange(id="period", start_date="2026-01-01",
                                end_date="2026-03-31"),
            dcc.Graph(id="efficiency-scatter"),
        ]),
        dcc.Tab(label="Pump Table", children=[
            dash_table.DataTable(id="pump-table", data=FLEET.to_dict("records"),
                                 row_selectable="multi"),
            html.Button("Export selection", id="export"),
        ]),
    ]),
])


@callback(Output("efficiency-scatter", "figure"),
          Input("areas", "value"), Input("flow-range", "value"))
def draw_scatter(areas, flow_range):
    view = FLEET[FLEET["area"].isin(areas) & FLEET["flow_bpd"].between(*flow_range)]
    fig = px.scatter(view, x="flow_bpd", y="efficiency_pct", color="area",
                     size="vibration_mms", trendline="ols", template="plotly_dark")
    fig.update_layout(dragmode="select")
    return fig


@callback(Output("picked-pumps", "data"),
          Input("efficiency-scatter", "selectedData"), State("areas", "value"))
def keep_selection(selected, areas):
    points = (selected or {}).get("points", [])
    return [p["x"] for p in points]


if __name__ == "__main__":
    app.run(debug=False)
