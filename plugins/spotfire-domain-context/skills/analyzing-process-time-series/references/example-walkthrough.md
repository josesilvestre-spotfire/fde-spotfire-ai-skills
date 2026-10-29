# The synthetic example

A complete four-layer instance (engine, pack, profile, bundle) built on synthetic data. It
gives the engine something concrete to run against, and it is the regression baseline: read
this file before you change any threshold.

```
assets/examples/
  make_data.py                  generates the export; seeded, so the output is reproducible
  example-pack/                 LAYER 2  a pack: class knowledge
    pack.yaml
    schema/extensions.yaml      contributes unit_class and persona vocabulary
    units/flow-segment.yaml     the class card: physics, invariants, failure modes
  example-profile/              LAYER 3  a profile: deployment facts
    profile.yaml
    tagmap.yaml                 column names -> role ids
    calibration.yaml            this asset's measured operating bands
    data.csv                    401 rows x 12 columns
  bundles/example-agent.yaml    LAYER 4  a bundle: the named, deliverable selection
  example-report.md             the committed output of the run below
```

Run it from the skill's `scripts/` folder:

```bash
python -m tssme packs                 # layer 2 discovered
python -m tssme profiles              # layer 3 discovered
python -m tssme bundles --show example-agent
python -m tssme analyse --profile example-segment --out ../assets/examples/example-report.md
python ../assets/examples/make_data.py   # regenerate the data (seed 20260916)
```

## What the example demonstrates

**The input contract, and nothing narrower.** A wide frame, a timestamp index, N columns of
sensors and conditions. The column names follow an ISA instrument convention (`PI-1001.PV`,
`LAB.DENSITY`) with no asset suffix. Naming is the tag map's business; if the engine starts
assuming a naming convention, this example stops resolving.

**No layer leaks into the one below it.** The class card carries no operating bands, no tag
names and no data path. The calibration overlay carries bands and nothing else.
`apply_calibration` refuses it if it tries to add a role, an invariant or a failure mode,
because an overlay that can redefine physics is a fork of the knowledge base.

**A pack is external.** `example-pack` contributes two enum values (`flow_segment`,
`example_analyst`) that the engine has never heard of, and the engine merges them without
knowing the pack exists.

## Planted faults and the checks that must catch them

Each row is a fault written into `make_data.py`. A row that stops being detected is a
regression in the engine, not a change in the data. `test_example_profile_runs_end_to_end`
asserts the same table in code.

| # | Planted in the data | Represents | Expected detection | Current result |
|---|---|---|---|---|
| 1 | `AI-1006.PV` constant at 12 ppm for all 400 samples | A fixed-dose tag, a frozen transmitter, or a manual constant | `dq_flatline` | HIGH, longest run 400 |
| 2 | Trailing row with every value blank but the timestamp | Snapshot or append export artifact | `dq_partial_rows` | MEDIUM, 1 row, blanked before analysis |
| 3 | `FI-1004.PV (2)` duplicating `FI-1004.PV` | A join duplicate from SQL, a data relation or a merge | Resolution warning plus `dq_duplicate_series` | Warned, then LOW, identical values |
| 4 | Temperature clipped to `[20, 36]`, 6 samples pinned at each end | Transmitter span, or an upstream clamp keeping a model input in domain | `dq_rail_saturation` | MEDIUM, 12 pinned, unclamped interior reported |
| 5 | Density sampled every 168 samples and held | Lab cadence merged into a SCADA frame | `dq_zero_order_hold` | MEDIUM, 2 updates over 400 samples |
| 6 | Detector column flagging `roc > 0` | An alarm thresholded on sign rather than magnitude | `stat_detector_firing_rate` | HIGH, fires on 50.2% |
| 7 | Restriction ramp reaching 7% from sample 240 | Progressive degradation: deposition, fouling, wear | `stat_regime_drift` on `residual` | HIGH, +4.32 kPa/month, t=16.1 |
| 7a | The same ramp, seen as model error | A model quality target being missed | `phys_range` on `residual_pct` (normative band) | HIGH, outside +/-5% on 28.5% of samples |
| 7b | The same ramp, seen as bias | `residual_centred` invariant | `stat_residual_bias` | MEDIUM, mean +3.50 against +/-3 |
| 8 | Step of 3% at sample 120 | A discrete cause: valve, batch interface, recalibration | `stat_changepoint` on `residual` | MEDIUM, 3.5 sd (see the lag note below) |
| 9 | No `pump_speed` column anywhere | An invariant whose precondition the data cannot evidence | `efficiency_at_reference` reported **not evaluated** | Listed as a coverage gap, not as a pass |

The relationships that must **not** fire matter as much:

| Relationship | Why it must stay clean | Current result |
|---|---|---|
| `residual == measured_dp - predicted_dp` | The identity is true by construction; a violation would mean the engine misaligned columns | Verified across 400 samples |
| `inlet_pressure > outlet_pressure` | The blank trailing row must not read as a violation (`NaN > NaN` is `False` in pandas, so an operand mask is required) | Verified across 400 evaluable samples |
| `measured_dp ~ flow ** 2` (tol 0.3) | Turbulent friction; the planted faults are small enough not to bend the exponent out of tolerance | Verified, observed 1.88 |

## Known limitations the example exposes

These are documented rather than tuned away. Adjusting a threshold until this one dataset
looks clean would fit the engine to the example.

**Changepoint detection lag.** The step at sample 120 is reported near sample 210. CUSUM is
scaled by the series' global spread, which the fault itself inflates, so detection lags the
event by tens of samples when the shift is comparable to the series' own variation. The scale
is global on purpose: a noise-only scale detects faster but shatters a slowly ramping series
into dozens of segments, and those segments are used as operating regimes. Treat a reported
changepoint as "somewhere in this neighbourhood".

**A smooth swing can be reported as a step.** Temperature here is a slow sinusoid, and it
draws a MEDIUM changepoint at 2.1 sd against a 2.0 sd gate. The check segments on a shift in
level and does not compare the size of the jump against the local slope. Treat low-sd
changepoints on a smoothly varying role with scepticism.

**Signature matching is verbose.** Eight candidates come out of three failure modes, most on
one-sample windows. Each one states its own weakness (onset mismatch, an unresolved
confounder, a competing mode) and they are routed to a separate "candidate diagnoses"
section. They are hypotheses to triage, not a list of faults.

**The additive confounder cannot be tested here.** `additive_ppm` never moves, so
`additive_change` can be neither confirmed nor excluded for any finding that lists it. The
calibration overlay says so. A confounder that cannot be tested has not been ruled out.

## Regenerating

`make_data.py` is seeded (`SEED = 20260916`), so the CSV is reproducible. If you change the
generator, rerun the analysis and update this table and `example-report.md` in the same
change. A planted fault with no documented expectation is not a test, and an expectation with
no planted fault is a claim about nothing.
