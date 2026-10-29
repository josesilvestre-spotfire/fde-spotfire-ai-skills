"""Calculation model of pipe_pressure_drop.xlsx: pressure drop per pipe segment.

The model reproduces the workbook as it is, including the behaviour listed in
change-list.md, so its outputs match the workbook's values. Each change in that
list goes in only after the owner approves it, followed by a new reconciliation.

Calculation IDs (L01 ...) refer to logic-spec.md.
"""

import math
import sys
from pathlib import Path

import pandas as pd

from excel_compat import (HIDDEN_ERRORS, ExcelError, average, div, iferror, log10, vlookup,
                          xmax, xsum)

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # inside a Spotfire data function there is no file
    HERE = Path(".")

# Data function interface: Spotfire parameter name -> model key.
PARAMETERS = {"FlowRate": "Inputs!B3", "FluidDensity": "Inputs!B4", "Viscosity": "Inputs!B5",
              "PipeAge": "Inputs!B6", "InletPressure": "Inputs!B8"}
TABLE_PARAMETERS = {"SEGMENTS": "Segments!A2:D21", "ROUGHNESS_BY_AGE": "Lookups!A3:B7"}
SPOTFIRE_OUTPUTS = ["SEGMENT_RESULTS", "TotalPressureDrop", "OutletPressure", "MaxVelocity",
                    "AverageGradient"]

# Inputs with the workbook's stored values.
INPUTS = {
    "Inputs!B3": 12000.0,   # Flow rate (bbl/d)
    "Inputs!B4": 53.0,      # Fluid density (lb/ft3)
    "Inputs!B5": 4.5,       # Viscosity (cP)
    "Inputs!B6": 25.0,      # Pipe age (years)
    "Inputs!B8": 950.0,     # Inlet pressure (psi)
    "Calc!G14": 0.35,       # friction loss typed over the formula of segment 10 (C4)
}

TABLES = {"Segments!A2:D21": "../data/SEGMENTS.csv",
          "Lookups!A3:B7": "../data/ROUGHNESS_BY_AGE.csv"}

OUTPUTS = ["Velocity (ft/s)", "Friction Loss (psi)", "Segment Drop (psi)",
           "Outlet Pressure (psi)", "Pressure Gradient (psi/ft)", "Total Pressure Drop (psi)",
           "Outlet Pressure at Line End (psi)", "Maximum Velocity (ft/s)",
           "Average Gradient (psi/ft)"]

OVERRIDE_SEGMENT = 10      # Calc!G14 holds a typed value (change C4)
BROKEN_SEGMENT = 15        # Calc!F19 reads the diameter of segment 1 (change C2)


def run(inputs=None, tables=None):
    """Return {output name: value or {segment: value}}."""
    x = dict(INPUTS)
    x.update(inputs or {})
    t = tables if tables is not None else load_tables()
    segments = t["Segments!A2:D21"]
    lookup = t["Lookups!A3:B7"]
    flow, density, viscosity = x["Inputs!B3"], x["Inputs!B4"], x["Inputs!B5"]

    # L01 Roughness: range lookup on the age table as stored (change C1)
    roughness = vlookup(x["Inputs!B6"], lookup.values.tolist(), 2)

    first_diameter = float(segments["Inner Diameter (in)"].iloc[0])
    velocity, friction, drop, outlet, gradient = {}, {}, {}, {}, {}
    pressure = x["Inputs!B8"]
    for row in segments.itertuples(index=False):
        seg = int(row[0])
        length, diameter, elevation = float(row[1]), float(row[2]), float(row[3])
        # L02 Velocity (ft/s)
        v = flow * 5.615 / 86400 / (math.pi * (diameter / 12) ** 2 / 4)
        # L03 Reynolds number
        reynolds = 1488 * density * v * (diameter / 12) / viscosity
        # L04 Friction factor, Swamee-Jain
        d_f = first_diameter if seg == BROKEN_SEGMENT else diameter
        f = 0.25 / log10(roughness / (3.7 * d_f) + 5.74 / reynolds ** 0.9) ** 2
        # L05 Friction loss (psi)
        if seg == OVERRIDE_SEGMENT:
            g = x["Calc!G14"]
        else:
            g = f * (length / (diameter / 12)) * density * v ** 2 / (2 * 32.174) / 144
        # L06 Elevation loss, in kPa as in the workbook (change C3)
        h = density * elevation / 144 * 6.894757
        # L07 Segment drop
        d = g + h
        # L08 Outlet pressure, running from the inlet
        pressure = pressure - d
        # L09 Pressure gradient; a zero-length segment gives #DIV/0! (change C5)
        try:
            grad = div(d, length)
        except ExcelError as exc:
            grad = exc.code
        velocity[seg], friction[seg], drop[seg] = v, g, d
        outlet[seg], gradient[seg] = pressure, grad

    last = max(outlet)
    return {
        "Velocity (ft/s)": velocity,
        "Friction Loss (psi)": friction,
        "Segment Drop (psi)": drop,
        "Outlet Pressure (psi)": outlet,
        "Pressure Gradient (psi/ft)": gradient,
        "Total Pressure Drop (psi)": xsum(list(drop.values())),                  # L10
        "Outlet Pressure at Line End (psi)": outlet[last],                      # L08
        "Maximum Velocity (ft/s)": xmax(list(velocity.values())),               # L11
        "Average Gradient (psi/ft)": iferror(                                   # L12
            lambda: average(list(gradient.values())), 0.0, "Summary!B7"),
    }


def spotfire_outputs(result):
    """The data function outputs: one table per segment and four single values."""
    segs = sorted(result["Outlet Pressure (psi)"])
    numeric = [g if isinstance(g, float) else None
               for g in (result["Pressure Gradient (psi/ft)"][s] for s in segs)]
    table = pd.DataFrame({
        "Segment": [float(s) for s in segs],
        "Velocity (ft/s)": [result["Velocity (ft/s)"][s] for s in segs],
        "Friction Loss (psi)": [result["Friction Loss (psi)"][s] for s in segs],
        "Segment Drop (psi)": [result["Segment Drop (psi)"][s] for s in segs],
        "Outlet Pressure (psi)": [result["Outlet Pressure (psi)"][s] for s in segs],
        "Pressure Gradient (psi/ft)": pd.Series(numeric, dtype="float64"),
    })
    return {"SEGMENT_RESULTS": table,
            "TotalPressureDrop": result["Total Pressure Drop (psi)"],
            "OutletPressure": result["Outlet Pressure at Line End (psi)"],
            "MaxVelocity": result["Maximum Velocity (ft/s)"],
            "AverageGradient": result["Average Gradient (psi/ft)"]}


def load_tables(folder=HERE):
    """Read the raw data and lookup tables of the app folder."""
    return {key: pd.read_csv(Path(folder) / path) for key, path in TABLES.items()}


def _rows(name, value):
    if isinstance(value, dict):
        return [(name, k, v) for k, v in value.items()]
    return [(name, 1, value)]


if __name__ == "__main__":
    import argparse
    import csv

    parser = argparse.ArgumentParser(description="Run the model and write its outputs.")
    parser.add_argument("--out", default="actual-model.csv")
    args = parser.parse_args()
    del HIDDEN_ERRORS[:]
    result = run()
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case", "output", "index", "value"])
        for name, value in result.items():
            for row in _rows(name, value):
                writer.writerow(["stored", *row])
    for item in HIDDEN_ERRORS:
        print(f"hidden error {item['error']} at {item['where']}", file=sys.stderr)
    print(f"wrote {args.out}")
