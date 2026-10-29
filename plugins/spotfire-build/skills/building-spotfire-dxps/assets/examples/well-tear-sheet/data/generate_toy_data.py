"""
generate_toy_data.py - synthetic dataset for the Well Tear Sheet example app.

Run with Spotfire's bundled Python (it has pandas and the spotfire package), from the example folder:
  "%SPOTFIRE_PYTHON%" data\generate_toy_data.py

Input : data/source_tear_sheet.json - synthetic annual economics of one well (not a real well or deal).
Output: data/<TABLE>.sbdf      one file per table, exact Spotfire column types
        data/csv/<TABLE>.csv   inspection copies
        html/header.html, html/diligence.html   text-area content (sanitizer-safe, inline styles)
        data/derived_summary.json               values the spec uses (payback date, checks)

Every annual number from the source is kept exactly. The monthly profile, the sensitivities and the
diligence flags are reconstructed from those numbers: monthly volumes and money items sum to the annual
totals, and sensitivity results are model deltas applied to the given base case.
"""
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd
import spotfire.sbdf as sbdf

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
SRC = json.load(open(os.path.join(HERE, "source_tear_sheet.json"), encoding="utf-8"))
META, KPI, ROWS = SRC["meta"], SRC["kpi"], SRC["rows"]
NRI, WI, DISC = META["nri"], META["wi"], META["disc"]
CALENDAR = ["2026", "2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034", "2035", "2036 to 2076"]

# --------------------------------------------------------------------------- complete the source
rem = ROWS[-1]
rem["gas_px"] = rem["gas_x"] / rem["n_gas"]
rem["g_boed"] = rem["g_boe"] / rem["days"]
rem["cum_fcf"] = ROWS[-2]["cum_fcf"] + rem["fcf"]
rem["cum_dfcf"] = ROWS[-2]["cum_dfcf"] + rem["dfcf"]
assert abs(rem["cum_fcf"] - SRC["pv_table"][0]["npv"]) < 1.0, "undiscounted total does not match pv_table rate 0"
assert abs(rem["cum_dfcf"] - KPI["npv10"]) < 1.0, "discounted total does not match NPV10"
assert abs(sum(r["g_oil"] for r in ROWS) - SRC["reserves"][0]["o"]) < 1.0, "gross oil does not match reserves"


# --------------------------------------------------------------------------- calendar
def add_months(d, n):
    m = d.month - 1 + n
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def days_in(d):
    return (add_months(d, 1) - d).days


START = dt.date(2026, 2, 1)                      # acquisition month (model month 0)
BLOCK_MONTHS = [r["months"] for r in ROWS]       # 11, 12 x 9, 483
N = sum(BLOCK_MONTHS)                            # 602 months: Feb-2026 .. Mar-2076
MONTHS = [add_months(START, k) for k in range(N)]
DAYS = np.array([days_in(d) for d in MONTHS], dtype=float)
BLOCK = np.repeat(np.arange(len(ROWS)), BLOCK_MONTHS)
PRODUCING = np.ones(N, dtype=bool)
PRODUCING[0] = False                             # first production Mar-2026
assert MONTHS[-1] == dt.date(2076, 3, 1)
EFFECTIVE = dt.date(2026, 1, 1)
T_MID = np.array([((d - EFFECTIVE).days + days_in(d) / 2.0) / 30.4375 for d in MONTHS])  # months, mid-month


# --------------------------------------------------------------------------- monthly volumes
def year_one_boe():
    """Gross BOE/d in Mar..Dec 2026: starts at the given peak, geometric decline matching the total."""
    peak_gross = KPI["peak_boed_n"] / NRI
    k = np.arange(1, 11)
    days = DAYS[k]
    target = ROWS[0]["g_boe"]
    lo, hi = 0.3, 1.0
    for _ in range(200):
        f = (lo + hi) / 2.0
        total = np.sum(peak_gross * f ** (k - 1) * days)
        lo, hi = (f, hi) if total < target else (lo, f)
    rate = peak_gross * f ** (k - 1)
    rate *= target / np.sum(rate * days)
    return rate


def year_one_split():
    """Split the year-1 BOE profile into oil and gas with a gas-oil ratio that ramps linearly to the
    year-2 average, so neither product steps at the Dec-2026 / Jan-2027 boundary. Annual oil and gas
    totals stay exact (boe = oil + gas / 6)."""
    boe = year_one_boe() * DAYS[1:11]
    gor_end = ROWS[1]["g_gas"] / ROWS[1]["g_oil"]
    target_oil = ROWS[0]["g_oil"]
    ramp = np.linspace(0.0, 1.0, 10)
    lo, hi = 0.0, gor_end
    for _ in range(200):
        start = (lo + hi) / 2.0
        gor = start + (gor_end - start) * ramp
        oil = boe / (1.0 + gor / 6.0)
        lo, hi = (start, hi) if oil.sum() > target_oil else (lo, start)
    oil *= target_oil / oil.sum()
    gas = (boe - oil) * 6.0
    return {"g_oil": oil, "g_gas": gas}


YEAR_ONE = year_one_split()


def product_volumes(key):
    """Monthly gross volumes for 'g_oil' or 'g_gas', summing exactly to the annual totals."""
    vol = np.zeros(N)
    vol[1:11] = YEAR_ONE[key]
    # anchors: last month of year 1, then the mid-point of years 2..10 (average daily rates)
    anchor_t = [T_MID[10]]
    anchor_r = [vol[10] / DAYS[10]]
    for y in range(1, 10):
        idx = np.where(BLOCK == y)[0]
        anchor_t.append(float(np.mean(T_MID[idx])))
        anchor_r.append(ROWS[y][key] / ROWS[y]["days"])
    anchor_t, log_r = np.array(anchor_t), np.log(np.array(anchor_r))

    def curve(log_r):
        slope = (log_r[-1] - log_r[-2]) / (anchor_t[-1] - anchor_t[-2])
        out = {}
        for y in range(1, 10):
            idx = np.where(BLOCK == y)[0]
            t = T_MID[idx]
            lr = np.interp(t, anchor_t, log_r)
            past = t > anchor_t[-1]
            lr[past] = log_r[-1] + slope * (t[past] - anchor_t[-1])
            out[y] = np.exp(lr) * DAYS[idx]
        return out, slope

    # move the year anchors until the smooth curve itself hits every annual total (anchor 0 is the
    # fixed year-1 end point), so the final per-year rescale is tiny and the curve has no steps
    for _ in range(60):
        vols, slope_end = curve(log_r)
        for y in range(1, 10):
            log_r[y] += math.log(ROWS[y][key] / vols[y].sum())
    vols, slope_end = curve(log_r)
    for y in range(1, 10):
        idx = np.where(BLOCK == y)[0]
        vol[idx] = vols[y] * ROWS[y][key] / vols[y].sum()
    # remaining block: start where year 10 trends to, constant decline solved to match the total
    idx = np.where(BLOCK == 10)[0]
    q0 = math.exp(log_r[-1] + slope_end * (T_MID[idx[0]] - anchor_t[-1]))
    months_from = np.arange(len(idx))
    target = ROWS[10][key]
    lo, hi = 1e-5, 3.0
    for _ in range(200):
        d = (lo + hi) / 2.0
        total = np.sum(q0 * np.exp(-d * months_from / 12.0) * DAYS[idx])
        lo, hi = (d, hi) if total > target else (lo, d)
    v = q0 * np.exp(-d * months_from / 12.0) * DAYS[idx]
    vol[idx] = v * target / v.sum()
    return vol, d


G_OIL, D_OIL = product_volumes("g_oil")
G_GAS, D_GAS = product_volumes("g_gas")
G_BOE = G_OIL + G_GAS / 6.0
N_OIL, N_GAS, N_BOE = G_OIL * NRI, G_GAS * NRI, G_BOE * NRI


# --------------------------------------------------------------------------- monthly money
def by_block(key):
    return np.array([ROWS[b][key] for b in BLOCK], dtype=float)


def allocate(total_key, weight):
    out = np.zeros(N)
    for y in range(len(ROWS)):
        idx = np.where(BLOCK == y)[0]
        w = weight[idx]
        if ROWS[y][total_key] and w.sum() > 0:
            out[idx] = ROWS[y][total_key] * w / w.sum()
    return out


OIL_REV = allocate("oil_x", N_OIL)
GAS_REV = allocate("gas_x", N_GAS)
REV = OIL_REV + GAS_REV
FIXED = np.where(PRODUCING, by_block("fixed") / by_block("well_mo"), 0.0)
VAR = allocate("var", N_BOE)
TGE = allocate("tge", N_GAS)
SEV = allocate("sev", REV)
ADVAL = allocate("adval", REV)
CAPEX = np.zeros(N)
CAPEX[0] = ROWS[0]["capex"]
CAPEX[-1] = ROWS[10]["capex"]                    # abandonment at the economic limit
ACQ = np.zeros(N)
ACQ[0] = ROWS[0]["acq"]
LOE = FIXED + VAR + TGE
TAXES = SEV + ADVAL
LIFT = LOE + TAXES
OPCF = REV - LIFT
FCF = OPCF - CAPEX - ACQ
DF = (1.0 + DISC) ** (-T_MID / 12.0)
DFCF = FCF * DF
SCALE = []
for y in range(len(ROWS)):
    idx = np.where(BLOCK == y)[0]
    s = ROWS[y]["dfcf"] / DFCF[idx].sum()
    SCALE.append(s)
    DFCF[idx] *= s
CUM_FCF = np.cumsum(FCF)
CUM_DFCF = np.cumsum(DFCF)
for y in range(len(ROWS)):
    idx = np.where(BLOCK == y)[0]
    for mk, rk in ((G_OIL, "g_oil"), (G_GAS, "g_gas"), (REV, "rev"), (LOE, "loe"), (TAXES, "taxes"),
                   (FCF, "fcf"), (DFCF, "dfcf")):
        assert abs(mk[idx].sum() - ROWS[y][rk]) < 0.01 * max(1.0, abs(ROWS[y][rk])) / 100.0, (y, rk)


def payback_months(cum, fcf):
    k = int(np.argmax(cum >= 0))
    if cum[k] < 0:
        return None
    return k + (-cum[k - 1] / fcf[k] if k > 0 else 0.0)


PAYBACK_MODEL = payback_months(CUM_FCF, FCF)


def months_to_date(m):
    whole = int(math.floor(m))
    d0 = add_months(START, whole)
    return d0 + dt.timedelta(days=round((m - whole) * days_in(d0)))


PAYBACK_DATE = months_to_date(KPI["payback"])


# --------------------------------------------------------------------------- economics model for sensitivities
def economics(oil_dp=0.0, gas_dp=0.0, loe_mult=1.0, capex_mult=1.0, delay=0, vol_mult=1.0):
    """Recompute monthly cash flows for a scenario and return PV10, NPV10, IRR, payback (model terms)."""
    n = N + delay
    pad = lambda a: np.concatenate([np.zeros(delay), a])[:n] if delay else a.copy()
    tax_rate = np.divide(TAXES, REV, out=np.zeros(N), where=REV > 0)
    n_oil, n_gas, n_boe = pad(N_OIL) * vol_mult, pad(N_GAS) * vol_mult, pad(N_BOE) * vol_mult
    oil_px = np.divide(OIL_REV, N_OIL, out=np.zeros(N), where=N_OIL > 0)
    gas_px = np.divide(GAS_REV, N_GAS, out=np.zeros(N), where=N_GAS > 0)
    rev = n_oil * (pad(oil_px) + np.where(n_oil > 0, oil_dp, 0.0)) + n_gas * (pad(gas_px) + np.where(n_gas > 0, gas_dp, 0.0))
    var_rate = np.divide(VAR, N_BOE, out=np.zeros(N), where=N_BOE > 0)
    tge_rate = np.divide(TGE, N_GAS, out=np.zeros(N), where=N_GAS > 0)
    loe = (pad(FIXED) + n_boe * pad(var_rate) + n_gas * pad(tge_rate)) * loe_mult
    taxes = rev * pad(tax_rate)
    opcf = rev - loe - taxes
    last = int(np.max(np.where(opcf > 0)[0]))     # economic limit: stop after the last positive month
    opcf[last + 1:] = 0.0
    capex = np.zeros(n)
    capex[delay] = ROWS[0]["capex"] * capex_mult  # completion moves with first production
    capex[last] += ROWS[10]["capex"]              # abandonment at the economic limit
    acq = np.zeros(n)
    acq[0] = ROWS[0]["acq"]
    t_mid = np.array([((add_months(START, k) - EFFECTIVE).days + days_in(add_months(START, k)) / 2.0) / 30.4375
                      for k in range(n)])
    df = (1.0 + DISC) ** (-t_mid / 12.0)
    pv10 = float(np.sum((opcf - capex) * df))
    npv10 = pv10 - float(np.sum(acq * df))
    fcf = opcf - capex - acq
    lo, hi = -0.0099, 0.2
    def npv_m(r):
        return float(np.sum(fcf / (1.0 + r) ** np.arange(n)))
    if npv_m(lo) * npv_m(hi) > 0:
        irr = None
    else:
        for _ in range(200):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if npv_m(mid) > 0 else (lo, mid)
        irr = (1.0 + (lo + hi) / 2.0) ** 12 - 1.0
    return {"pv10": pv10, "npv10": npv10, "irr": irr, "payback": payback_months(np.cumsum(fcf), fcf)}


BASE_MODEL = economics()
SCENARIOS = [
    ("Base case", {}),
    ("Oil price -$10/bbl", {"oil_dp": -10.0}),
    ("Oil price +$10/bbl", {"oil_dp": 10.0}),
    ("Gas price -$1.00/mcf", {"gas_dp": -1.0}),
    ("Gas price +$1.00/mcf", {"gas_dp": 1.0}),
    ("Lease operating expense +20%", {"loe_mult": 1.2}),
    ("Completion capex +15%", {"capex_mult": 1.15}),
    ("First production 6 months later", {"delay": 6}),
    ("Volumes -15%", {"vol_mult": 0.85}),
    ("Volumes +15%", {"vol_mult": 1.15}),
]
SENS = []
for order, (name, kw) in enumerate(SCENARIOS, start=1):
    m = economics(**kw)
    pv10 = KPI["pv10"] + (m["pv10"] - BASE_MODEL["pv10"])
    npv10 = KPI["npv10"] + (m["npv10"] - BASE_MODEL["npv10"])
    irr = None if m["irr"] is None else KPI["irr"] + (m["irr"] - BASE_MODEL["irr"])
    pb = None if m["payback"] is None else KPI["payback"] + (m["payback"] - BASE_MODEL["payback"])
    SENS.append({"Scenario": name, "Scenario Order": order, "PV10 ($)": pv10, "NPV10 ($)": npv10,
                 "IRR": irr, "Payback (months)": pb, "PV10 Change ($)": pv10 - KPI["pv10"]})


# --------------------------------------------------------------------------- tables
def frame(records, columns):
    df = pd.DataFrame.from_records(records, columns=columns)
    for c in df.columns:
        if df[c].dtype.name in ("str", "string") or df[c].dtype == object:
            if all(isinstance(v, str) or v is None for v in df[c]):
                df[c] = df[c].astype(object)
    return df


def date_col(values):
    return pd.Series(pd.to_datetime([pd.Timestamp(v) for v in values])).dt.date.astype(object)


tables = {}

summary = {
    "Well UID": META["uid"], "Category": META["cat"], "Development Status": META["type"].capitalize(),
    "Interest Type": META["interest"], "Working Interest": WI, "Net Revenue Interest": NRI,
    "Discount Rate": DISC, "Source File": META["src"],
    "PV10 ($)": KPI["pv10"], "Acquisition Price ($)": KPI["price"], "NPV10 ($)": KPI["npv10"],
    "IRR": KPI["irr"], "MOIC (x)": KPI["moic"], "Payback (months)": KPI["payback"],
    "Price per Net BOE ($/boe)": KPI["per_boe"], "All-in Cost per Net BOE ($/boe)": KPI["per_boe_all"],
    "Breakeven Oil NPV10 ($/bbl)": KPI["be_oil"], "Breakeven Oil 15% IRR ($/bbl)": SRC["be_oil_15"],
    "Peak Net Rate (boe/d)": KPI["peak_boed_n"], "Remaining Net Reserves (boe)": KPI["n_rem_boe"],
    "Completion Capex ($)": KPI["capex"], "Capex Headroom NPV10 ($)": SRC["be_capex"]["npv10"],
    "Capex Headroom 15% IRR ($)": SRC["be_capex"]["irr15"], "Oil Price Start ($/bbl)": META["oil_start"],
    "Oil Price Flat ($/bbl)": META["oil_flat"], "Gas Price Flat ($/mcf)": META["gas_flat"],
}
ws = frame([summary], list(summary.keys()))
ws.insert(8, "Effective Date", date_col([dt.date(2026, 1, 1)]))
ws.insert(9, "First Production", date_col([dt.date(2026, 3, 1)]))
ws.insert(10, "Acquisition Date", date_col([dt.date(2026, 2, 1)]))
ws.insert(11, "Economic Limit", date_col([dt.date(2076, 3, 1)]))
ws.insert(12, "Payback Date", date_col([PAYBACK_DATE]))
tables["WELL_SUMMARY"] = ws

annual = []
for i, r in enumerate(ROWS):
    annual.append({
        "Period": r["label"], "Period Order": i + 1, "Calendar Period": CALENDAR[i], "Model Year": i + 1,
        "Span": r["span"], "Months": r["months"], "Well Months": r["well_mo"], "Days": int(r["days"]),
        "Gross Oil (bbl)": r["g_oil"], "Gross Gas (mcf)": r["g_gas"], "Gross BOE (boe)": r["g_boe"],
        "Net Oil (bbl)": r["n_oil"], "Net Gas (mcf)": r["n_gas"], "Net BOE (boe)": r["n_boe"],
        "Oil Price ($/bbl)": r["oil_px"], "Gas Price ($/mcf)": r["gas_px"],
        "Oil Revenue ($)": r["oil_x"], "Gas Revenue ($)": r["gas_x"], "Revenue ($)": r["rev"],
        "Fixed LOE ($)": r["fixed"], "Variable LOE ($)": r["var"], "Gathering and Transport ($)": r["tge"],
        "LOE ($)": r["loe"], "Severance Tax ($)": r["sev"], "Ad Valorem Tax ($)": r["adval"],
        "Production Taxes ($)": r["taxes"], "Lifting Cost ($)": r["lift"], "Operating Cash Flow ($)": r["opcf"],
        "Capex ($)": r["capex"], "Acquisition ($)": r["acq"], "Free Cash Flow ($)": r["fcf"],
        "Discounted Free Cash Flow ($)": r["dfcf"], "Cumulative Free Cash Flow ($)": r["cum_fcf"],
        "Cumulative Discounted FCF ($)": r["cum_dfcf"], "Gross Rate (boe/d)": r["g_boed"],
        "Lifting Cost per BOE ($/boe)": r["lift"] / r["n_boe"], "LOE per BOE ($/boe)": r["loe"] / r["n_boe"],
    })
    for key in ("Revenue ($)", "LOE ($)", "Production Taxes ($)", "Lifting Cost ($)", "Operating Cash Flow ($)",
                "Capex ($)", "Acquisition ($)", "Free Cash Flow ($)", "Discounted Free Cash Flow ($)",
                "Cumulative Free Cash Flow ($)", "Cumulative Discounted FCF ($)", "Fixed LOE ($)",
                "Variable LOE ($)", "Gathering and Transport ($)", "Oil Revenue ($)", "Gas Revenue ($)"):
        annual[-1][key.replace("($)", "($K)")] = annual[-1][key] / 1000.0
tables["CASH_FLOW_ANNUAL"] = frame(annual, list(annual[0].keys()))

labels = [ROWS[b]["label"] for b in BLOCK]
monthly = pd.DataFrame({
    "Month": pd.Series([d for d in MONTHS], dtype=object),
    "Period": pd.Series(labels, dtype=object),
    "Model Year": (BLOCK + 1).astype("int64"),
    "Gross Oil Rate (bbl/d)": G_OIL / DAYS, "Gross Gas Rate (mcf/d)": G_GAS / DAYS,
    "Net Oil Rate (bbl/d)": N_OIL / DAYS, "Net Gas Rate (mcf/d)": N_GAS / DAYS, "Net BOE Rate (boe/d)": N_BOE / DAYS,
    "Net Oil (bbl)": N_OIL, "Net Gas (mcf)": N_GAS, "Net BOE (boe)": N_BOE,
    "Revenue ($)": REV, "LOE ($)": LOE, "Production Taxes ($)": TAXES, "Capex ($)": CAPEX, "Acquisition ($)": ACQ,
    "Operating Cash Flow ($)": OPCF, "Free Cash Flow ($)": FCF, "Discounted FCF ($)": DFCF,
    "Cumulative FCF ($)": CUM_FCF, "Cumulative Discounted FCF ($)": CUM_DFCF,
})
tables["PRODUCTION_MONTHLY"] = monthly

tables["PV_PROFILE"] = frame([{"Discount Rate": p["rate"] * 1.0, "PV ($)": p["pv"], "NPV after Price ($)": p["npv"]}
                              for p in SRC["pv_table"]], ["Discount Rate", "PV ($)", "NPV after Price ($)"])

be = [
    ("Oil breakeven, NPV10 = 0", KPI["be_oil"], "$/bbl"),
    ("Oil breakeven, 15% IRR", SRC["be_oil_15"], "$/bbl"),
    ("Max bid at 10% IRR", SRC["max_bid"][0]["bid"], "$"),
    ("Max bid at 15% IRR", SRC["max_bid"][1]["bid"], "$"),
    ("Max bid at 20% IRR", SRC["max_bid"][2]["bid"], "$"),
    ("Capex headroom, NPV10 = 0", SRC["be_capex"]["npv10"], "$"),
    ("Capex headroom, 15% IRR", SRC["be_capex"]["irr15"], "$"),
]
tables["BREAKEVENS"] = frame([{"Metric": m, "Value": v, "Unit": u, "Sort Order": i + 1} for i, (m, v, u) in enumerate(be)],
                             ["Metric", "Value", "Unit", "Sort Order"])

tables["RESERVES"] = frame([{"Reserves Case": r["item"], "Oil (bbl)": r["o"], "Gas (mcf)": r["g"], "BOE (boe)": r["boe"],
                             "Is Net": bool(r.get("key", False))} for r in SRC["reserves"]],
                           ["Reserves Case", "Oil (bbl)", "Gas (mcf)", "BOE (boe)", "Is Net"])

comps = [("Fixed", "fixed"), ("Variable", "var"), ("Gathering and transport", "tge"), ("Production taxes", "taxes")]
loe_rows = []
for y in range(10):
    for order, (name, key) in enumerate(comps, start=1):
        loe_rows.append({"Model Year": y + 1, "Period": ROWS[y]["label"], "Component": name, "Component Order": order,
                         "Cost per BOE ($/boe)": ROWS[y][key] / ROWS[y]["n_boe"]})
tables["LOE_PER_BOE"] = frame(loe_rows, ["Model Year", "Period", "Component", "Component Order", "Cost per BOE ($/boe)"])

tables["SENSITIVITIES"] = frame(SENS, ["Scenario", "Scenario Order", "PV10 ($)", "NPV10 ($)", "IRR",
                                       "Payback (months)", "PV10 Change ($)"])


# --------------------------------------------------------------------------- diligence flags (derived)
def money(v):
    s = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e6:
        return s + "$%.2fM" % (v / 1e6)
    return s + "$%.0fK" % (v / 1e3)


sens = {s["Scenario"]: s for s in SENS}
tail_boe_share = ROWS[10]["n_boe"] / KPI["n_rem_boe"]
tail_undisc = ROWS[10]["fcf"] / rem["cum_fcf"]
tail_pv = ROWS[10]["dfcf"] / KPI["npv10"]
yr2_vs_peak = 1.0 - ROWS[1]["g_boed"] / (KPI["peak_boed_n"] / NRI)
flags = [
    ("High", "15% hurdle not met",
     "IRR is %.1f%%. The maximum bid at a 15%% IRR is %s, so the %s price only clears a 10%% hurdle (maximum bid %s)."
     % (KPI["irr"] * 100, money(SRC["max_bid"][1]["bid"]), money(KPI["price"]), money(SRC["max_bid"][0]["bid"]))),
    ("High", "Completion capex drives the outcome",
     "Completion capex of %s is %.1f times the purchase price. A 15%% overrun moves PV10 by %s."
     % (money(KPI["capex"]), KPI["capex"] / KPI["price"], money(sens["Completion capex +15%"]["PV10 Change ($)"]))),
    ("Medium", "Oil breakeven above the long-term deck",
     "The NPV10 breakeven of $%.2f/bbl sits above the $%.2f/bbl flat deck. Oil $10/bbl lower moves PV10 by %s."
     % (KPI["be_oil"], META["oil_flat"], money(sens["Oil price -$10/bbl"]["PV10 Change ($)"])))
    if KPI["be_oil"] > META["oil_flat"] else
    ("Medium", "Thin margin over the long-term oil deck",
     "The NPV10 breakeven of $%.2f/bbl is $%.2f/bbl below the $%.2f/bbl flat deck. Oil $10/bbl lower moves PV10 by %s."
     % (KPI["be_oil"], META["oil_flat"] - KPI["be_oil"], META["oil_flat"],
        money(sens["Oil price -$10/bbl"]["PV10 Change ($)"]))),
    ("Medium", "Steep first-year decline",
     "Gross rate falls from a %.0f boe/d peak to a %.0f boe/d year-two average (%.0f%% lower)."
     % (KPI["peak_boed_n"] / NRI, ROWS[1]["g_boed"], yr2_vs_peak * 100)),
    ("Low", "Long tail carries undiscounted value",
     "Years after 2035 hold %.0f%% of remaining net BOE and %.0f%% of undiscounted cash flow, but discounted cash "
     "flow after 2035 adds %s to NPV10." % (tail_boe_share * 100, tail_undisc * 100, money(ROWS[10]["dfcf"]))),
    ("Low", "Location not provided",
     "The source case has no location, so offset wells, spacing and basin differentials cannot be checked."),
]
tables["DILIGENCE_FLAGS"] = frame([{"Severity": s, "Flag": f, "Detail": d, "Flag Order": i + 1} for i, (s, f, d) in enumerate(flags)],
                                  ["Severity", "Flag", "Detail", "Flag Order"])

notes = [
    "Economics are net to a %.0f%% working interest and a %.0f%% net revenue interest." % (WI * 100, NRI * 100),
    "Cash flows are pre-tax and unlevered, discounted at %.0f%% mid-month to the %s effective date." % (DISC * 100, META["eff"]),
    "Oil starts at $%.2f/bbl and declines to $%.2f/bbl flat; gas is $%.3f/mcf flat. Realized prices vary by year."
    % (META["oil_start"], META["oil_flat"], META["gas_flat"]),
    "Lease operating expense is fixed per well-month, variable per boe, plus gathering and transport per mcf. "
    "Production taxes are severance plus ad valorem, both a share of revenue.",
    "Completion capex of %s is spent in %s with first production in %s; %s of abandonment cost falls at the "
    "economic limit (%s)." % (money(KPI["capex"]), META["acq_date"], META["first_prod"], money(ROWS[10]["capex"]), META["end"]),
    "Sensitivities rerun the monthly model with an economic limit and apply the change to the base case.",
    "This test build reconstructs the monthly profile and sensitivities from the annual summary (toy data); "
    "annual totals match the source exactly.",
    "Source: %s, case %s." % (META["src"], META["uid"]),
]


# --------------------------------------------------------------------------- HTML text areas (inline styles only)
FONT = "font-family:Segoe UI,Arial,sans-serif;"
INK, INK2, INK3, HAIR = "#111110", "#4b4a46", "#8a8983", "#e2e1db"


def meta_cell(label, value):
    return ('<td style="padding:0 0 4px 22px;vertical-align:top;">'
            '<div style="font-size:10px;color:%s;">%s</div>'
            '<div style="font-size:11px;font-weight:600;color:%s;">%s</div></td>' % (INK3, label, INK, value))


header = (
    '<div style="%scolor:%s;background-color:#fcfcfa;padding:8px 12px 10px 12px;border-bottom:2px solid %s;">'
    '<table style="width:100%%;border-collapse:collapse;"><tr>'
    '<td style="vertical-align:bottom;">'
    '<div style="font-size:10px;color:%s;font-weight:600;">%s &#183; %s &#183; %s</div>'
    '<div style="font-size:22px;font-weight:600;margin:4px 0 2px 0;">%s</div>'
    '<div style="font-size:12px;color:%s;">Single-well acquisition tear sheet. Net to %.0f%% WI and %.0f%% NRI, pre-tax, '
    'unlevered, discounted at %.0f%% to %s.</div></td>'
    '<td style="vertical-align:bottom;text-align:right;"><table style="border-collapse:collapse;"><tr>%s%s%s</tr><tr>%s%s%s</tr></table></td>'
    '</tr></table></div>'
) % (FONT, INK, INK, INK2, META["cat"], META["type"].capitalize(), META["interest"], META["uid"], INK2,
     WI * 100, NRI * 100, DISC * 100, META["eff"],
     meta_cell("Effective", META["eff"]), meta_cell("Acquisition", META["acq_date"]),
     meta_cell("First production", META["first_prod"]), meta_cell("Economic limit", META["end"]),
     meta_cell("Location", "Not provided"), meta_cell("Source", META["src"]))

sev_color = {"High": "#ba2c48", "Medium": "#fb907b", "Low": "#8a8983"}
flag_html = "".join(
    '<tr><td style="width:10px;vertical-align:top;padding:7px 8px 7px 0;border-top:1px solid %s;">'
    '<div style="width:8px;height:8px;background-color:%s;margin-top:3px;"></div></td>'
    '<td style="vertical-align:top;padding:6px 0;border-top:1px solid %s;">'
    '<div style="font-size:11px;font-weight:600;color:%s;">%s <span style="font-weight:400;color:%s;font-size:10px;">%s</span></div>'
    '<div style="font-size:10.5px;color:%s;margin-top:2px;">%s</div></td></tr>'
    % (HAIR, sev_color[s], HAIR, INK, f, INK3, s, INK2, d) for s, f, d in flags)
notes_html = "".join('<li style="margin-bottom:4px;">%s</li>' % n for n in notes)
diligence = (
    '<div style="%scolor:%s;padding:4px 10px;">'
    '<div style="font-size:12.5px;font-weight:600;border-top:1px solid %s;padding-top:6px;margin-bottom:6px;">Diligence flags</div>'
    '<table style="width:100%%;border-collapse:collapse;">%s</table>'
    '<div style="font-size:12.5px;font-weight:600;border-top:1px solid %s;padding-top:6px;margin:12px 0 6px 0;">Method</div>'
    '<ol style="margin:0;padding-left:18px;color:%s;font-size:10px;">%s</ol></div>'
) % (FONT, INK, INK, flag_html, INK, INK2, notes_html)

os.makedirs(os.path.join(APP, "html"), exist_ok=True)
open(os.path.join(APP, "html", "header.html"), "w", encoding="utf-8").write(header + "\n")
open(os.path.join(APP, "html", "diligence.html"), "w", encoding="utf-8").write(diligence + "\n")


# --------------------------------------------------------------------------- write SBDF + CSV
os.makedirs(os.path.join(HERE, "csv"), exist_ok=True)
type_report = {}
for name, df in tables.items():
    path = os.path.join(HERE, name + ".sbdf")
    sbdf.export_data(df, path)
    back = sbdf.import_data(path)
    df.to_csv(os.path.join(HERE, "csv", name + ".csv"), index=False)
    type_report[name] = {"rows": len(back), "columns": {c: str(back[c].dtype) for c in back.columns}}

summary_out = {
    "paybackDate": PAYBACK_DATE.isoformat(),
    "paybackMonthsGiven": KPI["payback"],
    "paybackMonthsModel": PAYBACK_MODEL,
    "baseModel": BASE_MODEL,
    "terminalDecline": {"oil": D_OIL, "gas": D_GAS},
    "discountScale": SCALE,
    "tables": type_report,
}
json.dump(summary_out, open(os.path.join(HERE, "derived_summary.json"), "w", encoding="utf-8"), indent=2, default=str)
print(json.dumps({k: v for k, v in summary_out.items() if k != "tables"}, indent=2, default=str))
for name, info in type_report.items():
    print("%-20s %4d rows  %d columns" % (name, info["rows"], len(info["columns"])))
