---
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

I need a small Spotfire Analyst 15.0 analysis for our pump station, built properly rather than
clicked together by hand. The data is `pump_readings.csv` (columns: Timestamp, Pump ID, Flow
bbl/d, Discharge Pressure psig, Status). I want:

- an "Overview" page with a line chart of flow over time colored by pump, a table of the latest
  readings, and a text area at the top with a drop-down to pick the pump and a "Reset" button that
  sets the pick back to P-101;
- the line chart should only show the picked pump;
- when the picked pump changes, a script should also write the pump's design flow into another
  document property.

Set up the app folder under `pump-monitor/` with the spec and the files it needs, and tell me
exactly what I have to run and click, what I will have to finish by hand in Analyst, and how I
check the saved DXP afterwards. I have not installed anything from this library yet.
