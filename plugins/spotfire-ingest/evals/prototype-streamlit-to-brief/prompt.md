---
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

Our station engineers use the Streamlit prototype below to watch compressor discharge
temperature. We want the same app in Spotfire. Prepare everything the Spotfire build needs from
this prototype. Use `./workspace` as the DXP workspace (DXP_WORKSPACE) and `CompressorWatch` as
the app folder name. The app owner (the station engineer) is not available in this session.

`app.py`:

```python
import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Compressor Watch", layout="wide")


@st.cache_data
def load_readings(seed=5):
    rng = np.random.default_rng(seed)
    stamps = pd.date_range("2026-04-01", periods=24 * 45, freq="h")
    frames = []
    for unit in ["C-201", "C-202", "C-203"]:
        temp = 245 + 6 * np.sin(np.arange(len(stamps)) / 24 * 2 * np.pi)
        temp = temp + rng.normal(0, 2.5, len(stamps))
        frames.append(pd.DataFrame({"timestamp": stamps, "unit": unit,
                                    "discharge_temp_f": temp,
                                    "suction_psig": 380 + rng.normal(0, 4, len(stamps))}))
    return pd.concat(frames, ignore_index=True)


with st.sidebar:
    unit = st.selectbox("Compressor", ["C-201", "C-202", "C-203"])
    period = st.slider("Period", min_value=dt.datetime(2026, 4, 1),
                       max_value=dt.datetime(2026, 5, 15),
                       value=(dt.datetime(2026, 4, 10), dt.datetime(2026, 5, 10)))
    limit = st.number_input("High temperature limit (degF)", 200.0, 300.0, 255.0, 1.0)
    window = st.slider("Rolling window (h)", 3, 72, 12)
    uploaded = st.file_uploader("Load historian export (CSV)", type=["csv"])

data = pd.read_csv(uploaded, parse_dates=["timestamp"]) if uploaded else load_readings()
view = data[(data["unit"] == unit) & data["timestamp"].between(*period)].copy()
view["rolling_mean"] = view["discharge_temp_f"].rolling(window, min_periods=1).mean()
view["rolling_std"] = view["discharge_temp_f"].rolling(window, min_periods=2).std()

c1, c2 = st.columns(2)
c1.metric("Hours above limit", int((view["discharge_temp_f"] > limit).sum()))
c2.metric("Peak temperature (degF)", f"{view['discharge_temp_f'].max():.1f}")

trend_tab, table_tab = st.tabs(["Trend", "Readings"])
with trend_tab:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=view["timestamp"], y=view["rolling_mean"] + 2 * view["rolling_std"],
                             mode="lines", line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=view["timestamp"], y=view["rolling_mean"] - 2 * view["rolling_std"],
                             mode="lines", fill="tonexty", line=dict(width=0),
                             name="Normal range"))
    fig.add_trace(go.Scatter(x=view["timestamp"], y=view["discharge_temp_f"], mode="lines",
                             name="Discharge temperature"))
    fig.add_hline(y=limit, line_dash="dash", annotation_text="Limit")
    st.plotly_chart(fig, use_container_width=True)
with table_tab:
    st.dataframe(view[["timestamp", "unit", "discharge_temp_f", "suction_psig"]])
```
