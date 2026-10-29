"""
make_demo_csv.py - the two small tables of the Mod Layers Demo example app.

CPython standard library only; the output is the same on every run.
  data/csv/READINGS.csv  144 rows: pumps "Pump A" and "Pump B", hourly readings from
                         2026-01-01 00:00 to 2026-01-03 23:00 (Pressure (psig), Flow (bbl/d))
  data/csv/EVENTS.csv    6 rows: events E01 to E06, three per pump (Start, End, Severity)

Then write the SBDF files with Spotfire's own Python (exact column types), from the skill folder:
  "%SPOTFIRE_PYTHON%" scripts\sbdf_export.py assets\examples\mod-layers-demo\data\csv\READINGS.csv
      assets\examples\mod-layers-demo\data\READINGS.sbdf
      --types "Asset=String,Timestamp=DateTime,Pressure (psig)=Real,Flow (bbl/d)=Real"
  "%SPOTFIRE_PYTHON%" scripts\sbdf_export.py assets\examples\mod-layers-demo\data\csv\EVENTS.csv
      assets\examples\mod-layers-demo\data\EVENTS.sbdf
      --types "Event ID=String,Asset=String,Start=DateTime,End=DateTime,Severity=Real"
"""
import csv
import datetime as dt
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "csv")
START = dt.datetime(2026, 1, 1)
HOURS = 72
PUMPS = (("Pump A", 120.0, 2400.0, 0.0), ("Pump B", 95.0, 1800.0, 1.3))
EVENTS = (
    ("E01", "Pump A", 9, 13, 2.0),
    ("E02", "Pump A", 30, 31, 4.5),
    ("E03", "Pump A", 55, 61, 3.0),
    ("E04", "Pump B", 4, 6, 1.5),
    ("E05", "Pump B", 26, 34, 5.0),
    ("E06", "Pump B", 62, 64, 2.5),
)


def stamp(hour):
    return (START + dt.timedelta(hours=hour)).strftime("%Y-%m-%d %H:%M:%S")


def in_event(asset, hour):
    """Severity of the event running on this pump at this hour, else 0."""
    for _, pump, first, last, severity in EVENTS:
        if pump == asset and first <= hour <= last:
            return severity
    return 0.0


def readings():
    rows = []
    for asset, pressure, flow, phase in PUMPS:
        for hour in range(HOURS):
            day = math.sin(2.0 * math.pi * hour / 24.0 + phase)
            ripple = math.sin(2.0 * math.pi * hour / 5.0 + phase) * 0.6
            upset = in_event(asset, hour)
            rows.append([asset, stamp(hour),
                         "%.1f" % (pressure + 6.0 * day + ripple - 3.0 * upset + 0.05 * hour),
                         "%.1f" % (flow + 150.0 * day + 20.0 * ripple - 90.0 * upset)])
    return rows


def events():
    return [[eid, asset, stamp(first), stamp(last), "%.1f" % severity]
            for eid, asset, first, last, severity in EVENTS]


def write(name, header, rows):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print("%s: %d rows" % (path, len(rows)))


def main():
    os.makedirs(OUT, exist_ok=True)
    write("READINGS.csv", ["Asset", "Timestamp", "Pressure (psig)", "Flow (bbl/d)"], readings())
    write("EVENTS.csv", ["Event ID", "Asset", "Start", "End", "Severity"], events())


if __name__ == "__main__":
    main()
