---
name: generating-synthetic-process-data
description: Generates synthetic process historian data from first principles for demos, tests and anomaly-detection training sets, using a three-layer simulator (environment, operations state machine, equipment physics), Ornstein-Uhlenbeck coloured noise, slow drift, perturbation texture and an event catalog whose expected signatures are verified after generation. Covers train and holdout splits, Spotfire-ready outputs (event stamp columns, tag pivots, data function packaging) and scaling out to Databricks or Snowflake. Use when building or reviewing a simulator or synthetic dataset for pumps, pipelines, compressors, columns, exchangers, wells or chemical units, or when demo data must look like a real plant historian.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Generating synthetic process data

**Pending SME review:** the physics shortcuts, realism targets and typical values below have not yet been reviewed by an independent process SME.

Synthetic data for a process app has to survive a practitioner's first look: autocorrelated
noise, aperiodic operations, physically consistent cross-correlations, slow degradation, and
events that leave measurable signatures. Sine waves plus white noise do not. Every tag here
derives from physics driven by a small number of shared causes.

`scripts/simulator_skeleton.py` is a compact, tested example of the whole contract for a
pump station (three layers, OU noise, wear drift, four event subtypes, VERIFY harness,
spectral check, train and holdout split). Start from it or from its structure.

```bash
python scripts/simulator_skeleton.py --check             # generate, validate, print report
python scripts/simulator_skeleton.py --out <folder>      # also write historian.csv, events.csv
python scripts/tests/test_simulator_skeleton.py          # 6 tests, no Spotfire needed
```

## Research first

Ground the operating ranges for the domain before writing physics. Cite textbook and
standard values in the simulator header; where you cannot find a source, write `UNVERIFIED`
next to the constant and say so in the deliverable. A plausible invented number is worse
than a flagged one, because nobody can tell them apart later.

## Three layers, always

1. **Environment.** Per-region climatology: annual and diurnal temperature cycles (these
   are real) plus multi-day weather fronts from an Ornstein-Uhlenbeck process integrated
   once over the full horizon. Ambient feeds the physics: gas temperatures, cooler capacity,
   tank and buried-line temperatures that lag ambient.
2. **Operations.** A plant state machine: rate setpoints held for random multi-day periods
   (aperiodic, no synthetic rhythm), ramps with asymmetric time constants (fall fast,
   recover slowly), hot standby, turnarounds, trips, tank draws. Trip-class events drive
   this state machine so every tag responds coherently.
3. **Physics.** Every tag computed from rate, ambient and equipment health, per equipment
   class. See [references/physics-by-equipment.md](references/physics-by-equipment.md).

## Noise, drift and texture

- **All noise is coloured (OU), never white.** Exact discretisation:
  `x[i] = a*x[i-1] + s*eps`, `a = exp(-theta*dt)`, `s = sigma*sqrt((1 - a^2)/(2*theta))`.
  The correlation time is `1/theta`.
- **Cross-correlation comes only from shared drivers** (rate, ambient, health). Never inject
  a correlation matrix.
- **Slow drift**: exchanger fouling on the approach, catalyst decay, wear on pump head,
  instrument bias walks.
- **Texture**: spikes and dropouts as a micro-perturbation layer, separate from labelled
  events.
- **Controlled variables sit on setpoint** with small coloured control noise; the
  manipulated variable carries the load. A furnace outlet temperature is flat while fuel
  tracks rate.

## Events are a contract, not labels

- Families: Mechanical, Process, Electrical, Instrumentation, Operational. Name each subtype
  by its measurable effect ("High Discharge Temperature - Cooler Fouling", "Tower Flooding -
  High Differential Pressure"). Instrumentation covers freeze, drift and noise bursts.
- Register every subtype the scheduler can emit in `EVENT_CATALOG`. An unregistered subtype
  must fail with a KeyError, not pass silently.
- A `VERIFY` map declares each subtype's expected direction and magnitude band per tag, and
  a harness asserts every generated event against it.
- Stamp an `__Event_ID` column into the historian so Spotfire can relate series and events
  tables.
- Hold operating moves away from event windows and their verification baselines, or a
  setpoint change will be scored as (or will mask) an event signature.
- Never pad the horizon boundary with a terminal state. A ramp-boundary pad once marked
  every final sample as shut down and the whole fleet read offline.

Details and the validation suite: [references/events-and-validation.md](references/events-and-validation.md).

## Validation before shipping

1. Direction and magnitude check over `VERIFY` for every event.
2. Spectral check: no peak at one cycle per day on process tags after removing operating
   moves (the diurnal cycle belongs to ambient, not to pumped flow).
3. Shutdown thermal decay toward ambient and lagged recovery on restart.
4. Monotonicity sweep over every equipment curve family.
5. Realism statistics: trip crash and recovery times, setpoint hold distribution, rate
   variability at steady state.

## Machine learning dataset mode

A `Split` column with `train` and `test`. Defaults that worked for an anomaly-detection
demo: about 150 days of training with about 5 events of 1 to 3 days (about 5 percent
anomalous time), and about 45 days of held-out future with its own events. Report detection
performance on the holdout only. The `process-analytics-models` skill covers the detectors
and event-level scoring.

## Spotfire output

- An engine can double as a Python data function: input knobs (seed, horizon, fleet size,
  anomaly rate) and a numbered catalog of output tables, each naming the visual it feeds.
  Use the `writing-spotfire-data-functions` skill for staging blocks and SBDF-safe types
  (`np.nan` not `None`, concrete dtypes, native scalar casts).
- Historian-style outputs get a long tag table with an exact tag naming convention, plus an
  asset hierarchy mapping table.
- Keep generation deterministic: one `np.random.default_rng(seed)` per run, or per chunk
  with seeds derived from the chunk keys.
- For billions of rows, generate on cluster executors:
  [references/scaling-out.md](references/scaling-out.md).

## Self-review as the domain's senior engineer

Before delivering domain content, review the physics and the diagnostic logic as the
discipline's senior engineer would, and fix what would not survive that review. A review of
pump content once caught a wrong runout remedy, a missing speed signal and a wear diagnosis
made before instrument checks; [references/physics-by-equipment.md](references/physics-by-equipment.md)
lists those corrections.

## Status

The rules come from several simulators built and run on one machine and one Databricks
cluster. The skeleton and its tests are new for this library and run offline only; nothing
here has run inside Spotfire.

## References

- [references/physics-by-equipment.md](references/physics-by-equipment.md): physics
  shortcuts per equipment class, pump curve families, chemical process methods, wells,
  pipelines, review corrections.
- [references/events-and-validation.md](references/events-and-validation.md): event
  catalog design, VERIFY maps, the validation suite, realism targets.
- [references/scaling-out.md](references/scaling-out.md): Databricks `mapInPandas`,
  Snowflake chunked writes with a resume ledger, determinism checks, memory safety.
- [references/simulator-brief.md](references/simulator-brief.md): a fill-in brief for
  asking an agent to build a full simulator in one pass.
