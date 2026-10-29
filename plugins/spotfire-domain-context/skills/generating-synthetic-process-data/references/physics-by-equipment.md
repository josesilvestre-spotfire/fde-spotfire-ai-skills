# Physics by equipment class

Shortcuts that make each tag follow from rate, ambient and equipment health. They are
deliberately simple: enough physics that cross-tag relationships hold, not a design model.
Numbers marked UNVERIFIED are design choices from earlier simulators, not sourced values.

## Compressors

- Discharge pressure = suction pressure x stage compression ratio.
- Discharge temperature rises with compression ratio and with interstage cooler fouling.
  Compare discharge temperature only at matched ratio.
- Surge appears as short oscillation bursts in flow and pressure. Earlier simulators used
  bursts of 2 to 6 minutes on minute data (UNVERIFIED; real surge cycles are much faster
  than a minute, so the burst is an envelope, not a cycle).

## Columns (towers)

- Column dP scales with vapour rate to roughly the 1.8 power (the turbulent friction
  exponent; an approximation).
- Tray temperatures are composition proxies at constant pressure only.
- Flooding raises both product impurities together; a duty problem moves one.

## Furnaces and fired heaters

- Coil outlet temperature is the controlled variable: on setpoint with small coloured
  control noise.
- Fuel flow is the manipulated variable and tracks rate and feed temperature.

## Pumps (centrifugal)

- **Curve families from five nameplate values**: rated flow at best efficiency point
  (BEP), rated head, rated efficiency, speed, NPSHr. Scale with the affinity laws
  (`Q ~ N`, `H ~ N^2`, `P ~ N^3`) and impeller trims.
- **Viscosity correction per ANSI/HI 9.6.7**, with the B parameter evaluated once at the
  rated (BEP) point and the resulting correction factors applied across the curve.
  Evaluating B per flow point produces a low-flow cliff and a kink at the clamp boundary.
  Run a monotonicity sweep over every curve family to catch it.
- **Evaluate every historian sample against the curve**: expected head, efficiency and
  power at measured flow, and NPSH available against NPSHr for the actual fluid at the
  actual temperature.
- **Diagnostic regions**: operation left of the preferred operating region suggests an
  oversized pump or recirculation (trim or speed control); beyond roughly 120 percent of BEP
  is runout, with thinning NPSH margin; a slow drift below the full-diameter curve is wear.
- A quadratic head curve `H = H0 * (1 - k * (Q/Q_design)^2)` is enough for demo data (the
  skeleton uses it).

### Corrections from a rotating-equipment review

Apply the same scrutiny to any domain before shipping:

- Include the speed signal in historian inputs whenever the content recommends variable
  speed drives.
- Runout is corrected by restoring system resistance, not by fitting a larger impeller.
- Do not diagnose wear before instrumentation and configuration checks.
- Do not overstate what affinity-law reconstruction from nameplate data can recover.
- Show efficiency curves alongside head curves.
- Attribute every industry statistic; drop the ones you cannot attribute.
- Keep nameplate value counts consistent and define every scored metric.
- Cover radial thrust and minimum continuous stable flow in low-flow damage discussions,
  and note the scope limits of ANSI/HI 9.6.7.

## Heat exchangers

- LMTD or effectiveness-NTU with a fouling resistance that drifts upward over months.
- The approach temperature carries the finding; absolute temperatures move with ambient.

## Tanks

- Level integrates inflow minus draws. Draws (ship or truck loading) arrive every few days
  at random intervals.
- Tank temperature lags ambient by about a day and a half in earlier simulators
  (UNVERIFIED).

## Shutdown and restart

- Temperatures decay toward ambient during an outage and recover with thermal lag on
  restart.
- Earlier fleet simulators used these shape targets (UNVERIFIED against plant data): a
  power-loss trip takes flow below 10 percent of rate within about 5 minutes, a restart
  reaches 90 percent in about 7 hours, and steady rate then holds at a coefficient of
  variation near 2 percent.

## Wells

- Arps hyperbolic decline for production, with completion and geology fields as enrichment
  columns.

## Pipelines

- Forward Darcy-Weisbach pressure drop with a Colebrook friction factor, bounded by MAOP
  and by NPSHr at each pump station.
- Routes generated with haversine distances between station coordinates, with small
  coordinate jitter for map layers.

## Chemical process units

- Vapour-liquid equilibrium with Antoine vapour pressures and modified Raoult's law.
- Reaction equilibria by Gibbs energy minimisation (for example propane dehydrogenation to
  propylene and hydrogen).
- Catalyst deactivation as power-law or exponential decay in activity.
- Langmuir-Hinshelwood kinetics for heterogeneous reactions.
- Columns by Fenske-Underwood-Gilliland shortcut and McCabe-Thiele stage stepping; exchangers
  by LMTD and NTU.
- References: Smith, Van Ness and Abbott, *Introduction to Chemical Engineering
  Thermodynamics*, 8th ed.; Seader and Henley, *Separation Process Principles*, 3rd ed.

## LNG values used in an earlier simulator

All UNVERIFIED; confirm against literature and the design basis before reuse:

| Quantity | Value used |
|---|---|
| Baseload liquefaction specific power | 0.30 to 0.40 kWh/kg |
| Propane-precooled mixed refrigerant specific power | about 280 to 330 kWh/t, design basis 310 with age and part-load penalties |
| Acid gas removal outlet CO2 | below 50 ppmv specification (commonly quoted), 20 to 35 ppmv in normal operation |
