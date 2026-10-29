"""Pump vibration monitor: a synthetic Streamlit prototype used by the ingest skill tests."""

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import PUMPS, alarm_hours, forecast, simulate_readings, smooth

st.set_page_config(page_title="Pump Vibration Monitor", layout="wide")
st.title("Pump Vibration Monitor")


@st.cache_data
def load(days, seed):
    return simulate_readings(days=days, seed=seed)


with st.sidebar:
    pump = st.selectbox("Pump", PUMPS, index=2)
    window = st.date_input("Date range", (dt.date(2026, 1, 1), dt.date(2026, 3, 1)))
    alarm = st.number_input("Alarm level (mm/s)", 1.0, 15.0, 7.1, 0.1)
    span = st.slider("Smoothing span (h)", 6, 168, 48, 6)
    horizon = st.slider("Forecast horizon (h)", 24, 336, 72, 24)
    show_raw = st.checkbox("Show raw readings", value=True)
    upload = st.file_uploader("Replace readings (CSV)", type=["csv"])

data = pd.read_csv(upload) if upload is not None else load(60, 7)
start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
view = data[(data["timestamp"] >= start) & (data["timestamp"] < end)]
one = view[view["pump_id"] == pump].sort_values("timestamp")

k1, k2, k3 = st.columns(3)
k1.metric("Latest vibration (mm/s)", f"{one['vibration_mms'].iloc[-1]:.2f}")
k2.metric("Hours over alarm", int(alarm_hours(one, alarm).loc[pump]))
k3.metric("Mean flow (bbl/d)", f"{one['flow_bpd'].mean():,.0f}")

trend_tab, fleet_tab = st.tabs(["Trend", "Fleet"])

with trend_tab:
    smoothed = smooth(one["vibration_mms"], span)
    centre, lower, upper = forecast(smoothed, horizon)
    future = pd.date_range(one["timestamp"].iloc[-1], periods=horizon + 1, freq="h")[1:]
    fig = go.Figure()
    if show_raw:
        fig.add_trace(go.Scatter(x=one["timestamp"], y=one["vibration_mms"], name="Raw",
                                 mode="lines", line=dict(color="#94A3B8", width=1)))
    fig.add_trace(go.Scatter(x=one["timestamp"], y=smoothed, name="Smoothed", mode="lines"))
    fig.add_trace(go.Scatter(x=future, y=upper, mode="lines", line=dict(width=0),
                             showlegend=False))
    fig.add_trace(go.Scatter(x=future, y=lower, mode="lines", fill="tonexty",
                             fillcolor="rgba(167,139,250,0.25)", line=dict(width=0),
                             name="Forecast band"))
    fig.add_trace(go.Scatter(x=future, y=centre, mode="lines", name="Forecast",
                             line=dict(color="#A78BFA", dash="dot")))
    fig.add_hline(y=alarm, line_dash="dash", line_color="#F59E0B", annotation_text="Alarm")
    fig.update_layout(title=f"{pump} vibration and {horizon} h forecast",
                      yaxis_title="Vibration (mm/s)")
    st.plotly_chart(fig, use_container_width=True)

with fleet_tab:
    hours = alarm_hours(view, alarm).rename("Hours over alarm").reset_index()
    st.bar_chart(hours, x="pump_id", y="Hours over alarm")
    latest = view.sort_values("timestamp").groupby("pump_id").tail(1)
    picked = st.dataframe(latest, on_select="rerun", selection_mode="single-row")
    st.markdown(f"Rows in view: **{len(view):,}**")
