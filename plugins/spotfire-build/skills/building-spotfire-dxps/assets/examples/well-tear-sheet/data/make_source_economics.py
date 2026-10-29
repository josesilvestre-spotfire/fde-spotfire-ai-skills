"""
make_source_economics.py - writes data/source_tear_sheet.json for the Well Tear Sheet example.

Every number is synthetic. The well is a drilled but uncompleted (DUC) oil well with an Arps
hyperbolic decline that switches to a terminal exponential decline, a simple price deck, fixed and
variable operating cost, gathering and transport, severance and ad valorem tax, completion capex and
an acquisition price. The script models 602 months (Feb-2026 to Mar-2076), aggregates them into
the annual rows the example uses, and computes the headline economics from the same monthly cash
flows, so every total in the JSON is consistent with the rows.

Run with any Python 3.10+ (standard library only), from the example folder:
  python data/make_source_economics.py
Then run data/generate_toy_data.py with Spotfire's Python to write the SBDF files.
"""
import datetime as dt
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- assumptions (synthetic)
WI, NRI, DISC = 1.0, 0.75, 0.10
QI_OIL = 420.0          # gross oil rate in the first producing month, bbl/d
B_FACTOR = 1.1          # Arps b
DI_NOMINAL = 2.0        # initial nominal decline, 1/yr
D_TERMINAL = 0.07       # terminal exponential decline, 1/yr
GOR_START, GOR_END, GOR_YEARS = 2.2, 4.5, 15.0   # mcf/bbl, linear ramp
OIL_START, OIL_FLAT = 72.0, 63.0                 # realized oil price, $/bbl
GAS_START, GAS_FLAT = 3.40, 3.10                 # realized gas price, $/mcf
DECK_YEARS = 4                                   # years to reach the flat price
FIXED_PER_WELL_MONTH = 1250.0                    # $ per producing month
VAR_PER_BOE = 2.40                               # $ per gross boe
TGE_PER_MCF = 0.30                               # gathering and transport, $ per gross mcf
SEV_OIL, SEV_GAS, ADVAL = 0.046, 0.075, 0.020    # tax rates on revenue
COMPLETION_CAPEX = 9_500_000.0                   # spent in the acquisition month
ABANDONMENT = 120_000.0                          # spent in the last month
PRICE = 900_000.0                                # acquisition price, paid in Feb-2026

START = dt.date(2026, 2, 1)
EFFECTIVE = dt.date(2026, 1, 1)
BLOCK_MONTHS = [11] + [12] * 9 + [483]
LABELS = ["Yr %d" % (i + 1) for i in range(10)] + ["Remaining"]


def add_months(d, n):
    m = d.month - 1 + n
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def days_in(d):
    return (add_months(d, 1) - d).days


N = sum(BLOCK_MONTHS)
MONTHS = [add_months(START, k) for k in range(N)]
DAYS = [days_in(d) for d in MONTHS]
T_MID = [((d - EFFECTIVE).days + days_in(d) / 2.0) / 30.4375 for d in MONTHS]


def oil_rate(t_years):
    """Arps hyperbolic decline with a switch to exponential at D_TERMINAL."""
    d_t = DI_NOMINAL / (1.0 + B_FACTOR * DI_NOMINAL * t_years)
    if d_t > D_TERMINAL:
        return QI_OIL * (1.0 + B_FACTOR * DI_NOMINAL * t_years) ** (-1.0 / B_FACTOR)
    t_sw = (DI_NOMINAL / D_TERMINAL - 1.0) / (B_FACTOR * DI_NOMINAL)
    q_sw = QI_OIL * (1.0 + B_FACTOR * DI_NOMINAL * t_sw) ** (-1.0 / B_FACTOR)
    return q_sw * math.exp(-D_TERMINAL * (t_years - t_sw))


def deck(start, flat, year):
    if year >= DECK_YEARS:
        return flat
    return start + (flat - start) * year / DECK_YEARS


def monthly(oil_scale=1.0):
    rows = []
    for k, d in enumerate(MONTHS):
        producing = k >= 1
        t = (k - 1 + 0.5) / 12.0
        year = (k - 1) / 12.0
        g_oil = oil_rate(t) * DAYS[k] if producing else 0.0
        gor = GOR_START + (GOR_END - GOR_START) * min(max(t, 0.0) / GOR_YEARS, 1.0)
        g_gas = g_oil * gor
        g_boe = g_oil + g_gas / 6.0
        oil_px = deck(OIL_START, OIL_FLAT, max(year, 0.0)) * oil_scale
        gas_px = deck(GAS_START, GAS_FLAT, max(year, 0.0))
        n_oil, n_gas, n_boe = g_oil * NRI, g_gas * NRI, g_boe * NRI
        oil_x, gas_x = n_oil * oil_px, n_gas * gas_px
        rev = oil_x + gas_x
        g_fixed = FIXED_PER_WELL_MONTH if producing else 0.0
        g_var = VAR_PER_BOE * g_boe
        g_tge = TGE_PER_MCF * g_gas
        fixed, var, tge = g_fixed * WI, g_var * WI, g_tge * NRI
        loe = fixed + var + tge
        sev = SEV_OIL * oil_x + SEV_GAS * gas_x
        adval = ADVAL * rev
        taxes = sev + adval
        lift = loe + taxes
        opcf = rev - lift
        capex = (COMPLETION_CAPEX if k == 0 else 0.0) + \
            (ABANDONMENT if k == N - 1 else 0.0)
        acq = PRICE if k == 0 else 0.0
        rows.append(dict(
            g_oil=g_oil, g_gas=g_gas, g_boe=g_boe, n_oil=n_oil, n_gas=n_gas,
            n_boe=n_boe, rev=rev, fixed=fixed, var=var, tge=tge, loe=loe,
            sev=sev, adval=adval, taxes=taxes, lift=lift, opcf=opcf,
            capex=capex, acq=acq, fcf=opcf - capex - acq, oil_x=oil_x,
            gas_x=gas_x, g_loe=g_fixed + g_var + g_tge, g_fixed=g_fixed,
            g_var=g_var, g_tge=g_tge, well_mo=1.0 if producing else 0.0,
            days=float(DAYS[k]), oil_px=oil_px, gas_px=gas_px))
    return rows


def disc_factor(rate, k):
    return (1.0 + rate) ** (-T_MID[k] / 12.0)


def npv(rows, rate, include_acq=True):
    return sum((r["fcf"] if include_acq else r["fcf"] + r["acq"]) *
               disc_factor(rate, k) for k, r in enumerate(rows))


def solve(fn, lo, hi):
    f_lo = fn(lo)
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = fn(mid)
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def main():
    rows = monthly()
    sums = ("g_oil g_gas g_boe n_oil n_gas n_boe rev fixed var tge loe sev "
            "adval taxes lift opcf capex acq fcf oil_x gas_x g_loe g_fixed "
            "g_var g_tge well_mo days").split()
    annual, k0, cum_fcf, cum_dfcf = [], 0, 0.0, 0.0
    for i, months in enumerate(BLOCK_MONTHS):
        block = range(k0, k0 + months)
        row = {s: sum(rows[k][s] for k in block) for s in sums}
        row["dfcf"] = sum(rows[k]["fcf"] * disc_factor(DISC, k) for k in block)
        first, last = MONTHS[k0], MONTHS[k0 + months - 1]
        row["label"] = LABELS[i]
        row["span"] = "%s to %s" % (first.strftime("%b-%y"),
                                    last.strftime("%b-%y"))
        row["months"] = months
        row["oil_px"] = row["oil_x"] / row["n_oil"]
        if i < len(BLOCK_MONTHS) - 1:
            row["gas_px"] = row["gas_x"] / row["n_gas"]
            row["g_boed"] = row["g_boe"] / row["days"]
            cum_fcf += row["fcf"]
            cum_dfcf += row["dfcf"]
            row["cum_fcf"], row["cum_dfcf"] = cum_fcf, cum_dfcf
        annual.append(row)
        k0 += months

    pv_table = [{"rate": r, "pv": npv(rows, r, include_acq=False),
                 "npv": npv(rows, r)} for r in (0, 0.1, 0.15, 0.2, 0.3)]
    t_acq = T_MID[0] / 12.0
    irr_monthly = solve(lambda r: sum(x["fcf"] * (1 + r) ** (-k)
                                      for k, x in enumerate(rows)),
                        0.0, 0.5)
    cum, payback = 0.0, None
    for k, r in enumerate(rows):
        cum += r["fcf"]
        if cum >= 0 and payback is None:
            prev = cum - r["fcf"]
            payback = k - 1 + (-prev / r["fcf"])
    rem_net = sum(r["n_boe"] for r in rows)
    peak = max(r["n_boe"] / r["days"] for r in rows)

    def npv_at_oil(scale, rate):
        return npv(monthly(scale), rate)

    be_oil = OIL_FLAT * solve(lambda s: npv_at_oil(s, DISC), 0.2, 3.0)
    be_oil_15 = OIL_FLAT * solve(lambda s: npv_at_oil(s, 0.15), 0.2, 3.0)
    npv10 = npv(rows, DISC)
    kpi = {
        "pv10": pv_table[1]["pv"], "price": PRICE, "npv10": npv10,
        "irr": (1.0 + irr_monthly) ** 12 - 1.0,
        "moic": sum(r["opcf"] for r in rows) /
        (sum(r["capex"] for r in rows) + PRICE),
        "payback": payback,
        "per_boe": PRICE / rem_net,
        "per_boe_all": (PRICE + COMPLETION_CAPEX) / rem_net,
        "be_oil": be_oil, "peak_boed_n": peak, "n_rem_boe": rem_net,
        "capex": COMPLETION_CAPEX,
    }
    src = {
        "_note": ("Synthetic single-well economics for the example app, "
                  "written by make_source_economics.py (not a real well, "
                  "operator or deal). The 'Remaining' row (rows[10]) has no "
                  "gas_px, g_boed, cum_fcf or cum_dfcf; generate_toy_data.py "
                  "derives them from the other fields (gas_x / n_gas, "
                  "g_boe / days, and the cumulative sums)."),
        "meta": {"uid": "DEMO-WELL-001", "location": None,
                 "interest": "Working interest", "wi": WI, "nri": NRI,
                 "disc": DISC, "eff": "Jan 01, 2026", "end": "Mar-2076",
                 "cat": "DUC", "type": "undeveloped",
                 "src": "make_source_economics.py",
                 "first_prod": "Mar-2026", "acq_date": "Feb-2026",
                 "years": 10, "oil_start": OIL_START, "oil_flat": OIL_FLAT,
                 "gas_flat": GAS_FLAT},
        "kpi": kpi,
        "pv_table": pv_table,
        "max_bid": [{"irr": r, "bid": npv(rows, r, include_acq=False) *
                     (1.0 + r) ** t_acq} for r in (0.1, 0.15, 0.2)],
        "be_capex": {"npv10": npv10 * (1.0 + DISC) ** t_acq,
                     "irr15": npv(rows, 0.15) * 1.15 ** t_acq},
        "be_oil_15": be_oil_15,
        "reserves": [
            {"item": "Remaining gross", "o": sum(r["g_oil"] for r in rows),
             "g": sum(r["g_gas"] for r in rows),
             "boe": sum(r["g_boe"] for r in rows)},
            {"item": "Remaining net", "o": sum(r["n_oil"] for r in rows),
             "g": sum(r["n_gas"] for r in rows), "key": True,
             "boe": rem_net}],
        "rows": annual,
    }
    path = os.path.join(HERE, "source_tear_sheet.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(src, f, indent=1)
        f.write("\n")
    print("wrote %s: NPV10 %.0f, IRR %.1f%%, PV10 %.0f, net reserves %.0f boe"
          % (path, npv10, kpi["irr"] * 100, kpi["pv10"], rem_net))


if __name__ == "__main__":
    main()
