"""Line pressure watch: a synthetic Shiny for Python (Core) prototype used by the tests."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

STATIONS = {"ST1": "Station 1", "ST2": "Station 2", "ST3": "Station 3"}
rng = np.random.default_rng(11)
stamps = pd.date_range("2026-03-01", periods=24 * 30, freq="h")
DATA = pd.concat([
    pd.DataFrame({"timestamp": stamps, "station": key,
                  "suction_psi": 60 + rng.normal(0, 2, len(stamps)),
                  "discharge_psi": 900 - 20 * i + rng.normal(0, 8, len(stamps))})
    for i, key in enumerate(STATIONS)], ignore_index=True)
EVENTS = pd.DataFrame({"start": pd.to_datetime(["2026-03-05 06:00", "2026-03-18 14:00"]),
                       "end": pd.to_datetime(["2026-03-05 18:00", "2026-03-19 02:00"])})

app_ui = ui.page_navbar(
    ui.nav_panel(
        "Overview",
        ui.layout_sidebar(
            ui.sidebar(
                ui.input_select("station", "Station", choices=STATIONS, selected="ST2"),
                ui.input_slider("pressure_band", "Normal band (psi)", min=600, max=1000,
                                value=(820, 920), step=5),
                ui.input_switch("show_events", "Show upsets", value=True),
                ui.input_action_button("run", "Recalculate limits"),
                width=280,
            ),
            ui.layout_columns(
                ui.value_box("Mean discharge", ui.output_text("mean_discharge")),
                ui.value_box("Hours outside band", ui.output_text("hours_out")),
                col_widths=[6, 6],
            ),
            ui.card(ui.card_header("Discharge pressure"), output_widget("pressure_trend")),
        ),
    ),
    ui.nav_panel(
        "Details",
        ui.navset_card_tab(
            ui.nav_panel("Table", ui.output_data_frame("readings")),
            ui.nav_panel("Notes", ui.markdown("Readings are simulated.")),
        ),
    ),
    title="Line Pressure Watch",
)


def server(input, output, session):
    limits = reactive.value((820, 920))

    @reactive.calc
    def station_data():
        return DATA[DATA["station"] == input.station()]

    @reactive.effect
    @reactive.event(input.run)
    def _recalculate():
        values = station_data()["discharge_psi"]
        limits.set((values.quantile(0.05), values.quantile(0.95)))

    @render.text
    def mean_discharge():
        return f"{station_data()['discharge_psi'].mean():.0f} psi"

    @render.text
    def hours_out():
        low, high = input.pressure_band()
        values = station_data()["discharge_psi"]
        return str(int(((values < low) | (values > high)).sum()))

    @render_plotly
    def pressure_trend():
        frame = station_data()
        fig = go.Figure(go.Scatter(x=frame["timestamp"], y=frame["discharge_psi"],
                                   mode="lines", name="Discharge"))
        low, high = limits.get()
        fig.add_trace(go.Scatter(x=frame["timestamp"], y=[high] * len(frame),
                                 mode="lines", name="Upper limit",
                                 line=dict(dash="dot", color="#E11D48")))
        fig.add_hrect(y0=input.pressure_band()[0], y1=input.pressure_band()[1],
                      fillcolor="#22C55E", opacity=0.1)
        if input.show_events():
            for row in EVENTS.itertuples():
                fig.add_vrect(x0=row.start, x1=row.end, fillcolor="#F97316", opacity=0.2)
        return fig

    @render.data_frame
    def readings():
        return render.DataGrid(station_data(), selection_mode="row")


app = App(app_ui, server)
