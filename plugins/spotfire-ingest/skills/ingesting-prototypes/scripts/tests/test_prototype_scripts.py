"""Tests for the ingesting-prototypes scripts.

Run from anywhere:
    python scripts/tests/test_prototype_scripts.py
    python -m unittest discover -s scripts/tests

The scanner and the hand-off checker need the standard library only. The data function
test also needs numpy and pandas and is skipped without them.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL / "scripts"
SAMPLES = SKILL / "assets" / "samples"
EXAMPLE = SKILL / "assets" / "examples" / "pump-vibration-monitor"
sys.path.insert(0, str(SCRIPTS))

import scan_prototype  # noqa: E402


def scan(path):
    return scan_prototype.scan(path).items


def find(items, **match):
    return [i for i in items if all(i.get(k) == v for k, v in match.items())]


def gaps(items):
    return {(i["widget"], i["gap"]) for i in items if i["gap"]}


class StreamlitSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = scan(SAMPLES / "streamlit_pump_monitor")

    def test_inputs(self):
        ids = {i["id"] for i in find(self.items, kind="input")}
        self.assertTrue({"pump", "window", "alarm", "span", "horizon", "show_raw",
                         "upload"} <= ids, ids)
        span = find(self.items, kind="input", id="span")[0]
        self.assertIn("min=6", span["details"])
        self.assertIn("max=168", span["details"])
        self.assertIn("property `Span` (Integer)", span["spotfire"])

    def test_gap_flags(self):
        found = gaps(self.items)
        self.assertIn(("st.date_input", "G10"), found)
        self.assertIn(("st.file_uploader", "G11"), found)
        self.assertIn(("st.tabs", "G11"), found)
        self.assertIn(("fill=tonexty", "G2"), found)
        self.assertIn(("go.Scatter(line.dash=dot)", "G3"), found)
        self.assertIn(("st.markdown", "G6"), found)

    def test_outputs_and_reactivity(self):
        widgets = [i["widget"] for i in self.items]
        self.assertEqual(widgets.count("st.metric"), 3)
        for widget in ("st.bar_chart", "st.dataframe", "st.plotly_chart", "add_hline",
                       "@st.cache_data", "st.dataframe(on_select=...)", "st.sidebar"):
            self.assertIn(widget, widgets)
        local = find(self.items, kind="data", widget="import engine")
        self.assertEqual(len(local), 1)

    def test_numbering_follows_source_order(self):
        numbers = [i["number"] for i in self.items]
        self.assertEqual(numbers, [f"E{n:02d}" for n in range(1, len(numbers) + 1)])
        first = self.items[0]["where"]
        self.assertTrue(first.startswith("app.py:"), first)


class ShinySampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = scan(SAMPLES / "shiny_pressure_app")

    def test_pages(self):
        pages = [i["label"] for i in find(self.items, kind="page")]
        self.assertEqual(pages, ["Overview", "Details"])
        nested = find(self.items, widget="ui.nav_panel in a navset")
        self.assertEqual({i["label"] for i in nested}, {"Table", "Notes"})
        self.assertTrue(all(i["gap"] == "G11" for i in nested))

    def test_inputs(self):
        inputs = {i["id"]: i for i in find(self.items, kind="input")}
        self.assertEqual(set(inputs), {"station", "pressure_band", "show_events", "run"})
        self.assertEqual(inputs["pressure_band"]["gap"], "G10")
        self.assertIn("PressureBandMin", inputs["pressure_band"]["spotfire"])
        self.assertIn("default=ST2", inputs["station"]["details"])

    def test_outputs_gaps_and_reactivity(self):
        found = gaps(self.items)
        self.assertIn(("add_vrect", "G1"), found)
        self.assertIn(("go.Scatter(line.dash=dot)", "G3"), found)
        widgets = [i["widget"] for i in self.items]
        for widget in ("@reactive.calc", "@reactive.effect", "reactive.value", "add_hrect",
                       "@render_plotly", "@render.data_frame", "ui.value_box"):
            self.assertIn(widget, widgets)
        effect = find(self.items, widget="@reactive.effect")[0]
        self.assertIn("input.run", effect["details"])
        trend = find(self.items, widget="@render_plotly")[0]
        self.assertIn("show_events", trend["details"])
        placeholders = find(self.items, widget="output_widget")
        self.assertEqual(placeholders, [], "placeholders with a render function are merged")


class DashSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = scan(SAMPLES / "dash_pump_fleet")

    def test_pages_and_inputs(self):
        self.assertEqual([i["label"] for i in find(self.items, kind="page")],
                         ["Fleet", "Pump Table"])
        inputs = {i["id"]: i for i in find(self.items, kind="input")}
        self.assertIn("multiSelectListbox", inputs["areas"]["spotfire"])
        self.assertEqual(inputs["flow-range"]["gap"], "G10")
        self.assertEqual(inputs["period"]["gap"], "G10")
        self.assertIn("export", inputs)

    def test_callbacks_and_gaps(self):
        callbacks = find(self.items, widget="@callback")
        self.assertEqual(len(callbacks), 2)
        selection = [c for c in callbacks if "selectedData" in c["details"]][0]
        self.assertIn("marking", selection["spotfire"])
        found = gaps(self.items)
        self.assertIn(("dcc.Interval", "G11"), found)
        self.assertIn(("template=plotly_dark", "G7"), found)
        scatter = find(self.items, widget="px.scatter")[0]
        self.assertIn("trendline=ols", scatter["details"])


class OtherFormatsTest(unittest.TestCase):
    QMD = """---
title: "Pump report"
format: dashboard
---

# Overview

## Row {height=30%}

```{python}
#| content: valuebox
#| title: "Pumps running"
dict(icon="gear", value=12)
```

## Row {.tabset}

```{python}
import plotly.express as px
fig = px.area(df, x="t", y="flow")
```

```{ojs}
viewof span = Inputs.range([1, 48], {label: "Span", value: 12})
```
"""
    HTML = """<html><head><style>.a{color:red}</style></head><body>
<SpotfireControl id="PH_pump" label="Pump" />
[SPOTFIRE ACTION: Run model]
<select id="area"></select><input type="range" id="span"><button>Run</button>
<details><summary>More</summary></details>
<script>Plotly.newPlot("d", [{"type":"scatter","fill":"tonexty"}], {});</script>
</body></html>
"""
    JSX = """import React, { useState, useMemo } from "react";
import { LineChart, Line, ReferenceArea, Brush } from "recharts";
export default function App() {
  const [pump, setPump] = useState("P-101");
  const rows = useMemo(() => data.filter(r => r.pump === pump), [pump]);
  return (<LineChart data={rows}><Line dataKey="v" strokeDasharray="4 2" />
    <ReferenceArea x1={3} x2={5} /><Brush /></LineChart>);
}
"""

    def test_quarto_html_react(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "report.qmd").write_text(self.QMD, encoding="utf-8")
            (root / "mock.html").write_text(self.HTML, encoding="utf-8")
            (root / "App.jsx").write_text(self.JSX, encoding="utf-8")
            items = scan(root)
        widgets = {i["widget"] for i in items}
        for widget in ("valuebox", "# heading", "Inputs.range", "SpotfireControl",
                       "SPOTFIRE ACTION", "<details>", "useState", "useMemo", "<LineChart>"):
            self.assertIn(widget, widgets)
        found = gaps(items)
        self.assertIn(("{.tabset}", "G11"), found)
        self.assertIn(("px.area", "G2"), found)
        self.assertIn(("fill=tonexty", "G2"), found)
        self.assertIn(("<ReferenceArea>", "G1"), found)
        self.assertIn(("<Brush>", "G4"), found)
        self.assertIn(("<Line strokeDasharray>", "G3"), found)

    def test_syntax_error_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.py"
            path.write_text("import streamlit as st\nst.slider('A', 0, 10\n", encoding="utf-8")
            items = scan(path)
        self.assertEqual(items[0]["widget"], "syntax error")


class CommandLineTest(unittest.TestCase):
    def test_writes_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "scan_prototype.py"),
                 str(SAMPLES / "streamlit_pump_monitor"), "--out", tmp],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            markdown = (Path(tmp) / "prototype-inventory.md").read_text(encoding="utf-8")
            data = json.loads((Path(tmp) / "prototype-inventory.json").read_text(
                encoding="utf-8"))
        self.assertIn("| # | Prototype element | Where | Spotfire element | Fidelity | "
                      "Substitute and reason | Owner decision |", markdown)
        self.assertIn("## Gaps to resolve with the owner", markdown)
        self.assertGreater(len(data["elements"]), 20)


class HandoffCheckTest(unittest.TestCase):
    def run_check(self, folder):
        return subprocess.run([sys.executable, str(SCRIPTS / "check_handoff.py"), str(folder)],
                              capture_output=True, text=True)

    def test_example_passes(self):
        result = self.run_check(EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("0 errors, 0 warnings", result.stdout)

    def test_shipped_readings_match_the_generator(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is needed")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "PUMP_READINGS.csv"
            subprocess.run([sys.executable, "-B",
                            str(EXAMPLE / "ingest" / "make_pump_readings.py"), "--out", str(out)],
                           check=True, capture_output=True)
            fresh = out.read_text(encoding="utf-8")
        shipped = (EXAMPLE / "data" / "PUMP_READINGS.csv").read_text(encoding="utf-8")
        self.assertEqual(fresh, shipped)

    def test_broken_copy_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "app"
            shutil.copytree(EXAMPLE, folder)
            spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
            spec["properties"][0]["name"] = "pump_id"
            spec["dataFunctions"][0]["inputs"][2]["name"] = "windowStart"
            spec["pages"][0]["layout"]["column"].pop(0)
            (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
            brief = (folder / "app-brief.md").read_text(encoding="utf-8")
            brief = brief.replace("## Refresh cadence", "## Refresh")
            brief = brief.replace("| Mean flow | L06 |", "| Mean flow | L99 |")
            (folder / "app-brief.md").write_text(brief, encoding="utf-8")
            result = self.run_check(folder)
        self.assertEqual(result.returncode, 1)
        out = result.stdout
        self.assertIn("property 'pump_id' is not PascalCase", out)
        self.assertIn("the names must be equal", out)
        self.assertIn("visual 'kpiBand' must appear exactly once", out)
        self.assertIn("section '## Refresh cadence' is missing", out)
        self.assertIn("refers to L99", out)


class ExampleDataFunctionTest(unittest.TestCase):
    """The ported data function reproduces the prototype engine on the same data."""

    def test_port_matches_engine(self):
        try:
            import numpy as np
            import pandas as pd
        except ImportError:
            self.skipTest("numpy and pandas are needed")
        sys.path.insert(0, str(SAMPLES / "streamlit_pump_monitor"))
        try:
            import engine
        finally:
            sys.path.pop(0)
        raw = engine.simulate_readings(days=60, seed=7)
        table = raw.rename(columns={
            "timestamp": "Timestamp (UTC)", "pump_id": "Pump ID",
            "flow_bpd": "Flow Rate (bbl/d)", "discharge_psi": "Discharge Pressure (psi)",
            "vibration_mms": "Vibration (mm/s)"})
        scope = {"PUMP_READINGS": table, "PumpId": "P-103",
                 "WindowStart": pd.Timestamp("2026-01-01"),
                 "WindowEnd": pd.Timestamp("2026-03-01"), "AlarmLevel": 4.5,
                 "SmoothingSpan": 48, "ForecastHours": 72, "ShowRaw": True}
        code = (EXAMPLE / "datafunctions" / "calculate_vibration_trend.py").read_text(
            encoding="utf-8")
        exec(compile(code, "calculate_vibration_trend.py", "exec"), scope)
        window = raw[raw["timestamp"] < pd.Timestamp("2026-03-01")]
        one = window[window["pump_id"] == "P-103"].sort_values("timestamp")
        smoothed = engine.smooth(one["vibration_mms"], 48)
        centre, lower, upper = engine.forecast(smoothed, 72)
        trend = scope["VIBRATION_TREND"]
        history = trend["Vibration Smoothed (mm/s)"].dropna().to_numpy()
        ahead = trend["Vibration Forecast (mm/s)"].dropna().to_numpy()
        self.assertTrue(np.allclose(history, smoothed.to_numpy(), atol=1e-3))
        self.assertTrue(np.allclose(ahead, centre, atol=1e-3))
        self.assertTrue(np.allclose(trend["Forecast Upper (mm/s)"].dropna(), upper, atol=1e-3))
        self.assertEqual(scope["HoursOverAlarm"],
                         int(engine.alarm_hours(one, 4.5).loc["P-103"]))
        self.assertEqual(len(scope["FLEET_LATEST"]), 4)
        self.assertEqual(scope["RowsInView"], len(window))


if __name__ == "__main__":
    unittest.main(verbosity=2)
