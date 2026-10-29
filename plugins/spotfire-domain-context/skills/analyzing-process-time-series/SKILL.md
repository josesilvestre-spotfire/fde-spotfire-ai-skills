---
name: analyzing-process-time-series
description: Analyzes process and pipeline historian time series with a tested Python engine (tssme) that conditions every comparison on operating regime, corrects significance for autocorrelation, detects historian artifacts (frozen tags, transmitter rails, zero-order-held lab values, join duplicates, snapshot rows), evaluates unit card invariants, excludes confounders and matches multi-tag failure signatures. Use when deciding whether a trend, step, anomaly or model residual in sensor data is real, when reviewing an analysis or a Spotfire app's results for statistical faults, or when writing unit cards, tag maps and calibration overlays for the engine. Runs from the command line or inside a Spotfire Python data function.
metadata:
  maturity: Proven on one machine
---

# Analyzing process time series

**Pending SME review:** the statistical rules and thresholds below have not yet been reviewed by an independent process or statistics SME.

This skill ships `tssme`, a time series engine for historian data, and the method behind it.
The engine carries no equipment knowledge of its own. Equipment knowledge arrives as a
**pack** of validated YAML unit cards (the `midstream-process-knowledge` skill ships one),
deployment facts arrive as a **profile**, and a named deliverable is a **bundle**.

Statistics without process knowledge produces confident nonsense; process knowledge without
statistics produces opinions. The engine needs both, so every analysis runs against a unit
card.

## When to use this skill

- A user asks whether a trend, step or anomaly in historian data is real.
- You review an analysis, a model residual or a Spotfire app's results and need to check the
  statistics (regime mixing, naive standard errors, artifacts read as process events).
- You need a unit card, tag map or calibration overlay for a new unit.
- A Spotfire data function must run this analysis on a table already in the analysis.

## Quick start

Run from `scripts/` (or put `scripts/` on `PYTHONPATH`). Dependencies: numpy, pandas and
pyyaml; scipy is optional.

```bash
python -m tssme packs                       # which knowledge packs were discovered
python -m tssme profiles                    # which deployments are configured
python -m tssme cards --validate            # validate every unit card
python -m tssme checks                      # the check battery, engine and pack checks
python -m tssme analyse --profile example-segment --out report.md
python -m tssme analyse --data export.csv --unit <unit-id> --tagmap tagmap.yaml \
       [--pack <pack-id>] [--calibration calibration.yaml] [--asset <id>] --out report.md
python tests/test_tssme.py                  # 43 regression tests, no Spotfire needed
```

From Python, including a data function where the table arrives as a DataFrame:

```python
from tssme import analyse, report_md
ctx, result = analyse(profile="example-segment")
ctx, result = analyse(frame, unit="<unit-id>", tagmap="tagmap.yaml",
                      calibration="calibration.yaml")
print(report_md(ctx, result))
```

`assets/examples/` holds a complete synthetic instance of all four layers with faults planted
in the data. [references/example-walkthrough.md](references/example-walkthrough.md) lists
which check must catch which fault; read it before you change any threshold.

## The four layers

| Layer | Holds | Changes |
|---|---|---|
| Engine (`scripts/tssme/`) | Method: prep, checks, statistics, reporting, the card schema | Rarely |
| Pack (`pack.yaml` + `units/*.yaml`) | Class knowledge: what a unit is, how it fails, what confounds each failure, domain vocabulary and domain checks | Slowly |
| Profile (`profile.yaml` + tag map + calibration) | Deployment facts: which column is which role, this asset's measured bands, where the data lives | Constantly |
| Bundle (`bundles/*.yaml`) | A named selection across the three, plus a brief stating what it analyses and refuses | Per release |

Each layer contains only what is true at that layer. A number measured on one asset over one
period is a profile fact, not class knowledge. `apply_calibration` refuses an overlay that
tries to add a role, an invariant, a failure mode or a confounder. A pack may extend only
`unit_class`, `persona` and `quantity`; the other enums are properties the engine branches
on. Details: [references/method.md](references/method.md).

## Input contract

A **wide frame**: a timestamp column or index, and N columns of sensors and conditions.
Column naming is not part of the contract. The tag map declares the match strategy
(`exact`, `suffix`, `prefix`, `regex`). A multi-asset frame declares an `asset_pattern`
with a named `(?P<asset>...)` group; a frame without one is a single-asset export. Join
duplicates (`Foo (2)`) are found by the counter suffix alone.

## Hard rules

Each rule exists because breaking it produced a wrong answer on real data.

1. **Data quality gates everything.** Checks run in category order: `data_quality`,
   `physical`, `relational`, `statistical`, `sme`. Most apparent anomalies in historian data
   are artifacts, and a finding built on a broken column is worse than no finding.
2. **Never compare a value to a baseline from a different operating regime.** Segment
   first, compare second. The plant's normal is a function of how hard it is running.
3. **Never use a naive standard error on a process series.** Use
   `n_eff = n(1 - r1) / (1 + r1)` and inflate the SE by `sqrt(n / n_eff)`. With `r1 = 0.9`
   the naive SEM overstates significance by a factor above 4.
4. **For trend detection, carry regime as a fixed effect; do not z-score within regime.**
   Z-scoring subtracts each band's mean and absorbs the drift whenever band membership
   correlates with time, which it usually does because throughput follows the season. Fit
   `y ~ intercept + slope*t + band dummies`.
5. **A check whose roles are missing is skipped and reported as skipped.** "No findings" and
   "could not run" are different answers.
6. **Distinguish confounders from differentials.** A confounder is a benign explanation
   (nothing is wrong). A differential is another fault (something else is wrong). Both must
   be excluded; they lead to different actions.
7. **A detector firing on more than 20 percent of samples is not a detector.** Audit existing
   event columns for base rate before trusting them. A rate-of-change flag thresholded at zero
   fires on about half of all samples by construction.
8. **Severity is not monotonic in excursion fraction for a descriptive band.** If a quarter
   of the record is outside the band, the card is wrong, not the plant. For a `normative`
   band (a spec or a model quality target) the excursion rate is the finding and the band is
   never widened.
9. **One physical event is one finding.** Steps propagate across correlated tags. Detect per
   role, cluster by time, report once with the corroborating tags named.
10. **Every numeric bound carries a source.** If it cannot be sourced, write
    `source: UNVERIFIED` so it surfaces in the report. Never invent a range.

## Gotchas

- **`NaN > NaN` is `False` in pandas, not NaN.** Derive evaluability from the operands,
  never from the comparison result, or every blanked row reads as a failed inequality.
- **A clean two-level step is capped at 2.0 sd in globally z-scored units**, because the
  series' own sd grows with the step. Measure a shift against pooled within-segment sd.
- **CUSUM detects late, and the lag scales inversely with shift size.** Tags responding to
  one event trip days apart. Cluster on a window at least as wide as the lag (default 10
  samples).
- **Clamped values are not measurements.** A pile-up at the exact min or max of a continuous
  signal is a transmitter rail or an upstream clamp. Exclude it from band excursions and
  never calibrate a band from it.
- **A `lab` role that changes every sample is mis-declared.** It is modelled or
  temperature-corrected, so it is not independent evidence for a lab-staleness confounder.
- **Route reports on `Finding.kind`, not severity.** `defect`, `candidate`, `verified`,
  `not_evaluated`. A candidate downgraded to info is still a candidate, and an invariant
  that could not be evaluated is the opposite of a verification.

## Reading a report

| Section | `kind` | Meaning |
|---|---|---|
| Findings | `defect` | Something is wrong with the data, the card or the unit |
| Candidate diagnoses | `candidate` | A signature match; a hypothesis with its confounder status |
| Not evaluated | `not_evaluated` | A coverage gap, never reassurance |
| Verified as healthy | `verified` | Positively checked: an identity holds, a power law matches |

"Unverified card assumptions" lists every bound marked `UNVERIFIED`. "Uncalibrated bands"
lists descriptive bands not measured on this asset. Read both before acting on a finding.

## Reviewing someone else's analysis

Use the same rules when an analysis or an app result did not come from the engine:

1. Were artifacts excluded first: frozen tags, rails, held lab values, duplicates, snapshot
   rows, quality codes coerced to numbers? See
   [references/historian-artifacts.md](references/historian-artifacts.md).
2. Was any comparison made across operating regimes (rate, pumps running, mode, season)?
3. Does any significance claim use a naive standard error on autocorrelated data?
4. Was a trend computed after z-scoring within regime?
5. Is a single-tag threshold being read as a diagnosis? A diagnosis needs a multi-role
   signature, an onset that fits, and its confounders excluded.
6. Does an event flag fire on more than 20 percent of samples?
7. Is a modelled value used as independent evidence?

[references/detector-matrix.md](references/detector-matrix.md) maps each question to the
method that answers it and the way that method misleads.

## Spotfire

The engine needs only numpy, pandas and pyyaml, so it can run inside a Spotfire Python data
function. The Python bundled with Spotfire Analyst 15.0 was observed to have no scipy; the
engine falls back to exact NumPy implementations. Running it inside Spotfire is **Not yet
tested**. Wrapper code and package notes:
[references/spotfire-data-function.md](references/spotfire-data-function.md).

## Status

The engine and its 43 regression tests run offline (Python 3.14, numpy 2.5, pandas 3.0,
with and without scipy). The rules were built against real historian exports; the shipped
example is synthetic. Nothing here has run inside Spotfire.

## References

- [references/method.md](references/method.md): architecture, pipeline order, the two
  contracts, the defect log behind each rule, known limitations.
- [references/authoring-layers.md](references/authoring-layers.md): writing packs, unit
  cards, profiles, tag maps, calibration overlays, bundles and checks; the end-to-end
  workflow for a new unit.
- [references/detector-matrix.md](references/detector-matrix.md): which method answers which
  question, and how each one misleads.
- [references/historian-artifacts.md](references/historian-artifacts.md): what historians do
  to data and what each artifact fakes.
- [references/literature.md](references/literature.md): citations behind every rule, with
  verification status.
- [references/example-walkthrough.md](references/example-walkthrough.md): the synthetic
  example, its planted faults and expected detections.
- [references/spotfire-data-function.md](references/spotfire-data-function.md): running the
  engine in a Spotfire data function.
