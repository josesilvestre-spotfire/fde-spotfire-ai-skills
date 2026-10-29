# Simulator brief

A fill-in brief for asking an agent to build a complete first-principles historian simulator
in one pass. Fill in the bracketed fields and send the whole brief as one message.

---

Build a first-principles Python simulator that produces synthetic historian data realistic
enough to pass a practitioner's review, fully validated.

**Domain and fleet:** [for example "a 40-pump crude pipeline fleet across 5 regions" or "a
propane dehydrogenation unit feeding a C3 splitter"]

**Horizon and resolution:** [for example "150 days train and 45 days holdout at 5-minute
samples" or "10 years hourly"]

**Tag set:** [per-equipment tag roles, or "derive a realistic tag set per equipment class
and document it"]

**Purpose:** [anomaly-detection training set, demo data for a Spotfire app, or bulk data for
a compute demonstration. This decides which optional sections below apply.]

## Requirements

1. **Research first.** Ground operating ranges in textbooks, standards and vendor
   literature; cite every constant in the module header; mark anything unsourced
   `UNVERIFIED` and list those items at the end.
2. **Three layers.** Environment (climatology plus OU weather fronts integrated once),
   operations state machine (aperiodic setpoints, asymmetric ramps, trips, turnarounds,
   draws; no periodic rhythm; never pad the horizon end with a terminal state), physics per
   equipment class with every tag derived from rate, ambient and health.
3. **Noise and drift.** Coloured OU noise on every tag; correlation only through shared
   drivers; slow fouling, wear and bias drift; a spike and dropout texture layer separate
   from labelled events.
4. **Events as a contract.** Five families; subtypes named by measurable effect; every
   emittable subtype registered in `EVENT_CATALOG` (unregistered raises); a `VERIFY` map of
   expected directions and magnitude bands with a harness that asserts every generated
   event; trip-class events drive the state machine; `__Event_ID` stamp columns; per-subtype
   onset dynamics.
5. **Validation suite, run and reported.** VERIFY direction check, spectral check for a
   24-hour peak on process tags, shutdown thermal decay and recovery, monotonicity sweep of
   every curve family, realism statistics.
6. **[Machine learning mode]** `Split` column; training window with its own events and
   about 5 percent anomalous time; a held-out future window with its own events; detection
   performance on the holdout only, counted per event.
7. **[Spotfire mode]** Package as a Python data function: input knobs as document
   properties, a numbered catalog of output tables each naming its target visual, a long tag
   table with an exact tag naming convention, an asset mapping table, SBDF-safe dtypes.
8. **[Scale mode]** Seeded chunk tasks keyed by (plant, equipment, chunk), ready for a
   `mapInPandas` port, with deterministic per-chunk seeds.
9. Deterministic with `np.random.default_rng(seed)` throughout.
10. Before delivering, review the physics and diagnostic logic as the domain's senior
    engineer would and fix what would not survive that review. State every assumption at
    the end.

---

## Splitting a large digital twin into four briefs

For a large pipeline or geospatial twin, one brief produces too much at once. Split it into
four self-contained briefs, each producing only its section, each with exact names, dtypes
and limits and no TBD values:

1. Configuration, assets and geospatial: every parameter with its value, the equipment
   library with full specifications, station and system codes, route generation (haversine,
   coordinates, jitter), product definitions.
2. Commercial model and physics engine: contracts and rates, energy pricing, every physics
   function with complete formulas and constants, equipment curves, line resistance,
   equipment selection.
3. Lookup table and main simulation loop: the precomputed reference table, band selection
   logic, the loop and its inner solve, scenario logic, every output row structure and the
   complete results column list.
4. Map tables, time series pivot and final outputs: static map tables, the tag pivot with
   its exact naming convention, string casting and cleanup, every named output table.
