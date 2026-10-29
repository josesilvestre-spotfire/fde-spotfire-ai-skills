"""Write ../data/PUMP_READINGS.csv from the sample prototype's simulator.

The readings are synthetic: the Streamlit sample's engine simulates hourly flow,
discharge pressure and vibration for four pumps. This script renames the columns
to the naming standard (Title Case with units) and rounds the values, so the
build step can convert the file to SBDF.

    python make_pump_readings.py [--days 60] [--seed 7]

Needs numpy and pandas.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent.parent.parent / "samples" / "streamlit_pump_monitor"

COLUMNS = {"timestamp": "Timestamp (UTC)", "pump_id": "Pump ID",
           "flow_bpd": "Flow Rate (bbl/d)", "discharge_psi": "Discharge Pressure (psi)",
           "vibration_mms": "Vibration (mm/s)"}


def readings(days=60, seed=7):
    sys.path.insert(0, str(ENGINE))
    try:
        import engine
    finally:
        sys.path.pop(0)
    table = engine.simulate_readings(days=days, seed=seed).rename(columns=COLUMNS)
    return table.round({"Flow Rate (bbl/d)": 1, "Discharge Pressure (psi)": 2,
                        "Vibration (mm/s)": 3})


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default=str(HERE.parent / "data" / "PUMP_READINGS.csv"))
    args = parser.parse_args()
    table = readings(args.days, args.seed)
    table.to_csv(args.out, index=False, date_format="%Y-%m-%d %H:%M:%S", lineterminator="\n")
    print(f"{len(table)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
